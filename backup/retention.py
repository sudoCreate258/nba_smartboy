# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which backup sets to keep on the remote (M4.5 R7). Plain Python, no Django imports.

Keep the newest set of each of the last 7 local days that have sets ("daily") and the
newest set of each of the last 4 ISO weeks that have sets ("weekly"). Everything else
may be deleted, but only after a new set has been uploaded and verified (runner.py).
"""
import datetime

DAILY, WEEKLY = 7, 4
NAME_FORMAT = "%Y-%m-%dT%H%M%SZ"  # set names are their UTC start time


def set_name(moment):
    return moment.astimezone(datetime.timezone.utc).strftime(NAME_FORMAT)


def parse_set_name(name):
    """Aware UTC datetime for a set name, or None if the name is not a set name."""
    try:
        return datetime.datetime.strptime(name.rstrip("/"), NAME_FORMAT).replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None


def select(names, tz, daily=DAILY, weekly=WEEKLY):
    """(keep, delete): sorted lists of set names. Names that are not set names are never deleted."""
    dated = sorted(((parse_set_name(n), n.rstrip("/")) for n in names if parse_set_name(n)), reverse=True)
    newest_per_day, newest_per_week = {}, {}
    for moment, name in dated:  # newest first, so the first seen per bucket is the newest
        local = moment.astimezone(tz).date()
        newest_per_day.setdefault(local, name)
        newest_per_week.setdefault(local.isocalendar()[:2], name)
    keep = set(list(newest_per_day.values())[:daily]) | set(list(newest_per_week.values())[:weekly])
    all_sets = [name for _, name in dated]
    return sorted(keep), sorted(n for n in all_sets if n not in keep)
