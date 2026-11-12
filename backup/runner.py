# SPDX-License-Identifier: AGPL-3.0-or-later
"""One backup run (M4.5 R1, R2, R7, R8): build a dated set, upload it through an rclone
crypt remote into a staging area, verify it from the remote, publish it, then prune old sets.

Nothing readable leaves the machine: the run refuses any remote that is not an rclone
crypt remote, and crypt encrypts file names and contents before upload. The rclone config
(and with it the crypt password) is read from RCLONE_CONFIG and never printed here.

Remote layout:  <remote>staging/<set>/   uploaded, not yet proven
                <remote>sets/<set>/      verified and published: the only place `latest` and
                                         retention ever look
A set that fails verification never reaches `sets/`, so it can neither be restored by
mistake nor push a verified set out through retention.
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
from django.db import connection, transaction
from django.utils import timezone

from core.models import Contributor, Supersession
from core.services.export import EXPORT_MODELS, LEDGER_MODELS, RECORD_MODELS, export_lines, verify_line

from . import retention
from .models import BackupRun

DUMP = "twin.dump"
MANIFEST = "manifest.json"
INBOX = "inbox.tar.gz"
FORMAT, VERSION = "twin-backup", 1
STALE_AFTER = datetime.timedelta(hours=6)  # a "running" attempt older than this was interrupted


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
    # The repository folder is mounted into the container and is what git tracks: a config (which holds the
    # crypt password) must live outside it.
    if Path(config).resolve().is_relative_to(Path(settings.BASE_DIR).resolve()) \
            and not os.environ.get("TWIN_ALLOW_CONFIG_IN_REPO"):
        raise BackupError("the rclone config is inside the repository folder; keep it outside (RCLONE_CONFIG_HOST "
                          "in .env, docs/OPERATIONS.md) so its password cannot be committed")
    result = subprocess.run(["rclone", "--config", str(config), *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise BackupError(f"rclone {args[0]} failed: {result.stderr.strip()[-500:]}")
    return result.stdout


def require_crypt(remote, config):
    """Fail closed unless `remote` is an rclone crypt remote (R2: plain bytes never reach the remote).

    Reads only each remote's type and target from `rclone config dump`; aliases are followed to what
    they point at. A plain backend, a local path or an unknown name is refused before any file is built.
    """
    try:
        dump = json.loads(rclone(["config", "dump"], config))
    except json.JSONDecodeError:
        raise BackupError("could not read the rclone config")
    name = remote.split(":", 1)[0] if ":" in remote else ""
    seen = set()
    while name and name not in seen:
        seen.add(name)
        entry = dump.get(name)
        if entry is None:
            raise BackupError(f"BACKUP_REMOTE '{remote}' is not a remote in the rclone config; it must be the "
                              "crypt remote (see docs/OPERATIONS.md)")
        if entry.get("type") == "crypt":
            # A crypt remote that leaves names or data readable is not encryption (R2).
            if str(entry.get("no_data_encryption", "")).lower() == "true":
                raise BackupError(f"crypt remote '{name}' has no_data_encryption set: file contents would be stored "
                                  "readable. Remove that option (docs/OPERATIONS.md).")
            if str(entry.get("filename_encryption", "standard")).lower() == "off":
                raise BackupError(f"crypt remote '{name}' has filename_encryption = off: file names would be stored "
                                  "readable. Use 'standard' (docs/OPERATIONS.md).")
            if not entry.get("password"):
                raise BackupError(f"crypt remote '{name}' has no password set")
            return
        if entry.get("type") != "alias":
            raise BackupError(f"BACKUP_REMOTE '{remote}' is a '{entry.get('type')}' remote, not crypt: backups "
                              "would be stored readable. Point it at your crypt remote (docs/OPERATIONS.md).")
        target = entry.get("remote", "")
        name = target.split(":", 1)[0] if ":" in target else ""
    raise BackupError(f"BACKUP_REMOTE '{remote}' does not lead to a crypt remote; refusing to upload readable files")


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
    """Write the set into `folder`; returns the manifest dict (also written as manifest.json).

    The dump, the exports and the record counts all read ONE database snapshot (an exported
    repeatable-read snapshot that pg_dump joins), so they describe the same instant even
    while the app is being used.
    """
    now = now or timezone.now()
    include_inbox = settings.BACKUP_INCLUDE_INBOX if include_inbox is None else include_inbox
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    db = _db()
    exports, counts = [], {}
    with transaction.atomic():
        cursor = connection.cursor()
        cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        cursor.execute("SELECT pg_export_snapshot()")
        snapshot = cursor.fetchone()[0]
        _run(["pg_dump", "-Fc", "--snapshot", snapshot, "-h", db["host"], "-p", db["port"], "-U", db["user"],
              "-d", db["name"], "-f", str(folder / DUMP)], _pg_env(db))
        for contributor in Contributor.objects.order_by("handle"):
            name = f"my-data-{contributor.handle}.jsonl"
            with open(folder / name, "w", encoding="utf-8", newline="\n") as fh:
                for line in export_lines(contributor, now=now):
                    fh.write(line + "\n")
            exports.append(name)
        counts = {m.record_kind: m.objects.count() for m in EXPORT_MODELS}
        counts["supersession"] = Supersession.objects.count()
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
        "record_counts": counts,
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
    """pg_restore the dump into database `dbname`. clean=True replaces existing objects, in one
    transaction (all or nothing)."""
    db = _db()
    cmd = ["pg_restore", "--no-owner", "--no-privileges", "--exit-on-error", "-h", db["host"], "-p", db["port"],
           "-U", db["user"], "-d", dbname]
    if clean:
        cmd += ["--clean", "--if-exists", "--single-transaction"]
    _run(cmd + [str(dump)], _pg_env(db))


def compare_with_exports(dbname, folder, manifest):
    """The restored database `dbname` equals the exports: every export line self-verifies, the record CIDs
    are the same, and so are the correction (supersession) events. Returns the number of records checked."""
    folder, db = Path(folder), _db()
    restored, restored_events = {}, set()
    # Sets made before the ledger (M5) have no ledger counts (nor tables); their data kinds still verify.
    models = RECORD_MODELS + [m for m in LEDGER_MODELS if m.record_kind in manifest["record_counts"]]
    with psycopg.connect(host=db["host"], port=db["port"], user=db["user"], password=db["password"],
                         dbname=dbname) as conn:
        for model in models:
            rows = conn.execute(f'SELECT cid FROM "{model._meta.db_table}"').fetchall()
            restored[model.record_kind] = {r[0] for r in rows}
        restored_events = set(conn.execute("SELECT old_cid, new_cid FROM core_supersession").fetchall())
    exported = {m.record_kind: set() for m in EXPORT_MODELS}
    exported_events = set()
    for name in manifest["exports"]:
        with open(folder / name, encoding="utf-8") as fh:
            header = json.loads(fh.readline())
            if header.get("type") != "export" or header.get("format") != "nymbus-jsonl":
                raise BackupError(f"verify: {name} does not start with a nymbus-jsonl header")
            for number, line in enumerate(fh, start=2):
                item = json.loads(line)
                if item.get("type") == "record":
                    if not verify_line(item):
                        raise BackupError(f"verify: {name} line {number}: CID does not match its content")
                    exported[item["kind"]].add(item["cid"])
                elif item.get("type") == "supersession":
                    exported_events.add((item["old_cid"], item["new_cid"]))
    for kind, cids in restored.items():
        if cids != exported[kind]:
            raise BackupError(f"verify: {kind} CIDs in the restored dump differ from the export")
        if len(cids) != manifest["record_counts"].get(kind):
            raise BackupError(f"verify: {kind} count differs from the manifest")
    recorded = manifest["record_counts"].get("supersession")  # sets from before this field existed have none
    if restored_events != exported_events or (recorded is not None and len(restored_events) != recorded):
        raise BackupError("verify: corrections (supersession events) in the restored dump differ from the export")
    return sum(len(c) for c in restored.values())


def newer_migrations(dbname):
    """Migrations recorded in database `dbname` that this code does not have: the set came from newer code."""
    from django.db.migrations.loader import MigrationLoader

    code = set(MigrationLoader(None, ignore_no_migrations=True).disk_migrations)
    db = _db()
    with psycopg.connect(host=db["host"], port=db["port"], user=db["user"], password=db["password"],
                         dbname=dbname) as conn:
        recorded = {(a, n) for a, n in conn.execute("SELECT app, name FROM django_migrations").fetchall()}
    return sorted(f"{a}.{n}" for a, n in recorded - code)


def free_space_ok(needed_bytes):
    """The verify/restore scratch database lives on the same server as the live one. Refuse when the data
    volume has less than twice the set's size free (a full disk would hit the live database)."""
    free = shutil.disk_usage(settings.BASE_DIR).free  # the app and database volumes share the Docker VM disk
    return free >= 2 * needed_bytes


def verify_restore(folder, manifest, scratch, check_schema=False):
    """Restore the dump into a scratch database and compare it with the exports; drops the scratch database.

    check_schema=True (used by restore_backup) also refuses a set made by newer code than this one."""
    db = _db()
    size = sum(f["bytes"] for f in manifest["files"])
    if not free_space_ok(size):
        raise BackupError(f"verify: not enough free disk space for a scratch restore (need about {2 * size // 10**6} MB)")
    with _admin_conn(db) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{scratch}"')
    try:
        restore_dump(scratch, Path(folder) / DUMP)
        if check_schema:
            ahead = newer_migrations(scratch)
            if ahead:
                raise BackupError(f"this set was made by newer code (it has migrations this version lacks: "
                                  f"{', '.join(ahead[:3])}{', ...' if len(ahead) > 3 else ''}); update the app "
                                  "to at least that version first, then restore")
        return compare_with_exports(scratch, folder, manifest)
    finally:
        with _admin_conn(db) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)')


def list_sets(remote, config, area="sets"):
    """Names of the sets in `area` ("sets" = verified and published, "staging" = uploaded, not proven)."""
    try:
        out = rclone(["lsf", "--dirs-only", f"{remote}{area}/"], config)
    except BackupError as exc:
        if "directory not found" in str(exc).lower():  # nothing published yet
            return []
        raise
    return [line.rstrip("/") for line in out.splitlines() if line.strip()]


def download_set(name, folder, remote=None, config=None):
    """Download a published set `name` (or "latest") through the crypt remote into `folder`; returns its name.
    Only verified, published sets are ever offered; sets that failed verification stay in staging."""
    remote = remote if remote is not None else settings.BACKUP_REMOTE
    config = config if config is not None else os.environ.get("RCLONE_CONFIG", "")
    require_crypt(remote, config)
    published = sorted(n for n in list_sets(remote, config) if retention.parse_set_name(n))
    if name == "latest":
        if not published:
            raise BackupError("there are no verified backup sets on the remote")
        name = published[-1]
    elif name not in published:
        raise BackupError(f"'{name}' is not a verified backup set on the remote (available: "
                          f"{', '.join(published[-5:]) or 'none'})")
    rclone(["copy", f"{remote}sets/{name}", str(folder)], config)
    return name


# --- the run ---------------------------------------------------------------------------------

def _tz():
    try:
        return Contributor.objects.get(handle=settings.TWIN_CONTRIBUTOR).tzinfo
    except Contributor.DoesNotExist:
        return zoneinfo.ZoneInfo(settings.TIME_ZONE)


def drop_stray_scratch_databases():
    """A killed run can leave a twin_verify_*/twin_restore_check scratch database behind; they use disk
    on the live cluster, so every run begins by dropping them."""
    db = _db()
    with _admin_conn(db) as conn:
        names = [r[0] for r in conn.execute(
            "SELECT datname FROM pg_database WHERE datname LIKE 'twin\\_verify\\_%' OR datname = 'twin_restore_check'"
        ).fetchall()]
        for name in names:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    return names


def recover_interrupted(now=None):
    """Mark `running` attempts that never finished (process killed, machine off) as interrupted."""
    now = now or timezone.now()
    return BackupRun.objects.filter(status=BackupRun.Status.RUNNING, started_at__lt=now - STALE_AFTER).update(
        status=BackupRun.Status.FAILED, finished_at=now, error="Interrupted: the backup process stopped before it "
        "finished (machine off or restart). It will be retried.")


def run_backup(trigger=BackupRun.Trigger.MANUAL, now=None, remote=None, config=None, include_inbox=None):
    """Back up, verify, publish, prune. Returns the BackupRun (status ok or failed); never raises for backup errors.

    Verify and prune are separate outcomes: once the new set is verified and published it is a good recovery
    point even if deleting old sets later fails (that is recorded in `prune_error`, status stays ok).
    """
    now = now or timezone.now()
    remote = remote if remote is not None else settings.BACKUP_REMOTE
    config = config if config is not None else os.environ.get("RCLONE_CONFIG", "")
    recover_interrupted(now)
    drop_stray_scratch_databases()
    run = BackupRun.objects.create(started_at=now, trigger=trigger, set_name=retention.set_name(now))
    work = Path(tempfile.mkdtemp(prefix="twin-backup-"))
    try:
        if not remote or not remote.endswith((":", "/")):
            raise BackupError("BACKUP_REMOTE must name your crypt remote ending in ':' or '/', e.g. twin-crypt: "
                              "(set it in .env; see docs/OPERATIONS.md)")
        require_crypt(remote, config)  # before anything is built: readable files never go to a plain remote
        local = work / "set"
        manifest = build_set(local, now=now, include_inbox=include_inbox)
        run.manifest = manifest
        run.size_bytes = sum(f["bytes"] for f in manifest["files"])
        staging = f"{remote}staging/{run.set_name}"
        rclone(["copy", str(local), staging], config)
        run.uploaded = True
        run.save(update_fields=["manifest", "size_bytes", "uploaded"])

        fresh = work / "verify"
        rclone(["copy", staging, str(fresh)], config)  # a fresh download through crypt
        downloaded = json.loads((fresh / MANIFEST).read_text(encoding="utf-8"))
        if downloaded != manifest:
            raise BackupError("verify: the downloaded manifest differs from the one uploaded")
        check_files(fresh, downloaded)
        verify_restore(fresh, downloaded, scratch=f"twin_verify_{run.pk}")
        run.verified = True
        # Publish: only now does the set become visible to `latest` and retention.
        rclone(["moveto", staging, f"{remote}sets/{run.set_name}"], config)
        run.published = True
        run.status = BackupRun.Status.OK
        run.save(update_fields=["verified", "published", "status"])
    except Exception as exc:  # report every failure; earlier sets are left untouched
        run.status = BackupRun.Status.FAILED
        run.error = str(exc) if isinstance(exc, BackupError) else f"{type(exc).__name__}: {exc}"
    else:
        try:
            _, delete = retention.select(list_sets(remote, config), _tz())
            for name in delete:
                if name != run.set_name:
                    rclone(["purge", f"{remote}sets/{name}"], config)
                    run.pruned.append(name)
            # Leftovers of earlier failed runs (never published) are cleaned up too.
            for name in list_sets(remote, config, area="staging"):
                rclone(["purge", f"{remote}staging/{name}"], config)
        except Exception as exc:  # the new set is safe; say what was and was not deleted
            run.prune_error = (str(exc) if isinstance(exc, BackupError) else f"{type(exc).__name__}: {exc}")
    finally:
        shutil.rmtree(work, ignore_errors=True)
        run.finished_at = timezone.now()
        run.save()
    return run
