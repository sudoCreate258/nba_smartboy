# SPDX-License-Identifier: AGPL-3.0-or-later
"""Provenance page (MVP, 025 R3), read-only: pick a record and see its CID (recomputed), its correction
chain, every simulated read that included any version of it, and the grant that covered each read."""
from functools import reduce
from operator import or_

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from core.models import Contributor, Lineage, Supersession
from core.services.export import RECORD_MODELS
from ledger.models import AccessEvent, Grant, Recipient, Revocation

from .today import contributor_for
from .views import _context

DEMO = "demo"
CHOICES = 40


def _find(who, cid):
    for model in RECORD_MODELS:
        rec = model.objects.filter(contributor=who, cid=cid).first()
        if rec is not None:
            return rec
    return None


def detail(who, rec):
    model = type(rec)
    current = set(model.objects.current().filter(contributor=who).values_list("cid", flat=True))
    lineage = Lineage(who.id)
    head = lineage.resolve(rec.cid, current)
    members = lineage.members(head) if head else {rec.cid}
    chain = list(Supersession.objects.filter(contributor=who).filter(Q(old_cid__in=members) | Q(new_cid__in=members))
                 .order_by("created_seq"))
    reads = AccessEvent.objects.filter(contributor=who).filter(
        reduce(or_, (Q(record_cids__contains=[m]) for m in members))).order_by("seq")
    grants = {g.cid: g for g in Grant.objects.filter(contributor=who)}
    revoked = {r.grant_cid: r for r in Revocation.objects.filter(contributor=who)}
    recipients = dict(Recipient.choices)
    rows = []
    for e in reads:
        g = grants.get(e.grant_cid)
        rows.append({"e": e, "grant": g, "revocation": revoked.get(e.grant_cid),
                     "recipient": recipients.get(e.recipient, e.recipient),
                     "versions": [m for m in e.record_cids if m in members]})
    try:
        cid_ok = rec.compute_cid() == rec.cid
    except Exception:  # unreadable content is a failed check, not a page error
        cid_ok = False
    return {"rec": rec, "kind": rec.record_kind, "cid_ok": cid_ok, "is_current": rec.cid in current,
            "current_cid": head, "chain": chain, "reads": rows, "fields": rec.domain_fields()}


@login_required
@require_GET
def provenance_page(request):
    own = contributor_for(request.user)
    demo = Contributor.objects.filter(handle=DEMO).exclude(pk=own.pk).first()
    who = demo if request.GET.get("who") == DEMO and demo else own
    recent = []
    for model in RECORD_MODELS:
        recent += list(model.objects.current().filter(contributor=who).order_by("-created_seq")[:CHOICES])
    recent = sorted(recent, key=lambda r: r.created_seq, reverse=True)[:CHOICES]
    info = None
    cid = request.GET.get("cid", "").strip()
    if cid:
        rec = _find(who, cid)
        if rec is None:
            raise Http404
        info = detail(who, rec)
    with timezone.override(own.tzinfo):
        return render(request, "ui/provenance.html", _context(
            own, who=who, is_demo=who.handle == DEMO, demo=demo, recent=recent, info=info, cid=cid))
