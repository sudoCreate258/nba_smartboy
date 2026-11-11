import datetime

import pytest

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

