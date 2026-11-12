"""M6-T7: docs/PORTING.md carries test vectors that the code reproduces (R9)."""
import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from core.models import Contributor, DailySnapshot, ProbeSession, WeeklyCheck
from ledger.models import AccessEvent, Grant
from nymbus import ledger
from nymbus.provenance import canonical_bytes, compute_cid
from tools import porting_vectors as pv

ROOT = Path(__file__).resolve().parent.parent
UTC = datetime.timezone.utc


def test_porting_doc_carries_the_current_vectors():
    text = (ROOT / "docs" / "PORTING.md").read_text(encoding="utf-8")
    block = pv.START + text.split(pv.START, 1)[1].split(pv.END, 1)[0] + pv.END
    assert block == pv.markdown(), "run `python tools/porting_vectors.py --write`"


def test_the_vectors_are_self_consistent():
    records = pv.record_vectors()
    assert len(records) == 3 and len({r["cid"] for r in records}) == 3
    for r in records:
        assert compute_cid(r["canonical"].encode("utf-8")) == r["cid"]
    chain = pv.chain_vectors()
    events = chain["events"]
    assert ledger.check_chain([{"seq": e["fields"]["seq"], "prev_hash": e["fields"]["prev_hash"],
                                "canonical": e["canonical"].encode("utf-8")} for e in events]) == []
    assert chain["head"] == {"events": 3, "last_hash": events[-1]["sha256"]}
    assert events[0]["fields"]["prev_hash"] == "0" * 64 and events[1]["fields"]["prev_hash"] == events[0]["sha256"]


@pytest.fixture
def mike(db):
    return Contributor.objects.get(handle="mike")


def test_the_django_models_compute_the_same_cids(mike):
    """The vectors are what this implementation actually stores, not a parallel description."""
    snap = DailySnapshot(contributor=mike, date=datetime.date(2026, 11, 10), sleep_score=80,
                         wake_time=datetime.datetime(2026, 11, 10, 12, 0, tzinfo=UTC), sleep_duration_min=450,
                         resting_hr_sleep=52, hrv=61, spo2=Decimal("96.50"), source="manual")
    probe = ProbeSession(contributor=mike, started_at=datetime.datetime(2026, 11, 10, 13, 50, tzinfo=UTC),
                         kind="mini_puzzle", n_items=5, accuracy_pct="80", median_solve_s="12.5", blunders=1,
                         late_blunders=0, fast_blunders=1, move_time_cv="0.4", location="office")
    weekly = WeeklyCheck(contributor=mike, week_start=datetime.date(2026, 11, 9), instrument="OLBI", score="2.4",
                         scale_max="4")
    for record, vector in zip((snap, probe, weekly), pv.record_vectors()):
        record.save()
        assert record.cid == vector["cid"], record.record_kind

    grant = Grant(contributor=mike, category="probes", recipient="sim-research-partner", purpose="fatigue study",
                  start=datetime.datetime(2026, 11, 10, 14, 0, tzinfo=UTC))
    grant.save()
    chain = pv.chain_vectors()
    assert grant.cid == chain["grant"]["cid"]
    from ledger import service
    for e in chain["events"]:
        at = datetime.datetime.fromisoformat(e["fields"]["at"])
        if e["fields"]["record_cids"]:
            event, _ = service.simulated_read(mike, "sim-research-partner", "probes", now=at)
        else:  # the third vector reads an empty selection: build it as the service would
            last = AccessEvent.objects.filter(contributor=mike).order_by("-seq").first()
            event = AccessEvent(contributor=mike, seq=3, prev_hash=ledger.digest(last.canonical()), at=at,
                                grant_cid=grant.cid, recipient=grant.recipient, category="probes",
                                purpose=grant.purpose, record_cids=[], units=0)
            event.save()
        assert event.cid == e["cid"] and ledger.digest(event.canonical()) == e["sha256"]
    from ledger.verify import head
    assert {k: head(mike)[k] for k in ("events", "last_hash")} == chain["head"]
