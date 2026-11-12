# SPDX-License-Identifier: AGPL-3.0-or-later
# Local CI gate: the same checks as GitHub Actions, run in Docker.
#   pytest -q  and  makemigrations --check --dry-run
# Usage: powershell -File scripts/ci-local.ps1   (needs Docker Desktop and a .env)
# Writes the result (commit, date, test summary) to .agents/ci-local-last.txt.
$ErrorActionPreference = "Stop"
Set-Location (git rev-parse --show-toplevel)

$commit = git rev-parse --short HEAD
git diff --quiet HEAD --
$dirty = if ($LASTEXITCODE -ne 0) { " (with uncommitted changes)" } else { "" }
Write-Output "Local CI gate on $commit$dirty"

$ErrorActionPreference = "Continue"
$out = docker compose run --rm -T web sh -c "pytest -q -p no:cacheprovider && python manage.py makemigrations --check --dry-run" 2>&1 | ForEach-Object { "$_" }
$status = $LASTEXITCODE
$out | Select-Object -Last 5 | Write-Output
$summary = ($out | Select-String -Pattern "\d+ (passed|failed)" | Select-Object -Last 1).Line

New-Item -ItemType Directory -Force .agents | Out-Null
$result = if ($status -eq 0) { "PASS" } else { "FAIL" }
$stamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
# No BOM (PowerShell 5's -Encoding utf8 adds one), so the pre-push hook can match the line.
[System.IO.File]::WriteAllText((Join-Path (Get-Location) ".agents/ci-local-last.txt"), "$result $stamp $commit${dirty}: $summary`n")
Write-Output "Local CI gate: $result ($summary)"
exit $status
