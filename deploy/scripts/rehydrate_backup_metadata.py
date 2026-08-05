#!/usr/bin/env python3
"""Validate a precise restic snapshot before its backup pair is rehydrated."""

from __future__ import annotations

import json
import re
import sys
from pathlib import PurePosixPath
from typing import Any

_SNAPSHOT_ID = re.compile(r"^[0-9a-f]{64}$")
_BASENAME = re.compile(r"^[0-9]{8}T[0-9]{6}Z\.dump$")
_TAG = "ai-writing-assist-postgres"


def _fail(message: str) -> None:
    print(f"Off-site backup metadata is unsafe: {message}.", file=sys.stderr)
    raise SystemExit(1)


def _read_json(path: str) -> Any:
    try:
        with open(path, encoding="utf-8") as source:
            return json.load(source)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail("restic JSON output cannot be parsed")
        raise AssertionError from exc


def _snapshot(payload: Any, requested_id: str, dump_name: str) -> tuple[str, str]:
    if not isinstance(payload, list) or len(payload) != 1:
        _fail("requested snapshot is not exact")
    item = payload[0]
    if not isinstance(item, dict) or item.get("id") != requested_id:
        _fail("requested snapshot is not exact")
    tags = item.get("tags")
    paths = item.get("paths")
    if (
        not isinstance(tags, list)
        or any(not isinstance(tag, str) for tag in tags)
        or _TAG not in tags
        or not isinstance(paths, list)
        or len(paths) != 2
        or any(not isinstance(path, str) for path in paths)
    ):
        _fail("snapshot tag or path schema is invalid")
    expected = {dump_name, f"{dump_name}.sha256"}
    pure_paths = [PurePosixPath(path) for path in paths]
    if (
        any(
            not path.is_absolute()
            or ".." in path.parts
            or "\n" in str(path)
            or "\r" in str(path)
            for path in pure_paths
        )
        or {path.name for path in pure_paths} != expected
        or pure_paths[0].parent != pure_paths[1].parent
    ):
        _fail("snapshot paths do not describe the requested backup pair")
    return paths[0], paths[1]


def _nodes(path: str, dump_name: str) -> tuple[str, str]:
    expected = {dump_name, f"{dump_name}.sha256"}
    matches: list[str] = []
    files: list[str] = []
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        _fail("restic ls JSON output cannot be parsed")
        raise AssertionError from exc
    if not lines:
        _fail("restic ls JSON output is empty")
    for line in lines:
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            _fail("restic ls JSON output cannot be parsed")
            raise AssertionError from exc
        if not isinstance(item, dict) or item.get("struct_type") != "node":
            continue
        if item.get("type") != "file" or not isinstance(item.get("path"), str):
            continue
        candidate = item["path"]
        pure = PurePosixPath(candidate)
        if (
            not pure.is_absolute()
            or ".." in pure.parts
            or "\n" in candidate
            or "\r" in candidate
        ):
            _fail("restic file path is invalid")
        files.append(candidate)
        if pure.name in expected:
            matches.append(candidate)
    if len(files) != 2 or len(matches) != 2:
        _fail("snapshot does not contain exactly one requested backup pair")
    dump_path = next((item for item in matches if item.endswith(".dump")), None)
    sidecar_path = next((item for item in matches if item.endswith(".dump.sha256")), None)
    if dump_path is None or sidecar_path is None:
        _fail("snapshot does not contain the requested backup pair")
    if PurePosixPath(dump_path).parent != PurePosixPath(sidecar_path).parent:
        _fail("requested backup pair has different source directories")
    return dump_path, sidecar_path


def main(arguments: list[str]) -> None:
    if len(arguments) != 5:
        _fail("usage is <snapshot-id> <dump-basename> <snapshots-json> <ls-json>")
    snapshot_id, dump_name, snapshots_path, listing_path = arguments[1:]
    if _SNAPSHOT_ID.fullmatch(snapshot_id) is None:
        _fail("snapshot id is invalid")
    if _BASENAME.fullmatch(dump_name) is None or "/" in dump_name:
        _fail("backup basename is invalid")
    snapshot_dump, snapshot_sidecar = _snapshot(
        _read_json(snapshots_path), snapshot_id, dump_name
    )
    dump_path, sidecar_path = _nodes(listing_path, dump_name)
    if {snapshot_dump, snapshot_sidecar} != {dump_path, sidecar_path}:
        _fail("snapshot paths and restic listing do not describe the same pair")
    print(dump_path)
    print(sidecar_path)


if __name__ == "__main__":
    main(sys.argv)
