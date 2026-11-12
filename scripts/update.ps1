# SPDX-License-Identifier: AGPL-3.0-or-later
# Update this instance (M6 R7). Order: validate first, switch last.
#   1. refuse a working tree with tracked or untracked changes (Docker would deploy them)
#   2. pull the current branch (fast-forward only)
#   3. keep the running image as twin-web:previous, rebuild twin-web:local (one image for web,
#      web-https and backup) with the latest Debian updates
#   4. local gate against the NEW image in a one-off container (tests + migration check), while the
#      running services stay on the old image
#   5. migrate with a one-off container, then recreate every app service that was running
# Usage: powershell -File scripts/update.ps1
# On a failure before step 5 nothing that is running has changed; the message says how to roll back.
$ErrorActionPreference = "Stop"
Set-Location (git rev-parse --show-toplevel)

function Step([string]$name, [scriptblock]$run) {
    Write-Output "== $name"
    & $run
    if ($LASTEXITCODE -ne 0) {
        Write-Output ("update: '$name' failed (exit $LASTEXITCODE); stopped. Running services are unchanged" +
            " unless the step was 'migrate' or 'restart'. To return to the previous image:" +
            " docker tag twin-web:previous twin-web:local; docker compose up -d --no-build <services>")
        exit 1
    }
}

$dirty = git status --porcelain
if ($dirty) { Write-Output "update: the working tree has changes (tracked or untracked); commit, stash or remove them first:"; $dirty; exit 1 }

# App services running now (web, web-https, backup), so the same set comes back on the new image.
$running = @(docker compose --profile https --profile backup ps --services --filter status=running |
    Where-Object { $_ -in @("web", "web-https", "backup") })
if ($running.Count -eq 0) { $running = @("web") }

Step "pull (fast-forward only)" { git pull --ff-only }
Step "keep the current image as twin-web:previous" {
    docker image inspect twin-web:local *> $null
    if ($LASTEXITCODE -eq 0) { docker tag twin-web:local twin-web:previous } else { $global:LASTEXITCODE = 0 }
}
Step "rebuild the image" { docker compose build --pull web }
Step "local gate on the new image" { powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ci-local.ps1 }
Step "migrate" { docker compose run --rm -T web python manage.py migrate }
$profiles = @()
if ($running -contains "web-https") { $profiles += @("--profile", "https") }
if ($running -contains "backup") { $profiles += @("--profile", "backup") }
Step "restart $($running -join ', ') on the new image" { docker compose @profiles up -d --no-build @running }
Write-Output "update: done ($($running -join ', ') on the new image)."
