"""M3-T4: WeeklyCheck record (burnout self-check) and admin."""
import datetime
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from core.models import Contributor, WeeklyCheck

MONDAY = datetime.date(2026, 11, 9)


@pytest.fixture
def mike(db):
    return Contributor.objects.get(handle="mike")


def weekly(mike, **kw):
    kw.setdefault("week_start", MONDAY)
    kw.setdefault("instrument", "OLBI")
    kw.setdefault("score", "2.40")
    kw.setdefault("scale_max", "4")
    return WeeklyCheck(contributor=mike, **kw)


def test_saves_with_cid_and_decimal_score(mike):
    w = weekly(mike)
    w.save()
    w.refresh_from_db()
    assert w.cid.startswith("bafkrei") and w.score == Decimal("2.40")
    assert weekly(mike, score=2.4).compute_cid() == w.compute_cid()


@pytest.mark.parametrize(
    "kw,field",
    [
        ({"week_start": MONDAY + datetime.timedelta(days=1)}, "week_start"),
        ({"score": "5", "scale_max": "4"}, "score"),
        ({"score": "-1"}, "score"),
        ({"scale_max": "0"}, "scale_max"),
        ({"instrument": "  "}, "instrument"),
        ({"score": "nan"}, "score"),
    ],
)
def test_validation(mike, kw, field):
    with pytest.raises(ValidationError) as exc:
        weekly(mike, **kw).save()
    assert field in exc.value.message_dict
    assert WeeklyCheck.objects.count() == 0


def test_score_equal_to_scale_max_is_fine(mike):
    weekly(mike, score="4", scale_max="4").save()


def test_no_item_text_field():
    names = {f.name for f in WeeklyCheck._meta.fields}
    assert names == {"id", "cid", "contributor", "created_at", "week_start", "instrument", "score", "scale_max", "notes"}


def test_admin_add_and_correction(admin_client, mike):
    post = {"contributor": mike.pk, "week_start": "2026-11-09", "instrument": "OLBI", "score": "2.4",
            "scale_max": "4", "notes": ""}
    assert admin_client.post(reverse("admin:core_weeklycheck_add"), post).status_code == 302
    old = WeeklyCheck.objects.get()
    resp = admin_client.post(reverse("admin:core_weeklycheck_changelist"),
                             {"action": "save_as_correction", "_selected_action": [old.pk]})
    assert admin_client.get(resp.url).status_code == 200
    assert admin_client.post(resp.url, {**post, "score": "2.6"}).status_code == 302
    assert [w.score for w in WeeklyCheck.objects.current()] == [Decimal("2.60")]
