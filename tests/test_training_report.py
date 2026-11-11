"""M3.5-T4: training_report on a seeded database (via the sample CSV)."""
import datetime
import json
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from core.models import Contributor, Supersession, TrainingSession, TrainingSet

FIXTURE = Path(__file__).parent / "fixtures" / "sample_training.csv"
DISCLAIMER = "Load gauge, not a medical assessment."
UNTIL = "2026-11-13"  # week of Monday 2026-11-09


@pytest.fixture
def mike(db):
    m = Contributor.objects.get(handle="mike")
    call_command("ingest_training_csv", str(FIXTURE), stdout=StringIO())
    return m


def report(*args):
    out = StringIO()
    call_command("training_report", "--until", UNTIL, *args, stdout=out)
    return out.getvalue()


def test_text_report(mike):
    out = report("--weeks", "2")
    lines = out.splitlines()
    assert lines[0] == "Training report for mike, weeks 2026-11-02 to 2026-11-09"
    assert lines[2] == "STOP SIGNALS (joint pain 2 or more):"
    assert "set 2 romanian deadlift: joint pain 2 (low_back): stop the block; get it checked by a professional" in lines[3]
    assert "2026-11-02: no sets" in out
    # tonnage 800 + 720 + 300 + 300 + 600 + 720 + 0 (bodyweight pull-up); RIR 3,2,1,4,2,1 (one missing)
    assert "2026-11-09: 2 sessions, 7 sets, tonnage 3440 kg, mean RIR 2.2 (n=6)" in out
    assert "  hard sets: back 1, chest 3, hamstrings 1, quads 1" in out
    assert "  joint-pain sets by area: low_back 1, shoulder 1" in out
    assert out.rstrip().endswith(DISCLAIMER)


def test_json_report_has_no_notes(mike):
    data = json.loads(report("--json", "--weeks", "1"))
    [week] = data["training"]
    assert week["week"] == "2026-11-09" and week["summary"]["tonnage_kg"] == pytest.approx(3440)
    assert week["summary"]["hard_sets_by_muscle"]["chest"] == 3 and week["summary"]["deload"] is False
    [stop] = data["stop_signals"]
    assert stop["exercise"] == "romanian deadlift" and stop["action"].startswith("stop the block")
    text = json.dumps(data)
    assert "stopped here" not in text and "front of shoulder" not in text
    assert data["disclaimer"] == DISCLAIMER


def test_deload_week_marked(mike):
    TrainingSession(contributor=mike, started_at=datetime.datetime(2026, 11, 17, 23, tzinfo=datetime.timezone.utc),
                    program="RP", is_deload=True).save()
    s = TrainingSession.objects.get(is_deload=True)
    TrainingSet(contributor=mike, session_cid=s.cid, order=1, exercise="bench", muscle_group="chest", reps=8,
                rir=5).save()
    out = report("--until", "2026-11-18", "--weeks", "1")
    assert "2026-11-16 DELOAD: 1 sessions, 1 sets" in out and "hard sets: none" in out


def test_sets_follow_a_corrected_session(mike):
    old = TrainingSession.objects.get(location="gym")
    fixed = TrainingSession(contributor=mike, started_at=old.started_at, program=old.program, mesocycle=old.mesocycle,
                            meso_week=old.meso_week, location="gym", session_rpe=old.session_rpe, is_deload=True)
    fixed.save()
    Supersession.record(old, fixed)
    data = json.loads(report("--json", "--weeks", "1"))
    week = data["training"][0]["summary"]
    assert week["sets"] == 7 and week["sessions"] == 2 and week["deload"] is True


def test_sessions_without_sets_count_and_mark_deload(mike):
    """Review #4: a session logged without sets still counts, and a zero-set deload marks its week."""
    TrainingSession(contributor=mike, started_at=datetime.datetime(2026, 11, 17, 23, tzinfo=datetime.timezone.utc),
                    program="RP", is_deload=True).save()
    TrainingSession(contributor=mike, started_at=datetime.datetime(2026, 11, 18, 23, tzinfo=datetime.timezone.utc),
                    program="RP").save()
    out = report("--until", "2026-11-18", "--weeks", "1")
    assert "2026-11-16 DELOAD: 2 sessions, 0 sets, tonnage 0 kg, mean RIR n/a" in out


def test_earlier_stop_signals_counted(mike):
    out = report("--until", "2026-11-25", "--weeks", "1")
    assert "Stop signals: none" in out and "Earlier stop signals before these weeks: 1" in out


def test_report_is_per_contributor(mike):
    sam = Contributor.objects.create(handle="sam")
    out = StringIO()
    call_command("training_report", "--contributor", "sam", "--until", UNTIL, "--weeks", "1", stdout=out)
    assert "no sets" in out.getvalue() and sam.handle in out.getvalue()


def test_bad_arguments(db):
    with pytest.raises(CommandError, match="Unknown contributor"):
        report("--contributor", "nobody")
    with pytest.raises(CommandError, match="at least 1"):
        report("--weeks", "0")
