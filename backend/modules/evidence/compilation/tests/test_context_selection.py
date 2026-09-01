from __future__ import annotations

import pytest

from modules.evidence.compilation.contracts import CompileOptions
from modules.evidence.compilation.services.compiled_context import (
    CompiledContext,
    ContextItem,
    ContextSection,
    Tier,
)
from modules.evidence.compilation.services.context_compiler import ContextCompiler
from modules.evidence.compilation.services.review_projection import (
    context_review_metadata,
)


def _ref(entity_id: str) -> dict:
    return {
        "kind": "target",
        "target_ref": {
            "target_type": "world_entity",
            "target_id": entity_id,
            "target_path": "",
        },
    }


def _item(entity_id: str, *, required: bool = False) -> ContextItem:
    return ContextItem(
        key=entity_id,
        content=f"资料 {entity_id}",
        token_count=10,
        title=entity_id,
        source={"type": "world_entity", "id": entity_id},
        selection_ref=_ref(entity_id),
        selection_state="required" if required else "automatic",
        can_exclude=not required,
    )


def test_item_exclusion_changes_exact_rendered_section() -> None:
    section = ContextSection(
        key="world_entities",
        tier=Tier.P2,
        content="资料 entity-1\n资料 entity-2",
        token_count=20,
        items=[_item("entity-1"), _item("entity-2")],
    )

    sections, excluded, warnings = ContextCompiler._apply_item_exclusions(
        [section],
        [_ref("entity-2")],
        pinned_refs=[],
    )

    assert sections[0].content == "资料 entity-1"
    assert [item.key for item in excluded] == ["entity-2"]
    assert excluded[0].selection_state == "excluded"
    assert warnings == []


def test_required_item_cannot_be_excluded() -> None:
    section = ContextSection(
        key="required",
        tier=Tier.P0,
        content="资料 entity-1",
        token_count=10,
        items=[_item("entity-1", required=True)],
    )

    sections, excluded, warnings = ContextCompiler._apply_item_exclusions(
        [section],
        [_ref("entity-1")],
        pinned_refs=[],
    )

    assert sections[0].items[0].selection_state == "required"
    assert excluded == []
    assert warnings == ["核心参考资料不可排除：entity-1"]


def test_author_pinned_item_is_not_silently_trimmed() -> None:
    pinned = _item("entity-2").model_copy(
        update={"selection_state": "author_pinned"}
    )
    compiled = CompiledContext(
        sections=[
            ContextSection(
                key="required",
                tier=Tier.P0,
                content="必须资料" * 30,
                token_count=80,
                items=[_item("entity-1", required=True)],
            ),
            ContextSection(
                key="author_pinned_material",
                tier=Tier.P1,
                content="作者资料" * 30,
                token_count=80,
                items=[pinned],
            ),
        ],
        total_tokens=160,
        budget_tokens=100,
    ).enforce_budget()

    assert any(
        item.selection_state == "author_pinned"
        for section in compiled.sections
        for item in section.items
    )
    assert compiled.blockers == ["必需资料和作者添加资料超过本次可用容量"]


def test_selected_manifest_comes_from_actual_kept_items() -> None:
    compiled = CompiledContext(
        sections=[
            ContextSection(
                key="world_entities",
                tier=Tier.P2,
                content="资料 entity-1",
                token_count=10,
                items=[_item("entity-1")],
            )
        ]
    )
    options = CompileOptions(
        novel_id="00000000-0000-0000-0000-000000000001",
        task="生成",
        scope="world",
    )

    metadata = context_review_metadata(compiled, options)

    assert metadata["selected_asset_ids"]["world_entities"] == ["entity-1"]
    assert len(metadata["context_fingerprint"]) == 64


def test_context_fingerprint_tracks_provider_input_not_review_metadata() -> None:
    section = ContextSection(
        key="world_entities",
        tier=Tier.P2,
        content="旧塔仍在北港。",
        token_count=10,
        title="旧塔",
        preview="展示摘要",
        status="canonical",
        sources=[{"type": "world_entity", "id": "entity-1", "label": "旧塔"}],
    )
    changed_display = section.model_copy(
        update={"title": "旧塔资料", "preview": "另一段摘要", "status": "mixed"}
    )
    first = CompiledContext(sections=[section], activation_trace={"warning": "a"})
    second = CompiledContext(
        sections=[changed_display], activation_trace={"warning": "b"}
    )
    options = CompileOptions(novel_id="novel-1", task="生成", scope="world")

    assert (
        context_review_metadata(first, options)["context_fingerprint"]
        == context_review_metadata(second, options)["context_fingerprint"]
    )


@pytest.mark.asyncio
async def test_pinned_loader_errors_propagate(monkeypatch: pytest.MonkeyPatch) -> None:
    compiler = ContextCompiler()

    async def fail(*_args, **_kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(compiler, "_load_pinned_item", fail)
    options = CompileOptions(
        novel_id="novel-1",
        task="生成",
        scope="world",
        pinned_refs=[_ref("entity-1")],
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        await compiler._apply_pinned_refs(object(), [], options)
