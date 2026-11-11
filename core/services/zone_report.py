# SPDX-License-Identifier: AGPL-3.0-or-later
"""Django side of the zone report: loads current records and calls twin_metrics.zone."""
import datetime

from django.utils import timezone

from twin_metrics import zone

from ..models import DiscomfortCheck, ProbeSession, Reset, Supersession, WeeklyCheck, WorkBlock
from .probe_report import SCORED_KINDS, kind_report

MAX_CHAIN = 50  # guard when following corrections of a referenced probe


def week_range(contributor, weeks, until=None):
    """The `weeks` local Mondays ending with the week of `until` (default: today), oldest first."""
    today = until or timezone.now().astimezone(contributor.tzinfo).date()
    last = today - datetime.timedelta(days=today.weekday())
    return [last - datetime.timedelta(weeks=i) for i in range(weeks - 1, -1, -1)]


def _window_end(contributor, last_week):
    """Aware datetime at the end of the local week starting `last_week`."""
    return datetime.datetime.combine(last_week + datetime.timedelta(days=7), datetime.time.min, tzinfo=contributor.tzinfo)


def current_probe(cid):
    """The current probe session for a referenced CID, following corrections; None if missing."""
    seen = 0
    while seen < MAX_CHAIN:
        session = ProbeSession.objects.current().filter(cid=cid).first()
        if session is not None:
            return session
        step = Supersession.objects.filter(old_cid=cid).order_by("-id").first()
        if step is None:
            return None
        cid, seen = step.new_cid, seen + 1
    return None


def _metrics(session):
    if session is None:
        return {}
    return {m: None if getattr(session, m) is None else float(getattr(session, m)) for m in zone.RESET_METRICS}


def block_dict(b):
    return {"start": b.start, "end": b.end, "absorption": b.absorption, "interruptions": b.interruptions,
            "location": b.location, "posture": b.posture, "planned_length_min": b.planned_length_min}


def check_dict(c):
    return {"at": c.at, "area": c.area, "score": c.score, "trigger": c.trigger, "countermove": c.countermove,
            "sharp_or_numb": c.sharp_or_numb, "notes": c.notes, "cid": c.cid}


def zone_report(contributor, weeks=4, until=None):
    """Everything the zone report shows, for the given local weeks. Read-only."""
    tz = contributor.tzinfo
    reported = week_range(contributor, weeks, until)
    end = _window_end(contributor, reported[-1])
    start = datetime.datetime.combine(reported[0], datetime.time.min, tzinfo=tz)

    blocks = [block_dict(b) for b in WorkBlock.objects.current().filter(contributor=contributor, start__lt=end)]
    all_weeks = zone.weekly_zone(blocks, tz)  # includes earlier weeks, needed for the amber comparison
    zone_weeks = []
    for week in reported:
        summary = all_weeks.get(week)
        zone_weeks.append({"week": week, "summary": summary, "amber": zone.zone_amber(all_weeks, week)})

    checks = [check_dict(c) for c in DiscomfortCheck.objects.current()
              .filter(contributor=contributor, at__gte=start, at__lt=end)]
    discomfort = zone.weekly_discomfort(checks, tz)

    resets = []
    for r in Reset.objects.current().filter(contributor=contributor, at__lt=end):
        resets.append({"kind": r.kind, "before": _metrics(current_probe(r.before_probe_cid)),
                       "after": _metrics(current_probe(r.after_probe_cid))})

    weekly_checks = list(
        WeeklyCheck.objects.current()
        .filter(contributor=contributor, week_start__gte=reported[0], week_start__lte=reported[-1])
        .order_by("week_start", "instrument")
    )

    probes = []
    for kind in SCORED_KINDS:
        r = kind_report(contributor, kind)
        probes.append({"kind": str(kind), "status": r["status"], "flag": r["level"], "reasons": r["reasons"]})

    return {
        "weeks": reported,
        "stop_signals": zone.stop_signals(checks),
        "zone": zone_weeks,
        "discomfort": [{"week": w, "summary": discomfort.get(w)} for w in reported],
        "resets": zone.reset_effect(resets),
        "weekly_checks": weekly_checks,
        "probes": probes,
    }
