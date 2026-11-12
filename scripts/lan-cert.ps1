# SPDX-License-Identifier: AGPL-3.0-or-later
# Create (or reuse) your local certificate authority and a server certificate for LAN HTTPS (M6).
# Usage: powershell -File scripts/lan-cert.ps1 -LanHost 192.168.1.20
# Writes into certs/ (gitignored, never copied into the image). Keep certs/ca/ca.key private; put
# certs/ca/twin-ca.crt on your phone (README, "LAN HTTPS"). Runs openssl from Alpine 3.20 in the
# official alpine image; nothing leaves this computer.
param([Parameter(Mandatory = $true)][string]$LanHost)
$ErrorActionPreference = "Stop"
if ($LanHost -notmatch '^[A-Za-z0-9.-]+$') { throw "LanHost must be an address or host name, e.g. 192.168.1.20" }
Set-Location (git rev-parse --show-toplevel)
$root = (Get-Location).Path
New-Item -ItemType Directory -Force (Join-Path $root "certs") | Out-Null
docker run --rm -v "${root}/scripts:/s:ro" -v "${root}/certs:/certs" alpine:3.20 sh /s/lan-cert.sh $LanHost /certs
exit $LASTEXITCODE
