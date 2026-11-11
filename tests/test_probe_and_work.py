import datetime

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse

from core.models import Contributor, ImmutableRecordError, ProbeSession, ProvenancedRecord, WorkBlock

T0 = datetime.datetime(2026, 11, 11, 9, 0, tzinfo=datetime.timezone.utc)


@pytest.fixture
def mike(db):
    return Contributor.objects.get(handle="mike")


def block(mike, **kw):
    kw.setdefault("start", T0)
    kw.setdefault("end", T0 + datetime.timedelta(minutes=90))
    kw.setdefault("task_type", "code")
    return WorkBlock(contributor=mike, **kw)


def test_probe_session_saves_with_cid_and_nulls(mike):
    p = ProbeSession.objects.create(contributor=mike, started_at=T0, kind="puzzle_set", accuracy_pct=82.5, n_items=20)
    p.refresh_from_db()
    assert p.cid.startswith("bafkrei")
    assert p.blunders is None and p.location is None
    assert p.accuracy_pct == 82.5


def test_probe_session_cid_sensitive_and_immutable(mike):
    a = ProbeSession(contributor=mike, started_at=T0, kind="puzzle_set", blunders=1)
    b = ProbeSession(contributor=mike, started_at=T0, kind="puzzle_set", blunders=2)
    assert a.compute_cid() != b.compute_cid()
    a.save()
    a.blunders = 3
    with pytest.raises(ImmutableRecordError):
        a.save()


def test_work_block_duration_is_derived(mike):
    b = block(mike)
    b.save()
    assert b.duration == datetime.timedelta(minutes=90)
    assert "duration" not in [f.name for f in WorkBlock._meta.get_fields()]


@pytest.mark.parametrize("delta", [0, -5])
def test_work_block_end_must_be_after_start(mike, delta):
    b = block(mike, end=T0 + datetime.timedelta(minutes=delta))
    with pytest.raises(ValidationError):
        b.clean()
    with pytest.raises(ValidationError):
        b.save()


def test_work_block_db_constraint_end_after_start(mike):
    b = block(mike, end=T0 - datetime.timedelta(minutes=1))
    with pytest.raises(IntegrityError), transaction.atomic():
        b.cid = b.compute_cid()
        super(ProvenancedRecord, b).save()  # skip model validation


@pytest.mark.parametrize("field", ["absorption", "effort"])
@pytest.mark.parametrize("value", [0, 6])
def test_work_block_scores_range(mike, field, value):
    with pytest.raises(ValidationError):
        block(mike, **{field: value}).save()


def test_work_block_scores_valid(mike):
    block(mike, absorption=1, effort=5, interruptions=2, location="remote").save()
    assert WorkBlock.objects.count() == 1


@pytest.fixture
def admin_client(client, db):
    user = get_user_model().objects.create_superuser("root", "r@localhost", "pw")
    client.force_login(user)
    return client


@pytest.mark.parametrize("model", ["probesession", "workblock"])
def test_admin_changelists_load(admin_client, model):
    assert admin_client.get(reverse(f"admin:core_{model}_changelist")).status_code == 200


def test_admin_work_block_add_and_read_only(admin_client, mike):
    resp = admin_client.post(
        reverse("admin:core_workblock_add"),
        {
            "contributor": mike.pk,
            "start_0": "2026-11-11",
            "start_1": "09:00:00",
            "end_0": "2026-11-11",
            "end_1": "10:30:00",
            "task_type": "code",
            "notes": "",
        },
    )
    assert resp.status_code == 302
    wb = WorkBlock.objects.get()
    page = admin_client.get(reverse("admin:core_workblock_change", args=[wb.pk]))
    assert page.status_code == 200 and b'name="task_type"' not in page.content


def test_admin_work_block_end_before_start_shows_error(admin_client, mike):
    resp = admin_client.post(
        reverse("admin:core_workblock_add"),
        {
            "contributor": mike.pk,
            "start_0": "2026-11-11",
            "start_1": "10:00:00",
            "end_0": "2026-11-11",
            "end_1": "09:00:00",
            "task_type": "code",
            "notes": "",
        },
    )
    assert resp.status_code == 200
    assert WorkBlock.objects.count() == 0


@pytest.mark.parametrize(
    "model,make,field,new_value,post",
    [
        (
            "probesession",
            lambda m: ProbeSession(contributor=m, started_at=T0, kind="puzzle_set", n_items=20),
            "n_items",
            25,
            {"started_at_0": "2026-11-11", "started_at_1": "09:00:00", "kind": "puzzle_set", "n_items": "25", "notes": ""},
        ),
        (
            "workblock",
            lambda m: block(m),
            "task_type",
            "study",
            {"start_0": "2026-11-11", "start_1": "09:00:00", "end_0": "2026-11-11", "end_1": "10:30:00", "task_type": "study", "notes": ""},
        ),
    ],
)
def test_admin_correction_records_supersession(admin_client, mike, model, make, field, new_value, post):
    from core.models import Supersession

    old = make(mike)
    old.save()
    resp = admin_client.post(
        reverse(f"admin:core_{model}_changelist"),
        {"action": "save_as_correction", "_selected_action": [old.pk]},
    )
    assert resp.status_code == 302
    assert admin_client.get(resp.url).status_code == 200  # prefilled add form renders
    resp = admin_client.post(resp.url, {"contributor": mike.pk, **post})
    assert resp.status_code == 302
    cls = type(old)
    new = cls.objects.exclude(pk=old.pk).get()
    assert getattr(new, field) == new_value
    sup = Supersession.objects.get()
    assert (sup.old_cid, sup.new_cid) == (old.cid, new.cid)
    assert list(cls.objects.current()) == [new]


def test_admin_correction_identical_record_writes_nothing(admin_client, mike):
    from core.models import Supersession

    old = block(mike)
    old.save()
    post = {"contributor": mike.pk, "start_0": "2026-11-11", "start_1": "04:00:00",
            "end_0": "2026-11-11", "end_1": "05:30:00", "task_type": "code", "notes": ""}
    url = reverse("admin:core_workblock_add") + f"?supersedes={old.cid}"
    assert admin_client.post(url, post).status_code == 302
    assert WorkBlock.objects.count() == 1 and Supersession.objects.count() == 0


def test_admin_correction_action_needs_exactly_one(admin_client, mike):
    later = T0 + datetime.timedelta(hours=2)  # blocks of one contributor may not overlap
    a, b = block(mike), block(mike, task_type="admin", start=later, end=later + datetime.timedelta(minutes=30))
    a.save()
    b.save()
    resp = admin_client.post(
        reverse("admin:core_workblock_changelist"),
        {"action": "save_as_correction", "_selected_action": [a.pk, b.pk]},
        follow=True,
    )
    assert b"Select exactly one record." in resp.content
