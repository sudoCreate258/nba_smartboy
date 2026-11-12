# SPDX-License-Identifier: AGPL-3.0-or-later
# Create (or reuse) your local certificate authority and a server certificate for LAN HTTPS (M6).
# Usage: powershell -File scripts/lan-cert.ps1 -LanHost 192.168.1.20 [-CaDir C:\Users\you\.twin-ca]
# The CA (its private key) goes OUTSIDE this repository (default: %USERPROFILE%\.twin-ca), so no
# container that mounts the repository can read it. Only the server certificate and key go into
# certs/server/ (gitignored, kept out of the image, masked from /app in every container and mounted
# read-only into the HTTPS service alone). Put <CaDir>\twin-ca.crt on your phone (README, "LAN HTTPS").
# Runs openssl from Alpine 3.20 in the official alpine image; nothing leaves this computer.
param([Parameter(Mandatory = $true)][string]$LanHost, [string]$CaDir = (Join-Path $env:USERPROFILE ".twin-ca"))
$ErrorActionPreference = "Stop"
if ($LanHost -notmatch '^[A-Za-z0-9.-]+$') { throw "LanHost must be an address or host name, e.g. 192.168.1.20" }
Set-Location (git rev-parse --show-toplevel)
$root = (Get-Location).Path
New-Item -ItemType Directory -Force $CaDir | Out-Null
$CaDir = (Resolve-Path $CaDir).Path
if ($CaDir.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "CaDir is inside the repository; keep the CA key outside it (containers mount the repository)."
}
$server = Join-Path $root "certs/server"
New-Item -ItemType Directory -Force $server | Out-Null
docker run --rm -v "${root}/scripts:/s:ro" -v "${CaDir}:/ca" -v "${server}:/server" alpine:3.20 `
    sh /s/lan-cert.sh $LanHost /ca /server
exit $LASTEXITCODE
