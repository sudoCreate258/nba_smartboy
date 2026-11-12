"""M6-T6: signing, updates and the tooling rules (R6, R7)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_signing_is_offline_with_the_owners_key_and_skips_without_it():
    text = read("scripts/sign-image.ps1")
    assert "alpine:3.20" in text and "apk add --no-cache cosign" in text
    assert "--tlog-upload=false" in text and "--insecure-ignore-tlog=true" in text  # nothing to a public log
    assert "SKIPPED: no signing key" in text and "exit 0" in text
    assert "REFUSED: COSIGN_KEY_DIR is inside the repository" in text
    assert "org.opencontainers.image.version" in text
    for ignored in ("cosign.key", "*.key", "dist/"):
        assert ignored in read(".gitignore").split()


def test_dependabot_targets_develop_weekly_for_pip_and_actions():
    text = read(".github/dependabot.yml")
    assert text.count("target-branch: develop") == 2 and text.count("interval: weekly") == 2
    assert "package-ecosystem: pip" in text and "package-ecosystem: github-actions" in text
    assert "main" not in text.replace("# Dependency update PRs (M6 R7): weekly, into develop only (never main).", "")


def test_update_script_pulls_rebuilds_migrates_and_runs_the_gate():
    text = read("scripts/update.ps1")
    # Review fix: validate the new image before anything running changes, then migrate, then switch.
    steps = ["git status --porcelain", "git pull --ff-only", "docker tag twin-web:local twin-web:previous",
             "docker compose build --pull web", "scripts/ci-local.ps1", "docker compose run --rm -T web python manage.py migrate",
             "up -d --no-build @running"]
    positions = [text.index(s) for s in steps]
    assert positions == sorted(positions)
    assert '"web-https"' in text and "--profile\", \"https\"" in text  # the HTTPS service is updated too
    compose = read("docker-compose.yml")
    assert compose.count("image: twin-web:local") == 3  # one shared image for web, web-https and backup


def test_the_ca_key_stays_out_of_every_container():
    """Review fix: the whole repository is mounted at /app, so the CA lives outside it and certs/ is masked."""
    compose = read("docker-compose.yml")
    assert compose.count("- /app/certs") == compose.count("- .:/app") == 3
    ps1 = read("scripts/lan-cert.ps1")
    assert ".twin-ca" in ps1 and "CaDir is inside the repository" in ps1
    assert "./certs/server:/run/secrets/tls:ro" in compose and "certs/ca" not in compose


def test_no_third_party_images_and_no_docker_socket_anywhere():
    import re
    images = set()
    for path in ["docker-compose.yml", "Dockerfile", ".github/workflows/ci.yml"] + \
            [str(p.relative_to(ROOT)) for p in (ROOT / "scripts").glob("*")]:
        text = read(path)
        assert "docker.sock" not in text, path
        images |= set(re.findall(r"(?:image:|FROM|--from=|alpine:|postgres:|python:|node:)\s*([a-z0-9./:-]+)", text))
    namespaced = {i for i in images if "/" in i}
    assert not namespaced, namespaced
