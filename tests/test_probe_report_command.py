import json
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from core.models import Contributor, ProbeSession
from tests.test_probe_conditions import add_session, add_sleep, add_work, seed_baseline

DISCLAIMER = "Load gauge, not a medical assessment."


@pytest.fixture
def mike(db):
    return Contributor.objects.get(handle="mike")


def report(*args):
    out = StringIO()
    call_command("probe_report", *args, stdout=out)
    return out.getvalue()


def seed_red(mike):
    seed_baseline(mike)
    for i in (10, 11, 12):
        add_session(mike, i, acc=80 - 2.5, solve=10 + 1.3)
        add_sleep(mike, i, 60)
        add_work(mike, i, 8)


def test_text_report_for_a_red_flag(mike):
    seed_red(mike)
    out = report("--kind", "puzzle_set")
    assert "== puzzle_set ==" in out and "rapid_game" not in out
    assert "Baseline (default): 2026-10-01 to 2026-10-10, n=10" in out
    assert "accuracy_pct: mean 80.00" in out
    assert "accuracy_pct: 77.50 (z +1.19)" in out
    assert "Flag: RED: " in out and "sleep is falling" in out
    assert "Sleep: falling (" in out and "Work load: rising (" in out
    assert out.rstrip().endswith(DISCLAIMER)


def test_text_report_defaults_to_all_scored_kinds_and_handles_empty_kind(mike):
    seed_red(mike)
    out = report()
    assert "== puzzle_set ==" in out and "== rapid_game ==" in out and "== mini_puzzle ==" in out
    assert "insufficient baseline (0 of 10 sessions); no flags raised." in out
    assert "== module ==" not in out
    assert out.count(DISCLAIMER) == 1


def test_json_report(mike):
    seed_red(mike)
    data = json.loads(report("--json", "--kind", "puzzle_set"))
    assert data["contributor"] == "mike" and data["disclaimer"] == DISCLAIMER
    [item] = data["kinds"]
    assert item["kind"] == "puzzle_set" and item["flag"] == "red" and item["status"] == "ok"
    assert item["baseline"]["source"] == "default" and item["baseline"]["n"] == 10
    assert item["baseline"]["start"] == "2026-10-01" and item["baseline"]["end"] == "2026-10-10"
    assert item["baseline"]["stats"]["accuracy_pct"]["mean"] == pytest.approx(80.0)
    assert item["latest_z"]["accuracy_pct"] == pytest.approx(1.19, abs=0.01)
    assert item["latest_rolling_medians"]["accuracy_pct"] == pytest.approx(77.5)
    assert item["sleep"]["state"] is True and item["work"]["state"] is True
    assert item["skipped_metrics"] == {}


def test_json_all_kinds_has_both(mike):
    seed_red(mike)
    data = json.loads(report("--json"))
    assert [k["kind"] for k in data["kinds"]] == ["puzzle_set", "rapid_game", "mini_puzzle"]
    assert data["kinds"][1]["status"] == "insufficient_baseline" and data["kinds"][1]["flag"] == "none"


def test_text_report_with_no_flag_and_missing_context(mike):
    seed_baseline(mike, sleep=False, work=False)
    for i in (10, 11, 12):
        add_session(mike, i, acc=80, solve=10)
    out = report("--kind", "puzzle_set")
    assert "Flag: NONE" in out
    assert "Sleep: insufficient data (" in out and "Work load: insufficient data (" in out


def test_report_does_not_write_anything(mike):
    seed_red(mike)
    before = ProbeSession.objects.count()
    report()
    assert ProbeSession.objects.count() == before


def test_unknown_contributor_and_bad_kind(db):
    with pytest.raises(CommandError, match="Unknown contributor"):
        report("--contributor", "nobody")
    with pytest.raises(CommandError):
        report("--kind", "module")
