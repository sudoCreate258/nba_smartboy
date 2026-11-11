# SPDX-License-Identifier: AGPL-3.0-or-later
"""Django side of the training report: loads current sessions and sets, calls twin_metrics.training."""
import datetime

from twin_metrics import training

from ..models import Lineage, TrainingSession, TrainingSet
from .zone_report import week_range


def current_session_for(cid, contributor):
    """The current TrainingSession a (possibly superseded) session CID resolves to, or None."""
    current = {s.cid: s for s in TrainingSession.objects.current().filter(contributor=contributor)}
    found = Lineage(contributor.pk).resolve(cid, current)
    return None if found is None else current[found]


def sets_of(session):
    """Current sets of a current session, including sets attached to its earlier versions."""
    lineage = Lineage(session.contributor_id).members(session.cid)
    return TrainingSet.objects.current().filter(session_cid__in=lineage)


def set_dict(s, session):
    return {
        "started_at": session.started_at, "is_deload": session.is_deload, "session_cid": session.cid,
        "program": session.program, "order": s.order, "exercise": s.exercise, "muscle_group": s.muscle_group,
        "load_kg": None if s.load_kg is None else float(s.load_kg), "reps": s.reps, "rir": s.rir,
        "joint_pain": s.joint_pain, "joint_pain_area": s.joint_pain_area, "cid": s.cid,
    }


def training_report(contributor, weeks=4, until=None):
    """Weekly training summary for the given local weeks. Read-only.

    Only sessions starting in the window (and the sets attached to them or to
    their earlier versions) are loaded; earlier stop signals are counted in the database.
    """
    tz = contributor.tzinfo
    reported = week_range(contributor, weeks, until)
    start = datetime.datetime.combine(reported[0], datetime.time.min, tzinfo=tz)
    end = datetime.datetime.combine(reported[-1] + datetime.timedelta(days=7), datetime.time.min, tzinfo=tz)

    lineage = Lineage(contributor.pk)
    sessions = {s.cid: s for s in TrainingSession.objects.current()
                .filter(contributor=contributor, started_at__gte=start, started_at__lt=end)}
    owner = lineage.group(sessions)  # any session CID -> current session CID in the window
    sets = [set_dict(s, sessions[owner[s.session_cid]])
            for s in TrainingSet.objects.current().filter(contributor=contributor, session_cid__in=owner)]

    earlier = TrainingSession.objects.current().filter(contributor=contributor, started_at__lt=start)
    earlier_owner = lineage.group(earlier.values_list("cid", flat=True))
    earlier_stops = TrainingSet.objects.current().filter(
        contributor=contributor, session_cid__in=earlier_owner, joint_pain__gte=training.STOP_JOINT_PAIN
    ).count()

    session_dicts = [{"cid": s.cid, "started_at": s.started_at, "is_deload": s.is_deload} for s in sessions.values()]
    weekly = training.weekly_training(sets, tz, sessions=session_dicts)
    return {
        "weeks": reported,
        "stop_signals": training.stop_signals(sets),
        "earlier_stop_signals": earlier_stops,
        "training": [{"week": w, "summary": weekly.get(w)} for w in reported],
    }
