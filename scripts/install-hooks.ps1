# SPDX-License-Identifier: AGPL-3.0-or-later
# Installs the pre-push hook that runs the local CI gate (scripts/ci-local.sh) before every push.
# Usage: powershell -File scripts/install-hooks.ps1
# Git for Windows runs hooks with its bundled sh, so the hook itself is a shell script.
$ErrorActionPreference = "Stop"
$root = git rev-parse --show-toplevel
$hooks = git rev-parse --git-path hooks
if (-not [System.IO.Path]::IsPathRooted($hooks)) { $hooks = Join-Path $root $hooks }
New-Item -ItemType Directory -Force $hooks | Out-Null
$target = Join-Path $hooks "pre-push"
# Copy with LF line endings; sh rejects CRLF.
$text = (Get-Content -Raw (Join-Path $root "scripts/pre-push")) -replace "`r`n", "`n"
[System.IO.File]::WriteAllText($target, $text)
Write-Output "Installed $target (runs scripts/ci-local.sh before every push)."
