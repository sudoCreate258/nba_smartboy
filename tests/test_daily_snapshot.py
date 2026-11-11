import datetime
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.urls import reverse

from core.models import Contributor, DailySnapshot, ImmutableRecordError, Supersession
from core.services import CREATED, SKIPPED, SUPERSEDED, record_snapshot

D = datetime.date(2026, 11, 11)


@pytest.fixture
def mike(db):
    return Contributor.objects.get(handle="mike")


def snap(mike, **kw):
    kw.setdefault("date", D)
    kw.setdefault("source", "samsung_health")
    return DailySnapshot(contributor=mike, **kw)


def test_all_metrics_nullable_and_not_filled(mike):
    s = snap(mike)
    s.save()
    s.refresh_from_db()
    assert s.weight_kg is None and s.hrv is None and s.bedtime is None
    assert s.bia_timing == "unknown"


def test_cid_stable_across_float_string_decimal(mike):
    a = snap(mike, weight_kg=97.8, bedtime="22:54").compute_cid()
    b = snap(mike, weight_kg="97.8", bedtime=datetime.time(22, 54)).compute_cid()
    c = snap(mike, weight_kg=Decimal("97.80"), bedtime="22:54").compute_cid()
    assert a == b == c


def test_cid_changes_when_value_changes(mike):
    assert snap(mike, hrv=41).compute_cid() != snap(mike, hrv=42).compute_cid()


def test_cid_ignores_ingest_metadata(mike):
    # created_at is not content
    a = snap(mike, hrv=41)
    b = snap(mike, hrv=41)
    b.created_at = datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc)
    assert a.compute_cid() == b.compute_cid()


@pytest.mark.parametrize("field,value", [("body_fat_pct", 24.0), ("skeletal_muscle_kg", 40.6), ("bmr_kcal", 1900)])
def test_post_sauna_with_body_composition_rejected(mike, field, value):
    s = snap(mike, bia_timing="post_sauna", **{field: value})
    with pytest.raises(ValidationError):
        s.clean()
    with pytest.raises(ValidationError):
        s.save()
    assert DailySnapshot.objects.count() == 0


def test_post_sauna_without_body_composition_ok(mike):
    snap(mike, bia_timing="post_sauna", weight_kg=97.8).save()
    assert DailySnapshot.objects.count() == 1


def test_pre_session_with_body_composition_ok(mike):
    snap(mike, bia_timing="pre_session", body_fat_pct=24.0).save()
    assert DailySnapshot.objects.count() == 1


def test_snapshot_immutable(mike):
    s = snap(mike, hrv=41)
    s.save()
    s.hrv = 50
    with pytest.raises(ImmutableRecordError):
        s.save()


def test_service_created_skipped_superseded(mike):
    a, outcome = record_snapshot(snap(mike, hrv=41))
    assert outcome == CREATED and not Supersession.objects.exists()

    again, outcome = record_snapshot(snap(mike, hrv=41))
    assert outcome == SKIPPED and again.pk == a.pk

    b, outcome = record_snapshot(snap(mike, hrv=44))
    assert outcome == SUPERSEDED
    assert Supersession.objects.get().old_cid == a.cid and Supersession.objects.get().new_cid == b.cid
    assert DailySnapshot.objects.count() == 2


def test_one_current_per_contributor_per_date(mike):
    for hrv in (41, 44, 47):
        record_snapshot(snap(mike, hrv=hrv))
    record_snapshot(snap(mike, date=D + datetime.timedelta(days=1), hrv=41))
    current = DailySnapshot.objects.current().filter(contributor=mike, date=D)
    assert current.count() == 1
    assert current.get().hrv == 47
    assert DailySnapshot.objects.current().count() == 2


def test_service_rejects_post_sauna_body_comp(mike):
    with pytest.raises(ValidationError):
        record_snapshot(snap(mike, bia_timing="post_sauna", body_fat_pct=24.0))


@pytest.fixture
def admin_client(client, db):
    user = get_user_model().objects.create_superuser("root", "r@localhost", "pw")
    client.force_login(user)
    return client


def test_admin_existing_record_is_read_only(admin_client, mike):
    s, _ = record_snapshot(snap(mike, hrv=41))
    resp = admin_client.get(reverse("admin:core_dailysnapshot_change", args=[s.pk]))
    assert resp.status_code == 200
    assert b'name="hrv"' not in resp.content


def test_admin_save_as_correction_prefills_add_form(admin_client, mike):
    s, _ = record_snapshot(snap(mike, hrv=41, weight_kg=97.8))
    resp = admin_client.post(
        reverse("admin:core_dailysnapshot_changelist"),
        {"action": "save_as_correction", "_selected_action": [s.pk]},
    )
    assert resp.status_code == 302
    assert resp.url.startswith(reverse("admin:core_dailysnapshot_add"))
    assert "hrv=41" in resp.url and "weight_kg=97.8" in resp.url
    assert admin_client.get(resp.url).status_code == 200


def test_admin_add_supersedes_current(admin_client, mike):
    s, _ = record_snapshot(snap(mike, hrv=41))
    resp = admin_client.post(
        reverse("admin:core_dailysnapshot_add"),
        {"contributor": mike.pk, "date": "2026-11-11", "source": "manual", "bia_timing": "unknown", "hrv": 45, "notes": ""},
    )
    assert resp.status_code == 302
    new = DailySnapshot.objects.current().get(date=D)
    assert new.hrv == 45 and Supersession.objects.get().old_cid == s.cid


def test_revert_a_b_a_records_event_without_new_row(mike):
    a, _ = record_snapshot(snap(mike, hrv=41))
    b, _ = record_snapshot(snap(mike, hrv=44))
    again, outcome = record_snapshot(snap(mike, hrv=41))
    assert outcome == SUPERSEDED and again.pk == a.pk
    assert DailySnapshot.objects.count() == 2
    assert [(s.old_cid, s.new_cid) for s in Supersession.objects.order_by('id')] == [
        (a.cid, b.cid),
        (b.cid, a.cid),
    ]
    assert list(DailySnapshot.objects.current().filter(date=D)) == [a]


def test_reingest_of_current_is_noop_after_revert(mike):
    record_snapshot(snap(mike, hrv=41))
    record_snapshot(snap(mike, hrv=44))
    record_snapshot(snap(mike, hrv=41))
    _, outcome = record_snapshot(snap(mike, hrv=41))
    assert outcome == SKIPPED
    assert Supersession.objects.count() == 2



def test_direct_save_cannot_create_second_current_snapshot(mike):
    snap(mike, hrv=41).save()
    with pytest.raises(ValidationError):
        snap(mike, hrv=44).save()
    assert DailySnapshot.objects.count() == 1
    assert not Supersession.objects.exists()


def test_direct_save_with_supersede_records_event(mike):
    a = snap(mike, hrv=41)
    a.save()
    b = snap(mike, hrv=44)
    b.save(supersede=True)
    assert Supersession.objects.get().new_cid == b.cid
    assert list(DailySnapshot.objects.current().filter(date=D)) == [b]


def test_other_date_or_contributor_is_not_blocked(mike):
    snap(mike, hrv=41).save()
    snap(mike, date=D + datetime.timedelta(days=1), hrv=41).save()
    other = Contributor.objects.create(handle='other')
    snap(other, hrv=41).save()
    assert DailySnapshot.objects.current().count() == 3

