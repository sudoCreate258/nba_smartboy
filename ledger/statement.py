# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deposit statement (M5 R6): per local month and category, who read how many records, for what
purpose, and the simulated credits. Simulated only: there is no currency anywhere."""
import datetime
import json

from django.db.models.functions import TruncMonth
from django.utils import timezone

from nymbus import ledger

from .models import AccessEvent


MAX_MONTH_LINKS = 24


def _month_bounds(month, tz):
    """[start, end) of a local month as aware datetimes."""
    year, mon = int(month[:4]), int(month[5:])
    start = datetime.datetime(year, mon, 1, tzinfo=tz)
    end = datetime.datetime(year + (mon == 12), mon % 12 + 1, 1, tzinfo=tz)
    return start, end


def _events(contributor, month):
    """Events of one local month only (bounded in SQL, index on contributor and time)."""
    start, end = _month_bounds(month, contributor.tzinfo)
    rows = AccessEvent.objects.filter(contributor=contributor, at__gte=start, at__lt=end).order_by("seq")
    return [{"at": e.at, "category": e.category, "recipient": e.recipient, "purpose": e.purpose,
             "record_cids": e.record_cids, "units": e.units} for e in rows]


def _months(contributor):
    """Local months with events, newest first (at most MAX_MONTH_LINKS), without loading the events."""
    times = (AccessEvent.objects.filter(contributor=contributor)
             .annotate(m=TruncMonth("at", tzinfo=contributor.tzinfo)).values_list("m", flat=True).distinct())
    return sorted({t.strftime("%Y-%m") for t in times}, reverse=True)[:MAX_MONTH_LINKS]


def current_month(contributor, now=None):
    return ledger.month_of(now or timezone.now(), contributor.tzinfo)


def build(contributor, month=None, now=None):
    """The statement of `month` ('YYYY-MM', default this local month) with its CID and the months that
    have events."""
    requested = month
    month = ledger.parse_month(month, current_month(contributor, now))
    stmt = ledger.statement(_events(contributor, month), contributor.tzinfo, month)
    stmt["timezone"] = contributor.timezone
    stmt["cid"] = ledger.statement_cid(contributor.handle, contributor.timezone, stmt)
    stmt["months"] = _months(contributor)
    stmt["ignored_month"] = requested if requested and requested != month else None
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
