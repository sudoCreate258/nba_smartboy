# SPDX-License-Identifier: AGPL-3.0-or-later
from django.core.management.base import BaseCommand, CommandError

from core.services.export import ImportError_, import_lines


class Command(BaseCommand):
    help = "Import a nymbus-jsonl export into a database with no records for its contributor (checks every CID)."

    def add_arguments(self, parser):
        parser.add_argument("path")

    def handle(self, *args, path, **options):
        try:
            with open(path, encoding="utf-8") as fh:
                counts = import_lines(fh)
        except OSError as exc:
            raise CommandError(f"Cannot read {path}: {exc}")
        except ImportError_ as exc:
            raise CommandError(f"Nothing imported: {exc}")
        self.stdout.write(f"Imported {counts['records']} records and {counts['supersessions']} corrections "
                          f"for {counts['contributor']}; every CID verified.")
