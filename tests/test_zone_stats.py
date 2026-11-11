"""M3-T5 / R10: zone, reset and discomfort statistics on synthetic data (no database)."""
import datetime
import zoneinfo

import pytest

from twin_metrics import zone

NY = "America/New_York"
NYZ = zoneinfo.ZoneInfo(NY)
UTC = datetime.timezone.utc
MON = datetime.date(2026, 10, 5)  # a Monday


def local(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=NYZ)


def blk(start, minutes, absorption=4, interruptions=0, **kw):
    return {"start": start, "end": start + datetime.timedelta(minutes=minutes),
            "absorption": absorption, "interruptions": interruptions, **kw}


# --- high-focus classification ---------------------------------------------

@pytest.mark.parametrize(
    "absorption,interruptions,expected",
    [(4, 1, True), (5, 0, True), (3, 0, False), (4, 2, False), (None, 0, False), (5, None, False), (None, None, False)],
)
def test_high_focus_classification(absorption, interruptions, expected):
    assert zone.is_high_focus({"absorption": absorption, "interruptions": interruptions}) is expected


# --- weekly bucketing -------------------------------------------------------

def test_week_of_is_local_monday():
    # Sunday 23:30 New York is Monday 03:30 UTC: still the previous local week.
    sunday_late = local(MON + datetime.timedelta(days=6), 23, 30)
    assert sunday_late.astimezone(UTC).date().weekday() == 0
    assert zone.week_of(sunday_late, NY) == MON
    assert zone.week_of(local(MON + datetime.timedelta(days=7), 0, 0), NY) == MON + datetime.timedelta(days=7)


def test_block_crossing_midnight_and_week_counts_in_week_of_start():
    start = local(MON + datetime.timedelta(days=6), 23, 0)  # Sunday 23:00 -> Monday 01:00
    weeks = zone.weekly_zone([blk(start, 120)], NY)
    assert list(weeks) == [MON]
    assert weeks[MON]["total_hours"] == pytest.approx(2.0)


def test_dst_week_buckets_and_durations():
    # US DST ends Sunday 2026-11-01 02:00 -> 01:00. That Sunday belongs to the week of Monday 2026-10-26.
    dst_monday = datetime.date(2026, 10, 26)
    before = datetime.datetime(2026, 11, 1, 0, 30, tzinfo=NYZ)  # EDT
    weeks = zone.weekly_zone([blk(before, 180)], NY)  # 00:30 EDT -> 02:30 EST is 3 real hours
    assert list(weeks) == [dst_monday]
    assert weeks[dst_monday]["total_hours"] == pytest.approx(3.0)
    after_change = datetime.datetime(2026, 11, 2, 9, 0, tzinfo=NYZ)
    assert zone.week_of(after_change, NY) == datetime.date(2026, 11, 2)


def test_weekly_summary_and_breakdowns():
    blocks = [
        blk(local(MON, 9), 50, location="remote", posture="sit", planned_length_min=50),
        blk(local(MON, 10), 25, absorption=2, location="remote", posture="stand", planned_length_min=25),
        blk(local(MON, 13), 40, interruptions=None, location="office"),
    ]
    w = zone.weekly_zone(blocks, NY)[MON]
    assert w["blocks"] == 3 and w["total_hours"] == pytest.approx(115 / 60)
    assert w["high_focus_minutes"] == 50 and w["focus_share"] == pytest.approx(50 / 115)
    assert w["by"]["location"]["remote"]["focus_share"] == pytest.approx(50 / 75)
    assert w["by"]["location"]["office"]["high_focus_minutes"] == 0
    assert w["by"]["posture"]["unknown"]["blocks"] == 1
    assert set(w["by"]["planned_length_min"]) == {25, 50, "unknown"}


# --- theta band -------------------------------------------------------------

def test_theta_median_and_iqr():
    t = zone.theta([20, 30, 40, 50, 60])
    assert (t["n"], t["median"], t["q1"], t["q3"], t["iqr"]) == (5, 40, 30, 50, 20)
    assert zone.theta([45]) == {"n": 1, "median": 45, "q1": 45, "q3": 45, "iqr": 0}
    assert zone.theta([])["median"] is None


def test_theta_uses_only_high_focus_blocks():
    blocks = [blk(local(MON, 9), 30), blk(local(MON, 10), 90), blk(local(MON, 12), 200, absorption=1)]
    t = zone.weekly_zone(blocks, NY)[MON]["theta"]
    assert t["n"] == 2 and t["median"] == 60


# --- zone amber -------------------------------------------------------------

def weeks_with(shares_hours):
    """Synthetic weeks: each entry (focus share, total hours), oldest first, consecutive weeks."""
    blocks = []
    for i, (share, hours) in enumerate(shares_hours):
        day = MON + datetime.timedelta(weeks=i)
        total = hours * 60
        focus = round(total * share)
        if focus:
            blocks.append(blk(local(day, 8), focus))
        if total - focus:
            blocks.append(blk(local(day, 8) + datetime.timedelta(minutes=focus), total - focus, absorption=1))
    return zone.weekly_zone(blocks, NY)


def test_zone_amber_true_when_share_falls_and_hours_steady():
    weeks = weeks_with([(0.6, 20), (0.6, 20), (0.6, 20), (0.45, 21)])
    r = zone.zone_amber(weeks, MON + datetime.timedelta(weeks=3))
    assert r["state"] is True and "45%" in r["detail"]


@pytest.mark.parametrize(
    "last",
    [(0.5, 20),  # share fell only 17%
     (0.45, 25),  # hours up 25%: working more, not "effort without flow"
     (0.6, 20)],
)
def test_zone_amber_false(last):
    weeks = weeks_with([(0.6, 20), (0.6, 20), (0.6, 20), last])
    assert zone.zone_amber(weeks, MON + datetime.timedelta(weeks=3))["state"] is False


def test_zone_amber_insufficient_with_fewer_than_three_prior_weeks():
    weeks = weeks_with([(0.6, 20), (0.6, 20), (0.4, 20)])
    r = zone.zone_amber(weeks, MON + datetime.timedelta(weeks=2))
    assert r["state"] is None and "2 of 3 prior weeks" in r["detail"]


def test_zone_amber_gap_week_is_missing_data_not_rest():
    weeks = weeks_with([(0.6, 20), (0.6, 20), (0.6, 20), (0.4, 20)])
    del weeks[MON + datetime.timedelta(weeks=1)]
    assert zone.zone_amber(weeks, MON + datetime.timedelta(weeks=3))["state"] is None


def test_zone_amber_with_no_blocks_this_week():
    assert zone.zone_amber({}, MON)["state"] is None


def test_zone_amber_prior_share_zero_never_ambers():
    weeks = weeks_with([(0, 20), (0, 20), (0, 20), (0, 20)])
    assert zone.zone_amber(weeks, MON + datetime.timedelta(weeks=3))["state"] is False


# --- reset effect -----------------------------------------------------------

def rs(kind, acc_before, acc_after, solve_before=10.0, solve_after=10.0):
    return {"kind": kind, "before": {"accuracy_pct": acc_before, "median_solve_s": solve_before},
            "after": {"accuracy_pct": acc_after, "median_solve_s": solve_after}}


def test_reset_effect_vs_none_and_n_marking():
    resets = [rs("walk", 70, 80, 12, 10) for _ in range(5)] + [rs("none", 70, 72) for _ in range(5)]
    resets += [rs("nap", 70, 90) for _ in range(4)]
    out = zone.reset_effect(resets)
    assert out["walk"]["n"] == 5 and out["walk"]["interpretable"] is True
    assert out["walk"]["accuracy_pct"]["mean_change"] == 10
    assert out["walk"]["accuracy_pct"]["vs_none"] == 8
    assert out["walk"]["median_solve_s"]["vs_none"] == -2
    assert out["nap"]["n"] == 4 and out["nap"]["interpretable"] is False  # shown, but marked
    assert out["none"]["accuracy_pct"]["vs_none"] is None


def test_reset_effect_missing_metrics_and_no_control():
    r = rs("walk", None, 80)
    out = zone.reset_effect([r])
    assert out["walk"]["accuracy_pct"] == {"n": 0, "mean_change": None, "vs_none": None}
    assert out["walk"]["median_solve_s"]["vs_none"] is None  # no "none" resets to compare with


# --- discomfort ------------------------------------------------------------

def chk(at, area="neck", score=2, trigger="end_of_block", countermove="none", sharp_or_numb=False):
    return {"at": at, "area": area, "score": score, "trigger": trigger, "countermove": countermove,
            "sharp_or_numb": sharp_or_numb}


def test_sharp_or_numb_surfaces_as_stop_signal():
    later, earlier = chk(local(MON, 15), sharp_or_numb=True), chk(local(MON, 9), area="wrist", sharp_or_numb=True)
    checks = [chk(local(MON, 8)), later, earlier]
    assert zone.stop_signals(checks) == [earlier, later]
    assert zone.weekly_discomfort(checks, NY)[MON]["stop_signals"] == [earlier, later]


def test_weekly_discomfort_summary():
    checks = [
        chk(local(MON, 9), score=4, trigger="end_of_commute", countermove="hip_flexor", area="hip"),
        chk(local(MON, 10), score=5, trigger="end_of_commute", area="hip"),
        chk(local(MON, 11), score=3, trigger="end_of_meeting", countermove="chin_tuck_pullapart"),
        chk(local(MON, 12), score=1),
        chk(local(MON + datetime.timedelta(days=7), 9), score=0),
    ]
    out = zone.weekly_discomfort(checks, NY)
    w = out[MON]
    assert w["n"] == 4
    assert w["mean_score"] == {"hip": 4.5, "neck": 2.0}
    assert w["high_by_trigger"] == {"end_of_commute": 2, "end_of_meeting": 1}
    assert w["countermove_share"] == pytest.approx(2 / 3)
    assert out[MON + datetime.timedelta(days=7)]["countermove_share"] is None
