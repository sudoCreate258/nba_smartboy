"""Canonical bytes and CIDv1 for Nymbus records. Plain Python, no Django imports."""
import base64
import datetime
import hashlib
import json
from decimal import Decimal

_CID_PREFIX = bytes([0x01, 0x55, 0x12, 0x20])  # CIDv1, raw codec, sha2-256, 32 bytes


def _normalize(value):
    if isinstance(value, datetime.datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Naive datetimes are never hashed; attach a time zone first.")
        return value.astimezone(datetime.timezone.utc).isoformat()
    if isinstance(value, (datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def normalize_fields(fields):
    """The JSON-ready form of a record's content fields, exactly as they are hashed
    (datetimes as UTC ISO strings, dates/times ISO, decimals as strings)."""
    return {k: _normalize(v) for k, v in fields.items()}


def canonical_bytes(kind, contributor, fields):
    """Deterministic JSON bytes: sorted keys, compact separators, UTF-8."""
    payload = {
        "kind": kind,
        "contributor": contributor,
        "fields": normalize_fields(fields),
    }
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def compute_cid(data):
    """CIDv1 string: 'b' + lowercase base32 (no padding) of version+codec+multihash."""
    raw = _CID_PREFIX + hashlib.sha256(data).digest()
    return "b" + base64.b32encode(raw).decode("ascii").lower().rstrip("=")
