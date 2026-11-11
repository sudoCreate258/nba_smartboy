import datetime
import re
from io import StringIO
from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse

from core.models import Contributor, DailySnapshot, Supersession, WorkBlock
from core.services import record_snapshot

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def mike(db):
    return Contributor.objects.get(handle="mike")


@pytest.mark.parametrize("value", [datetime.datetime(2026, 11, 11, 7, 0), "2026-11-11T07:00:00"])
def test_record_snapshot_naive_datetime_is_validation_error(mike, value):
    snap = DailySnapshot(contributor=mike, date=datetime.date(2026, 11, 11), source="manual", wake_time=value)
    with pytest.raises(ValidationError):
        record_snapshot(snap)
    assert DailySnapshot.objects.count() == 0


def _block(mike):
    b = WorkBlock(
        contributor=mike,
        start=datetime.datetime(2026, 11, 11, 9, 0, tzinfo=datetime.timezone.utc),
        end=datetime.datetime(2026, 11, 11, 10, 0, tzinfo=datetime.timezone.utc),
        task_type="code",
    )
    b.save()
    return b


POST = {"start_0": "2026-11-12", "start_1": "09:00:00", "end_0": "2026-11-12", "end_1": "10:00:00",
        "task_type": "code", "notes": ""}


def test_admin_correction_unknown_supersedes_is_form_error(admin_client, mike):
    _block(mike)
    url = reverse("admin:core_workblock_add") + "?supersedes=nope"
    resp = admin_client.post(url, {"contributor": mike.pk, **POST})
    assert resp.status_code == 200
    assert b"does not exist" in resp.content
    assert WorkBlock.objects.count() == 1


def test_admin_correction_other_contributor_is_form_error(admin_client, mike):
    old = _block(mike)
    other = Contributor.objects.create(handle="sam")
    url = reverse("admin:core_workblock_add") + f"?supersedes={old.cid}"
    resp = admin_client.post(url, {"contributor": other.pk, **POST})
    assert resp.status_code == 200
    assert b"same contributor" in resp.content
    assert WorkBlock.objects.count() == 1 and Supersession.objects.count() == 0


def test_migration_0008_has_spdx_header():
    first = (ROOT / "core/migrations/0008_validation_bounds.py").read_text(encoding="utf-8").splitlines()[0]
    assert first == "# SPDX-License-Identifier: AGPL-3.0-or-later"


def test_agents_dir_is_gitignored():
    assert ".agents/" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()


def _ingest(tmp_path, text):
    p = tmp_path / "in.yaml"
    p.write_text(text, encoding="utf-8")
    call_command("ingest_yaml", str(p), stdout=StringIO())


@pytest.mark.parametrize(
    "wake",
    [
        "2026-11-01 01:30:00",  # ambiguous: clocks go back in America/New_York
        "2026-03-08 02:30:00",  # nonexistent: clocks go forward
    ],
)
def test_ingest_rejects_dst_ambiguous_or_nonexistent_times(db, tmp_path, wake):
    day = wake[:10]
    with pytest.raises(CommandError, match=r"wake_time: .*(ambiguous|does not exist)"):
        _ingest(tmp_path, f"date: {day}\nsource: manual\nwake_time: '{wake}'\n")
    assert DailySnapshot.objects.count() == 0


def test_ingest_accepts_unambiguous_local_time_and_explicit_offset(db, tmp_path):
    _ingest(tmp_path, "- {date: 2026-11-10, source: manual, wake_time: '2026-11-10 07:00:00'}\n"
                      "- {date: 2026-11-01, source: manual, wake_time: '2026-11-01T01:30:00-04:00'}\n")
    assert DailySnapshot.objects.count() == 2
