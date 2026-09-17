"""范围冻结引擎测试：manifest 规范化、omission 阻断、分片归并、排除回流。"""

from __future__ import annotations

import pytest

from modules.evidence.compilation.contracts import CompileOptions
from modules.evidence.compilation.knowledge.contracts import (
    KnowledgeContractError,
    KnowledgeDirectorDisposition,
    KnowledgeSubject,
)
from modules.evidence.compilation.knowledge.policies import (
    require_capability_policy,
)
from modules.evidence.compilation.knowledge.scope import (
    REFERENCE_USAGE_AUDIT_ONLY,
    build_scope_receipt,
    ensure_no_excluded_backflow,
    knowledge_subject_from_options,
    reduce_dispositions,
    require_scope_complete,
    shard_source_keys,
)
from modules.evidence.compilation.services.compiled_context import (
    CompiledContext,
    ContextItem,
    ContextSection,
    Tier,
    selection_ref_key,
)


def _section(
    key: str,
    sources: list[dict],
    *,
    excluded: bool = False,
    truncated_reason: str | None = None,
) -> ContextSection:
    return ContextSection(
        key=key,
        tier=Tier.P1,




                        content="\n".join(
            str(source.get("label") or source.get("id") or "-")
            for source in sources
        ),
        sources=list(sources),
        excluded=excluded,
        truncated_reason=truncated_reason,
        items=[
            ContextItem(
                key=f"{key}:{index}",
                content=str(source.get("label") or source.get("id") or "-"),
                source=dict(source),
            )
            for index, source in enumerate(sources)
        ],
    )


def _source(type_: str, id_: str, **extra) -> dict:
    return {"type": type_, "id": id_, "label": f"{type_} {id_}", **extra}


def _author_policy():
    return require_capability_policy("world.generation.suggestion")


def _subject() -> KnowledgeSubject:
    return KnowledgeSubject(subject_type="author")


def test_manifest_normalized_and_complete_by_default() -> None:
    compiled = CompiledContext(
        sections=[
            _section("world_entities", [_source("world_entity", "b"),
                _source("world_entity", "a")]),
            _section("world_bible_working_pages", [_source("world_bible_page", "p1")]),
            _section("author_task_note", [_source("task", "note")]),
        ]
    )
    build = build_scope_receipt(
        compiled, _author_policy(), _subject(), novel_id="novel-1"
    )
    receipt = build.receipt
    keys = receipt.source_keys()
    # 规范化：按 source_key 排序；无身份来源（type=task 无 id）不入 manifest
    assert keys == tuple(sorted(keys))
    assert "world_entity:a" in keys and "world_entity:b" in keys
    assert "world_bible_page:p1" in keys
    assert receipt.scope_complete is True
    assert not receipt.omitted
    assert generator_set(build) == set(keys)
    coverage = {item.dimension: item for item in receipt.coverage}
    assert coverage["world_entities"].covered_by == ("world_entity:a", "world_entity:b")
    assert coverage["world_bible"].covered_by == ("world_bible_page:p1",)
    require_scope_complete(build)


def generator_set(build) -> set[str]:
    return set(build.generator_keys)


def test_budget_omission_blocks_scope() -> None:
    omitted_item = ContextItem(
        key="world_entities:1",
        content="被预算驱逐的对象",
        source=_source("world_entity", "b"),
        selection_state="omitted",
        omission_reason="超过 token 预算后按低优先级移除",
    )
    compiled = CompiledContext(
        sections=[_section("world_entities", [_source("world_entity", "a")])],
        omitted_items=[omitted_item],
    )
    build = build_scope_receipt(
        compiled, _author_policy(), _subject(), novel_id="novel-1"
    )
    assert build.receipt.scope_complete is False
    assert [entry.source_key for entry in build.receipt.omitted] == ["world_entity:b"]
    with pytest.raises(KnowledgeContractError, match="omission"):
        require_scope_complete(build)


def test_required_dimension_fully_excluded_blocks_scope() -> None:
    compiled = CompiledContext(
        sections=[
            _section(
                "world_entities",
                [_source("world_entity", "a")],
                excluded=True,
            ),
            _section("world_bible_working_pages", [_source("world_bible_page", "p1")]),
        ]
    )
    build = build_scope_receipt(
        compiled, _author_policy(), _subject(), novel_id="novel-1"
    )
    assert [entry.source_key for entry in build.receipt.excluded] == ["world_entity:a"]
    coverage = {item.dimension: item for item in build.receipt.coverage}
    assert coverage["world_entities"].omitted is True
    assert "作者显式排除" in coverage["world_entities"].omission_reason
    with pytest.raises(KnowledgeContractError, match="world_entities"):
        require_scope_complete(build)


def test_truncated_section_marks_scope_incomplete() -> None:
    compiled = CompiledContext(
        sections=[
            _section(
                "world_entities",
                [_source("world_entity", "a")],
                truncated_reason="超过预算截断",
            )
        ]
    )
    build = build_scope_receipt(
        compiled, _author_policy(), _subject(), novel_id="novel-1"
    )
    assert build.receipt.scope_complete is False
    with pytest.raises(KnowledgeContractError, match="截断"):
        require_scope_complete(build)


def test_audit_only_reference_hidden_from_generator() -> None:
    pinned_source = _source("world_bible_page", "p9")
    pinned_ref = {
        "kind": "target",
        "target_ref": {
            "target_type": "world_bible_page",
            "target_id": "p9",
            "target_path": "",
        },
    }
    section = _section("world_bible_working_pages", [pinned_source])
    section = section.model_copy(
        update={
            "items": [
                ContextItem(
                    key="world_bible_working_pages:0",
                    content="作者钉住的页面",
                    source=pinned_source,
                    selection_state="author_pinned",
                    selection_ref=pinned_ref,
                )
            ]
        }
    )
    compiled = CompiledContext(sections=[section])
    build = build_scope_receipt(
        compiled,
        _author_policy(),
        _subject(),
        novel_id="novel-1",
        reference_usages={selection_ref_key(pinned_ref): REFERENCE_USAGE_AUDIT_ONLY},
    )
    assert "world_bible_page:p9" in build.receipt.source_keys()
    assert "world_bible_page:p9" not in build.generator_keys
    assert build.audit_only_keys == ("world_bible_page:p9",)
    hidden = [entry.source_key for entry in build.hidden_from_generator()]
    assert hidden == ["world_bible_page:p9"]
    require_scope_complete(build)


def test_excluded_backflow_detected() -> None:
    compiled = CompiledContext(
        sections=[
            _section("world_entities", [_source("world_entity", "secret")], excluded=True)
        ]
    )
    build = build_scope_receipt(
        compiled, _author_policy(), _subject(), novel_id="novel-1"
    )
    # 人为把排除项塞回生成者集合
    object.__setattr__(
        build, "generator_keys", ("world_entity:secret",)
    )
    with pytest.raises(KnowledgeContractError, match="回流"):
        ensure_no_excluded_backflow(build)


def test_generator_visible_intersection_and_fingerprints() -> None:
    compiled = CompiledContext(
        sections=[
            _section(
                "world_entities",
                [_source("world_entity", "a"), _source("world_entity", "b")],
            ),
        ]
    )
    full = build_scope_receipt(
        compiled, _author_policy(), _subject(), novel_id="novel-1"
    )
    restricted = build_scope_receipt(
        compiled,
        _author_policy(),
        _subject(),
        novel_id="novel-1",
        generator_visible=["world_entity:a", "world_entity:ghost"],
    )
    assert restricted.generator_keys == ("world_entity:a",)
    assert (
        restricted.receipt.generator_fingerprint
        != full.receipt.generator_fingerprint
    )
    assert (
        restricted.receipt.authority_fingerprint
        == full.receipt.authority_fingerprint
    )


def test_sharding_is_deterministic_and_complete() -> None:
    keys = [f"world_entity:{i}" for i in range(130)]
    shards = shard_source_keys(keys, shard_size=64)
    assert len(shards) == 3
    assert shards[0] == tuple(sorted(keys)[:64])
    flattened = [key for shard in shards for key in shard]
    assert len(flattened) == len(set(flattened)) == 130
    assert shard_source_keys(keys, shard_size=64) == shards


def test_reduce_dispositions_requires_exactly_once() -> None:
    keys = [f"k{i}" for i in range(5)]
    dispositions = [
        KnowledgeDirectorDisposition(source_key=key, disposition="allowed_for_generation")
        for key in keys
    ]
    merged = reduce_dispositions([dispositions[:3], dispositions[3:]], keys)
    assert merged == tuple(dispositions)

    with pytest.raises(KnowledgeContractError, match="missing"):
        reduce_dispositions([dispositions[:3]], keys)
    with pytest.raises(KnowledgeContractError, match="duplicate"):
        reduce_dispositions([dispositions, dispositions], keys)
    with pytest.raises(KnowledgeContractError, match="unknown"):
        reduce_dispositions(
            [
                dispositions
                + [
                    KnowledgeDirectorDisposition(
                        source_key="ghost", disposition="forbidden"
                    )
                ]
            ],
            keys,
        )


def test_knowledge_subject_from_options() -> None:
    options = CompileOptions(
        novel_id="novel-1",
        task="t",
        scope="scene",
        reveal_mode="character",
        viewpoint_character_id="char-7",
        visible_until_chapter=4,
        scene_id="scene-9",
    )
    subject = knowledge_subject_from_options(options)
    assert subject.subject_type == "character"
    assert subject.character_id == "char-7"
    assert subject.cutoff_chapter == 4
    assert subject.cutoff_scene_id == "scene-9"

    author_options = CompileOptions(
        novel_id="novel-1", task="t", scope="project", reveal_mode="author_full"
    )
    assert knowledge_subject_from_options(author_options).subject_type == "author"


def test_scope_complete_options_require_capability() -> None:
    with pytest.raises(ValueError, match="capability"):
        CompileOptions(
            novel_id="novel-1", task="t", scope="project", scope_complete=True
        )


def test_replay_whitelist_carries_governance_fields() -> None:
    from modules.evidence.compilation.services.confirmation_service import (
        ContextConfirmationService,
    )

    options = CompileOptions(
        novel_id="novel-1",
        task="t",
        scope="project",
        capability="world.generation.suggestion",
        scope_complete=True,
        reference_usages={"ref-key": REFERENCE_USAGE_AUDIT_ONLY},
    )
    payload = ContextConfirmationService._compile_options_json(options)
    assert payload["capability"] == "world.generation.suggestion"
    assert payload["scope_complete"] is True
    assert payload["reference_usages"] == {"ref-key": REFERENCE_USAGE_AUDIT_ONLY}
    restored = CompileOptions(**payload)
    assert restored.capability == options.capability
    assert restored.scope_complete is True
    assert restored.reference_usages == options.reference_usages


def test_content_hash_prefers_declared_hash() -> None:
    hashed = _source("world_entity", "a", content_hash="declared")
    section = _section("world_entities", [hashed])
    build = build_scope_receipt(
        CompiledContext(sections=[section]),
        _author_policy(),
        _subject(),
        novel_id="novel-1",
    )
    assert build.receipt.entry("world_entity:a").content_hash == "declared"


def test_confirmed_knowledge_source_count_dedupes_across_sections() -> None:
    """P1-7：入队冻结的来源上界按稳定 key 去重，且不小于实际 included。"""
    from types import SimpleNamespace

    from modules.evidence.compilation.facade import confirmed_knowledge_source_count
    from modules.evidence.compilation.services.compiled_context import (
        CompiledContext,
        ContextSection,
        Tier,
    )

    def _sources(*ids):
        return [{"type": "world_entity", "id": value, "label": value} for value in ids]

    compiled = CompiledContext(
        sections=[
            ContextSection(
                key="world_entities",
                tier=Tier.P1,
                content="",
                sources=_sources("a", "b"),
            ),
            ContextSection(
                key="world_bible_working_pages",
                tier=Tier.P2,
                content="",
                sources=_sources("b", "c"),
            ),
        ]
    )
    context = SimpleNamespace(compiled=compiled)
    assert confirmed_knowledge_source_count(context) == 3
