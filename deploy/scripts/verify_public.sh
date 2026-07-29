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

python3 - "$TMP_DIR/index.html" >"$TMP_DIR/frontend-assets.tsv" <<'PY'
from html.parser import HTMLParser
from pathlib import PurePosixPath
import sys
from urllib.parse import urlsplit


class FrontendAssetParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.assets: list[tuple[str, str]] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        values = dict(attrs)
        if tag == "script" and values.get("src"):
            self.assets.append(("script", values["src"] or ""))
            return
        if tag == "link" and "stylesheet" in (values.get("rel") or "").split():
            if values.get("href"):
                self.assets.append(("stylesheet", values["href"] or ""))


with open(sys.argv[1], encoding="utf-8") as index_file:
    parser = FrontendAssetParser()
    parser.feed(index_file.read())

if not parser.assets:
    raise SystemExit("Frontend index does not declare any runtime assets")

for kind, reference in parser.assets:
    parsed = urlsplit(reference)
    if parsed.scheme or parsed.netloc:
        continue
    if parsed.fragment:
        raise SystemExit(f"Unexpected frontend asset fragment: {reference!r}")
    if parsed.query or any(character.isspace() for character in parsed.path):
        raise SystemExit(f"Unexpected frontend asset path: {reference!r}")
    path = PurePosixPath("/" + parsed.path.lstrip("/"))
    if ".." in path.parts:
        raise SystemExit(f"Frontend asset escapes the public root: {reference!r}")
    print(f"{kind}\t{path.as_posix()}")
PY

TAB=$(printf '\t')
while IFS="$TAB" read -r asset_kind asset_path; do
    content_type=$(curl --fail --silent --show-error \
        --proto '=https' --tlsv1.2 \
        --output /dev/null --write-out '%{content_type}' \
        "$PUBLIC_BASE_URL$asset_path")
    case "$asset_kind:$content_type" in
        script:application/javascript*|script:text/javascript*|stylesheet:text/css*)
            ;;
        *)
            echo "Unexpected content type for $asset_path: $content_type" >&2
            exit 1
            ;;
    esac
done <"$TMP_DIR/frontend-assets.tsv"

echo "Public HTTPS, frontend runtime assets, API, and database health checks passed."
