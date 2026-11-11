"""M3.5-T3: ingest_training_csv (exact owner header, atomic, idempotent)."""
import datetime
from decimal import Decimal
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from core.management.commands.ingest_training_csv import HEADER
from core.models import Contributor, TrainingSession, TrainingSet

FIXTURE = Path(__file__).parent / "fixtures" / "sample_training.csv"
OWNER_HEADER = ("started_at,program,mesocycle,meso_week,is_deload,location,session_rpe,order,exercise,muscle_group,"
                "load_kg,reps,rir,pump,soreness_before,joint_pain,joint_pain_area,notes")
ROW = "2026-11-10 18:00,RP,Meso 1,1,no,gym,7,1,Bench Press,chest,80,10,2,,,,,"


@pytest.fixture
def mike(db):
    return Contributor.objects.get(handle="mike")


def ingest(path, *args):
    out = StringIO()
    call_command("ingest_training_csv", str(path), *args, stdout=out)
    return out.getvalue()


def write(tmp_path, text, name="t.csv"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_header_is_exactly_the_owners():
    assert ",".join(HEADER) == OWNER_HEADER
    assert FIXTURE.read_text(encoding="utf-8").splitlines()[0] == OWNER_HEADER


def test_happy_path(mike):
    out = ingest(FIXTURE)
    assert "sessions created=2 existing=0; sets created=7 skipped=0" in out
    first = TrainingSession.objects.get(location="gym")
    assert first.started_at == datetime.datetime(2026, 11, 10, 23, 0, tzinfo=datetime.timezone.utc)  # 18:00 EST
    assert (first.program, first.mesocycle, first.meso_week, first.is_deload) == ("RP Hypertrophy", "Meso 1", 1, False)
    assert first.session_rpe == Decimal("7.5") and first.notes == "" and first.ended_at is None
    sets = TrainingSet.objects.filter(session_cid=first.cid).order_by("order")
    assert [s.exercise for s in sets] == ["bench press", "bench press", "cable fly", "overhead triceps extension"]
    fly = sets[2]
    assert (fly.joint_pain, fly.joint_pain_area, fly.notes) == (1, "shoulder", "front of shoulder")
    assert sets[3].joint_pain is None and sets[3].joint_pain_area is None
    pullup = TrainingSet.objects.get(exercise="pull-up")
    assert pullup.load_kg is None and pullup.notes == "bodyweight"
    assert TrainingSet.objects.get(exercise="romanian deadlift").rir is None


def test_reimport_is_idempotent(mike):
    ingest(FIXTURE)
    out = ingest(FIXTURE)
    assert "sessions created=0 existing=2; sets created=0 skipped=7" in out
    assert TrainingSession.objects.count() == 2 and TrainingSet.objects.count() == 7


def test_appending_rows_later_adds_only_new_sets(mike, tmp_path):
    ingest(write(tmp_path, OWNER_HEADER + "\n" + ROW + "\n"))
    more = ROW.replace(",1,Bench Press,chest,80,10,", ",2,Bench Press,chest,80,9,")
    out = ingest(write(tmp_path, OWNER_HEADER + "\n" + ROW + "\n" + more + "\n", "t2.csv"))
    assert "existing=1; sets created=1 skipped=1" in out


def test_unknown_column_rolls_back(mike, tmp_path):
    p = write(tmp_path, OWNER_HEADER + ",mood\n" + ROW + ",ok\n")
    with pytest.raises(CommandError, match="Unknown columns: mood"):
        ingest(p)
    assert TrainingSession.objects.count() == 0


def test_bad_row_rolls_back_the_whole_file(mike, tmp_path):
    bad = ROW.replace(",1,Bench Press,chest,80,10,2,", ",2,Bench Press,neck,80,10,2,")
    p = write(tmp_path, OWNER_HEADER + "\n" + ROW + "\n" + bad + "\n")
    with pytest.raises(CommandError, match=r"Line 3: muscle_group"):
        ingest(p)
    assert TrainingSession.objects.count() == 0 and TrainingSet.objects.count() == 0


@pytest.mark.parametrize("value,expected", [("yes", True), ("YES", True), ("True", True), ("no", False),
                                            ("FALSE", False), ("", False)])
def test_is_deload_values(mike, tmp_path, value, expected):
    ingest(write(tmp_path, OWNER_HEADER + "\n" + ROW.replace(",no,gym,", f",{value},gym,") + "\n"))
    assert TrainingSession.objects.get().is_deload is expected


def test_is_deload_rejects_other_values(mike, tmp_path):
    with pytest.raises(CommandError, match="Line 2: is_deload"):
        ingest(write(tmp_path, OWNER_HEADER + "\n" + ROW.replace(",no,gym,", ",maybe,gym,") + "\n"))


def test_started_at_with_offset_and_dst_rejection(mike, tmp_path):
    ingest(write(tmp_path, OWNER_HEADER + "\n" + ROW.replace("2026-11-10 18:00", "2026-11-10T18:00:00-05:00") + "\n"))
    assert TrainingSession.objects.get().started_at.hour == 23
    ambiguous = ROW.replace("2026-11-10 18:00", "2026-11-01 01:30")
    with pytest.raises(CommandError, match="Line 2: started_at: .*ambiguous"):
        ingest(write(tmp_path, OWNER_HEADER + "\n" + ambiguous + "\n", "dst.csv"))


def test_sessions_group_by_started_at_and_program(mike, tmp_path):
    other_program = ROW.replace(",RP,", ",Conditioning,").replace(",1,Bench Press,", ",1,Bike,").replace(",chest,", ",full_body,")
    out = ingest(write(tmp_path, OWNER_HEADER + "\n" + ROW + "\n" + other_program + "\n"))
    assert "sessions created=2" in out


def test_conflicting_session_columns_are_rejected(mike, tmp_path):
    second = ROW.replace(",gym,7,1,", ",home,7,2,")
    with pytest.raises(CommandError, match="Line 3: session columns differ .*location"):
        ingest(write(tmp_path, OWNER_HEADER + "\n" + ROW + "\n" + second + "\n"))


def test_duplicate_order_with_different_values_is_rejected(mike, tmp_path):
    clash = ROW.replace(",80,10,2,", ",80,8,2,")
    with pytest.raises(CommandError, match="Line 3: order: Set 1 already exists"):
        ingest(write(tmp_path, OWNER_HEADER + "\n" + ROW + "\n" + clash + "\n"))


def test_columns_any_order_optional_omitted_blank_rows_and_bom(mike, tmp_path):
    p = tmp_path / "bom.csv"
    p.write_text("\ufeffexercise,order,reps,muscle_group,started_at\nRow,1,8,back,2026-11-10 18:00\n,,,,\n",
                 encoding="utf-8")
    assert "sets created=1" in ingest(p)


@pytest.mark.parametrize("text,match", [
    ("program,order\nRP,1\n", "Missing required columns"),
    (OWNER_HEADER + "\n" + ROW + ",extra\n", "more values than columns"),
    (OWNER_HEADER + "\n" + ROW.replace(",10,2,", ",ten,2,") + "\n", "reps: not a whole number"),
])
def test_malformed_files(mike, tmp_path, text, match):
    with pytest.raises(CommandError, match=match):
        ingest(write(tmp_path, text))


def test_unknown_contributor_and_missing_file(db, tmp_path):
    with pytest.raises(CommandError, match="Unknown contributor"):
        ingest(FIXTURE, "--contributor", "nobody")
    with pytest.raises(CommandError, match="Cannot read"):
        ingest(tmp_path / "nope.csv")
