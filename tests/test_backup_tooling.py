"""M4.5-T1: backup tooling in the image, Compose profile, and secret hygiene (R3, R4, R6)."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
# Never part of the repository content (gitignored or generated). `.kiro` is tracked, so it IS scanned.
SKIP_DIRS = {".git", ".agents", ".planner", ".pytest_cache", "__pycache__", "staticfiles", "backups",
             "backup-not-configured"}
SECRET_PATTERNS = [
    re.compile(r"(?m)^\s*type\s*=\s*crypt\s*$"),                        # an rclone crypt remote section
    re.compile(r"(?m)^\s*password2?\s*=\s*\S{8,}"),                     # rclone (obscured) crypt password / salt
    re.compile(r'"(?:access|refresh)_token"\s*:\s*"[^"]{8,}'),          # OAuth tokens (rclone drive config)
    re.compile(r"(?m)^\s*token\s*=\s*\{"),                              # rclone token line
]


def repo_files():
    for path in ROOT.rglob("*"):
        rel = path.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in rel.parts) or not path.is_file():
            continue
        if rel.parts[:2] == ("data", "inbox"):
            continue
        yield path


def test_no_rclone_config_or_crypt_secret_in_the_repository():
    names = [p for p in repo_files() if p.name == "rclone.conf" or p.name.endswith(".rclone.conf")]
    assert names == []
    for path in repo_files():
        if path.suffix in {".png", ".pyc"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in SECRET_PATTERNS:
            assert not pattern.search(text), f"{path.relative_to(ROOT)} looks like it holds an rclone secret"


def test_gitignore_covers_rclone_config_and_backups():
    lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    for entry in ("rclone.conf", "*.rclone.conf", "backups/", ".env"):
        assert entry in lines


def test_the_hygiene_check_catches_a_crypt_config():
    sample = "[twin-crypt]\ntype = crypt\nremote = gdrive:twin\npassword = abcdefghijklmnop\n"
    assert any(p.search(sample) for p in SECRET_PATTERNS)


def test_the_scan_covers_the_specification_files():
    """Review: a secret pasted into a tracked spec must fail the gate, so .kiro must be scanned."""
    scanned = {p.relative_to(ROOT).parts[0] for p in repo_files()}
    assert ".kiro" in scanned and "docs" in scanned and "tests" in scanned
    spec = ROOT / ".kiro" / "specs" / "m4-5-encrypted-backup" / "requirements.md"
    assert spec in set(repo_files())


def test_backup_service_is_an_opt_in_profile_with_a_read_only_config():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    svc = compose["services"]["backup"]
    assert svc["profiles"] == ["backup"] and svc["command"] == "python manage.py backup_loop"
    assert any(v.endswith(":/run/secrets/rclone.conf:ro") and "RCLONE_CONFIG_HOST" in v for v in svc["volumes"])
    assert svc["environment"]["RCLONE_CONFIG"] == "/run/secrets/rclone.conf"
    assert "RCLONE_CONFIG" not in str(compose["services"]["web"])  # the web service never sees the config
    assert "postgres:16" in (ROOT / "Dockerfile").read_text(encoding="utf-8")  # pg tools from the official image


@pytest.mark.parametrize("tool,expected", [("pg_dump", "(PostgreSQL) 16."), ("pg_restore", "(PostgreSQL) 16."),
                                           ("rclone", "rclone v")])
def test_tools_are_installed(tool, expected):
    assert shutil.which(tool), f"{tool} missing from the image"
    out = subprocess.run([tool, "--version" if tool != "rclone" else "version"], capture_output=True, text=True)
    assert expected in out.stdout
