# SPDX-License-Identifier: AGPL-3.0-or-later
# One command to start the twin (MVP, 025 R1): build, start, migrate, seed the DEMO profile, print URLs.
# Usage: powershell -File scripts/up.ps1    (needs Docker Desktop and a .env; see docs/QUICKSTART.md)
$ErrorActionPreference = "Stop"
Set-Location (git rev-parse --show-toplevel)
if (-not (Test-Path .env)) { Write-Output "up: no .env yet. Copy .env.example to .env and set your own values (docs/QUICKSTART.md)."; exit 1 }

function Step([string]$name, [scriptblock]$run) {
    Write-Output "== $name"
    & $run
    if ($LASTEXITCODE -ne 0) { Write-Output "up: '$name' failed (exit $LASTEXITCODE)."; exit 1 }
}

# Only this one setting is read from .env, for the phone URL; nothing else is printed.
$httpsHost = (Select-String -Path .env -Pattern '^\s*TWIN_HTTPS_HOST\s*=\s*(\S+)' | Select-Object -First 1)
$httpsHost = if ($httpsHost) { $httpsHost.Matches[0].Groups[1].Value } else { "" }
$https = $httpsHost -and (Test-Path "certs/server/server.crt")

Step "build" { docker compose build web }
Step "start" { docker compose up -d --no-build web }
Step "migrate" { docker compose exec -T web python manage.py migrate --verbosity 0 }
Step "seed the DEMO profile" { docker compose exec -T web python manage.py seed_demo }
if ($https) { Step "start LAN HTTPS" { docker compose --profile https up -d --no-build web-https } }

$users = docker compose exec -T web python manage.py shell -c "from django.contrib.auth import get_user_model as g; print(g().objects.count())"
Write-Output ""
Write-Output "Twin is running."
Write-Output "  On this computer: http://localhost:8000/"
if ($https) { Write-Output "  On your phone (LAN HTTPS): https://${httpsHost}:8443/" }
else { Write-Output "  Phone: set up LAN HTTPS first (README, 'LAN HTTPS'); then run this again for the phone URL." }
Write-Output "  Provenance demo: http://localhost:8000/provenance/?who=demo"
if ("$users".Trim() -eq "0") { Write-Output "  First time: create your login with  docker compose exec web python manage.py createsuperuser" }
