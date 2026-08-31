from __future__ import annotations

from modules.evidence.compilation.contracts import CompileOptions
from modules.evidence.compilation.schemas import ContextCompileRequest
from modules.evidence.compilation.services.compiled_context import (
    CompiledContext,
    ContextItem,
    ContextSection,
    Tier,
)
from modules.evidence.compilation.services.context_compiler import ContextCompiler
from modules.evidence.compilation.services.review_projection import (
    context_option_fingerprint,
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


def test_option_fingerprint_ignores_scene_derived_chapter_index() -> None:
    payload = {
        "novel_id": "00000000-0000-0000-0000-000000000001",
        "action": "story.one_click.simulate",
        "task": "一键推演当前场景",
        "scope": "scene",
        "scene_id": "00000000-0000-0000-0000-000000000002",
    }
    preview = ContextCompileRequest(**payload)
    confirmed = CompileOptions(
        novel_id=payload["novel_id"],
        consumer_action=payload["action"],
        task=payload["task"],
        scope=payload["scope"],
        scene_id=payload["scene_id"],
        requested_chapter_index=None,
        chapter_index=1,
    )

    assert context_option_fingerprint(preview) == context_option_fingerprint(
        confirmed
    )
