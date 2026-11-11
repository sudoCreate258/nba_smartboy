"""M3.5-T2: training statistics on synthetic data (no database)."""
import datetime
import zoneinfo

import pytest

from twin_metrics import training

NY = "America/New_York"
NYZ = zoneinfo.ZoneInfo(NY)
MON = datetime.date(2026, 11, 9)


def at(day, hour=18):
    return datetime.datetime.combine(MON + datetime.timedelta(days=day), datetime.time(hour), tzinfo=NYZ)


def s(day=0, muscle="chest", load=80.0, reps=10, rir=2, joint_pain=None, area=None, deload=False, session="a", order=1):
    return {"started_at": at(day), "session_cid": session, "order": order, "muscle_group": muscle, "load_kg": load,
            "reps": reps, "rir": rir, "joint_pain": joint_pain, "joint_pain_area": area, "is_deload": deload}


@pytest.mark.parametrize("rir,hard", [(0, True), (3, True), (4, False), (None, True)])
def test_hard_set(rir, hard):
    assert training.is_hard({"rir": rir}) is hard


def test_tonnage_and_bodyweight():
    assert training.tonnage(s(load=80, reps=10)) == 800
    assert training.tonnage(s(load=None, reps=15)) == 0


def test_weekly_summary():
    sets = [
        s(0, "chest", 80, 10, 2, session="a", order=1),
        s(0, "chest", 80, 9, 1, session="a", order=2),
        s(0, "triceps", 20, 12, 5, session="a", order=3),  # rir 5: not hard
        s(2, "quads", 100, 6, None, session="b", order=1),  # rir missing: hard
        s(2, "quads", None, 20, 3, joint_pain=1, area="hip", session="b", order=2),
        s(2, "back", 60, 10, 2, joint_pain=2, session="b", order=3),
    ]
    w = training.weekly_training(sets, NY)[MON]
    assert w["sessions"] == 2 and w["sets"] == 6
    assert w["hard_sets_by_muscle"] == {"back": 1, "chest": 2, "quads": 2}
    assert w["tonnage_kg"] == pytest.approx(800 + 720 + 240 + 600 + 0 + 600)
    assert w["mean_rir"] == pytest.approx((2 + 1 + 5 + 3 + 2) / 5) and w["rir_n"] == 5
    assert w["joint_pain_by_area"] == {"hip": 1, "unknown": 1}
    assert w["deload"] is False
    assert [x["order"] for x in w["stop_signals"]] == [3]


def test_deload_week_marked_and_weeks_split():
    sets = [s(0, deload=True), s(7, session="c")]
    weeks = training.weekly_training(sets, NY)
    assert weeks[MON]["deload"] is True
    assert weeks[MON + datetime.timedelta(days=7)]["deload"] is False


def test_sunday_night_session_stays_in_its_local_week():
    late = s(6)
    late["started_at"] = at(6, 23)  # Sunday 23:00 New York = Monday UTC
    assert list(training.weekly_training([late], NY)) == [MON]


def test_mean_rir_none_without_rir():
    w = training.weekly_training([s(rir=None)], NY)[MON]
    assert w["mean_rir"] is None and w["rir_n"] == 0


def test_stop_signals_sorted_oldest_first():
    later, earlier = s(2, joint_pain=3, order=1), s(0, joint_pain=2, order=5)
    assert training.stop_signals([later, s(1), earlier]) == [earlier, later]
