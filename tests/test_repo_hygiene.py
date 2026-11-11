"""Public-repo hygiene (planner 013): workflow permissions, local CI gate files, synthetic fixtures."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))


def test_workflows_are_read_only_and_never_use_pull_request_target():
    assert WORKFLOWS
    for path in WORKFLOWS:
        text = path.read_text(encoding="utf-8")
        assert "pull_request_target" not in text, path.name
        data = yaml.safe_load(text)
        assert data.get("permissions") == {"contents": "read"}, path.name
        for job in data["jobs"].values():
            assert job.get("permissions", {"contents": "read"}) == {"contents": "read"}, path.name


def test_local_ci_gate_files_exist():
    for name in ("ci-local.sh", "ci-local.ps1", "pre-push", "install-hooks.ps1"):
        assert (ROOT / "scripts" / name).is_file(), name
    assert "makemigrations --check --dry-run" in (ROOT / "scripts" / "ci-local.sh").read_text(encoding="utf-8")


def test_fixtures_use_synthetic_body_values():
    text = (ROOT / "tests" / "fixtures" / "sample_snapshots.yaml").read_text(encoding="utf-8")
    assert "weight_kg: 70.0" in text and "body_fat_pct: 15.0" in text
