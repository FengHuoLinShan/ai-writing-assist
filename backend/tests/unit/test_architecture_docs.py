from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts/check_architecture_docs.py"
SPEC = importlib.util.spec_from_file_location("check_architecture_docs", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
architecture_docs = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = architecture_docs
SPEC.loader.exec_module(architecture_docs)


def test_architecture_document_inventory_matches_repository() -> None:
    result = architecture_docs.check_inventory(ROOT)

    assert result.errors == []


def test_extract_router_names_handles_quoted_compatibility_route() -> None:
    router_text = """
const routes = {
  home: { title: "Home" },
  "project-settings": { title: "Settings" },
}
"""

    assert architecture_docs._extract_router_names(router_text) == {
        "home",
        "project-settings",
    }


def test_no_impact_acknowledgement_requires_checkbox_and_reason(
    tmp_path: Path,
) -> None:
    event_path = tmp_path / "event.json"
    event_path.write_text(
        json.dumps(
            {
                "pull_request": {
                    "body": (
                        "- [x] 已逐项核对未更新文档，确认无当前架构影响\n\n"
                        "无影响说明（勾选第三项时必填）："
                        "仅调整内部实现，稳定契约未变化"
                    )
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert architecture_docs._read_no_impact_acknowledgement(
        event_path,
        None,
    ) == "仅调整内部实现，稳定契约未变化"


def test_impact_rule_matches_production_files_but_excludes_tests() -> None:
    rule = {
        "source_globs": ["backend/modules/**/*.py"],
        "exclude_globs": [
            "backend/modules/**/test_*.py",
            "backend/modules/**/tests/**/*.py",
        ],
    }

    assert architecture_docs._rule_matches_path(
        rule,
        "backend/modules/world/services/map/playback.py",
    )
    assert not architecture_docs._rule_matches_path(
        rule,
        "backend/modules/world/tests/test_playback.py",
    )


def test_git_changed_files_handles_quoted_paths_across_all_change_sources(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "architecture-docs@example.invalid"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Architecture Docs Test"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "config", "core.quotePath", "true"],
        cwd=repo,
        check=True,
    )
    document_path = "docs/00_整体设计.md"
    document = repo / document_path
    document.parent.mkdir()
    document.write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "add", document_path], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "baseline"], cwd=repo, check=True)
    baseline = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    document.write_text("committed change\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-am", "document change"], cwd=repo, check=True)
    staged_path = "docs/staged path [quote].md"
    staged = repo / staged_path
    staged.write_text("staged\n", encoding="utf-8")
    subprocess.run(["git", "add", staged_path], cwd=repo, check=True)
    working_path = "working path [quote].txt"
    (repo / working_path).write_text("working\n", encoding="utf-8")
    untracked_path = "untracked\npath.txt"
    (repo / untracked_path).write_text("new\n", encoding="utf-8")

    changed = architecture_docs._git_changed_files(repo, baseline, "HEAD")

    assert {
        document_path,
        staged_path,
        working_path,
        untracked_path,
    } <= changed
    assert {document_path} - changed == set()
