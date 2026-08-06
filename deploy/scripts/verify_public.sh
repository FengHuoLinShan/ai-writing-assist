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

curl_https --dump-header "$TMP_DIR/health.headers" --max-filesize 65536 \
    "$PUBLIC_BASE_URL/api/health" >"$TMP_DIR/health.json"
python3 - "$TMP_DIR/health.json" "$TMP_DIR/health.headers" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as health_file:
    payload = json.load(health_file)
if payload.get("status") != "healthy" or payload.get("database") != "connected":
    raise SystemExit(f"Unexpected health response: {payload!r}")

with open(sys.argv[2], encoding="iso-8859-1") as header_file:
    raw_lines = header_file.read().splitlines()
responses: list[list[str]] = []
current: list[str] | None = None
for raw_line in raw_lines:
    line = raw_line.strip("\r")
    if line.startswith("HTTP/"):
        if current is not None:
            responses.append(current)
        current = []
    elif not line:
        if current is not None:
            responses.append(current)
            current = None
    elif current is None:
        raise SystemExit("Security header verification found an unframed header block")
    else:
        current.append(line)
if current is not None:
    responses.append(current)
if not responses:
    raise SystemExit("Security header verification found no HTTP response headers")

headers: dict[str, list[str]] = {}
for line in responses[-1]:
    if ":" not in line:
        raise SystemExit("Security header verification found a malformed header")
    name, value = line.split(":", 1)
    headers.setdefault(name.strip().lower(), []).append(value.strip())

required = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
}
for name, expected in required.items():
    values = headers.get(name, [])
    if values != [expected]:
        raise SystemExit(
            f"Security header {name} must appear exactly once with the expected value"
        )

hsts_values = headers.get("strict-transport-security", [])
if len(hsts_values) != 1:
    raise SystemExit(
        "Security header strict-transport-security must appear exactly once"
    )
hsts_directives: dict[str, str | None] = {}
for raw_directive in hsts_values[0].split(";"):
    directive = raw_directive.strip()
    if not directive:
        raise SystemExit("Security header strict-transport-security is malformed")
    name, separator, raw_value = directive.partition("=")
    normalized_name = name.strip().lower()
    if normalized_name not in {"max-age", "includesubdomains", "preload"}:
        raise SystemExit(
            "Security header strict-transport-security has an unsupported directive"
        )
    if normalized_name in hsts_directives:
        raise SystemExit(
            "Security header strict-transport-security repeats a directive"
        )
    value = raw_value.strip() if separator else None
    if normalized_name == "max-age":
        if value is None or not value.isascii() or not value.isdecimal():
            raise SystemExit(
                "Security header strict-transport-security has an invalid max-age"
            )
    elif value is not None:
        raise SystemExit(
            "Security header strict-transport-security has an invalid flag directive"
        )
    hsts_directives[normalized_name] = value
max_age = hsts_directives.get("max-age")
if max_age is None or int(max_age) < 31_536_000:
    raise SystemExit(
        "Security header strict-transport-security must retain at least one year"
    )
if "preload" in hsts_directives and "includesubdomains" not in hsts_directives:
    raise SystemExit(
        "Security header strict-transport-security preload requires includeSubDomains"
    )

csp_values = headers.get("content-security-policy", [])
if len(csp_values) != 1:
    raise SystemExit("Security header content-security-policy must appear exactly once")
csp = csp_values[0]
expected_csp = {
    "default-src": ["'self'"],
    "script-src": ["'self'"],
    "style-src": ["'self'", "'unsafe-inline'"],
    "img-src": ["'self'", "data:"],
    "connect-src": ["'self'"],
    "object-src": ["'none'"],
    "base-uri": ["'self'"],
    "frame-ancestors": ["'none'"],
}
actual_csp: dict[str, list[str]] = {}
for raw_directive in csp.split(";"):
    tokens = raw_directive.split()
    if not tokens:
        continue
    name, values = tokens[0].lower(), tokens[1:]
    if name in actual_csp:
        raise SystemExit("Security header content-security-policy repeats a directive")
    actual_csp[name] = values
if actual_csp != expected_csp:
    raise SystemExit("Security header content-security-policy differs from the baseline")
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
