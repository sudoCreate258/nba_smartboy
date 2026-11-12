# SPDX-License-Identifier: AGPL-3.0-or-later
from django.core.management.base import BaseCommand, CommandError

from core.models import Contributor
from core.services.export import export_lines


class Command(BaseCommand):
    help = "Export all of a contributor's records and corrections as JSON Lines (nymbus-jsonl v1)."

    def add_arguments(self, parser):
        parser.add_argument("--contributor", default="mike")
        parser.add_argument("--out", help="file to write (default: standard output)")

    def handle(self, *args, contributor, out, **options):
        try:
            who = Contributor.objects.get(handle=contributor)
        except Contributor.DoesNotExist:
            raise CommandError(f"Unknown contributor: {contributor}")
        if out:
            n = 0
            with open(out, "w", encoding="utf-8", newline="\n") as fh:
                for line in export_lines(who):
                    fh.write(line + "\n")
                    n += 1
            self.stderr.write(f"Wrote {n} lines to {out}")
        else:
            for line in export_lines(who):
                self.stdout.write(line)
