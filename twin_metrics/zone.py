# SPDX-License-Identifier: AGPL-3.0-or-later
"""Zone, reset and discomfort statistics (M3).

Plain Python, no Django imports. Inputs are lists of dicts with aware
datetimes; weeks are local ISO weeks (Monday start) in the given time zone.
A block that crosses midnight (or a week boundary) counts in the week of its
start. This is a load gauge, not a medical assessment.
"""
import datetime
import statistics
import zoneinfo

HIGH_FOCUS_MIN_ABSORPTION = 4
HIGH_FOCUS_MAX_INTERRUPTIONS = 1
PRIOR_WEEKS = 3
SHARE_DROP = 0.20  # amber: focus share at least 20% below the prior mean ...
HOURS_BAND = 0.10  # ... while total hours stay within +-10% of the prior mean
MIN_RESET_N = 5
DISCOMFORT_THRESHOLD = 3
BREAKDOWNS = ("location", "posture", "planned_length_min")
UNKNOWN = "unknown"


def _tz(tz):
    return zoneinfo.ZoneInfo(tz) if isinstance(tz, str) else tz


def week_of(moment, tz):
    """Local Monday (date) of the ISO week containing `moment`."""
    local = moment.astimezone(_tz(tz)).date()
    return local - datetime.timedelta(days=local.weekday())


def is_high_focus(block):
    """absorption >= 4 and interruptions <= 1; a missing value means not high-focus."""
    absorption, interruptions = block.get("absorption"), block.get("interruptions")
    if absorption is None or interruptions is None:
        return False
    return absorption >= HIGH_FOCUS_MIN_ABSORPTION and interruptions <= HIGH_FOCUS_MAX_INTERRUPTIONS


def minutes(block):
    return (block["end"] - block["start"]).total_seconds() / 60


def theta(lengths):
    """Median and interquartile range of high-focus block lengths (minutes).

    {"n", "median", "q1", "q3", "iqr"}; values are None with no blocks. One block
    gives q1 == q3 == median. Quartiles use the inclusive method.
    """
    if not lengths:
        return {"n": 0, "median": None, "q1": None, "q3": None, "iqr": None}
    if len(lengths) == 1:
        q1 = q3 = lengths[0]
    else:
        q1, _, q3 = statistics.quantiles(lengths, n=4, method="inclusive")
    return {"n": len(lengths), "median": statistics.median(lengths), "q1": q1, "q3": q3, "iqr": q3 - q1}


def _share(focus_min, total_min):
    return focus_min / total_min if total_min else None


def _summary(blocks):
    total = sum(minutes(b) for b in blocks)
    focus = [minutes(b) for b in blocks if is_high_focus(b)]
    return {
        "blocks": len(blocks),
        "total_hours": total / 60,
        "high_focus_minutes": sum(focus),
        "focus_share": _share(sum(focus), total),
        "theta": theta(focus),
    }


def weekly_zone(blocks, tz):
    """{week Monday: summary} for every week that has at least one block, oldest first.

    summary: blocks, total_hours, high_focus_minutes, focus_share, theta, and
    "by": {breakdown: {value: {blocks, total_hours, high_focus_minutes, focus_share}}}
    for location, posture and planned_length_min (missing values under "unknown").
    """
    weeks = {}
    for b in blocks:
        weeks.setdefault(week_of(b["start"], tz), []).append(b)
    out = {}
    for week in sorted(weeks):
        items = weeks[week]
        summary = _summary(items)
        summary["by"] = {}
        for key in BREAKDOWNS:
            groups = {}
            for b in items:
                value = b.get(key)
                groups.setdefault(UNKNOWN if value is None else value, []).append(b)
            summary["by"][key] = {
                value: {k: v for k, v in _summary(group).items() if k != "theta"}
                for value, group in sorted(groups.items(), key=lambda kv: str(kv[0]))
            }
        out[week] = summary
    return out


def zone_amber(weeks, week):
    """Zone amber for `week` against the PRIOR_WEEKS calendar weeks right before it.

    weeks: weekly_zone() output. Every prior week must have blocks (a week
    without blocks is missing data, not a week of rest), otherwise the state is
    None ("insufficient data"). Amber (True) when the focus share is at least
    SHARE_DROP below the prior mean while total hours stay within HOURS_BAND of
    the prior mean: running on effort, not flow.
    Returns {"state": True/False/None, "detail": str}.
    """
    current = weeks.get(week)
    if current is None:
        return {"state": None, "detail": "insufficient data: no work blocks this week"}
    prior = [week - datetime.timedelta(weeks=i) for i in range(1, PRIOR_WEEKS + 1)]
    have = [weeks[w] for w in prior if w in weeks]
    if len(have) < PRIOR_WEEKS:
        return {"state": None, "detail": f"insufficient data: {len(have)} of {PRIOR_WEEKS} prior weeks have work blocks"}
    mean_share = statistics.fmean(w["focus_share"] for w in have)
    mean_hours = statistics.fmean(w["total_hours"] for w in have)
    share, hours = current["focus_share"], current["total_hours"]
    share_fell = mean_share > 0 and share <= (1 - SHARE_DROP) * mean_share
    hours_steady = abs(hours - mean_hours) <= HOURS_BAND * mean_hours
    detail = (f"focus share {share:.0%} vs prior mean {mean_share:.0%}; "
              f"hours {hours:.1f} vs prior mean {mean_hours:.1f}")
    return {"state": share_fell and hours_steady, "detail": detail}


RESET_METRICS = ("accuracy_pct", "median_solve_s")


def _delta(reset, metric):
    before, after = reset["before"].get(metric), reset["after"].get(metric)
    return None if before is None or after is None else after - before


def reset_effect(resets):
    """Per reset kind: n and mean change (after - before) per mini-probe metric, vs "none".

    resets: [{"kind", "before": {metric: value}, "after": {metric: value}}].
    Returns {kind: {"n", "interpretable", metric: {"n", "mean_change", "vs_none"}}};
    kinds with n < MIN_RESET_N are kept but interpretable is False. vs_none is
    the kind's mean change minus the mean change of "none" (None when either is missing).
    A higher accuracy change is better; a lower solve-time change is better.
    """
    by_kind = {}
    for r in resets:
        by_kind.setdefault(r["kind"], []).append(r)
    out = {}
    for kind, items in sorted(by_kind.items()):
        row = {"n": len(items), "interpretable": len(items) >= MIN_RESET_N}
        for metric in RESET_METRICS:
            deltas = [d for d in (_delta(r, metric) for r in items) if d is not None]
            row[metric] = {"n": len(deltas), "mean_change": statistics.fmean(deltas) if deltas else None}
        out[kind] = row
    control = out.get("none")
    for kind, row in out.items():
        for metric in RESET_METRICS:
            mine = row[metric]["mean_change"]
            base = control[metric]["mean_change"] if control else None
            row[metric]["vs_none"] = None if kind == "none" or mine is None or base is None else mine - base
    return out


def stop_signals(checks):
    """Discomfort checks marked sharp_or_numb, oldest first."""
    return sorted((c for c in checks if c.get("sharp_or_numb")), key=lambda c: c["at"])


def weekly_discomfort(checks, tz):
    """{week Monday: summary} for weeks with checks, oldest first.

    summary: n; mean_score per area; count of checks with score >= 3 per trigger;
    countermove_share (share of score >= 3 checks with a countermove other than
    "none", None when there are none); stop_signals (sharp_or_numb checks).
    """
    weeks = {}
    for c in checks:
        weeks.setdefault(week_of(c["at"], tz), []).append(c)
    out = {}
    for week in sorted(weeks):
        items = weeks[week]
        areas = {}
        for c in items:
            areas.setdefault(c["area"], []).append(c["score"])
        high = [c for c in items if c["score"] >= DISCOMFORT_THRESHOLD]
        triggers = {}
        for c in high:
            triggers[c["trigger"]] = triggers.get(c["trigger"], 0) + 1
        moved = [c for c in high if c.get("countermove") not in (None, "none")]
        out[week] = {
            "n": len(items),
            "mean_score": {a: statistics.fmean(s) for a, s in sorted(areas.items())},
            "high_by_trigger": dict(sorted(triggers.items())),
            "countermove_share": len(moved) / len(high) if high else None,
            "stop_signals": stop_signals(items),
        }
    return out
