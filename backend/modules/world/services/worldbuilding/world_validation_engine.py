"""Pure validation rules and ReviewPacket construction for World Bible state."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from datetime import date
from pathlib import PurePosixPath
from typing import Any

from core.errors import ValidationError
from modules.world.schemas import (
    WorldDesignCheckpointPayload,
    WorldValidationFinding,
    WorldValidationPolicy,
    WorldValidationSemanticOutput,
)

_WIKILINK_RE = re.compile(r"\[\[([^\]\n]+)\]\]")


def _document_metadata(item: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(item.get("metadata") or {})
    imported = metadata.get("worldbook_import")
    frontmatter = (
        dict(imported.get("frontmatter") or {}) if isinstance(imported, dict) else {}
    )
    return {**metadata, **frontmatter}


def _frontmatter(item: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(item.get("metadata") or {})
    imported = metadata.get("worldbook_import")
    if isinstance(imported, dict) and isinstance(imported.get("frontmatter"), dict):
        return dict(imported["frontmatter"])
    return {
        key: value
        for key, value in metadata.items()
        if key not in {"worldbook_import", "validation_policy"}
    }


def _frontmatter_type_matches(value: Any, expected: str) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "date":
        if not isinstance(value, str):
            return False
        try:
            date.fromisoformat(value)
        except ValueError:
            return False
        return True
    if expected == "number":
        return (
            not isinstance(value, bool)
            and isinstance(value, int | float)
            and math.isfinite(float(value))
        )
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "array:string":
        return isinstance(value, list) and all(isinstance(item, str) for item in value)
    if expected == "array:wikilink":
        return isinstance(value, list) and all(
            isinstance(item, str) and re.fullmatch(r"\[\[[^\]\n]+\]\]", item)
            for item in value
        )
    return False


def _aliases(item: dict[str, Any]) -> list[str]:
    values = _document_metadata(item).get("aliases", [])
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def _normalized_name(value: object) -> str:
    return str(value or "").strip().casefold()


def _link_parts(value: str) -> tuple[str, str]:
    raw = value.split("|", 1)[0]
    target, _, anchor = raw.partition("#")
    return target.split("^", 1)[0].strip(), anchor.strip()


def _entry_link_keys(entry: dict[str, Any]) -> set[str]:
    keys = {
        _normalized_name(entry.get("title")),
        *(_normalized_name(alias) for alias in entry.get("aliases") or _aliases(entry)),
    }
    path = str(entry.get("source_path") or "").strip()
    if path:
        keys.add(_normalized_name(path))
        parts = PurePosixPath(PurePosixPath(path).with_suffix("")).parts
        keys.update(
            _normalized_name(PurePosixPath(*parts[index:])) for index in range(len(parts))
        )
    return {key for key in keys if key}


def _link_lookup(manifest: dict[str, Any], items: list[dict[str, Any]]) -> set[str]:
    lookup: set[str] = set()
    entries = [
        *list(manifest.get("link_lookup") or manifest.get("lookup") or []),
        *items,
    ]
    for entry in entries:
        lookup.update(_entry_link_keys(entry))
    return lookup


def _anchor_lookup(
    manifest: dict[str, Any], items: list[dict[str, Any]]
) -> dict[str, set[str]]:
    lookup: dict[str, set[str]] = defaultdict(set)
    entries = [
        *list(manifest.get("link_lookup") or manifest.get("lookup") or []),
        *items,
    ]
    for entry in entries:
        anchors = {
            _normalized_name(value)
            for value in entry.get("anchors") or []
            if str(value).strip()
        }
        for key in _entry_link_keys(entry):
            lookup[key].update(anchors)
    return lookup


def _line_number(text: str, offset: int) -> int:
    return text[:offset].count("\n") + 1


def _field_value(item: dict[str, Any], path: str) -> Any:
    value: Any = _document_metadata(item)
    for part in path.split("."):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", part) or not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def stable_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
    ).hexdigest()


def _finding(
    *,
    layer: str,
    severity: str,
    category: str,
    action: str,
    message: str,
    source_key: str | None = None,
    location: str | None = None,
    excerpt: str | None = None,
    question_id: str | None = None,
) -> WorldValidationFinding:
    identity = stable_hash(
        [layer, severity, category, action, message, source_key, location, question_id]
    )[:24]
    return WorldValidationFinding(
        finding_id=f"finding:{identity}",
        layer=layer,
        severity=severity,
        category=category,
        action=action,
        message=message,
        source_key=source_key,
        location=location,
        excerpt=excerpt,
        question_id=question_id,
    )


def _scan_wikilinks(
    text: str,
    *,
    source_key: str,
    link_lookup: set[str],
    anchor_lookup: dict[str, set[str]],
    current_anchors: list[str],
    location_prefix: str,
) -> list[WorldValidationFinding]:
    findings: list[WorldValidationFinding] = []
    for match in _WIKILINK_RE.finditer(text):
        target, anchor = _link_parts(match.group(1))
        target_keys = (
            [_normalized_name(target), _normalized_name(PurePosixPath(target).name)]
            if target
            else []
        )
        resolved_key = next((key for key in target_keys if key in link_lookup), None)
        location = (
            f"line:{_line_number(text, match.start())}"
            if location_prefix == "body"
            else location_prefix
        )
        if target and resolved_key is None:
            findings.append(
                _finding(
                    layer="structure",
                    severity="error",
                    category="wikilink-dangling",
                    action="CLOSE",
                    message=f"悬空 WikiLink [[{match.group(1)}]]。",
                    source_key=source_key,
                    location=location,
                )
            )
        elif anchor:
            available = (
                anchor_lookup.get(resolved_key, set())
                if resolved_key
                else {_normalized_name(value) for value in current_anchors}
            )
            if _normalized_name(anchor) not in available:
                findings.append(
                    _finding(
                        layer="structure",
                        severity="error",
                        category="wikilink-anchor-dangling",
                        action="CLOSE",
                        message="WikiLink 指向不存在的标题锚点。",
                        source_key=source_key,
                        location=location,
                    )
                )
    return findings


def deterministic_findings(
    policy: WorldValidationPolicy,
    manifest: dict[str, Any],
    checkpoint: WorldDesignCheckpointPayload | None,
) -> list[WorldValidationFinding]:
    items = list(manifest.get("items") or [])
    findings: list[WorldValidationFinding] = []
    titles: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        title = str(item.get("title") or "").strip()
        source_key = str(item.get("source_key") or "")
        if not title:
            findings.append(
                _finding(
                    layer="structure",
                    severity="error",
                    category="missing-title",
                    action="CLOSE",
                    message="页面缺少标题。",
                    source_key=source_key,
                )
            )
        elif item.get("target_type") in {
            None,
            "world_bible_page",
            "world_bible_draft",
        }:
            titles[title.casefold()].append(item)
    for duplicate in titles.values():
        if (
            len(
                {item.get("identity_key") or item.get("source_key") for item in duplicate}
            )
            < 2
        ):
            continue
        for item in duplicate:
            findings.append(
                _finding(
                    layer="structure",
                    severity="error",
                    category="duplicate-title",
                    action="SPLIT",
                    message=f"页面标题重复：{item.get('title')}",
                    source_key=str(item.get("source_key") or ""),
                )
            )

    for item in items:
        schema = policy.frontmatter_schemas.get(str(item.get("page_type") or ""))
        if schema is None:
            continue
        source_key = str(item.get("source_key") or "")
        frontmatter = _frontmatter(item)
        for field in schema.required:
            if field not in frontmatter:
                findings.append(
                    _finding(
                        layer="structure",
                        severity="error",
                        category="schema-required",
                        action="CLOSE",
                        message=f"Frontmatter 缺少必填字段 {field}。",
                        source_key=source_key,
                    )
                )
        allowed = set(schema.required) | set(schema.optional)
        if allowed and schema.unknown_fields != "ignore":
            for field in sorted(set(frontmatter) - allowed):
                findings.append(
                    _finding(
                        layer="structure",
                        severity=schema.unknown_fields,
                        category="schema-unknown-field",
                        action="CLOSE"
                        if schema.unknown_fields == "error"
                        else "KEEP-GATE",
                        message=f"Frontmatter 字段 {field} 未在该页面类型中声明。",
                        source_key=source_key,
                    )
                )
        for field, expected in schema.field_types.items():
            if field in frontmatter and not _frontmatter_type_matches(
                frontmatter[field], expected
            ):
                findings.append(
                    _finding(
                        layer="structure",
                        severity="error",
                        category="schema-field-type",
                        action="CLOSE",
                        message=f"Frontmatter 字段 {field} 类型不符合 {expected}。",
                        source_key=source_key,
                    )
                )
        for field, values in schema.enums.items():
            if field in frontmatter and frontmatter[field] not in values:
                findings.append(
                    _finding(
                        layer="structure",
                        severity="error",
                        category="schema-field-enum",
                        action="CLOSE",
                        message=f"Frontmatter 字段 {field} 不在允许枚举中。",
                        source_key=source_key,
                    )
                )
        for field, pattern in schema.patterns.items():
            value = frontmatter.get(field)
            if value is not None and (
                not isinstance(value, str) or re.search(pattern, value) is None
            ):
                findings.append(
                    _finding(
                        layer="structure",
                        severity="error",
                        category="schema-string-pattern",
                        action="CLOSE",
                        message=f"Frontmatter 字段 {field} 格式不正确。",
                        source_key=source_key,
                    )
                )
        for field, minimum in schema.min_items.items():
            value = frontmatter.get(field)
            if value is not None and (
                not isinstance(value, list) or len(value) < minimum
            ):
                findings.append(
                    _finding(
                        layer="structure",
                        severity="error",
                        category="schema-array-length",
                        action="CLOSE",
                        message=f"Frontmatter 字段 {field} 项数不足。",
                        source_key=source_key,
                    )
                )
        for field in schema.unique_arrays:
            value = frontmatter.get(field)
            if isinstance(value, list) and len(value) != len(
                {stable_hash(entry) for entry in value}
            ):
                findings.append(
                    _finding(
                        layer="structure",
                        severity="error",
                        category="schema-array-duplicate",
                        action="CLOSE",
                        message=f"Frontmatter 字段 {field} 含重复项。",
                        source_key=source_key,
                    )
                )
        for field, required_items in schema.required_items.items():
            value = frontmatter.get(field)
            if isinstance(value, list):
                missing = [entry for entry in required_items if entry not in value]
            else:
                missing = required_items
            if missing:
                findings.append(
                    _finding(
                        layer="structure",
                        severity="error",
                        category="schema-array-required-item",
                        action="CLOSE",
                        message=f"Frontmatter 字段 {field} 缺少必需项。",
                        source_key=source_key,
                    )
                )
        imported_meta = dict(item.get("metadata") or {}).get("worldbook_import")
        source_path = str(
            (
                imported_meta.get("source_path")
                if isinstance(imported_meta, dict)
                else None
            )
            or item.get("source_path")
            or ""
        )
        if schema.source_prefixes and not any(
            source_path.startswith(prefix) for prefix in schema.source_prefixes
        ):
            findings.append(
                _finding(
                    layer="structure",
                    severity="error",
                    category="schema-source-scope",
                    action="CLOSE",
                    message="页面来源路径不在该类型允许的目录中。",
                    source_key=source_key,
                )
            )
        if (
            schema.title_matches_source_stem
            and source_path
            and str(item.get("title") or "") != PurePosixPath(source_path).stem
        ):
            findings.append(
                _finding(
                    layer="structure",
                    severity="error",
                    category="schema-title-filename",
                    action="CLOSE",
                    message="页面标题与来源文件名不一致。",
                    source_key=source_key,
                )
            )

    policy_sources = {
        str(item.get("identity_key") or item.get("source_key") or "")
        for item in items
        if isinstance(dict(item.get("metadata") or {}).get("validation_policy"), dict)
    }
    if len(policy_sources) > 1:
        findings.append(
            _finding(
                layer="structure",
                severity="error",
                category="validation-policy-multiple",
                action="CLOSE",
                message="只能保留一个待激活或已激活的世界书校验策略。",
            )
        )

    names: dict[str, list[tuple[str, str, str, str]]] = defaultdict(list)
    lookup_entries = {
        str(entry.get("source_key") or ""): entry
        for entry in manifest.get("alias_lookup") or manifest.get("lookup") or []
        if isinstance(entry, dict)
    }
    for item in items:
        lookup_entries[str(item.get("source_key") or "")] = item
    for source_key, entry in lookup_entries.items():
        if entry.get("target_type") not in {
            None,
            "world_bible_page",
            "world_bible_draft",
        }:
            continue
        identity_key = str(entry.get("identity_key") or source_key)
        title = str(entry.get("title") or "").strip()
        if title:
            names[_normalized_name(title)].append(
                (identity_key, source_key, "title", title)
            )
        aliases = entry.get("aliases") or _aliases(entry)
        for alias in aliases:
            value = str(alias).strip()
            if value:
                names[_normalized_name(value)].append(
                    (identity_key, source_key, "alias", value)
                )
    for records in names.values():
        if len({record[0] for record in records}) < 2:
            continue
        detail = "；".join(
            f"{value}({kind})" for _, _, kind, value in sorted(set(records))
        )
        for source_key in sorted({record[1] for record in records}):
            findings.append(
                _finding(
                    layer="structure",
                    severity="error",
                    category="alias-conflict",
                    action="SPLIT",
                    message=f"标题或别名冲突：{detail}",
                    source_key=source_key,
                )
            )

    link_lookup = _link_lookup(manifest, items)
    anchor_lookup = _anchor_lookup(manifest, items)
    for item in items:
        source_key = str(item.get("source_key") or "")
        body = str(item.get("body", item.get("content") or ""))
        metadata = _document_metadata(item)
        if "\ufffd" in body:
            findings.append(
                _finding(
                    layer="structure",
                    severity="error",
                    category="text-replacement-character",
                    action="CLOSE",
                    message="正文包含 Unicode 替换字符 U+FFFD。",
                    source_key=source_key,
                )
            )
        if "\x00" in body:
            findings.append(
                _finding(
                    layer="structure",
                    severity="error",
                    category="text-nul",
                    action="CLOSE",
                    message="正文包含 NUL 字符。",
                    source_key=source_key,
                )
            )
        if body.count("[[") != body.count("]]"):
            findings.append(
                _finding(
                    layer="structure",
                    severity="error",
                    category="wikilink-unbalanced",
                    action="CLOSE",
                    message="WikiLink 方括号数量不平衡。",
                    source_key=source_key,
                )
            )
        findings.extend(
            _scan_wikilinks(
                body,
                source_key=source_key,
                link_lookup=link_lookup,
                anchor_lookup=anchor_lookup,
                current_anchors=list(item.get("anchors") or []),
                location_prefix="body",
            )
        )
        findings.extend(
            _scan_wikilinks(
                json.dumps(_frontmatter(item), ensure_ascii=False, default=str),
                source_key=source_key,
                link_lookup=link_lookup,
                anchor_lookup=anchor_lookup,
                current_anchors=list(item.get("anchors") or []),
                location_prefix="frontmatter",
            )
        )

        imported = item.get("metadata", {}).get("worldbook_import")
        if isinstance(imported, dict):
            path = str(imported.get("source_path") or "")
            frontmatter = imported.get("frontmatter")
            if (
                path.casefold().endswith(".md")
                and item.get("page_type") != "source_material"
                and not frontmatter
            ):
                findings.append(
                    _finding(
                        layer="structure",
                        severity="error",
                        category="frontmatter-missing",
                        action="CLOSE",
                        message="Wiki 页缺少 YAML Frontmatter。",
                        source_key=source_key,
                        location="line:1",
                    )
                )
            front_title = metadata.get("title")
            if front_title and str(front_title).strip() != str(item.get("title") or ""):
                findings.append(
                    _finding(
                        layer="structure",
                        severity="error",
                        category="frontmatter-title-mismatch",
                        action="CLOSE",
                        message="Frontmatter title 与导入页标题不一致。",
                        source_key=source_key,
                    )
                )

        created = metadata.get("created")
        updated = metadata.get("updated")
        if isinstance(created, str) and isinstance(updated, str) and updated < created:
            findings.append(
                _finding(
                    layer="structure",
                    severity="error",
                    category="date-order",
                    action="CLOSE",
                    message="updated 早于 created。",
                    source_key=source_key,
                )
            )

        decision_status = metadata.get("decision_status")
        decision_questions = metadata.get("decision_questions")
        open_questions = metadata.get("canon_status") == "open-questions"
        has_decision_heading = any(
            line.strip() == "## 待创作者裁定" for line in body.splitlines()
        )
        if (
            open_questions
            or decision_status
            or decision_questions
            or has_decision_heading
        ):
            if decision_status not in {"author-required", "deferred"}:
                findings.append(
                    _finding(
                        layer="structure",
                        severity="error",
                        category="decision-status-missing",
                        action="AUTHOR-REQUIRED",
                        message="待裁定页必须声明 author-required 或 deferred。",
                        source_key=source_key,
                    )
                )
            if not (
                isinstance(decision_questions, list)
                and decision_questions
                and all(str(value).strip() for value in decision_questions)
            ):
                findings.append(
                    _finding(
                        layer="structure",
                        severity="error",
                        category="decision-questions-missing",
                        action="AUTHOR-REQUIRED",
                        message="待裁定页必须列出非空问题。",
                        source_key=source_key,
                    )
                )
            if not has_decision_heading:
                findings.append(
                    _finding(
                        layer="structure",
                        severity="error",
                        category="decision-section-missing",
                        action="AUTHOR-REQUIRED",
                        message="待裁定页缺少“待创作者裁定”章节。",
                        source_key=source_key,
                    )
                )
            if decision_status == "deferred" and not re.search(
                r"不阻塞|剧情需要|升级为必须|终局|延后|deferred",
                body,
                re.IGNORECASE,
            ):
                findings.append(
                    _finding(
                        layer="structure",
                        severity="warning",
                        category="decision-defer-reason",
                        action="KEEP-GATE",
                        message="deferred 裁定应说明延后理由或升级条件。",
                        source_key=source_key,
                    )
                )

    combined = "\n\n".join(str(item.get("content") or "") for item in items)
    page_types = {str(item.get("page_type") or "") for item in items}
    for rule in policy.rules:
        scoped = [
            item
            for item in items
            if not rule.page_type or item.get("page_type") == rule.page_type
        ]
        if rule.operator == "page_type_exists":
            failed = str(rule.value) not in page_types
            source_key = None
        elif rule.operator == "max_chars":
            failed = sum(len(str(item.get("content") or "")) for item in scoped) > int(
                rule.value
            )
            source_key = None
        elif rule.operator == "frontmatter_required":
            failed_item = next(
                (
                    item
                    for item in scoped
                    if _field_value(item, str(rule.value)) in (None, "", [], ())
                ),
                None,
            )
            failed = failed_item is not None
            source_key = str(failed_item.get("source_key") or "") if failed_item else None
        elif rule.operator == "field_equals":
            expected = dict(rule.value)
            failed_item = next(
                (
                    item
                    for item in scoped
                    if _field_value(item, str(expected["field"])) != expected["equals"]
                ),
                None,
            )
            failed = failed_item is not None
            source_key = str(failed_item.get("source_key") or "") if failed_item else None
        elif rule.operator == "numeric_tolerance":
            expected = dict(rule.value)
            failed_item = next(
                (
                    item
                    for item in scoped
                    if not isinstance(
                        _field_value(item, str(expected["field"])), int | float
                    )
                    or abs(
                        float(_field_value(item, str(expected["field"])))
                        - float(expected["expected"])
                    )
                    > float(expected["tolerance"])
                ),
                None,
            )
            failed = failed_item is not None
            source_key = str(failed_item.get("source_key") or "") if failed_item else None
        elif rule.operator in {"regex", "forbid_regex"}:
            matched = re.search(
                str(rule.value),
                "\n\n".join(str(item.get("content") or "") for item in scoped),
                re.MULTILINE,
            )
            failed = matched is None if rule.operator == "regex" else matched is not None
            source_key = None
        else:
            text = "\n\n".join(str(item.get("content") or "") for item in scoped)
            failed = (
                str(rule.value) not in text
                if rule.operator == "contains"
                else str(rule.value) in text
            )
            source_key = next(
                (
                    str(item.get("source_key") or "")
                    for item in scoped
                    if str(rule.value) in str(item.get("content") or "")
                ),
                None,
            )
        if failed:
            findings.append(
                _finding(
                    layer="structure",
                    severity=rule.severity,
                    category=f"policy:{rule.rule_id}",
                    action="CLOSE" if rule.severity == "error" else "KEEP-GATE",
                    message=rule.message,
                    source_key=source_key,
                )
            )

    target_sources = {
        str(entry.get("target_id") or ""): str(entry.get("source_key") or "")
        for entry in manifest.get("lookup") or []
        if isinstance(entry, dict) and entry.get("target_id")
    }
    dependency_edges: list[tuple[str, str]] = []
    for item in items:
        source_key = str(item.get("source_key") or "")
        seen_refs: set[tuple[str, str, str]] = set()
        for ref in item.get("linked_asset_refs") or []:
            if not isinstance(ref, dict):
                findings.append(
                    _finding(
                        layer="structure",
                        severity="error",
                        category="dependency-invalid",
                        action="CLOSE",
                        message="依赖引用必须是对象。",
                        source_key=source_key,
                    )
                )
                continue
            relation = str(ref.get("relation") or "informs")
            target_type = str(
                ref.get("target_type") or ref.get("type") or ref.get("source_type") or ""
            )
            target_id = str(
                ref.get("target_id") or ref.get("id") or ref.get("source_id") or ""
            )
            identity = (relation, target_type, target_id)
            if relation not in {"requires", "informs", "derives", "conflicts"}:
                findings.append(
                    _finding(
                        layer="structure",
                        severity="error",
                        category="dependency-relation-invalid",
                        action="CLOSE",
                        message=f"未知依赖关系：{relation}。",
                        source_key=source_key,
                    )
                )
            if not target_type or not target_id:
                findings.append(
                    _finding(
                        layer="structure",
                        severity="error",
                        category="dependency-target-missing",
                        action="CLOSE",
                        message="依赖引用缺少目标类型或标识。",
                        source_key=source_key,
                    )
                )
                continue
            if identity in seen_refs:
                findings.append(
                    _finding(
                        layer="structure",
                        severity="error",
                        category="dependency-duplicate",
                        action="CLOSE",
                        message="同一依赖关系重复。",
                        source_key=source_key,
                    )
                )
            seen_refs.add(identity)
            target_source = target_sources.get(target_id)
            if target_type in {"world_bible_page", "page"} and not target_source:
                findings.append(
                    _finding(
                        layer="structure",
                        severity="error",
                        category="dependency-dangling",
                        action="CLOSE",
                        message="世界书依赖指向不可用页面。",
                        source_key=source_key,
                    )
                )
            if target_source == source_key:
                findings.append(
                    _finding(
                        layer="structure",
                        severity="error",
                        category="dependency-self-edge",
                        action="SPLIT",
                        message="世界书页不能依赖自身。",
                        source_key=source_key,
                    )
                )
            if target_source and relation in {"requires", "derives"}:
                dependency_edges.append((target_source, source_key))
    if _has_dependency_cycle(dependency_edges):
        findings.append(
            _finding(
                layer="structure",
                severity="error",
                category="dependency-cycle",
                action="SPLIT",
                message="世界书页依赖图存在循环。",
                location="linked_asset_refs",
            )
        )

    if checkpoint is None:
        findings.append(
            _finding(
                layer="engine",
                severity="error" if manifest.get("scope") == "full" else "warning",
                category="missing-world-state",
                action=("CLOSE" if manifest.get("scope") == "full" else "CANDIDATE"),
                message="尚无 world_design_checkpoint，无法审计完整世界状态。",
            )
        )
        return findings

    state = checkpoint.world_state
    if manifest.get("scope") == "full":
        for decision in state.authority.author_required:
            findings.append(
                _finding(
                    layer="engine",
                    severity="error",
                    category="author-required",
                    action="AUTHOR-REQUIRED",
                    message=decision.question,
                    source_key=decision.evidence[0] if decision.evidence else None,
                    location=f"authority.author_required:{decision.id}",
                )
            )
        for facet in state.facets:
            if facet.status == "gap":
                findings.append(
                    _finding(
                        layer="engine",
                        severity="warning",
                        category="facet-gap",
                        action="CANDIDATE",
                        message=f"{facet.id} {facet.name} 尚缺证据。",
                        location=f"facets:{facet.id}",
                    )
                )
            if facet.maturity.framework - facet.maturity.instance > 2:
                findings.append(
                    _finding(
                        layer="engine",
                        severity="warning",
                        category="candidate-mountain",
                        action="KEEP-GATE",
                        message=f"{facet.id} 框架成熟度显著高于实例成熟度。",
                        location=f"facets:{facet.id}.maturity",
                    )
                )
        for name, loop in state.reproduction_loops:
            if loop.status in {"gap", "partial"}:
                findings.append(
                    _finding(
                        layer="engine",
                        severity="warning",
                        category="reproduction-loop-gap",
                        action="CANDIDATE",
                        message=f"六循环 {name} 尚未闭合。",
                        location=f"reproduction_loops:{name}",
                    )
                )
        for chain in state.coupling_chains:
            if chain.status in {"gap", "partial"}:
                findings.append(
                    _finding(
                        layer="engine",
                        severity="warning",
                        category="coupling-chain-gap",
                        action="CANDIDATE",
                        message=f"{chain.id} {chain.name} 尚未闭合。",
                        location=f"coupling_chains:{chain.id}",
                    )
                )
        for name, situated in state.situated_tests:
            if situated.status in {"gap", "partial"}:
                findings.append(
                    _finding(
                        layer="engine",
                        severity="warning",
                        category="situated-test-gap",
                        action="KEEP-GATE",
                        message=f"情境测试 {name} 尚未完成。",
                        location=f"situated_tests:{name}",
                    )
                )
        for test in state.pressure_tests:
            if test.status == "not-run":
                findings.append(
                    _finding(
                        layer="engine",
                        severity="warning",
                        category="pressure-not-run",
                        action="KEEP-GATE",
                        message=f"{test.id} {test.name} 尚未运行。",
                        location=f"pressure_tests:{test.id}",
                    )
                )
        for rule in state.rules:
            missing = [
                label
                for label, values in (
                    ("代价", [*rule.costs, *rule.losses]),
                    ("故障模式", rule.failure_modes),
                    ("维护", rule.maintenance),
                )
                if not values
            ]
            if missing:
                findings.append(
                    _finding(
                        layer="engine",
                        severity="warning",
                        category="rule-economics-gap",
                        action="KEEP-GATE",
                        message=f"规则 {rule.id} 缺少{'/'.join(missing)}。",
                        location=f"rules:{rule.id}",
                    )
                )
        coverage_gap = any(
            entry.status in {"gap", "partial"} for _, entry in state.reproduction_loops
        ) or any(facet.status in {"gap", "partial"} for facet in state.facets)
        if state.audit.valid is True and coverage_gap:
            findings.append(
                _finding(
                    layer="engine",
                    severity="error",
                    category="audit-overclaim",
                    action="CLOSE",
                    message="audit.valid=true 与未闭合的世界状态矛盾。",
                    location="audit.valid",
                )
            )
        invalidated_layers = {
            layer for change in state.change_log for layer in change.invalidated_layers
        }
        for layer in invalidated_layers:
            pipeline = getattr(state.fiction_core, layer, None)
            if pipeline is not None and pipeline.status not in {
                "invalidated",
                "needs-review",
                "blocked",
            }:
                findings.append(
                    _finding(
                        layer="engine",
                        severity="error",
                        category="downstream-invalidation-missing",
                        action="CLOSE",
                        message=f"{layer} 已被变更记录失效，但下游状态未同步。",
                        location=f"fiction_core:{layer}",
                    )
                )
    if _has_dependency_cycle(
        [
            (edge.source, edge.to)
            for edge in state.dependencies
            if edge.status == "active" and edge.kind != "contradicts"
        ]
    ):
        findings.append(
            _finding(
                layer="engine",
                severity="error",
                category="dependency-cycle",
                action="SPLIT",
                message="世界状态依赖图存在循环。",
                location="dependencies",
            )
        )
    if not combined and items:
        findings.append(
            _finding(
                layer="structure",
                severity="warning",
                category="empty-content",
                action="CANDIDATE",
                message="校验范围没有可检查的正文。",
            )
        )
    return findings


def _has_dependency_cycle(edges: list[tuple[str, str]]) -> bool:
    graph: dict[str, set[str]] = defaultdict(set)
    for source, target in edges:
        if source == target:
            return True
        graph[source].add(target)
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        if any(visit(target) for target in graph.get(node, ())):
            return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in graph)


def build_review_packets(
    *,
    run_id: str,
    scope: str,
    policy: WorldValidationPolicy,
    manifest: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    questions = [item.model_dump(mode="json") for item in policy.required_questions]
    parts: list[dict[str, str]] = []
    for item in manifest.get("items") or []:
        text = str(item.get("content") or "")
        if not text:
            continue
        for offset in range(0, len(text), policy.packet_character_limit):
            parts.append(
                {
                    "source_key": str(item.get("source_key") or ""),
                    "text": text[offset : offset + policy.packet_character_limit],
                    "location": (
                        f"chars:{offset}-"
                        f"{min(len(text), offset + policy.packet_character_limit)}"
                    ),
                }
            )
    checkpoint = manifest.get("world_state_checkpoint")
    if isinstance(checkpoint, dict) and isinstance(checkpoint.get("payload"), dict):
        state_text = json.dumps(
            checkpoint["payload"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        source_key = f"world_state:{checkpoint.get('suggestion_id') or 'checkpoint'}"
        for offset in range(0, len(state_text), policy.packet_character_limit):
            parts.append(
                {
                    "source_key": source_key,
                    "text": state_text[offset : offset + policy.packet_character_limit],
                    "location": (
                        f"world_state:chars:{offset}-"
                        f"{min(len(state_text), offset + policy.packet_character_limit)}"
                    ),
                }
            )
    budget = {
        "planned_input_characters": sum(len(item["text"]) for item in parts),
        "used_input_characters": 0,
        "planned_packets": len(parts),
        "used_packets": 0,
        "max_input_characters": policy.max_input_characters,
        "max_packets": policy.max_packets,
        "planned_output_tokens": len(parts) * policy.max_output_tokens_per_packet,
        "max_output_tokens_per_packet": policy.max_output_tokens_per_packet,
        "per_packet_timeout_seconds": policy.per_packet_timeout_seconds,
    }
    if (
        budget["planned_input_characters"] > policy.max_input_characters
        or len(parts) > policy.max_packets
    ):
        return [], budget
    packets = []
    for index, content in enumerate(parts):
        packet = {
            "run_id": run_id,
            "policy_version": policy.policy_version,
            "scope": scope,
            "shard_index": index,
            "shard_count": len(parts),
            "pages": [
                {
                    key: item.get(key)
                    for key in (
                        "source_key",
                        "target_type",
                        "target_id",
                        "title",
                        "page_type",
                        "status",
                        "version",
                        "content_hash",
                    )
                }
                for item in manifest.get("items") or []
                if item.get("source_key") == content["source_key"]
            ],
            "content": content,
            "questions": questions,
        }
        packet["input_hash"] = stable_hash(packet)
        packets.append(packet)
    return packets, budget


def validate_semantic_output(
    packet: dict[str, Any],
    output: WorldValidationSemanticOutput,
) -> tuple[list[WorldValidationFinding], list[dict[str, Any]]]:
    question_ids = [item["question_id"] for item in packet["questions"]]
    answers = {item.question_id: item for item in output.answers}
    if len(answers) != len(output.answers) or set(answers) != set(question_ids):
        raise ValidationError(
            "Semantic validation did not cover each question exactly once"
        )
    content = packet["content"]
    findings: list[WorldValidationFinding] = []
    coverage = []
    for question_id in question_ids:
        answer = answers[question_id]
        if answer.source_key and answer.source_key != content["source_key"]:
            raise ValidationError("Semantic validation cited an unknown source")
        if answer.excerpt and answer.excerpt not in content["text"]:
            raise ValidationError(
                "Semantic validation excerpt is not in the frozen source"
            )
        if answer.verdict == "pass" and not (
            answer.source_key == content["source_key"] and answer.excerpt
        ):
            raise ValidationError("A semantic pass requires frozen source evidence")
        coverage.append(
            {
                "question_id": question_id,
                "shard_index": packet["shard_index"],
                "answered": True,
                "evidence_located": bool(answer.excerpt),
            }
        )
        if answer.verdict != "pass":
            findings.append(
                _finding(
                    layer="semantic",
                    severity=(
                        "error"
                        if answer.verdict in {"fail", "author-required"}
                        else "warning"
                    ),
                    category=answer.category,
                    action=answer.action,
                    message=answer.explanation,
                    source_key=answer.source_key,
                    location=answer.location,
                    excerpt=answer.excerpt,
                    question_id=question_id,
                )
            )
    return findings, coverage


def overall_result(
    findings: list[WorldValidationFinding],
    *,
    insufficient_evidence: bool = False,
) -> tuple[str, str]:
    if insufficient_evidence:
        return "insufficient-evidence", "block"
    if any(item.action == "AUTHOR-REQUIRED" for item in findings):
        return "author-required", "block"
    if any(item.severity == "error" for item in findings):
        return "fail", "block"
    if findings:
        return "mixed", "warn"
    return "pass", "pass"


__all__ = [
    "build_review_packets",
    "deterministic_findings",
    "overall_result",
    "stable_hash",
    "validate_semantic_output",
]
