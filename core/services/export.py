# SPDX-License-Identifier: AGPL-3.0-or-later
"""'My data' export and import (M4-T6): JSON Lines, the first draft of the Nymbus interchange format.

Since M5 the ledger (grants, revocations, access events) is exported as ordinary record lines
of kinds grant, revocation and access_event; import checks the access-event hash chain.

Line 1:  {"type": "export", "format": "nymbus-jsonl", "version": 1, "contributor": ..., "timezone": ...,
          "exported_at": ...}
Records: {"type": "record", "kind": <record kind>, "cid": ..., "contributor": <handle>,
          "fields": <canonical content>, "created_at": ...}
Events:  {"type": "supersession", "old_cid": ..., "new_cid": ..., "reason": ..., "created_at": ...}

`fields` is exactly the content the CID is computed over (nymbus.provenance.normalize_fields),
so any stack can recompute and check each CID from its line. Lines are in the order they
were created; replaying them in that order rebuilds the same records and history.
"""
import datetime
import json

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from nymbus.provenance import canonical_bytes, compute_cid, normalize_fields

from ledger.models import AccessEvent, Grant, Revocation
from nymbus import ledger

from ..models import (Contributor, DailySnapshot, DiscomfortCheck, ProbeSession, ProvenancedRecord, Reset,
                      Supersession, TrainingSession, TrainingSet, WeeklyCheck, WorkBlock)

FORMAT, VERSION = "nymbus-jsonl", 1
RECORD_MODELS = [DailySnapshot, ProbeSession, WorkBlock, DiscomfortCheck, Reset, WeeklyCheck, TrainingSession,
                 TrainingSet]  # the owner's data
LEDGER_MODELS = [Grant, Revocation, AccessEvent]  # who may read it, and every read (M5)
EXPORT_MODELS = RECORD_MODELS + LEDGER_MODELS
BY_KIND = {m.record_kind: m for m in EXPORT_MODELS}


class ImportError_(Exception):
    """A line that cannot be imported; the whole file is rolled back."""


def _iso(dt):
    return dt.astimezone(datetime.timezone.utc).isoformat()


def export_lines(contributor, now=None):
    """Yield the export as JSON strings (one per line, no newline)."""
    yield json.dumps({"type": "export", "format": FORMAT, "version": VERSION, "contributor": contributor.handle,
                      "timezone": contributor.timezone, "exported_at": _iso(now or timezone.now())}, sort_keys=True)
    events = []
    for model in EXPORT_MODELS:
        for r in model.objects.filter(contributor=contributor):
            events.append((r.created_at, 0, r.pk, model.record_kind, r))
    for s in Supersession.objects.filter(contributor=contributor):
        events.append((s.created_at, 1, s.pk, "", s))
    events.sort(key=lambda e: e[:4])
    for _, _, _, kind, obj in events:
        if isinstance(obj, ProvenancedRecord):
            yield json.dumps({"type": "record", "kind": kind, "cid": obj.cid, "contributor": contributor.handle,
                              "fields": normalize_fields(obj.domain_fields()), "created_at": _iso(obj.created_at)},
                             sort_keys=True, ensure_ascii=False)
        else:
            yield json.dumps({"type": "supersession", "old_cid": obj.old_cid, "new_cid": obj.new_cid,
                              "reason": obj.reason, "created_at": _iso(obj.created_at)}, sort_keys=True)


def verify_line(item):
    """True when the record line's CID matches its own content."""
    return compute_cid(canonical_bytes(item["kind"], item["contributor"], item["fields"])) == item["cid"]


def import_lines(lines):
    """Rebuild an export into a database with no records for its contributor.

    Returns {"records": n, "supersessions": n, "contributor": handle}. Every CID is
    checked twice: against the line's own content, and against the CID the stored
    record gets. Any problem rolls back the whole file.
    """
    items = []
    for number, line in enumerate(lines, start=1):
        if line.strip():
            try:
                items.append((number, json.loads(line)))
            except json.JSONDecodeError as exc:
                raise ImportError_(f"line {number}: not JSON ({exc.msg})")
    header = items[0][1] if items else None
    if not isinstance(header, dict) or header.get("type") != "export" or header.get("format") != FORMAT:
        raise ImportError_("line 1: not a nymbus-jsonl export header")
    if header.get("version") != VERSION:
        raise ImportError_(f"line 1: unsupported version {header.get('version')!r}")
    _check_header(header)
    for number, item in items[1:]:
        _check_line(number, item)
    replaces = {i["new_cid"]: i["old_cid"] for _, i in items if i["type"] == "supersession"}
    counts = {"records": 0, "supersessions": 0, "contributor": header["contributor"]}
    with transaction.atomic():
        contributor, created = Contributor.objects.get_or_create(handle=header["contributor"],
                                                                 defaults={"timezone": header["timezone"]})
        if any(m.objects.filter(contributor=contributor).exists() for m in EXPORT_MODELS):
            raise ImportError_(f"contributor {contributor.handle} already has records; import into a fresh database")
        if contributor.timezone != header["timezone"]:
            # No records yet, so local days and weeks are defined by the export's time zone.
            contributor.timezone = header["timezone"]
            try:
                contributor.full_clean()
            except ValidationError:
                raise ImportError_(f"line 1: unknown time zone {header['timezone']!r}")
            contributor.save()
        imported = {}  # cid -> record, to validate correction lines
        for number, item in items[1:]:
            try:
                if item["type"] == "record":
                    record = _import_record(number, item, contributor, replaces)
                    imported[record.cid] = record
                    counts["records"] += 1
                else:
                    old, new = imported.get(item["old_cid"]), imported.get(item["new_cid"])
                    if old is None or new is None:
                        raise ImportError_(f"line {number}: correction refers to a record that is not in the file "
                                           "before it")
                    Supersession.record(old, new, reason=item["reason"])  # same kind, contributor, not self
                    counts["supersessions"] += 1
            except ImportError_:
                raise
            except ValidationError as exc:
                raise ImportError_(f"line {number}: {' '.join(exc.messages)}")
            except Exception as exc:  # database constraint or conversion problem: still a line-numbered error
                raise ImportError_(f"line {number}: {type(exc).__name__}: {exc}")
        # Each access event was checked against the one before it as it was replayed; check the whole
        # chain once more as stored.
        events = AccessEvent.objects.filter(contributor=contributor).order_by("seq")
        problems = ledger.check_chain([{"seq": e.seq, "prev_hash": e.prev_hash, "canonical": e.canonical()}
                                       for e in events])
        if problems:
            raise ImportError_("ledger hash chain is broken: " + "; ".join(problems))
    return counts


_HEADER = {"type": str, "format": str, "version": int, "contributor": str, "timezone": str, "exported_at": str}
_RECORD = {"type": str, "kind": str, "cid": str, "contributor": str, "fields": dict, "created_at": str}
_SUPERSESSION = {"type": str, "old_cid": str, "new_cid": str, "reason": str, "created_at": str}


def _check_shape(number, item, shape):
    if not isinstance(item, dict):
        raise ImportError_(f"line {number}: not a JSON object")
    for key, kind in shape.items():
        if not isinstance(item.get(key), kind) or isinstance(item.get(key), bool) != (kind is bool):
            raise ImportError_(f"line {number}: '{key}' must be a {kind.__name__}")
    extra = set(item) - set(shape)
    if extra:
        raise ImportError_(f"line {number}: unexpected keys {', '.join(sorted(extra))}")


def _check_header(header):
    _check_shape(1, header, _HEADER)


def _check_line(number, item):
    kind = item.get("type") if isinstance(item, dict) else None
    if kind == "record":
        _check_shape(number, item, _RECORD)
        if item["kind"] not in BY_KIND:
            raise ImportError_(f"line {number}: unknown record kind {item['kind']!r}")
    elif kind == "supersession":
        _check_shape(number, item, _SUPERSESSION)
        if item["old_cid"] == item["new_cid"]:
            raise ImportError_(f"line {number}: a record cannot supersede itself")
    else:
        raise ImportError_(f"line {number}: unknown line type {kind!r}")


def _import_record(number, item, contributor, replaces):
    model = BY_KIND[item["kind"]]
    if item["contributor"] != contributor.handle:
        raise ImportError_(f"line {number}: record of another contributor")
    if not verify_line(item):
        raise ImportError_(f"line {number}: CID does not match the line's content")
    record = model(contributor=contributor)
    content = {f.name: f for f in model._meta.concrete_fields if f.name not in ("id", "cid", "contributor", "created_at")}
    for name, value in item["fields"].items():
        field = content.get(name)
        if field is None:
            raise ImportError_(f"line {number}: unknown field {name!r} for {item['kind']}")
        setattr(record, field.attname, field.to_python(value))
    if item["cid"] in replaces and hasattr(record, "replaces_cid"):
        record.replaces_cid = replaces[item["cid"]]  # a correction may overlap what it replaces
    # ProvenancedRecord.save: validation and CID, without the one-per-date snapshot rule;
    # history comes from the supersession lines.
    ProvenancedRecord.save(record)
    if record.cid != item["cid"]:
        raise ImportError_(f"line {number}: stored CID {record.cid} differs from {item['cid']}")
    return record
