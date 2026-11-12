# SPDX-License-Identifier: AGPL-3.0-or-later
# Vulnerability gate (M6 R3): builds the web image, saves it to a tar and scans it, plus requirements.txt,
# with osv-scanner from Alpine 3.20 (official alpine:3.20 image). The Docker socket is never mounted; the
# image tar and the repository are mounted read-only. Fails on fixable HIGH/CRITICAL advisories that are
# not in scan-ignore.txt. Usage: powershell -File scripts/scan.ps1   (needs network for the advisory API)
$ErrorActionPreference = "Stop"
Set-Location (git rev-parse --show-toplevel)
$root = (Get-Location).Path
$out = Join-Path $root ".agents/scan"
New-Item -ItemType Directory -Force $out | Out-Null

$ErrorActionPreference = "Continue"
docker build -q -t twin-web:scan . | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Output "scan: image build failed"; exit 1 }
docker save -o (Join-Path $out "web.tar") twin-web:scan
if ($LASTEXITCODE -ne 0) { Write-Output "scan: docker save failed"; exit 1 }
docker run --rm -v "${root}:/repo:ro" -v "$(Join-Path $out 'web.tar'):/in/web.tar:ro" -v "${out}:/out" `
    alpine:3.20 sh /repo/scripts/scan.sh 2>&1 | ForEach-Object { "$_" }
$status = $LASTEXITCODE
Remove-Item (Join-Path $out "web.tar") -ErrorAction SilentlyContinue
exit $status
