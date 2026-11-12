# SPDX-License-Identifier: AGPL-3.0-or-later
"""'My data' export and import (M4-T6): JSON Lines, the first draft of the Nymbus interchange format.

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

from django.db import transaction
from django.utils import timezone

from nymbus.provenance import canonical_bytes, compute_cid, normalize_fields

from ..models import (Contributor, DailySnapshot, DiscomfortCheck, ProbeSession, ProvenancedRecord, Reset,
                      Supersession, TrainingSession, TrainingSet, WeeklyCheck, WorkBlock)

FORMAT, VERSION = "nymbus-jsonl", 1
RECORD_MODELS = [DailySnapshot, ProbeSession, WorkBlock, DiscomfortCheck, Reset, WeeklyCheck, TrainingSession,
                 TrainingSet]
BY_KIND = {m.record_kind: m for m in RECORD_MODELS}


class ImportError_(Exception):
    """A line that cannot be imported; the whole file is rolled back."""


def _iso(dt):
    return dt.astimezone(datetime.timezone.utc).isoformat()


def export_lines(contributor, now=None):
    """Yield the export as JSON strings (one per line, no newline)."""
    yield json.dumps({"type": "export", "format": FORMAT, "version": VERSION, "contributor": contributor.handle,
                      "timezone": contributor.timezone, "exported_at": _iso(now or timezone.now())}, sort_keys=True)
    events = []
    for model in RECORD_MODELS:
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
    if not items or items[0][1].get("type") != "export" or items[0][1].get("format") != FORMAT:
        raise ImportError_("line 1: not a nymbus-jsonl export header")
    header = items[0][1]
    if header.get("version") != VERSION:
        raise ImportError_(f"line 1: unsupported version {header.get('version')!r}")
    replaces = {i["new_cid"]: i["old_cid"] for _, i in items if i.get("type") == "supersession"}
    counts = {"records": 0, "supersessions": 0, "contributor": header["contributor"]}
    with transaction.atomic():
        contributor, _ = Contributor.objects.get_or_create(handle=header["contributor"],
                                                           defaults={"timezone": header["timezone"]})
        if any(m.objects.filter(contributor=contributor).exists() for m in RECORD_MODELS):
            raise ImportError_(f"contributor {contributor.handle} already has records; import into a fresh database")
        for number, item in items[1:]:
            kind = item.get("type")
            if kind == "record":
                model = BY_KIND.get(item.get("kind"))
                if model is None:
                    raise ImportError_(f"line {number}: unknown record kind {item.get('kind')!r}")
                if item.get("contributor") != contributor.handle:
                    raise ImportError_(f"line {number}: record of another contributor")
                if not verify_line(item):
                    raise ImportError_(f"line {number}: CID does not match the line's content")
                record = model(contributor=contributor)
                for name, value in item["fields"].items():
                    field = model._meta.get_field(name)
                    setattr(record, field.attname, field.to_python(value))
                if item["cid"] in replaces and hasattr(record, "replaces_cid"):
                    record.replaces_cid = replaces[item["cid"]]  # a correction may overlap what it replaces
                try:
                    # ProvenancedRecord.save: validation and CID, without the one-per-date snapshot
                    # rule; history comes from the supersession lines.
                    ProvenancedRecord.save(record)
                except Exception as exc:
                    raise ImportError_(f"line {number}: {exc}")
                if record.cid != item["cid"]:
                    raise ImportError_(f"line {number}: stored CID {record.cid} differs from {item['cid']}")
                counts["records"] += 1
            elif kind == "supersession":
                Supersession.objects.create(old_cid=item["old_cid"], new_cid=item["new_cid"],
                                            contributor=contributor, reason=item.get("reason", ""))
                counts["supersessions"] += 1
            else:
                raise ImportError_(f"line {number}: unknown line type {kind!r}")
    return counts
