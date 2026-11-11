# SPDX-License-Identifier: AGPL-3.0-or-later
"""Django side of the probe report: picks sessions and baseline windows."""
import datetime

from twin_metrics import probes

from ..models import DailySnapshot, ProbeBaseline, ProbeSession, WorkBlock

DEFAULT_BASELINE_N = 10
MAX_DEFAULT_SPAN = datetime.timedelta(days=42)  # a default baseline must fall within 42 days
SCORED_KINDS = (ProbeSession.Kind.PUZZLE_SET, ProbeSession.Kind.RAPID_GAME, ProbeSession.Kind.MINI_PUZZLE)


def current_sessions(contributor, kind):
    """Current (not superseded) sessions of a kind, oldest first; ties broken by CID."""
    return list(
        ProbeSession.objects.current()
        .filter(contributor=contributor, kind=kind)
        .order_by("started_at", "cid")
    )


def baseline_window(contributor, kind, sessions=None):
    """Split a kind's current sessions into baseline and later sessions.

    If the owner set a ProbeBaseline (newest frozen_at wins), the baseline is the
    sessions starting inside [start, end] and later sessions start after `end`.
    Otherwise the baseline is the first DEFAULT_BASELINE_N sessions, but only if
    they fall within MAX_DEFAULT_SPAN; if not, "problem" explains that a
    ProbeBaseline must be set and no flags are raised.
    Returns {"source", "start", "end", "baseline", "after", "problem"}; start/end
    are None when there are no baseline sessions in a default window; problem is
    None when the window is usable.
    """
    if sessions is None:
        sessions = current_sessions(contributor, kind)
    configured = ProbeBaseline.objects.filter(contributor=contributor, kind=kind).first()
    if configured is not None:
        return {
            "source": "configured",
            "start": configured.start,
            "end": configured.end,
            "baseline": [s for s in sessions if configured.start <= s.started_at <= configured.end],
            "after": [s for s in sessions if s.started_at > configured.end],
            "problem": None,
        }
    baseline, after = sessions[:DEFAULT_BASELINE_N], sessions[DEFAULT_BASELINE_N:]
    problem = None
    if len(baseline) == DEFAULT_BASELINE_N:
        span = baseline[-1].started_at - baseline[0].started_at
        if span > MAX_DEFAULT_SPAN:
            problem = (
                f"insufficient baseline: set a ProbeBaseline (the first {DEFAULT_BASELINE_N} sessions "
                f"span {span.days} days, more than {MAX_DEFAULT_SPAN.days})"
            )
    return {
        "source": "default",
        "start": baseline[0].started_at if baseline else None,
        "end": baseline[-1].started_at if baseline else None,
        "baseline": baseline,
        "after": after,
        "problem": problem,
    }

LOAD_DAYS = 3  # days (and nights) behind the sleep and work conditions


def _local_date(moment, tz):
    return moment.astimezone(tz).date()


def _day_start(day, tz):
    return datetime.datetime.combine(day, datetime.time.min, tzinfo=tz)


def sleep_falling(contributor, window, latest):
    """Is the mean sleep_score of the last 3 nights >= 1 SD below the baseline nights' mean?

    The nights are the 3 local days ending on the day of `latest` (a session).
    Returns {"state": True/False/None, "detail": str}; None means insufficient data.
    """
    tz = contributor.tzinfo
    current = DailySnapshot.objects.current().filter(contributor=contributor, sleep_score__isnull=False)
    if latest is None or window["start"] is None:
        return {"state": None, "detail": "insufficient data: no sessions"}
    end_day = _local_date(latest.started_at, tz)
    recent_days = [end_day - datetime.timedelta(days=i) for i in range(LOAD_DAYS)]
    recent = list(current.filter(date__in=recent_days).values_list("sleep_score", flat=True))
    baseline = list(
        current.filter(
            date__range=(_local_date(window["start"], tz), _local_date(window["end"], tz))
        ).values_list("sleep_score", flat=True)
    )
    if len(recent) < LOAD_DAYS:
        return {"state": None, "detail": f"insufficient data: {len(recent)} of {LOAD_DAYS} recent nights have a sleep score"}
    state = probes.deviates(sum(recent) / len(recent), baseline, probes.LOWER)
    if state is None:
        return {"state": None, "detail": f"insufficient data: {len(baseline)} baseline nights (need 2 with varying scores)"}
    return {"state": state, "detail": f"last {LOAD_DAYS} nights mean {sum(recent) / len(recent):.1f} vs {len(baseline)} baseline nights"}


def merge_intervals(intervals):
    """Sorted, non-overlapping (start, end) pairs; overlapping or touching pairs are joined."""
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _hours_in(blocks, start, end):
    """Hours covered by blocks inside [start, end); overlapping blocks are counted once."""
    clipped = [(max(b.start, start), min(b.end, end)) for b in blocks]
    return sum((e - s).total_seconds() for s, e in merge_intervals(p for p in clipped if p[1] > p[0])) / 3600


def work_rising(contributor, window, latest):
    """Are the work hours of the 3 local days up to `latest` >= 1 SD above the baseline's mean 3-day total?

    Baseline totals are every 3-day window that lies inside the baseline window and holds at
    least one WorkBlock; days without blocks are never counted as zero hours on their own.
    Returns {"state": True/False/None, "detail": str}; None means insufficient data.
    """
    tz = contributor.tzinfo
    if latest is None or window["start"] is None:
        return {"state": None, "detail": "insufficient data: no sessions"}
    span = datetime.timedelta(days=LOAD_DAYS)
    blocks = list(WorkBlock.objects.current().filter(contributor=contributor))
    end_day = _local_date(latest.started_at, tz)
    recent_start = _day_start(end_day - datetime.timedelta(days=LOAD_DAYS - 1), tz)
    recent_end = _day_start(end_day + datetime.timedelta(days=1), tz)
    if not any(b.end > recent_start and b.start < recent_end for b in blocks):
        return {"state": None, "detail": f"insufficient data: no work blocks in the last {LOAD_DAYS} days"}
    first, last = _local_date(window["start"], tz), _local_date(window["end"], tz)
    totals = []
    day = first + datetime.timedelta(days=LOAD_DAYS - 1)
    while day <= last:
        start = _day_start(day - datetime.timedelta(days=LOAD_DAYS - 1), tz)
        end = _day_start(day + datetime.timedelta(days=1), tz)
        if any(b.end > start and b.start < end for b in blocks):
            totals.append(_hours_in(blocks, start, end))
        day += datetime.timedelta(days=1)
    recent = _hours_in(blocks, recent_start, recent_end)
    state = probes.deviates(recent, totals, probes.HIGHER)
    if state is None:
        return {"state": None, "detail": f"insufficient data: {len(totals)} baseline 3-day windows with work blocks (need 2 with varying totals)"}
    return {"state": state, "detail": f"last {LOAD_DAYS} days {recent:.1f} h vs {len(totals)} baseline windows"}


def session_dict(session):
    """Plain dict of the scored metrics, floats or None, for twin_metrics.probes."""
    return {
        name: None if getattr(session, name) is None else float(getattr(session, name))
        for name, _ in probes.METRICS[session.kind]
    }


def kind_report(contributor, kind):
    """Evaluate one scored kind end to end; returns probes.evaluate_kind's dict plus context."""
    sessions = current_sessions(contributor, kind)
    window = baseline_window(contributor, kind, sessions)
    latest = sessions[-1] if sessions else None
    sleep = sleep_falling(contributor, window, latest)
    work = work_rising(contributor, window, latest)
    result = probes.evaluate_kind(
        kind,
        [session_dict(s) for s in window["baseline"]],
        [session_dict(s) for s in window["after"]],
        sleep_falling=sleep["state"],
        work_rising=work["state"],
        baseline_problem=window["problem"],
    )
    result.update(
        baseline_source=window["source"],
        baseline_start=window["start"],
        baseline_end=window["end"],
        sleep=sleep,
        work=work,
    )
    return result
