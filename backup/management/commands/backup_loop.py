# SPDX-License-Identifier: AGPL-3.0-or-later
"""The `backup` Compose service: check every few minutes, back up once per night (R6)."""
import datetime
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils import timezone

from backup import schedule
from backup.models import BackupRun
from backup.runner import _tz, run_backup

from .backup_now import describe


def check_once(now=None):
    """Run the nightly backup if it is due. Returns (ran: bool, message)."""
    now = now or timezone.now()
    window = schedule.parse_window(settings.BACKUP_WINDOW)
    last = BackupRun.objects.order_by("-started_at").values_list("started_at", flat=True).first()
    due, reason = schedule.is_due(now, last, window, _tz())
    if not due:
        return False, reason
    run = run_backup(BackupRun.Trigger.NIGHTLY, now=now)
    return True, f"{reason}: {describe(run)}"


class Command(BaseCommand):
    help = "Run forever: one encrypted backup per night inside BACKUP_WINDOW, with catch-up after sleep."

    def add_arguments(self, parser):
        parser.add_argument("--interval", type=int, default=300, help="seconds between checks (default 300)")
        parser.add_argument("--once", action="store_true", help="check once and exit (tests, cron)")
        parser.add_argument("--now", type=datetime.datetime.fromisoformat, default=None, help=argparse_hidden())

    def handle(self, *args, interval, once, now, **options):
        schedule.parse_window(settings.BACKUP_WINDOW)  # fail fast on a bad window
        self.stdout.write(f"Backup loop: window {settings.BACKUP_WINDOW} local, checking every {interval} s.")
        while True:
            try:
                ran, message = check_once(now)
                if ran or once:
                    self.stdout.write(f"{timezone.now():%Y-%m-%d %H:%M} {message}")
            except Exception as exc:  # e.g. the database restarting: report and try again next time
                self.stderr.write(f"{timezone.now():%Y-%m-%d %H:%M} check failed: {type(exc).__name__}: {exc}")
            if once:
                return
            close_old_connections()  # a long-running process must not keep a broken connection
            time.sleep(interval)


def argparse_hidden():
    import argparse
    return argparse.SUPPRESS
