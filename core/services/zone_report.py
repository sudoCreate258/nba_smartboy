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


class ProbeResolver:
    """Resolves referenced probe CIDs to current sessions of one contributor, in memory.

    Loads the contributor's current sessions and supersession events once, then
    follows correction chains (latest event per old CID) without further queries.
    """

    def __init__(self, contributor):
        self.current = {p.cid: p for p in ProbeSession.objects.current().filter(contributor=contributor)}
        self.next = {}
        for old, new in (Supersession.objects.filter(contributor=contributor)
                         .order_by("id").values_list("old_cid", "new_cid")):
            self.next[old] = new  # later events win

    def resolve(self, cid):
        """(session or None, corrected: bool)."""
        start = cid
        for _ in range(MAX_CHAIN):
            if cid in self.current:
                return self.current[cid], cid != start
            if cid not in self.next:
                return None, False
            cid = self.next[cid]
        return None, False


def current_probe(cid, contributor):
    """The current probe session for a referenced CID, following corrections; None if missing."""
    return ProbeResolver(contributor).resolve(cid)[0]


def _metrics(session):
    return {m: None if getattr(session, m) is None else float(getattr(session, m)) for m in zone.RESET_METRICS}


def resolve_reset(reset, resolver):
    """({"kind", "before", "after", "corrected"}, None) or (None, problem text).

    The probes are rechecked against the Reset's own rules after following
    corrections: current mini_puzzle sessions of the reset's contributor that
    bracket the reset (before < at < after).
    """
    before, before_fixed = resolver.resolve(reset.before_probe_cid)
    after, after_fixed = resolver.resolve(reset.after_probe_cid)
    label = f"reset {reset.kind} at {reset.at.astimezone(reset.contributor.tzinfo):%Y-%m-%d %H:%M} ({reset.cid[:12]})"
    if before is None or after is None:
        return None, f"{label}: a referenced probe no longer resolves to a current session"
    if before.kind != ProbeSession.Kind.MINI_PUZZLE or after.kind != ProbeSession.Kind.MINI_PUZZLE:
        return None, f"{label}: a referenced probe was corrected to a kind other than mini_puzzle"
    if not before.started_at < reset.at < after.started_at:
        return None, f"{label}: the corrected probes no longer bracket the reset"
    return {"kind": reset.kind, "before": _metrics(before), "after": _metrics(after),
            "corrected": before_fixed or after_fixed}, None


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

    # Earlier weeks are needed for the amber comparison, but only PRIOR_WEEKS of them.
    lookback = start - datetime.timedelta(weeks=zone.PRIOR_WEEKS)
    blocks = [block_dict(b) for b in WorkBlock.objects.current()
              .filter(contributor=contributor, start__gte=lookback, start__lt=end)]
    all_weeks = zone.weekly_zone(blocks, tz)
    zone_weeks = []
    for week in reported:
        summary = all_weeks.get(week)
        zone_weeks.append({"week": week, "summary": summary, "amber": zone.zone_amber(all_weeks, week)})

    checks = [check_dict(c) for c in DiscomfortCheck.objects.current()
              .filter(contributor=contributor, at__gte=start, at__lt=end)]
    discomfort = zone.weekly_discomfort(checks, tz)

    earlier_stops = DiscomfortCheck.objects.current().filter(
        contributor=contributor, at__lt=start, sharp_or_numb=True
    ).count()

    resolver = ProbeResolver(contributor)
    resets, excluded, corrected = [], [], 0
    for r in Reset.objects.current().filter(contributor=contributor, at__lt=end).select_related("contributor"):
        item, problem = resolve_reset(r, resolver)
        if problem:
            excluded.append(problem)
        else:
            resets.append(item)
            corrected += item["corrected"]

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
        "earlier_stop_signals": earlier_stops,
        "zone": zone_weeks,
        "discomfort": [{"week": w, "summary": discomfort.get(w)} for w in reported],
        "resets": zone.reset_effect(resets),
        "resets_excluded": excluded,
        "resets_corrected": corrected,
        "weekly_checks": weekly_checks,
        "probes": probes,
    }
