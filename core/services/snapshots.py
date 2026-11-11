from django.db import transaction

from ..models import Contributor, DailySnapshot, Supersession

CREATED = "created"
SKIPPED = "skipped"
SUPERSEDED = "superseded"


def record_snapshot(snapshot):
    """Store an unsaved DailySnapshot, keeping one current snapshot per contributor and date.

    - CID is the current snapshot: nothing is written (skipped).
    - CID is stored but superseded (a revert, A -> B -> A): a Supersession is
      recorded from the current snapshot to it; no new row (superseded).
    - New CID with a current snapshot on that date: it is stored and supersedes it.
    Returns (record, outcome).
    """
    with transaction.atomic():
        snapshot.validate()
        # Serialize writers per contributor so two callers cannot both supersede
        # the same current snapshot.
        Contributor.objects.select_for_update().get(pk=snapshot.contributor_id)
        cid = snapshot.compute_cid()
        current = snapshot.current_for_date()
        existing = DailySnapshot.objects.filter(cid=cid).first()
        if existing is not None:
            if current is None or current.pk == existing.pk:
                return existing, SKIPPED
            Supersession.record(current, existing, reason="revert")
            return existing, SUPERSEDED
        snapshot.save(supersede=current is not None)
        return snapshot, SUPERSEDED if current else CREATED
