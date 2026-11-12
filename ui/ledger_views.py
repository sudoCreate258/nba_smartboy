# SPDX-License-Identifier: AGPL-3.0-or-later
"""Permissions and Statement pages (M5 R7). Server-rendered; nothing here is queued offline."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404, StreamingHttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET

from core.services.export import BY_KIND
from ledger import service
from ledger import statement as stmt_mod
from ledger.models import Grant, Recipient, Revocation
from nymbus.ledger import UNIT_LABEL

from .forms import GrantForm, RevokeForm
from .modules import CORE, categories, enabled_ids, registry
from .today import contributor_for
from .views import _context


def _sections(contributor, bound=None, now=None):
    """[{owner, name, on, categories: [{id, label, kinds, count, active, past, form}]}], core first."""
    now = now or timezone.now()
    reg, enabled = registry(), enabled_ids()
    revoked = {r.grant_cid: r for r in Revocation.objects.filter(contributor=contributor)}
    grants = list(Grant.objects.filter(contributor=contributor).order_by("-start", "-id"))
    recipients = dict(Recipient.choices)
    sections = {}
    for cat in categories():
        owner = cat["owner"]
        section = sections.setdefault(owner, {
            "owner": owner, "name": "Core" if owner == CORE else reg[owner]["name"],
            "on": owner == CORE or owner in enabled, "categories": []})
        count = sum(BY_KIND[k].objects.current().filter(contributor=contributor).count() for k in cat["kinds"])
        active, past = [], []
        for g in (g for g in grants if g.category == cat["id"]):
            row = {"g": g, "recipient": recipients.get(g.recipient, g.recipient), "revocation": revoked.get(g.cid)}
            (active if g.is_active(now, revocation=row["revocation"]) or g.start > now else past).append(row)
        form = bound if bound is not None and bound.prefix == cat["id"] else GrantForm(prefix=cat["id"])
        section["categories"].append({**cat, "count": count, "active": active, "past": past, "form": form})
    return list(sections.values())


@login_required
def permissions_page(request):
    """Who may read each data category: grant (POST) and links to revoke."""
    contributor = contributor_for(request.user)
    with timezone.override(contributor.tzinfo):
        bound, status = None, 200
        if request.method == "POST":
            category = request.POST.get("category", "")
            if category not in {c["id"] for c in categories()}:
                raise Http404
            bound = GrantForm(request.POST, prefix=category)
            if bound.is_valid():
                try:
                    g = service.grant(contributor, category, bound.cleaned_data["recipient"],
                                      bound.cleaned_data["purpose"], end=bound.cleaned_data["end"])
                except ValidationError as exc:
                    bound.add_error(None, exc.messages)
                else:
                    messages.success(request, f"{dict(Recipient.choices)[g.recipient]} may now read "
                                              f"{_label(category)}. Every read is recorded on your statement.")
                    return redirect(reverse("ui:permissions") + f"#cat-{category}")
            status = 400
        return render(request, "ui/permissions.html", _context(contributor, sections=_sections(contributor, bound)),
                      status=status)


def _label(category):
    return next((c["label"] for c in categories() if c["id"] == category), category)


@login_required
def revoke_page(request, cid):
    """Confirmation step for a revocation (GET shows it, POST confirms)."""
    contributor = contributor_for(request.user)
    g = Grant.objects.filter(cid=cid, contributor=contributor).first()
    if g is None:
        raise Http404
    recipient = dict(Recipient.choices).get(g.recipient, g.recipient)
    with timezone.override(contributor.tzinfo):
        ended = g.end is not None and g.end <= timezone.now()
        if request.method != "POST" and (ended or g.revocation() is not None):
            messages.info(request, "This grant is no longer active; there is nothing to revoke.")
            return redirect(reverse("ui:permissions") + f"#cat-{g.category}")
        form = RevokeForm(request.POST if request.method == "POST" else None)
        if request.method == "POST" and form.is_valid():
            try:
                service.revoke(contributor, g.cid, reason=form.cleaned_data["reason"])
            except ValidationError as exc:
                messages.warning(request, " ".join(exc.messages))
            else:
                messages.success(request, f"Revoked: {recipient} can no longer read {_label(g.category)}. "
                                          "Earlier reads stay in the ledger.")
            return redirect(reverse("ui:permissions") + f"#cat-{g.category}")
        return render(request, "ui/revoke.html", _context(contributor, g=g, recipient=recipient,
                                                          category_label=_label(g.category), form=form))


def _labels():
    return {c["id"]: c["label"] for c in categories()}, dict(Recipient.choices)


@login_required
@require_GET
def statement_page(request):
    contributor = contributor_for(request.user)
    stmt = stmt_mod.build(contributor, request.GET.get("month"))
    cats, recipients = _labels()
    rows = [{**r, "category_label": cats.get(r["category"], r["category"]),
             "recipient_label": recipients.get(r["recipient"], r["recipient"])} for r in stmt["rows"]]
    totals = [{**t, "category_label": cats.get(t["category"], t["category"])} for t in stmt["totals"]]
    return render(request, "ui/statement.html", _context(contributor, s=stmt, rows=rows, totals=totals,
                                                         unit=UNIT_LABEL))


@login_required
@require_GET
def statement_download(request):
    contributor = contributor_for(request.user)
    stmt = stmt_mod.build(contributor, request.GET.get("month"))
    resp = StreamingHttpResponse((line + "\n" for line in stmt_mod.jsonl(contributor, stmt)),
                                 content_type="application/x-ndjson; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="statement-{contributor.handle}-{stmt["month"]}.jsonl"'
    resp["Cache-Control"] = "no-store"
    return resp
