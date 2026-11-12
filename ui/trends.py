# SPDX-License-Identifier: AGPL-3.0-or-later
"""Trend charts for the last 4 or 12 weeks (R2). Reads current records; computes nothing new:
probe medians and baselines come from twin_metrics.probes, zone weeks from twin_metrics.zone."""
import datetime

from django.utils import timezone

from core.models import DailySnapshot, DiscomfortCheck, WorkBlock
from core.services.probe_report import SCORED_KINDS, baseline_window, current_sessions, session_dict
from core.services.zone_report import block_dict, check_dict
from twin_metrics import probes, zone
from twin_metrics.svg import bar_chart, line_chart

from .modules import enabled_ids, is_on


def chart(title, points, source, unit="", band=None, kind="line", group="core"):
    """One chart: its data (for the API) and its SVG (for the page). `group` ties it to a module."""
    draw = bar_chart(title, points, unit) if kind == "bar" else line_chart(title, points, unit, band=band)
    return {"title": title, "source": source, "points": points, "unit": unit, "band": band, "svg": draw,
            "group": group}


def _days(start_day, end_day):
    d = start_day
    while d <= end_day:
        yield d
        d += datetime.timedelta(days=1)


def _bedtime_hour(dt, tz):
    """Local bedtime as hours on a noon-to-noon clock, so 23:30 = 23.5 and 00:30 = 24.5."""
    local = dt.astimezone(tz)
    hour = local.hour + local.minute / 60
    return hour + 24 if hour < 12 else hour


def _label(d):
    return d.strftime("%d %b")


def build(contributor, weeks=4, today=None, enabled=None):
    """Charts for the period; charts of disabled modules are left out."""
    enabled = enabled_ids() if enabled is None else enabled
    data = _build(contributor, weeks, today, enabled)
    data["charts"] = [c for c in data["charts"] if is_on("charts", c["group"], enabled)]
    return data


def _build(contributor, weeks, today, enabled):
    tz = contributor.tzinfo
    today = today or timezone.now().astimezone(tz).date()
    last_monday = today - datetime.timedelta(days=today.weekday())
    mondays = [last_monday - datetime.timedelta(weeks=i) for i in range(weeks - 1, -1, -1)]
    first_day = mondays[0]
    days = list(_days(first_day, today))
    start = datetime.datetime.combine(first_day, datetime.time.min, tzinfo=tz)
    end = datetime.datetime.combine(today + datetime.timedelta(days=1), datetime.time.min, tzinfo=tz)

    snaps = {s.date: s for s in DailySnapshot.objects.current().filter(
        contributor=contributor, date__gte=first_day, date__lte=today)}

    def daily(attr, pre_session_only=False):
        out = []
        for d in days:
            s = snaps.get(d)
            v = None if s is None else getattr(s, attr)
            if pre_session_only and s is not None and s.bia_timing != DailySnapshot.BiaTiming.PRE_SESSION:
                v = None
            out.append((_label(d), None if v is None else float(v)))
        return out

    src = "Daily snapshots (current records)"
    pre = src + ", bia_timing = pre_session"
    bedtimes = [(_label(d), None if snaps.get(d) is None or snaps[d].bedtime is None
                 else round(_bedtime_hour(snaps[d].bedtime, tz), 2)) for d in days]
    charts = [
        chart("Sleep score", daily("sleep_score"), src),
        chart("Bedtime (hour, 24 = midnight)", bedtimes, src),
        chart("Resting HR during sleep", daily("resting_hr_sleep"), src, "bpm"),
        chart("HRV", daily("hrv"), src, "ms"),
        chart("Weight (pre-session readings only)", daily("weight_kg", True), pre, "kg"),
        chart("Body fat (pre-session readings only)", daily("body_fat_pct", True), pre, "%"),
    ]

    for kind in (SCORED_KINDS if is_on("charts", "probes", enabled) else ()):
        sessions = current_sessions(contributor, kind)
        window = baseline_window(contributor, kind, sessions)
        metric, _ = probes.METRICS[kind][0]  # accuracy_pct for every scored kind
        medians = probes.rolling_medians([session_dict(s) for s in sessions], probes.METRICS[kind])
        points = [(timezone.localtime(s.started_at, tz).strftime("%d %b"), m.get(metric))
                  for s, m in zip(sessions, medians) if start <= s.started_at < end]
        band = None
        if window["problem"] is None and len(window["baseline"]) >= probes.MIN_BASELINE:
            mean, sd, _ = probes.baseline_stats([session_dict(s) for s in window["baseline"]],
                                                probes.METRICS[kind])[metric]
            if mean is not None and sd:
                band = (mean - sd, mean + sd)
        note = "shaded: baseline mean +/- 1 SD" if band else "no usable baseline yet"
        charts.append(chart(f"Probe {kind}: rolling median accuracy (last 3 sessions)", points,
                            f"Probe sessions ({kind}), current records; {note}", "%", band=band, group="probes"))

    lookback = start - datetime.timedelta(weeks=zone.PRIOR_WEEKS)
    blocks = [block_dict(b) for b in WorkBlock.objects.current().filter(
        contributor=contributor, start__gte=lookback, start__lt=end)]
    weekly = zone.weekly_zone(blocks, tz)
    hours = [(_label(m), weekly[m]["total_hours"] if m in weekly else None) for m in mondays]
    share = [(_label(m), None if m not in weekly or weekly[m]["focus_share"] is None
              else round(100 * weekly[m]["focus_share"], 1)) for m in mondays]
    wsrc = "Work blocks (current records), local weeks starting Monday"
    charts.append(chart("Weekly work hours", hours, wsrc, "h", kind="bar", group="work"))
    charts.append(chart("Weekly focus share", share, wsrc + "; high focus = absorption >= 4 and interruptions <= 1",
                        "%", group="work"))

    checks = [check_dict(c) for c in DiscomfortCheck.objects.current().filter(
        contributor=contributor, at__gte=start, at__lt=end)]
    disc = zone.weekly_discomfort(checks, tz)
    areas = sorted({a for w in disc.values() for a in w["mean_score"]})
    for area in areas:
        pts = [(_label(m), disc[m]["mean_score"].get(area) if m in disc else None) for m in mondays]
        charts.append(chart(f"Discomfort: {area.replace('_', ' ')} (weekly mean, 0-10)", pts,
                            "Discomfort checks (current records)", group="discomfort"))
    if not areas:
        charts.append(chart("Discomfort by area", [], "Discomfort checks (current records): none in this period",
                            group="discomfort"))
    return {"weeks": weeks, "first_day": first_day, "today": today, "charts": charts}


def as_data(trends):
    """The same charts as plain data (for /api/v0/trends): title, source, points, unit, band."""
    keep = ("title", "source", "points", "unit", "band", "group")
    return {"weeks": trends["weeks"], "first_day": trends["first_day"], "today": trends["today"],
            "charts": [{k: c[k] for k in keep} for c in trends["charts"]]}
