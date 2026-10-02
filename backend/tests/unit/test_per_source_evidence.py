"""逐源上下文证据（B8）测试：逐源 token、处置状态、哈希基底与元数据上限。"""

from __future__ import annotations

import json

from modules.evidence.compilation.knowledge.contracts import (
    KnowledgeScopeReceipt,
    KnowledgeSourceEntry,
    KnowledgeSubject,
)
from modules.evidence.compilation.knowledge.policies import (
    CapabilityKnowledgePolicy,
)
from modules.evidence.compilation.knowledge.scope import build_scope_receipt
from modules.evidence.compilation.services.compiled_context import (
    CompiledContext,
    ContextItem,
    ContextSection,
    Tier,
)


def _policy() -> CapabilityKnowledgePolicy:
    # 直接取注册表里的 writing.generate 策略，避免复制字段。
    from modules.evidence.contracts import CAPABILITY_REGISTRY

    return CAPABILITY_REGISTRY["writing.generate"]


def _section(
    key: str,
    *,
    items: list[ContextItem] | None = None,
    sources: list[dict] | None = None,
    excluded: bool = False,
    tier: Tier = Tier.P2,
) -> ContextSection:
    return ContextSection(
        key=key,
        tier=tier,
        content="".join(item.content for item in (items or [])) or "fallback",
        token_count=sum(item.token_count for item in (items or [])) or 1,
        sources=sources or [],
        items=items,
        excluded=excluded,
    )


def _item(
    key: str,
    *,
    token_count: int = 10,
    selection_state: str = "automatic",
    omission_reason: str | None = None,
    source: dict | None = None,
) -> ContextItem:
    return ContextItem(
        key=key,
        content=f"content-of-{key}",
        token_count=token_count,
        source=source
        or {"type": "world_entity", "id": key, "content_hash": f"hash-{key}"},
        selection_state=selection_state,
        omission_reason=omission_reason,
    )


def _build(*sections: ContextSection, **overrides) -> KnowledgeScopeReceipt:
    compiled = CompiledContext(sections=list(sections), budget_tokens=9999)
    build = build_scope_receipt(
        compiled,
        _policy(),
        KnowledgeSubject(subject_type="author"),
        novel_id="11111111-1111-1111-1111-111111111111",
        **overrides,
    )
    return build.receipt


def test_receipt_records_per_source_tokens_and_states() -> None:
    receipt = _build(
        _section(
            "world_entities",
            items=[
                _item("ent-a", token_count=120),
                _item(
                    "ent-b",
                    token_count=80,
                    selection_state="omitted",
                    omission_reason="超过预算",
                ),
            ],
        )
    )

    entry_a = receipt.entry("world_entity:ent-a")
    entry_b = receipt.entry("world_entity:ent-b")
    assert entry_a is not None and entry_a.token_count == 120
    assert entry_a.state == "included"
    assert entry_b is not None and entry_b.token_count == 80
    assert entry_b.state == "omitted"
    assert entry_b.state_reason == "超过预算"

    # run 账本可复算逐源 token 构成
    serialized = receipt.to_dict()
    tokens = {item["source_key"]: item["token_count"] for item in serialized["included"]}
    assert tokens["world_entity:ent-a"] == 120
    assert tokens["world_entity:ent-b"] == 80


def test_trimmed_and_omitted_are_distinguished() -> None:
    from modules.evidence.compilation.services.compiled_context import (
        ContextBudgetEvent,
    )

    compiled = CompiledContext(
        sections=[
            _section("characters", items=[_item("char-1", token_count=50)]),
            _section("memory_records", items=[_item("mem-1", token_count=30)]),
        ],
        budget_tokens=9999,
        truncated_keys=["characters"],
        evicted_keys=["memory_records"],
        budget_events=[
            ContextBudgetEvent(
                section_key="memory_records",
                event_type="evicted",
                reason="超过 token 预算后按低优先级移除",
                before_tokens=30,
                after_tokens=0,
                tier=3,
            )
        ],
    )
    build = build_scope_receipt(
        compiled,
        _policy(),
        KnowledgeSubject(subject_type="author"),
        novel_id="11111111-1111-1111-1111-111111111111",
    )
    receipt = build.receipt
    char_entry = receipt.entry("world_entity:char-1")
    mem_entry = receipt.entry("world_entity:mem-1")
    assert char_entry is not None and char_entry.state == "trimmed"
    assert mem_entry is not None and mem_entry.state == "omitted"
    assert "截断" in char_entry.state_reason
    assert "移除" in mem_entry.state_reason


def test_hash_basis_content_and_identity() -> None:
    receipt = _build(
        _section(
            "world_entities",
            items=[
                _item("ent-with-hash"),  # source 带 content_hash
                _item(
                    "ent-identity",
                    source={
                        "type": "world_entity",
                        "id": "ent-identity",
                        "label": "只有身份",
                    },
                ),
            ],
        )
    )

    with_hash = receipt.entry("world_entity:ent-with-hash")
    identity_only = receipt.entry("world_entity:ent-identity")
    assert with_hash is not None and with_hash.hash_basis == "content"
    assert identity_only is not None and identity_only.hash_basis == "content"
    unmaterialized = _build(
        _section(
            "world_entities",
            items=[_item("body")],
            sources=[{"type": "draft", "id": "metadata-only"}],
        )
    ).entry("draft:metadata-only")
    assert unmaterialized.hash_basis == "identity" and unmaterialized.token_count is None
    changed_item = _item(
        "ent-identity", source={"type": "world_entity", "id": "ent-identity"}
    ).model_copy(update={"content": "changed body"})
    changed = _build(_section("world_entities", items=[changed_item])).entry(
        "world_entity:ent-identity"
    )
    assert changed.content_hash != identity_only.content_hash


def test_atomic_multisource_budget_evidence_keeps_shared_count_once() -> None:
    section = ContextSection(
        key="working_pages",
        tier=Tier.P3,
        content='[{"text":"first"},{"text":"second"}]',
        token_count=20,
        sources=[{"type": "draft", "id": "a"}, {"type": "draft", "id": "b"}],
    )
    compiled = CompiledContext(
        sections=[section], total_tokens=20, budget_tokens=1
    ).enforce_budget()
    receipt = build_scope_receipt(
        compiled, _policy(), KnowledgeSubject(subject_type="author"), novel_id="n"
    ).receipt
    assert {e.source_id for e in receipt.omitted} == {"a", "b"}
    assert all(
        e.state == "omitted" and e.hash_basis == "content" for e in receipt.omitted
    )
    groups = {g["key"]: g for e in receipt.omitted for g in e.token_groups}
    assert sum(g["token_count"] for g in groups.values()) == 20
    assert all(g["shared"] for g in groups.values())
    assert all(e.token_count is None for e in receipt.omitted)  # 不冒充独立消耗
    assert (
        KnowledgeScopeReceipt.from_dict(receipt.to_dict()).to_dict() == receipt.to_dict()
    )


def test_omitted_item_retains_tokens_and_repeated_source_sums_distinct_items() -> None:
    source = {"type": "draft", "id": "same"}
    section = _section(
        "world_entities",
        items=[
            _item("part-a", token_count=12, source=source),
            _item("part-b", token_count=8, source=source),
        ],
        tier=Tier.P3,
    )
    compiled = CompiledContext(
        sections=[section], total_tokens=20, budget_tokens=1
    ).enforce_budget()
    receipt = build_scope_receipt(
        compiled, _policy(), KnowledgeSubject(subject_type="author"), novel_id="n"
    ).receipt
    assert receipt.omitted[0].token_count == 20
    assert len(receipt.omitted[0].token_groups) == 2


def test_fingerprint_stable_without_evidence_fields() -> None:
    base = KnowledgeSourceEntry(
        source_key="world_entity:x",
        source_type="world_entity",
        source_id="x",
        content_hash="h",
    )
    enriched = KnowledgeSourceEntry(
        source_key="world_entity:x",
        source_type="world_entity",
        source_id="x",
        content_hash="h",
        token_count=42,
        state="trimmed",
        state_reason="截断",
        hash_basis="identity",
    )

    assert base._fingerprint_dict() == enriched._fingerprint_dict()
    assert base.to_dict() != enriched.to_dict()

    # 指纹整体不受证据字段影响（既有确认不漂移）
    subject = KnowledgeSubject(subject_type="author")
    receipt_a = KnowledgeScopeReceipt(
        policy_version=1,
        capability="writing.generate",
        novel_id="n",
        subject=subject,
        included=(base,),
        scope_complete=True,
    )
    receipt_b = KnowledgeScopeReceipt(
        policy_version=1,
        capability="writing.generate",
        novel_id="n",
        subject=subject,
        included=(enriched,),
        scope_complete=True,
    )
    assert receipt_a.receipt_fingerprint() == receipt_b.receipt_fingerprint()


def test_source_entry_roundtrip_preserves_evidence() -> None:
    entry = KnowledgeSourceEntry(
        source_key="scene:s1",
        source_type="scene",
        source_id="s1",
        content_hash="hash",
        token_count=77,
        state="trimmed",
        state_reason="按条目截断",
        hash_basis="identity",
    )

    restored = KnowledgeSourceEntry.from_dict(json.loads(json.dumps(entry.to_dict())))

    assert restored == entry


def test_source_entry_metadata_size_is_bounded() -> None:
    """每个来源的元数据体积上限：防止账本条目无界膨胀。

    构建点对 state_reason/label 设 200 字符上界；身份字段（source_key 等）
    由真实 id（UUID/短 key）决定。用现实极端值断言整体序列化有界。
    """
    from modules.evidence.compilation.knowledge.scope import build_scope_receipt

    compiled = CompiledContext(
        sections=[
            _section(
                "world_entities",
                items=[
                    _item(
                        "x",
                        selection_state="omitted",
                        omission_reason="超长原因" * 100,
                        source={
                            "type": "world_entity",
                            "id": "x",
                            "content_hash": "h" * 64,
                        },
                    )
                ],
            )
        ],
        budget_tokens=9999,
    )
    receipt = build_scope_receipt(
        compiled,
        _policy(),
        KnowledgeSubject(subject_type="author"),
        novel_id="11111111-1111-1111-1111-111111111111",
    ).receipt
    entry = receipt.included[0]

    assert len(entry.state_reason) <= 200
    serialized = json.dumps(entry.to_dict(), ensure_ascii=False)
    assert len(serialized.encode("utf-8")) <= 2048

def test_token_groups_are_capped_with_overflow_record() -> None:
    """单源 token_groups 数量有上界：超限折叠为 __overflow__，账目仍有界。"""
    shared_source = {"type": "world_entity", "id": "ent-many", "content_hash": "h"}
    items = [
        _item(f"grp-{index:03d}", token_count=100 + index, source=dict(shared_source))
        for index in range(40)
    ]
    receipt = _build(_section("world_entities", items=items))

    entry = receipt.entry("world_entity:ent-many")
    assert entry is not None
    groups = entry.token_groups
    assert len(groups) == 33  # 32 条 + 1 条 overflow
    overflow = groups[-1]
    assert overflow["key"] == "__overflow__:world_entity:ent-many"
    assert overflow["dropped_group_count"] == 8
    # 保留下的是 token 数最大的 32 组
    kept_tokens = sorted(g["token_count"] for g in groups[:-1])
    assert kept_tokens == list(range(108, 140))
    # 折叠不改变逐源 token 复算口径（全量 = 保留组 + overflow 折叠合计）
    assert entry.token_count == sum(
        g["token_count"] for g in groups[:-1] if not g["shared"]
    ) + overflow["token_count"]


def test_token_group_overflow_keeps_shared_groups_and_is_source_scoped() -> None:
    """多来源各自溢出时 overflow 不按 key 互相合并；共享组不被折叠，
    跨来源按 key 去重复算仍能找回它。"""
    sources = {
        name: {"type": "world_entity", "id": name, "content_hash": f"h-{name}"}
        for name in ("a", "b")
    }
    own = _section(
        "world_entities",
        items=[
            _item(f"{name}-{index:03d}", token_count=10 + index, source=dict(src))
            for name, src in sources.items()
            for index in range(40)
        ],
    )
    shared = ContextSection(
        key="working_pages",
        tier=Tier.P3,
        content="indivisible",
        token_count=7,
        sources=[dict(src) for src in sources.values()],
    )
    receipt = _build(own, shared)

    groups_by_source = {
        name: receipt.entry(f"world_entity:{name}").token_groups for name in sources
    }
    for name, groups in groups_by_source.items():
        assert sum(1 for g in groups if g["shared"]) == 1
        overflow = [g for g in groups if g["key"].startswith("__overflow__")]
        assert [g["key"] for g in overflow] == [f"__overflow__:world_entity:{name}"]
        assert overflow[0]["dropped_group_count"] == 8

    # 跨来源按 key 去重复算：两条 overflow 各自保留，共享块只计一次
    deduped = {
        g["key"]: g for groups in groups_by_source.values() for g in groups
    }
    own_total = sum(10 + index for index in range(40)) * 2
    assert sum(g["token_count"] for g in deduped.values()) == own_total + 7
