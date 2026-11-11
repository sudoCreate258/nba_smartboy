# SPDX-License-Identifier: AGPL-3.0-or-later
"""Helpers shared by the ingest and report commands."""
import datetime

from django.core.exceptions import ValidationError
from django.utils.dateparse import parse_datetime

DISCLAIMER = "Load gauge, not a medical assessment."
STOP_TEXT = "stop the block; get it checked by a professional"


def iso_default(value):
    """json.dumps default: dates and datetimes as ISO strings; anything else is an error."""
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    raise TypeError(f"Not JSON serializable: {type(value).__name__}")


def localize(value, tz, name="datetime"):
    """Aware datetime in UTC. Offset-less values are read in the contributor's time zone."""
    if isinstance(value, str):
        parsed = parse_datetime(value)
        if parsed is None:
            raise ValidationError(f"Not a datetime: {value!r}")
        value = parsed
    if not isinstance(value, datetime.datetime):
        raise ValidationError(f"Not a datetime: {value!r}")
    if value.tzinfo is None:
        value = value.replace(tzinfo=tz)
        # Different offsets for fold=0 and fold=1 mean the local time is ambiguous (clocks
        # go back) or does not exist (clocks go forward). Never pick silently.
        if value.replace(fold=0).utcoffset() != value.replace(fold=1).utcoffset():
            raise ValidationError(
                {name: f"{value:%Y-%m-%d %H:%M} is ambiguous or does not exist in {tz.key} (DST); "
                       "give an explicit UTC offset."}
            )
    return value.astimezone(datetime.timezone.utc)


def describe(exc):
    """Error text that names the field when the error is per-field."""
    if hasattr(exc, "error_dict"):
        return "; ".join(f"{name}: {' '.join(msgs)}" for name, msgs in exc.message_dict.items())
    return "; ".join(exc.messages)
