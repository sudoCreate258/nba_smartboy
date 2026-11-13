# SPDX-License-Identifier: AGPL-3.0-or-later
"""Round-trip proof (MVP, 025 R4): export a contributor as nymbus-jsonl v1, import it into a freshly
made scratch database, export it again there, and compare every record CID, every correction and the
ledger head. Exit 0 when identical, 1 otherwise. The live database is only read.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from backup.runner import _admin_conn, _db
from core.models import Contributor
from core.services.export import export_lines
from nymbus import ledger
from nymbus.provenance import canonical_bytes

SCRATCH = "twin_roundtrip_check"


def summary(lines):
    """(record (kind, cid) set, supersession pair set, ledger head) of an export."""
    records, corrections, events, handle = set(), set(), [], None
    for line in lines:
        item = json.loads(line)
        if item["type"] == "export":
            handle = item["contributor"]
        elif item["type"] == "record":
            records.add((item["kind"], item["cid"]))
            if item["kind"] == "access_event":
                events.append(item["fields"])
        elif item["type"] == "supersession":
            corrections.add((item["old_cid"], item["new_cid"]))
    events.sort(key=lambda f: f["seq"])
    last = ledger.digest(canonical_bytes("access_event", handle, events[-1])) if events else ledger.GENESIS
    return records, corrections, {"events": len(events), "last_hash": last}


def _manage(env, *args):
    result = subprocess.run([sys.executable, "manage.py", *args], cwd=settings.BASE_DIR, env=env,
                            capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise CommandError(f"manage.py {args[0]} in the scratch database failed: {result.stderr.strip()[-500:]}")
    return result.stdout


class Command(BaseCommand):
    help = "Export, import into a scratch database, export again, compare CIDs, corrections and ledger head (exit 0/1)."

    def add_arguments(self, parser):
        parser.add_argument("--contributor", default="demo")

    def handle(self, *args, contributor, **options):
        try:
            who = Contributor.objects.get(handle=contributor)
        except Contributor.DoesNotExist:
            raise CommandError(f"Unknown contributor: {contributor} (run seed_demo for the DEMO profile)")
        db = _db()
        with tempfile.TemporaryDirectory(prefix="twin-roundtrip-") as tmp:
            first = Path(tmp) / "first.jsonl"
            second = Path(tmp) / "second.jsonl"
            first.write_text("".join(line + "\n" for line in export_lines(who)), encoding="utf-8")
            with _admin_conn(db) as conn:
                conn.execute(f'DROP DATABASE IF EXISTS "{SCRATCH}"')
                conn.execute(f'CREATE DATABASE "{SCRATCH}"')
            try:
                env = {**os.environ, "POSTGRES_DB": SCRATCH}
                _manage(env, "migrate", "--verbosity", "0")
                _manage(env, "import_my_data", str(first))
                _manage(env, "export_my_data", "--contributor", contributor, "--out", str(second))
                a = summary(first.read_text(encoding="utf-8").splitlines())
                b = summary(second.read_text(encoding="utf-8").splitlines())
            finally:
                with _admin_conn(db) as conn:
                    conn.execute(f'DROP DATABASE IF EXISTS "{SCRATCH}"')
        problems = [name for name, x, y in zip(("record CIDs", "corrections", "ledger head"), a, b) if x != y]
        if problems:
            raise CommandError(f"Round trip FAILED for {contributor}: {', '.join(problems)} differ")
        self.stdout.write(f"Round trip OK for {contributor}: {len(a[0])} records, {len(a[1])} corrections, "
                          f"ledger head {a[2]['events']} events / {a[2]['last_hash'][:16]}... identical after "
                          "export, import into an empty database and export again.")
