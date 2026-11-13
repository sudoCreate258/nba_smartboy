# SPDX-License-Identifier: AGPL-3.0-or-later
"""Body map (025 Part C, R14): weekly implied muscle volume shaded on a front/back figure, with pain
flags. ESTIMATED, NOT MEASURED. Server-rendered SVG (no script, no inline style: CSP 'self')."""
import datetime
from functools import lru_cache
from html import escape
from pathlib import Path

import yaml
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from .modules import enabled_ids
from .today import contributor_for

from core.models import DiscomfortCheck, Lineage, TrainingSession, TrainingSet
from twin_metrics.muscles import flags, validate_map, weekly_volume

MAP_PATH = Path(settings.BASE_DIR) / "twin" / "muscle_map.yaml"

# (view, muscle) -> shapes in a 100 x 220 figure; each shape is drawn on the left and mirrored right.
SHAPES = {
    "front": {
        "front_delts": [("ellipse", 33, 52, 7, 6)], "side_delts": [("ellipse", 26, 56, 4, 7)],
        "chest": [("rect", 36, 52, 13, 14)], "biceps": [("rect", 24, 64, 7, 18)], "forearms": [("rect", 21, 84, 7, 22)],
        "abs": [("rect", 42, 68, 7, 30)], "quads": [("rect", 35, 110, 12, 40)], "adductors": [("rect", 44, 110, 5, 26)],
        "calves": [("rect", 37, 158, 8, 34)],
    },
    "back": {
        "rear_delts": [("ellipse", 33, 52, 7, 6)], "upper_back": [("rect", 36, 48, 13, 16)],
        "lats": [("rect", 33, 64, 12, 20)], "triceps": [("rect", 24, 64, 7, 18)], "lower_back": [("rect", 41, 84, 8, 14)],
        "glutes": [("rect", 36, 98, 13, 14)], "hamstrings": [("rect", 36, 114, 11, 38)], "calves": [("rect", 37, 158, 9, 30)],
        "forearms": [("rect", 21, 84, 7, 22)],
    },
}
# Discomfort / joint-pain areas -> (view, x, y) markers.
PAIN_SPOTS = {"neck": ("back", 50, 40), "shoulder": ("front", 28, 52), "wrist": ("front", 23, 108),
              "hip": ("front", 38, 104), "low_back": ("back", 50, 90), "other": ("front", 50, 120)}


@lru_cache(maxsize=1)
def muscle_map():
    return validate_map(yaml.safe_load(MAP_PATH.read_text(encoding="utf-8")))


def week_bounds(contributor, week_start):
    tz = contributor.tzinfo
    start = datetime.datetime.combine(week_start, datetime.time(0), tzinfo=tz)
    return start, start + datetime.timedelta(days=7)


def week_data(contributor, week_start):
    """Sets and pain flags of one local week (Monday start), from current records."""
    start, end = week_bounds(contributor, week_start)
    sessions = TrainingSession.objects.current().filter(contributor=contributor, started_at__gte=start,
                                                       started_at__lt=end)
    group = Lineage(contributor.id).group({s.cid for s in sessions})
    sets = list(TrainingSet.objects.current().filter(contributor=contributor, session_cid__in=list(group)))
    pains = [{"area": d.area, "score": d.score, "source": "discomfort check"} for d in
             DiscomfortCheck.objects.current().filter(contributor=contributor, at__gte=start, at__lt=end)]
    pains += [{"area": s.joint_pain_area, "score": s.joint_pain, "source": f"joint pain ({s.exercise})"}
              for s in sets if s.joint_pain and s.joint_pain_area]
    rows = [{"exercise": s.exercise, "reps": s.reps, "load_kg": s.load_kg, "side": s.side} for s in sets]
    return rows, pains


def svg(volume, pains):
    """Front and back figures; muscle opacity by share of the week's highest volume."""
    top = max(volume["total"].values(), default=0)
    parts = ['<svg class="body-map" viewBox="0 0 220 220" role="img" '
             'aria-label="Estimated weekly muscle volume, front and back; not measured">']
    for offset, view in ((0, "front"), (115, "back")):
        parts.append(f'<g transform="translate({offset} 0)"><text x="50" y="12" class="tick" '
                     f'text-anchor="middle">{view}</text>')
        parts.append('<circle cx="50" cy="28" r="10" class="body-outline"/>'
                     '<rect x="34" y="44" width="32" height="66" rx="8" class="body-outline"/>')
        for muscle, shapes in SHAPES[view].items():
            v = volume["total"].get(muscle, 0.0)
            opacity = 0.08 + 0.92 * (v / top) if top else 0.08
            label = escape(f"{muscle.replace('_', ' ')}: {v:,.0f} kg-reps (estimate)")
            for kind, x, y, a, b in shapes:
                for mx in (x, 100 - x - (a if kind == "rect" else 0)):
                    if kind == "rect":
                        parts.append(f'<rect x="{mx}" y="{y}" width="{a}" height="{b}" rx="2" class="muscle" '
                                     f'fill-opacity="{opacity:.2f}"><title>{label}</title></rect>')
                    else:
                        cx = mx if mx == x else 100 - x
                        parts.append(f'<ellipse cx="{cx}" cy="{y}" rx="{a}" ry="{b}" class="muscle" '
                                     f'fill-opacity="{opacity:.2f}"><title>{label}</title></ellipse>')
        for p in pains:
            spot = PAIN_SPOTS.get(p["area"], PAIN_SPOTS["other"])
            if spot[0] == view:
                parts.append(f'<circle cx="{spot[1]}" cy="{spot[2]}" r="5" class="pain"><title>'
                             f'{escape(p["area"].replace("_", " "))} {p["score"]}/10 ({escape(p["source"])})'
                             '</title></circle>')
        parts.append("</g>")
    parts.append("</svg>")
    return "".join(parts)


def build(contributor, week_start):
    mapping = muscle_map()
    rows, pains = week_data(contributor, week_start)
    volume = weekly_volume(rows, mapping)
    ranked = sorted(volume["total"].items(), key=lambda kv: -kv[1])
    return {"week_start": week_start, "volume": volume, "ranked": ranked, "flags": flags(volume, mapping),
            "pains": pains, "svg": svg(volume, pains), "sets": len(rows)}


@login_required
@require_GET
def body_page(request):
    """The body map of one local week (?week=any date in it; default this week). Training module only."""
    from .views import _context  # ui.views imports a lot; keep this module light for the plain helpers

    if "training" not in enabled_ids():
        raise Http404
    contributor = contributor_for(request.user)
    try:
        day = datetime.date.fromisoformat(request.GET.get("week", ""))
    except ValueError:
        day = timezone.now().astimezone(contributor.tzinfo).date()
    monday = day - datetime.timedelta(days=day.weekday())
    with timezone.override(contributor.tzinfo):
        return render(request, "ui/body.html", _context(
            contributor, b=build(contributor, monday), prev=monday - datetime.timedelta(days=7),
            next=monday + datetime.timedelta(days=7)))
