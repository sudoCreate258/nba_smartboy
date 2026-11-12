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


def today(contributor, now=None):
    """Everything the home screen shows, for the contributor's local today."""
    now = now or timezone.now()
    day = now.astimezone(contributor.tzinfo).date()
    zone = zone_report(contributor, weeks=1, until=day)
    training = training_report(contributor, weeks=1, until=day)
    tz = contributor.tzinfo
    stops = [
        {"at": c["at"].astimezone(tz), "what": f"{c['area']} discomfort, score {c['score']}"}
        for c in zone["stop_signals"]
    ] + [
        {"at": s["started_at"].astimezone(tz),
         "what": f"joint pain {s['joint_pain']} ({s['joint_pain_area'] or 'area not given'}), {s['exercise']}"}
        for s in training["stop_signals"]
    ]
    probes = []
    for kind in SCORED_KINDS:
        r = kind_report(contributor, kind)
        probes.append({"kind": str(kind), "flag": r["level"], "reasons": r["reasons"]})
    amber = zone["zone"][-1]["amber"]
    return {
        "day": day,
        "checkins": checkins(contributor, day),
        "stop_signals": sorted(stops, key=lambda s: s["at"]),
        "earlier_stop_signals": zone["earlier_stop_signals"] + training["earlier_stop_signals"],
        "probes": probes,
        "zone": {"flag": {True: "amber", False: "none", None: "insufficient data"}[amber["state"]],
                 "detail": amber["detail"]},
    }
