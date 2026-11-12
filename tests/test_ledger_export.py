"""M5-T7: export/import carries grants, revocations and access events and checks the hash chain (R8);
the ledger code makes no network calls (R9)."""
import ast
import datetime
import json
import socket
from pathlib import Path

import pytest
from django.db import connection

from core.models import Contributor
from core.services.export import LEDGER_MODELS, ImportError_, export_lines, import_lines
from ledger import service, statement
from ledger.models import AccessEvent, Grant, Revocation
from ledger.verify import verify
from tests.test_export import snapshot_state, wipe
from tests.test_export import seed as seed_records

ROOT = Path(__file__).resolve().parent.parent
UTC = datetime.timezone.utc
T = datetime.datetime(2026, 11, 12, 15, 0, tzinfo=UTC)
H = datetime.timedelta(hours=1)


def seed_ledger(m):
    probes = service.grant(m, "probes", "self-analysis", "weekly review", now=T)
    service.grant(m, "training", "sim-research-partner", "volume study", end=T + 48 * H, now=T)
    service.simulated_read(m, "self-analysis", "probes", now=T + H)
    service.simulated_read(m, "sim-research-partner", "training", now=T + 2 * H)
    service.revoke(m, probes.cid, reason="done", now=T + 3 * H)
    service.simulated_read(m, "sim-research-partner", "training", now=T + 4 * H)


@pytest.fixture
def mike(db):
    m = Contributor.objects.get(handle="mike")
    seed_records(m)
    seed_ledger(m)
    return m


def ledger_state():
    return {m.record_kind: sorted(m.objects.values_list("cid", flat=True)) for m in LEDGER_MODELS}


def wipe_all():
    wipe()
    with connection.cursor() as cur:  # row triggers refuse DELETE; TRUNCATE is the owner's tool
        cur.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cur.execute("TRUNCATE ledger_grant, ledger_revocation, ledger_accessevent")


def test_export_contains_the_ledger_in_order(mike):
    lines = [json.loads(line) for line in export_lines(mike)]
    kinds = [x["kind"] for x in lines if x.get("kind") in ("grant", "revocation", "access_event")]
    assert kinds == ["grant", "grant", "access_event", "access_event", "revocation", "access_event"]
    events = [x for x in lines if x.get("kind") == "access_event"]
    assert [e["fields"]["seq"] for e in events] == [1, 2, 3]
    assert events[0]["fields"]["prev_hash"] == "0" * 64


def test_round_trip_keeps_every_cid_and_the_chain(mike):
    before, ledger_before = snapshot_state(), ledger_state()
    stmt_before = statement.build(mike, "2026-11")
    lines = list(export_lines(mike))
    wipe_all()
    assert ledger_state() != ledger_before
    counts = import_lines(lines)
    assert counts["records"] == 14 + 6
    assert snapshot_state() == before and ledger_state() == ledger_before
    assert verify(mike) == ([], {"grants": 2, "revocations": 1, "events": 3, "records": 5})
    assert statement.build(mike, "2026-11")["cid"] == stmt_before["cid"]


def _resign(item):
    """Recompute a tampered line's CID, so only the chain (not the line check) can catch it."""
    from nymbus.provenance import canonical_bytes, compute_cid
    item["cid"] = compute_cid(canonical_bytes(item["kind"], item["contributor"], item["fields"]))
    return item


@pytest.mark.parametrize("change,match", [
    (lambda e: e["fields"].update(prev_hash="a" * 64), r"line \d+: Must be the SHA-256 of the previous event"),
    (lambda e: e["fields"].update(seq=5), r"line \d+: Must be 2, the next in the chain"),
])
def test_import_refuses_a_broken_chain(mike, change, match):
    items = [json.loads(line) for line in export_lines(mike)]
    second = [i for i in items if i.get("kind") == "access_event"][1]
    change(second)
    _resign(second)
    wipe_all()
    with pytest.raises(ImportError_, match=match):
        import_lines([json.dumps(i) for i in items])
    assert not AccessEvent.objects.exists() and not Grant.objects.exists()  # rolled back


def test_import_refuses_a_dropped_event(mike):
    items = [json.loads(line) for line in export_lines(mike)]
    first = next(i for i in items if i.get("kind") == "access_event")
    items.remove(first)
    wipe_all()
    with pytest.raises(ImportError_, match="the next in the chain"):
        import_lines([json.dumps(i) for i in items])


def test_import_refuses_a_read_after_its_revocation(mike):
    """Moving a revocation line before a read it should have stopped is caught by the grant check."""
    items = [json.loads(line) for line in export_lines(mike)]
    rev = next(i for i in items if i.get("kind") == "revocation")
    rev["fields"]["at"] = (T + H / 2).isoformat()
    _resign(rev)
    items.remove(rev)
    items.insert(next(n for n, i in enumerate(items) if i.get("kind") == "access_event"), rev)
    wipe_all()
    with pytest.raises(ImportError_, match="not active at the time of the read"):
        import_lines([json.dumps(i) for i in items])


def test_import_refuses_a_backdated_revocation_left_in_place(mike):
    """Review fix: the revocation stays after the read in the file but is dated before it; each line
    passes on its own, only the full verification after replay sees the inactive grant."""
    items = [json.loads(line) for line in export_lines(mike)]
    rev = next(i for i in items if i.get("kind") == "revocation")
    rev["fields"]["at"] = (T + H / 2).isoformat()
    _resign(rev)
    wipe_all()
    with pytest.raises(ImportError_, match="ledger does not verify: .*not active"):
        import_lines([json.dumps(i) for i in items])
    assert not Grant.objects.exists()


@pytest.mark.parametrize("bad_cid", ["bafkreimissingrecord", "work"])
def test_import_refuses_reads_of_missing_or_wrong_category_records(mike, bad_cid):
    items = [json.loads(line) for line in export_lines(mike)]
    if bad_cid == "work":  # a real record, but not in the event's category
        bad_cid = next(i["cid"] for i in items if i.get("kind") == "work_block")
    events = [i for i in items if i.get("kind") == "access_event"]
    events[-1]["fields"]["record_cids"] = events[-1]["fields"]["record_cids"][:-1] + [bad_cid]
    _resign(events[-1])
    wipe_all()
    with pytest.raises(ImportError_, match="ledger does not verify: .*(does not exist|is not in category)"):
        import_lines([json.dumps(i) for i in items])


# --- R9: no network ------------------------------------------------------------------------

NETWORK_MODULES = {"socket", "ssl", "http", "urllib", "urllib3", "requests", "httpx", "aiohttp", "smtplib", "ftplib",
                   "telnetlib", "xmlrpc", "websocket", "websockets", "subprocess", "asyncio"}
LEDGER_SOURCES = sorted((ROOT / "ledger").rglob("*.py")) + [ROOT / "nymbus" / "ledger.py", ROOT / "ui" / "ledger_views.py"]


def test_ledger_sources_import_no_network_module():
    assert len(LEDGER_SOURCES) >= 8
    for path in LEDGER_SOURCES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert name.split(".")[0] not in NETWORK_MODULES, f"{path.relative_to(ROOT)} imports {name}"


@pytest.fixture
def no_network(monkeypatch):
    calls = []

    def refuse(*args, **kwargs):
        calls.append(args)
        raise AssertionError(f"outbound network call: {args!r}")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    return calls


def test_no_outbound_network_call_across_the_ledger(db, no_network, client):
    from django.contrib.auth import get_user_model
    from django.core.management import call_command
    from io import StringIO

    m = Contributor.objects.get(handle="mike")
    seed_records(m)
    seed_ledger(m)
    assert verify(m)[0] == []
    statement.build(m, "2026-11")
    list(statement.jsonl(m, statement.build(m, "2026-11")))
    call_command("verify_ledger", stdout=StringIO())
    lines = list(export_lines(m))
    wipe_all()
    import_lines(lines)
    client.force_login(get_user_model().objects.create_user("owner", password="a-long-test-password"))
    assert client.get("/permissions/").status_code == 200
    assert client.get("/statement/?month=2026-11").status_code == 200
    client.post("/permissions/", {"category": "work", "work-recipient": "self-analysis", "work-purpose": "focus"})
    g = Grant.objects.get(category="work")
    service.simulated_read(m, "self-analysis", "work")
    client.post(f"/permissions/revoke/{g.cid}/", {"reason": ""})
    assert Revocation.objects.count() == 2
    assert no_network == []
