# SPDX-License-Identifier: AGPL-3.0-or-later
"""When the nightly backup is due (M4.5 R6). Plain Python, no Django imports.

A "night" starts at the window start (local time, e.g. 02:00). A backup is due when the
last attempt was before the most recent window start: inside the window that is the
nightly run; a machine that slept through the window runs once on its next wake
(catch-up); after one attempt the night is done, so it never runs twice a night.
"""
import datetime


def parse_window(text):
    """'02:00-05:00' -> (time(2, 0), time(5, 0)). The window may cross midnight ('23:00-01:00')."""
    try:
        start, end = (datetime.time.fromisoformat(part.strip()) for part in text.split("-"))
    except ValueError:
        raise ValueError(f"BACKUP_WINDOW must look like 02:00-05:00, not {text!r}")
    if start == end:
        raise ValueError("BACKUP_WINDOW start and end must differ")
    return start, end


def _at(day, t, tz):
    """Aware datetime for local `day` at `t`; a time skipped by DST moves forward to the first valid instant."""
    naive = datetime.datetime.combine(day, t)
    candidate = naive.replace(tzinfo=tz)
    roundtrip = candidate.astimezone(datetime.timezone.utc).astimezone(tz).replace(tzinfo=None)
    if roundtrip != naive:  # nonexistent local time (clocks went forward): use the instant they jumped to
        return candidate.astimezone(datetime.timezone.utc).astimezone(tz)
    return candidate


def night_start(now, window, tz):
    """The most recent window start at or before `now` (aware), as an aware datetime."""
    start, _ = window
    local = now.astimezone(tz)
    today = _at(local.date(), start, tz)
    if today <= now:
        return today
    return _at(local.date() - datetime.timedelta(days=1), start, tz)


def in_window(now, window, tz):
    start, end = window
    begin = night_start(now, window, tz)
    end_day = begin.astimezone(tz).date() + (datetime.timedelta(days=1) if end <= start else datetime.timedelta())
    return now < _at(end_day, end, tz)


MAX_ATTEMPTS = 3  # a night: the first run plus up to two retries after a failure
RETRY_AFTER = datetime.timedelta(minutes=20)


def is_due(now, last_attempt, window, tz, failures_tonight=0, last_failed=False):
    """(due, reason). `last_attempt` is the start of the latest backup attempt (aware) or None.

    A successful (or still-running) attempt ends the night. A FAILED attempt may be retried inside the window,
    at most MAX_ATTEMPTS attempts per night, RETRY_AFTER apart, so a short outage does not cost a whole night
    while a broken setup is still not hammered.
    """
    begin = night_start(now, window, tz)
    if last_attempt is not None and last_attempt >= begin:
        if (last_failed and in_window(now, window, tz) and failures_tonight < MAX_ATTEMPTS
                and now - last_attempt >= RETRY_AFTER):
            return True, f"retry {failures_tonight + 1} of {MAX_ATTEMPTS - 1} after a failed attempt"
        return False, "already ran this night"
    if in_window(now, window, tz):
        return True, "inside the backup window"
    return True, "catch-up: the window passed without a backup"
