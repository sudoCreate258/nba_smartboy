from collections import Counter

import yaml
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Contributor, DailySnapshot
from core.services import CREATED, SKIPPED, SUPERSEDED, record_snapshot

ALLOWED_KEYS = {
    f.name
    for f in DailySnapshot._meta.concrete_fields
    if not f.primary_key and f.name not in {"cid", "contributor", "created_at"}
}
REQUIRED_KEYS = {"date", "source"}


class Command(BaseCommand):
    help = "Ingest DailySnapshots from a YAML file (one mapping or a list) in a single transaction."

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--contributor", default="mike")

    def handle(self, *args, path, contributor, **options):
        try:
            contributor_obj = Contributor.objects.get(handle=contributor)
        except Contributor.DoesNotExist:
            raise CommandError(f"Unknown contributor: {contributor}")
        items = self.load_items(path)
        self.check_keys(items)

        counts = Counter()
        new_cids = []
        with transaction.atomic():  # any error below rolls back the whole file
            for i, item in enumerate(items, start=1):
                snapshot = DailySnapshot(contributor=contributor_obj, **item)
                try:
                    record, outcome = record_snapshot(snapshot)
                except ValidationError as exc:
                    raise CommandError(f"Record {i}: {'; '.join(exc.messages)}")
                counts[outcome] += 1
                if outcome != SKIPPED:
                    new_cids.append(record.cid)

        self.stdout.write(
            f"created={counts[CREATED]} skipped={counts[SKIPPED]} superseded={counts[SUPERSEDED]}"
        )
        for cid in new_cids:
            self.stdout.write(f"  {cid}")

    def load_items(self, path):
        try:
            with open(path, encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
        except OSError as exc:
            raise CommandError(f"Cannot read {path}: {exc}")
        except yaml.YAMLError as exc:
            raise CommandError(f"Invalid YAML in {path}: {exc}")
        items = [data] if isinstance(data, dict) else data
        if not isinstance(items, list) or not all(isinstance(x, dict) for x in items):
            raise CommandError("YAML must be a mapping or a list of mappings.")
        return items

    def check_keys(self, items):
        unknown = set()
        for i, item in enumerate(items, start=1):
            unknown |= set(item) - ALLOWED_KEYS
            missing = REQUIRED_KEYS - set(item)
            if missing:
                raise CommandError(f"Record {i} is missing required keys: {', '.join(sorted(missing))}")
        if unknown:
            raise CommandError(f"Unknown keys: {', '.join(sorted(map(str, unknown)))}")
