# SPDX-License-Identifier: AGPL-3.0-or-later
from django.core.management.base import BaseCommand, CommandError

from core.models import Contributor
from ledger.verify import verify


class Command(BaseCommand):
    help = ("Recompute every grant, revocation and access-event CID, the hash chain, and the CID of every "
            "record read; fails (non-zero) on any break.")

    def add_arguments(self, parser):
        parser.add_argument("--contributor", help="only this contributor (default: all)")

    def handle(self, *args, contributor, **options):
        who = None
        if contributor:
            try:
                who = Contributor.objects.get(handle=contributor)
            except Contributor.DoesNotExist:
                raise CommandError(f"Unknown contributor: {contributor}")
        problems, counts = verify(who)
        if problems:
            raise CommandError(f"Ledger verification FAILED ({len(problems)} problems):\n"
                               + "\n".join(f"  - {p}" for p in problems))
        self.stdout.write(f"Ledger OK: {counts['grants']} grants, {counts['revocations']} revocations, "
                          f"{counts['events']} access events; hash chain intact; "
                          f"{counts['records']} record CIDs recomputed.")
