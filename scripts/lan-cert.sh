#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later
# Local certificate authority and server certificate for LAN HTTPS (M6 R5). The OWNER runs this
# (scripts/lan-cert.ps1 runs it in the official alpine:3.20 image with openssl from Alpine 3.20).
#   sh lan-cert.sh HOST OUT_DIR
# OUT_DIR/ca/ca.key        CA private key: stays on this computer, never in git, never on the phone
# OUT_DIR/ca/twin-ca.crt   CA certificate: install it on the phone to trust the server
# OUT_DIR/server/server.*  server certificate (825 days, the iOS maximum) and key for gunicorn
# An existing CA is reused, so re-running only renews the server certificate (e.g. a new address).
set -eu
host="$1"
out="$2"
command -v openssl >/dev/null 2>&1 || apk add --no-cache openssl >/dev/null
umask 077
mkdir -p "$out/ca" "$out/server"
case "$host" in
  *[!0-9.]*) san="DNS:$host,DNS:localhost,IP:127.0.0.1" ;;
  *) san="IP:$host,DNS:localhost,IP:127.0.0.1" ;;
esac

if [ ! -f "$out/ca/ca.key" ]; then
  openssl ecparam -name prime256v1 -genkey -noout -out "$out/ca/ca.key"
  openssl req -x509 -new -key "$out/ca/ca.key" -sha256 -days 3650 -out "$out/ca/twin-ca.crt" \
    -subj "/CN=Twin local CA $(date -u +%Y-%m-%d)" \
    -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" >/dev/null 2>&1
  echo "lan-cert: created a new local CA (keep $out/ca/ca.key private)"
else
  echo "lan-cert: reusing the existing local CA"
fi

openssl ecparam -name prime256v1 -genkey -noout -out "$out/server/server.key"
openssl req -new -key "$out/server/server.key" -subj "/CN=$host" -out "$out/server/server.csr" >/dev/null 2>&1
printf "basicConstraints=CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=serverAuth\nsubjectAltName=%s\n" "$san" \
  > "$out/server/server.ext"
openssl x509 -req -in "$out/server/server.csr" -CA "$out/ca/twin-ca.crt" -CAkey "$out/ca/ca.key" \
  -CAcreateserial -CAserial "$out/ca/serial" -days 825 -sha256 -extfile "$out/server/server.ext" \
  -out "$out/server/server.crt" >/dev/null 2>&1
rm -f "$out/server/server.csr" "$out/server/server.ext"
chmod 644 "$out/ca/twin-ca.crt" "$out/server/server.crt"
chmod 644 "$out/server/server.key"  # readable by the container user; the folder is gitignored
echo "lan-cert: server certificate for $host ($san), valid 825 days"
openssl x509 -in "$out/ca/twin-ca.crt" -noout -fingerprint -sha256
