# SPDX-License-Identifier: AGPL-3.0-or-later
from django.core.management.base import BaseCommand, CommandError

from backup.models import BackupRun
from backup.runner import run_backup


def describe(run):
    size = "" if run.size_bytes is None else f", {run.size_bytes / 1e6:.1f} MB"
    if run.status == BackupRun.Status.OK:
        pruned = f", pruned {len(run.pruned)} old set(s)" if run.pruned else ""
        return f"Backup {run.set_name} uploaded and verified{size}{pruned}."
    stage = "verify" if run.uploaded else "backup"
    return f"Backup {run.set_name} failed at {stage}: {run.error}"


class Command(BaseCommand):
    help = "Back up now: dump + export (+ inbox if BACKUP_INCLUDE_INBOX=1), encrypt and upload, verify, prune."

    def handle(self, *args, **options):
        run = run_backup(BackupRun.Trigger.MANUAL)
        if run.status != BackupRun.Status.OK:
            raise CommandError(describe(run))
        self.stdout.write(describe(run))
