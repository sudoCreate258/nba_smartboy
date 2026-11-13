# SPDX-License-Identifier: AGPL-3.0-or-later
"""Strict shape checks for dtom data (027): nymbus.twin_capture.v1 and nymbus.twin_minute.v1.
Plain Python, no Django imports.

Rules: the listed fields must have the listed JSON types; a number may be null when dtom could not
measure it (stored as null, never 0); a boolean is not a number; unknown fields are allowed and kept
as given. Every function raises DtomError naming the path of the first bad value.
"""
import datetime

CAPTURE_SCHEMA = "nymbus.twin_capture.v1"
MINUTE_SCHEMA = "nymbus.twin_minute.v1"
REGIONS = ("neck", "back", "shL", "shR")
EVENT_TYPES = ("focus", "coach_flag", "coach_fixed", "posture_sample")


class DtomError(ValueError):
    pass


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _num(v, path, null=True, lo=None, hi=None):
    if v is None and null:
        return
    if not _is_num(v):
        raise DtomError(f"{path}: must be a number{' or null' if null else ''}")
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        raise DtomError(f"{path}: must be between {lo} and {hi}")


def _type(v, kind, path, null=False):
    if v is None and null:
        return
    if not isinstance(v, kind) or isinstance(v, bool) and kind is not bool:
        names = kind.__name__ if isinstance(kind, type) else "/".join(k.__name__ for k in kind)
        raise DtomError(f"{path}: must be {names}{' or null' if null else ''}")


def parse_time(v, path):
    """An ISO 8601 date-time WITH a time zone (naive times are never guessed)."""
    _type(v, str, path)
    try:
        t = datetime.datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        raise DtomError(f"{path}: not an ISO 8601 date-time")
    if t.tzinfo is None or t.utcoffset() is None:
        raise DtomError(f"{path}: must include a time zone")
    return t


def _numbers(d, path, keys=None, null=True, lo=None, hi=None):
    """A dict of numbers (or nulls). keys: required keys, others allowed."""
    _type(d, dict, path)
    for k in keys or ():
        if k not in d:
            raise DtomError(f"{path}.{k}: missing")
    for k, v in d.items():
        _num(v, f"{path}.{k}", null=null, lo=lo, hi=hi)


def check_sample(s, path):
    _type(s, dict, path)
    _type(s.get("label"), str, f"{path}.label")
    parse_time(s.get("at"), f"{path}.at")
    _num(s.get("frames"), f"{path}.frames", lo=0)
    for key in ("angles", "measures", "load_pct", "load_nm"):
        if s.get(key) is not None:
            _numbers(s[key], f"{path}.{key}")
    _type(s.get("look"), str, f"{path}.look", null=True)
    _num(s.get("head_pitch"), f"{path}.head_pitch")
    _type(s.get("side_view"), bool, f"{path}.side_view", null=True)


def check_capture(doc):
    """Validate a nymbus.twin_capture.v1 export; returns its exported_at as an aware datetime."""
    _type(doc, dict, "capture")
    if doc.get("schema") != CAPTURE_SCHEMA:
        raise DtomError(f"schema: must be {CAPTURE_SCHEMA!r}")
    exported = parse_time(doc.get("exported_at"), "exported_at")
    if "cameras" in doc:
        _type(doc["cameras"], list, "cameras")
    if doc.get("body_model") is not None:
        bm = doc["body_model"]
        _type(bm, dict, "body_model")
        for key in ("bone_lengths_m", "range_of_motion_deg"):
            if bm.get(key) is not None:
                _type(bm[key], dict, f"body_model.{key}")
                for name, v in bm[key].items():
                    if isinstance(v, dict):  # e.g. a joint with several planes
                        _numbers(v, f"body_model.{key}.{name}")
                    else:
                        _num(v, f"body_model.{key}.{name}")
    if doc.get("posture_seconds") is not None:
        _numbers(doc["posture_seconds"], "posture_seconds", lo=0)
    _type(doc.get("posture_samples_v0"), list, "posture_samples_v0")
    for i, s in enumerate(doc["posture_samples_v0"]):
        check_sample(s, f"posture_samples_v0[{i}]")
    for key in ("coach_log", "face_log"):
        if key in doc:
            _type(doc[key], list, key)
    return exported


def check_minute(doc):
    """Validate a nymbus.twin_minute.v1 document; returns (t_start, t_end) as aware datetimes."""
    _type(doc, dict, "minute")
    if doc.get("schema") != MINUTE_SCHEMA:
        raise DtomError(f"schema: must be {MINUTE_SCHEMA!r}")
    start, end = parse_time(doc.get("t_start"), "t_start"), parse_time(doc.get("t_end"), "t_end")
    if end <= start:
        raise DtomError("t_end: must be after t_start")
    for key in ("source", "version"):
        _type(doc.get(key), str, key)
    _type(doc.get("cameras"), list, "cameras")
    _num(doc.get("side_view_pct"), "side_view_pct", lo=0, hi=100)
    _numbers(doc.get("posture"), "posture", keys=("sitting_s", "standing_s"), lo=0)
    for key in ("load_pct_avg", "load_pct_max", "fatigue_max"):
        _numbers(doc.get(key), key, keys=REGIONS)
    _num(doc.get("same_position_max_min"), "same_position_max_min", lo=0)
    face = doc.get("face")
    _type(face, dict, "face")
    for key in ("blinks_per_min", "yawns", "brow_tension", "head_pitch_avg"):
        _num(face.get(key), f"face.{key}")
    _numbers(face.get("looking_pct"), "face.looking_pct", keys=("screen", "down", "away"), lo=0, hi=100)
    _numbers(doc.get("using_s"), "using_s", keys=("laptop", "phone"), lo=0)
    _type(doc.get("events"), list, "events")
    for i, e in enumerate(doc["events"]):
        _type(e, dict, f"events[{i}]")
        parse_time(e.get("t"), f"events[{i}].t")
        if e.get("type") not in EVENT_TYPES:
            raise DtomError(f"events[{i}].type: must be one of {', '.join(EVENT_TYPES)}")
        if e.get("region") not in REGIONS + (None,):
            raise DtomError(f"events[{i}].region: must be one of {', '.join(REGIONS)} or null")
    return start, end
