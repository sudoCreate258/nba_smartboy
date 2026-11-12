"""Fixes from the PR #11 (M4.5) semantic review."""
import datetime
import json
import subprocess
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection

from backup import retention, runner
from backup.management.commands import backup_loop
from backup.models import BackupRun
from backup.status import backup_status
from core.models import Contributor, DiscomfortCheck, Supersession
from core.services.records import save_record
from tests.backup_helpers import crypt_remote, obscure
from tests.test_export import seed

pytestmark = pytest.mark.django_db(transaction=True)
UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 11, 12, 7, 30, tzinfo=UTC)
DAY = datetime.timedelta(days=1)


@pytest.fixture(scope="module", autouse=True)
def restore_migration_data(django_db_blocker):
    yield
    with django_db_blocker.unblock():
        Contributor.objects.get_or_create(handle="mike", defaults={"timezone": "America/New_York"})


@pytest.fixture
def mike():
    m, _ = Contributor.objects.get_or_create(handle="mike", defaults={"timezone": "America/New_York"})
    seed(m)
    return m


@pytest.fixture
def remote(tmp_path):
    return crypt_remote(tmp_path)


def rc(config, *args):
    return subprocess.run(["rclone", "--config", str(config), *args], capture_output=True, text=True, check=True).stdout


def plain_config(tmp_path):
    """A config with a PLAIN local remote, an alias to it, and an alias to a crypt remote."""
    store = tmp_path / "plain-store"
    store.mkdir()
    config, crypt, _ = crypt_remote(tmp_path)
    with open(config, "a", encoding="utf-8") as fh:
        fh.write(f"\n[plain]\ntype = local\n\n[plainalias]\ntype = alias\nremote = plain:{store}\n"
                 "\n[cryptalias]\ntype = alias\nremote = vault:\n")
    return config, store


# --- 1. crypt is enforced -------------------------------------------------------------------

def test_plain_remote_is_refused_and_nothing_is_written(mike, tmp_path):
    config, store = plain_config(tmp_path)
    for name in ("plain:" + str(store) + "/", "plainalias:", "store:" + str(store) + "/", "nonexistent:"):
        run = runner.run_backup(now=NOW, remote=name, config=config)
        assert run.status == "failed" and not run.uploaded
        assert "not crypt" in run.error or "not a remote in the rclone config" in run.error
    assert list(store.rglob("*")) == []  # not a single readable byte went to the plain remote


def test_alias_to_crypt_is_accepted(mike, tmp_path):
    config, _ = plain_config(tmp_path)
    run = runner.run_backup(now=NOW, remote="cryptalias:", config=config)
    assert run.status == "ok", run.error


def test_restore_refuses_a_plain_remote(tmp_path):
    config, store = plain_config(tmp_path)
    with pytest.raises(runner.BackupError, match="not crypt"):
        runner.download_set("latest", tmp_path / "x", remote="plainalias:", config=config)


# --- 2. failed sets are never recovery points ------------------------------------------------

def test_failed_set_stays_in_staging_and_cannot_be_restored_or_pruned_against(mike, remote, monkeypatch, tmp_path):
    config, name, store = remote
    good = runner.run_backup(now=NOW - 2 * DAY, remote=name, config=config)
    assert good.status == "ok" and good.published
    real = runner.rclone
    published = {p for p in store.rglob("*") if p.is_file()}

    def corrupt_upload(args, cfg):
        out = real(args, cfg)
        if args[0] == "copy" and "staging/" in args[2] and "/staging" not in args[1]:
            # A file this upload added (not by mtime: the VM clock can step back, M6).
            files = sorted(p for p in store.rglob("*") if p.is_file() and p not in published)
            newest = max(files, key=lambda p: p.stat().st_size)
            data = bytearray(newest.read_bytes())
            data[len(data) // 2] ^= 0xFF
            newest.write_bytes(bytes(data))
        return out

    monkeypatch.setattr(runner, "rclone", corrupt_upload)
    bad = runner.run_backup(now=NOW - DAY, remote=name, config=config)
    monkeypatch.setattr(runner, "rclone", real)
    assert bad.status == "failed" and bad.uploaded and not bad.published and not bad.verified
    assert runner.list_sets(name, config) == [good.set_name]  # the failed set is not published
    assert bad.set_name in runner.list_sets(name, config, area="staging")
    # `latest` restores the verified set, never the failed one.
    folder = tmp_path / "dl"
    assert runner.download_set("latest", folder, remote=name, config=config) == good.set_name
    with pytest.raises(runner.BackupError, match="not a verified backup set"):
        runner.download_set(bad.set_name, tmp_path / "dl2", remote=name, config=config)
    # A later good run publishes, keeps the verified history and cleans the leftover staging set.
    later = runner.run_backup(now=NOW, remote=name, config=config)
    assert later.status == "ok"
    assert runner.list_sets(name, config) == sorted([good.set_name, later.set_name])
    assert runner.list_sets(name, config, area="staging") == []


# --- 3. one snapshot, corrections checked ----------------------------------------------------------

def test_dump_and_exports_share_one_snapshot(mike, remote, monkeypatch):
    """A record written after the snapshot is taken (during the dump) is in neither file."""
    config, name, _ = remote
    real_run = runner._run
    late = {}

    def write_during_dump(cmd, env):
        if cmd[0] == "pg_dump" and not late:
            assert "--snapshot" in cmd
            # Another connection commits a new record while the dump runs.
            from django.db import connections
            other = connections.create_connection("default")
            try:
                other.cursor().execute(
                    "INSERT INTO core_discomfortcheck (cid, contributor_id, created_at, at, area, score, trigger, "
                    "countermove, sharp_or_numb, notes) SELECT 'bafkreilate', id, now(), now(), 'neck', 1, 'other', "
                    "'none', false, '' FROM core_contributor LIMIT 1")
                other.commit() if not other.get_autocommit() else None
            finally:
                other.close()
            late["done"] = True
        return real_run(cmd, env)

    monkeypatch.setattr(runner, "_run", write_during_dump)
    run = runner.run_backup(now=NOW, remote=name, config=config)
    assert late and run.status == "ok", run.error  # consistent: the late record is in neither the dump nor the export
    assert "bafkreilate" not in json.dumps(run.manifest)
    assert DiscomfortCheck.objects.filter(cid="bafkreilate").exists()  # it exists now, and goes in the next backup


def test_supersession_difference_is_detected(mike, tmp_path):
    folder = tmp_path / "set"
    manifest = runner.build_set(folder, now=NOW, include_inbox=False)
    assert manifest["record_counts"]["supersession"] == Supersession.objects.count() == 4
    export = folder / "my-data-mike.jsonl"
    lines = export.read_text(encoding="utf-8").splitlines()
    sup = next(i for i, line in enumerate(lines) if json.loads(line)["type"] == "supersession")
    del lines[sup]  # the export drops one correction the dump still has
    export.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(runner.BackupError, match="corrections .* differ from the export"):
        runner.verify_restore(folder, manifest, scratch="twin_verify_sup")


# --- 4. restore proves first, replaces in one transaction ----------------------------------------------

def test_restore_checks_in_scratch_first_and_leaves_live_data_if_the_set_is_bad(mike, remote, tmp_path, monkeypatch):
    config, name, _ = remote
    monkeypatch.setenv("RCLONE_CONFIG", str(config))
    from django.conf import settings
    settings.BACKUP_REMOTE = name
    assert runner.run_backup(now=NOW).status == "ok"
    before = sorted(DiscomfortCheck.objects.values_list("cid", flat=True))
    # A set whose dump and export disagree but whose hashes are consistent (as if built wrongly).
    folder = tmp_path / "bad-set"
    manifest = runner.build_set(folder, now=NOW, include_inbox=False)
    export = folder / "my-data-mike.jsonl"
    lines = export.read_text(encoding="utf-8").splitlines()
    export.write_text("\n".join(l for l in lines if '"kind": "discomfort_check"' not in l) + "\n", encoding="utf-8")
    entry = next(f for f in manifest["files"] if f["name"] == "my-data-mike.jsonl")
    entry["bytes"], entry["sha256"] = export.stat().st_size, runner.sha256(export)
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(CommandError, match="Restore failed: verify: discomfort_check CIDs"):
        call_command("restore_backup", str(folder), "--yes", stdout=StringIO())
    assert sorted(DiscomfortCheck.objects.values_list("cid", flat=True)) == before  # live data untouched


def test_restore_is_a_single_transaction(monkeypatch):
    seen = {}
    monkeypatch.setattr(runner, "_run", lambda cmd, env: seen.update(cmd=cmd))
    runner.restore_dump("somedb", "x.dump", clean=True)
    assert "--single-transaction" in seen["cmd"] and "--clean" in seen["cmd"]
    runner.restore_dump("somedb", "x.dump")
    assert "--single-transaction" not in seen["cmd"]


def test_restore_asks_before_replacing_any_data_not_only_records(mike, remote, monkeypatch):
    config, name, _ = remote
    monkeypatch.setenv("RCLONE_CONFIG", str(config))
    from django.conf import settings
    from django.contrib.auth import get_user_model
    settings.BACKUP_REMOTE = name
    assert runner.run_backup(now=NOW).status == "ok"
    for model in (DiscomfortCheck,):
        pass
    with connection.cursor() as cur:
        cur.execute("TRUNCATE core_trainingset, core_trainingsession, core_reset, core_weeklycheck, core_workblock, "
                    "core_discomfortcheck, core_probesession, core_dailysnapshot, core_supersession")
    get_user_model().objects.create_user("owner", password="a-long-test-password")  # live data that is not a record
    with pytest.raises(CommandError, match="already has data .*auth_user"):
        call_command("restore_backup", "--set", "latest", stdout=StringIO())


# --- 5. interrupted attempts ---------------------------------------------------------------------

def test_interrupted_attempt_is_recovered_retried_and_visible(mike, monkeypatch):
    stuck = BackupRun.objects.create(started_at=NOW - datetime.timedelta(hours=7), trigger="nightly",
                                     status="running", set_name="x")
    s = backup_status(NOW)
    assert s["level"] == "red" and "Interrupted" in s["detail"]  # visible even before recovery
    calls = []
    monkeypatch.setattr(backup_loop, "run_backup", lambda trigger, now=None, **kw: calls.append(now) or stuck)
    ran, _ = backup_loop.check_once(NOW)
    stuck.refresh_from_db()
    assert ran and stuck.status == "failed" and stuck.error.startswith("Interrupted")  # recovered, then retried
    # A run that is genuinely still going (started minutes ago) is left alone.
    fresh = BackupRun.objects.create(started_at=NOW - datetime.timedelta(minutes=5), trigger="nightly",
                                     status="running")
    runner.recover_interrupted(NOW)
    fresh.refresh_from_db()
    assert fresh.status == "running"


# --- 6. prune failures are not verify failures ------------------------------------------------------

def test_prune_failure_keeps_the_new_set_good(mike, remote, monkeypatch):
    config, name, _ = remote
    for day in range(9, 0, -1):
        assert runner.run_backup(now=NOW - day * DAY, remote=name, config=config).status == "ok"
    real = runner.rclone

    def purge_fails(args, cfg):
        if args[0] == "purge" and "/sets/" in args[1].replace(":sets/", "/sets/"):
            raise runner.BackupError("rclone purge failed: remote unreachable")
        return real(args, cfg)

    monkeypatch.setattr(runner, "rclone", purge_fails)
    run = runner.run_backup(now=NOW, remote=name, config=config)
    assert run.status == "ok" and run.verified and run.published
    assert "remote unreachable" in run.prune_error
    s = backup_status(NOW)
    assert s["level"] == "ok" and "could not be deleted" in s["detail"]
    out = StringIO()
    from backup.management.commands.backup_now import describe
    assert "WARNING: deleting old sets failed" in describe(run) and "the new set is safe" in describe(run)


def test_failure_stage_names():
    from backup.status import failure_stage
    assert failure_stage(BackupRun(uploaded=False)) == "backup"
    assert failure_stage(BackupRun(uploaded=True, verified=False)) == "verify"
    assert failure_stage(BackupRun(uploaded=True, verified=True)) == "publish"


# --- second review: crypt options, config location, schema, disk space, CI ----------------------

def crypt_with(tmp_path, extra):
    config, name, store = crypt_remote(tmp_path)
    text = config.read_text(encoding="utf-8")
    config.write_text(text.replace("[vault]\ntype = crypt", "[vault]\ntype = crypt\n" + extra), encoding="utf-8")
    return config, name, store


@pytest.mark.parametrize("option,match", [
    ("no_data_encryption = true", "no_data_encryption"),
    ("filename_encryption = off", "filename_encryption = off"),
])
def test_crypt_remote_with_encryption_switched_off_is_refused(mike, tmp_path, option, match):
    config, name, store = crypt_with(tmp_path, option)
    run = runner.run_backup(now=NOW, remote=name, config=config)
    assert run.status == "failed" and match in run.error and not run.uploaded
    assert [p for p in store.rglob("*") if p.is_file()] == []


def test_crypt_remote_without_a_password_is_refused(mike, tmp_path):
    config, name, _ = crypt_remote(tmp_path)
    lines = [line for line in config.read_text(encoding="utf-8").splitlines() if not line.startswith("password =")]
    config.write_text("\n".join(lines) + "\n", encoding="utf-8")
    run = runner.run_backup(now=NOW, remote=name, config=config)
    assert run.status == "failed" and "no password" in run.error


def test_config_inside_the_repository_is_refused(mike, remote, tmp_path):
    from django.conf import settings
    config, name, _ = remote
    inside = settings.BASE_DIR / "data" / "inbox" / "oops-rclone.conf"
    inside.write_bytes(config.read_bytes())
    try:
        run = runner.run_backup(now=NOW, remote=name, config=inside)
        assert run.status == "failed" and "inside the repository folder" in run.error
    finally:
        inside.unlink()


def test_restore_refuses_a_set_from_newer_code(mike, remote, tmp_path, monkeypatch):
    config, name, _ = remote
    monkeypatch.setenv("RCLONE_CONFIG", str(config))
    from django.conf import settings
    settings.BACKUP_REMOTE = name
    folder = tmp_path / "set"
    manifest = runner.build_set(folder, now=NOW, include_inbox=False)
    # The helper itself is tested against a real scratch database below; here: the command refuses.
    monkeypatch.setattr(runner, "newer_migrations", lambda dbname: ["core.0999_future", "core.1000_more"])
    before = sorted(DiscomfortCheck.objects.values_list("cid", flat=True))
    with pytest.raises(CommandError, match="made by newer code .*core\\.0999_future"):
        call_command("restore_backup", str(folder), "--yes", stdout=StringIO())
    assert sorted(DiscomfortCheck.objects.values_list("cid", flat=True)) == before  # refused before replacing


def test_newer_migrations_helper_sees_only_unknown_migrations(mike, tmp_path):
    folder = tmp_path / "set"
    runner.build_set(folder, now=NOW, include_inbox=False)
    db = runner._db()
    with runner._admin_conn(db) as conn:
        conn.execute('DROP DATABASE IF EXISTS "twin_schema_probe" WITH (FORCE)')
        conn.execute('CREATE DATABASE "twin_schema_probe"')
    try:
        runner.restore_dump("twin_schema_probe", folder / runner.DUMP)
        assert runner.newer_migrations("twin_schema_probe") == []  # same code: nothing newer
        import psycopg
        with psycopg.connect(host=db["host"], port=db["port"], user=db["user"], password=db["password"],
                             dbname="twin_schema_probe", autocommit=True) as conn:
            conn.execute("INSERT INTO django_migrations (app, name, applied) VALUES ('core', '9999_future', now())")
        assert runner.newer_migrations("twin_schema_probe") == ["core.9999_future"]
    finally:
        with runner._admin_conn(db) as conn:
            conn.execute('DROP DATABASE IF EXISTS "twin_schema_probe" WITH (FORCE)')


def test_not_enough_disk_space_stops_the_scratch_restore(mike, tmp_path, monkeypatch):
    folder = tmp_path / "set"
    manifest = runner.build_set(folder, now=NOW, include_inbox=False)
    assert runner.free_space_ok(1)  # the real check passes on a machine with space
    monkeypatch.setattr(runner, "free_space_ok", lambda needed: False)
    with pytest.raises(runner.BackupError, match="not enough free disk space"):
        runner.verify_restore(folder, manifest, scratch="twin_verify_space")


def test_ci_workflow_installs_the_backup_tooling():
    """Review: GitHub CI must have rclone and the PostgreSQL 16 client, or the backup tests cannot run there."""
    from pathlib import Path
    text = (Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "postgresql-client-16" in text and "rclone" in text
    assert "pg_dump --version && pg_restore --version && rclone version" in text  # fail fast if missing


# --- bounded retry, stray scratch databases ------------------------------------------------------

def test_failed_attempt_is_retried_inside_the_window_a_bounded_number_of_times():
    import zoneinfo
    from backup import schedule
    tz = zoneinfo.ZoneInfo("America/New_York")
    w = schedule.parse_window("02:00-05:00")
    first = datetime.datetime(2026, 11, 12, 2, 5, tzinfo=tz)
    soon = first + datetime.timedelta(minutes=5)
    later = first + datetime.timedelta(minutes=21)
    assert schedule.is_due(soon, first, w, tz, failures_tonight=1, last_failed=True)[0] is False  # not hammering
    due, reason = schedule.is_due(later, first, w, tz, failures_tonight=1, last_failed=True)
    assert due and reason.startswith("retry 2 of 2")
    # The third failure ends the night; success never retries; outside the window a failure is not retried.
    assert schedule.is_due(later, first, w, tz, failures_tonight=3, last_failed=True)[0] is False
    assert schedule.is_due(later, first, w, tz, failures_tonight=0, last_failed=False)[0] is False
    out_of_window = datetime.datetime(2026, 11, 12, 6, 0, tzinfo=tz)
    assert schedule.is_due(out_of_window, first, w, tz, failures_tonight=1, last_failed=True)[0] is False


def test_loop_retries_a_failed_night_then_stops(monkeypatch, db):
    calls = []

    def failing(trigger, now=None, **kw):
        calls.append(now)
        return BackupRun.objects.create(started_at=now, finished_at=now, trigger=trigger, status="failed",
                                        set_name="x", error="rclone copy failed: timeout")

    monkeypatch.setattr(backup_loop, "run_backup", failing)
    t = NOW  # 02:30 New York, inside the window
    results = []
    for step in range(6):
        results.append(backup_loop.check_once(t + datetime.timedelta(minutes=25 * step))[0])
    assert results[:3] == [True, True, True]          # first attempt + two retries (25 min apart)
    assert results[3:] == [False, False, False]        # then the night is over
    assert len(calls) == 3


def test_stray_scratch_databases_are_dropped_at_the_start_of_a_run(mike, remote):
    config, name, _ = remote
    db = runner._db()
    with runner._admin_conn(db) as conn:
        conn.execute('CREATE DATABASE "twin_verify_999"')
        conn.execute('CREATE DATABASE "twin_restore_check"')
    run = runner.run_backup(now=NOW, remote=name, config=config)
    assert run.status == "ok", run.error
    with runner._admin_conn(db) as conn:
        left = [r[0] for r in conn.execute(
            "SELECT datname FROM pg_database WHERE datname LIKE 'twin\\_verify\\_%' OR datname = 'twin_restore_check'"
        ).fetchall()]
    assert left == []


def test_the_runbook_does_not_hand_out_yes_for_a_database_with_data():
    from pathlib import Path
    text = (Path(__file__).resolve().parent.parent / "docs" / "OPERATIONS.md").read_text(encoding="utf-8")
    fresh = text.split("### Restore onto a fresh machine")[1].split("## Running reports")[0]
    command = next(line for line in fresh.splitlines() if "restore_backup --set latest" in line and "docker" in line)
    assert "--yes" not in command  # an empty database needs no confirmation
    assert "--yes" in fresh  # but it is explained for the replace-existing-data case


# --- found by running the documented fresh-machine steps for real -------------------------------------

def test_a_freshly_migrated_database_counts_as_empty_for_restore():
    from backup.management.commands.restore_backup import live_row_counts
    Contributor.objects.get_or_create(handle="mike", defaults={"timezone": "America/New_York"})
    assert list(Contributor.objects.values_list("handle", flat=True)) == ["mike"]
    assert live_row_counts()["core_contributor"] == 0  # the seeded row is not data
    Contributor.objects.create(handle="sam")
    assert live_row_counts()["core_contributor"] == 2  # a real second contributor is


def test_sets_from_before_the_supersession_count_still_verify(mike, tmp_path):
    """The first M4.5 sets had no supersession count in the manifest; they must still restore."""
    folder = tmp_path / "set"
    manifest = runner.build_set(folder, now=NOW, include_inbox=False)
    manifest["record_counts"].pop("supersession")
    assert runner.verify_restore(folder, manifest, scratch="twin_verify_oldformat") == 14
