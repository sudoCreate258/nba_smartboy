# SPDX-License-Identifier: AGPL-3.0-or-later
"""Owner page for dtom data (027 Part C): /twin/?day=YYYY-MM-DD. Read-only, server-rendered, no script.
Estimated by dtom from the owner's cameras, not a clinical measurement."""
import datetime

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from core.models import PostureSample, TwinMinute
from twin_metrics.dtom import REGIONS, sparkline, summarize_day

from .today import contributor_for

MAX_ROWS = 600  # newest minutes shown as rows (a full day is 1440); the summary covers all of them
REGION_LABELS = {"neck": "Neck", "back": "Back", "shL": "Left shoulder", "shR": "Right shoulder"}


def _fmt(v, digits=1):
    return "–" if v is None else f"{v:.{digits}f}"


def day_view(contributor, day):
    tz = contributor.tzinfo
    start = datetime.datetime.combine(day, datetime.time(0), tzinfo=tz)
    end = start + datetime.timedelta(days=1)
    minutes = list(TwinMinute.objects.current().filter(contributor=contributor, t_start__gte=start, t_start__lt=end)
                   .order_by("t_start"))
    docs = [m.data for m in minutes]
    s = summarize_day(docs)
    regions = [{"label": REGION_LABELS[r], "avg": _fmt(s["load_avg"][r]), "max": _fmt(s["load_max"][r]),
                "above": s["minutes_above"][r], "fatigue": _fmt(s["fatigue_max"][r], 2),
                "spark": sparkline([(d.get("load_pct_avg") or {}).get(r) for d in docs])} for r in REGIONS]
    rows = []
    for m in minutes[-MAX_ROWS:]:
        d = m.data
        load = d.get("load_pct_avg") or {}
        face = d.get("face") or {}
        posture = d.get("posture") or {}
        rows.append({"t": m.t_start.astimezone(tz).strftime("%H:%M"),
                     "sitting": _fmt(posture.get("sitting_s"), 0), "standing": _fmt(posture.get("standing_s"), 0),
                     "loads": [_fmt(load.get(r)) for r in REGIONS], "blinks": _fmt(face.get("blinks_per_min"), 0),
                     "screen": _fmt((face.get("looking_pct") or {}).get("screen"), 0),
                     "events": len(d.get("events") or [])})
    samples = list(PostureSample.objects.current().filter(contributor=contributor, at__gte=start, at__lt=end)
                   .order_by("at"))
    return {"day": day, "summary": s, "sitting": _fmt(s["sitting_min"], 0), "blinks": _fmt(s["blinks_per_min"]),
            "screen": _fmt(s["screen_pct"], 0), "regions": regions, "rows": rows,
            "hidden_rows": max(0, len(minutes) - MAX_ROWS), "samples": samples}


@login_required
@require_GET
def twin_page(request):
    from .views import _context

    contributor = contributor_for(request.user)
    today = timezone.now().astimezone(contributor.tzinfo).date()
    try:
        day = datetime.date.fromisoformat(request.GET.get("day", ""))
    except ValueError:
        day = today
    with timezone.override(contributor.tzinfo):
        return render(request, "ui/twin.html", _context(
            contributor, v=day_view(contributor, day), prev=day - datetime.timedelta(days=1),
            next=day + datetime.timedelta(days=1), region_labels=[REGION_LABELS[r] for r in REGIONS]))
