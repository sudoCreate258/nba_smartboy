# SPDX-License-Identifier: AGPL-3.0-or-later
from django.apps import AppConfig


class LedgerConfig(AppConfig):
    """Simulated ownership ledger (M5): grants, revocations and hash-chained access events."""
    name = "ledger"
    default_auto_field = "django.db.models.BigAutoField"
