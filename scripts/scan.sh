#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later
# Dependency and image vulnerability gate (M6 R3). Runs inside the official alpine:3.20 image with
# osv-scanner and python3 from Alpine 3.20's own packages. Never mounts the Docker socket:
#   /repo           the repository, read-only (requirements.txt, tools/, scan-ignore.txt)
#   /in/web.tar     `docker save` of the web image, read-only
#   /out            results (osv JSON, package lists)
# Exit 1 when a fixable HIGH/CRITICAL advisory is not in scan-ignore.txt.
set -eu
apk add --no-cache osv-scanner python3 >/dev/null
echo "osv-scanner $(osv-scanner --version | sed -n 's/^osv-scanner version: //p') (Alpine $(cat /etc/alpine-release))"

# Dependencies as pinned in requirements.txt.
osv-scanner --format json --lockfile "requirements.txt:/repo/requirements.txt" > /out/deps.json || true

# The image as built: Debian packages and installed Python distributions, read from the saved tar.
python3 /repo/tools/image_packages.py /in/web.tar /out
osv-scanner --format json --lockfile "dpkg-status:/out/dpkg-status" \
  --lockfile "requirements.txt:/out/python-packages.txt" > /out/image.json || true

python3 /repo/tools/scan_report.py --debian-release "$(cat /out/debian-release)" \
  --ignore /repo/scan-ignore.txt /out/deps.json /out/image.json
