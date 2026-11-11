# SPDX-License-Identifier: AGPL-3.0-or-later
"""Django side of the probe report: picks sessions and baseline windows."""
from ..models import ProbeBaseline, ProbeSession

DEFAULT_BASELINE_N = 10
SCORED_KINDS = (ProbeSession.Kind.PUZZLE_SET, ProbeSession.Kind.RAPID_GAME)


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
    Otherwise the baseline is the first DEFAULT_BASELINE_N sessions.
    Returns {"source", "start", "end", "baseline", "after"}; start/end are None
    when there are no baseline sessions in a default window.
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
        }
    baseline, after = sessions[:DEFAULT_BASELINE_N], sessions[DEFAULT_BASELINE_N:]
    return {
        "source": "default",
        "start": baseline[0].started_at if baseline else None,
        "end": baseline[-1].started_at if baseline else None,
        "baseline": baseline,
        "after": after,
    }
