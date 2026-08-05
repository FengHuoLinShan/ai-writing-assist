#!/usr/bin/env python3
"""Validate the current architecture-document inventory and change impact."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "docs/architecture/architecture-documents.toml"

TABLE_NAME_RE = re.compile(r"""__tablename__\s*=\s*["']([^"']+)["']""")
TASK_HANDLER_RE = re.compile(
    r"""@task_handler\(\s*["']([^"']+)["']""",
    re.MULTILINE,
)
API_PREFIX_RE = re.compile(
    r"""APIRouter\([^)]*?\bprefix\s*=\s*["']([^"']+)["']""",
    re.DOTALL,
)
MARKDOWN_LINK_RE = re.compile(r"""!?\[[^\]]*]\(([^)]+)\)""")
NO_DOC_IMPACT_RE = re.compile(
    r"""(?mi)^-\s*\[[xX]]\s*已逐项核对未更新文档，确认无当前架构影响\s*$"""
)
NO_DOC_REASON_RE = re.compile(
    r"""(?mi)^无影响说明（勾选第三项时必填）：\s*(\S.+)$"""
)


@dataclass
class CheckResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def merge(self, other: CheckResult) -> None:
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)
        self.notes.extend(other.notes)


def load_registry(root: Path = ROOT) -> dict[str, Any]:
    path = root / "docs/architecture/architecture-documents.toml"
    with path.open("rb") as handle:
        registry = tomllib.load(handle)
    if registry.get("schema_version") != 1:
        raise ValueError("architecture registry schema_version must be 1")
    return registry


def _read(root: Path, relative_path: str) -> str:
    return (root / relative_path).read_text(encoding="utf-8")


def _contains_symbol(text: str, symbol: str) -> bool:
    return re.search(
        rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])",
        text,
    ) is not None


def _component_for_path(
    relative_path: str,
    components: list[dict[str, Any]],
) -> dict[str, Any] | None:
    matches: list[tuple[int, dict[str, Any]]] = []
    for component in components:
        for source_root in component.get("source_roots", []):
            if relative_path == source_root or relative_path.startswith(
                f"{source_root}/"
            ):
                matches.append((len(source_root), component))
    return max(matches, default=(0, None), key=lambda item: item[0])[1]


def _registered_current_documents(registry: dict[str, Any]) -> set[str]:
    documents = set(registry.get("central_documents", []))
    for component in registry.get("components", []):
        documents.update(component.get("design_docs", []))
        documents.update(component.get("code_docs", []))
    return documents


def _markdown_targets(text: str) -> list[str]:
    targets: list[str] = []
    for raw_target in MARKDOWN_LINK_RE.findall(text):
        target = raw_target.strip()
        if target.startswith("<") and ">" in target:
            target = target[1 : target.index(">")]
        elif " " in target:
            target = target.split(" ", 1)[0]
        targets.append(unquote(target))
    return targets


def _check_markdown_links(
    root: Path,
    documents: set[str],
) -> CheckResult:
    result = CheckResult()
    for relative_path in sorted(documents):
        path = root / relative_path
        if path.suffix.lower() != ".md" or not path.exists():
            continue
        for target in _markdown_targets(path.read_text(encoding="utf-8")):
            if (
                not target
                or target.startswith("#")
                or "://" in target
                or target.startswith(("mailto:", "data:"))
            ):
                continue
            target_path = target.split("#", 1)[0]
            if not target_path:
                continue
            resolved = (path.parent / target_path).resolve()
            if not resolved.exists():
                result.errors.append(
                    f"{relative_path}: broken local link target {target!r}"
                )
    return result


def _extract_router_names(router_text: str) -> set[str]:
    start_match = re.search(r"\bconst\s+routes\s*=\s*{", router_text)
    if start_match is None:
        return set()
    block = router_text[start_match.end() :]
    names: set[str] = set()
    for line in block.splitlines():
        if line.startswith("}"):
            break
        match = re.match(
            r"""\s*(?:"([^"]+)"|'([^']+)'|([A-Za-z][\w-]*))\s*:\s*{""",
            line,
        )
        if match:
            names.add(next(value for value in match.groups() if value))
    return names


def _extract_task_handlers(root: Path) -> set[str]:
    handlers: set[str] = set()
    for path in sorted((root / "backend/modules").glob("*/tasks.py")):
        handlers.update(TASK_HANDLER_RE.findall(path.read_text(encoding="utf-8")))
    return handlers


def _extract_tables(root: Path) -> dict[str, str]:
    tables: dict[str, str] = {}
    candidates = [
        *root.glob("backend/modules/**/models.py"),
        *root.glob("backend/modules/**/*_models.py"),
        *root.glob("backend/modules/**/models/*.py"),
        root / "backend/infrastructure/tasks/models.py",
    ]
    for path in sorted(set(candidates)):
        if not path.is_file():
            continue
        relative_path = path.relative_to(root).as_posix()
        for table_name in TABLE_NAME_RE.findall(path.read_text(encoding="utf-8")):
            tables[table_name] = relative_path
    return tables


def _extract_api_prefixes(root: Path) -> dict[str, set[str]]:
    prefixes: dict[str, set[str]] = {}
    candidates = [
        *root.glob("backend/modules/**/*.py"),
        *root.glob("backend/infrastructure/**/api.py"),
    ]
    for path in sorted(set(candidates)):
        if not path.is_file() or "/tests/" in path.as_posix():
            continue
        found = set(API_PREFIX_RE.findall(path.read_text(encoding="utf-8")))
        if found:
            prefixes[path.relative_to(root).as_posix()] = found
    return prefixes


def _check_drawio(root: Path, registry: dict[str, Any]) -> CheckResult:
    result = CheckResult()
    drawio_path = root / "docs/architecture/module-architecture.drawio"
    html_path = root / "docs/architecture/module-architecture.html"
    try:
        xml_root = ElementTree.parse(drawio_path).getroot()
    except ElementTree.ParseError as exc:
        result.errors.append(f"{drawio_path.relative_to(root)}: invalid XML: {exc}")
        return result

    cells = list(xml_root.iter("mxCell"))
    cell_ids = [cell.get("id") for cell in cells if cell.get("id")]
    if len(cell_ids) != len(set(cell_ids)):
        result.errors.append("module architecture diagram contains duplicate cell IDs")
    cell_id_set = set(cell_ids)
    for cell in cells:
        if cell.get("edge") != "1":
            continue
        for attr in ("source", "target"):
            endpoint = cell.get(attr)
            if endpoint and endpoint not in cell_id_set:
                result.errors.append(
                    f"module architecture edge {cell.get('id')} has missing "
                    f"{attr} {endpoint}"
                )

    drawio_text = drawio_path.read_text(encoding="utf-8")
    html_text = html_path.read_text(encoding="utf-8")
    for component in registry.get("components", []):
        if component.get("kind") != "business":
            continue
        name = component["name"]
        if name not in drawio_text:
            result.errors.append(
                f"module architecture drawio omits business module {name}"
            )
        if name not in html_text:
            result.errors.append(f"module architecture HTML omits business module {name}")
    return result


def check_inventory(root: Path = ROOT) -> CheckResult:
    result = CheckResult()
    try:
        registry = load_registry(root)
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        result.errors.append(f"cannot load architecture registry: {exc}")
        return result

    components = registry.get("components", [])
    business_components = {
        component["name"]: component
        for component in components
        if component.get("kind") == "business"
    }
    actual_business_modules = {
        path.name
        for path in (root / "backend/modules").iterdir()
        if path.is_dir() and (path / "__init__.py").exists()
    }
    registered_business_modules = set(business_components)
    if actual_business_modules != registered_business_modules:
        missing = sorted(actual_business_modules - registered_business_modules)
        stale = sorted(registered_business_modules - actual_business_modules)
        if missing:
            result.errors.append(
                f"unregistered business modules: {', '.join(missing)}"
            )
        if stale:
            result.errors.append(
                f"registry contains removed business modules: {', '.join(stale)}"
            )

    architecture_files = set(registry.get("architecture_files", []))
    actual_architecture_files = {
        path.relative_to(root).as_posix()
        for path in (root / "docs/architecture").iterdir()
        if path.is_file()
    }
    if architecture_files != actual_architecture_files:
        missing = sorted(actual_architecture_files - architecture_files)
        stale = sorted(architecture_files - actual_architecture_files)
        if missing:
            result.errors.append(
                f"unregistered docs/architecture files: {', '.join(missing)}"
            )
        if stale:
            result.errors.append(
                f"missing registered architecture files: {', '.join(stale)}"
            )

    current_documents = _registered_current_documents(registry)
    for relative_path in sorted(current_documents | architecture_files):
        if not (root / relative_path).is_file():
            result.errors.append(
                f"registered current document is missing: {relative_path}"
            )

    expected_module_docs = {
        document
        for component in components
        for document in component.get("design_docs", [])
        if document.startswith("docs/modules/")
    }
    actual_module_docs = {
        path.relative_to(root).as_posix()
        for path in (root / "docs/modules").glob("*.md")
    }
    if expected_module_docs != actual_module_docs:
        missing = sorted(actual_module_docs - expected_module_docs)
        stale = sorted(expected_module_docs - actual_module_docs)
        if missing:
            result.errors.append(
                f"unregistered current module documents: {', '.join(missing)}"
            )
        if stale:
            result.errors.append(
                f"missing current module documents: {', '.join(stale)}"
            )

    for catalog_path in registry.get("module_catalogs", []):
        catalog = _read(root, catalog_path)
        for name in sorted(business_components):
            if not _contains_symbol(catalog, name):
                result.errors.append(
                    f"{catalog_path}: business module {name!r} is not cataloged"
                )

    adr_index_path = registry["adr_index"]
    adr_index = _read(root, adr_index_path)
    adr_paths = {
        path.relative_to(root).as_posix()
        for path in (root / "docs/adr").glob("*.md")
        if path.name != "README.md"
    }
    for adr_path in sorted(adr_paths):
        if Path(adr_path).name not in adr_index:
            result.errors.append(f"{adr_index_path}: ADR not indexed: {adr_path}")

    database_catalog_path = registry["database_catalog"]
    database_catalog = _read(root, database_catalog_path)
    tables = _extract_tables(root)
    for table_name, source_path in sorted(tables.items()):
        if not _contains_symbol(database_catalog, table_name):
            result.errors.append(
                f"{database_catalog_path}: table {table_name!r} from "
                f"{source_path} is omitted"
            )
        component = _component_for_path(source_path, components)
        if component is None:
            continue
        design_text = "\n".join(
            _read(root, path) for path in component.get("design_docs", [])
        )
        code_text = "\n".join(
            _read(root, path) for path in component.get("code_docs", [])
        )
        if (
            component.get("design_docs")
            and not _contains_symbol(design_text, table_name)
        ):
            result.errors.append(
                f"{component['name']} design docs omit owned table {table_name!r}"
            )
        if component.get("code_docs") and not _contains_symbol(
            code_text,
            table_name,
        ):
            result.errors.append(
                f"{component['name']} code docs omit owned table {table_name!r}"
            )

    discovered_prefixes = _extract_api_prefixes(root)
    prefixes_by_component: dict[str, set[str]] = {
        component["name"]: set() for component in components
    }
    for source_path, prefixes in discovered_prefixes.items():
        component = _component_for_path(source_path, components)
        if component is None:
            result.errors.append(
                f"API prefixes have no registered component: {source_path}"
            )
            continue
        prefixes_by_component[component["name"]].update(prefixes)
    for component in components:
        expected = set(component.get("api_prefixes", []))
        actual = prefixes_by_component.get(component["name"], set())
        if expected != actual:
            result.errors.append(
                f"{component['name']} API prefix registry mismatch: "
                f"registered={sorted(expected)}, code={sorted(actual)}"
            )
        design_text = "\n".join(
            _read(root, path) for path in component.get("design_docs", [])
        )
        code_text = "\n".join(
            _read(root, path) for path in component.get("code_docs", [])
        )
        for prefix in sorted(actual):
            if component.get("design_docs") and prefix not in design_text:
                result.errors.append(
                    f"{component['name']} design docs omit API prefix {prefix!r}"
                )
            if component.get("code_docs") and prefix not in code_text:
                result.errors.append(
                    f"{component['name']} code docs omit API prefix {prefix!r}"
                )

    router_names = _extract_router_names(
        _read(root, "frontend-console/router.js")
    )
    if not router_names:
        result.errors.append("could not discover frontend hash routes")
    for catalog_path in registry.get("frontend_route_catalogs", []):
        catalog = _read(root, catalog_path)
        for route_name in sorted(router_names):
            if not _contains_symbol(catalog, route_name):
                result.errors.append(
                    f"{catalog_path}: frontend route {route_name!r} is omitted"
                )

    task_handlers = _extract_task_handlers(root)
    for catalog_path in registry.get("task_catalogs", []):
        catalog = _read(root, catalog_path)
        for handler_name in sorted(task_handlers):
            if not _contains_symbol(catalog, handler_name):
                result.errors.append(
                    f"{catalog_path}: task handler {handler_name!r} is omitted"
                )

    prompt_catalog_path = registry["prompt_catalog"]
    prompt_catalog = _read(root, prompt_catalog_path)
    for prompt_path in sorted((root / "backend/prompts").glob("*.md")):
        if f"`{prompt_path.name}`" not in prompt_catalog:
            result.errors.append(
                f"{prompt_catalog_path}: prompt file {prompt_path.name!r} is omitted"
            )

    current_documents.update(adr_paths)
    result.merge(_check_markdown_links(root, current_documents))
    result.merge(_check_drawio(root, registry))

    result.notes.append(
        "inventory: "
        f"{len(business_components)} business modules, "
        f"{len(tables)} ORM tables, "
        f"{len(task_handlers)} task handlers, "
        f"{len(router_names)} frontend routes, "
        f"{len(adr_paths)} ADR files"
    )
    return result


def _git_changed_files(
    root: Path,
    base_ref: str,
    head_ref: str,
) -> set[str]:
    committed_command = [
        "git",
        "diff",
        "--name-only",
        "-z",
        "--diff-filter=ACMRD",
        f"{base_ref}...{head_ref}",
    ]
    completed = subprocess.run(
        committed_command,
        cwd=root,
        check=True,
        capture_output=True,
    )
    changed = _decode_git_paths(completed.stdout)
    if head_ref != "HEAD":
        return changed

    working_tree = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            "-z",
            "--diff-filter=ACMRD",
            "HEAD",
        ],
        cwd=root,
        check=True,
        capture_output=True,
    )
    changed.update(_decode_git_paths(working_tree.stdout))
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    changed.update(_decode_git_paths(untracked.stdout))
    return changed


def _decode_git_paths(output: bytes) -> set[str]:
    return {
        os.fsdecode(path)
        for path in output.split(b"\0")
        if path
    }


def _decode_git_diagnostic(output: bytes | str | None) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        return os.fsdecode(output).strip()
    return output.strip()


def _expand_required_documents(
    required_documents: list[str],
    component: dict[str, Any] | None,
) -> set[str]:
    expanded: set[str] = set()
    for document in required_documents:
        if document == "{component_design_docs}":
            if component is not None:
                expanded.update(component.get("design_docs", []))
        elif document == "{component_code_docs}":
            if component is not None:
                expanded.update(component.get("code_docs", []))
        else:
            expanded.add(document)
    return expanded


def _rule_matches_path(rule: dict[str, Any], relative_path: str) -> bool:
    included = any(
        fnmatch.fnmatch(relative_path, pattern)
        for pattern in rule.get("source_globs", [])
    )
    excluded = any(
        fnmatch.fnmatch(relative_path, pattern)
        for pattern in rule.get("exclude_globs", [])
    )
    return included and not excluded


def _read_no_impact_acknowledgement(
    event_path: Path | None,
    direct_reason: str | None,
) -> str | None:
    if direct_reason and direct_reason.strip():
        return direct_reason.strip()
    if event_path is None or not event_path.is_file():
        return None
    event = json.loads(event_path.read_text(encoding="utf-8"))
    body = str((event.get("pull_request") or {}).get("body") or "")
    if NO_DOC_IMPACT_RE.search(body) is None:
        return None
    reason_match = NO_DOC_REASON_RE.search(body)
    if reason_match is None:
        return None
    reason = reason_match.group(1).strip()
    if reason in {"无", "无影响", "N/A", "n/a", "待补充"}:
        return None
    return reason


def check_impact(
    base_ref: str,
    *,
    head_ref: str = "HEAD",
    event_path: Path | None = None,
    no_change_reason: str | None = None,
    root: Path = ROOT,
) -> CheckResult:
    result = CheckResult()
    registry = load_registry(root)
    components = registry.get("components", [])
    try:
        changed_files = _git_changed_files(root, base_ref, head_ref)
    except subprocess.CalledProcessError as exc:
        stderr = _decode_git_diagnostic(exc.stderr)
        result.errors.append(
            f"cannot calculate architecture-doc impact from {base_ref}: {stderr}"
        )
        return result

    required_documents: set[str] = set()
    matched_rules: set[str] = set()
    for rule in registry.get("impact_rules", []):
        for changed_file in changed_files:
            if not _rule_matches_path(rule, changed_file):
                continue
            component = _component_for_path(changed_file, components)
            required_documents.update(
                _expand_required_documents(
                    rule.get("required_documents", []),
                    component,
                )
            )
            matched_rules.add(rule["id"])

    missing_documents = sorted(required_documents - changed_files)
    if missing_documents:
        acknowledgement = _read_no_impact_acknowledgement(
            event_path,
            no_change_reason,
        )
        detail = (
            f"impact rules {', '.join(sorted(matched_rules))} require review of: "
            f"{', '.join(missing_documents)}"
        )
        if acknowledgement:
            result.warnings.append(
                f"{detail}; explicitly acknowledged as no current-doc change: "
                f"{acknowledgement}"
            )
        else:
            result.errors.append(detail)
            result.errors.append(
                "update the listed documents, or in the PR template check "
                "'已逐项核对未更新文档，确认无当前架构影响' and provide a reason"
            )
    elif required_documents:
        result.notes.append(
            "impact: all required documents changed for rules "
            f"{', '.join(sorted(matched_rules))}"
        )
    else:
        result.notes.append("impact: no architecture-sensitive source changes detected")
    return result


def _print_result(result: CheckResult) -> None:
    for note in result.notes:
        print(f"NOTE: {note}")
    for warning in result.warnings:
        print(f"WARNING: {warning}")
    for error in result.errors:
        print(f"ERROR: {error}", file=sys.stderr)
    if not result.errors:
        print("Architecture documentation checks passed.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-ref",
        help="Git base ref for change-impact validation",
    )
    parser.add_argument(
        "--head-ref",
        default="HEAD",
        help="Git head ref for change-impact validation (default: HEAD)",
    )
    parser.add_argument(
        "--event-path",
        type=Path,
        help="GitHub pull_request event JSON used for an explicit no-change reason",
    )
    parser.add_argument(
        "--no-change-reason",
        help="Explicit local acknowledgement for reviewed but unchanged documents",
    )
    args = parser.parse_args()

    result = check_inventory(ROOT)
    if args.base_ref:
        result.merge(
            check_impact(
                args.base_ref,
                head_ref=args.head_ref,
                event_path=args.event_path,
                no_change_reason=args.no_change_reason,
                root=ROOT,
            )
        )
    _print_result(result)
    return 1 if result.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
