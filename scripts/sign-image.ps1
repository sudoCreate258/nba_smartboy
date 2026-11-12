# SPDX-License-Identifier: AGPL-3.0-or-later
# Build, sign and verify the web image (M6 R6) with cosign from Alpine 3.20 (official alpine:3.20 image).
#   powershell -File scripts/sign-image.ps1            build twin-web:<version> and sign it
#   powershell -File scripts/sign-image.ps1 -Verify    check the signature against the image you have
# The signed statement is the image ID (the digest of its configuration, which covers every layer) plus
# version and commit, written to dist/ (gitignored). Signing is offline: nothing goes to a transparency log.
# Key: a cosign key pair YOU create and keep outside this repository (docs/OPERATIONS.md); point
# COSIGN_KEY_DIR at its folder; COSIGN_PASSWORD holds its password. No key = a clear SKIPPED message, exit 0.
param([switch]$Verify, [string]$Version = "")
$ErrorActionPreference = "Stop"
Set-Location (git rev-parse --show-toplevel)
$root = (Get-Location).Path
$commit = (git rev-parse HEAD).Trim()
if (-not $Version) { $Version = (git describe --tags --always --dirty).Trim() }
$image = "twin-web:$Version"
$dist = Join-Path $root "dist"
$statement = "twin-web-$Version.json"
New-Item -ItemType Directory -Force $dist | Out-Null

$keyDir = $env:COSIGN_KEY_DIR
$needed = if ($Verify) { "cosign.pub" } else { "cosign.key" }
if (-not $keyDir -or -not (Test-Path (Join-Path $keyDir $needed))) {
    Write-Output "SKIPPED: no signing key ($needed not found; set COSIGN_KEY_DIR to the folder with your cosign key pair, see docs/OPERATIONS.md). The image was not signed."
    exit 0
}
$keyDir = (Resolve-Path $keyDir).Path
if ($keyDir.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
    Write-Output "REFUSED: COSIGN_KEY_DIR is inside the repository; keep the key outside it."
    exit 1
}

$ErrorActionPreference = "Continue"
function Cosign([string]$cmd) {
    docker run --rm -e COSIGN_PASSWORD -v "${keyDir}:/keys:ro" -v "${dist}:/dist" alpine:3.20 `
        sh -c "apk add --no-cache cosign >/dev/null && $cmd" 2>&1 | ForEach-Object { Write-Host "$_" }
    return $LASTEXITCODE  # only the exit code is returned; cosign's messages go to the console
}

if (-not $Verify) {
    docker build -q -t $image --label "org.opencontainers.image.version=$Version" `
        --label "org.opencontainers.image.revision=$commit" . | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Output "FAILED: image build"; exit 1 }
    $id = (docker image inspect --format "{{.Id}}" $image).Trim()
    $body = [ordered]@{ image = "twin-web"; version = $Version; revision = $commit; image_id = $id } | ConvertTo-Json -Compress
    [System.IO.File]::WriteAllText((Join-Path $dist $statement), $body)
    $status = Cosign "cosign sign-blob --yes --tlog-upload=false --key /keys/cosign.key --output-signature /dist/$statement.sig /dist/$statement"
    if ($status -ne 0) { Write-Output "FAILED: signing"; exit 1 }
    Write-Output "SIGNED: $image ($id), statement dist/$statement, signature dist/$statement.sig"
    exit 0
}

if (-not (Test-Path (Join-Path $dist "$statement.sig"))) { Write-Output "FAILED: no signature dist/$statement.sig for $Version"; exit 1 }
$signed = Get-Content (Join-Path $dist $statement) -Raw | ConvertFrom-Json
$id = (docker image inspect --format "{{.Id}}" $image 2>$null)
if (-not $id) { Write-Output "FAILED: image $image is not present"; exit 1 }
if ($id.Trim() -ne $signed.image_id) { Write-Output "FAILED: $image is $($id.Trim()), the signed image is $($signed.image_id)"; exit 1 }
$status = Cosign "cosign verify-blob --insecure-ignore-tlog=true --key /keys/cosign.pub --signature /dist/$statement.sig /dist/$statement"
if ($status -ne 0) { Write-Output "FAILED: the signature does not verify with cosign.pub"; exit 1 }
Write-Output "VERIFIED: $image ($($signed.image_id)) signed for $Version at $($signed.revision)"
exit 0
