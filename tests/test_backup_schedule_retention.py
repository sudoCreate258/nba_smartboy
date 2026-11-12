"""M4.5-T2: backup window and catch-up, retention selection (R6, R7, R11). No database, no network."""
import datetime
import zoneinfo

import pytest

from backup import retention, schedule

NY = zoneinfo.ZoneInfo("America/New_York")
W = schedule.parse_window("02:00-05:00")


def at(y, m, d, hh, mm=0):
    return datetime.datetime(y, m, d, hh, mm, tzinfo=NY)


# --- window and catch-up ---------------------------------------------------

def test_parse_window():
    assert W == (datetime.time(2), datetime.time(5))
    for bad in ("2-5", "02:00", "02:00-02:00"):
        with pytest.raises(ValueError):
            schedule.parse_window(bad)


def test_due_inside_the_window_once():
    now = at(2026, 11, 12, 2, 10)
    assert schedule.is_due(now, at(2026, 11, 11, 2, 5), W, NY) == (True, "inside the backup window")
    ran = at(2026, 11, 12, 2, 10)
    assert schedule.is_due(at(2026, 11, 12, 4, 0), ran, W, NY)[0] is False  # never twice a night
    assert schedule.is_due(at(2026, 11, 12, 23, 0), ran, W, NY)[0] is False  # nor later that day


def test_catch_up_after_sleeping_through_the_window():
    last = at(2026, 11, 11, 2, 5)
    due, reason = schedule.is_due(at(2026, 11, 12, 8, 30), last, W, NY)
    assert due and reason.startswith("catch-up")
    assert schedule.is_due(at(2026, 11, 12, 9, 0), at(2026, 11, 12, 8, 30), W, NY)[0] is False


def test_before_the_window_belongs_to_the_previous_night():
    ran = at(2026, 11, 11, 3, 0)
    assert schedule.is_due(at(2026, 11, 12, 1, 30), ran, W, NY)[0] is False
    assert schedule.is_due(at(2026, 11, 12, 2, 0), ran, W, NY)[0] is True


def test_first_run_ever_and_manual_run_in_the_evening():
    assert schedule.is_due(at(2026, 11, 12, 14, 0), None, W, NY)[0] is True
    manual = at(2026, 11, 12, 20, 0)  # backup_now in the evening
    assert schedule.is_due(at(2026, 11, 13, 2, 30), manual, W, NY)[0] is True  # next night still runs


def test_window_crossing_midnight():
    w = schedule.parse_window("23:00-01:00")
    assert schedule.in_window(at(2026, 11, 12, 0, 30), w, NY)
    assert not schedule.in_window(at(2026, 11, 12, 1, 30), w, NY)
    assert schedule.night_start(at(2026, 11, 12, 0, 30), w, NY) == at(2026, 11, 11, 23, 0)


def test_dst_spring_forward_window_start_is_skipped():
    # 2026-03-08: 02:00 does not exist in New York; the night starts when clocks jump (03:00 EDT).
    begin = schedule.night_start(at(2026, 3, 8, 4, 0), W, NY)
    assert begin.astimezone(datetime.timezone.utc) == datetime.datetime(2026, 3, 8, 7, 0, tzinfo=datetime.timezone.utc)
    assert schedule.is_due(at(2026, 3, 8, 3, 30), at(2026, 3, 7, 2, 30), W, NY)[0] is True
    assert schedule.in_window(at(2026, 3, 8, 4, 30), W, NY)


def test_dst_fall_back_runs_once():
    # 2026-11-01: 01:00-02:00 happens twice; the window starts at 02:00 EST.
    ran = datetime.datetime(2026, 11, 1, 2, 15, tzinfo=NY)
    assert schedule.is_due(datetime.datetime(2026, 11, 1, 4, 0, tzinfo=NY), ran, W, NY)[0] is False


# --- retention ---------------------------------------------------------------

def names(moments):
    return [retention.set_name(m) for m in moments]


def test_set_names_round_trip():
    m = datetime.datetime(2026, 11, 12, 7, 5, 9, tzinfo=datetime.timezone.utc)
    assert retention.set_name(m) == "2026-11-12T070509Z"
    assert retention.parse_set_name("2026-11-12T070509Z/") == m
    assert retention.parse_set_name("notes.txt") is None


def test_keeps_7_daily_and_4_weekly():
    # One set per night for 40 nights (02:30 local), newest = 2026-11-12.
    moments = [at(2026, 11, 12, 2, 30) - datetime.timedelta(days=i) for i in range(40)]
    keep, delete = retention.select(names(moments), NY)
    kept = {retention.parse_set_name(n).astimezone(NY).date() for n in keep}
    last7 = {at(2026, 11, 12, 2).date() - datetime.timedelta(days=i) for i in range(7)}
    assert last7 <= kept
    weekly = kept - last7
    # Newest set of each of the last 4 ISO weeks (Thu 12 Nov is newest): this week's (12 Nov) and last
    # week's (Sun 8 Nov) are already daily sets; the two weeks before add Sun 1 Nov and Sun 25 Oct.
    assert sorted(weekly) == [datetime.date(2026, 10, 25), datetime.date(2026, 11, 1)]
    assert len(keep) == 9 and len(keep) + len(delete) == 40


def test_several_sets_on_one_day_keep_only_the_newest():
    moments = [at(2026, 11, 12, 2, 30), at(2026, 11, 12, 9, 0), at(2026, 11, 12, 21, 0)]
    keep, delete = retention.select(names(moments), NY)
    assert keep == [retention.set_name(at(2026, 11, 12, 21, 0))] and len(delete) == 2


def test_day_and_week_use_local_time():
    # 23:30 New York on Sunday 2026-11-08 is Monday 04:30 UTC; it belongs to Sunday's week.
    late_sunday = at(2026, 11, 8, 23, 30)
    monday = at(2026, 11, 9, 2, 30)
    keep, _ = retention.select(names([late_sunday, monday]), NY, daily=1, weekly=2)
    assert set(keep) == set(names([late_sunday, monday]))  # two different ISO weeks


def test_dst_change_day_is_one_day():
    sets = [datetime.datetime(2026, 11, 1, 1, 30, tzinfo=NY), datetime.datetime(2026, 11, 1, 1, 30, fold=1, tzinfo=NY)]
    keep, delete = retention.select(names(sets), NY, daily=1, weekly=0)
    assert len(keep) == 1 and len(delete) == 1


def test_unknown_names_are_never_deleted():
    keep, delete = retention.select(["README", "2026-11-12T070000Z"], NY)
    assert "README" not in delete and keep == ["2026-11-12T070000Z"]
