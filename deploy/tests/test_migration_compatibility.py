from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

DEPLOY_ROOT = Path(__file__).parents[1]
HELPER = DEPLOY_ROOT / "scripts" / "migration_compatibility.py"


def _git(repo: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write_migration(repo: Path, name: str, source: str) -> None:
    directory = repo / "backend" / "alembic" / "versions"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(source)


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", message)
    return _git(repo, "rev-parse", "HEAD")


def _repo(
    tmp_path: Path, *, legacy_active_without_helper: bool = False
) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "migration-tests@example.com")
    _git(repo, "config", "user.name", "Migration Tests")
    helper_path = repo / "deploy" / "scripts"
    if not legacy_active_without_helper:
        helper_path.mkdir(parents=True)
        helper_path.joinpath("migration_compatibility.py").write_text(HELPER.read_text())
    _write_migration(repo, "a.py", 'revision = "a"\ndown_revision = None\n')
    active = _commit(repo, "active")
    if legacy_active_without_helper:
        helper_path.mkdir(parents=True)
        helper_path.joinpath("migration_compatibility.py").write_text(HELPER.read_text())
    _write_migration(repo, "b.py", 'revision = "b"\ndown_revision = "a"\n')
    target = _commit(repo, "target")
    return repo, active, target


def _verify(
    repo: Path, active: str, target: str, live: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HELPER), "verify", str(repo), active, target],
        input=live,
        capture_output=True,
        text=True,
    )


def _verify_target(
    repo: Path, target: str, restored: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HELPER), "verify-target", str(repo), target],
        input=restored,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("which", ["same", "forward"])
def test_accepts_same_or_forward_graph(tmp_path: Path, which: str) -> None:
    repo, active, target = _repo(tmp_path)
    result = _verify(repo, active, active if which == "same" else target, "a\n")

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("restored", ["a\n", "b\n"])
def test_target_revision_guard_accepts_reachable_revision(
    tmp_path: Path, restored: str
) -> None:
    repo, _active, target = _repo(tmp_path)

    result = _verify_target(repo, target, restored)

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("restored", ["orphan\n", "a\nb\n"])
def test_target_revision_guard_rejects_unknown_or_multiple_revisions(
    tmp_path: Path, restored: str
) -> None:
    repo, _active, target = _repo(tmp_path)

    result = _verify_target(repo, target, restored)

    assert result.returncode != 0
    assert "Migration compatibility guard rejected" in result.stderr


def test_accepts_legacy_active_without_guard_helper_when_target_has_one(
    tmp_path: Path,
) -> None:
    repo, active, target = _repo(tmp_path, legacy_active_without_helper=True)

    result = _verify(repo, active, target, "a\n")

    assert result.returncode == 0, result.stderr


def test_rejects_reverse_or_unknown_target_graph(tmp_path: Path) -> None:
    repo, active, target = _repo(tmp_path)

    result = _verify(repo, target, active, "b\n")

    assert result.returncode != 0
    assert "does not contain the live revision" in result.stderr


def test_rejects_same_revision_with_rewritten_active_ancestry(tmp_path: Path) -> None:
    repo, _active, live = _repo(tmp_path)
    _write_migration(repo, "x.py", 'revision = "x"\ndown_revision = None\n')
    _write_migration(repo, "a.py", 'revision = "a"\ndown_revision = "x"\n')
    _write_migration(repo, "c.py", 'revision = "c"\ndown_revision = "b"\n')
    target = _commit(repo, "rewrite b ancestry")

    result = _verify(repo, live, target, "b\n")

    assert result.returncode != 0
    assert "rewrites active migration ancestry" in result.stderr


def test_accepts_static_merge_and_depends_on_edges(tmp_path: Path) -> None:
    repo, active, _target = _repo(tmp_path)
    _write_migration(repo, "side.py", 'revision: str = "side"\ndown_revision = "a"\n')
    _write_migration(
        repo,
        "merge.py",
        'revision = "merge"\n'
        'down_revision = ("b", "side")\n'
        "depends_on = []\n"
        'branch_labels = ("main",)\n',
    )
    target = _commit(repo, "merge")

    result = _verify(repo, active, target, "a\n")

    assert result.returncode == 0, result.stderr


def test_rejects_depends_on_that_would_hide_an_alembic_multi_head(tmp_path: Path) -> None:
    repo, active, _target = _repo(tmp_path)
    _write_migration(repo, "side.py", 'revision = "side"\ndown_revision = "a"\n')
    _write_migration(
        repo,
        "dependent.py",
        'revision = "dependent"\ndown_revision = "b"\ndepends_on = "side"\n',
    )
    target = _commit(repo, "depends-on multihead")

    result = _verify(repo, active, target, "a\n")

    assert result.returncode != 0
    assert "exactly one head" in result.stderr


def test_resolves_depends_on_branch_label_without_creating_a_head_edge(
    tmp_path: Path,
) -> None:
    repo, active, _target = _repo(tmp_path)
    _write_migration(
        repo,
        "a.py",
        'revision = "a"\ndown_revision = None\nbranch_labels = "anchor"\n',
    )
    _write_migration(
        repo,
        "b.py",
        'revision = "b"\ndown_revision = "a"\ndepends_on = "anchor"\n',
    )
    target = _commit(repo, "depends on branch label")

    result = _verify(repo, active, target, "a\n")

    assert result.returncode == 0, result.stderr


def test_rejects_branch_label_collision_with_a_revision(tmp_path: Path) -> None:
    repo, active, _target = _repo(tmp_path)
    _write_migration(
        repo,
        "b.py",
        'revision = "b"\ndown_revision = "a"\nbranch_labels = "a"\n',
    )
    target = _commit(repo, "label collision")

    result = _verify(repo, active, target, "a\n")

    assert result.returncode != 0
    assert "collides" in result.stderr


@pytest.mark.parametrize(
    ("name", "source", "expected"),
    [
        ("dynamic.py", 'revision = build()\ndown_revision = "b"\n', "not a literal"),
        ("duplicate.py", 'revision = "b"\ndown_revision = "b"\n', "duplicate"),
        (
            "missing.py",
            'revision = "missing"\ndown_revision = "gone"\n',
            "missing parent",
        ),
        ("cycle.py", 'revision = "cycle"\ndown_revision = "cycle"\n', "cycle"),
        ("head.py", 'revision = "head"\ndown_revision = None\n', "exactly one head"),
    ],
)
def test_rejects_malformed_graph_metadata(
    tmp_path: Path, name: str, source: str, expected: str
) -> None:
    repo, active, _target = _repo(tmp_path)
    _write_migration(repo, name, source)
    target = _commit(repo, name)

    result = _verify(repo, active, target, "a\n")

    assert result.returncode != 0
    assert expected in result.stderr


def test_rejects_database_drift_duplicate_rows_and_uncommitted_source(
    tmp_path: Path,
) -> None:
    repo, active, target = _repo(tmp_path)
    _write_migration(
        repo, "working.py", 'revision = "working"\ndown_revision = missing()\n'
    )

    drift = _verify(repo, active, target, "wrong\n")
    duplicate = _verify(repo, active, target, "a\na\n")
    multiple_live_heads = _verify(repo, active, target, "a\nb\n")
    committed_only = _verify(repo, active, target, "a\n")

    assert drift.returncode != 0
    assert "do not match" in drift.stderr
    assert duplicate.returncode != 0
    assert multiple_live_heads.returncode != 0
    assert "do not match" in multiple_live_heads.stderr
    assert committed_only.returncode == 0, committed_only.stderr


def test_rejects_missing_or_symlinked_committed_guard_assets(tmp_path: Path) -> None:
    repo, active, target = _repo(tmp_path)
    _git(repo, "rm", "deploy/scripts/migration_compatibility.py")
    missing_helper = _commit(repo, "helper missing")

    missing = _verify(repo, active, missing_helper, "a\n")
    assert missing.returncode != 0
    assert "asset is missing or unsafe" in missing.stderr

    repo, active, target = _repo(tmp_path / "symlink")
    helper = repo / "deploy" / "scripts" / "migration_compatibility.py"
    helper.unlink()
    helper.symlink_to("elsewhere.py")
    symlink_helper = _commit(repo, "helper symlink")
    symlink = _verify(repo, active, symlink_helper, "a\n")
    assert symlink.returncode != 0
    assert "asset is missing or unsafe" in symlink.stderr
