"""Simulated ownership ledger (Nymbus layer 6, phase 1). Plain Python, no Django imports.

Who may use which category of the owner's data, and a tamper-evident record of every use.
Simulated only: the recipients are fixed simulated parties and the units are "simulated
credits", never money or tokens.
"""
import hashlib
import re
from collections import defaultdict

from .provenance import canonical_bytes, compute_cid

RECIPIENTS = ("self-analysis", "sim-research-partner")
UNIT_LABEL = "simulated credits"
CREDITS_PER_RECORD = 1
GENESIS = "0" * 64  # prev_hash of the first event in a chain
STATEMENT_FORMAT, STATEMENT_VERSION = "nymbus-statement-jsonl", 1


def units_for(record_cids):
    """Simulated credits for one read: one per record read."""
    return CREDITS_PER_RECORD * len(record_cids)


def digest(data):
    """SHA-256 hex of an event's canonical bytes: what the next event stores as prev_hash.
    It is the same digest the event's CID carries, so the chain adds no second identifier."""
    return hashlib.sha256(data).hexdigest()


def is_active(start, end, revoked_at, at):
    """A grant is active from its start, until its end (exclusive) and until it is revoked."""
    return start <= at and (end is None or at < end) and (revoked_at is None or at < revoked_at)


def check_chain(events):
    """Problems in one contributor's chain, [] when intact.

    `events`: dicts with "seq", "prev_hash" and "canonical" (bytes), in seq order.
    """
    problems, expected_prev = [], GENESIS
    for position, event in enumerate(events, start=1):
        if event["seq"] != position:
            problems.append(f"event {event['seq']}: expected sequence number {position} (an event is missing or "
                            "out of order)")
        if event["prev_hash"] != expected_prev:
            problems.append(f"event {event['seq']}: prev_hash does not match the previous event")
        expected_prev = digest(event["canonical"])
    return problems


def month_of(at, tz):
    return at.astimezone(tz).strftime("%Y-%m")


def months(events, tz):
    """Local months that have events, newest first."""
    return sorted({month_of(e["at"], tz) for e in events}, reverse=True)


def statement(events, tz, month):
    """The deposit statement of one local month.

    `events`: dicts with "at", "category", "recipient", "purpose", "record_cids", "units".
    Rows are per (category, recipient, purpose); totals per category; everything in simulated credits.
    """
    groups = defaultdict(lambda: {"reads": 0, "records_accessed": 0, "records": set(), "units": 0})
    for e in events:
        if month_of(e["at"], tz) != month:
            continue
        g = groups[(e["category"], e["recipient"], e["purpose"])]
        g["reads"] += 1
        g["records_accessed"] += len(e["record_cids"])
        g["records"].update(e["record_cids"])
        g["units"] += e["units"]
    rows = [{"category": c, "recipient": r, "purpose": p, "reads": g["reads"],
             "records_accessed": g["records_accessed"], "distinct_records": len(g["records"]), "units": g["units"]}
            for (c, r, p), g in sorted(groups.items())]
    totals = defaultdict(lambda: {"reads": 0, "records_accessed": 0, "units": 0})
    for row in rows:
        for key in ("reads", "records_accessed", "units"):
            totals[row["category"]][key] += row[key]
    return {"month": month, "unit": UNIT_LABEL, "rows": rows,
            "totals": [{"category": c, **t} for c, t in sorted(totals.items())],
            "units_total": sum(row["units"] for row in rows)}


def statement_cid(contributor, timezone_name, stmt):
    """CIDv1 of the statement content (month, time zone, unit label and rows)."""
    fields = {"month": stmt["month"], "timezone": timezone_name, "unit": stmt["unit"], "rows": stmt["rows"]}
    return compute_cid(canonical_bytes("deposit_statement", contributor, fields))


def parse_month(value, default):
    """'YYYY-MM' -> the same string when valid, else `default`."""
    return value if isinstance(value, str) and _MONTH.fullmatch(value) else default


_MONTH = re.compile(r"\d{4}-(0[1-9]|1[0-2])")
