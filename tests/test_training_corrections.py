"""M3.5 review fixes: session corrections keep their sets (CSV, order check, admin) and field/CSV checks."""
import datetime
from io import StringIO

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse

from core.models import Contributor, Lineage, Supersession, TrainingSession, TrainingSet
from core.services.training_report import current_session_for, sets_of

HEADER = ("started_at,program,mesocycle,meso_week,is_deload,location,session_rpe,order,exercise,muscle_group,"
          "load_kg,reps,rir,pump,soreness_before,joint_pain,joint_pain_area,notes")
ROW1 = "2026-11-10 18:00,RP,Meso 1,1,no,gym,7,1,Bench Press,chest,80,10,2,,,,,"
ROW2 = "2026-11-10 18:00,RP,Meso 1,1,no,gym,7,2,Bench Press,chest,80,9,1,,,,,"


@pytest.fixture
def mike(db):
    return Contributor.objects.get(handle="mike")


def ingest(tmp_path, *rows, name="t.csv"):
    p = tmp_path / name
    p.write_text(HEADER + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    out = StringIO()
    call_command("ingest_training_csv", str(p), stdout=out)
    return out.getvalue()


def correct_session_in_admin(mike, notes="felt strong"):
    """What the admin correction does: a new session with the same columns plus notes, and a Supersession."""
    old = TrainingSession.objects.current().get()
    new = TrainingSession(contributor=mike, started_at=old.started_at, program=old.program, mesocycle=old.mesocycle,
                          meso_week=old.meso_week, is_deload=old.is_deload, location=old.location,
                          session_rpe=old.session_rpe, notes=notes)
    new.save()
    Supersession.record(old, new)
    return old, new


def test_csv_append_after_session_correction(mike, tmp_path):
    """Review #1: appending rows after the session was corrected in the admin."""
    ingest(tmp_path, ROW1)
    old, new = correct_session_in_admin(mike)
    out = ingest(tmp_path, ROW1, ROW2, name="t2.csv")
    assert "sessions created=0 existing=1; sets created=1 skipped=1" in out
    added = TrainingSet.objects.get(order=2)
    assert added.session_cid == new.cid
    assert sets_of(new).count() == 2


def test_unchanged_reimport_after_correction_skips_everything(mike, tmp_path):
    ingest(tmp_path, ROW1, ROW2)
    correct_session_in_admin(mike)
    assert "sets created=0 skipped=2" in ingest(tmp_path, ROW1, ROW2, name="t2.csv")


def test_order_clash_across_session_versions(mike, tmp_path):
    """Review #2: set 1 under the old session CID blocks another set 1 under the corrected one."""
    ingest(tmp_path, ROW1)
    old, new = correct_session_in_admin(mike)
    with pytest.raises(ValidationError, match="Set 1 already exists"):
        TrainingSet(contributor=mike, session_cid=new.cid, order=1, exercise="squat", muscle_group="quads",
                    reps=5).save()


def test_admin_set_table_follows_corrections(admin_client, mike, tmp_path):
    """Review #3: the current version lists the sets; the superseded one points to it and offers no add link."""
    ingest(tmp_path, ROW1, ROW2)
    old, new = correct_session_in_admin(mike)
    current_page = admin_client.get(reverse("admin:core_trainingsession_change", args=[new.pk])).content
    assert current_page.count(b"bench press") == 2 and b"Add a set to this session" in current_page
    assert new.cid.encode() in current_page
    old_page = admin_client.get(reverse("admin:core_trainingsession_change", args=[old.pk])).content
    assert b"This session was corrected" in old_page and b"Add a set to this session" not in old_page
    assert reverse("admin:core_trainingsession_change", args=[new.pk]).encode() in old_page


def test_lineage_helpers(mike, tmp_path):
    ingest(tmp_path, ROW1)
    old, new = correct_session_in_admin(mike)
    _, newer = correct_session_in_admin(mike, notes="edited twice")
    lineage = Lineage(mike.pk)
    assert lineage.members(newer.cid) == {old.cid, new.cid, newer.cid}
    assert lineage.group({newer.cid}) == {old.cid: newer.cid, new.cid: newer.cid, newer.cid: newer.cid}
    assert current_session_for(old.cid, mike) == newer


def test_joint_pain_area_needs_a_score(mike, tmp_path):
    """Review #7."""
    with pytest.raises(CommandError, match="Line 2: joint_pain: Give a joint pain score"):
        ingest(tmp_path, ROW1.replace(",2,,,,,", ",2,,,,shoulder,"))
    ingest(tmp_path, ROW1.replace(",2,,,,,", ",2,,,0,shoulder,"), name="ok.csv")
    assert TrainingSet.objects.get().joint_pain_area == "shoulder"


def test_program_typo_is_an_error_not_a_second_session(mike, tmp_path):
    """Review #8."""
    with pytest.raises(CommandError, match="Line 3: session columns differ .*program"):
        ingest(tmp_path, ROW1.replace(",RP,", ",RP Hypertrophy,"), ROW2.replace(",RP,", ",RP  hypertrophy,"))
    assert TrainingSession.objects.count() == 0


def test_repeated_columns_are_rejected(mike, tmp_path):
    """Review #9."""
    p = tmp_path / "dup.csv"
    p.write_text("started_at,order,exercise,muscle_group,reps,reps\n2026-11-10 18:00,1,row,back,8,10\n",
                 encoding="utf-8")
    with pytest.raises(CommandError, match="Repeated columns: reps"):
        call_command("ingest_training_csv", str(p), stdout=StringIO())


def test_report_only_loads_the_window(mike, tmp_path, django_assert_max_num_queries):
    """Review #6: a long history does not add per-set queries to a short report."""
    rows = [f"2026-{m:02d}-{d:02d} 18:00,RP,,,no,gym,,1,row,back,50,10,2,,,,," for m in (9, 10) for d in (1, 8, 15, 22)]
    ingest(tmp_path, *rows)
    with django_assert_max_num_queries(8):
        call_command("training_report", "--until", "2026-11-13", "--weeks", "1", stdout=StringIO())


def test_earlier_stop_signal_counted_in_the_database(mike, tmp_path):
    ingest(tmp_path, ROW1.replace(",2,,,,,", ",2,,,3,shoulder,"))
    correct_session_in_admin(mike)
    out = StringIO()
    call_command("training_report", "--until", "2026-11-25", "--weeks", "1", stdout=out)
    assert "Earlier stop signals before these weeks: 1" in out.getvalue()
