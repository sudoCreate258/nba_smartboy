# SPDX-License-Identifier: AGPL-3.0-or-later
import datetime
import json

from django.core.management.base import BaseCommand, CommandError

from core.models import Contributor
from core.services.common import DISCLAIMER, STOP_TEXT, iso_default
from core.services.training_report import training_report


def jsonable(report, contributor):
    tz = contributor.tzinfo

    def stop(s):
        return {"at": s["started_at"].astimezone(tz).isoformat(), "exercise": s["exercise"], "order": s["order"],
                "joint_pain": s["joint_pain"], "joint_pain_area": s["joint_pain_area"], "cid": s["cid"],
                "action": STOP_TEXT}

    def summary(w):
        return None if w is None else {**w, "stop_signals": [stop(s) for s in w["stop_signals"]]}

    return {
        "contributor": contributor.handle,
        "weeks": [w.isoformat() for w in report["weeks"]],
        "stop_signals": [stop(s) for s in report["stop_signals"]],
        "earlier_stop_signals": report["earlier_stop_signals"],
        "training": [{"week": t["week"].isoformat(), "summary": summary(t["summary"])} for t in report["training"]],
        "disclaimer": DISCLAIMER,
    }


def render_text(item):
    lines = [f"Training report for {item['contributor']}, weeks {item['weeks'][0]} to {item['weeks'][-1]}", ""]
    if item["stop_signals"]:
        lines.append("STOP SIGNALS (joint pain 2 or more):")
        for s in item["stop_signals"]:
            area = s["joint_pain_area"] or "area not given"
            lines.append(f"  {s['at'][:16].replace('T', ' ')} set {s['order']} {s['exercise']}: joint pain "
                         f"{s['joint_pain']} ({area}): {STOP_TEXT}")
    else:
        lines.append("Stop signals: none")
    if item["earlier_stop_signals"]:
        lines.append(f"Earlier stop signals before these weeks: {item['earlier_stop_signals']} "
                     "(widen --weeks to see them)")
    lines.append("")
    lines.append("== Training (hard set: RIR 3 or less, or RIR not recorded) ==")
    for t in item["training"]:
        w = t["summary"]
        if w is None:
            lines.append(f"{t['week']}: no sets")
            continue
        deload = " DELOAD" if w["deload"] else ""
        hard = ", ".join(f"{m} {n}" for m, n in w["hard_sets_by_muscle"].items()) or "none"
        rir = "n/a" if w["mean_rir"] is None else f"{w['mean_rir']:.1f} (n={w['rir_n']})"
        pain = ", ".join(f"{a} {n}" for a, n in w["joint_pain_by_area"].items()) or "none"
        lines.append(f"{t['week']}{deload}: {w['sessions']} sessions, {w['sets']} sets, "
                     f"tonnage {w['tonnage_kg']:.0f} kg, mean RIR {rir}")
        lines.append(f"  hard sets: {hard}")
        lines.append(f"  joint-pain sets by area: {pain}")
    lines.append("")
    lines.append(DISCLAIMER)
    return "\n".join(lines)


class Command(BaseCommand):
    help = "Print the weekly training report: stop signals, hard sets per muscle, tonnage, RIR, deloads, joint pain."

    def add_arguments(self, parser):
        parser.add_argument("--contributor", default="mike")
        parser.add_argument("--weeks", type=int, default=4, help="number of local weeks to show (default 4)")
        parser.add_argument("--until", type=datetime.date.fromisoformat, default=None,
                            help="YYYY-MM-DD: the last reported week is the local week containing this date "
                                 "(whole week, Monday-Sunday; default: today)")
        parser.add_argument("--json", action="store_true", dest="as_json", help="print JSON instead of text")

    def handle(self, *args, contributor, weeks, until, as_json, **options):
        if weeks < 1:
            raise CommandError("--weeks must be at least 1")
        try:
            who = Contributor.objects.get(handle=contributor)
        except Contributor.DoesNotExist:
            raise CommandError(f"Unknown contributor: {contributor}")
        item = jsonable(training_report(who, weeks=weeks, until=until), who)
        if as_json:
            self.stdout.write(json.dumps(item, indent=2, default=iso_default))
        else:
            self.stdout.write(render_text(item))
