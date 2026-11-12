# SPDX-License-Identifier: AGPL-3.0-or-later
"""Backup status for the home page and /api/v0/today (M4.5 R9)."""
import datetime

from django.conf import settings
from django.utils import timezone

from .models import BackupRun

AMBER_AFTER = datetime.timedelta(hours=48)
RED_AFTER = datetime.timedelta(days=7)
STALE_AFTER = datetime.timedelta(hours=6)  # a "running" attempt older than this was interrupted


def failure_stage(run):
    """Where a failed attempt stopped: backup (before upload), verify (uploaded, not proven) or publish."""
    if not run.uploaded:
        return "backup"
    return "publish" if run.verified else "verify"


def backup_status(now=None):
    """{"level": ok|amber|red|not_set_up, "detail", "last_ok_at", "size_bytes", "verified", "last_error", ...}."""
    now = now or timezone.now()
    # An attempt that began long ago and never finished counts as an interruption, not as "still running".
    settled = BackupRun.objects.exclude(status=BackupRun.Status.RUNNING)
    stale = BackupRun.objects.filter(status=BackupRun.Status.RUNNING, started_at__lt=now - STALE_AFTER)
    latest = max([r for r in (settled.order_by("-started_at").first(), stale.order_by("-started_at").first()) if r],
                 key=lambda r: r.started_at, default=None)
    last_ok = BackupRun.objects.filter(status=BackupRun.Status.OK, published=True).order_by("-started_at").first()
    out = {"last_ok_at": None, "size_bytes": None, "verified": None, "last_error": None, "set_name": None,
           "prune_error": None}
    if last_ok is not None:
        out.update(last_ok_at=last_ok.finished_at or last_ok.started_at, size_bytes=last_ok.size_bytes,
                   verified=last_ok.verified, set_name=last_ok.set_name, prune_error=last_ok.prune_error or None)
    if latest is None:
        if not settings.BACKUP_REMOTE:
            return {**out, "level": "not_set_up",
                    "detail": "No backup set up yet (see docs/OPERATIONS.md, Encrypted backup)."}
        return {**out, "level": "red", "detail": "No backup has run yet."}
    if latest.status in (BackupRun.Status.FAILED, BackupRun.Status.RUNNING):
        error = latest.error or "Interrupted: the backup process stopped before it finished."
        out["last_error"] = error
        return {**out, "level": "red", "detail": f"The last backup failed at {failure_stage(latest)}: {error}"}
    age = now - out["last_ok_at"]
    level = "red" if age > RED_AFTER else "amber" if age > AMBER_AFTER else "ok"
    hours = int(age.total_seconds() // 3600)
    when = f"{hours} h ago" if hours < 48 else f"{hours // 24} days ago"
    note = " Old sets could not be deleted (the new set is safe)." if out["prune_error"] else ""
    return {**out, "level": level, "detail": f"Last backup {when}, verified.{note}"}
