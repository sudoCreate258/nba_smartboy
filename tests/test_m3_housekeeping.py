"""M3-T0: carry-over from R0 and the M2 review (DECISIONS, "Planner answers to the M2 review")."""
import datetime
from io import StringIO

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.urls import reverse

from core.models import Contributor, ProbeBaseline, ProbeSession, Supersession, WorkBlock
from core.services.probe_report import _hours_in, baseline_window, kind_report, merge_intervals
from twin_metrics import probes

UTC = datetime.timezone.utc
T0 = datetime.datetime(2026, 11, 11, 9, 0, tzinfo=UTC)


@pytest.fixture
def mike(db):
    return Contributor.objects.get(handle="mike")


def at(day, hour=9):
    return datetime.datetime(2026, 9, 1, hour, 0, tzinfo=UTC) + datetime.timedelta(days=day)


def session(mike, day, acc=80.0, solve=10.0):
    p = ProbeSession(contributor=mike, started_at=at(day), kind="puzzle_set", accuracy_pct=acc, median_solve_s=solve)
    p.save()
    return p


def block(mike, start, minutes, **kw):
    kw.setdefault("task_type", "code")
    return WorkBlock(contributor=mike, start=start, end=start + datetime.timedelta(minutes=minutes), **kw)


# --- 42-day rule for the default baseline ---------------------------------

def test_default_baseline_within_42_days_is_used(mike):
    for d in [0, 5, 10, 15, 20, 25, 30, 35, 40, 42]:
        session(mike, d, acc=80 + (d % 3))
    w = baseline_window(mike, "puzzle_set")
    assert w["problem"] is None and len(w["baseline"]) == 10


def test_default_baseline_over_42_days_is_insufficient(mike):
    for d in [0, 5, 10, 15, 20, 25, 30, 35, 40, 43]:
        session(mike, d, acc=80 + (d % 3))
    for d in (44, 45, 46):
        session(mike, d, acc=60, solve=20)  # would be red with a usable baseline
    w = baseline_window(mike, "puzzle_set")
    assert "set a ProbeBaseline" in w["problem"] and "43 days" in w["problem"]
    r = kind_report(mike, "puzzle_set")
    assert r["status"] == "insufficient_baseline" and r["level"] == "none"
    assert r["reasons"] == [w["problem"]]


def test_configured_baseline_is_not_limited_to_42_days(mike):
    for d in range(0, 100, 10):
        session(mike, d, acc=80 + (d % 3))
    ProbeBaseline.objects.create(contributor=mike, kind="puzzle_set", start=at(0), end=at(95))
    w = baseline_window(mike, "puzzle_set")
    assert w["problem"] is None and len(w["baseline"]) == 10


def test_report_text_explains_spread_baseline(mike):
    for d in range(0, 100, 10):
        session(mike, d)
    out = StringIO()
    call_command("probe_report", "--kind", "puzzle_set", stdout=out)
    assert "Baseline: insufficient baseline: set a ProbeBaseline" in out.getvalue()
    assert "no flags raised." in out.getvalue()


# --- "ratio" label ----------------------------------------------------------

def test_move_time_cv_admin_column_is_labelled_ratio(admin_client, mike):
    ProbeSession(contributor=mike, started_at=T0, kind="rapid_game", move_time_cv="0.45").save()
    page = admin_client.get(reverse("admin:core_probesession_changelist"))
    assert page.status_code == 200
    assert b"move time cv (ratio)" in page.content.lower() and b"0.45" in page.content


# --- overlapping work blocks ------------------------------------------------

def test_overlapping_block_is_rejected(mike):
    block(mike, T0, 60).save()
    with pytest.raises(ValidationError, match="Overlaps work block"):
        block(mike, T0 + datetime.timedelta(minutes=30), 60).save()
    assert WorkBlock.objects.count() == 1


def test_touching_blocks_are_fine(mike):
    block(mike, T0, 60).save()
    block(mike, T0 + datetime.timedelta(minutes=60), 60).save()
    block(mike, T0 - datetime.timedelta(minutes=30), 30).save()
    assert WorkBlock.objects.count() == 3


def test_overlap_is_per_contributor_and_ignores_superseded(mike):
    sam = Contributor.objects.create(handle="sam")
    old = block(mike, T0, 60)
    old.save()
    block(sam, T0, 60).save()  # other contributor: fine
    moved = block(mike, T0 + datetime.timedelta(hours=3), 60)
    moved.save()
    Supersession.record(old, moved)
    block(mike, T0 + datetime.timedelta(minutes=15), 30).save()  # old is no longer current
    assert WorkBlock.objects.current().filter(contributor=mike).count() == 2


def test_correction_may_overlap_the_block_it_replaces(mike):
    old = block(mike, T0, 60)
    old.save()
    fix = block(mike, T0, 75, task_type="study")
    fix.replaces_cid = old.cid
    fix.save()
    Supersession.record(old, fix)
    assert list(WorkBlock.objects.current()) == [fix]


def test_identical_block_is_a_duplicate_not_an_overlap(mike):
    block(mike, T0, 60).save()
    assert not block(mike, T0, 60).overlapping().exists()


def test_admin_rejects_overlapping_block(admin_client, mike):
    block(mike, T0, 60).save()  # 04:00-05:00 New York
    post = {"contributor": mike.pk, "start_0": "2026-11-11", "start_1": "04:30:00",
            "end_0": "2026-11-11", "end_1": "06:00:00", "task_type": "code", "notes": ""}
    resp = admin_client.post(reverse("admin:core_workblock_add"), post)
    assert resp.status_code == 200 and b"Overlaps work block" in resp.content
    assert b"2026-11-11 04:00-05:00 America/New_York" in resp.content  # local time, not UTC
    assert WorkBlock.objects.count() == 1


def test_merge_intervals():
    assert merge_intervals([(5, 6), (1, 3), (2, 4), (4, 4.5)]) == [(1, 4.5), (5, 6)]
    assert merge_intervals([]) == []


def test_hours_sum_counts_overlapping_blocks_once():
    # Overlaps can exist in data stored before the rule; sums must not double-count.
    a = WorkBlock(start=T0, end=T0 + datetime.timedelta(hours=2))
    b = WorkBlock(start=T0 + datetime.timedelta(hours=1), end=T0 + datetime.timedelta(hours=3))
    assert _hours_in([a, b], T0, T0 + datetime.timedelta(days=1)) == pytest.approx(3.0)
    assert _hours_in([a, b], T0 + datetime.timedelta(hours=2), T0 + datetime.timedelta(days=1)) == pytest.approx(1.0)


# --- rolling medians with fewer than 3 sessions (kept as is) ---------------

def test_early_rolling_medians_use_what_exists_and_flags_need_three():
    """The first post-baseline medians use 1 and 2 sessions (design: "use what exists").

    A single bad first session yields a high z on its own, but no flag is raised
    until 3 scored sessions exist, and then all 3 rows must qualify.
    """
    metrics = probes.METRICS["puzzle_set"]
    baseline = [{"accuracy_pct": 80 + (-1) ** i, "median_solve_s": 10 + (-1) ** i} for i in range(10)]
    stats = probes.baseline_stats(baseline, metrics)
    bad = {"accuracy_pct": 70, "median_solve_s": 15}
    good = {"accuracy_pct": 80, "median_solve_s": 10}
    medians = probes.rolling_medians([bad, good], metrics)
    assert medians[0] == {"accuracy_pct": 70, "median_solve_s": 15}  # one session
    assert medians[1] == {"accuracy_pct": 75, "median_solve_s": 12.5}  # two sessions
    z = probes.rolling_z([bad, good], stats, metrics)
    assert probes.flag(z)[0] == "none"
    z3 = probes.rolling_z([bad, good, good], stats, metrics)
    assert probes.flag(z3)[0] == "none"  # the median of 3 is back to normal
