"""M5-T2: Grant, Revocation, AccessEvent rules and immutability (R2, R3, R4, R10)."""
import datetime

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, connection, transaction

from core.models import Contributor, ImmutableRecordError
from ledger.models import AccessEvent, Grant, Revocation
from nymbus import ledger

UTC = datetime.timezone.utc
T = datetime.datetime(2026, 11, 12, 15, 0, tzinfo=UTC)
H = datetime.timedelta(hours=1)


@pytest.fixture
def mike(db):
    return Contributor.objects.get(handle="mike")


def make_grant(mike, **kw):
    g = Grant(contributor=mike, **{"category": "probes", "recipient": "self-analysis", "purpose": "weekly review",
                                   "start": T, **kw})
    g.save()
    return g


def event_for(grant, at, cids=(), **kw):
    """An unsaved event that continues the chain (the service does this under a lock)."""
    last = AccessEvent.objects.filter(contributor=grant.contributor).order_by("-seq").first()
    fields = {"seq": last.seq + 1 if last else 1,
              "prev_hash": ledger.digest(last.canonical()) if last else ledger.GENESIS,
              "at": at, "grant_cid": grant.cid, "recipient": grant.recipient, "category": grant.category,
              "purpose": grant.purpose, "record_cids": list(cids), "units": ledger.units_for(cids)}
    fields.update(kw)
    return AccessEvent(contributor=grant.contributor, **fields)


def test_grant_is_cid_addressed_and_needs_a_purpose(mike):
    g = make_grant(mike, end=T + 24 * H)
    assert g.cid.startswith("b") and Grant.objects.get().cid == g.cid
    with pytest.raises(ValidationError, match="purpose"):
        make_grant(mike, purpose="   ")
    with pytest.raises(ValidationError, match="end must be after start"):
        make_grant(mike, purpose="other", end=T)
    with pytest.raises(ValidationError):
        make_grant(mike, purpose="other", recipient="a-real-company")
    with pytest.raises(ValidationError):
        make_grant(mike, purpose="other", category="Not A Slug")


def test_grant_activity_window_and_revocation(mike):
    g = make_grant(mike, end=T + 24 * H)
    assert not g.is_active(T - H) and g.is_active(T) and g.is_active(T + 23 * H) and not g.is_active(T + 24 * H)
    Revocation(contributor=mike, grant_cid=g.cid, at=T + 2 * H).save()
    assert g.is_active(T + H) and not g.is_active(T + 2 * H)
    assert Grant.objects.count() == 1  # the grant is kept, superseded by the revocation


def test_revocation_rules(mike):
    g = make_grant(mike)
    with pytest.raises(ValidationError, match="grant of the same contributor"):
        Revocation(contributor=mike, grant_cid="bafkreinotagrant", at=T).save()
    other = Contributor.objects.create(handle="someone")
    with pytest.raises(ValidationError, match="grant of the same contributor"):
        Revocation(contributor=other, grant_cid=g.cid, at=T).save()
    Revocation(contributor=mike, grant_cid=g.cid, at=T + H).save()
    with pytest.raises(ValidationError, match="already revoked"):
        Revocation(contributor=mike, grant_cid=g.cid, at=T + 2 * H, reason="again").save()


def test_access_events_chain_and_match_their_grant(mike):
    g = make_grant(mike)
    first = event_for(g, T + H, ["bafkreia", "bafkreib"])
    first.save()
    assert first.seq == 1 and first.prev_hash == ledger.GENESIS and first.units == 2
    second = event_for(g, T + 2 * H)
    second.save()
    assert second.prev_hash == ledger.digest(first.canonical())
    for bad, match in [({"units": 5}, "units"), ({"recipient": "sim-research-partner"}, "recipient"),
                       ({"purpose": "something else"}, "purpose"), ({"category": "work"}, "category"),
                       ({"seq": 7}, "next in the chain"), ({"prev_hash": "f" * 64}, "previous event"),
                       ({"record_cids": ["x", "x"], "units": 2}, "listed twice"),
                       ({"grant_cid": "bafkreinope"}, "grant of the same contributor")]:
        with pytest.raises(ValidationError, match=match):
            event_for(g, T + 3 * H, **bad).save()
    with pytest.raises(ValidationError, match="not active"):
        event_for(g, T - H).save()
    assert AccessEvent.objects.count() == 2


def test_prev_hash_is_the_digest_inside_the_previous_cid(mike):
    """The chain uses the CID's own SHA-256, not a second identifier."""
    import base64
    g = make_grant(mike)
    e = event_for(g, T + H)
    e.save()
    raw = base64.b32decode(e.cid[1:].upper() + "=" * (-len(e.cid[1:]) % 8))
    assert raw[4:].hex() == ledger.digest(e.canonical())


def test_ledger_rows_are_immutable_in_the_model_and_in_the_database(mike):
    g = make_grant(mike)
    e = event_for(g, T + H)
    e.save()
    r = Revocation(contributor=mike, grant_cid=g.cid, at=T + 2 * H)
    r.save()
    for obj, model in ((g, Grant), (e, AccessEvent), (r, Revocation)):
        with pytest.raises(ImmutableRecordError):
            obj.save()
        with pytest.raises(ImmutableRecordError):
            obj.delete()
        with pytest.raises(ImmutableRecordError):
            model.objects.all().delete()
        with pytest.raises(ImmutableRecordError):
            model.objects.update(created_at=T)
        for sql in (f'UPDATE "{model._meta.db_table}" SET created_at = now()',
                    f'DELETE FROM "{model._meta.db_table}"'):
            with pytest.raises(DatabaseError, match="append-only"):
                with transaction.atomic(), connection.cursor() as cur:
                    cur.execute(sql)
    assert (Grant.objects.count(), AccessEvent.objects.count(), Revocation.objects.count()) == (1, 1, 1)
