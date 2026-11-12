# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deposit statement (M5 R6): per local month and category, who read how many records, for what
purpose, and the simulated credits. Simulated only: there is no currency anywhere."""
import json

from django.utils import timezone

from nymbus import ledger

from .models import AccessEvent


def _events(contributor):
    return [{"at": e.at, "category": e.category, "recipient": e.recipient, "purpose": e.purpose,
             "record_cids": e.record_cids, "units": e.units}
            for e in AccessEvent.objects.filter(contributor=contributor).order_by("seq")]


def current_month(contributor, now=None):
    return ledger.month_of(now or timezone.now(), contributor.tzinfo)


def build(contributor, month=None, now=None):
    """The statement of `month` ('YYYY-MM', default this local month) with its CID and the months that
    have events."""
    month = ledger.parse_month(month, current_month(contributor, now))
    events = _events(contributor)
    stmt = ledger.statement(events, contributor.tzinfo, month)
    stmt["timezone"] = contributor.timezone
    stmt["cid"] = ledger.statement_cid(contributor.handle, contributor.timezone, stmt)
    stmt["months"] = ledger.months(events, contributor.tzinfo)
    return stmt


def jsonl(contributor, stmt):
    """The download: a header line carrying the CID, then one line per row and per category total.
    The CID covers month, time zone, unit and rows (totals are sums of the rows)."""
    yield json.dumps({"type": "statement", "format": ledger.STATEMENT_FORMAT, "version": ledger.STATEMENT_VERSION,
                      "contributor": contributor.handle, "timezone": stmt["timezone"], "month": stmt["month"],
                      "unit": stmt["unit"], "cid": stmt["cid"]}, sort_keys=True)
    for row in stmt["rows"]:
        yield json.dumps({"type": "row", **row}, sort_keys=True, ensure_ascii=False)
    for total in stmt["totals"]:
        yield json.dumps({"type": "total", **total}, sort_keys=True)
