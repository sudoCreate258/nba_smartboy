# SPDX-License-Identifier: AGPL-3.0-or-later
"""Django side of the training report: loads current sessions and sets, calls twin_metrics.training."""
import datetime

from twin_metrics import training

from ..models import Supersession, TrainingSession, TrainingSet
from .zone_report import MAX_CHAIN, week_range


class SessionResolver:
    """Current training session for a referenced CID, following corrections (in memory)."""

    def __init__(self, contributor):
        self.current = {s.cid: s for s in TrainingSession.objects.current().filter(contributor=contributor)}
        self.next = dict(Supersession.objects.filter(contributor=contributor).order_by("id")
                         .values_list("old_cid", "new_cid"))

    def resolve(self, cid):
        for _ in range(MAX_CHAIN):
            if cid in self.current:
                return self.current[cid]
            if cid not in self.next:
                return None
            cid = self.next[cid]
        return None


def set_dict(s, session):
    return {
        "started_at": session.started_at, "is_deload": session.is_deload, "session_cid": session.cid,
        "program": session.program, "order": s.order, "exercise": s.exercise, "muscle_group": s.muscle_group,
        "load_kg": None if s.load_kg is None else float(s.load_kg), "reps": s.reps, "rir": s.rir,
        "joint_pain": s.joint_pain, "joint_pain_area": s.joint_pain_area, "cid": s.cid,
    }


def training_report(contributor, weeks=4, until=None):
    """Weekly training summary for the given local weeks. Read-only."""
    tz = contributor.tzinfo
    reported = week_range(contributor, weeks, until)
    start = datetime.datetime.combine(reported[0], datetime.time.min, tzinfo=tz)
    end = datetime.datetime.combine(reported[-1] + datetime.timedelta(days=7), datetime.time.min, tzinfo=tz)

    resolver = SessionResolver(contributor)
    sets, excluded, earlier_stops = [], [], 0
    for s in TrainingSet.objects.current().filter(contributor=contributor):
        session = resolver.resolve(s.session_cid)
        if session is None:
            excluded.append(f"set {s.order} {s.exercise} ({s.cid[:12]}): its session no longer resolves")
            continue
        if session.started_at < start:
            earlier_stops += s.is_stop_signal
            continue
        if session.started_at < end:
            sets.append(set_dict(s, session))

    weekly = training.weekly_training(sets, tz)
    return {
        "weeks": reported,
        "stop_signals": training.stop_signals(sets),
        "earlier_stop_signals": earlier_stops,
        "training": [{"week": w, "summary": weekly.get(w)} for w in reported],
        "excluded": excluded,
    }
