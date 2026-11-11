import datetime
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from core.models import Contributor, ProbeSession

T = datetime.datetime(2026, 11, 11, 9, 0, tzinfo=datetime.timezone.utc)

# CIDs computed before M2 added any field; they must never change.
GOLDEN_RAPID = "bafkreieb5drt2i5amvimrvaqkkdxhuwc2c26wdh5wetfqeqd434abzmz5u"
GOLDEN_PUZZLE = "bafkreibwnv6yfbejtoi5psanj4jdpq4qfbjftrcqgkmpnlrjfeqlnkwory"


@pytest.fixture
def mike(db):
    return Contributor.objects.get(handle="mike")


def rapid(mike, **kw):
    return ProbeSession(
        contributor=mike, started_at=T, kind="rapid_game",
        accuracy_pct="81.5", late_blunders=1, blunders=2, **kw,
    )


def puzzle(mike):
    return ProbeSession(
        contributor=mike, started_at=T, kind="puzzle_set",
        n_items=20, accuracy_pct="90", median_solve_s="12.5",
    )


def test_existing_cids_unchanged(mike):
    assert rapid(mike).compute_cid() == GOLDEN_RAPID
    assert puzzle(mike).compute_cid() == GOLDEN_PUZZLE


def test_null_omit_if_null_field_is_left_out(mike, monkeypatch):
    monkeypatch.setattr(ProbeSession, "OMIT_IF_NULL", ("n_items", "own_rating"))
    fields = puzzle(mike).domain_fields()
    assert "n_items" in fields  # set, so kept
    assert "own_rating" not in fields  # null and listed, so omitted
    assert "opponent_rating" in fields and fields["opponent_rating"] is None  # null, not listed: kept



def test_move_time_cv_is_in_cid_only_when_set(mike):
    base = rapid(mike)
    with_cv = rapid(mike, move_time_cv="0.45")
    assert "move_time_cv" not in base.domain_fields()
    assert with_cv.domain_fields()["move_time_cv"] == Decimal("0.45")
    assert with_cv.compute_cid() != base.compute_cid()
    assert rapid(mike, move_time_cv=0.45).compute_cid() == with_cv.compute_cid()


def test_move_time_cv_saves_and_rejects_bad_values(mike):
    p = rapid(mike, move_time_cv="0.45")
    p.save()
    p.refresh_from_db()
    assert p.move_time_cv == Decimal("0.45")
    for bad in ("-0.01", "0.456", "nan"):
        with pytest.raises(ValidationError):
            rapid(mike, move_time_cv=bad, notes=bad).save()


def test_admin_adds_probe_with_move_time_cv(admin_client, mike):
    post = {"contributor": mike.pk, "started_at_0": "2026-11-11", "started_at_1": "09:00:00",
            "kind": "rapid_game", "move_time_cv": "0.62", "notes": ""}
    assert admin_client.post(reverse("admin:core_probesession_add"), post).status_code == 302
    assert ProbeSession.objects.get().move_time_cv == Decimal("0.62")
    assert admin_client.get(reverse("admin:core_probesession_changelist")).status_code == 200