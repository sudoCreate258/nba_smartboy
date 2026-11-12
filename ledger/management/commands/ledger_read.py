# SPDX-License-Identifier: AGPL-3.0-or-later
from django.core.management.base import BaseCommand, CommandError

from core.models import Contributor
from ledger.models import Recipient
from ledger.service import AccessRefused, simulated_read
from nymbus.ledger import UNIT_LABEL


class Command(BaseCommand):
    help = "Run one simulated read of a data category for a simulated recipient (needs an active grant)."

    def add_arguments(self, parser):
        parser.add_argument("--recipient", required=True, choices=Recipient.values)
        parser.add_argument("--category", required=True)
        parser.add_argument("--contributor", default="mike")

    def handle(self, *args, recipient, category, contributor, **options):
        try:
            who = Contributor.objects.get(handle=contributor)
        except Contributor.DoesNotExist:
            raise CommandError(f"Unknown contributor: {contributor}")
        try:
            event, records = simulated_read(who, recipient, category)
        except AccessRefused as exc:
            raise CommandError(f"Refused: {exc}")
        self.stdout.write(f"Read {len(records)} {category} records for {recipient} (event #{event.seq}, "
                          f"{event.cid}); {event.units} {UNIT_LABEL}.")
