#!/usr/bin/env python3
"""Validate the bounded public frontend asset delivery contract."""

from __future__ import annotations

import argparse
import re
import sys
from html.parser import HTMLParser
from pathlib import PurePosixPath
from urllib.parse import urlsplit

MAX_INVENTORY_BYTES = 65536
MAX_INVENTORY_ENTRIES = 512
LEGACY_PATHS = {
    "/shared/esc.js",
    "/ui/toast.js",
    "/ui/modal.js",
    "/stateSlices.js",
    "/state.js",
    "/apiContracts.js",
    "/router.js",
    "/commands.js",
}
CORE_PATHS = {"/", "/index.html", "/asset-manifest.json", "/asset-inventory.txt"}
SAFE_PATH = re.compile(
    r"^/(?:[A-Za-z0-9][A-Za-z0-9._-]*)(?:/[A-Za-z0-9][A-Za-z0-9._-]*)*$"
)


class FrontendAssetParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.assets: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "script" and values.get("src"):
            self.assets.append(values["src"] or "")
        elif tag == "link" and "stylesheet" in (values.get("rel") or "").split():
            if values.get("href"):
                self.assets.append(values["href"] or "")


def normalize_index_reference(reference: str) -> str | None:
    parsed = urlsplit(reference)
    if parsed.scheme in {"http", "https"}:
        return None
    if parsed.netloc:
        raise ValueError(
            f"Protocol-relative frontend asset is not allowed: {reference!r}"
        )
    if parsed.scheme:
        raise ValueError(f"Unexpected frontend asset scheme: {reference!r}")
    if parsed.fragment or parsed.query or any(char.isspace() for char in parsed.path):
        raise ValueError(f"Unexpected frontend asset path: {reference!r}")
    path = PurePosixPath("/" + parsed.path.lstrip("/"))
    if ".." in path.parts or "\\" in parsed.path or "//" in parsed.path:
        raise ValueError(f"Frontend asset escapes the public root: {reference!r}")
    normalized = path.as_posix()
    if normalized != "/" and not SAFE_PATH.fullmatch(normalized):
        raise ValueError(f"Unexpected frontend asset path: {reference!r}")
    return normalized


def parse_index_assets(index_html: str) -> set[str]:
    parser = FrontendAssetParser()
    parser.feed(index_html)
    assets = set()
    for reference in parser.assets:
        path = normalize_index_reference(reference)
        if path:
            assets.add(path)
    if not assets:
        raise ValueError("Frontend index does not declare any runtime assets")
    return assets


def validate_inventory(raw: bytes, index_assets: set[str]) -> list[str]:
    if len(raw) > MAX_INVENTORY_BYTES or b"\r" in raw:
        raise ValueError("Frontend asset inventory exceeds the delivery contract")
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise ValueError("Frontend asset inventory is not UTF-8") from error
    if not lines or len(lines) > MAX_INVENTORY_ENTRIES or any(not line for line in lines):
        raise ValueError("Frontend asset inventory has invalid entries")
    if len(lines) != len(set(lines)):
        raise ValueError("Frontend asset inventory has duplicate entries")
    inventory = set(lines)
    if any(path != "/" and not SAFE_PATH.fullmatch(path) for path in inventory):
        raise ValueError("Frontend asset inventory has unsafe paths")
    if not CORE_PATHS <= inventory or not LEGACY_PATHS <= inventory:
        raise ValueError("Frontend asset inventory is missing required runtime paths")
    if not any(
        path.startswith("/assets/") and path.endswith(".js") for path in inventory
    ):
        raise ValueError("Frontend asset inventory is missing JavaScript bundles")
    if not index_assets <= inventory:
        raise ValueError("Frontend index references assets absent from inventory")
    return sorted(inventory)


def _read_limited(path: str) -> bytes:
    with open(path, "rb") as asset_file:
        return asset_file.read(MAX_INVENTORY_BYTES + 1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", required=True)
    parser.add_argument("--inventory")
    args = parser.parse_args()
    try:
        with open(args.index, encoding="utf-8") as index_file:
            index_assets = parse_index_assets(index_file.read())
        if args.inventory:
            paths = validate_inventory(_read_limited(args.inventory), index_assets)
        else:
            paths = sorted(index_assets)
    except (OSError, UnicodeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print("\n".join(paths))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
