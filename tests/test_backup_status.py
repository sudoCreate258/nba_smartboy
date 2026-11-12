"""M4.5-T5: backup status on the home page and in /api/v0/today (R9)."""
import datetime

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from backup.models import BackupRun
from backup.status import backup_status

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 11, 12, 15, 0, tzinfo=UTC)


def run(hours_ago, status="ok", uploaded=True, error=""):
    t = NOW - datetime.timedelta(hours=hours_ago)
    return BackupRun.objects.create(started_at=t, finished_at=t, trigger="nightly", status=status,
                                    set_name=t.strftime("%Y-%m-%dT%H%M%SZ"), size_bytes=2_500_000,
                                    uploaded=uploaded, verified=status == "ok", error=error)


@pytest.mark.django_db
def test_not_set_up_and_never_ran(settings):
    settings.BACKUP_REMOTE = ""
    assert backup_status(NOW)["level"] == "not_set_up"
    settings.BACKUP_REMOTE = "vault:"
    assert backup_status(NOW)["level"] == "red"


@pytest.mark.django_db
@pytest.mark.parametrize("hours,level", [(10, "ok"), (48, "ok"), (49, "amber"), (24 * 7, "amber"),
                                         (24 * 7 + 1, "red")])
def test_age_thresholds(hours, level):
    run(hours)
    s = backup_status(NOW)
    assert s["level"] == level and s["verified"] is True and s["size_bytes"] == 2_500_000


@pytest.mark.django_db
def test_failed_verify_is_red_even_with_a_recent_good_set():
    run(30)
    run(2, status="failed", uploaded=True, error="verify: twin.dump does not match its SHA-256 in the manifest")
    s = backup_status(NOW)
    assert s["level"] == "red" and "failed at verify" in s["detail"]
    assert s["last_ok_at"] == NOW - datetime.timedelta(hours=30)  # the last good set is still reported


@pytest.mark.django_db
def test_running_attempt_does_not_hide_the_last_result():
    run(5)
    BackupRun.objects.create(started_at=NOW, trigger="nightly", status="running")
    assert backup_status(NOW)["level"] == "ok"


@pytest.fixture
def client_in(client, db):
    client.force_login(get_user_model().objects.create_user("owner", password="a-long-test-password"))
    return client


def test_home_and_api_show_backup_status(client_in, settings):
    settings.BACKUP_REMOTE = "vault:"
    BackupRun.objects.create(started_at=datetime.datetime.now(UTC), finished_at=datetime.datetime.now(UTC),
                             trigger="manual", status="ok", set_name="x", size_bytes=2_500_000, uploaded=True,
                             verified=True)
    html = client_in.get(reverse("ui:home")).content.decode()
    assert "Backup" in html and "flag-ok" in html and "Last backup 0 h ago, verified." in html and "2.4" in html
    api = client_in.get(reverse("ui:api_today")).json()["today"]["backup"]
    assert api["level"] == "ok" and api["verified"] is True and api["size_bytes"] == 2_500_000


def test_home_shows_not_set_up(client_in, settings):
    settings.BACKUP_REMOTE = ""
    assert "not set up" in client_in.get(reverse("ui:home")).content.decode()
