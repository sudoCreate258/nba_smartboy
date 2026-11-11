"""M3-T3: mini_puzzle probe kind and the Reset record."""
import datetime

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from core.models import Contributor, ProbeBaseline, ProbeSession, Reset, Supersession
from core.services.probe_report import SCORED_KINDS, kind_report
from twin_metrics import probes

UTC = datetime.timezone.utc
T = datetime.datetime(2026, 11, 11, 15, 0, tzinfo=UTC)
MIN = datetime.timedelta(minutes=1)


@pytest.fixture
def mike(db):
    return Contributor.objects.get(handle="mike")


def mini(mike, started_at, kind="mini_puzzle", contributor=None, **kw):
    kw.setdefault("accuracy_pct", 80)
    kw.setdefault("median_solve_s", 9)
    p = ProbeSession(contributor=contributor or mike, started_at=started_at, kind=kind, n_items=5, **kw)
    p.save()
    return p


def reset(mike, before, after, at=T, kind="walk", **kw):
    return Reset(contributor=mike, at=at, kind=kind, before_probe_cid=before.cid, after_probe_cid=after.cid, **kw)


# --- mini_puzzle kind -------------------------------------------------------

def test_mini_puzzle_is_a_scored_kind():
    assert probes.METRICS["mini_puzzle"] == [("accuracy_pct", "lower"), ("median_solve_s", "higher")]
    assert "mini_puzzle" in SCORED_KINDS


def test_mini_puzzle_gets_baseline_and_flags_like_any_kind(mike):
    start = datetime.datetime(2026, 10, 1, 15, 0, tzinfo=UTC)
    for i in range(10):
        mini(mike, start + datetime.timedelta(days=i), accuracy_pct=80 + 2 * (-1) ** i, median_solve_s=9 + (-1) ** i)
    for i in (10, 11, 12):
        mini(mike, start + datetime.timedelta(days=i), accuracy_pct=70, median_solve_s=12)
    r = kind_report(mike, "mini_puzzle")
    assert r["status"] == "ok" and r["n_baseline"] == 10 and r["n_scored"] == 3
    assert r["level"] == "red"


def test_mini_puzzle_baseline_can_be_configured(mike):
    ProbeBaseline(contributor=mike, kind="mini_puzzle", start=T, end=T + MIN).full_clean()


# --- Reset ------------------------------------------------------------------

def test_reset_saves_with_cid(mike):
    before, after = mini(mike, T - 10 * MIN), mini(mike, T + 15 * MIN)
    r = reset(mike, before, after, duration_min=10)
    r.save()
    r.refresh_from_db()
    assert r.cid.startswith("bafkrei") and r.kind == "walk"
    assert r.compute_cid() != reset(mike, before, after, kind="none", duration_min=10).compute_cid()


def test_none_is_the_control_condition(mike):
    before, after = mini(mike, T - MIN), mini(mike, T + MIN)
    reset(mike, before, after, kind="none").save()
    assert Reset.objects.get().kind == Reset.Kind.NONE


def test_probes_must_bracket_the_reset(mike):
    early, late = mini(mike, T - MIN), mini(mike, T + MIN)
    with pytest.raises(ValidationError) as exc:
        reset(mike, late, early).save()
    assert set(exc.value.message_dict) == {"before_probe_cid", "after_probe_cid"}
    with pytest.raises(ValidationError, match="start before"):
        reset(mike, early, late, at=T - MIN).save()  # before == at is not before


def test_probes_must_be_current_mini_puzzles_of_the_same_contributor(mike):
    before, after = mini(mike, T - MIN), mini(mike, T + MIN)
    full = mini(mike, T - 2 * MIN, kind="puzzle_set")
    sam = Contributor.objects.create(handle="sam")
    other = mini(mike, T + 2 * MIN, contributor=sam)
    with pytest.raises(ValidationError, match="mini_puzzle"):
        reset(mike, full, after).save()
    with pytest.raises(ValidationError, match="same contributor"):
        reset(mike, before, other).save()
    with pytest.raises(ValidationError, match="current probe session"):
        Reset(contributor=mike, at=T, kind="walk", before_probe_cid="bafkreinope", after_probe_cid=after.cid).save()
    fixed = mini(mike, T - MIN, accuracy_pct=60)
    Supersession.record(before, fixed)
    with pytest.raises(ValidationError, match="current probe session"):
        reset(mike, before, after).save()
    reset(mike, fixed, after).save()
    assert Reset.objects.count() == 1


@pytest.mark.parametrize("kw", [{"kind": "sauna"}, {"duration_min": 241}])
def test_field_validation(mike, kw):
    before, after = mini(mike, T - MIN), mini(mike, T + MIN)
    kw.setdefault("kind", "walk")
    with pytest.raises(ValidationError):
        reset(mike, before, after, **kw).save()


def test_admin_add_and_correction(admin_client, mike):
    before, after = mini(mike, T - MIN), mini(mike, T + 20 * MIN)
    post = {"contributor": mike.pk, "at_0": "2026-11-11", "at_1": "10:00:00", "kind": "walk", "duration_min": "10",
            "before_probe_cid": before.cid, "after_probe_cid": after.cid, "notes": ""}
    assert admin_client.post(reverse("admin:core_reset_add"), post).status_code == 302
    old = Reset.objects.get()
    resp = admin_client.post(reverse("admin:core_reset_changelist"),
                             {"action": "save_as_correction", "_selected_action": [old.pk]})
    assert admin_client.get(resp.url).status_code == 200
    assert admin_client.post(resp.url, {**post, "kind": "breathing"}).status_code == 302
    new = Reset.objects.exclude(pk=old.pk).get()
    assert list(Reset.objects.current()) == [new] and new.kind == "breathing"


def test_admin_shows_reference_errors_next_to_the_field(admin_client, mike):
    after = mini(mike, T + MIN)
    post = {"contributor": mike.pk, "at_0": "2026-11-11", "at_1": "10:00:00", "kind": "walk",
            "before_probe_cid": "bafkreinope", "after_probe_cid": after.cid, "notes": ""}
    resp = admin_client.post(reverse("admin:core_reset_add"), post)
    assert resp.status_code == 200 and b"Must be the CID of a current probe session." in resp.content
    assert Reset.objects.count() == 0
