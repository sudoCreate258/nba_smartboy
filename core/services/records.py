# SPDX-License-Identifier: AGPL-3.0-or-later
"""One write path for records: duplicate check, corrections and Supersession events.

Used by the admin and the phone app (and any later adapter), so the rules are
enforced in one place rather than remembered per caller (M3 review #9).
"""
from django.core.exceptions import ValidationError
from django.db import transaction

from ..models import Contributor, DailySnapshot, Supersession
from .snapshots import CREATED, SKIPPED, SUPERSEDED, record_snapshot


def save_record(record, supersedes=None, reason=""):
    """Store an unsaved record; returns (stored record, outcome).

    outcome: CREATED, SKIPPED (identical record already stored, nothing written)
    or SUPERSEDED (stored as a correction of `supersedes`, or a revert to an
    identical earlier record). `supersedes` must be a current record of the
    same kind and contributor.
    """
    if supersedes is not None:
        if type(supersedes) is not type(record) or supersedes.contributor_id != record.contributor_id:
            raise ValidationError("A correction must be the same kind of record from the same contributor.")
        if not type(supersedes).objects.current().filter(pk=supersedes.pk).exists():
            raise ValidationError("This record was already corrected; correct its current version instead.")
        if hasattr(record, "replaces_cid"):
            record.replaces_cid = supersedes.cid  # lets overlap/order checks ignore the record being replaced

    if isinstance(record, DailySnapshot):
        if supersedes is not None and supersedes.date != record.date:
            raise ValidationError({"date": "A correction keeps the date of the snapshot it corrects."})
        return record_snapshot(record)  # one current snapshot per date: supersedes the current one itself

    model = type(record)
    with transaction.atomic():
        Contributor.objects.select_for_update().get(pk=record.contributor_id)
        record.validate()
        existing = model.objects.filter(cid=record.compute_cid()).first()
        if existing is not None:
            if supersedes is not None and existing.cid != supersedes.cid:
                Supersession.record(supersedes, existing, reason=reason or "revert")
                return existing, SUPERSEDED
            return existing, SKIPPED
        record.save()
        if supersedes is not None:
            Supersession.record(supersedes, record, reason=reason)
            return record, SUPERSEDED
        return record, CREATED
