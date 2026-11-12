# SPDX-License-Identifier: AGPL-3.0-or-later
from django.apps import AppConfig


class BackupConfig(AppConfig):
    """Encrypted off-hours backup (M4.5)."""

    name = "backup"
    default_auto_field = "django.db.models.BigAutoField"
