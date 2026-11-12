# SPDX-License-Identifier: AGPL-3.0-or-later
"""Trend charts for the last 4 or 12 weeks (R2). Reads current records; computes nothing new:
probe medians and baselines come from twin_metrics.probes, zone weeks from twin_metrics.zone."""
import datetime

from django.utils import timezone

from core.models import DailySnapshot, DiscomfortCheck, WorkBlock
from core.services.probe_report import SCORED_KINDS, baseline_window, current_sessions, session_dict
from twin_metrics import probes, zone
from twin_metrics.svg import bar_chart, line_chart

from core.services.zone_report import block_dict, check_dict


def _days(start_day, end_day):
    d = start_day
    while d <= end_day:
        yield d
        d += datetime.timedelta(days=1)


def _bedtime_hour(dt, tz):
    """Local bedtime as hours after noon-to-noon start, so 23:30 = 23.5 and 00:30 = 24.5."""
    local = dt.astimezone(tz)
    hour = local.hour + local.minute / 60
    return hour + 24 if hour < 12 else hour


def build(contributor, weeks=4, today=None):
    tz = contributor.tzinfo
    today = today or timezone.now().astimezone(tz).date()
    last_monday = today - datetime.timedelta(days=today.weekday())
    mondays = [last_monday - datetime.timedelta(weeks=i) for i in range(weeks - 1, -1, -1)]
    first_day = mondays[0]
    days = list(_days(first_day, today))
    day_label = lambda d: d.strftime("%d %b")  # noqa: E731
    week_label = lambda d: d.strftime("%d %b")  # noqa: E731
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
            out.append((day_label(d), None if v is None else float(v)))
        return out

    src = "Daily snapshots (current records)"
    charts = [
        {"title": "Sleep score", "svg": line_chart("Sleep score", daily("sleep_score")), "source": src},
        {"title": "Bedtime (hour, 24 = midnight)", "source": src, "svg": line_chart(
            "Bedtime (hour, 24 = midnight)",
            [(day_label(d), None if snaps.get(d) is None or snaps[d].bedtime is None
              else round(_bedtime_hour(snaps[d].bedtime, tz), 2)) for d in days])},
        {"title": "Resting HR during sleep", "svg": line_chart("Resting HR during sleep", daily("resting_hr_sleep"), "bpm"),
         "source": src},
        {"title": "HRV", "svg": line_chart("HRV", daily("hrv"), "ms"), "source": src},
        {"title": "Weight (pre-session readings only)", "source": src + ", bia_timing = pre_session",
         "svg": line_chart("Weight (pre-session readings only)", daily("weight_kg", True), "kg")},
        {"title": "Body fat (pre-session readings only)", "source": src + ", bia_timing = pre_session",
         "svg": line_chart("Body fat (pre-session readings only)", daily("body_fat_pct", True), "%")},
    ]

    for kind in SCORED_KINDS:
        sessions = current_sessions(contributor, kind)
        window = baseline_window(contributor, kind, sessions)
        metric, _ = probes.METRICS[kind][0]  # accuracy_pct for every scored kind
        dicts = [session_dict(s) for s in sessions]
        medians = probes.rolling_medians(dicts, probes.METRICS[kind])
        points = [(timezone.localtime(s.started_at, tz).strftime("%d %b"), m.get(metric))
                  for s, m in zip(sessions, medians) if start <= s.started_at < end]
        band = None
        if window["problem"] is None and len(window["baseline"]) >= probes.MIN_BASELINE:
            mean, sd, _ = probes.baseline_stats([session_dict(s) for s in window["baseline"]],
                                                probes.METRICS[kind])[metric]
            if mean is not None and sd:
                band = (mean - sd, mean + sd)
        title = f"Probe {kind}: rolling median accuracy (last 3 sessions)"
        note = "shaded: baseline mean +/- 1 SD" if band else "no usable baseline yet"
        charts.append({"title": title, "svg": line_chart(title, points, "%", band=band),
                       "source": f"Probe sessions ({kind}), current records; {note}"})

    lookback = start - datetime.timedelta(weeks=zone.PRIOR_WEEKS)
    blocks = [block_dict(b) for b in WorkBlock.objects.current().filter(
        contributor=contributor, start__gte=lookback, start__lt=end)]
    weekly = zone.weekly_zone(blocks, tz)
    hours = [(week_label(m), weekly[m]["total_hours"] if m in weekly else None) for m in mondays]
    share = [(week_label(m), None if m not in weekly or weekly[m]["focus_share"] is None
              else round(100 * weekly[m]["focus_share"], 1)) for m in mondays]
    wsrc = "Work blocks (current records), local weeks starting Monday"
    charts.append({"title": "Weekly work hours", "svg": bar_chart("Weekly work hours", hours, "h"), "source": wsrc})
    charts.append({"title": "Weekly focus share", "svg": line_chart("Weekly focus share", share, "%"),
                   "source": wsrc + "; high focus = absorption >= 4 and interruptions <= 1"})

    checks = [check_dict(c) for c in DiscomfortCheck.objects.current().filter(
        contributor=contributor, at__gte=start, at__lt=end)]
    disc = zone.weekly_discomfort(checks, tz)
    areas = sorted({a for w in disc.values() for a in w["mean_score"]})
    for area in areas:
        pts = [(week_label(m), disc[m]["mean_score"].get(area) if m in disc else None) for m in mondays]
        title = f"Discomfort: {area.replace('_', ' ')} (weekly mean, 0-10)"
        charts.append({"title": title, "svg": line_chart(title, pts), "source": "Discomfort checks (current records)"})
    if not areas:
        charts.append({"title": "Discomfort by area", "svg": line_chart("Discomfort by area", []),
                       "source": "Discomfort checks (current records): none in this period"})
    return {"weeks": weeks, "first_day": first_day, "today": today, "charts": charts}
