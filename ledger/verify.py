# SPDX-License-Identifier: AGPL-3.0-or-later
"""Recompute the whole ledger from stored content (M5 R4): `manage.py verify_ledger`."""
from django.core.exceptions import ValidationError

from core.models import Contributor
from core.services.export import RECORD_MODELS
from nymbus import ledger
from ui.modules import kinds_of

from .models import AccessEvent, Grant, Revocation


def _cid_ok(obj):
    try:
        return obj.compute_cid() == obj.cid
    except (ValidationError, ValueError, TypeError):
        return False


def head(contributor):
    """The ledger head (M6 R2): number of access events and the SHA-256 of the newest one (64 zeros when
    there is none), plus the grant and revocation counts. Written into every backup manifest."""
    last = AccessEvent.objects.filter(contributor=contributor).order_by("-seq").first()
    return {"events": AccessEvent.objects.filter(contributor=contributor).count(),
            "last_hash": ledger.digest(last.canonical()) if last else ledger.GENESIS,
            "grants": Grant.objects.filter(contributor=contributor).count(),
            "revocations": Revocation.objects.filter(contributor=contributor).count()}


def newest_anchor():
    """(set name, {handle: head}) of the newest published backup that carries ledger heads, or (None, {})."""
    from backup.models import BackupRun

    for run in BackupRun.objects.filter(published=True).order_by("-started_at").only("set_name", "manifest"):
        heads = (run.manifest or {}).get("ledger_heads")
        if isinstance(heads, dict):
            return run.set_name, heads
    return None, {}


def compare_head(contributor, anchor, where="the backup"):
    """Problems when the live ledger is shorter than, or differs from, an anchored head. A longer live
    ledger is fine as long as it extends the anchored one."""
    if not isinstance(anchor, dict):
        return []
    problems = []
    events = list(AccessEvent.objects.filter(contributor=contributor).order_by("seq"))
    anchored = anchor.get("events", 0)
    if len(events) < anchored:
        problems.append(f"{contributor}: the ledger is shorter than in {where}: {len(events)} access events, "
                        f"{where} had {anchored} (events were removed)")
    elif anchored and ledger.digest(events[anchored - 1].canonical()) != anchor.get("last_hash"):
        problems.append(f"{contributor}: access event {anchored} differs from {where} (the chain was rewritten)")
    for kind, model in (("grants", Grant), ("revocations", Revocation)):
        live = model.objects.filter(contributor=contributor).count()
        if live < anchor.get(kind, 0):
            problems.append(f"{contributor}: {live} {kind}, fewer than the {anchor[kind]} in {where} "
                            f"({kind} were removed)")
    return problems


def verify(contributor=None):
    """(problems, counts). problems == [] means every CID, the chain and every read record check out."""
    problems = []
    counts = {"grants": 0, "revocations": 0, "events": 0, "records": 0}
    for who in [contributor] if contributor else Contributor.objects.order_by("id"):
        grants = {g.cid: g for g in Grant.objects.filter(contributor=who)}
        revocations = list(Revocation.objects.filter(contributor=who))
        events = list(AccessEvent.objects.filter(contributor=who).order_by("seq", "id"))
        counts["grants"] += len(grants)
        counts["revocations"] += len(revocations)
        counts["events"] += len(events)
        for obj in list(grants.values()) + revocations + events:
            if not _cid_ok(obj):
                problems.append(f"{who}: {obj.record_kind} {obj.cid}: CID does not match its stored content")
        revoked = {}
        for r in revocations:
            if r.grant_cid not in grants:
                problems.append(f"{who}: revocation {r.cid}: revokes a grant that does not exist")
            revoked[r.grant_cid] = r.at
        for g in grants.values():
            if g.overlapping().filter(pk__lt=g.pk).exists():
                problems.append(f"{who}: grant {g.cid}: overlaps another grant in force for {g.recipient} / "
                                f"{g.category}")
        problems += [f"{who}: {p}" for p in ledger.check_chain(
            [{"seq": e.seq, "prev_hash": e.prev_hash, "canonical": e.canonical()} for e in events])]
        records = {}
        for model in RECORD_MODELS:
            for rec in model.objects.filter(contributor=who):
                records[rec.cid] = rec
        checked = {}
        for e in events:
            where = f"{who}: event {e.seq}"
            g = grants.get(e.grant_cid)
            if g is None:
                problems.append(f"{where}: its grant {e.grant_cid} does not exist")
            else:
                for name in ("recipient", "category", "purpose"):
                    if getattr(e, name) != getattr(g, name):
                        problems.append(f"{where}: {name} differs from its grant")
                if not ledger.is_active(g.start, g.end, revoked.get(g.cid), e.at):
                    problems.append(f"{where}: its grant was not active at {e.at.isoformat()}")
            cids = e.record_cids if isinstance(e.record_cids, list) else []
            if e.units != ledger.units_for(cids):
                problems.append(f"{where}: units {e.units} != {ledger.units_for(cids)} for {len(cids)} records")
            kinds = kinds_of(e.category)
            if not kinds:
                problems.append(f"{where}: unknown category {e.category!r}")
            for cid in cids:
                rec = records.get(cid)
                if rec is None:
                    problems.append(f"{where}: record {cid} does not exist")
                    continue
                if cid not in checked:
                    checked[cid] = _cid_ok(rec)
                    if not checked[cid]:
                        problems.append(f"{where}: record {cid} no longer matches its CID")
                if kinds and rec.record_kind not in kinds:
                    problems.append(f"{where}: record {cid} ({rec.record_kind}) is not in category {e.category}")
        counts["records"] += len(checked)
    return problems, counts
