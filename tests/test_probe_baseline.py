import datetime

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse

from core.models import Contributor, ProbeBaseline, ProbeSession, Supersession
from core.services.probe_report import baseline_window, current_sessions

UTC = datetime.timezone.utc


@pytest.fixture
def mike(db):
    return Contributor.objects.get(handle="mike")


def at(day):
    return datetime.datetime(2026, 10, 1, 9, 0, tzinfo=UTC) + datetime.timedelta(days=day)


def make(mike, day, kind="puzzle_set", **kw):
    p = ProbeSession(contributor=mike, started_at=at(day), kind=kind, accuracy_pct=80, **kw)
    p.save()
    return p


def test_default_window_is_first_ten_current_sessions(mike):
    sessions = [make(mike, d) for d in range(13)]
    w = baseline_window(mike, "puzzle_set")
    assert w["source"] == "default"
    assert w["baseline"] == sessions[:10] and w["after"] == sessions[10:]
    assert (w["start"], w["end"]) == (at(0), at(9))


def test_default_window_with_no_sessions(mike):
    w = baseline_window(mike, "puzzle_set")
    assert w["baseline"] == [] and w["after"] == [] and w["start"] is None


def test_default_window_ignores_superseded_and_other_kinds(mike):
    old = make(mike, 0)
    corrected = ProbeSession(contributor=mike, started_at=at(0), kind="puzzle_set", accuracy_pct=70)
    corrected.save()
    Supersession.record(old, corrected)
    make(mike, 1, kind="rapid_game")
    assert current_sessions(mike, "puzzle_set") == [corrected]


def test_ties_ordered_by_cid(mike):
    a = make(mike, 0, n_items=1)
    b = make(mike, 0, n_items=2)
    assert current_sessions(mike, "puzzle_set") == sorted([a, b], key=lambda s: s.cid)


def test_configured_window_overrides_default(mike):
    sessions = [make(mike, d) for d in range(8)]
    ProbeBaseline.objects.create(contributor=mike, kind="puzzle_set", start=at(1), end=at(3))
    w = baseline_window(mike, "puzzle_set")
    assert w["source"] == "configured"
    assert w["baseline"] == sessions[1:4] and w["after"] == sessions[4:]


def test_configured_window_is_per_kind_and_newest_wins(mike):
    ProbeBaseline.objects.create(contributor=mike, kind="puzzle_set", start=at(0), end=at(1),
                                 frozen_at=at(20))
    ProbeBaseline.objects.create(contributor=mike, kind="puzzle_set", start=at(2), end=at(3),
                                 frozen_at=at(21))
    make(mike, 2, kind="rapid_game")
    assert baseline_window(mike, "puzzle_set")["start"] == at(2)
    assert baseline_window(mike, "rapid_game")["source"] == "default"


def test_baseline_has_no_cid_and_is_not_a_record():
    assert not hasattr(ProbeBaseline, "cid")


def test_baseline_validation(mike):
    with pytest.raises(ValidationError):
        ProbeBaseline(contributor=mike, kind="module", start=at(0), end=at(1)).full_clean()
    with pytest.raises(ValidationError):
        ProbeBaseline(contributor=mike, kind="puzzle_set", start=at(2), end=at(1)).full_clean()
    with pytest.raises(IntegrityError), transaction.atomic():
        ProbeBaseline.objects.create(contributor=mike, kind="puzzle_set", start=at(2), end=at(1))


def test_baseline_admin(admin_client, mike):
    post = {"contributor": mike.pk, "kind": "puzzle_set", "start_0": "2026-10-01", "start_1": "09:00:00",
            "end_0": "2026-10-10", "end_1": "09:00:00", "frozen_at_0": "2026-10-11", "frozen_at_1": "08:00:00"}
    assert admin_client.post(reverse("admin:core_probebaseline_add"), post).status_code == 302
    assert ProbeBaseline.objects.count() == 1
    assert admin_client.get(reverse("admin:core_probebaseline_changelist") + "?kind=puzzle_set").status_code == 200
