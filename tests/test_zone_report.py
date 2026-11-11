"""M3-T6: zone_report service and command on a seeded database."""
import datetime
import json
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from core.models import Contributor, DiscomfortCheck, ProbeSession, Reset, Supersession, WeeklyCheck, WorkBlock
from core.services.zone_report import current_probe, week_range, zone_report

DISCLAIMER = "Load gauge, not a medical assessment."
MON = datetime.date(2026, 10, 5)
UNTIL = MON + datetime.timedelta(weeks=3, days=2)  # Wednesday of the 4th week


@pytest.fixture
def mike(db):
    return Contributor.objects.get(handle="mike")


def at(mike, week, day=0, hour=9, minute=0):
    d = MON + datetime.timedelta(weeks=week, days=day)
    return datetime.datetime.combine(d, datetime.time(hour, minute), tzinfo=mike.tzinfo)


def work(mike, week, day, hour, minutes, absorption=4, interruptions=0, **kw):
    start = at(mike, week, day, hour)
    WorkBlock(contributor=mike, start=start, end=start + datetime.timedelta(minutes=minutes), task_type="code",
              absorption=absorption, interruptions=interruptions, **kw).save()


def seed_zone(mike, last_share=0.6):
    """4 weeks of 20 h; the first 3 at 60% high focus, the last at `last_share`."""
    for week in range(4):
        share = 0.6 if week < 3 else last_share
        for day in range(4):  # 4 days x 5 h
            focus = round(300 * share)
            work(mike, week, day, 8, focus, location="remote", posture="sit", planned_length_min=50)
            work(mike, week, day, 14, 300 - focus, absorption=2, location="office")


def mini(mike, started_at, acc, solve=10):
    p = ProbeSession(contributor=mike, started_at=started_at, kind="mini_puzzle", accuracy_pct=acc,
                     median_solve_s=solve)
    p.save()
    return p


def add_reset(mike, week, day, kind, before_acc, after_acc):
    t = at(mike, week, day, 13)
    before = mini(mike, t - datetime.timedelta(minutes=5), before_acc)
    after = mini(mike, t + datetime.timedelta(minutes=20), after_acc)
    Reset(contributor=mike, at=t, kind=kind, duration_min=10, before_probe_cid=before.cid,
          after_probe_cid=after.cid).save()
    return before, after


def report(*args):
    out = StringIO()
    call_command("zone_report", "--until", UNTIL.isoformat(), *args, stdout=out)
    return out.getvalue()


def test_week_range(mike):
    assert week_range(mike, 4, UNTIL) == [MON + datetime.timedelta(weeks=i) for i in range(4)]
    assert week_range(mike, 1, MON + datetime.timedelta(days=6)) == [MON]


def test_service_zone_amber_and_breakdowns(mike):
    seed_zone(mike, last_share=0.4)
    r = zone_report(mike, weeks=4, until=UNTIL)
    assert r["weeks"][-1] == MON + datetime.timedelta(weeks=3)
    last = r["zone"][-1]
    assert last["summary"]["total_hours"] == pytest.approx(20)
    assert last["summary"]["focus_share"] == pytest.approx(0.4)
    assert last["amber"]["state"] is True
    assert r["zone"][0]["amber"]["state"] is None  # no prior weeks
    assert set(last["summary"]["by"]["location"]) == {"remote", "office"}


def test_superseded_blocks_are_ignored(mike):
    seed_zone(mike)
    old = WorkBlock.objects.order_by("start").first()
    fix = WorkBlock(contributor=mike, start=old.start, end=old.end, task_type="code", absorption=1, interruptions=0)
    fix.replaces_cid = old.cid
    fix.save()
    Supersession.record(old, fix)
    first = zone_report(mike, weeks=4, until=UNTIL)["zone"][0]["summary"]
    assert first["high_focus_minutes"] == pytest.approx(180 * 3)  # one of four focus blocks no longer counts


def test_text_report_stop_signals_first(mike):
    seed_zone(mike)
    DiscomfortCheck(contributor=mike, at=at(mike, 3, 1, 11), area="wrist", score=6, trigger="end_of_block",
                    sharp_or_numb=True).save()
    DiscomfortCheck(contributor=mike, at=at(mike, 3, 1, 15), area="neck", score=4, trigger="end_of_meeting",
                    countermove="chin_tuck_pullapart").save()
    out = report()
    lines = out.splitlines()
    assert lines[0].startswith("Zone report for mike, weeks 2026-10-05 to 2026-10-26")
    assert lines[2] == "STOP SIGNALS (sharp or numb):"
    assert "wrist score 6 (end_of_block): stop the block; get it checked by a professional" in lines[3]
    assert out.index("STOP SIGNALS") < out.index("== Zone")
    assert "mean score neck 4.0, wrist 6.0" in out
    assert "countermove after score >= 3: 50%" in out
    assert out.rstrip().endswith(DISCLAIMER)


def test_text_report_without_data(mike):
    out = report("--weeks", "2")
    assert "Stop signals: none" in out
    assert "2026-10-19: no work blocks" in out and "2026-10-26: no checks" in out
    assert "no resets logged" in out and "none in these weeks" in out
    assert "mini_puzzle: NONE (insufficient baseline: 0 of 10 sessions)" in out


def test_reset_effect_in_report(mike):
    for i in range(5):
        add_reset(mike, 0, i, "walk", 70, 80)
        add_reset(mike, 1, i, "none", 70, 72)
    add_reset(mike, 2, 0, "nap", 70, 90)
    out = report()
    assert "walk: 5 resets; accuracy change +10.0 (n=5), vs none +8.0; solve change +0.0 s (n=5), vs none +0.0 s" in out
    assert "nap: 1 resets; accuracy change +20.0 (n=1, not interpretable yet: n < 5), vs none +18.0 " \
           "(underpowered: needs n >= 5 on both sides)" in out
    data = json.loads(report("--json"))
    walk = data["resets"]["walk"]["accuracy_pct"]
    assert walk["vs_none"] == pytest.approx(8) and walk["interpretable"] and walk["vs_none_interpretable"]


def test_reset_follows_corrections_of_its_probes(mike):
    before, after = add_reset(mike, 0, 0, "walk", 70, 80)
    fixed = mini(mike, after.started_at, 85)
    Supersession.record(after, fixed)
    assert current_probe(after.cid, mike) == fixed
    r = zone_report(mike, weeks=4, until=UNTIL)
    assert r["resets"]["walk"]["accuracy_pct"]["mean_change"] == pytest.approx(15)
    assert r["resets_corrected"] == 1 and r["resets_excluded"] == []
    assert "1 reset(s) use probes that were corrected" in report()


@pytest.mark.parametrize("change", ["kind", "time"])
def test_correction_that_breaks_the_reset_contract_excludes_it(mike, change):
    """Review #3: a probe corrected to another kind, or moved past the reset, no longer counts."""
    before, after = add_reset(mike, 0, 0, "walk", 70, 80)
    if change == "kind":
        fixed = ProbeSession(contributor=mike, started_at=after.started_at, kind="puzzle_set", accuracy_pct=80)
    else:
        fixed = ProbeSession(contributor=mike, started_at=at(mike, 0, 0, 12), kind="mini_puzzle", accuracy_pct=80)
    fixed.save()
    Supersession.record(after, fixed)
    r = zone_report(mike, weeks=4, until=UNTIL)
    assert r["resets"] == {}
    [problem] = r["resets_excluded"]
    assert ("other than mini_puzzle" if change == "kind" else "no longer bracket") in problem
    assert "Excluded: reset walk at 2026-10-05 13:00" in report()


def test_unresolvable_probe_is_excluded_not_counted(mike, monkeypatch):
    """Review #6: a broken correction chain drops the reset from n and says so."""
    from core import models

    add_reset(mike, 0, 0, "walk", 70, 80)
    monkeypatch.setattr(models, "MAX_CHAIN", 0)
    r = zone_report(mike, weeks=4, until=UNTIL)
    assert r["resets"] == {} and "no longer resolves" in r["resets_excluded"][0]


def test_correction_chain_is_followed_to_the_end(mike):
    before, after = add_reset(mike, 0, 0, "walk", 70, 80)
    first = mini(mike, after.started_at, 82)
    Supersession.record(after, first)
    second = mini(mike, after.started_at, 84)
    Supersession.record(first, second)
    assert current_probe(after.cid, mike) == second


def test_earlier_stop_signals_are_counted(mike):
    DiscomfortCheck(contributor=mike, at=at(mike, -2, 0, 10), area="wrist", score=7, trigger="other",
                    sharp_or_numb=True).save()
    out = report()
    assert "Stop signals: none" in out
    assert "Earlier stop signals before these weeks: 1" in out
    assert json.loads(report("--json"))["earlier_stop_signals"] == 1


def test_json_has_no_free_text_notes(mike):
    DiscomfortCheck(contributor=mike, at=at(mike, 3, 0, 10), area="hip", score=3, trigger="other",
                    sharp_or_numb=True, notes="private text").save()
    assert "private text" not in report("--json")


def test_report_is_per_contributor(mike):
    sam = Contributor.objects.create(handle="sam")
    seed_zone(sam)
    DiscomfortCheck(contributor=sam, at=at(sam, 3, 0, 10), area="hip", score=9, trigger="other",
                    sharp_or_numb=True).save()
    WeeklyCheck(contributor=sam, week_start=MON, instrument="OLBI", score="3", scale_max="4").save()
    r = zone_report(mike, weeks=4, until=UNTIL)
    assert all(z["summary"] is None for z in r["zone"])
    assert r["stop_signals"] == [] and r["weekly_checks"] == []


def test_blocks_before_the_lookback_are_not_loaded(mike):
    seed_zone(mike)
    r = zone_report(mike, weeks=1, until=UNTIL)  # window = week 3, lookback = weeks 0-2
    assert r["zone"][0]["amber"]["state"] is False
    r = zone_report(mike, weeks=1, until=UNTIL - datetime.timedelta(weeks=2))  # week 1: only 1 prior week
    assert r["zone"][0]["amber"]["state"] is None


def test_until_includes_the_whole_week(mike):
    work(mike, 3, 5, 9, 60)  # Saturday after the Wednesday --until date
    r = zone_report(mike, weeks=1, until=UNTIL)
    assert r["zone"][0]["summary"]["total_hours"] == pytest.approx(1.0)


def test_weekly_check_shown_separately(mike):
    WeeklyCheck(contributor=mike, week_start=MON + datetime.timedelta(weeks=2), instrument="OLBI", score="2.4",
                scale_max="4").save()
    WeeklyCheck(contributor=mike, week_start=MON - datetime.timedelta(weeks=1), instrument="OLBI", score="1",
                scale_max="4").save()  # outside the window
    out = report()
    assert "2026-10-19: OLBI 2.4 / 4" in out and "2026-09-28" not in out
    assert "never combined into one score" in out


def test_json_report(mike):
    seed_zone(mike, last_share=0.4)
    DiscomfortCheck(contributor=mike, at=at(mike, 3, 0, 10), area="hip", score=3, trigger="end_of_commute",
                    sharp_or_numb=True).save()
    data = json.loads(report("--json"))
    assert data["contributor"] == "mike" and data["disclaimer"] == DISCLAIMER
    assert data["weeks"] == ["2026-10-05", "2026-10-12", "2026-10-19", "2026-10-26"]
    [stop] = data["stop_signals"]
    assert stop["area"] == "hip" and stop["action"].startswith("stop the block")
    assert data["zone"][3]["amber"]["state"] is True
    assert data["zone"][3]["summary"]["by"]["planned_length_min"]["50"]["focus_share"] == pytest.approx(1.0)
    assert data["discomfort"][3]["summary"]["stop_signals"][0]["area"] == "hip"
    assert [p["kind"] for p in data["probes"]] == ["puzzle_set", "rapid_game", "mini_puzzle"]


def test_report_is_read_only(mike):
    seed_zone(mike)
    before = WorkBlock.objects.count()
    report()
    assert WorkBlock.objects.count() == before


def test_bad_arguments(db):
    with pytest.raises(CommandError, match="Unknown contributor"):
        report("--contributor", "nobody")
    with pytest.raises(CommandError, match="at least 1"):
        report("--weeks", "0")
