from django.db import transaction

from .models import DailySnapshot

CREATED = "created"
SKIPPED = "skipped"
SUPERSEDED = "superseded"


def record_snapshot(snapshot):
    """Store an unsaved DailySnapshot, keeping one current snapshot per contributor and date.

    - CID already stored: nothing is written, the existing record is returned (skipped).
    - A current snapshot exists for that date: the new record supersedes it.
    Returns (record, outcome).
    """
    with transaction.atomic():
        snapshot.clean()
        cid = snapshot.compute_cid()
        existing = DailySnapshot.objects.filter(cid=cid).first()
        if existing is not None:
            return existing, SKIPPED
        current = (
            DailySnapshot.objects.current()
            .filter(contributor=snapshot.contributor, date=snapshot.date)
            .first()
        )
        snapshot.supersedes = current
        snapshot.save()
        return snapshot, SUPERSEDED if current else CREATED
