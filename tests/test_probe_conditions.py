import datetime

import pytest

from core.models import Contributor, DailySnapshot, ProbeSession, Supersession, WorkBlock
from core.services.probe_report import baseline_window, current_sessions, kind_report, sleep_falling, work_rising
from twin_metrics.probes import deviates

UTC = datetime.timezone.utc
DAY0 = datetime.date(2026, 10, 1)


@pytest.fixture
def mike(db):
    return Contributor.objects.get(handle="mike")


def day(i):
    return DAY0 + datetime.timedelta(days=i)


def session_time(i):
    return datetime.datetime.combine(day(i), datetime.time(13, 0), tzinfo=UTC)  # 09:00 in New York


def add_session(mike, i, acc=80.0, solve=10.0):
    p = ProbeSession(contributor=mike, started_at=session_time(i), kind="puzzle_set",
                     accuracy_pct=acc, median_solve_s=solve)
    p.save()
    return p


def add_sleep(mike, i, score):
    s = DailySnapshot(contributor=mike, date=day(i), source="manual", sleep_score=score)
    s.save()
    return s


def add_work(mike, i, hours):
    start = datetime.datetime.combine(day(i), datetime.time(15, 0), tzinfo=UTC)
    WorkBlock(contributor=mike, start=start, end=start + datetime.timedelta(hours=hours), task_type="code").save()


def window_for(mike):
    sessions = current_sessions(mike, "puzzle_set")
    return baseline_window(mike, "puzzle_set", sessions), sessions[-1]


def seed_baseline(mike, sleep=True, work=True):
    """10 baseline days (0-9) with varying scores and hours, one session per day."""
    for i in range(10):
        add_session(mike, i, acc=80 + 2 * (-1) ** i, solve=10 + (-1) ** i)
        if sleep:
            add_sleep(mike, i, 80 + 5 * (-1) ** i)
        if work:
            add_work(mike, i, 2 + (i % 2))


def test_deviates():
    base = [-1, 1] * 5  # SD ~1.054
    assert deviates(-1.2, base, "lower") is True
    assert deviates(-0.5, base, "lower") is False
    assert deviates(1.2, base, "higher") is True
    assert deviates(0.5, base, "higher") is False
    assert deviates(None, base, "lower") is None
    assert deviates(1, [3], "lower") is None
    assert deviates(1, [3, 3, 3], "lower") is None


def test_sleep_falling_true_and_false(mike):
    seed_baseline(mike)
    for i in (10, 11, 12):
        add_session(mike, i)
        add_sleep(mike, i, 60)
    window, latest = window_for(mike)
    assert sleep_falling(mike, window, latest)["state"] is True


def test_sleep_not_falling_when_recent_nights_match_baseline(mike):
    seed_baseline(mike)
    for i in (10, 11, 12):
        add_session(mike, i)
        add_sleep(mike, i, 80)
    window, latest = window_for(mike)
    assert sleep_falling(mike, window, latest)["state"] is False


def test_sleep_insufficient_when_recent_nights_missing(mike):
    seed_baseline(mike)
    for i in (10, 11, 12):
        add_session(mike, i)
    add_sleep(mike, 12, 50)
    window, latest = window_for(mike)
    out = sleep_falling(mike, window, latest)
    assert out["state"] is None and "1 of 3 recent nights" in out["detail"]


def test_sleep_insufficient_without_any_snapshot_or_session(mike):
    assert sleep_falling(mike, baseline_window(mike, "puzzle_set"), None)["state"] is None
    seed_baseline(mike, sleep=False)
    window, latest = window_for(mike)
    assert sleep_falling(mike, window, latest)["state"] is None


def test_sleep_insufficient_when_baseline_nights_do_not_vary(mike):
    seed_baseline(mike, sleep=False)
    for i in range(13):
        add_sleep(mike, i, 80)
        if i > 9:
            add_session(mike, i)
    window, latest = window_for(mike)
    assert sleep_falling(mike, window, latest)["state"] is None


def test_superseded_snapshot_is_ignored(mike):
    seed_baseline(mike)
    for i in (10, 11):
        add_session(mike, i)
        add_sleep(mike, i, 80)
    add_session(mike, 12)
    wrong = add_sleep(mike, 12, 30)
    fixed = DailySnapshot(contributor=mike, date=day(12), source="manual", sleep_score=80)
    fixed.save(supersede=True)
    assert Supersession.objects.filter(old_cid=wrong.cid, new_cid=fixed.cid).exists()
    window, latest = window_for(mike)
    assert sleep_falling(mike, window, latest)["state"] is False


def test_work_rising_true_and_false(mike):
    seed_baseline(mike)
    for i in (10, 11, 12):
        add_session(mike, i)
        add_work(mike, i, 8)
    window, latest = window_for(mike)
    out = work_rising(mike, window, latest)
    assert out["state"] is True and "24.0 h" in out["detail"]


def test_work_not_rising_at_baseline_load(mike):
    seed_baseline(mike)
    for i in (10, 11, 12):
        add_session(mike, i)
        add_work(mike, i, 2 + (i % 2))
    window, latest = window_for(mike)
    assert work_rising(mike, window, latest)["state"] is False


def test_work_insufficient_without_recent_blocks_or_baseline_blocks(mike):
    seed_baseline(mike)
    for i in (10, 11, 12):
        add_session(mike, i)
    window, latest = window_for(mike)
    out = work_rising(mike, window, latest)
    assert out["state"] is None and "no work blocks" in out["detail"]


def test_work_insufficient_without_baseline_blocks(mike):
    seed_baseline(mike, work=False)
    for i in (10, 11, 12):
        add_session(mike, i)
        add_work(mike, i, 8)
    window, latest = window_for(mike)
    assert work_rising(mike, window, latest)["state"] is None


def test_work_block_crossing_midnight_counts_fully_inside_window(mike):
    seed_baseline(mike)
    add_session(mike, 11)
    # 22:00 on day 10 to 02:00 on day 11 (New York) lies inside the 3 days ending day 11.
    start = datetime.datetime.combine(day(10), datetime.time(22), tzinfo=datetime.timezone(datetime.timedelta(hours=-4)))
    WorkBlock(contributor=mike, start=start, end=start + datetime.timedelta(hours=4), task_type="code").save()
    window, latest = window_for(mike)
    # Window is days 9-11: the 3 h block on day 9 plus the 4 h block.
    assert "7.0 h" in work_rising(mike, window, latest)["detail"]


def test_work_block_is_clipped_to_the_window(mike):
    seed_baseline(mike)
    add_session(mike, 11)
    # 20:00 on day 8 to 04:00 on day 9 (New York): only the 4 h after midnight fall in days 9-11.
    start = datetime.datetime.combine(day(8), datetime.time(20), tzinfo=datetime.timezone(datetime.timedelta(hours=-4)))
    WorkBlock(contributor=mike, start=start, end=start + datetime.timedelta(hours=8), task_type="code").save()
    window, latest = window_for(mike)
    assert "7.0 h" in work_rising(mike, window, latest)["detail"]  # 3 h (day 9 block) + 4 h clipped

def test_kind_report_red_via_amber_plus_falling_sleep(mike):
    seed_baseline(mike)
    for i in (10, 11, 12):
        add_session(mike, i, acc=80 - 2.5, solve=10 + 1.3)
        add_sleep(mike, i, 60)
    out = kind_report(mike, "puzzle_set")
    assert out["status"] == "ok" and out["level"] == "red"
    assert "sleep is falling" in out["reasons"]
    assert out["sleep"]["state"] is True and out["work"]["state"] is None
    assert out["baseline_source"] == "default"


def test_kind_report_amber_when_context_is_insufficient(mike):
    seed_baseline(mike, sleep=False, work=False)
    for i in (10, 11, 12):
        add_session(mike, i, acc=80 - 2.5, solve=10 + 1.3)
    out = kind_report(mike, "puzzle_set")
    assert out["level"] == "amber"
    assert out["sleep"]["state"] is None and out["work"]["state"] is None


def test_kind_report_ignores_superseded_sessions(mike):
    seed_baseline(mike, sleep=False, work=False)
    bad = [add_session(mike, i, acc=40, solve=30) for i in (10, 11, 12)]
    for i, old in zip((10, 11, 12), bad):
        fixed = ProbeSession(contributor=mike, started_at=session_time(i), kind="puzzle_set",
                             accuracy_pct=80, median_solve_s=10)
        fixed.save()
        Supersession.record(old, fixed)
    out = kind_report(mike, "puzzle_set")
    assert out["level"] == "none" and out["n_scored"] == 3


def test_kind_report_insufficient_baseline(mike):
    for i in range(4):
        add_session(mike, i)
    out = kind_report(mike, "puzzle_set")
    assert out["status"] == "insufficient_baseline" and out["level"] == "none"
