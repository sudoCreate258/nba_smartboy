"""M3.5-T1: TrainingSession and TrainingSet records, admin and corrections."""
import datetime
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from core.models import Contributor, ImmutableRecordError, Supersession, TrainingSession, TrainingSet

UTC = datetime.timezone.utc
T = datetime.datetime(2026, 11, 11, 23, 0, tzinfo=UTC)  # 18:00 New York


@pytest.fixture
def mike(db):
    return Contributor.objects.get(handle="mike")


def session(mike, **kw):
    kw.setdefault("program", "RP Hypertrophy")
    s = TrainingSession(contributor=mike, started_at=kw.pop("started_at", T), **kw)
    s.save()
    return s


def tset(mike, sess, **kw):
    kw.setdefault("order", 1)
    kw.setdefault("exercise", "Bench Press")
    kw.setdefault("muscle_group", "chest")
    kw.setdefault("reps", 10)
    return TrainingSet(contributor=mike, session_cid=sess.cid, **kw)


def test_session_saves_with_cid(mike):
    s = session(mike, mesocycle="Meso 1", meso_week=2, is_deload=False, location="gym", session_rpe="7.5")
    s.refresh_from_db()
    assert s.cid.startswith("bafkrei") and s.session_rpe == Decimal("7.5")


@pytest.mark.parametrize("kw", [{"meso_week": 0}, {"session_rpe": "10.5"}, {"location": "park"},
                                {"ended_at": T - datetime.timedelta(minutes=1)}])
def test_session_validation(mike, kw):
    with pytest.raises(ValidationError):
        session(mike, **kw)


def test_exercise_is_normalized_before_hashing(mike):
    s = session(mike)
    a, b = tset(mike, s, exercise="  Bench   Press "), tset(mike, s, exercise="bench press")
    assert a.compute_cid() == b.compute_cid()
    a.save()
    a.refresh_from_db()
    assert a.exercise == "bench press"


def test_set_saves_and_is_immutable(mike):
    s = session(mike)
    x = tset(mike, s, load_kg="80", rir=2, pump=2, soreness_before=1, joint_pain=0)
    x.save()
    x.refresh_from_db()
    assert x.load_kg == Decimal("80.0") and x.rir == 2
    x.reps = 12
    with pytest.raises(ImmutableRecordError):
        x.save()


@pytest.mark.parametrize("kw", [{"order": 0}, {"reps": -1}, {"rir": 11}, {"pump": 4}, {"soreness_before": 4},
                                {"joint_pain": 4}, {"joint_pain_area": "knee"}, {"muscle_group": "neck"},
                                {"load_kg": "-1"}, {"load_kg": "80.25"}])
def test_set_validation(mike, kw):
    s = session(mike)
    with pytest.raises(ValidationError):
        tset(mike, s, **kw).save()
    assert TrainingSet.objects.count() == 0


def test_session_reference_must_be_current_and_same_contributor(mike):
    s = session(mike)
    with pytest.raises(ValidationError, match="current training session"):
        TrainingSet(contributor=mike, session_cid="bafkreinope", order=1, exercise="row", muscle_group="back",
                    reps=8).save()
    sam = Contributor.objects.create(handle="sam")
    with pytest.raises(ValidationError, match="same contributor"):
        TrainingSet(contributor=sam, session_cid=s.cid, order=1, exercise="row", muscle_group="back", reps=8).save()
    fixed = session(mike, program="RP Hypertrophy v2")
    Supersession.record(s, fixed)
    with pytest.raises(ValidationError, match="current training session"):
        tset(mike, s).save()


def test_order_is_unique_per_session_except_for_corrections(mike):
    s = session(mike)
    first = tset(mike, s)
    first.save()
    with pytest.raises(ValidationError, match="Set 1 already exists"):
        tset(mike, s, reps=8).save()
    fix = tset(mike, s, reps=8)
    fix.replaces_cid = first.cid
    fix.save()
    Supersession.record(first, fix)
    tset(mike, s, order=2).save()
    tset(mike, s, order=2).full_clean(exclude=["cid"])  # an identical set is a duplicate, not a clash
    assert TrainingSet.objects.current().count() == 2


def test_stop_signal_threshold(mike):
    s = session(mike)
    assert tset(mike, s, joint_pain=2).is_stop_signal and not tset(mike, s, joint_pain=1).is_stop_signal
    assert not tset(mike, s).is_stop_signal


def test_admin_session_page_lists_sets_and_add_link(admin_client, mike):
    s = session(mike)
    tset(mike, s, joint_pain=2, joint_pain_area="shoulder").save()
    page = admin_client.get(reverse("admin:core_trainingsession_change", args=[s.pk]))
    assert page.status_code == 200
    assert b"bench press" in page.content and b"Add a set to this session" in page.content
    add = admin_client.get(reverse("admin:core_trainingset_add") + f"?contributor={mike.pk}&session_cid={s.cid}")
    assert add.status_code == 200 and s.cid.encode() in add.content


def test_admin_add_set_and_correct(admin_client, mike):
    s = session(mike)
    post = {"contributor": mike.pk, "session_cid": s.cid, "order": "1", "exercise": "Squat", "muscle_group": "quads",
            "load_kg": "100", "reps": "6", "rir": "2", "notes": ""}
    assert admin_client.post(reverse("admin:core_trainingset_add"), post).status_code == 302
    old = TrainingSet.objects.get()
    resp = admin_client.post(reverse("admin:core_trainingset_changelist"),
                             {"action": "save_as_correction", "_selected_action": [old.pk]})
    assert admin_client.get(resp.url).status_code == 200
    assert admin_client.post(resp.url, {**post, "reps": "7"}).status_code == 302
    assert [x.reps for x in TrainingSet.objects.current()] == [7]


def test_admin_session_correction(admin_client, mike):
    s = session(mike)
    post = {"contributor": mike.pk, "started_at_0": "2026-11-11", "started_at_1": "18:00:00", "program": "RP",
            "mesocycle": "", "notes": ""}
    resp = admin_client.post(reverse("admin:core_trainingsession_changelist"),
                             {"action": "save_as_correction", "_selected_action": [s.pk]})
    assert admin_client.get(resp.url).status_code == 200
    assert admin_client.post(resp.url, post).status_code == 302
    assert [x.program for x in TrainingSession.objects.current()] == ["RP"]
