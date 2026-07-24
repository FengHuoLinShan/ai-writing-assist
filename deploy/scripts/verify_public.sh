#!/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$SCRIPT_DIR/common.sh"

validate_environment
PUBLIC_BASE_URL=$(env_value PUBLIC_BASE_URL)
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT HUP INT TERM

curl --fail --silent --show-error \
    --proto '=https' --tlsv1.2 \
    "$PUBLIC_BASE_URL/api/health" >"$TMP_DIR/health.json"
python3 - "$TMP_DIR/health.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as health_file:
    payload = json.load(health_file)
if payload.get("status") != "healthy" or payload.get("database") != "connected":
    raise SystemExit(f"Unexpected health response: {payload!r}")
PY

curl --fail --silent --show-error \
    --proto '=https' --tlsv1.2 \
    "$PUBLIC_BASE_URL/" >"$TMP_DIR/index.html"
grep -q '<div id="app"></div>' "$TMP_DIR/index.html"

echo "Public HTTPS, frontend, API, and database health checks passed."
