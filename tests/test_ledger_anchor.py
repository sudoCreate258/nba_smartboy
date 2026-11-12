"""M6-T2: the ledger head is anchored in backups; a removed tail or revocation is detected (R2)."""
import datetime
import json
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.urls import reverse

from backup.models import BackupRun
from core.models import Contributor
from ledger import service
from ledger.models import AccessEvent
from ledger.verify import compare_head, head, newest_anchor
from nymbus import ledger
from tests.test_export import seed
from tests.test_ledger_export import seed_ledger

T = datetime.datetime(2026, 11, 12, 15, 0, tzinfo=datetime.timezone.utc)


@pytest.fixture
def mike(db):
    m = Contributor.objects.get(handle="mike")
    seed(m)
    seed_ledger(m)
    return m


def anchor_now(mike, name="2026-11-12T070000Z"):
    """A published backup as the runner logs it (its manifest carries the heads)."""
    heads = {mike.handle: head(mike)}
    BackupRun.objects.create(started_at=T, trigger="manual", status="ok", set_name=name, published=True,
                             verified=True, manifest={"ledger_heads": heads})
    return heads


def owner_sql(*statements):
    """As a database owner who switches the ledger triggers off."""
    with connection.cursor() as cur:
        cur.execute("SET CONSTRAINTS ALL IMMEDIATE")
        for t in ("ledger_grant", "ledger_revocation", "ledger_accessevent"):
            cur.execute(f"ALTER TABLE {t} DISABLE TRIGGER {t}_append_only")
        for sql in statements:
            cur.execute(sql)
        for t in ("ledger_grant", "ledger_revocation", "ledger_accessevent"):
            cur.execute(f"ALTER TABLE {t} ENABLE TRIGGER {t}_append_only")


def run(*args):
    out = StringIO()
    call_command("verify_ledger", *args, stdout=out)
    return out.getvalue()


def test_head_is_count_and_hash_of_the_newest_event(mike):
    h = head(mike)
    last = AccessEvent.objects.get(seq=3)
    assert h == {"events": 3, "last_hash": ledger.digest(last.canonical()), "grants": 2, "revocations": 1}
    assert head(Contributor.objects.create(handle="empty"))["last_hash"] == "0" * 64


def test_no_anchor_then_matching_anchor(mike):
    assert newest_anchor() == (None, {})
    assert "no backup anchor yet" in run()
    anchor_now(mike)
    assert "head matches backup 2026-11-12T070000Z" in run()
    service.simulated_read(mike, "sim-research-partner", "training", now=T + 5 * datetime.timedelta(hours=1))
    assert "head matches" in run()  # a longer ledger that extends the anchored one is fine


@pytest.mark.parametrize("sql,expect", [
    ("DELETE FROM ledger_accessevent WHERE seq = 3", "shorter than in backup"),
    ("DELETE FROM ledger_revocation", "0 revocations, fewer than the 1 in backup"),
])
def test_a_removed_tail_or_revocation_is_detected(mike, sql, expect):
    anchor_now(mike)
    owner_sql(sql)
    with pytest.raises(CommandError, match=expect):
        run()


def test_a_rewritten_newest_event_is_detected(mike):
    anchor_now(mike)
    # Rewrite the newest event consistently (CID recomputed), so only the anchor can tell.
    e = AccessEvent.objects.get(seq=3)
    e.purpose = "rewritten"
    owner_sql(f"DELETE FROM ledger_accessevent WHERE seq = 3")
    problems = compare_head(mike, {"events": 3, "last_hash": ledger.digest(e.canonical()), "grants": 2,
                                   "revocations": 1})
    assert "shorter" in problems[0]
    live = {"events": 3, "last_hash": "f" * 64, "grants": 2, "revocations": 1}
    service.simulated_read(mike, "sim-research-partner", "training", now=T + 6 * datetime.timedelta(hours=1))
    assert "access event 3 differs" in compare_head(mike, live)[0]


def test_compare_with_a_manifest_kept_outside(mike, tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"ledger_heads": {"mike": head(mike)}}), encoding="utf-8")
    assert f"head matches manifest {path}" in run("--manifest", str(path))
    owner_sql("DELETE FROM ledger_accessevent WHERE seq = 3")
    with pytest.raises(CommandError, match="shorter than in manifest"):
        run("--manifest", str(path))
    old = tmp_path / "old.json"
    old.write_text(json.dumps({"record_counts": {}}), encoding="utf-8")
    with pytest.raises(CommandError, match="no ledger heads"):
        run("--manifest", str(old))


def test_statement_page_shows_the_head_and_the_anchor(client, mike):
    client.force_login(get_user_model().objects.create_user("owner", password="a-long-test-password"))
    html = client.get(reverse("ui:statement")).content.decode()
    assert "3 reads recorded, 2 grants, 1 revocation." in html and "No backup carries a ledger head yet" in html
    anchor_now(mike)
    html = client.get(reverse("ui:statement")).content.decode()
    assert "Matches the newest backup (2026-11-12T070000Z: 3 reads" in html
    owner_sql("DELETE FROM ledger_accessevent WHERE seq = 3")
    html = client.get(reverse("ui:statement")).content.decode()
    assert 'role="alert"' in html and "shorter than in the backup" in html


@pytest.mark.parametrize("bad", ["bad", {"events": 3}, {"events": -1, "last_hash": "0" * 64, "grants": 0, "revocations": 0},
                                 {"events": 3, "last_hash": "XYZ", "grants": 2, "revocations": 1},
                                 {"events": 0, "last_hash": "a" * 64, "grants": 0, "revocations": 0},
                                 {"events": True, "last_hash": "0" * 64, "grants": 0, "revocations": 0}])
def test_a_malformed_head_is_a_problem_not_a_match(mike, tmp_path, bad):
    """Review fix: a malformed anchor used to be read as 'matching'."""
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"ledger_heads": {"mike": bad}}), encoding="utf-8")
    with pytest.raises(CommandError, match="ledger head"):
        run("--manifest", str(path))