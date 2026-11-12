"""M5-T4: verify_ledger recomputes the chain and every CID; any break fails loudly (R4, R10)."""
import datetime
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection

from core.models import Contributor
from ledger import service
from ledger.models import AccessEvent
from nymbus import ledger
from tests.test_export import seed

UTC = datetime.timezone.utc
T = datetime.datetime(2026, 11, 12, 15, 0, tzinfo=UTC)
H = datetime.timedelta(hours=1)


@pytest.fixture
def mike(db):
    m = Contributor.objects.get(handle="mike")
    seed(m)
    probes = service.grant(m, "probes", "self-analysis", "review", now=T)
    service.grant(m, "training", "sim-research-partner", "volume study", now=T)
    for i in range(1, 4):
        service.simulated_read(m, "self-analysis", "probes", now=T + i * H)
    service.simulated_read(m, "sim-research-partner", "training", now=T + 4 * H)
    service.revoke(m, probes.cid, now=T + 5 * H)
    return m


def tamper(sql, *params):
    """Edit ledger rows as an attacker with table-owner rights would (the triggers are switched off)."""
    with connection.cursor() as cur:
        cur.execute("SET CONSTRAINTS ALL IMMEDIATE")  # flush deferred FK checks so ALTER TABLE is allowed
        for t in ("ledger_grant", "ledger_revocation", "ledger_accessevent"):
            cur.execute(f"ALTER TABLE {t} DISABLE TRIGGER {t}_append_only")
        cur.execute(sql, params)
        for t in ("ledger_grant", "ledger_revocation", "ledger_accessevent"):
            cur.execute(f"ALTER TABLE {t} ENABLE TRIGGER {t}_append_only")


def run():
    out = StringIO()
    call_command("verify_ledger", stdout=out)
    return out.getvalue()


def test_intact_ledger_verifies(mike):
    assert run().strip() == ("Ledger OK: 2 grants, 1 revocations, 4 access events; hash chain intact; "
                             "5 record CIDs recomputed.")


def test_pure_chain_check():
    a = b'{"a":1}'
    good = [{"seq": 1, "prev_hash": ledger.GENESIS, "canonical": a},
            {"seq": 2, "prev_hash": ledger.digest(a), "canonical": b"x"}]
    assert ledger.check_chain(good) == []
    assert "prev_hash does not match" in ledger.check_chain([good[0], {**good[1], "prev_hash": "0" * 64}])[0]
    assert "expected sequence number 1" in ledger.check_chain(good[1:])[0]


@pytest.mark.parametrize("sql,expect", [
    ("UPDATE ledger_accessevent SET units = 99 WHERE seq = 2", ["access_event", "CID does not match",
                                                                 "event 3: prev_hash does not match", "units 99"]),
    ("UPDATE ledger_accessevent SET record_cids = '[]'::jsonb WHERE seq = 1", ["event 2: prev_hash does not match"]),
    ("DELETE FROM ledger_accessevent WHERE seq = 2", ["expected sequence number 2"]),
    ("UPDATE ledger_accessevent SET prev_hash = repeat('a', 64) WHERE seq = 3", ["event 3: prev_hash does not match"]),
    ("UPDATE ledger_grant SET purpose = 'resale' WHERE category = 'probes'", ["grant", "CID does not match",
                                                                             "purpose differs from its grant"]),
    ("DELETE FROM ledger_revocation", []),  # a removed revocation leaves a consistent but shorter history...
])
def test_tampering_is_detected(mike, sql, expect):
    tamper(sql)
    if not expect:
        assert "Ledger OK" in run()  # ...which only the export and backups can show (documented limit)
        return
    with pytest.raises(CommandError) as exc:
        run()
    text = str(exc.value)
    assert text.startswith("Ledger verification FAILED")
    for fragment in expect:
        assert fragment in text, (fragment, text)


def test_a_changed_record_that_was_read_is_detected(mike):
    read = AccessEvent.objects.get(seq=1).record_cids[0]
    with connection.cursor() as cur:  # core tables have no trigger: the record CID check catches it
        cur.execute("UPDATE core_probesession SET accuracy_pct = 99.9 WHERE cid = %s", [read])
    with pytest.raises(CommandError, match=f"record {read} no longer matches its CID"):
        run()


def test_unknown_contributor(db):
    with pytest.raises(CommandError, match="Unknown contributor"):
        call_command("verify_ledger", "--contributor", "nobody", stdout=StringIO())
