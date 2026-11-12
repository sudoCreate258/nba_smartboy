# SPDX-License-Identifier: AGPL-3.0-or-later
from django.db import models


class BackupRun(models.Model):
    """One backup attempt (a log row, not contributed data: no CID)."""

    class Status(models.TextChoices):
        RUNNING = "running"
        OK = "ok"
        FAILED = "failed"

    class Trigger(models.TextChoices):
        NIGHTLY = "nightly"
        MANUAL = "manual"

    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    trigger = models.CharField(max_length=8, choices=Trigger.choices)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.RUNNING)
    set_name = models.CharField(max_length=32, blank=True)
    size_bytes = models.BigIntegerField(null=True, blank=True)
    uploaded = models.BooleanField(default=False)
    verified = models.BooleanField(default=False)
    published = models.BooleanField(default=False, help_text="Moved from staging to the verified sets.")
    pruned = models.JSONField(default=list, blank=True)
    prune_error = models.TextField(blank=True, help_text="Deleting old sets failed; the new set is still good.")
    manifest = models.JSONField(null=True, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.set_name or self.started_at:%Y-%m-%d %H:%M} {self.status}"
