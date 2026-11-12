# SPDX-License-Identifier: AGPL-3.0-or-later
"""Backup status for the home page and /api/v0/today (M4.5 R9)."""
import datetime

from django.conf import settings
from django.utils import timezone

from .models import BackupRun

AMBER_AFTER = datetime.timedelta(hours=48)
RED_AFTER = datetime.timedelta(days=7)


def backup_status(now=None):
    """{"level": ok|amber|red|not_set_up, "detail", "last_ok_at", "size_bytes", "verified", "last_error"}."""
    now = now or timezone.now()
    latest = BackupRun.objects.exclude(status=BackupRun.Status.RUNNING).order_by("-started_at").first()
    last_ok = BackupRun.objects.filter(status=BackupRun.Status.OK).order_by("-started_at").first()
    out = {"last_ok_at": None, "size_bytes": None, "verified": None, "last_error": None, "set_name": None}
    if last_ok is not None:
        out.update(last_ok_at=last_ok.finished_at or last_ok.started_at, size_bytes=last_ok.size_bytes,
                   verified=last_ok.verified, set_name=last_ok.set_name)
    if latest is None:
        if not settings.BACKUP_REMOTE:
            return {**out, "level": "not_set_up",
                    "detail": "No backup set up yet (see docs/OPERATIONS.md, Encrypted backup)."}
        return {**out, "level": "red", "detail": "No backup has run yet."}
    if latest.status == BackupRun.Status.FAILED:
        out["last_error"] = latest.error
        stage = "verify" if latest.uploaded else "backup"
        return {**out, "level": "red", "detail": f"The last backup failed at {stage}: {latest.error}"}
    age = now - out["last_ok_at"]
    level = "red" if age > RED_AFTER else "amber" if age > AMBER_AFTER else "ok"
    hours = int(age.total_seconds() // 3600)
    when = f"{hours} h ago" if hours < 48 else f"{hours // 24} days ago"
    return {**out, "level": level, "detail": f"Last backup {when}, verified."}
