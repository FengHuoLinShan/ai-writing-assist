"""
范围冻结引擎

从 scope_complete 编译结果构建冻结范围回执（KnowledgeScopeReceipt）与生成者
可见集。权威 manifest 覆盖编译产物中的全部来源；预算驱逐、作者排除与不可读
来源都被显式记录为 omitted/excluded，绝不静默裁剪——任何必查维度的 omission
都会让 `require_scope_complete` 阻断生成。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from modules.evidence.compilation.knowledge.contracts import (
    KnowledgeContractError,
    KnowledgeDimensionCoverage,
    KnowledgeDirectorDisposition,
    KnowledgeScopeReceipt,
    KnowledgeSourceEntry,
    KnowledgeSubject,
    knowledge_canonical_hash,
)
from modules.evidence.compilation.knowledge.policies import (
    KNOWLEDGE_DIMENSIONS,
    CapabilityKnowledgePolicy,
)
from modules.evidence.compilation.services.compiled_context import selection_ref_key

if TYPE_CHECKING:
    from modules.evidence.compilation.contracts import CompileOptions
    from modules.evidence.compilation.services.compiled_context import CompiledContext

REFERENCE_USAGE_CREATION = "creation"
REFERENCE_USAGE_AUDIT_ONLY = "audit_only"
REFERENCE_USAGES = frozenset({REFERENCE_USAGE_CREATION, REFERENCE_USAGE_AUDIT_ONLY})

SECTION_DIMENSION_MAP: dict[str, str] = {
    "world_entities": "world_entities",
    "reader_visible_world": "reader_reveal",
    "reader_visible_manuscript": "prior_prose",
    "world_bible_activation": "world_rules",
    "world_bible_synopsis": "world_bible",
    "world_bible_working_pages": "world_bible",
    "knowledge_constraints": "character_knowledge",
    "pov_knowledge": "character_knowledge",
    "scene_director_constraints": "character_knowledge",
    "role_profile": "character_knowledge",
    "role_visible_knowledge": "character_knowledge",
    "delta_timeline": "timeline",
    "foreshadowing_constraints": "plot_threads",
    "safe_plotline_context": "plot_threads",
    "open_narrative_obligations": "plot_threads",
    "scene_blueprint": "outline",
    "outline_analysis_range": "outline",
    "outline_analysis_scenes": "outline",
    "outline_analysis_arcs": "outline",
    "outline_analysis_threads": "outline",
    "outline_analysis_foreshadowing": "outline",
    "outline_analysis_reveals": "outline",
    "scene_world_state": "scene_state",
    "scene_time_boundary": "scene_state",
    "scene_constraints": "scene_state",
    "current_scene_evidence": "scene_state",
    "historical_role_context": "memory",
    "retrieval_evidence_packs": "prior_prose",
}
"""编译 section key → 知识维度映射；未映射的 section 仍进 manifest 但不计维度覆盖。"""


def knowledge_subject_from_options(options: CompileOptions) -> KnowledgeSubject:
    """从 CompileOptions 派生知识主体与截止点。"""
    subject_type = {
        "reader": "reader",
        "character": "character",
    }.get(options.reveal_mode, "author")
    return KnowledgeSubject(
        subject_type=subject_type,
        character_id=options.viewpoint_character_id,
        cutoff_chapter=options.visible_until_chapter or options.requested_chapter_index,
        cutoff_scene_id=options.visible_until_scene_id or options.scene_id,
        cutoff_offset=options.visible_until_offset,
    )


def source_key_of(source: Mapping[str, Any]) -> str:
    """从来源身份字典派发稳定短 key；无身份来源返回空串（不入 manifest）。"""
    source_type = str(source.get("type") or "").strip() or "source"
    for field in ("id", "source_ref", "target_ref", "revision_id", "version"):
        value = source.get(field)
        if value is None or value == "":
            continue
        if isinstance(value, Mapping):
            value = knowledge_canonical_hash(dict(value))
        return f"{source_type}:{value}"
    return ""


def _content_hash_of(source: Mapping[str, Any]) -> str:
    for key in ("content_hash", "hash", "source_hash"):
        value = source.get(key)
        if isinstance(value, str) and value:
            return value
    identity = {
        key: source[key]
        for key in (
            "type",
            "id",
            "source_ref",
            "target_ref",
            "revision_id",
            "version",
            "label",
            "summary",
        )
        if key in source
    }
    return knowledge_canonical_hash(identity)


@dataclass(frozen=True)
class KnowledgeScopeBuild:
    """一次范围冻结的产物：回执 + 生成者可见 key + 仅审查可见 key。"""

    receipt: KnowledgeScopeReceipt
    generator_keys: tuple[str, ...]
    audit_only_keys: tuple[str, ...]

    def hidden_from_generator(self) -> tuple[KnowledgeSourceEntry, ...]:
        """权威包 − 生成者包；供 HiddenGuard 与语义审查使用。"""
        visible = set(self.generator_keys)
        return tuple(
            entry
            for entry in self.receipt.included
            if entry.source_key not in visible
        )


def build_scope_receipt(
    compiled: CompiledContext,
    policy: CapabilityKnowledgePolicy,
    subject: KnowledgeSubject,
    *,
    novel_id: str = "",
    dimension_overrides: Mapping[str, str] | None = None,
    reference_usages: Mapping[str, str] | None = None,
    generator_visible: Iterable[str] | None = None,
    continuation: str | None = None,
    created_at: str = "",
) -> KnowledgeScopeBuild:
    """从编译产物构建冻结范围回执。

    - included：编译产物中的全部来源（权威包），按 source_key 规范化排序；
    - excluded：作者显式排除（excluded_items / excluded section），不得回流；
    - omitted：预算驱逐或不可读来源，必查维度命中即 scope_complete=False；
    - generator_keys：默认等于 included，审计专用引用与不可见集从中扣除。
    """
    dimension_map = dict(SECTION_DIMENSION_MAP)
    if dimension_overrides:
        dimension_map.update(dimension_overrides)

    entries: dict[str, KnowledgeSourceEntry] = {}
    entry_dimensions: dict[str, set[str]] = {}
    excluded_keys: set[str] = set()
    omitted_keys: set[str] = set()

    def _absorb(source: Mapping[str, Any], dimension: str) -> None:
        key = source_key_of(source)
        if not key:
            return
        if key not in entries:
            entries[key] = KnowledgeSourceEntry(
                source_key=key,
                source_type=str(source.get("type") or "source"),
                source_id=str(source.get("id") or key.split(":", 1)[1]),
                content_hash=_content_hash_of(source),
                label=str(source.get("label") or ""),
            )
            entry_dimensions[key] = set()
        if dimension:
            entry_dimensions[key].add(dimension)

    for section in compiled.sections:
        dimension = dimension_map.get(section.key, "")
        for source in section.sources:
            _absorb(source, dimension)
        if section.excluded:
            for source in section.sources:
                key = source_key_of(source)
                if key:
                    excluded_keys.add(key)

    for item in compiled.excluded_items:
        _absorb(item.source, "")
        key = source_key_of(item.source)
        if key:
            excluded_keys.add(key)
    for item in compiled.omitted_items:
        _absorb(item.source, "")
        key = source_key_of(item.source)
        if key:
            omitted_keys.add(key)

    audit_only_keys: set[str] = set()
    for section in compiled.sections:
        for item in section.materialize_items().items:
            if item.selection_state != "author_pinned" or not item.selection_ref:
                continue
            ref_key = selection_ref_key(item.selection_ref)
            if (reference_usages or {}).get(ref_key) == REFERENCE_USAGE_AUDIT_ONLY:
                key = source_key_of(item.source)
                if key:
                    audit_only_keys.add(key)

    included_with_dimensions = tuple(
        KnowledgeSourceEntry(
            source_key=entry.source_key,
            source_type=entry.source_type,
            source_id=entry.source_id,
            content_hash=entry.content_hash,
            label=entry.label,
            dimensions=tuple(sorted(entry_dimensions.get(entry.source_key, ()))),
        )
        for entry in sorted(entries.values(), key=lambda e: e.source_key)
    )
    excluded = tuple(
        entry for entry in included_with_dimensions if entry.source_key in excluded_keys
    )
    omitted = tuple(
        entry
        for entry in included_with_dimensions
        if entry.source_key in omitted_keys and entry.source_key not in excluded_keys
    )
    included_final = tuple(
        entry
        for entry in included_with_dimensions
        if entry.source_key not in excluded_keys
    )

    coverage: list[KnowledgeDimensionCoverage] = []
    for dimension in policy.required_dimensions:
        all_keys = {
            entry.source_key
            for entry in included_with_dimensions
            if dimension in entry.dimensions
        }
        candidates = all_keys - excluded_keys
        if candidates:
            coverage.append(
                KnowledgeDimensionCoverage(
                    dimension=dimension,
                    covered_by=tuple(sorted(candidates)),
                )
            )
        elif all_keys & excluded_keys:
            coverage.append(
                KnowledgeDimensionCoverage(
                    dimension=dimension,
                    covered_by=(),
                    omitted=True,
                    omission_reason="必查维度来源被作者显式排除",
                )
            )
        elif all_keys & omitted_keys:
            coverage.append(
                KnowledgeDimensionCoverage(
                    dimension=dimension,
                    covered_by=(),
                    omitted=True,
                    omission_reason="必查维度来源全部被预算或可读性排除",
                )
            )
        else:
            coverage.append(
                KnowledgeDimensionCoverage(
                    dimension=dimension,
                    covered_by=(),
                    omission_reason="冻结范围内无该维度来源",
                )
            )

    allowed_keys = {entry.source_key for entry in included_final}
    if generator_visible is None:
        generator_keys = allowed_keys - audit_only_keys
    else:
        generator_keys = (set(generator_visible) & allowed_keys) - audit_only_keys

    authority_fingerprint = knowledge_canonical_hash(
        {
            "kind": "knowledge_authority_package",
            "capability": policy.capability_id,
            "entries": [entry.to_dict() for entry in included_final],
        }
    )
    generator_fingerprint = knowledge_canonical_hash(
        {
            "kind": "knowledge_generator_package",
            "capability": policy.capability_id,
            "source_keys": sorted(generator_keys),
        }
    )

    truncated = any(section.truncated_reason for section in compiled.sections)
    scope_complete = not omitted and not truncated

    receipt = KnowledgeScopeReceipt(
        policy_version=1,
        capability=policy.capability_id,
        novel_id=novel_id,
        subject=subject,
        included=included_final,
        excluded=excluded,
        omitted=omitted,
        coverage=tuple(coverage),
        authority_fingerprint=authority_fingerprint,
        generator_fingerprint=generator_fingerprint,
        scope_complete=scope_complete,
        continuation=continuation,
        created_at=created_at,
    )
    return KnowledgeScopeBuild(
        receipt=receipt,
        generator_keys=tuple(sorted(generator_keys)),
        audit_only_keys=tuple(sorted(audit_only_keys)),
    )


def require_scope_complete(build: KnowledgeScopeBuild) -> None:
    """必查维度缺失或存在 omission 时阻断生成。"""
    receipt = build.receipt
    problems: list[str] = []
    if not receipt.scope_complete:
        if receipt.omitted:
            keys = ", ".join(entry.source_key for entry in receipt.omitted[:5])
            problems.append(f"存在预算或可读性 omission：{keys}")
        else:
            problems.append("编译产物存在截断，范围不完整")
    for item in receipt.coverage:
        if item.omitted:
            problems.append(
                f"必查维度 {item.dimension} 被排除：{item.omission_reason}"
            )
    ensure_no_excluded_backflow(build)
    if problems:
        raise KnowledgeContractError(
            "冻结范围不完整，阻断生成（"
            + scope_continuation_token(receipt)
            + "）："
            + "; ".join(problems)
        )


def ensure_no_excluded_backflow(build: KnowledgeScopeBuild) -> None:
    """作者显式排除的来源不得回流生成者包。"""
    excluded_keys = {entry.source_key for entry in build.receipt.excluded}
    leaked = excluded_keys & set(build.generator_keys)
    if leaked:
        raise KnowledgeContractError(
            "作者排除项回流生成者包：" + ", ".join(sorted(leaked))
        )


def scope_continuation_token(receipt: KnowledgeScopeReceipt) -> str:
    """阻断后可恢复的 continuation 指针；重整资料后重新冻结。"""
    return (
        f"scope_continuation:{receipt.capability}:{receipt.receipt_fingerprint()[:12]}"
    )


def shard_source_keys(
    source_keys: Iterable[str], *, shard_size: int = 64
) -> tuple[tuple[str, ...], ...]:
    """确定性分片：排序后按固定大小切块，分片间无重叠、并集等于全集。"""
    if shard_size <= 0:
        raise KnowledgeContractError("shard_size must be positive")
    ordered = tuple(sorted(set(source_keys)))
    return tuple(
        ordered[start : start + shard_size]
        for start in range(0, len(ordered), shard_size)
    )


def reduce_dispositions(
    shard_results: Iterable[Iterable[KnowledgeDirectorDisposition]],
    expected_keys: Iterable[str],
) -> tuple[KnowledgeDirectorDisposition, ...]:
    """确定性归并导演分片结果；要求每个来源 key 恰好被处置一次。"""
    expected = set(expected_keys)
    merged: dict[str, KnowledgeDirectorDisposition] = {}
    duplicates: list[str] = []
    for shard in shard_results:
        for disposition in shard:
            key = disposition.source_key
            if key in merged:
                duplicates.append(key)
                continue
            merged[key] = disposition
    missing = sorted(expected - set(merged))
    unknown = sorted(set(merged) - expected)
    problems: list[str] = []
    if missing:
        problems.append("missing: " + ", ".join(missing[:5]))
    if unknown:
        problems.append("unknown: " + ", ".join(unknown[:5]))
    if duplicates:
        problems.append("duplicate: " + ", ".join(sorted(set(duplicates))[:5]))
    if problems:
        raise KnowledgeContractError(
            "director shards do not cover manifest exactly once: "
            + "; ".join(problems)
        )
    return tuple(merged[key] for key in sorted(merged))


def validate_dimensions(dimensions: Iterable[str]) -> None:
    for dimension in dimensions:
        if dimension not in KNOWLEDGE_DIMENSIONS:
            raise KnowledgeContractError(f"unknown knowledge dimension: {dimension}")
