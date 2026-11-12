"""M5-T3: reads only through an active grant; refusals write nothing; revocation is immediate (R3, R5, R10)."""
import datetime
from io import StringIO

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError

from core.models import Contributor, ProbeSession, TrainingSession
from ledger import service
from ledger.models import AccessEvent, Grant, Revocation
from ledger.service import AccessRefused, simulated_read
from tests.test_export import seed

UTC = datetime.timezone.utc
T = datetime.datetime(2026, 11, 12, 15, 0, tzinfo=UTC)
H = datetime.timedelta(hours=1)


@pytest.fixture
def mike(db):
    m = Contributor.objects.get(handle="mike")
    seed(m)
    return m


def test_lifecycle_grant_read_revoke(mike):
    g = service.grant(mike, "probes", "self-analysis", "  weekly review  ", now=T)
    assert g.purpose == "weekly review" and g.start == T and g.end is None
    event, records = simulated_read(mike, "self-analysis", "probes", now=T + H)
    current = set(ProbeSession.objects.current().filter(contributor=mike).values_list("cid", flat=True))
    assert {r["cid"] for r in records} == current == set(event.record_cids) and len(current) == 2
    assert all(r["kind"] == "probe_session" and "accuracy_pct" in r["fields"] for r in records)
    assert (event.seq, event.grant_cid, event.purpose, event.units) == (1, g.cid, "weekly review", 2)
    r = service.revoke(mike, g.cid, reason="done", now=T + 2 * H)
    assert r.grant_cid == g.cid and Grant.objects.filter(cid=g.cid).exists()  # nothing deleted
    with pytest.raises(ValidationError, match="already revoked"):
        service.revoke(mike, g.cid, now=T + 3 * H)


def test_refused_without_a_grant_and_nothing_is_written(mike):
    with pytest.raises(AccessRefused, match="No active grant lets sim-research-partner read probes"):
        simulated_read(mike, "sim-research-partner", "probes", now=T)
    service.grant(mike, "probes", "self-analysis", "review", now=T)
    with pytest.raises(AccessRefused):  # another recipient's grant does not count
        simulated_read(mike, "sim-research-partner", "probes", now=T + H)
    with pytest.raises(AccessRefused):  # nor does a grant for another category
        simulated_read(mike, "self-analysis", "training", now=T + H)
    with pytest.raises(AccessRefused):  # nor a grant that has not started yet
        simulated_read(mike, "self-analysis", "probes", now=T - H)
    assert AccessEvent.objects.count() == 0


def test_expired_grant_is_refused(mike):
    service.grant(mike, "training", "sim-research-partner", "volume study", end=T + 24 * H, now=T)
    simulated_read(mike, "sim-research-partner", "training", now=T + 23 * H)
    with pytest.raises(AccessRefused):
        simulated_read(mike, "sim-research-partner", "training", now=T + 24 * H)
    assert AccessEvent.objects.count() == 1
    g = Grant.objects.get()
    with pytest.raises(ValidationError, match="already ended"):
        service.revoke(mike, g.cid, now=T + 25 * H)


def test_revocation_is_immediate_and_scoped_to_its_category(mike):
    probes = service.grant(mike, "probes", "sim-research-partner", "fatigue study", now=T)
    service.grant(mike, "training", "sim-research-partner", "volume study", now=T)
    old, _ = simulated_read(mike, "sim-research-partner", "probes", now=T + H)
    service.revoke(mike, probes.cid, now=T + 2 * H)
    with pytest.raises(AccessRefused):  # the very next read, at the same instant
        simulated_read(mike, "sim-research-partner", "probes", now=T + 2 * H)
    assert AccessEvent.objects.count() == 1  # the refusal wrote no event
    event, records = simulated_read(mike, "sim-research-partner", "training", now=T + 2 * H)
    assert event.seq == 2 and event.prev_hash != old.prev_hash
    assert len(records) == TrainingSession.objects.current().count() + 2  # one session, two sets
    kept = AccessEvent.objects.get(seq=1)  # old events stay readable
    assert kept.cid == old.cid and kept.category == "probes" and kept.record_cids == old.record_cids


def test_a_new_grant_after_revocation_works_again(mike):
    g = service.grant(mike, "probes", "self-analysis", "review", now=T)
    service.revoke(mike, g.cid, now=T + H)
    service.grant(mike, "probes", "self-analysis", "review", now=T + 2 * H)
    event, _ = simulated_read(mike, "self-analysis", "probes", now=T + 3 * H)
    assert event.grant_cid != g.cid and Revocation.objects.count() == 1


def test_grant_refuses_unknown_categories_and_duplicates(mike):
    with pytest.raises(ValidationError, match="Unknown data category"):
        service.grant(mike, "genome", "self-analysis", "x", now=T)
    service.grant(mike, "probes", "self-analysis", "review", now=T)
    with pytest.raises(ValidationError, match="already has a grant for this category"):
        service.grant(mike, "probes", "self-analysis", "review", now=T)
    with pytest.raises(ValidationError, match="No such grant"):
        service.revoke(mike, "bafkreinope", now=T)


def test_one_grant_in_force_per_recipient_and_category(mike):
    """Review fix: overlapping grants made a revoke silently incomplete (an older grant took over)."""
    first = service.grant(mike, "probes", "self-analysis", "weekly review", end=T + 48 * H, now=T)
    with pytest.raises(ValidationError, match="revoke it first"):
        service.grant(mike, "probes", "self-analysis", "fatigue study", now=T + H)
    service.grant(mike, "probes", "sim-research-partner", "fatigue study", now=T + H)  # another recipient: fine
    service.grant(mike, "training", "self-analysis", "volume", now=T + H)  # another category: fine
    service.revoke(mike, first.cid, now=T + 2 * H)
    with pytest.raises(AccessRefused):  # nothing else lets self-analysis read probes
        simulated_read(mike, "self-analysis", "probes", now=T + 2 * H)
    second = service.grant(mike, "probes", "self-analysis", "fatigue study", now=T + 3 * H)
    event, _ = simulated_read(mike, "self-analysis", "probes", now=T + 4 * H)
    assert event.grant_cid == second.cid and event.purpose == "fatigue study"
    # A grant that already ended does not block a new one either.
    ended = service.grant(mike, "work", "self-analysis", "focus", end=T + 5 * H, now=T + 4 * H)
    service.grant(mike, "work", "self-analysis", "focus again", now=T + 6 * H)
    assert ended.revocation() is None


def test_a_refused_read_is_logged(mike, caplog):
    with caplog.at_level("WARNING", logger="ledger"):
        with pytest.raises(AccessRefused):
            simulated_read(mike, "sim-research-partner", "probes", now=T)
    assert "refused read: probes -> sim-research-partner for mike" in caplog.text


def test_two_contributors_have_separate_chains(mike):
    other = Contributor.objects.create(handle="someone")
    service.grant(mike, "probes", "self-analysis", "review", now=T)
    service.grant(other, "probes", "self-analysis", "review", now=T)
    a, _ = simulated_read(mike, "self-analysis", "probes", now=T + H)
    b, _ = simulated_read(other, "self-analysis", "probes", now=T + H)
    c, _ = simulated_read(mike, "self-analysis", "probes", now=T + 2 * H)
    assert (a.seq, b.seq, c.seq) == (1, 1, 2)
    assert a.prev_hash == b.prev_hash == "0" * 64 and b.record_cids == []
    from ledger.verify import verify
    assert verify()[0] == []


def test_ledger_read_command(mike):
    with pytest.raises(CommandError, match="Refused: No active grant"):
        call_command("ledger_read", "--recipient", "self-analysis", "--category", "work", stdout=StringIO())
    service.grant(mike, "work", "self-analysis", "focus review")
    out = StringIO()
    call_command("ledger_read", "--recipient", "self-analysis", "--category", "work", stdout=out)
    assert "Read 2 work records for self-analysis (event #1," in out.getvalue()  # current block + reset
    assert "2 simulated credits." in out.getvalue()
