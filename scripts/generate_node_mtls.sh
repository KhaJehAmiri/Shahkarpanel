#!/usr/bin/env bash
# Generate a small CA + panel client cert for node mTLS (SSL_CLIENT_CERT_FILE).
# Run on the panel host; copy outputs to each node agent.
set -euo pipefail

OUT="${1:-/var/lib/shahkar/certs/mtls}"
DAYS="${2:-3650}"
mkdir -p "$OUT"
cd "$OUT"

if [ -f ca.key ]; then
  echo "CA already exists in $OUT — remove files to regenerate" >&2
  exit 1
fi

openssl req -x509 -newkey rsa:4096 -sha256 -days "$DAYS" -nodes \
  -keyout ca.key -out ca.pem \
  -subj "/CN=Shahkar Node CA"

openssl req -newkey rsa:4096 -nodes -keyout client.key -out client.csr \
  -subj "/CN=shahkar-panel-client"

openssl x509 -req -in client.csr -CA ca.pem -CAkey ca.key -CAcreateserial \
  -out client.pem -days "$DAYS" -sha256

chmod 600 ca.key client.key
rm -f client.csr

cat <<EOF

Generated in: $OUT
  ca.pem       — trust on every node (SSL_CLIENT_CERT_FILE)
  client.pem   — panel client certificate (optional mutual auth setups)
  client.key   — panel client private key (keep on panel only)

Node agent (.env or docker -e):
  SSL_CLIENT_CERT_FILE=$OUT/ca.pem

Panel (optional strict TLS to nodes):
  NODE_SSL_VERIFY=True

Restart node agents after copying ca.pem.
EOF
