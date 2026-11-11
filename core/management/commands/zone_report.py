# SPDX-License-Identifier: AGPL-3.0-or-later
import datetime
import json

from django.core.management.base import BaseCommand, CommandError

from core.models import Contributor
from core.services.zone_report import zone_report

DISCLAIMER = "Load gauge, not a medical assessment."
STOP_TEXT = "stop the block; get it checked by a professional"


def _iso(value):
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    raise TypeError(f"Not JSON serializable: {type(value).__name__}")


def jsonable(report, contributor):
    tz = contributor.tzinfo

    def week_summary(summary):
        if summary is None:
            return None
        return {**summary, "stop_signals": [_stop(c) for c in summary["stop_signals"]]} if "stop_signals" in summary else summary

    def _stop(c):
        # Free-text notes are never part of report output (DECISIONS, M3 review).
        return {"at": c["at"].astimezone(tz).isoformat(), "area": c["area"], "score": c["score"],
                "trigger": c["trigger"], "cid": c["cid"], "action": STOP_TEXT}

    def by_keys(by):
        return {key: {str(k): v for k, v in groups.items()} for key, groups in by.items()}

    return {
        "contributor": contributor.handle,
        "weeks": [w.isoformat() for w in report["weeks"]],
        "stop_signals": [_stop(c) for c in report["stop_signals"]],
        "earlier_stop_signals": report["earlier_stop_signals"],
        "zone": [
            {"week": z["week"].isoformat(),
             "summary": None if z["summary"] is None else {**z["summary"], "by": by_keys(z["summary"]["by"])},
             "amber": z["amber"]}
            for z in report["zone"]
        ],
        "discomfort": [{"week": d["week"].isoformat(), "summary": week_summary(d["summary"])} for d in report["discomfort"]],
        "resets": report["resets"],
        "resets_excluded": report["resets_excluded"],
        "resets_corrected": report["resets_corrected"],
        "weekly_checks": [
            {"week_start": w.week_start.isoformat(), "instrument": w.instrument, "score": float(w.score),
             "scale_max": float(w.scale_max), "cid": w.cid}
            for w in report["weekly_checks"]
        ],
        "probes": report["probes"],
        "disclaimer": DISCLAIMER,
    }


def _pct(value):
    return "n/a" if value is None else f"{value:.0%}"


def _num(value, fmt=".1f"):
    return "n/a" if value is None else format(value, fmt)


def render_text(item):
    lines = [f"Zone report for {item['contributor']}, weeks {item['weeks'][0]} to {item['weeks'][-1]}", ""]
    if item["stop_signals"]:
        lines.append("STOP SIGNALS (sharp or numb):")
        for s in item["stop_signals"]:
            lines.append(f"  {s['at'][:16].replace('T', ' ')} {s['area']} score {s['score']} ({s['trigger']}): {STOP_TEXT}")
    else:
        lines.append("Stop signals: none")
    if item["earlier_stop_signals"]:
        lines.append(f"Earlier stop signals before these weeks: {item['earlier_stop_signals']} "
                     "(widen --weeks to see them)")
    lines.append("")
    lines.append("== Zone (high focus: absorption >= 4 and interruptions <= 1) ==")
    for z in item["zone"]:
        s = z["summary"]
        if s is None:
            lines.append(f"{z['week']}: no work blocks")
            continue
        t = s["theta"]
        theta = "n/a" if t["median"] is None else f"median {t['median']:.0f} min, IQR {t['q1']:.0f}-{t['q3']:.0f}"
        amber = {True: "AMBER", False: "none", None: "insufficient data"}[z["amber"]["state"]]
        lines.append(f"{z['week']}: {s['total_hours']:.1f} h, high focus {s['high_focus_minutes']:.0f} min, "
                     f"focus share {_pct(s['focus_share'])}, theta {theta}; zone flag: {amber} ({z['amber']['detail']})")
        for key, groups in s["by"].items():
            parts = [f"{k} {g['total_hours']:.1f} h / {_pct(g['focus_share'])}" for k, g in groups.items()]
            lines.append(f"  by {key}: " + ", ".join(parts))
    lines.append("")
    lines.append("== Discomfort ==")
    for d in item["discomfort"]:
        s = d["summary"]
        if s is None:
            lines.append(f"{d['week']}: no checks")
            continue
        means = ", ".join(f"{a} {m:.1f}" for a, m in s["mean_score"].items())
        triggers = ", ".join(f"{t} {n}" for t, n in s["high_by_trigger"].items()) or "none"
        lines.append(f"{d['week']}: {s['n']} checks; mean score {means}; score >= 3 by trigger: {triggers}; "
                     f"countermove after score >= 3: {_pct(s['countermove_share'])}")
    lines.append("")
    lines.append("== Reset effect (all resets to date; change = after - before mini-probe) ==")
    if not item["resets"]:
        lines.append("no resets logged")
    for kind, r in item["resets"].items():
        parts = []
        for metric, label, unit in (("accuracy_pct", "accuracy", ""), ("median_solve_s", "solve", " s")):
            m = r[metric]
            text = f"{label} change {_num(m['mean_change'], '+.1f')}{unit} (n={m['n']}"
            text += ")" if m["interpretable"] else ", not interpretable yet: n < 5)"
            if kind != "none" and m["vs_none"] is not None:
                text += f", vs none {m['vs_none']:+.1f}{unit}"
                if not m["vs_none_interpretable"]:
                    text += " (underpowered: needs n >= 5 on both sides)"
            parts.append(text)
        lines.append(f"{kind}: {r['resets']} resets; " + "; ".join(parts))
    if item["resets_corrected"]:
        lines.append(f"{item['resets_corrected']} reset(s) use probes that were corrected after the reset was saved.")
    for problem in item["resets_excluded"]:
        lines.append(f"Excluded: {problem}")
    lines.append("")
    lines.append("== Weekly check (shown as recorded; never combined into one score) ==")
    if not item["weekly_checks"]:
        lines.append("none in these weeks")
    for w in item["weekly_checks"]:
        lines.append(f"{w['week_start']}: {w['instrument']} {w['score']:g} / {w['scale_max']:g}")
    lines.append("")
    lines.append("== Probe flags ==")
    for p in item["probes"]:
        reason = f" ({'; '.join(p['reasons'])})" if p["reasons"] else ""
        lines.append(f"{p['kind']}: {p['flag'].upper()}{reason}")
    lines.append("")
    lines.append(DISCLAIMER)
    return "\n".join(lines)


class Command(BaseCommand):
    help = "Print the weekly zone report: stop signals, zone, discomfort, reset effect, weekly check, probe flags."

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
        item = jsonable(zone_report(who, weeks=weeks, until=until), who)
        if as_json:
            self.stdout.write(json.dumps(item, indent=2, default=_iso))
        else:
            self.stdout.write(render_text(item))
