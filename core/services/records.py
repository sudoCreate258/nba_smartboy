# SPDX-License-Identifier: AGPL-3.0-or-later
"""One write path for records: duplicate check, corrections and Supersession events.

Used by the admin and the phone app (and any later adapter), so the rules are
enforced in one place rather than remembered per caller (M3 review #9).
The contributor row lock is taken before anything is checked, so "is the record I am
correcting still current?" and the write that depends on it cannot interleave with
another writer (M4 review).
"""
from django.core.exceptions import ValidationError
from django.db import transaction

from ..models import Contributor, DailySnapshot, Lineage, Supersession
from .snapshots import CREATED, SKIPPED, SUPERSEDED, record_snapshot

STALE = "This record was already corrected; correct its current version instead."


def save_record(record, supersedes=None, reason=""):
    """Store an unsaved record; returns (stored record, outcome).

    outcome: CREATED, SKIPPED (identical record already stored, nothing written)
    or SUPERSEDED (stored as a correction of `supersedes`, or a revert to an
    identical earlier version of the same record). `supersedes` must be a current
    record of the same kind and contributor at the moment of writing.
    """
    if supersedes is not None:
        if type(supersedes) is not type(record) or supersedes.contributor_id != record.contributor_id:
            raise ValidationError("A correction must be the same kind of record from the same contributor.")
        if hasattr(record, "replaces_cid"):
            record.replaces_cid = supersedes.cid  # lets overlap/order checks ignore the record being replaced
    model = type(record)
    with transaction.atomic():
        Contributor.objects.select_for_update().get(pk=record.contributor_id)
        if supersedes is not None and not model.objects.current().filter(pk=supersedes.pk).exists():
            raise ValidationError(STALE)

        if isinstance(record, DailySnapshot):
            if supersedes is not None:
                if supersedes.date != record.date:
                    raise ValidationError({"date": "A correction keeps the date of the snapshot it corrects."})
                current = record.current_for_date()
                if current is not None and current.pk != supersedes.pk:
                    raise ValidationError(STALE)
            return record_snapshot(record)  # one current snapshot per date: supersedes the current one itself

        record.validate()
        existing = model.objects.filter(cid=record.compute_cid()).first()
        if existing is not None:
            if supersedes is not None and existing.cid != supersedes.cid:
                # A revert may only bring back an earlier version of this same record.
                if existing.cid not in Lineage(record.contributor_id).members(supersedes.cid):
                    raise ValidationError("An identical record already exists as a different record; nothing written.")
                Supersession.record(supersedes, existing, reason=reason or "revert")
                return existing, SUPERSEDED
            return existing, SKIPPED
        record.save()
        if supersedes is not None:
            Supersession.record(supersedes, record, reason=reason)
            return record, SUPERSEDED
        return record, CREATED
