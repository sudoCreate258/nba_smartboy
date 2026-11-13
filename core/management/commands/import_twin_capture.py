# SPDX-License-Identifier: AGPL-3.0-or-later
"""Import one dtom session export (nymbus.twin_capture.v1) as records (027 Part A, R2).

    python manage.py import_twin_capture --file data/inbox/camera-probe/twin-2026-11-13.json

One TwinCapture (the export without its samples) plus one PostureSample per entry of
posture_samples_v0, through the normal record path (validation, CID, immutable). Same file again:
nothing new (identical CIDs). The whole file is one transaction. No grants are created.
"""
import copy
import json

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Contributor, PostureSample, TwinCapture
from core.services.records import save_record
from core.services.snapshots import CREATED
from twin_metrics.dtom import DtomError, check_capture, parse_time


def import_capture(doc, contributor):
    """(capture, created records, skipped records). Raises DtomError / ValidationError; nothing is written then."""
    exported = check_capture(doc)
    samples = doc["posture_samples_v0"]
    raw = copy.deepcopy({k: v for k, v in doc.items() if k != "posture_samples_v0"})
    created = skipped = 0
    with transaction.atomic():
        capture, outcome = save_record(TwinCapture(contributor=contributor, source="dtom", exported_at=exported,
                                                   sample_count=len(samples), raw=raw))
        created, skipped = (1, 0) if outcome == CREATED else (0, 1)
        for i, s in enumerate(samples):
            _, outcome = save_record(PostureSample(contributor=contributor, capture_cid=capture.cid, index=i,
                                                   label=s["label"], at=parse_time(s["at"], f"posture_samples_v0[{i}].at"),
                                                   data=copy.deepcopy(s)))
            created += outcome == CREATED
            skipped += outcome != CREATED
    return capture, created, skipped


class Command(BaseCommand):
    help = "Import a dtom twin_capture.v1 export (one TwinCapture + one PostureSample per sample). Idempotent."

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True)
        parser.add_argument("--contributor", default=None, help="default: TWIN_CONTRIBUTOR")

    def handle(self, *args, file, contributor, **options):
        handle = contributor or settings.TWIN_CONTRIBUTOR
        try:
            who = Contributor.objects.get(handle=handle)
        except Contributor.DoesNotExist:
            raise CommandError(f"Unknown contributor: {handle}")
        try:
            with open(file, encoding="utf-8") as fh:
                doc = json.load(fh)
        except OSError as exc:
            raise CommandError(f"Cannot read {file}: {exc}")
        except ValueError as exc:
            raise CommandError(f"{file} is not JSON: {exc}")
        try:
            capture, created, skipped = import_capture(doc, who)
        except DtomError as exc:
            raise CommandError(f"Nothing imported: {exc}")
        except ValidationError as exc:
            raise CommandError(f"Nothing imported: {' '.join(exc.messages)}")
        self.stdout.write(f"Imported dtom capture {capture.cid} ({capture.sample_count} posture samples) for "
                          f"{who.handle}: {created} new records, {skipped} already stored.")
