# SPDX-License-Identifier: AGPL-3.0-or-later
from django.db import models


class ModuleSetting(models.Model):
    """On/off state of one UI module (configuration, not contributed data: no CID, editable)."""

    module_id = models.CharField(max_length=64, unique=True)
    enabled = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.module_id}: {'on' if self.enabled else 'off'}"
