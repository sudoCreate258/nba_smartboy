# SPDX-License-Identifier: AGPL-3.0-or-later
"""Implied muscle volume from logged sets (025 Part C, R13). Plain Python, no Django imports.

AN ESTIMATE, NOT A MEASUREMENT: volume per muscle = sets x reps x load x weight, with the weights from
twin/muscle_map.yaml (rough until the owner adds EMG sources). A set without a load (body weight) adds
nothing and is counted under `no_load`.
"""
from collections import defaultdict

SIDES = ("L", "R")


def validate_map(data):
    """Raise ValueError unless the map has the expected shape (muscles, flags, exercises, weights 0-1)."""
    muscles = set(data.get("muscles") or [])
    if not muscles:
        raise ValueError("muscle map: 'muscles' must list the muscles")
    lo, hi = data["flags"]["lr_ratio_band"]
    if not 0 < lo <= hi:
        raise ValueError("muscle map: lr_ratio_band must be 0 < low <= high")
    for pair in data["flags"]["pairs"]:
        a, b = pair["muscles"]
        if a not in muscles or b not in muscles or not 0 < pair["band"][0] <= pair["band"][1]:
            raise ValueError(f"muscle map: bad pair {pair}")
    for name, row in data["exercises"].items():
        if "source" not in row:
            raise ValueError(f"muscle map: {name} needs a source field")
        for part in ("primary", "secondary"):
            for muscle, w in (row.get(part) or {}).items():
                if muscle not in muscles or not 0 <= w <= 1:
                    raise ValueError(f"muscle map: {name}: {muscle} {w}")
    return data


def weights(row):
    out = dict(row.get("secondary") or {})
    out.update(row.get("primary") or {})
    return out


def weekly_volume(sets, mapping):
    """sets: dicts with exercise, reps, load_kg (number or None), side (L, R, bilateral or None), sets (default 1).

    Returns {"total": {muscle: volume}, "side": {muscle: {"L": v, "R": v}}, "unmapped": {exercise: n},
    "no_load": n}. One-sided volume is also part of the total.
    """
    total, side = defaultdict(float), defaultdict(lambda: {"L": 0.0, "R": 0.0})
    unmapped, no_load = defaultdict(int), 0
    for s in sets:
        row = mapping["exercises"].get(s["exercise"])
        if row is None:
            unmapped[s["exercise"]] += 1
            continue
        if s.get("load_kg") is None:
            no_load += 1
            continue
        base = s.get("sets", 1) * s["reps"] * float(s["load_kg"])
        for muscle, w in weights(row).items():
            total[muscle] += base * w
            if s.get("side") in SIDES:
                side[muscle][s["side"]] += base * w
    return {"total": dict(total), "side": {m: dict(v) for m, v in side.items()}, "unmapped": dict(unmapped),
            "no_load": no_load}


def flags(volume, mapping):
    """Imbalance flags: [{"kind": "left_right"|"pair", "muscles", "ratio", "band"}]. ratio None = one side
    (or one muscle of the pair) has no volume at all."""
    out = []
    lo, hi = mapping["flags"]["lr_ratio_band"]
    for muscle, v in sorted(volume["side"].items()):
        left, right = v["L"], v["R"]
        if not (left or right):
            continue
        ratio = left / right if right else None
        if ratio is None or not lo <= ratio <= hi:
            out.append({"kind": "left_right", "muscles": [muscle], "ratio": ratio, "band": [lo, hi]})
    for pair in mapping["flags"]["pairs"]:
        a, b = pair["muscles"]
        va, vb = volume["total"].get(a, 0.0), volume["total"].get(b, 0.0)
        if not (va or vb):
            continue
        ratio = va / vb if vb else None
        plo, phi = pair["band"]
        if ratio is None or not plo <= ratio <= phi:
            out.append({"kind": "pair", "muscles": [a, b], "ratio": ratio, "band": [plo, phi]})
    return out
