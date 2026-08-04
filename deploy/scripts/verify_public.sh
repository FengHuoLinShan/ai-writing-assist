#!/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$SCRIPT_DIR/common.sh"

usage() {
    echo "Usage: $0 [--runtime]" >&2
}

case "$#" in
    0)
        verification_mode=full
        ;;
    1)
        if [ "$1" != "--runtime" ]; then
            usage
            exit 2
        fi
        verification_mode=runtime
        ;;
    *)
        usage
        exit 2
        ;;
esac

curl_https() {
    curl --fail --silent --show-error \
        --connect-timeout 5 --max-time 30 \
        --proto '=https' --tlsv1.2 "$@"
}

validate_environment
PUBLIC_BASE_URL=$(env_value PUBLIC_BASE_URL)
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT HUP INT TERM

curl_https --max-filesize 65536 \
    "$PUBLIC_BASE_URL/api/health" >"$TMP_DIR/health.json"
python3 - "$TMP_DIR/health.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as health_file:
    payload = json.load(health_file)
if payload.get("status") != "healthy" or payload.get("database") != "connected":
    raise SystemExit(f"Unexpected health response: {payload!r}")
PY

curl_https --max-filesize 1048576 \
    "$PUBLIC_BASE_URL/" >"$TMP_DIR/index.html"
grep -q '<div id="app"></div>' "$TMP_DIR/index.html"

if [ "$verification_mode" = runtime ]; then
    python3 "$SCRIPT_DIR/validate_frontend_assets.py" \
        --index "$TMP_DIR/index.html" >"$TMP_DIR/frontend-assets.txt"
else
    contract_marker="$REPO_ROOT/deploy/frontend-asset-contract.version"
    if [ ! -e "$contract_marker" ] && [ ! -L "$contract_marker" ]; then
        inventory_path=""
    else
        if [ ! -f "$contract_marker" ] || [ -L "$contract_marker" ] \
            || [ "$(wc -l <"$contract_marker")" -ne 1 ] \
            || [ "$(cat "$contract_marker")" != "1" ]; then
            echo "Invalid frontend asset contract marker." >&2
            exit 1
        fi
        inventory_path="$TMP_DIR/asset-inventory.txt"
        curl_https --max-filesize 65536 \
            "$PUBLIC_BASE_URL/asset-inventory.txt" >"$inventory_path"
    fi

    if [ -n "$inventory_path" ]; then
        python3 "$SCRIPT_DIR/validate_frontend_assets.py" \
            --index "$TMP_DIR/index.html" \
            --inventory "$inventory_path" >"$TMP_DIR/frontend-assets.txt"
    else
        python3 "$SCRIPT_DIR/validate_frontend_assets.py" \
            --index "$TMP_DIR/index.html" >"$TMP_DIR/frontend-assets.txt"
    fi
fi

while IFS= read -r asset_path; do
    content_type=$(curl_https \
        --output /dev/null --write-out '%{content_type}' \
        "$PUBLIC_BASE_URL$asset_path")
    case "$asset_path:$content_type" in
        /:*text/html*|*.html:text/html*|*.js:application/javascript*|*.js:text/javascript*|*.css:text/css*|*.json:application/json*|*.txt:text/plain*|*.svg:image/svg+xml*|*.png:image/png*|*.jpg:image/jpeg*|*.jpeg:image/jpeg*|*.gif:image/gif*|*.webp:image/webp*|*.avif:image/avif*|*.woff:font/woff*|*.woff2:font/woff2*|*.woff:application/font-woff*|*.woff2:application/font-woff*|*.woff:application/octet-stream*|*.woff2:application/octet-stream*)
            ;;
        *)
            echo "Unexpected content type for $asset_path: $content_type" >&2
            exit 1
            ;;
    esac
done <"$TMP_DIR/frontend-assets.txt"

if [ "$verification_mode" = runtime ]; then
    echo "Public HTTPS, index frontend runtime assets, API, and database health checks passed."
elif [ -n "$inventory_path" ]; then
    echo "Public HTTPS, complete frontend asset inventory, API, and database health checks passed."
else
    echo "Public HTTPS, frontend runtime assets, API, and database health checks passed."
fi
