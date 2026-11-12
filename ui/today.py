# SPDX-License-Identifier: AGPL-3.0-or-later
"""Data for the home screen: today's check-ins, latest flags and stop signals.

No business logic lives here: it only calls the core services and models.
"""
import datetime

from django.conf import settings
from django.utils import timezone

from core.models import Contributor, DailySnapshot, DiscomfortCheck, ProbeSession, Reset, WorkBlock
from core.services.probe_report import SCORED_KINDS, kind_report
from core.services.training_report import training_report
from core.services.zone_report import zone_report

from .modules import enabled_ids, is_on


def contributor_for(user):
    """The contributor whose data the app shows.

    Phase 1 has one contributor per instance; every login maps to TWIN_CONTRIBUTOR.
    Linking users to contributors is Nymbus phase 2.
    """
    return Contributor.objects.get(handle=settings.TWIN_CONTRIBUTOR)


def local_day_bounds(contributor, day):
    tz = contributor.tzinfo
    start = datetime.datetime.combine(day, datetime.time.min, tzinfo=tz)
    return start, start + datetime.timedelta(days=1)


def checkins(contributor, day):
    """[(label, done, kind)] for the five daily check-ins on the contributor's local `day`."""
    start, end = local_day_bounds(contributor, day)
    mine = {"contributor": contributor}
    return [
        ("Daily snapshot", DailySnapshot.objects.current().filter(date=day, **mine).exists(), "snapshot"),
        ("Probe", ProbeSession.objects.current().filter(started_at__gte=start, started_at__lt=end, **mine).exists(),
         "probe"),
        ("Work block", WorkBlock.objects.current().filter(start__gte=start, start__lt=end, **mine).exists(), "work"),
        ("Discomfort check", DiscomfortCheck.objects.current().filter(at__gte=start, at__lt=end, **mine).exists(),
         "discomfort"),
        ("Reset", Reset.objects.current().filter(at__gte=start, at__lt=end, **mine).exists(), "reset"),
    ]


def today(contributor, now=None, enabled=None):
    """Everything the home screen shows, for the contributor's local today.

    Sections of disabled modules are left out (`enabled`: module ids; default: the stored settings).
    """
    enabled = enabled_ids() if enabled is None else enabled
    now = now or timezone.now()
    day = now.astimezone(contributor.tzinfo).date()
    tz = contributor.tzinfo
    stops, earlier = [], 0
    zone_flag = None
    if is_on("home", "zone_flag", enabled) or is_on("home", "discomfort_stops", enabled):
        zone = zone_report(contributor, weeks=1, until=day)
        if is_on("home", "discomfort_stops", enabled):
            stops += [{"at": c["at"].astimezone(tz), "what": f"{c['area']} discomfort, score {c['score']}"}
                      for c in zone["stop_signals"]]
            earlier += zone["earlier_stop_signals"]
        if is_on("home", "zone_flag", enabled):
            amber = zone["zone"][-1]["amber"]
            zone_flag = {"flag": {True: "amber", False: "none", None: "insufficient data"}[amber["state"]],
                         "detail": amber["detail"]}
    if is_on("home", "training_stops", enabled):
        training = training_report(contributor, weeks=1, until=day)
        stops += [{"at": s["started_at"].astimezone(tz),
                   "what": f"joint pain {s['joint_pain']} ({s['joint_pain_area'] or 'area not given'}), {s['exercise']}"}
                  for s in training["stop_signals"]]
        earlier += training["earlier_stop_signals"]
    probes = []
    if is_on("home", "probe_flags", enabled):
        for kind in SCORED_KINDS:
            r = kind_report(contributor, kind)
            probes.append({"kind": str(kind), "flag": r["level"], "reasons": r["reasons"]})
    return {
        "day": day,
        "checkins": [c for c in checkins(contributor, day) if is_on("checkins", c[2], enabled)],
        "stop_signals": sorted(stops, key=lambda s: s["at"]),
        "earlier_stop_signals": earlier,
        "probes": probes,
        "zone": zone_flag,
    }
