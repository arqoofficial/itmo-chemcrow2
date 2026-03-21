#!/usr/bin/env bash
# Генерация самоподписанного fullchain.pem + privkey.pem в ./certs (для теста или доступа только по IP).
# Использование:
#   ./scripts/gen-selfsigned-certs.sh                    # CN=localhost, SAN DNS:localhost
#   ./scripts/gen-selfsigned-certs.sh 203.0.113.10       # SAN IP:203.0.113.10
#   ./scripts/gen-selfsigned-certs.sh app.example.com    # SAN DNS:app.example.com

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/certs"
mkdir -p "$OUT"

HOST="${1:-localhost}"
if [[ "$HOST" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  SAN="IP:${HOST}"
  CN="$HOST"
else
  SAN="DNS:${HOST}"
  CN="$HOST"
fi

openssl req -x509 -nodes -days 365 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 \
  -keyout "$OUT/privkey.pem" \
  -out "$OUT/fullchain.pem" \
  -subj "/CN=${CN}" \
  -addext "subjectAltName=${SAN}"

echo "Written: $OUT/fullchain.pem and $OUT/privkey.pem (CN=${CN}, ${SAN})"
