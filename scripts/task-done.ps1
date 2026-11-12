# SPDX-License-Identifier: AGPL-3.0-or-later
# Finish a task in one command: stage the given paths, commit (noreply identity),
# run the local CI gate on the clean commit, push, and append a line to the
# planner progress log. Nothing is pushed when the gate fails.
#
#   powershell -File scripts/task-done.ps1 -Message "M4-T3: ..." -Paths ui,tests/test_x.py
#
# Identity is passed per command (the repo's git config is not changed).
param(
    [Parameter(Mandatory = $true)][string]$Message,
    [Parameter(Mandatory = $true)][string[]]$Paths,
    [string]$Name = "Vladimir Beauge",
    [string]$Email = "59755293+sudoCreate258@users.noreply.github.com"
)
$ErrorActionPreference = "Stop"
Set-Location (git rev-parse --show-toplevel)
$Paths = $Paths | ForEach-Object { $_ -split "," } | Where-Object { $_ }

git add -- $Paths
git diff --cached --quiet
if ($LASTEXITCODE -eq 0) { Write-Output "Nothing staged."; exit 1 }
git -c "user.name=$Name" -c "user.email=$Email" commit -q -m $Message
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$sha = git rev-parse --short HEAD

& powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ci-local.ps1 | Select-Object -Last 2
$gate = $LASTEXITCODE
$result = (Get-Content .agents/ci-local-last.txt -Raw).Trim()
$branch = git rev-parse --abbrev-ref HEAD
$pushed = "not pushed"
if ($gate -eq 0) {
    $ErrorActionPreference = "Continue"
    git push -u origin $branch 2>&1 | Select-String -Pattern "->|refused|gate" | ForEach-Object { "$_" }
    $pushed = if ($LASTEXITCODE -eq 0) { "pushed $branch" } else { "push failed" }
}
$line = "- $(Get-Date -Format HH:mm) $Message; commit $sha; gate: $result; $pushed"
$log = ".planner/to-planner/progress.md"
if (Test-Path $log) { Add-Content -Encoding utf8 $log $line }
Write-Output $line
if ($gate -ne 0) { exit $gate }
