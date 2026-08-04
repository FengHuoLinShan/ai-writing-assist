from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

DEPLOY_ROOT = Path(__file__).parents[1]


def _git(repo_root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo_root), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _repository(tmp_path: Path) -> tuple[Path, str, str]:
    repo_root = tmp_path / "repo"
    shutil.copytree(DEPLOY_ROOT, repo_root / "deploy")
    (repo_root / "backend").mkdir()
    (repo_root / "backend" / "Dockerfile").write_text("FROM scratch\n")
    (repo_root / "frontend-console").mkdir()
    (repo_root / "frontend-console" / "Dockerfile").write_text("FROM scratch\n")
    (repo_root / "tracked.txt").write_text("target A\n")
    _git(repo_root, "init", "-q")
    _git(repo_root, "config", "user.email", "deploy-tests@example.com")
    _git(repo_root, "config", "user.name", "Deployment Tests")
    _git(repo_root, "add", "deploy", "backend", "frontend-console", "tracked.txt")
    _git(repo_root, "commit", "-qm", "target A")
    commit_a = _git(repo_root, "rev-parse", "HEAD")

    origin_root = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-q", str(origin_root)], check=True)
    _git(repo_root, "remote", "add", "origin", str(origin_root))
    _git(repo_root, "push", "-qu", "origin", "HEAD:main")

    (repo_root / "tracked.txt").write_text("target B\n")
    _git(repo_root, "add", "tracked.txt")
    _git(repo_root, "commit", "-qm", "target B")
    commit_b = _git(repo_root, "rev-parse", "HEAD")
    _git(repo_root, "push", "origin", "HEAD:main")
    _git(repo_root, "fetch", "origin")
    return repo_root, commit_a, commit_b


def _guard(repo_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "/bin/sh",
            "-c",
            '. "$0"; verify_deployment_checkout',
            "deploy/scripts/common.sh",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=10,
    )


def _make_unmerged(repo_root: Path) -> None:
    commit_a = _git(repo_root, "rev-parse", "HEAD~1")
    current_commit = _git(repo_root, "rev-parse", "HEAD")
    _git(repo_root, "checkout", "-qb", "other", commit_a)
    (repo_root / "tracked.txt").write_text("other branch\n")
    _git(repo_root, "add", "tracked.txt")
    _git(repo_root, "commit", "-qm", "other branch")
    _git(repo_root, "checkout", "-q", "--detach", current_commit)
    (repo_root / "tracked.txt").write_text("current branch\n")
    _git(repo_root, "add", "tracked.txt")
    _git(repo_root, "commit", "-qm", "current branch")
    result = subprocess.run(
        ["git", "-C", str(repo_root), "merge", "other"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0


def _stage_runtime_environment(repo_root: Path) -> None:
    runtime_path = repo_root / "deploy" / ".env.production"
    runtime_path.write_text("staged runtime drift\n")
    _git(repo_root, "add", "-f", "deploy/.env.production")


def _modify_tracked_runtime_environment(repo_root: Path) -> None:
    _stage_runtime_environment(repo_root)
    _git(repo_root, "commit", "-qm", "tracked runtime path")
    (repo_root / "deploy" / ".env.production").write_text("modified runtime drift\n")


def test_checkout_guard_allows_only_operational_runtime_paths(tmp_path: Path) -> None:
    repo_root, _commit_a, _commit_b = _repository(tmp_path)
    deploy_root = repo_root / "deploy"
    (deploy_root / ".env.production").write_text("secret=runtime-only\n")
    state_dir = deploy_root / ".state"
    state_dir.mkdir()
    (state_dir / "current-release").write_text("runtime-only\n")
    backup_dir = deploy_root / "backups"
    backup_dir.mkdir()
    (backup_dir / "backup.dump").write_text("runtime-only\n")

    result = _guard(repo_root)

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_checkout_guard_rejects_all_non_operational_drift_without_echoing_paths(
    tmp_path: Path,
) -> None:
    preparations = {
        "tracked": lambda repo: (repo / "tracked.txt").write_text("changed\n"),
        "staged": lambda repo: (
            (repo / "tracked.txt").write_text("staged\n"),
            _git(repo, "add", "tracked.txt"),
        ),
        "untracked": lambda repo: (repo / "backend" / "untracked.py").write_text(
            "untracked\n"
        ),
        "ignored": lambda repo: (
            (repo / ".git" / "info" / "exclude").write_text("ignored-source.py\n"),
            (repo / "ignored-source.py").write_text("ignored\n"),
        ),
        "unmerged": _make_unmerged,
        "runtime-staged": _stage_runtime_environment,
        "runtime-modified": _modify_tracked_runtime_environment,
        "odd": lambda repo: (repo / "frontend-console" / "odd\nsource.txt").write_text(
            "untracked\n"
        ),
    }

    for name, prepare in preparations.items():
        repo_root, _commit_a, _commit_b = _repository(tmp_path / name)
        prepare(repo_root)

        result = _guard(repo_root)

        assert result.returncode != 0
        assert result.stdout == ""
        assert "Deployment checkout is unsafe" in result.stderr
        assert "odd\nsource.txt" not in result.stderr


def test_checkout_guard_rejects_a_clean_commit_that_tracks_runtime_paths(
    tmp_path: Path,
) -> None:
    for runtime_name in (
        "deploy/.state/current-release",
        "deploy/.state",
        "deploy/backups",
    ):
        repo_root, _commit_a, _commit_b = _repository(
            tmp_path / runtime_name.replace("/", "-")
        )
        runtime_path = repo_root / runtime_name
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        runtime_path.write_text("tracked runtime path\n")
        _git(repo_root, "add", "-f", runtime_name)
        _git(repo_root, "commit", "-qm", "tracked runtime path")

        result = _guard(repo_root)

        assert result.returncode != 0
        assert result.stdout == ""
        assert "Deployment checkout is unsafe" in result.stderr


def test_fixed_snapshot_uses_only_target_tree(tmp_path: Path) -> None:
    repo_root, commit_a, _commit_b = _repository(tmp_path)
    deploy_root = repo_root / "deploy"
    (deploy_root / ".env.production").write_text("runtime secret\n")
    (deploy_root / ".state").mkdir()
    (deploy_root / ".state" / "current-release").write_text("runtime state\n")
    (deploy_root / "backups").mkdir()
    (deploy_root / "backups" / "backup.dump").write_text("runtime backup\n")
    (repo_root / "backend" / "untracked.py").write_text("untracked\n")
    (repo_root / ".git" / "info" / "exclude").write_text("ignored-source.py\n")
    (repo_root / "ignored-source.py").write_text("ignored\n")

    script = r'''
. "$0"
prepare_fixed_commit_build_context "$1"
python3 - "$FIXED_COMMIT_BUILD_CONTEXT_ROOT" "$FIXED_COMMIT_BUILD_CONTEXT_OVERRIDE" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
source = root / "source"
override = json.loads(Path(sys.argv[2]).read_text())
print(json.dumps({
    "root": str(root),
    "source": str(source),
    "tracked": (source / "tracked.txt").read_text(),
    "runtime_secret": (source / "deploy" / ".env.production").exists(),
    "runtime_state": (source / "deploy" / ".state").exists(),
    "runtime_backups": (source / "deploy" / "backups").exists(),
    "untracked": (source / "backend" / "untracked.py").exists(),
    "ignored": (source / "ignored-source.py").exists(),
    "override": override,
}))
PY
root=$FIXED_COMMIT_BUILD_CONTEXT_ROOT
cleanup_fixed_commit_build_context
test ! -e "$root"
'''
    result = subprocess.run(
        ["/bin/sh", "-c", script, "deploy/scripts/common.sh", commit_a],
        cwd=repo_root,
        env=os.environ | {"TMPDIR": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    snapshot = json.loads(result.stdout)
    source = snapshot["source"]
    assert snapshot["tracked"] == "target A\n"
    assert not any(
        snapshot[name]
        for name in (
            "runtime_secret",
            "runtime_state",
            "runtime_backups",
            "untracked",
            "ignored",
        )
    )
    expected_dockerfiles = {
        "api": "backend/Dockerfile",
        "worker": "backend/Dockerfile",
        "frontend": "frontend-console/Dockerfile",
        "migrate": "backend/Dockerfile",
        "account-maintenance": "backend/Dockerfile",
    }
    for service, dockerfile in expected_dockerfiles.items():
        build = snapshot["override"]["services"][service]["build"]
        assert build == {"context": source, "dockerfile": dockerfile}
