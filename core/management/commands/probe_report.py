# SPDX-License-Identifier: AGPL-3.0-or-later
import json

from django.core.management.base import BaseCommand, CommandError

from core.models import Contributor
from core.services.probe_report import SCORED_KINDS, kind_report

DISCLAIMER = "Load gauge, not a medical assessment."


def jsonable(report, contributor):
    """Plain dict for one kind; datetimes become ISO strings, stats tuples become mappings."""
    tz = contributor.tzinfo

    def day(value):
        return None if value is None else value.astimezone(tz).date().isoformat()

    return {
        "kind": report["kind"],
        "status": report["status"],
        "baseline": {
            "source": report["baseline_source"],
            "start": day(report["baseline_start"]),
            "end": day(report["baseline_end"]),
            "n": report["n_baseline"],
            "stats": {
                name: {"mean": mean, "sd": sd, "n": n} for name, (mean, sd, n) in report["stats"].items()
            },
        },
        "scored_sessions": report["n_scored"],
        "skipped_metrics": report["skipped"],
        "latest_rolling_medians": report["medians"],
        "latest_z": report["z"],
        "flag": report["level"],
        "reasons": report["reasons"],
        "sleep": report["sleep"],
        "work": report["work"],
    }


def _state(condition, true_text, false_text):
    text = {True: true_text, False: false_text, None: "insufficient data"}[condition["state"]]
    return f"{text} ({condition['detail']})"


def render_text(item):
    lines = [f"== {item['kind']} =="]
    base = item["baseline"]
    if item["status"] == "insufficient_baseline" and base["n"] < 10:
        lines.append(f"Baseline: insufficient baseline ({base['n']} of 10 sessions); no flags raised.")
    elif item["status"] == "insufficient_baseline":
        lines.append(f"Baseline: {'; '.join(item['reasons'])}; no flags raised.")
    else:
        lines.append(f"Baseline ({base['source']}): {base['start']} to {base['end']}, n={base['n']}")
        for name, s in base["stats"].items():
            if name in item["skipped_metrics"]:
                continue
            lines.append(f"  {name}: mean {s['mean']:.2f}, sd {s['sd']:.2f}, n={s['n']}")
        if item["skipped_metrics"]:
            lines.append("Skipped metrics: " + "; ".join(f"{k} ({v})" for k, v in item["skipped_metrics"].items()))
        if item["latest_rolling_medians"]:
            lines.append(f"Latest rolling medians (z, positive = worse), {item['scored_sessions']} scored sessions:")
            for name, median in item["latest_rolling_medians"].items():
                z = item["latest_z"].get(name)
                lines.append(f"  {name}: {median:.2f}" + (f" (z {z:+.2f})" if z is not None else " (not scored)"))
        else:
            lines.append("Latest rolling medians: none yet (no sessions after the baseline).")
    flag = item["flag"].upper()
    lines.append(f"Flag: {flag}" + (": " + "; ".join(item["reasons"]) if item["reasons"] else ""))
    lines.append("Sleep: " + _state(item["sleep"], "falling", "not falling"))
    lines.append("Work load: " + _state(item["work"], "rising", "not rising"))
    return "\n".join(lines)


class Command(BaseCommand):
    help = "Print the probe-session load gauge: baseline, rolling z-scores, flags, sleep and work context."

    def add_arguments(self, parser):
        parser.add_argument("--contributor", default="mike")
        parser.add_argument("--kind", choices=[str(k) for k in SCORED_KINDS], help="one probe kind (default: all scored kinds)")
        parser.add_argument("--json", action="store_true", dest="as_json", help="print JSON instead of text")

    def handle(self, *args, contributor, kind, as_json, **options):
        try:
            who = Contributor.objects.get(handle=contributor)
        except Contributor.DoesNotExist:
            raise CommandError(f"Unknown contributor: {contributor}")
        kinds = [kind] if kind else [str(k) for k in SCORED_KINDS]
        items = [jsonable(kind_report(who, k), who) for k in kinds]
        if as_json:
            self.stdout.write(json.dumps({"contributor": who.handle, "kinds": items, "disclaimer": DISCLAIMER}, indent=2))
            return
        self.stdout.write(f"Probe report for {who.handle}")
        for item in items:
            self.stdout.write("")
            self.stdout.write(render_text(item))
        self.stdout.write("")
        self.stdout.write(DISCLAIMER)
