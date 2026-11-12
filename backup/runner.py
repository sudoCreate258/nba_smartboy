# SPDX-License-Identifier: AGPL-3.0-or-later
"""One backup run (M4.5 R1, R2, R7, R8): build a dated set, upload it through an rclone
crypt remote, verify it from the remote, then prune old sets.

Nothing readable leaves the machine: rclone crypt encrypts file names and contents
before upload. The rclone config (and with it the crypt password) is read from
RCLONE_CONFIG and never touched or printed here.
"""
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import zoneinfo
from pathlib import Path

import psycopg
from django.conf import settings
from django.db import connection
from django.utils import timezone

from core.models import Contributor
from core.services.export import RECORD_MODELS, export_lines, verify_line

from . import retention
from .models import BackupRun

DUMP = "twin.dump"
MANIFEST = "manifest.json"
INBOX = "inbox.tar.gz"
FORMAT, VERSION = "twin-backup", 1


class BackupError(Exception):
    pass


# --- helpers ---------------------------------------------------------------------

def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_commit():
    """The checked-out commit, read from .git (git itself is not in the image)."""
    head = Path(settings.BASE_DIR) / ".git" / "HEAD"
    try:
        ref = head.read_text().strip()
        if ref.startswith("ref: "):
            path = Path(settings.BASE_DIR) / ".git" / ref[5:]
            if path.exists():
                return path.read_text().strip()
            packed = Path(settings.BASE_DIR) / ".git" / "packed-refs"
            for line in packed.read_text().splitlines():
                if line.endswith(" " + ref[5:]):
                    return line.split()[0]
            return "unknown"
        return ref
    except OSError:
        return "unknown"


def rclone(args, config):
    """Run rclone with the given config; raise BackupError with its message on failure."""
    if not config or not Path(config).is_file():
        raise BackupError("rclone is not configured: RCLONE_CONFIG must point to your rclone.conf "
                          "(set RCLONE_CONFIG_HOST in .env; see docs/OPERATIONS.md)")
    result = subprocess.run(["rclone", "--config", str(config), *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise BackupError(f"rclone {args[0]} failed: {result.stderr.strip()[-500:]}")
    return result.stdout


def _db():
    s = connection.settings_dict
    return {"host": s["HOST"] or "localhost", "port": str(s["PORT"] or 5432), "user": s["USER"],
            "password": s["PASSWORD"], "name": s["NAME"]}


def _pg_env(db):
    return {**os.environ, "PGPASSWORD": db["password"] or ""}


def _run(cmd, env):
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        raise BackupError(f"{cmd[0]} failed: {result.stderr.strip()[-500:]}")


# --- building the set -------------------------------------------------------------------

def build_set(folder, now=None, include_inbox=None):
    """Write the set into `folder`; returns the manifest dict (also written as manifest.json)."""
    now = now or timezone.now()
    include_inbox = settings.BACKUP_INCLUDE_INBOX if include_inbox is None else include_inbox
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    db = _db()
    _run(["pg_dump", "-Fc", "-h", db["host"], "-p", db["port"], "-U", db["user"], "-d", db["name"],
          "-f", str(folder / DUMP)], _pg_env(db))
    exports = []
    for contributor in Contributor.objects.order_by("handle"):
        name = f"my-data-{contributor.handle}.jsonl"
        with open(folder / name, "w", encoding="utf-8", newline="\n") as fh:
            for line in export_lines(contributor, now=now):
                fh.write(line + "\n")
        exports.append(name)
    if include_inbox and Path(settings.BACKUP_INBOX_DIR).is_dir():
        with tarfile.open(folder / INBOX, "w:gz") as tar:
            for path in sorted(Path(settings.BACKUP_INBOX_DIR).rglob("*")):
                if path.is_file() and path.name != ".gitkeep":
                    tar.add(path, arcname=str(path.relative_to(settings.BACKUP_INBOX_DIR)))
    files = sorted(p.name for p in folder.iterdir() if p.name != MANIFEST)
    manifest = {
        "format": FORMAT, "version": VERSION,
        "created_at": now.astimezone(datetime.timezone.utc).isoformat(),
        "git_commit": git_commit(), "app_version": settings.TWIN_VERSION,
        "files": [{"name": n, "bytes": (folder / n).stat().st_size, "sha256": sha256(folder / n)} for n in files],
        "exports": exports,
        "record_counts": {m.record_kind: m.objects.count() for m in RECORD_MODELS},
        "includes_inbox": INBOX in files,
    }
    (folder / MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


# --- verification -------------------------------------------------------------------------

def check_files(folder, manifest):
    """Every file in the manifest exists with the recorded size and SHA-256; raises BackupError."""
    folder = Path(folder)
    for entry in manifest["files"]:
        path = folder / entry["name"]
        if not path.is_file():
            raise BackupError(f"verify: {entry['name']} is missing from the downloaded set")
        if path.stat().st_size != entry["bytes"] or sha256(path) != entry["sha256"]:
            raise BackupError(f"verify: {entry['name']} does not match its SHA-256 in the manifest")


def _admin_conn(db):
    return psycopg.connect(host=db["host"], port=db["port"], user=db["user"], password=db["password"],
                           dbname="postgres", autocommit=True)


def restore_dump(dbname, dump, clean=False):
    """pg_restore the dump into database `dbname` (clean=True replaces existing objects)."""
    db = _db()
    cmd = ["pg_restore", "--no-owner", "--no-privileges", "--exit-on-error", "-h", db["host"], "-p", db["port"],
           "-U", db["user"], "-d", dbname]
    if clean:
        cmd += ["--clean", "--if-exists"]
    _run(cmd + [str(dump)], _pg_env(db))


def compare_with_exports(dbname, folder, manifest):
    """Every export line self-verifies, and the record CIDs in `dbname` equal the exports' and the manifest counts.
    Returns the number of records checked."""
    folder, db = Path(folder), _db()
    restored = {}
    with psycopg.connect(host=db["host"], port=db["port"], user=db["user"], password=db["password"],
                         dbname=dbname) as conn:
        for model in RECORD_MODELS:
            rows = conn.execute(f'SELECT cid FROM "{model._meta.db_table}"').fetchall()
            restored[model.record_kind] = {r[0] for r in rows}
    exported = {m.record_kind: set() for m in RECORD_MODELS}
    for name in manifest["exports"]:
        with open(folder / name, encoding="utf-8") as fh:
            for number, line in enumerate(fh, start=1):
                item = json.loads(line)
                if item.get("type") != "record":
                    continue
                if not verify_line(item):
                    raise BackupError(f"verify: {name} line {number}: CID does not match its content")
                exported[item["kind"]].add(item["cid"])
    for kind, cids in restored.items():
        if cids != exported[kind]:
            raise BackupError(f"verify: {kind} CIDs in the restored dump differ from the export")
        if len(cids) != manifest["record_counts"].get(kind):
            raise BackupError(f"verify: {kind} count differs from the manifest")
    return sum(len(c) for c in restored.values())


def verify_restore(folder, manifest, scratch):
    """Restore the dump into a scratch database and compare it with the exports; drops the scratch database."""
    db = _db()
    with _admin_conn(db) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{scratch}"')
    try:
        restore_dump(scratch, Path(folder) / DUMP)
        return compare_with_exports(scratch, folder, manifest)
    finally:
        with _admin_conn(db) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)')


def download_set(name, folder, remote=None, config=None):
    """Download set `name` (or "latest") through the crypt remote into `folder`; returns the set name."""
    remote = remote if remote is not None else settings.BACKUP_REMOTE
    config = config if config is not None else os.environ.get("RCLONE_CONFIG", "")
    if name == "latest":
        sets = sorted(n for n in list_sets(remote, config) if retention.parse_set_name(n))
        if not sets:
            raise BackupError("there are no backup sets on the remote")
        name = sets[-1]
    rclone(["copy", f"{remote}sets/{name}", str(folder)], config)
    return name


# --- the run ---------------------------------------------------------------------------------

def _tz():
    try:
        return Contributor.objects.get(handle=settings.TWIN_CONTRIBUTOR).tzinfo
    except Contributor.DoesNotExist:
        return zoneinfo.ZoneInfo(settings.TIME_ZONE)


def list_sets(remote, config):
    out = rclone(["lsf", "--dirs-only", f"{remote}sets/"], config)
    return [line.rstrip("/") for line in out.splitlines() if line.strip()]


def run_backup(trigger=BackupRun.Trigger.MANUAL, now=None, remote=None, config=None, include_inbox=None):
    """Back up, verify, prune. Returns the BackupRun (status ok or failed); never raises for backup errors."""
    now = now or timezone.now()
    remote = remote if remote is not None else settings.BACKUP_REMOTE
    config = config if config is not None else os.environ.get("RCLONE_CONFIG", "")
    run = BackupRun.objects.create(started_at=now, trigger=trigger, set_name=retention.set_name(now))
    work = Path(tempfile.mkdtemp(prefix="twin-backup-"))
    try:
        if not remote or not remote.endswith((":", "/")):
            raise BackupError("BACKUP_REMOTE must name your crypt remote ending in ':' or '/', e.g. twin-crypt: "
                              "(set it in .env; see docs/OPERATIONS.md)")
        local = work / "set"
        manifest = build_set(local, now=now, include_inbox=include_inbox)
        run.manifest = manifest
        run.size_bytes = sum(f["bytes"] for f in manifest["files"])
        target = f"{remote}sets/{run.set_name}"
        rclone(["copy", str(local), target], config)
        run.uploaded = True
        run.save(update_fields=["manifest", "size_bytes", "uploaded"])

        fresh = work / "verify"
        rclone(["copy", target, str(fresh)], config)  # a fresh download through crypt
        downloaded = json.loads((fresh / MANIFEST).read_text(encoding="utf-8"))
        if downloaded != manifest:
            raise BackupError("verify: the downloaded manifest differs from the one uploaded")
        check_files(fresh, downloaded)
        verify_restore(fresh, downloaded, scratch=f"twin_verify_{run.pk}")
        run.verified = True

        _, delete = retention.select(list_sets(remote, config), _tz())
        for name in delete:
            if name != run.set_name:
                rclone(["purge", f"{remote}sets/{name}"], config)
                run.pruned.append(name)
        run.status = BackupRun.Status.OK
    except Exception as exc:  # report every failure; earlier sets are left untouched
        run.status = BackupRun.Status.FAILED
        run.error = f"{type(exc).__name__}: {exc}" if not isinstance(exc, BackupError) else str(exc)
    finally:
        shutil.rmtree(work, ignore_errors=True)
        run.finished_at = timezone.now()
        run.save()
    return run
