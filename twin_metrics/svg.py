# SPDX-License-Identifier: AGPL-3.0-or-later
"""Server-rendered SVG charts (M4). Plain Python, no Django, no JavaScript, no external assets.

A series is a list of (label, value) with value None for "no data"; missing
values break the line (they are never filled in). Every chart carries a <title>
and a <desc> listing its values, so screen readers get the numbers.
"""
from html import escape

W, H = 320, 150
PAD_L, PAD_R, PAD_T, PAD_B = 36, 8, 10, 22


def _fmt(v):
    return "no data" if v is None else (f"{v:.0f}" if abs(v) >= 100 or float(v).is_integer() else f"{v:.1f}")


def _scale(values, band=None):
    pool = [v for v in values if v is not None] + (list(band) if band else [])
    if not pool:
        return 0.0, 1.0
    lo, hi = min(pool), max(pool)
    if lo == hi:
        lo, hi = lo - 1, hi + 1
    pad = (hi - lo) * 0.08
    return lo - pad, hi + pad


def _frame(title, desc, body, lo, hi, labels):
    w_in, h_in = W - PAD_L - PAD_R, H - PAD_T - PAD_B
    ticks = []
    for v in (lo, (lo + hi) / 2, hi):
        y = PAD_T + h_in * (1 - (v - lo) / (hi - lo))
        ticks.append(f'<line x1="{PAD_L}" x2="{W - PAD_R}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>'
                     f'<text x="{PAD_L - 4}" y="{y + 4:.1f}" class="tick" text-anchor="end">{escape(_fmt(v))}</text>')
    xl = ""
    if labels:
        xl = (f'<text x="{PAD_L}" y="{H - 6}" class="tick">{escape(labels[0])}</text>'
              f'<text x="{W - PAD_R}" y="{H - 6}" class="tick" text-anchor="end">{escape(labels[-1])}</text>')
    # Inline SVG in HTML needs no xmlns, so pages carry no URL at all.
    return (f'<svg viewBox="0 0 {W} {H}" role="img" class="chart" '
            f'aria-label="{escape(title)}"><title>{escape(title)}</title><desc>{escape(desc)}</desc>'
            f'{"".join(ticks)}{body}{xl}</svg>')


def _desc(points, unit):
    u = f" {unit}" if unit else ""
    return "; ".join(f"{label}: {_fmt(v)}{u if v is not None else ''}" for label, v in points) or "no data"


def line_chart(title, points, unit="", band=None):
    """Line through the points; None breaks the line. band=(low, high) shades a reference range."""
    values = [v for _, v in points]
    lo, hi = _scale(values, band)
    w_in, h_in = W - PAD_L - PAD_R, H - PAD_T - PAD_B
    n = len(points)

    def xy(i, v):
        x = PAD_L + (w_in * (i / (n - 1)) if n > 1 else w_in / 2)
        return x, PAD_T + h_in * (1 - (v - lo) / (hi - lo))

    body = []
    if band:
        y_hi, y_lo = xy(0, band[1])[1], xy(0, band[0])[1]
        body.append(f'<rect x="{PAD_L}" y="{y_hi:.1f}" width="{w_in}" height="{max(y_lo - y_hi, 0):.1f}" class="band"/>')
    run = []
    for i, v in enumerate(values + [None]):
        if v is None:
            if len(run) > 1:
                body.append('<polyline class="line" points="' + " ".join(f"{x:.1f},{y:.1f}" for x, y in run) + '"/>')
            run = []
        else:
            run.append(xy(i, v))
    for i, v in enumerate(values):
        if v is not None:
            x, y = xy(i, v)
            body.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.5" class="dot"/>')
    desc = _desc(points, unit)
    if band:
        desc += f". Reference range {_fmt(band[0])} to {_fmt(band[1])}"
    return _frame(title, desc, "".join(body), lo, hi, [label for label, _ in points])


def bar_chart(title, points, unit=""):
    """One bar per point; None draws no bar."""
    values = [v for _, v in points]
    lo, hi = _scale([0.0] + values)
    lo = min(lo, 0.0)
    w_in, h_in = W - PAD_L - PAD_R, H - PAD_T - PAD_B
    n = max(len(points), 1)
    slot = w_in / n
    y0 = PAD_T + h_in * (1 - (0 - lo) / (hi - lo))
    body = []
    for i, v in enumerate(values):
        if v is None:
            continue
        y = PAD_T + h_in * (1 - (v - lo) / (hi - lo))
        body.append(f'<rect x="{PAD_L + i * slot + slot * 0.15:.1f}" y="{min(y, y0):.1f}" width="{slot * 0.7:.1f}" '
                    f'height="{abs(y0 - y):.1f}" class="bar"/>')
    return _frame(title, _desc(points, unit), "".join(body), lo, hi, [label for label, _ in points])
