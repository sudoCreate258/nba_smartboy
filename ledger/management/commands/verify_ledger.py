# SPDX-License-Identifier: AGPL-3.0-or-later
import json

from django.core.management.base import BaseCommand, CommandError

from core.models import Contributor
from ledger.verify import compare_head, newest_anchor, verify


class Command(BaseCommand):
    help = ("Recompute every grant, revocation and access-event CID, the hash chain, and the CID of every "
            "record read; compare the ledger head with the newest backup (or --manifest); fails (non-zero) "
            "on any break.")

    def add_arguments(self, parser):
        parser.add_argument("--contributor", help="only this contributor (default: all)")
        parser.add_argument("--manifest", help="a backup manifest.json kept outside the database to compare with "
                                               "(default: the newest published backup's manifest as logged)")

    def handle(self, *args, contributor, manifest, **options):
        who = None
        if contributor:
            try:
                who = Contributor.objects.get(handle=contributor)
            except Contributor.DoesNotExist:
                raise CommandError(f"Unknown contributor: {contributor}")
        problems, counts = verify(who)
        if manifest:
            try:
                with open(manifest, encoding="utf-8") as fh:
                    heads = json.load(fh).get("ledger_heads")
            except (OSError, ValueError) as exc:
                raise CommandError(f"Cannot read {manifest}: {exc}")
            if not isinstance(heads, dict):
                raise CommandError(f"{manifest} has no ledger heads (a set made before M6)")
            where = f"manifest {manifest}"
        else:
            name, heads = newest_anchor()
            where = f"backup {name}"
        anchored = 0
        for handle, head in heads.items():
            c = Contributor.objects.filter(handle=handle).first()
            if who is not None and c != who:
                continue
            if c is None:
                problems.append(f"{handle}: in {where} but not in this database")
                continue
            problems += compare_head(c, head, where)
            anchored += 1
        if problems:
            raise CommandError(f"Ledger verification FAILED ({len(problems)} problems):\n"
                               + "\n".join(f"  - {p}" for p in problems))
        anchor = f"head matches {where}" if anchored else "no backup anchor yet"
        self.stdout.write(f"Ledger OK: {counts['grants']} grants, {counts['revocations']} revocations, "
                          f"{counts['events']} access events; hash chain intact; "
                          f"{counts['records']} record CIDs recomputed; {anchor}.")
