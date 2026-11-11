# SPDX-License-Identifier: AGPL-3.0-or-later
"""Import training sets from CSV: one row per set, session columns repeated.

Header (planner message 012; columns may come in any order, optional ones may be left out):
started_at,program,mesocycle,meso_week,is_deload,location,session_rpe,order,exercise,muscle_group,
load_kg,reps,rir,pump,soreness_before,joint_pain,joint_pain_area,notes
"""
import csv
from collections import Counter
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.management.commands.ingest_yaml import describe, localize
from core.models import Contributor, TrainingSession, TrainingSet

HEADER = (
    "started_at,program,mesocycle,meso_week,is_deload,location,session_rpe,order,exercise,muscle_group,"
    "load_kg,reps,rir,pump,soreness_before,joint_pain,joint_pain_area,notes"
).split(",")
REQUIRED = {"started_at", "order", "exercise", "muscle_group", "reps"}
SESSION_COLUMNS = ("mesocycle", "meso_week", "is_deload", "location", "session_rpe")
INTS = {"meso_week", "order", "reps", "rir", "pump", "soreness_before", "joint_pain"}
DECIMALS = {"session_rpe", "load_kg"}
LOWER = {"location", "muscle_group", "joint_pain_area"}
BOOLS = {"yes": True, "true": True, "no": False, "false": False, "": False}


class RowError(Exception):
    pass


def parse_value(name, raw):
    value = (raw or "").strip()
    if name == "is_deload":
        try:
            return BOOLS[value.lower()]
        except KeyError:
            raise RowError(f"is_deload: use yes/no or true/false, not {value!r}")
    if value == "":
        return "" if name in {"program", "mesocycle", "notes"} else None
    if name in INTS:
        try:
            return int(value)
        except ValueError:
            raise RowError(f"{name}: not a whole number: {value!r}")
    if name in DECIMALS:
        try:
            return Decimal(value)
        except InvalidOperation:
            raise RowError(f"{name}: not a number: {value!r}")
    if name in LOWER:
        return value.lower()
    return value


class Command(BaseCommand):
    help = "Import training sessions and sets from a CSV file (one row per set) in a single transaction."

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--contributor", default="mike")

    def handle(self, *args, path, contributor, **options):
        try:
            who = Contributor.objects.get(handle=contributor)
        except Contributor.DoesNotExist:
            raise CommandError(f"Unknown contributor: {contributor}")
        rows = self.read(path)
        counts = Counter()
        with transaction.atomic():  # any error rolls back the whole file
            sessions = {}
            for line, row in rows:
                try:
                    # Omitted optional columns get the same value as an empty cell.
                    values = {k: parse_value(k, row.get(k, "")) for k in HEADER}
                    if values.get("started_at") is None:
                        raise RowError("started_at is required")
                    started = localize(values["started_at"], who.tzinfo, "started_at")
                    key = (started, values["program"])
                    fields = {k: values[k] for k in SESSION_COLUMNS}
                    if key not in sessions:
                        sessions[key] = (self.session(who, started, key[1], fields, counts), fields)
                    session, first = sessions[key]
                    if fields != first:
                        changed = ", ".join(k for k in SESSION_COLUMNS if fields[k] != first[k])
                        raise RowError(f"session columns differ from the first row of this session ({changed})")
                    self.add_set(who, session, values, counts)
                except RowError as exc:
                    raise CommandError(f"Line {line}: {exc}")
                except ValidationError as exc:
                    raise CommandError(f"Line {line}: {describe(exc)}")
        self.stdout.write(
            f"sessions created={counts['session_created']} existing={counts['session_existing']}; "
            f"sets created={counts['set_created']} skipped={counts['set_skipped']}"
        )

    def read(self, path):
        try:
            with open(path, encoding="utf-8-sig", newline="") as fh:  # utf-8-sig: spreadsheet exports
                reader = csv.DictReader(fh)
                header = [h.strip() for h in (reader.fieldnames or [])]
                unknown = [h for h in header if h not in HEADER]
                if unknown:
                    raise CommandError(f"Unknown columns: {', '.join(unknown)}")
                missing = REQUIRED - set(header)
                if missing:
                    raise CommandError(f"Missing required columns: {', '.join(sorted(missing))}")
                reader.fieldnames = header
                rows = []
                for row in reader:
                    if None in row:
                        raise CommandError(f"Line {reader.line_num}: more values than columns")
                    if all((v or "").strip() == "" for v in row.values()):
                        continue  # blank spreadsheet row
                    rows.append((reader.line_num, row))
                return rows
        except OSError as exc:
            raise CommandError(f"Cannot read {path}: {exc}")
        except csv.Error as exc:
            raise CommandError(f"Invalid CSV in {path}: {exc}")

    def session(self, who, started, program, fields, counts):
        candidate = TrainingSession(contributor=who, started_at=started, program=program, **fields)
        candidate.validate()
        existing = TrainingSession.objects.filter(cid=candidate.compute_cid()).first()
        if existing is not None:
            counts["session_existing"] += 1
            return existing
        candidate.save()
        counts["session_created"] += 1
        return candidate

    def add_set(self, who, session, values, counts):
        set_fields = {k: values[k] for k in HEADER if k not in SESSION_COLUMNS + ("started_at", "program")}
        candidate = TrainingSet(contributor=who, session_cid=session.cid, **set_fields)
        if TrainingSet.objects.filter(cid=candidate.compute_cid()).exists():
            counts["set_skipped"] += 1
            return
        candidate.save()
        counts["set_created"] += 1
