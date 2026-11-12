# SPDX-License-Identifier: AGPL-3.0-or-later
"""Write /sw.js as the server serves it, so the CI gates can syntax-check it with node."""
from django.core.management.base import BaseCommand
from django.test import Client


class Command(BaseCommand):
    help = "Render the service worker (/sw.js) to a file for `node --check`."

    def add_arguments(self, parser):
        parser.add_argument("--out", required=True)

    def handle(self, *args, out, **options):
        resp = Client(HTTP_HOST="localhost").get("/sw.js")
        if resp.status_code != 200:
            raise SystemExit(f"/sw.js answered {resp.status_code}")
        with open(out, "wb") as fh:
            fh.write(resp.content)
        self.stdout.write(f"Wrote {out}")
