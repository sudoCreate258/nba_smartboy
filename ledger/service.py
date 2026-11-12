# SPDX-License-Identifier: AGPL-3.0-or-later
"""The only way a simulated recipient reads the owner's data (M5 R3, R5).

Every function takes the contributor row lock, so grants, revocations and reads of one
contributor are serialized: once a revocation has committed, the next read is refused.
A refused read writes nothing. Local only: nothing here opens a network connection.
"""
import logging

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from core.models import Contributor
from core.services.export import BY_KIND
from nymbus import ledger
from nymbus.provenance import normalize_fields
from ui.modules import categories, kinds_of

from .models import AccessEvent, Grant, Revocation


log = logging.getLogger("ledger")


class AccessRefused(Exception):
    """No active grant for this recipient and category: nothing was read or written."""


def _lock(contributor):
    return Contributor.objects.select_for_update().get(pk=contributor.pk)


def _ledger_now(contributor):
    """The time for a ledger write, read under the contributor lock, never earlier than anything already in
    the contributor's ledger. A host clock can step back (seen on the Docker VM); without this a read
    right after a revocation could be dated before it and slip through."""
    now = timezone.now()
    latest = [AccessEvent.objects.filter(contributor=contributor).aggregate(t=Max("at"))["t"],
              Revocation.objects.filter(contributor=contributor).aggregate(t=Max("at"))["t"],
              Grant.objects.filter(contributor=contributor).aggregate(t=Max("start"))["t"]]
    latest = max((t for t in latest if t is not None), default=None)
    return max(now, latest) if latest is not None else now


def grant(contributor, category, recipient, purpose, end=None, now=None):
    """Grant `recipient` read access to `category` from now on (until `end`, when given)."""
    if category not in {c["id"] for c in categories()}:
        raise ValidationError({"category": f"Unknown data category {category!r}."})
    with transaction.atomic():
        _lock(contributor)
        now = now or _ledger_now(contributor)  # read the clock only once the lock is held
        g = Grant(contributor=contributor, category=category, recipient=recipient,
                  purpose=(purpose or "").strip(), start=now, end=end)
        g.save()  # validation refuses a second grant in force for the same recipient and category
    return g


def revoke(contributor, grant_cid, reason="", now=None):
    """End a grant now. The grant stays; a Revocation record supersedes it."""
    with transaction.atomic():
        _lock(contributor)
        now = now or _ledger_now(contributor)  # read the clock only once the lock is held
        g = Grant.objects.filter(cid=grant_cid, contributor=contributor).first()
        if g is None:
            raise ValidationError("No such grant.")
        if g.revocation() is not None:
            raise ValidationError("This grant is already revoked.")
        if g.end is not None and g.end <= now:
            raise ValidationError("This grant has already ended.")
        r = Revocation(contributor=contributor, grant_cid=g.cid, at=now, reason=reason.strip())
        r.save()
    return r


def active_grant(contributor, recipient, category, at, grant_cid=None):
    """The newest grant letting `recipient` read `category` at `at`, or None."""
    grants = Grant.objects.filter(contributor=contributor, recipient=recipient, category=category)
    if grant_cid:
        grants = grants.filter(cid=grant_cid)
    revoked = dict(Revocation.objects.filter(contributor=contributor).values_list("grant_cid", "at"))
    for g in grants.order_by("-start", "-id"):
        if ledger.is_active(g.start, g.end, revoked.get(g.cid), at):
            return g
    return None


def category_records(contributor, category):
    """Current records of a category's kinds, oldest first within each kind."""
    out = []
    for kind in kinds_of(category):
        out += list(BY_KIND[kind].objects.current().filter(contributor=contributor).order_by("created_seq"))
    return out


def simulated_read(contributor, recipient, category, now=None, grant_cid=None):
    """Read a category for a simulated recipient. Returns (event, [{"kind", "cid", "fields"}]).

    Raises AccessRefused (and writes nothing) unless an active grant allows it.
    """
    with transaction.atomic():
        _lock(contributor)
        now = now or _ledger_now(contributor)  # read the clock only once the lock is held
        g = active_grant(contributor, recipient, category, now, grant_cid=grant_cid)
        if g is None:
            # Not a ledger event (a refusal takes no sequence number); logged so probing is visible.
            log.warning("refused read: %s -> %s for %s at %s (no active grant)", category, recipient,
                        contributor.handle, now.isoformat())
            raise AccessRefused(f"No active grant lets {recipient} read {category}; nothing was read.")
        records = category_records(contributor, category)
        cids = [r.cid for r in records]
        last = AccessEvent.objects.filter(contributor=contributor).order_by("-seq").first()
        event = AccessEvent(contributor=contributor, seq=last.seq + 1 if last else 1,
                            prev_hash=ledger.digest(last.canonical()) if last else ledger.GENESIS, at=now,
                            grant_cid=g.cid, recipient=recipient, category=category, purpose=g.purpose,
                            record_cids=cids, units=ledger.units_for(cids))
        event.save()
    data = [{"kind": r.record_kind, "cid": r.cid, "fields": normalize_fields(r.domain_fields())} for r in records]
    return event, data
