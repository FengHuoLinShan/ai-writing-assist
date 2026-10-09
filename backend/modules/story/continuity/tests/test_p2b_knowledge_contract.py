"""P2-B 统一知识方言契约测试（B1 契约先行单元）。

覆盖四组验收点：

1. 结构校验：``KnowledgeStatement`` 三分类不变量（known 必有值绑定，
   false_belief/unknown 结构上不承载绑定，unknown 必有文本层）。
2. 旧 payload 兼容读取：事件路径三形态（完整绑定/无绑定/误信）与
   机器路径形态（``KnowledgeInPanorama``）读进新契约，缺什么落什么层。
3. 值绑定哈希口径：与 ``scene_state_view._knowledge_grants`` /
   ``_filter_entries`` 的 ``stable_hash`` 口径逐位对拍。
4. 揭示判定纯函数：两套揭示系统（story outline / world knowledge）现状
   行为矩阵对拍 + 「读者揭示只在已证明展示的原文范围内启用」判定通路。

隐式透传红线：``KnowledgeInPanorama`` 未声明 ``extra``（Pydantic 默认忽略
额外键），机器路径 payload 偷带值绑定键会静默透传、读回时静默消失——
``read_machine_knowledge`` 只认白名单结构，透传键一律不采信为绑定。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from infrastructure.stable_hash import stable_hash
from modules.story.continuity.field_provenance import (
    FieldProvenance,
    ProvenanceSourceRef,
)
from modules.story.continuity.knowledge_contract import (
    FALSE_MARKER_KEYS,
    UNSUPPORTED_READER_VIEW_DIMENSIONS,
    KnowledgeClass,
    KnowledgeDenialCause,
    KnowledgeOrigin,
    KnowledgeStatement,
    RevealDomain,
    SceneAnchor,
    bind_value,
    build_knowledge_grants,
    classify_knowledge,
    denial_reason,
    evaluate_reader_reveal,
    extract_scene_anchor,
    proven_shown_chapters,
    read_knowledge_statement,
    read_knowledge_statements,
    read_machine_knowledge,
    reveal_within_proven_shown,
    value_matches,
)
from modules.story.continuity.scene_state_view import SceneStateViewService
from modules.story.continuity.schemas import KnowledgeInPanorama


def _ref(chapter: int, **overrides) -> dict:
    base = {
        "draft_id": "d1",
        "chapter_index": chapter,
        "version_number": 1,
        "content_mode": "working",
        "start_offset": 0,
        "end_offset": 48,
        "source_hash": "h" * 64,
        "range_hash": "r" * 64,
    }
    base.update(overrides)
    return base


# ============================================================
# 1. 结构校验
# ============================================================


def test_p2b_known_statement_requires_bindings_and_subject() -> None:
    with pytest.raises(ValidationError, match="at least one value binding"):
        KnowledgeStatement(
            holder_id="c1",
            knowledge_class=KnowledgeClass.known,
            origin=KnowledgeOrigin.scene_event,
        )
    with pytest.raises(ValidationError, match="requires subject_id"):
        KnowledgeStatement(
            holder_id="c1",
            knowledge_class=KnowledgeClass.known,
            value_bindings={"custody_holder": bind_value("乙")},
            origin=KnowledgeOrigin.scene_event,
        )


def test_p2b_only_known_carries_bindings() -> None:
    bindings = {"custody_holder": bind_value("甲")}
    for knowledge_class in (KnowledgeClass.unknown, KnowledgeClass.false_belief):
        with pytest.raises(ValidationError, match="never grant"):
            KnowledgeStatement(
                holder_id="c1",
                subject_id="key",
                knowledge_class=knowledge_class,
                value_bindings=bindings,
                text_summary="乙误信钥匙已归还甲",
                origin=KnowledgeOrigin.scene_event,
            )


def test_p2b_unknown_statement_requires_text_summary() -> None:
    with pytest.raises(ValidationError, match="text summary"):
        KnowledgeStatement(
            holder_id="c1",
            knowledge_class=KnowledgeClass.unknown,
            origin=KnowledgeOrigin.scene_event,
        )


def test_p2b_statement_is_frozen() -> None:
    statement = read_knowledge_statement(
        {"character_id": "c1", "knowledge": "丙知道铜钥匙在乙手中"}
    )
    assert statement is not None
    with pytest.raises(ValidationError):
        statement.holder_id = "c2"  # type: ignore[misc]


# ============================================================
# 2. 旧 payload 兼容读取（事件路径）
# ============================================================

# 探索路径完整形态（与 test_scene_state_view._custody_fixture_events 同款）。
_FULL_EVENT_PAYLOAD = {
    "character_id": "bing",
    "subject_id": "key",
    "fields": ["custody_holder"],
    "known_values": {"custody_holder": "yi"},
    "knowledge": "丙知道铜钥匙在乙手中",
}

_FALSE_EVENT_PAYLOAD = {
    "character_id": "yi",
    "subject_id": "key",
    "fields": ["custody_holder"],
    "known_values": {"custody_holder": "jia"},
    "knowledge": "乙误信钥匙已归还甲",
    "false": True,
}


def test_p2b_full_event_payload_reads_as_known() -> None:
    statement = read_knowledge_statement(_FULL_EVENT_PAYLOAD)
    assert statement is not None
    assert statement.holder_id == "bing"
    assert statement.subject_id == "key"
    assert statement.knowledge_class is KnowledgeClass.known
    assert statement.known_fields == ("custody_holder",)
    assert statement.value_bindings == {"custody_holder": bind_value("yi")}
    assert statement.text_summary == "丙知道铜钥匙在乙手中"
    assert statement.origin is KnowledgeOrigin.scene_event


def test_p2b_unbound_event_payload_reads_as_unknown() -> None:
    statement = read_knowledge_statement(
        {"character_id": "bing", "subject_id": "key", "knowledge": "丙听说过这把钥匙"}
    )
    assert statement is not None
    assert statement.knowledge_class is KnowledgeClass.unknown
    assert statement.value_bindings == {}
    assert statement.text_summary == "丙听说过这把钥匙"


def test_p2b_unknown_without_text_gets_placeholder_not_dropped() -> None:
    statement = read_knowledge_statement({"character_id": "c1"})
    assert statement is not None
    assert statement.knowledge_class is KnowledgeClass.unknown
    assert statement.text_summary  # 与视图现状同文案兜底，不静默丢弃


def test_p2b_false_marker_payload_reads_as_false_belief() -> None:
    # 误信条目即便带完整三件套，也分类 false_belief 且不承载任何绑定
    # （误信不是知识——对齐 _knowledge_grants 先判误信再谈授予的现状）。
    statement = read_knowledge_statement(_FALSE_EVENT_PAYLOAD)
    assert statement is not None
    assert statement.knowledge_class is KnowledgeClass.false_belief
    assert statement.value_bindings == {}
    assert statement.known_fields == ("custody_holder",)  # 原字段列表保留


@pytest.mark.parametrize("marker", FALSE_MARKER_KEYS)
def test_p2b_both_false_markers_recognized(marker: str) -> None:
    statement = read_knowledge_statement(
        {"character_id": "c1", "knowledge": "误信", marker: True}
    )
    assert statement is not None
    assert statement.knowledge_class is KnowledgeClass.false_belief


def test_p2b_partial_binding_only_binds_intersection() -> None:
    # fields ⊄ known_values：知道有 note 字段但不知道值——字段列表保留，
    # 只绑定交集，交集非空即 known。
    statement = read_knowledge_statement(
        {
            "character_id": "c1",
            "subject_id": "key",
            "fields": ["custody_holder", "note"],
            "known_values": {"custody_holder": "yi"},
            "knowledge": "丙知道保管者",
        }
    )
    assert statement is not None
    assert statement.knowledge_class is KnowledgeClass.known
    assert statement.known_fields == ("custody_holder", "note")
    assert statement.value_bindings == {"custody_holder": bind_value("yi")}
    # 全无交集 → unknown（无法表达「知道哪个值」）。
    empty = read_knowledge_statement(
        {
            "character_id": "c1",
            "subject_id": "key",
            "fields": ["note"],
            "known_values": {"custody_holder": "yi"},
        }
    )
    assert empty is not None
    assert empty.knowledge_class is KnowledgeClass.unknown


def test_p2b_holder_alias_and_missing_holder() -> None:
    assert read_knowledge_statement({"holder_id": "c1", "knowledge": "x"}) is not None
    assert read_knowledge_statement({"knowledge": "无归属知识"}) is None
    assert read_knowledge_statement(None) is None
    assert read_knowledge_statement("not-a-dict") is None  # type: ignore[arg-type]


def test_p2b_read_state_json_tolerates_old_and_malformed() -> None:
    assert read_knowledge_statements(None) == []
    assert read_knowledge_statements({}) == []  # 旧格式无知识键
    assert read_knowledge_statements({"character_knowledge": "bad"}) == []
    statements = read_knowledge_statements(
        {
            "character_knowledge": [
                _FULL_EVENT_PAYLOAD,
                {"not": "a proper entry without holder"},
                "junk",
                _FALSE_EVENT_PAYLOAD,
            ]
        }
    )
    assert [item.knowledge_class for item in statements] == [
        KnowledgeClass.known,
        KnowledgeClass.false_belief,
    ]


def test_p2b_read_carries_source_and_scene_anchor() -> None:
    from modules.story.continuity.field_provenance import ProvenanceSourceRef

    refs = (ProvenanceSourceRef.model_validate(_ref(2)),)
    statement = read_knowledge_statement(
        {**_FULL_EVENT_PAYLOAD, "scene_index": 3, "scene_sequence": 7},
        event_id="evt-1",
        source_refs=refs,
    )
    assert statement is not None
    assert statement.event_id == "evt-1"
    assert statement.source_refs == refs
    assert statement.scene_anchor == SceneAnchor(scene_index=3, scene_sequence=7)


def test_p2b_scene_anchor_extraction_tolerates_wrong_types() -> None:
    anchor = extract_scene_anchor(
        {"scene_id": "s1", "scene_index": True, "scene_sequence": "7", "extra": 1}
    )
    assert anchor.scene_id == "s1"
    assert anchor.scene_index is None  # bool 不当 int
    assert anchor.scene_sequence is None  # 字符串数字不当 int
    assert not extract_scene_anchor(None).has_anchor


# ============================================================
# 3. 值绑定哈希口径（对拍 _knowledge_grants / _filter_entries 现状）
# ============================================================


def test_p2b_grants_match_scene_state_view_implementation() -> None:
    """契约授予表与 ``_knowledge_grants`` 对同一 checkpoint 逐位相等。"""
    state_json = {
        "character_knowledge": [
            _FULL_EVENT_PAYLOAD,  # 丙：known（绑定 custody_holder=yi）
            _FALSE_EVENT_PAYLOAD,  # 乙：误信，永不授予
            {  # 丙：无值绑定，不授予
                "character_id": "bing",
                "subject_id": "key",
                "knowledge": "丙还听说过别的",
            },
        ]
    }
    legacy = SceneStateViewService._knowledge_grants(
        SimpleNamespace(state_json=state_json), "bing"
    )
    unified = build_knowledge_grants(read_knowledge_statements(state_json), "bing")
    # frozenset 与 set 按值比较：逐位对拍旧实现的授予表。
    assert unified == legacy
    assert unified == {"key": {"custody_holder": frozenset({bind_value("yi")})}}


def test_p2b_value_matches_uses_filter_entry_semantics() -> None:
    for value in ("yi", 3, ["a", {"b": 1}], {"k": "v"}, None):
        binding = bind_value(value)
        assert value_matches(binding, value) is True
        assert value_matches(binding, "other") is False
        # 口径即 stable_hash 默认参数（_knowledge_grants 与 _filter_entries 同款）。
        assert binding == stable_hash(value)


def test_p2b_grants_skip_other_holders_and_unbound_classes() -> None:
    statements = read_knowledge_statements(
        {"character_knowledge": [_FULL_EVENT_PAYLOAD, _FALSE_EVENT_PAYLOAD]}
    )
    assert build_knowledge_grants(statements, "yi") == {}  # 乙只有误信
    assert build_knowledge_grants(statements, "nobody") == {}
    # 契约内查询：binding_hashes 只看 known 且 subject 匹配。
    known = statements[0]
    assert known.binding_hashes("key", "custody_holder") == frozenset({bind_value("yi")})
    assert known.binding_hashes("key", "custody_owner") == frozenset()
    assert known.binding_hashes("other", "custody_holder") == frozenset()
    false_belief = statements[1]
    assert false_belief.binding_hashes("key", "custody_holder") == frozenset()


def test_p2b_denial_reason_three_mutually_exclusive_causes() -> None:
    """B0 xfail 缺口承载：三类拒绝原因互斥可区分 + 授予返回 None。"""

    def reason(
        payloads: list[dict],
        value: Any,
        *,
        field: str = "custody_holder",
        holder_id: str = "bing",
    ):
        return denial_reason(
            read_knowledge_statements({"character_knowledge": payloads}),
            holder_id=holder_id,
            subject_id="key",
            field=field,
            value=value,
        )

    # 授予：known 条目绑定当前值。
    assert reason([_FULL_EVENT_PAYLOAD], "yi") is None
    # 值不匹配：旧值授权对新值（B0 用例 1——口令改写）。
    assert (
        reason([_FULL_EVENT_PAYLOAD], "jia")
        is KnowledgeDenialCause.knowledge_value_mismatch
    )
    # 误信：仅有误信条目（含结构上可授予的三件套形态）——零授予归因误信
    # （夹具 holder 是乙，对乙本人才有归因意义）。
    assert (
        reason([_FALSE_EVENT_PAYLOAD], "jia", holder_id="yi")
        is KnowledgeDenialCause.false_belief
    )
    # 无条目：同场旁观/部分知晓的未覆盖字段（不知道 ≠ 知道没有）。
    assert reason([], "yi") is KnowledgeDenialCause.no_knowledge_entry
    assert (
        reason([_FULL_EVENT_PAYLOAD], "yi", field="secret_relation")
        is KnowledgeDenialCause.no_knowledge_entry
    )
    # unknown 文本条目不构成字段级授予：对该字段等同无条目。
    assert (
        reason(
            [{"character_id": "bing", "subject_id": "key", "knowledge": "听说过"}],
            "yi",
        )
        is KnowledgeDenialCause.no_knowledge_entry
    )
    # 同 holder 的 known 条目授予不受其误信条目影响（拒绝时归因值不匹配——
    # 授予来自知识，误信不参与）。
    bing_false = {**_FALSE_EVENT_PAYLOAD, "character_id": "bing"}
    assert (
        reason([_FULL_EVENT_PAYLOAD, bing_false], "jia")
        is KnowledgeDenialCause.knowledge_value_mismatch
    )
    assert reason([_FULL_EVENT_PAYLOAD, bing_false], "yi") is None


# ============================================================
# 4. 机器路径映射（P2-B 裁定：降级为文本知识，不冒充值绑定）
# ============================================================

# state_gate 产出的机器路径 payload 形态（KnowledgeInPanorama 声明字段）。
_MACHINE_PAYLOAD = {
    "id": "evolution-knowledge-uuid5",
    "character_id": "yi",
    "target_type": "entity",
    "target_id": "key",
    "knowledge_level": "partial",
    "known_content": "乙听说钥匙被交给了别人保管",
    "source_chapter_index": 4,
    "status": "canonical",
}


def test_p2b_machine_payload_maps_to_unbound_text_knowledge() -> None:
    statement = read_machine_knowledge(_MACHINE_PAYLOAD)
    assert statement is not None
    assert statement.holder_id == "yi"
    assert statement.knowledge_class is KnowledgeClass.unknown
    assert statement.value_bindings == {}
    assert statement.subject_id is None  # target_id 无字段语义，不冒充绑定锚
    assert statement.text_summary == "乙听说钥匙被交给了别人保管"
    assert statement.origin is KnowledgeOrigin.machine_observation
    assert statement.entry_id == "evolution-knowledge-uuid5"
    assert statement.unchecked_note is None  # partial 非传闻级


def test_p2b_machine_rumor_level_adds_unchecked_note() -> None:
    statement = read_machine_knowledge({**_MACHINE_PAYLOAD, "knowledge_level": "rumor"})
    assert statement is not None
    assert statement.unchecked_note is not None
    assert "传闻" in statement.unchecked_note


def test_p2b_machine_smuggled_binding_keys_are_not_adopted() -> None:
    """隐式透传红线：extra=ignore 让绑定键静默透传，转换器不采信。"""
    smuggled = {
        **_MACHINE_PAYLOAD,
        "subject_id": "key",
        "fields": ["custody_holder"],
        "known_values": {"custody_holder": "yi"},
    }
    # 红线存在性：KnowledgeInPanorama 校验静默通过（Pydantic 默认忽略额外键），
    # 机器路径 event 会带着这些键持久化——方言统一时不得当作值绑定采信。
    validated = KnowledgeInPanorama.model_validate(smuggled)
    assert "fields" not in validated.model_dump()
    statement = read_machine_knowledge(smuggled)
    assert statement is not None
    assert statement.knowledge_class is KnowledgeClass.unknown
    assert statement.value_bindings == {}
    assert statement.subject_id is None
    # 分类绑定方言：机器方言下即使三件套键齐备也恒 unknown（不采信透传），
    # 事件方言下同形态才是 known——同一键形态语义随方言不同。
    assert classify_knowledge(smuggled) is KnowledgeClass.known
    assert (
        classify_knowledge(smuggled, origin=KnowledgeOrigin.machine_observation)
        is KnowledgeClass.unknown
    )


def test_p2b_machine_statement_cannot_be_constructed_as_known() -> None:
    # 结构不变量兜底：即便接线层手误传绑定，unknown 条目也构造不出绑定。
    with pytest.raises(ValidationError):
        KnowledgeStatement(
            holder_id="yi",
            knowledge_class=KnowledgeClass.unknown,
            value_bindings={"custody_holder": bind_value("yi")},
            text_summary="文本知识",
            origin=KnowledgeOrigin.machine_observation,
        )


# ============================================================
# 5. 揭示边界判定纯函数
# ============================================================


def test_p2b_outline_domain_defaults_public_without_policy() -> None:
    # story outline 结构层现状：无策略且无揭示主张记录 → 默认公开
    # （结构层是作者大纲资产，test_reader_view_gates_entities_by_reveal 钉定）。
    assert (
        evaluate_reader_reveal(
            domain=RevealDomain.outline_structure,
            has_policy=False,
            cutoff_chapter=5,
        )
        is True
    )
    # 有策略时保守：无已揭示锚 → 隐藏；当章（== cutoff）不揭示。
    assert (
        evaluate_reader_reveal(
            domain=RevealDomain.outline_structure,
            has_policy=True,
            cutoff_chapter=5,
            reveal_chapters=frozenset(),
        )
        is False
    )
    assert (
        evaluate_reader_reveal(
            domain=RevealDomain.outline_structure,
            has_policy=True,
            cutoff_chapter=5,
            reveal_chapters=frozenset({5}),
        )
        is False
    )
    assert (
        evaluate_reader_reveal(
            domain=RevealDomain.outline_structure,
            has_policy=True,
            cutoff_chapter=5,
            reveal_chapters=frozenset({3, 4}),
        )
        is True
    )


def test_p2b_outline_domain_secret_with_claim_not_revealed_early() -> None:
    """B0 xfail 缺口承载：无策略但有揭示主张记录时不得默认公开。

    场景即 test_p2b_reader_before_reveal_scene_must_not_see_secret：秘密在
    Scene 0（第 1 章）已有作者层记录，揭示主张锚在第 2 章——揭示主张记录
    把对象移入「须证明」域，锚未到 cutoff → 隐藏；到锚章且 < cutoff → 公开。
    """
    # 读者在第 1 章（cutoff=1），揭示主张锚=第 2 章：未揭示。
    assert (
        evaluate_reader_reveal(
            domain=RevealDomain.outline_structure,
            has_policy=False,
            cutoff_chapter=1,
            reveal_chapters=frozenset({2}),
        )
        is False
    )
    # 读者读到第 3 章，主张锚（2）已过且当章不揭示语义下成立：公开。
    assert (
        evaluate_reader_reveal(
            domain=RevealDomain.outline_structure,
            has_policy=False,
            cutoff_chapter=3,
            reveal_chapters=frozenset({2}),
        )
        is True
    )
    # 有主张记录但 cutoff 未知 → 不猜（隐藏）。
    assert (
        evaluate_reader_reveal(
            domain=RevealDomain.outline_structure,
            has_policy=False,
            cutoff_chapter=None,
            reveal_chapters=frozenset({2}),
        )
        is False
    )


def test_p2b_world_domain_matches_reader_revealed_behavior() -> None:
    """world 知识层对拍 ``_reader_revealed``：public_baseline 优先、
    无 cutoff/无锚隐藏、严格小于当章不揭示。"""
    from modules.world.services.core.knowledge_visibility_service import (
        KnowledgeVisibilityService,
    )

    def legacy(public_baseline: bool, reveal_chapter: int | None, cutoff: int | None):
        return KnowledgeVisibilityService._reader_revealed(
            SimpleNamespace(
                public_baseline=public_baseline,
                reveal_chapter_index=reveal_chapter,
            ),
            cutoff,
        )

    def unified(
        public_baseline: bool, reveal_chapter: int | None, cutoff: int | None
    ) -> bool:
        return evaluate_reader_reveal(
            domain=RevealDomain.world_knowledge,
            has_policy=True,
            cutoff_chapter=cutoff,
            reveal_chapters=frozenset({reveal_chapter})
            if reveal_chapter is not None
            else frozenset(),
            public_baseline=public_baseline,
        )

    matrix = [
        (True, None, None),
        (True, 7, 9),
        (False, None, None),
        (False, None, 9),
        (False, 7, None),
        (False, 9, 9),  # 当章不揭示
        (False, 8, 9),
    ]
    for public_baseline, reveal_chapter, cutoff in matrix:
        assert unified(public_baseline, reveal_chapter, cutoff) is legacy(
            public_baseline, reveal_chapter, cutoff
        ), (public_baseline, reveal_chapter, cutoff)


def test_p2b_unsupported_reader_dimensions_pinned() -> None:
    # 第一阶段未支持的 reader timeline/causality 保持显式 unsupported，
    # 不得以作者全知视图补齐。
    assert UNSUPPORTED_READER_VIEW_DIMENSIONS == ("timeline", "causality")


# ============================================================
# 6. 已证明展示的原文范围（读者揭示启用前置）
# ============================================================


def _provenance(chapter: int, *, with_refs: bool = True) -> FieldProvenance:
    return FieldProvenance(
        field_key="custody_holder",
        dimension="entities",
        event_id="evt-1",
        subject_ref="key",
        source_refs=(
            (ProvenanceSourceRef.model_validate(_ref(chapter)),) if with_refs else ()
        ),
        version=1 if with_refs else 0,
        recorded_at_sequence=1,
    )


def test_p2b_proven_shown_chapters_only_from_sourced_refs() -> None:
    records = [
        _provenance(2),
        _provenance(3),
        _provenance(9, with_refs=False),  # unverified：追到事件不等于读者见过
    ]
    assert proven_shown_chapters(records) == frozenset({2, 3})


def test_p2b_reveal_within_proven_shown() -> None:
    proven = frozenset({2, 3})
    assert reveal_within_proven_shown(3, proven) is True
    assert reveal_within_proven_shown(2, proven) is True
    assert reveal_within_proven_shown(4, proven) is False  # 计划了但正文未证明
    assert reveal_within_proven_shown(None, proven) is False  # 无锚不猜
    assert reveal_within_proven_shown(2, frozenset()) is False


def test_p2b_reader_reveal_requires_both_cutoff_and_proof() -> None:
    """启用读者揭示的完整通路：cutoff 判定 + 已展示证明双闸。"""
    revealed = evaluate_reader_reveal(
        domain=RevealDomain.world_knowledge,
        has_policy=True,
        cutoff_chapter=5,
        reveal_chapters=frozenset({3}),
    )
    assert revealed is True
    assert reveal_within_proven_shown(3, frozenset({2, 3})) is True
    # cutoff 过但正文未证明展示 → 不启用。
    assert reveal_within_proven_shown(3, frozenset({9})) is False
