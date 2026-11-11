# SPDX-License-Identifier: AGPL-3.0-or-later
"""Training statistics (M3.5): hard sets, tonnage, RIR, deloads, joint pain.

Plain Python, no Django imports. A set is a dict with the session's
`started_at` (aware) and `is_deload`, plus muscle_group, load_kg, reps, rir,
joint_pain and joint_pain_area. Weeks are local ISO weeks (Monday start) of
the session start. This is a load gauge, not a medical assessment.
"""
import statistics

from .zone import UNKNOWN, week_of

HARD_MAX_RIR = 3  # a set with rir <= 3, or with rir missing, counts as hard
STOP_JOINT_PAIN = 2


def is_hard(s):
    return s.get("rir") is None or s["rir"] <= HARD_MAX_RIR


def is_stop_signal(s):
    return s.get("joint_pain") is not None and s["joint_pain"] >= STOP_JOINT_PAIN


def tonnage(s):
    """load x reps; a set without load (bodyweight) adds 0."""
    return 0.0 if s.get("load_kg") is None else s["load_kg"] * s["reps"]


def stop_signals(sets):
    """Sets with joint_pain >= 2, oldest first."""
    return sorted((s for s in sets if is_stop_signal(s)), key=lambda s: (s["started_at"], s.get("order", 0)))


def weekly_training(sets, tz):
    """{week Monday: summary} for weeks with sets, oldest first.

    summary: sessions (distinct session_cid), sets, hard_sets_by_muscle,
    tonnage_kg, mean_rir (None when no set recorded rir), rir_n, deload (any
    session that week is a deload), joint_pain_by_area (sets with joint_pain
    >= 1; area "unknown" when not given), stop_signals.
    """
    weeks = {}
    for s in sets:
        weeks.setdefault(week_of(s["started_at"], tz), []).append(s)
    out = {}
    for week in sorted(weeks):
        items = weeks[week]
        hard = {}
        for s in items:
            if is_hard(s):
                hard[s["muscle_group"]] = hard.get(s["muscle_group"], 0) + 1
        rirs = [s["rir"] for s in items if s.get("rir") is not None]
        pain = {}
        for s in items:
            if s.get("joint_pain"):
                area = s.get("joint_pain_area") or UNKNOWN
                pain[area] = pain.get(area, 0) + 1
        out[week] = {
            "sessions": len({s.get("session_cid") for s in items}),
            "sets": len(items),
            "hard_sets_by_muscle": dict(sorted(hard.items())),
            "tonnage_kg": sum(tonnage(s) for s in items),
            "mean_rir": statistics.fmean(rirs) if rirs else None,
            "rir_n": len(rirs),
            "deload": any(s.get("is_deload") for s in items),
            "joint_pain_by_area": dict(sorted(pain.items())),
            "stop_signals": stop_signals(items),
        }
    return out
