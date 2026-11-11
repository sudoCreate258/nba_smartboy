"""M3-T2: DiscomfortCheck record, admin and corrections."""
import datetime

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from core.models import Contributor, DiscomfortCheck, ImmutableRecordError, Supersession

T = datetime.datetime(2026, 11, 11, 14, 0, tzinfo=datetime.timezone.utc)
POST = {"at_0": "2026-11-11", "at_1": "09:00:00", "area": "neck", "score": "4", "trigger": "end_of_block",
        "countermove": "chin_tuck_pullapart", "notes": ""}


@pytest.fixture
def mike(db):
    return Contributor.objects.get(handle="mike")


def check(mike, **kw):
    kw.setdefault("area", "neck")
    kw.setdefault("score", 3)
    kw.setdefault("trigger", "end_of_block")
    return DiscomfortCheck(contributor=mike, at=T, **kw)


def test_saves_with_cid_and_defaults(mike):
    c = check(mike)
    c.save()
    c.refresh_from_db()
    assert c.cid.startswith("bafkrei")
    assert c.countermove == "none" and c.sharp_or_numb is False


def test_cid_covers_stop_signal_and_record_is_immutable(mike):
    assert check(mike).compute_cid() != check(mike, sharp_or_numb=True).compute_cid()
    c = check(mike)
    c.save()
    c.score = 9
    with pytest.raises(ImmutableRecordError):
        c.save()
    with pytest.raises(ImmutableRecordError):
        DiscomfortCheck.objects.all().delete()


@pytest.mark.parametrize(
    "kw", [{"score": 11}, {"score": -1}, {"area": "knee"}, {"trigger": "gaming"}, {"countermove": "yoga"}]
)
def test_validation(mike, kw):
    with pytest.raises(ValidationError):
        check(mike, **kw).save()
    assert DiscomfortCheck.objects.count() == 0


@pytest.mark.parametrize("score", [0, 10])
def test_score_bounds_inclusive(mike, score):
    check(mike, score=score).save()


def test_naive_time_rejected(mike):
    with pytest.raises(ValidationError):
        DiscomfortCheck(contributor=mike, at=datetime.datetime(2026, 11, 11, 9), area="neck", score=2,
                        trigger="other").save()


def test_admin_add_and_changelist(admin_client, mike):
    resp = admin_client.post(reverse("admin:core_discomfortcheck_add"), {"contributor": mike.pk, **POST})
    assert resp.status_code == 302
    assert DiscomfortCheck.objects.get().countermove == "chin_tuck_pullapart"
    assert admin_client.get(reverse("admin:core_discomfortcheck_changelist") + "?sharp_or_numb__exact=0").status_code == 200


def test_admin_correction_records_supersession(admin_client, mike):
    old = check(mike)
    old.save()
    resp = admin_client.post(reverse("admin:core_discomfortcheck_changelist"),
                             {"action": "save_as_correction", "_selected_action": [old.pk]})
    assert resp.status_code == 302 and admin_client.get(resp.url).status_code == 200
    resp = admin_client.post(resp.url, {"contributor": mike.pk, **POST, "score": "6"})
    assert resp.status_code == 302
    new = DiscomfortCheck.objects.exclude(pk=old.pk).get()
    assert new.score == 6
    assert Supersession.objects.filter(old_cid=old.cid, new_cid=new.cid).exists()
    assert list(DiscomfortCheck.objects.current()) == [new]
