# SPDX-License-Identifier: AGPL-3.0-or-later
"""Permissions and Statement pages (M5 R7). Server-rendered; nothing here is queued offline."""
from django.contrib.auth.decorators import login_required
from django.http import StreamingHttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from ledger import statement as stmt_mod
from ledger.models import Recipient
from nymbus.ledger import UNIT_LABEL

from .modules import categories
from .today import contributor_for
from .views import _context


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
