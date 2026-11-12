# SPDX-License-Identifier: AGPL-3.0-or-later
from django.apps import AppConfig


class UiConfig(AppConfig):
    """Phone-friendly web app (M4): server-rendered pages over the core services."""

    name = "ui"
    default_auto_field = "django.db.models.BigAutoField"
