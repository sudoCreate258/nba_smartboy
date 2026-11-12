# SPDX-License-Identifier: AGPL-3.0-or-later
# Update this instance (M6 R7): pull the current branch (fast-forward only), rebuild the image with the
# latest Debian security updates, restart, apply migrations, and run the local gate.
# Usage: powershell -File scripts/update.ps1   (stops at the first failing step; your data is untouched
# by everything except `migrate`, which only adds)
$ErrorActionPreference = "Stop"
Set-Location (git rev-parse --show-toplevel)

function Step([string]$name, [scriptblock]$run) {
    Write-Output "== $name"
    & $run
    if ($LASTEXITCODE -ne 0) { Write-Output "update: '$name' failed (exit $LASTEXITCODE); stopped here."; exit 1 }
}

git diff --quiet HEAD --
if ($LASTEXITCODE -ne 0) { Write-Output "update: you have uncommitted changes; commit or stash them first."; exit 1 }
Step "pull (fast-forward only)" { git pull --ff-only }
Step "rebuild the image" { docker compose build --pull web }
Step "restart" { docker compose up -d web }
Step "migrate" { docker compose exec -T web python manage.py migrate }
Step "local gate" { powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ci-local.ps1 }
Write-Output "update: done."
