"""M4.5-T4: backup_now and backup_loop (R6)."""
import datetime
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from backup.management.commands import backup_loop
from backup.models import BackupRun
from core.models import Contributor
from tests.backup_helpers import crypt_remote

UTC = datetime.timezone.utc


@pytest.fixture(scope="module", autouse=True)
def restore_migration_data(django_db_blocker):
    """The transactional test below flushes the database; put the data migration's contributor back."""
    yield
    with django_db_blocker.unblock():
        Contributor.objects.get_or_create(handle="mike", defaults={"timezone": "America/New_York"})


def fake_run(calls):
    def run(trigger, now=None, **kw):
        calls.append((trigger, now))
        return BackupRun.objects.create(started_at=now, finished_at=now, trigger=trigger, status="ok",
                                        set_name=now.strftime("%Y-%m-%dT%H%M%SZ"), uploaded=True, verified=True,
                                        size_bytes=1000)
    return run


@pytest.mark.django_db
def test_loop_runs_once_per_night_and_catches_up(monkeypatch, settings):
    settings.BACKUP_WINDOW = "02:00-05:00"
    calls = []
    monkeypatch.setattr(backup_loop, "run_backup", fake_run(calls))
    ny_0230 = datetime.datetime(2026, 11, 12, 7, 30, tzinfo=UTC)
    assert backup_loop.check_once(ny_0230)[0] is True
    assert backup_loop.check_once(ny_0230 + datetime.timedelta(hours=1))[0] is False  # same night
    # Asleep through the next window; wakes at 09:00 New York: one catch-up run, then nothing.
    wake = datetime.datetime(2026, 11, 13, 14, 0, tzinfo=UTC)
    ran, message = backup_loop.check_once(wake)
    assert ran and message.startswith("catch-up")
    assert backup_loop.check_once(wake + datetime.timedelta(hours=3))[0] is False
    assert [c[0] for c in calls] == ["nightly", "nightly"]


@pytest.mark.django_db
def test_loop_command_once(monkeypatch):
    calls = []
    monkeypatch.setattr(backup_loop, "run_backup", fake_run(calls))
    out = StringIO()
    call_command("backup_loop", "--once", "--now", "2026-11-12T07:30:00+00:00", stdout=out)
    assert "inside the backup window" in out.getvalue() and len(calls) == 1
    out = StringIO()
    call_command("backup_loop", "--once", "--now", "2026-11-12T08:30:00+00:00", stdout=out)
    assert "already ran this night" in out.getvalue() and len(calls) == 1


@pytest.mark.django_db
def test_loop_keeps_going_when_a_check_fails(monkeypatch):
    def broken(now=None):
        raise RuntimeError("database restarting")
    monkeypatch.setattr(backup_loop, "check_once", broken)
    err = StringIO()
    call_command("backup_loop", "--once", stdout=StringIO(), stderr=err)
    assert "check failed: RuntimeError: database restarting" in err.getvalue()


@pytest.mark.django_db
def test_bad_window_fails_fast(settings):
    settings.BACKUP_WINDOW = "2-5"
    with pytest.raises(ValueError, match="BACKUP_WINDOW"):
        call_command("backup_loop", "--once", stdout=StringIO())


@pytest.mark.django_db(transaction=True)
def test_backup_now_real_run_and_failure(tmp_path, monkeypatch, settings):
    Contributor.objects.get_or_create(handle="mike", defaults={"timezone": "America/New_York"})
    config, name, _ = crypt_remote(tmp_path)
    monkeypatch.setenv("RCLONE_CONFIG", str(config))
    settings.BACKUP_REMOTE = name
    out = StringIO()
    call_command("backup_now", stdout=out)
    assert "uploaded and verified" in out.getvalue()
    assert BackupRun.objects.get().trigger == "manual"
    settings.BACKUP_REMOTE = ""
    with pytest.raises(CommandError, match="failed at backup: BACKUP_REMOTE"):
        call_command("backup_now", stdout=StringIO())
