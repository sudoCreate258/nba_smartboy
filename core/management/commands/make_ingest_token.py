# SPDX-License-Identifier: AGPL-3.0-or-later
"""Print a new random token for dtom's live ingest (027 Part B). It is only printed: put it in .env as
DTOM_INGEST_TOKEN=<token> (and in dtom), then restart the web service. Nothing is stored here."""
import secrets

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Print a new random DTOM_INGEST_TOKEN for .env (nothing is stored)."

    def handle(self, *args, **options):
        token = secrets.token_urlsafe(32)
        self.stdout.write(f"DTOM_INGEST_TOKEN={token}")
        self.stderr.write("Paste the line above into .env (and the token into dtom), then: docker compose up -d web. "
                          "This token is not stored anywhere else.")
