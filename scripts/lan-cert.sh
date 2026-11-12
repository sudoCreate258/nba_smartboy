#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later
# Local certificate authority and server certificate for LAN HTTPS (M6 R5). The OWNER runs this
# (scripts/lan-cert.ps1 runs it in the official alpine:3.20 image with openssl from Alpine 3.20).
#   sh lan-cert.sh HOST CA_DIR SERVER_DIR
# CA_DIR/ca.key            CA private key: outside the repository, never in a container that runs the app
# CA_DIR/twin-ca.crt       CA certificate: install it on the phone to trust the server
# SERVER_DIR/server.*      server certificate (825 days, the iOS maximum) and key for gunicorn
# An existing CA is reused, so re-running only renews the server certificate (e.g. a new address).
set -eu
host="$1"
ca="$2"
server="$3"
command -v openssl >/dev/null 2>&1 || apk add --no-cache openssl >/dev/null
umask 077
mkdir -p "$ca" "$server"
case "$host" in
  *[!0-9.]*) san="DNS:$host,DNS:localhost,IP:127.0.0.1" ;;
  *) san="IP:$host,DNS:localhost,IP:127.0.0.1" ;;
esac

if [ ! -f "$ca/ca.key" ]; then
  openssl ecparam -name prime256v1 -genkey -noout -out "$ca/ca.key"
  openssl req -x509 -new -key "$ca/ca.key" -sha256 -days 3650 -out "$ca/twin-ca.crt" \
    -subj "/CN=Twin local CA $(date -u +%Y-%m-%d)" \
    -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" >/dev/null 2>&1
  echo "lan-cert: created a new local CA in $ca (keep ca.key private)"
else
  echo "lan-cert: reusing the existing local CA"
fi

work=$(mktemp -d)
openssl ecparam -name prime256v1 -genkey -noout -out "$server/server.key"
openssl req -new -key "$server/server.key" -subj "/CN=$host" -out "$work/server.csr" >/dev/null 2>&1
printf "basicConstraints=CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=serverAuth\nsubjectAltName=%s\n" "$san" \
  > "$work/server.ext"
openssl x509 -req -in "$work/server.csr" -CA "$ca/twin-ca.crt" -CAkey "$ca/ca.key" \
  -CAcreateserial -CAserial "$ca/serial" -days 825 -sha256 -extfile "$work/server.ext" \
  -out "$server/server.crt" >/dev/null 2>&1
rm -rf "$work"
chmod 644 "$ca/twin-ca.crt" "$server/server.crt"
chmod 644 "$server/server.key"  # readable by the HTTPS container; the folder is gitignored and masked from /app
echo "lan-cert: server certificate for $host ($san), valid 825 days"
openssl x509 -in "$ca/twin-ca.crt" -noout -fingerprint -sha256
