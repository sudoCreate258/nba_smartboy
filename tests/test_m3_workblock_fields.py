"""M3-T1: WorkBlock posture and planned_length_min, both in OMIT_IF_NULL."""
import datetime

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from core.models import Contributor, WorkBlock

T = datetime.datetime(2026, 11, 11, 9, 0, tzinfo=datetime.timezone.utc)

# Computed before M3 added posture and planned_length_min; must never change.
GOLDEN_WORK_BLOCK = "bafkreih7fmpmlnhro5k47qqxc6qiyp7xyyfps6p46wjworn3uw7u2xc3ee"


@pytest.fixture
def mike(db):
    return Contributor.objects.get(handle="mike")


def block(mike, **kw):
    return WorkBlock(contributor=mike, start=T, end=T + datetime.timedelta(minutes=50), task_type="code",
                     location="remote", interruptions=1, absorption=4, effort=3, **kw)


def test_pre_m3_work_block_cid_unchanged(mike):
    assert block(mike).compute_cid() == GOLDEN_WORK_BLOCK


def test_new_fields_enter_the_cid_only_when_set(mike):
    base = block(mike)
    assert "posture" not in base.domain_fields() and "planned_length_min" not in base.domain_fields()
    sit = block(mike, posture="sit")
    planned = block(mike, planned_length_min=50)
    assert len({base.compute_cid(), sit.compute_cid(), planned.compute_cid()}) == 3
    assert WorkBlock.OMIT_IF_NULL == ("posture", "planned_length_min")


def test_new_fields_save(mike):
    b = block(mike, posture="mixed", planned_length_min=25)
    b.save()
    b.refresh_from_db()
    assert (b.posture, b.planned_length_min) == ("mixed", 25)


@pytest.mark.parametrize("kw", [{"posture": "lying"}, {"planned_length_min": 0}, {"planned_length_min": 241}])
def test_new_fields_validated(mike, kw):
    with pytest.raises(ValidationError):
        block(mike, **kw).save()


def test_admin_add_with_posture(admin_client, mike):
    post = {"contributor": mike.pk, "start_0": "2026-11-11", "start_1": "09:00:00", "end_0": "2026-11-11",
            "end_1": "09:50:00", "task_type": "code", "posture": "stand", "planned_length_min": "50", "notes": ""}
    assert admin_client.post(reverse("admin:core_workblock_add"), post).status_code == 302
    assert WorkBlock.objects.get().posture == "stand"
    assert admin_client.get(reverse("admin:core_workblock_changelist") + "?posture=stand").status_code == 200
