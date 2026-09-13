"""CI selection must account for every changed path and fail closed."""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/classify_ci_changes.py"
spec = importlib.util.spec_from_file_location("classify_ci_changes", SCRIPT)
selector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(selector)


@pytest.mark.parametrize(
    ("paths", "expected"),
    [
        ([], set()),
        (["docs/design.md", "backend/README.md"], set()),
        (["README.md"], {"images"}),
        (["backend/tests/unit/test_example.py"], {"backend"}),
        (["backend/modules/world/tests/test_example.py"], {"backend"}),
        (["backend/tests/e2e/test_example.py"], {"backend", "postgresql"}),
        (["backend/conftest.py"], {"backend", "postgresql", "browser", "images"}),
        (["frontend-console/tests/example.test.js"], {"frontend"}),
        (
            ["frontend-console/e2e/visual-example.spec.js-snapshots/page-darwin.png"],
            set(),
        ),
        (["frontend-console/e2e/fixtures.js"], {"frontend", "browser", "images"}),
        (
            [
                "frontend-console/e2e/visual-example.spec.js-snapshots/page-darwin.png",
                "backend/app/main.py",
            ],
            {"backend", "postgresql", "browser", "images"},
        ),
        (["backend/app/main.py"], {"backend", "postgresql", "browser", "images"}),
        (["frontend-console/src/App.vue"], {"frontend", "browser", "images"}),
        (["backend/Dockerfile"], {"backend", "images"}),
        (["frontend-console/Dockerfile"], {"backend", "images"}),
        (["deploy/scripts/release.sh"], {"backend", "images"}),
        (["frontend-console/package-lock.json", "backend/uv.lock"], selector.GATES),
        ([".github/workflows/frontend-ci.yml"], selector.GATES),
        (["scripts/tool.py"], selector.GATES),
        (["Makefile"], selector.GATES),
        (["new-directory/unknown"], selector.GATES),
    ],
)
def test_path_selection(paths, expected):
    assert selector.classify(paths) == expected


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def run_selector(repo, event, event_name="pull_request"):
    event_path = repo / "event.json"
    event_path.write_text(json.dumps(event))
    output = repo / "output"
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=repo,
        env={
            **os.environ,
            "GITHUB_EVENT_NAME": event_name,
            "GITHUB_EVENT_PATH": str(event_path),
            "GITHUB_OUTPUT": str(output),
        },
        capture_output=True,
        text=True,
    )
    return result, output.read_text() if output.exists() else ""


def test_git_diff_includes_deleted_and_both_renamed_paths(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "ci-test@example.invalid")
    git(tmp_path, "config", "user.name", "CI test")
    (tmp_path / "backend").mkdir()
    (tmp_path / "frontend-console").mkdir()
    (tmp_path / "backend/old.py").write_text("old\n")
    (tmp_path / "frontend-console/deleted.js").write_text("deleted\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "base")
    base = git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "backend/old.py").rename(tmp_path / "frontend-console/with\nnewline.js")
    (tmp_path / "frontend-console/deleted.js").unlink()
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "rename and delete")
    head = git(tmp_path, "rev-parse", "HEAD")
    result, output = run_selector(
        tmp_path, {"pull_request": {"base": {"sha": base}, "head": {"sha": head}}}
    )
    assert result.returncode == 0, result.stderr
    assert set(output.splitlines()) == {f"{gate}=true" for gate in selector.GATES} | {
        "browser_suite=test:e2e:smoke"
    }


@pytest.mark.parametrize("sha", ["0" * 40, "--output=/tmp/unsafe", "main"])
def test_invalid_or_unavailable_diff_fails_without_outputs(tmp_path, sha):
    result, output = run_selector(
        tmp_path, {"pull_request": {"base": {"sha": sha}, "head": {"sha": "1" * 40}}}
    )
    assert result.returncode != 0
    assert output == ""


def test_main_push_selects_all_without_needing_git(tmp_path):
    result, output = run_selector(tmp_path, {"ref": "refs/heads/main"}, "push")
    assert result.returncode == 0, result.stderr
    assert set(output.splitlines()) == {f"{gate}=true" for gate in selector.GATES} | {
        "browser_suite=test:e2e:functional"
    }


def test_unsupported_event_fails_without_outputs(tmp_path):
    result, output = run_selector(tmp_path, {}, "workflow_dispatch")
    assert result.returncode != 0
    assert output == ""


@pytest.mark.parametrize("paths, expected", [
    (["frontend-console/e2e/generate.spec.js"], "test:e2e:functional"),
    (["frontend-console/e2e/helpers/workbench.js"], "test:e2e:functional"),
    (["frontend-console/playwright.functional.config.js"], "test:e2e:functional"),
    (["frontend-console/package.json"], "test:e2e:functional"),
    ([".github/workflows/frontend-ci.yml"], "test:e2e:functional"),
    (["frontend-console/e2e/visual-world.spec.js-snapshots/old.png"], "test:e2e:smoke"),
    (["frontend-console/styles.css"], "test:e2e:smoke"),
])
def test_browser_suite_covers_changed_behavior_collection(paths, expected):
    assert selector.browser_suite(paths) == expected
