# SPDX-License-Identifier: AGPL-3.0-or-later
from django.core.management.base import BaseCommand, CommandError

from backup.models import BackupRun
from backup.runner import run_backup
from backup.status import failure_stage


def describe(run):
    size = "" if run.size_bytes is None else f", {run.size_bytes / 1e6:.1f} MB"
    if run.status == BackupRun.Status.OK:
        pruned = f", pruned {len(run.pruned)} old set(s)" if run.pruned else ""
        warn = (f" WARNING: deleting old sets failed after {len(run.pruned)} deletion(s) ({run.prune_error}); "
                "the new set is safe.") if run.prune_error else ""
        return f"Backup {run.set_name} uploaded and verified{size}{pruned}.{warn}"
    stage = failure_stage(run)
    return f"Backup {run.set_name} failed at {stage}: {run.error}"


class Command(BaseCommand):
    help = "Back up now: dump + export (+ inbox if BACKUP_INCLUDE_INBOX=1), encrypt and upload, verify, prune."

    def handle(self, *args, **options):
        run = run_backup(BackupRun.Trigger.MANUAL)
        if run.status != BackupRun.Status.OK:
            raise CommandError(describe(run))
        self.stdout.write(describe(run))
