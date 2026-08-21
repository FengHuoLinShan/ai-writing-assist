"""Pure validation rules and ReviewPacket construction for World Bible state."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any

from core.errors import ValidationError
from modules.world.schemas import (
    WorldDesignCheckpointPayload,
    WorldValidationFinding,
    WorldValidationPolicy,
    WorldValidationSemanticOutput,
)


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
        else:
            titles[title.casefold()].append(item)
    for duplicate in titles.values():
        if len(duplicate) < 2:
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

    if checkpoint is None:
        findings.append(
            _finding(
                layer="engine",
                severity="warning",
                category="missing-world-state",
                action="CANDIDATE",
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
    budget = {
        "planned_input_characters": sum(len(item["text"]) for item in parts),
        "used_input_characters": 0,
        "planned_packets": len(parts),
        "used_packets": 0,
        "max_input_characters": policy.max_input_characters,
        "max_packets": policy.max_packets,
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
