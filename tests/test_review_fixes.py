import datetime
import os
import subprocess
import sys

import pytest
from django.core.exceptions import ValidationError

from core.models import (
    Contributor,
    DailySnapshot,
    ImmutableRecordError,
    ProbeSession,
)
from core.services import record_snapshot

D = datetime.date(2026, 1, 5)


@pytest.fixture
def mike(db):
    return Contributor.objects.get(handle="mike")


def snap(mike, **kw):
    kw.setdefault("date", D)
    kw.setdefault("source", DailySnapshot.Source.MANUAL)
    return DailySnapshot(contributor=mike, **kw)


@pytest.mark.parametrize(
    "kw",
    [
        {"source": "bogus"},
        {"bia_timing": "nope"},
        {"sleep_score": 90000},
        {"spo2": 150},
        {"body_fat_pct": 101},
        {"sleep_duration_min": 1441},
    ],
)
def test_snapshot_rejects_invalid_values(mike, kw):
    with pytest.raises(ValidationError):
        snap(mike, **kw).save()
    assert DailySnapshot.objects.count() == 0


def test_record_snapshot_rejects_invalid_values(mike):
    with pytest.raises(ValidationError):
        record_snapshot(snap(mike, source="bogus"))


def probe(mike, **kw):
    kw.setdefault("started_at", datetime.datetime(2026, 1, 5, 9, tzinfo=datetime.timezone.utc))
    kw.setdefault("kind", ProbeSession.Kind.PUZZLE_SET)
    return ProbeSession(contributor=mike, **kw)


@pytest.mark.parametrize(
    "kw",
    [
        {"kind": "bogus"},
        {"location": "moon"},
        {"accuracy_pct": 150},
        {"blunders": 2, "late_blunders": 3},
        {"blunders": 2, "fast_blunders": 3},
    ],
)
def test_probe_rejects_invalid_values(mike, kw):
    with pytest.raises(ValidationError):
        probe(mike, **kw).save()


def test_probe_valid_saves(mike):
    probe(mike, accuracy_pct=88.5, blunders=3, late_blunders=1, fast_blunders=2).save()


def test_queryset_update_and_delete_blocked(mike):
    s = snap(mike, weight_kg=80)
    s.save()
    qs = DailySnapshot.objects.filter(pk=s.pk)
    with pytest.raises(ImmutableRecordError):
        qs.update(weight_kg=90)
    with pytest.raises(ImmutableRecordError):
        qs.delete()
    with pytest.raises(ImmutableRecordError):
        DailySnapshot.objects.bulk_update([s], ["weight_kg"])
    with pytest.raises(ImmutableRecordError):
        s.delete()
    assert DailySnapshot.objects.get(pk=s.pk).weight_kg == 80


def test_supersede_must_match_contributor_and_date(mike, db):
    other = Contributor.objects.create(handle="other")
    old = snap(mike, weight_kg=80)
    old.save()
    with pytest.raises(ValidationError):
        snap(other, weight_kg=81, supersedes=old).save()
    with pytest.raises(ValidationError):
        snap(mike, date=D + datetime.timedelta(days=1), weight_kg=81, supersedes=old).save()
    snap(mike, weight_kg=81, supersedes=old).save()


def run_settings(env):
    base = {k: v for k, v in os.environ.items() if not k.startswith("DJANGO_")}
    base["DJANGO_SETTINGS_MODULE"] = "twin.settings"
    base.update(env)
    return subprocess.run(
        [sys.executable, "-c", "from django.conf import settings; print(settings.DEBUG)"],
        env=base,
        capture_output=True,
        text=True,
    )


def test_settings_fail_closed_without_secret():
    result = run_settings({})
    assert result.returncode != 0
    assert "DJANGO_SECRET_KEY" in result.stderr


def test_settings_debug_off_by_default():
    result = run_settings({"DJANGO_SECRET_KEY": "x"})
    assert result.stdout.strip() == "False"
