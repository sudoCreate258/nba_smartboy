"""M4.5-T3: backup round trip through a local rclone crypt remote (R1, R2, R7, R8, R11). No network."""
import datetime
import json
import subprocess

import pytest

from backup import retention, runner
from backup.models import BackupRun
from core.models import Contributor
from tests.backup_helpers import crypt_remote
from tests.test_export import seed

pytestmark = pytest.mark.django_db(transaction=True, serialized_rollback=True)
UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 11, 12, 7, 30, tzinfo=UTC)  # 02:30 New York


@pytest.fixture
def remote(tmp_path):
    return crypt_remote(tmp_path)


@pytest.fixture
def mike():
    m = Contributor.objects.get(handle="mike")
    seed(m)
    return m


def rc(config, *args):
    return subprocess.run(["rclone", "--config", str(config), *args], capture_output=True, text=True, check=True).stdout


def test_round_trip_backup_and_verify(mike, remote, tmp_path):
    config, name, store = remote
    run = runner.run_backup(BackupRun.Trigger.MANUAL, now=NOW, remote=name, config=config)
    assert run.status == "ok", run.error
    assert run.uploaded and run.verified and run.set_name == "2026-11-12T073000Z"
    m = run.manifest
    assert m["format"] == "twin-backup" and m["app_version"] and m["git_commit"]
    assert {f["name"] for f in m["files"]} == {"twin.dump", "my-data-mike.jsonl"}
    assert all(len(f["sha256"]) == 64 and f["bytes"] > 0 for f in m["files"])
    assert m["record_counts"]["discomfort_check"] == 1 and m["record_counts"]["training_set"] == 2
    assert not m["includes_inbox"] and run.size_bytes == sum(f["bytes"] for f in m["files"])
    # Through the crypt remote the set is readable ...
    assert rc(config, "lsf", f"{name}sets/2026-11-12T073000Z/").split() == ["manifest.json", "my-data-mike.jsonl",
                                                                            "twin.dump"]
    # ... while the bytes on the backing store have encrypted names and contents.
    stored = [p for p in store.rglob("*") if p.is_file()]
    assert len(stored) == 3
    for p in stored:
        assert not any(word in str(p) for word in ("manifest", "my-data", "twin.dump", "sets"))
        data = p.read_bytes()
        assert b"nymbus-jsonl" not in data and b"twin-backup" not in data and b"PGDMP" not in data


def test_scratch_database_is_dropped(mike, remote):
    config, name, _ = remote
    run = runner.run_backup(now=NOW, remote=name, config=config)
    db = runner._db()
    with runner._admin_conn(db) as conn:
        left = conn.execute("SELECT datname FROM pg_database WHERE datname LIKE 'twin_verify_%'").fetchall()
    assert run.status == "ok" and left == []


def test_inbox_is_opt_in(mike, remote, tmp_path, settings):
    config, name, _ = remote
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "training.csv").write_text("started_at,order\n", encoding="utf-8")
    (inbox / ".gitkeep").write_text("", encoding="utf-8")
    settings.BACKUP_INBOX_DIR = inbox
    run = runner.run_backup(now=NOW, remote=name, config=config, include_inbox=True)
    assert run.status == "ok", run.error and run.manifest["includes_inbox"]
    assert "inbox.tar.gz" in {f["name"] for f in run.manifest["files"]}


def test_manifest_hash_mismatch_is_detected(tmp_path, mike):
    folder = tmp_path / "set"
    manifest = runner.build_set(folder, now=NOW, include_inbox=False)
    runner.check_files(folder, manifest)
    with open(folder / "my-data-mike.jsonl", "a", encoding="utf-8") as fh:
        fh.write("\n")
    with pytest.raises(runner.BackupError, match="my-data-mike.jsonl does not match its SHA-256"):
        runner.check_files(folder, manifest)
    (folder / "my-data-mike.jsonl").unlink()
    with pytest.raises(runner.BackupError, match="my-data-mike.jsonl is missing"):
        runner.check_files(folder, manifest)


def test_tampered_remote_set_fails_verify_and_keeps_old_sets(mike, remote, monkeypatch):
    config, name, store = remote
    first = runner.run_backup(now=NOW - datetime.timedelta(days=1), remote=name, config=config)
    assert first.status == "ok"
    real_rclone = runner.rclone
    before = {p for p in store.rglob("*") if p.is_file()}

    def corrupt_after_upload(args, cfg):
        out = real_rclone(args, cfg)
        if args[0] == "copy" and args[2].startswith(name):  # right after the upload: damage the new dump
            new = [p for p in store.rglob("*") if p.is_file() and p not in before]
            target = max(new, key=lambda p: p.stat().st_size)
            data = bytearray(target.read_bytes())
            data[len(data) // 2] ^= 0xFF
            target.write_bytes(bytes(data))
        return out

    monkeypatch.setattr(runner, "rclone", corrupt_after_upload)
    second = runner.run_backup(now=NOW, remote=name, config=config)
    assert second.status == "failed" and second.uploaded and not second.verified and second.error
    assert second.pruned == []
    assert retention.set_name(NOW - datetime.timedelta(days=1)) in runner.list_sets(name, config)


def test_verify_compares_restored_cids_with_the_export(mike, remote, tmp_path):
    folder = tmp_path / "set"
    manifest = runner.build_set(folder, now=NOW, include_inbox=False)
    runner.verify_restore(folder, manifest, scratch="twin_verify_test_ok")
    lines = (folder / "my-data-mike.jsonl").read_text(encoding="utf-8").splitlines()
    record = next(i for i, line in enumerate(lines) if json.loads(line)["type"] == "record")
    lines.pop(record)  # the export no longer matches the dump
    (folder / "my-data-mike.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(runner.BackupError, match="CIDs in the restored dump differ"):
        runner.verify_restore(folder, manifest, scratch="twin_verify_test_bad")


def test_retention_prunes_only_after_a_verified_set(mike, remote):
    config, name, _ = remote
    for day in range(9, 0, -1):  # nine earlier nightly sets
        assert runner.run_backup(now=NOW - datetime.timedelta(days=day), remote=name, config=config).status == "ok"
    latest = runner.run_backup(now=NOW, remote=name, config=config)
    assert latest.status == "ok"
    sets = runner.list_sets(name, config)
    assert latest.set_name in sets and len(sets) <= 7 + 4
    assert retention.set_name(NOW - datetime.timedelta(days=9)) not in sets  # the oldest was pruned
    assert set(latest.pruned) and not set(latest.pruned) & set(sets)


@pytest.mark.parametrize("remote_name,config_ok,match", [
    ("", True, "BACKUP_REMOTE"), ("vault", True, "BACKUP_REMOTE"), ("vault:", False, "not configured"),
])
def test_misconfiguration_is_a_failed_run_with_a_clear_reason(mike, remote, remote_name, config_ok, match):
    config, _, _ = remote
    run = runner.run_backup(now=NOW, remote=remote_name, config=config if config_ok else "/nope/rclone.conf")
    assert run.status == "failed" and match in run.error and not run.uploaded
