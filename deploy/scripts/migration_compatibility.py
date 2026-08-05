#!/usr/bin/env python3
"""Fail closed before deploying a migration graph older than the live database.

This deliberately reads only committed Git blobs.  It must never import a target
revision module: migration modules are application code, not configuration.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import PurePosixPath

_REVISION = re.compile(r"^[A-Za-z0-9_]{1,128}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_MIGRATIONS_PREFIX = "backend/alembic/versions/"
_HELPER_PATH = "deploy/scripts/migration_compatibility.py"


class GuardError(Exception):
    """The deployment must stop before changing the checkout or services."""


@dataclass(frozen=True)
class Graph:
    parents: dict[str, tuple[str, ...]]
    versioned_parents: dict[str, tuple[str, ...]]
    head: str


def _fail(message: str) -> None:
    print(
        f"Migration compatibility guard rejected the target: {message}.",
        file=sys.stderr,
    )
    raise SystemExit(1)


def _revision(value: object) -> str:
    if not isinstance(value, str) or _REVISION.fullmatch(value) is None:
        raise GuardError("migration revision metadata is invalid")
    return value


def _commit(value: str) -> str:
    if _COMMIT.fullmatch(value) is None:
        raise GuardError("commit identifier is invalid")
    return value


def _git(repo_root: str, arguments: list[str]) -> bytes:
    try:
        completed = subprocess.run(
            ["git", "-C", repo_root, *arguments],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise GuardError("cannot read the requested Git migration tree") from exc
    return completed.stdout


def _regular_blob(repo_root: str, commit: str, path: str) -> bytes:
    entry = _git(repo_root, ["ls-tree", "-z", commit, "--", path])
    expected_suffix = os.fsencode("\t" + path + "\0")
    if not entry.endswith(expected_suffix):
        raise GuardError("required migration guard asset is missing or unsafe")
    metadata = entry[: -len(expected_suffix)].split()
    if len(metadata) != 3 or metadata[0] not in {b"100644", b"100755"}:
        raise GuardError("required migration guard asset is missing or unsafe")
    if metadata[1] != b"blob" or len(metadata[2]) != 40:
        raise GuardError("required migration guard asset is missing or unsafe")
    return _git(repo_root, ["show", f"{commit}:{path}"])


def _migration_paths(repo_root: str, commit: str) -> list[str]:
    output = _git(repo_root, ["ls-tree", "-r", "-z", commit, "--", _MIGRATIONS_PREFIX])
    entries = [entry for entry in output.split(b"\0") if entry]
    if not entries:
        raise GuardError("migration tree is empty")
    paths: list[str] = []
    for entry in entries:
        try:
            metadata, encoded_path = entry.split(b"\t", 1)
            mode, object_type, object_id = metadata.split()
            path = os.fsdecode(encoded_path)
        except (UnicodeDecodeError, ValueError) as exc:
            raise GuardError("migration tree contains an unsafe path") from exc
        pure_path = PurePosixPath(path)
        if (
            mode not in {b"100644", b"100755"}
            or object_type != b"blob"
            or len(object_id) != 40
            or not path.startswith(_MIGRATIONS_PREFIX)
            or not path.endswith(".py")
            or ".." in pure_path.parts
            or pure_path.is_absolute()
        ):
            raise GuardError("migration tree contains an unsafe path")
        paths.append(path)
    return sorted(paths)


def _assignment_value(tree: ast.Module, name: str, *, required: bool) -> object | None:
    found: list[ast.expr] = []
    for statement in tree.body:
        value: ast.expr | None = None
        if isinstance(statement, ast.Assign):
            if len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name):
                if statement.targets[0].id == name:
                    value = statement.value
        elif isinstance(statement, ast.AnnAssign):
            if isinstance(statement.target, ast.Name) and statement.target.id == name:
                value = statement.value
        if value is not None:
            found.append(value)
    if not found and not required:
        return None
    if len(found) != 1:
        raise GuardError(f"migration {name} metadata is missing or duplicated")
    try:
        return ast.literal_eval(found[0])
    except (TypeError, ValueError) as exc:
        raise GuardError(f"migration {name} metadata is not a literal") from exc


def _revision_list(value: object | None, name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        values = (value,)
    elif isinstance(value, (tuple, list)):
        values = tuple(value)
    else:
        raise GuardError(f"migration {name} metadata is invalid")
    revisions = tuple(_revision(item) for item in values)
    if len(set(revisions)) != len(revisions):
        raise GuardError(f"migration {name} metadata is duplicated")
    return revisions


def _branch_labels(value: object | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        labels = (value,)
    elif isinstance(value, (tuple, list)):
        labels = tuple(value)
    else:
        raise GuardError("migration branch_labels metadata is invalid")
    if any(not isinstance(label, str) or not label for label in labels):
        raise GuardError("migration branch_labels metadata is invalid")
    if len(set(labels)) != len(labels):
        raise GuardError("migration branch_labels metadata is duplicated")
    return labels


def _graph(repo_root: str, commit: str, *, require_helper: bool) -> Graph:
    _git(repo_root, ["cat-file", "-e", f"{commit}^{{commit}}"])
    if require_helper:
        _regular_blob(repo_root, commit, _HELPER_PATH)
    migration_metadata: dict[
        str, tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]
    ] = {}
    labels: dict[str, str] = {}
    for path in _migration_paths(repo_root, commit):
        try:
            tree = ast.parse(_regular_blob(repo_root, commit, path).decode("utf-8"))
        except (SyntaxError, UnicodeDecodeError) as exc:
            raise GuardError("migration source cannot be parsed") from exc
        revision = _revision(_assignment_value(tree, "revision", required=True))
        down_revision = _revision_list(
            _assignment_value(tree, "down_revision", required=True), "down_revision"
        )
        depends_on = _branch_labels(
            _assignment_value(tree, "depends_on", required=False)
        )
        branch_labels = _branch_labels(
            _assignment_value(tree, "branch_labels", required=False)
        )
        if revision in migration_metadata:
            raise GuardError("migration graph has duplicate revisions")
        migration_metadata[revision] = (down_revision, depends_on, branch_labels)
    for revision, (_, _, branch_labels) in migration_metadata.items():
        for label in branch_labels:
            if label in migration_metadata or label in labels:
                raise GuardError(
                    "migration branch label collides with a revision or label"
                )
            labels[label] = revision

    parents: dict[str, tuple[str, ...]] = {}
    versioned_parents: dict[str, tuple[str, ...]] = {}
    for revision, (down_revision, depends_on, _) in migration_metadata.items():
        dependency_revisions = tuple(labels.get(item, item) for item in depends_on)
        edges = down_revision + tuple(
            item for item in dependency_revisions if item not in down_revision
        )
        parents[revision] = edges
        versioned_parents[revision] = down_revision
    parent_revisions = {parent for edges in parents.values() for parent in edges}
    if not parent_revisions <= set(parents):
        raise GuardError("migration graph has a missing parent")
    versioned_parent_revisions = {
        parent for edges in versioned_parents.values() for parent in edges
    }
    heads = set(parents) - versioned_parent_revisions
    if len(heads) != 1:
        raise GuardError("migration graph must have exactly one head")
    def visit(revision: str, visiting: set[str], visited: set[str]) -> None:
        if revision in visiting:
            raise GuardError("migration graph contains a cycle")
        if revision in visited:
            return
        visiting.add(revision)
        for parent in parents[revision]:
            visit(parent, visiting, visited)
        visiting.remove(revision)
        visited.add(revision)

    visited: set[str] = set()
    for revision in parents:
        visit(revision, set(), visited)
    return Graph(
        parents=parents,
        versioned_parents=versioned_parents,
        head=next(iter(heads)),
    )


def _live_revisions() -> set[str]:
    raw = sys.stdin.buffer.read()
    if not raw or len(raw) > 65536:
        raise GuardError("live migration revision output is invalid")
    try:
        values = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise GuardError("live migration revision output is invalid") from exc
    if not values or any(not value for value in values):
        raise GuardError("live migration revision output is invalid")
    revisions = {_revision(value) for value in values}
    if len(revisions) != len(values):
        raise GuardError("live migration revision output is duplicated")
    return revisions


def _target_reaches(target: Graph, revision: str) -> bool:
    pending = [target.head]
    seen: set[str] = set()
    while pending:
        current = pending.pop()
        if current == revision:
            return True
        if current in seen:
            continue
        seen.add(current)
        pending.extend(target.parents[current])
    return False


def _active_ancestry_matches_target(
    active: Graph, target: Graph, live_revision: str
) -> bool:
    pending = [live_revision]
    seen: set[str] = set()
    while pending:
        revision = pending.pop()
        if revision in seen:
            continue
        seen.add(revision)
        if revision not in target.parents:
            return False
        if (
            active.parents[revision] != target.parents[revision]
            or active.versioned_parents[revision]
            != target.versioned_parents[revision]
        ):
            return False
        pending.extend(active.parents[revision])
    return True


def verify(repo_root: str, active_commit: str, target_commit: str) -> None:
    active = _graph(repo_root, _commit(active_commit), require_helper=False)
    target = _graph(repo_root, _commit(target_commit), require_helper=True)
    live_revisions = _live_revisions()
    if live_revisions != {active.head}:
        raise GuardError("live database revisions do not match the active deployment")
    for revision in live_revisions:
        if revision not in target.parents:
            raise GuardError("target migration graph does not contain the live revision")
        if not _active_ancestry_matches_target(active, target, revision):
            raise GuardError("target migration graph rewrites active migration ancestry")
        if not _target_reaches(target, revision):
            raise GuardError("target migration graph is not forward-compatible")


def main(arguments: list[str]) -> None:
    if len(arguments) != 5 or arguments[1] != "verify":
        _fail("usage is verify <repo-root> <active-commit> <target-commit>")
    try:
        verify(arguments[2], arguments[3], arguments[4])
    except GuardError as exc:
        _fail(str(exc))


if __name__ == "__main__":
    main(sys.argv)
