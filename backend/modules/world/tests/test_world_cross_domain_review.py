"""Cross-domain review uses confirmed text and exact, current source versions."""

import hashlib
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core.errors import ConflictError
from modules.evidence.compilation.services.compiled_context import (
    CompiledContext,
    ContextItem,
    ContextSection,
    Tier,
)
from modules.world.map_atlas_models import MapAtlasNode, MapAtlasRevision
from modules.world.models import CoreEntity
from modules.world.schemas import WorldImpactSourceReadRequest
from modules.world.services.worldbuilding.world_impact_service import WorldImpactService
from modules.world.services.worldbuilding.world_validation_service import (
    WorldValidationService,
)


@pytest.mark.asyncio
async def test_semantic_scope_uses_retained_confirmed_text_and_all_selected_domains(
    db_session, project_novel_id
):
    root, thread, map_id, draft = (str(uuid.uuid4()) for _ in range(4))
    source_ref = {
        "draft_id": draft,
        "chapter_index": 1,
        "version_number": 1,
        "content_mode": "canonical",
        "start_offset": 2,
        "end_offset": 5,
        "source_hash": "a" * 64,
        "range_hash": "b" * 64,
    }
    entries = []
    for kind, target_id, text in (
        ("core_entity", root, "确认后的世界摘要"),
        ("story_thread", thread, "确认后的剧情约束"),
        ("map_node", map_id, "确认后的空间声明"),
    ):
        entries.append(
            ContextItem(
                key=target_id,
                content=text,
                title=text,
                source={"type": kind, "id": target_id},
                selection_ref={
                    "kind": "target",
                    "target_ref": {
                        "target_type": kind,
                        "target_id": target_id,
                        "target_path": "",
                    },
                },
            )
        )
    entries.append(
        ContextItem(
            key="prose",
            content="实际选中的正文",
            title="正文",
            source={"type": "writing_draft", "id": draft},
            selection_ref={"kind": "source_range", "source_ref": source_ref},
        )
    )
    entries.append(
        ContextItem(
            key="excluded",
            content="作者排除的秘密",
            source={"type": "core_entity", "id": root},
            selection_state="excluded",
        )
    )
    compiled = CompiledContext(
        sections=[ContextSection(key="selected", tier=Tier.P1, content="", items=entries)]
    )
    confirmed = SimpleNamespace(
        compiled=compiled,
        confirmation=SimpleNamespace(context_fingerprint="fixed"),
        compile_options={},
    )
    original = {
        "scope": "targeted",
        "items": [
            {
                "source_key": f"entity:{root}",
                "target_type": "core_entity",
                "target_id": root,
                "content": "不应重新注入的完整原文与秘密",
            }
        ],
    }
    impact = {
        "scope_hash": "c" * 64,
        "sections": {
            "story": {"items": [{"kind": "story_thread", "id": thread}]},
            "map": {"items": [{"kind": "map_node", "id": map_id}]},
            "prose": {
                "items": [{"kind": "prose_chapter", "id": "1", "source_ref": source_ref}]
            },
        },
    }
    with patch(
        "modules.evidence.facade.prepare_confirmed_ai_action",
        autospec=True,
        return_value=confirmed,
    ):
        frozen = await WorldValidationService()._freeze_semantic_scope(
            db_session,
            project_novel_id,
            original,
            impact,
            confirmation_id=str(uuid.uuid4()),
            domains=["world", "story", "prose", "map"],
        )
    text = "\n".join(item["content"] for item in frozen["semantic_items"])
    assert "秘密" not in text and "完整原文" not in text
    assert all(
        expected in text
        for expected in ("世界摘要", "剧情约束", "空间声明", "实际选中的正文")
    )
    assert frozen["semantic_omissions"] == []
    assert len(frozen["semantic_items"]) == 4
    confirmed.confirmation.context_fingerprint = "changed"
    with pytest.raises(ConflictError):
        WorldValidationService._confirmed_semantic_manifest(frozen, confirmed)


@pytest.mark.asyncio
async def test_story_and_map_sources_open_exact_versions_and_detect_changes(
    db_session, project_novel_id
):
    from modules.story.outline_state.models import OutlineArc, PlotThread, Scene

    nid = uuid.UUID(project_novel_id)
    root = CoreEntity(
        novel_id=nid, entity_type="location", name="潮门", status="canonical"
    )
    db_session.add(root)
    await db_session.flush()
    thread = PlotThread(
        novel_id=nid,
        name="潮门主线",
        thread_type="main",
        summary="守住潮门",
        status="draft",
        related_entity_ids=[str(root.id)],
    )
    arc = OutlineArc(
        novel_id=nid,
        title="第一卷",
        arc_goal="守住港口",
        status="draft",
        related_entity_ids=[str(root.id)],
    )
    scene = Scene(
        novel_id=nid,
        scene_index=0,
        title="潮门故障",
        goal="维修潮门",
        status="draft",
        structure_meta={"related_entity_ids": [str(root.id)]},
    )
    node = MapAtlasNode(
        novel_id=nid,
        semantic_key="tide",
        title="潮门地图",
        level="city",
        status="adopted",
        location_entity_id=root.id,
    )
    db_session.add_all([thread, arc, scene, node])
    await db_session.flush()
    revision = MapAtlasRevision(
        novel_id=nid,
        node_id=node.id,
        status="saved",
        geometry_hash="d" * 64,
        document={
            "features": [
                {
                    "id": "gate",
                    "kind": "location",
                    "label": "潮门",
                    "points": [{"x": 0, "y": 0}],
                    "note": "港口北侧",
                }
            ],
            "constraints": [],
        },
    )
    db_session.add(revision)
    await db_session.flush()
    node.current_revision_id = revision.id
    await db_session.flush()
    service = WorldImpactService()
    preview = await service.preview(
        db_session, project_novel_id, target_type="core_entity", target_id=str(root.id)
    )
    items = {item.kind: item for section in preview.sections for item in section.items}
    assert {"story_thread", "outline_arc", "outline_scene", "map_node"} <= items.keys()
    for kind in ("story_thread", "outline_arc", "outline_scene", "map_node"):
        result = await service.read_source(
            db_session,
            WorldImpactSourceReadRequest(novel_id=project_novel_id, item=items[kind]),
        )
        assert result.text and result.source_hash == items[kind].source_hash
    thread.summary = "新的剧情前提"
    await db_session.flush()
    with pytest.raises(ConflictError):
        await service.read_source(
            db_session,
            WorldImpactSourceReadRequest(
                novel_id=project_novel_id, item=items["story_thread"]
            ),
        )
    changed = await service.preview(
        db_session, project_novel_id, target_type="core_entity", target_id=str(root.id)
    )
    assert preview.scope_hash != changed.scope_hash


@pytest.mark.asyncio
async def test_pinned_prose_does_not_expand_to_the_surrounding_paragraph(
    db_session, project_novel_id
):
    from modules.evidence.compilation.services.context_compiler import ContextCompiler
    from modules.evidence.contracts import CompileOptions

    text = "前缀选中句后缀"
    ref = {
        "draft_id": str(uuid.uuid4()),
        "chapter_index": 1,
        "version_number": 1,
        "content_mode": "canonical",
        "start_offset": 2,
        "end_offset": 5,
        "source_hash": hashlib.sha256(text.encode()).hexdigest(),
        "range_hash": hashlib.sha256("选中句".encode()).hexdigest(),
    }
    with patch(
        "modules.evidence.compilation.novel_evidence.NovelEvidenceService.read",
        autospec=True,
        return_value={
            "text": text,
            "title": "第一章",
            "highlight_start": 2,
            "highlight_end": 5,
            "source_ref": ref,
        },
    ):
        item = await ContextCompiler._load_pinned_item(
            db_session,
            CompileOptions(novel_id=project_novel_id, task="精确引用", scope="world"),
            {"kind": "source_range", "source_ref": ref},
        )
    assert item is not None and "选中句" in item.content
    assert "前缀" not in item.content and "后缀" not in item.content


@pytest.mark.asyncio
async def test_planning_targets_are_not_exposed_to_reader_or_scene_local_context(
    db_session, project_novel_id
):
    from modules.evidence.compilation.novel_evidence import NovelEvidenceService
    from modules.evidence.contracts import VisibilityContextContract
    from shared.target_ref import TargetRef

    for kind in ("story_thread", "outline_arc", "story_outline", "map_node"):
        for visibility in (
            VisibilityContextContract(mode="reader"),
            VisibilityContextContract(mode="character", character_id=str(uuid.uuid4())),
            VisibilityContextContract(mode="author", cutoff_chapter=2),
        ):
            item, warnings = await NovelEvidenceService()._visible_target(
                db_session,
                novel_id=project_novel_id,
                target=TargetRef(
                    target_type=kind, target_id=str(uuid.uuid4()), target_path=""
                ),
                content_mode="canonical",
                visibility=visibility,
            )
            assert item is None and warnings


@pytest.mark.asyncio
async def test_semantic_run_freezes_real_confirmation_and_invalidates_changed_source(
    async_client,
    db_session,
    account_llm_connection,
):
    from modules.world.models.worldbuilding import WorldValidationRun
    from modules.world.schemas import WorldValidationPolicy
    from modules.world.services.worldbuilding.world_validation_engine import stable_hash
    from modules.world.tests.test_world_cocreation_sessions import _create_project

    novel_id = await _create_project(async_client, "实际语义范围冻结")
    entity = CoreEntity(
        novel_id=uuid.UUID(novel_id),
        name="潮门规则",
        entity_type="rule",
        summary="潮门每次耗盐",
        status="canonical",
    )
    db_session.add(entity)
    await db_session.flush()
    context = {
        "novel_id": novel_id,
        "action": "world.validation.semantic",
        "task": "核对潮门",
        "scope": "world",
        "budget_tokens": 12000,
        "pinned_refs": [
            {
                "kind": "target",
                "target_ref": {
                    "target_type": "core_entity",
                    "target_id": str(entity.id),
                    "target_path": "",
                },
            }
        ],
    }
    preview = await async_client.post("/api/evidence/compilation/compile", json=context)
    assert preview.status_code == 200, preview.text
    confirmed = await async_client.post(
        "/api/evidence/compilation/confirm",
        json={
            **context,
            "expected_context_fingerprint": preview.json()["context_fingerprint"],
        },
    )
    assert confirmed.status_code == 201, confirmed.text
    policy = WorldValidationPolicy(
        schema_version="world_validation_policy.v1",
        policy_version="scope-test",
        semantic_enabled=True,
        required_questions=[
            {
                "question_id": "scope",
                "gate": "knowledge",
                "question": "这些资料是否矛盾？",
            }
        ],
    )
    with patch.object(
        WorldValidationService,
        "active_policy",
        autospec=True,
        return_value=(policy, stable_hash(policy.model_dump(mode="json"))),
    ):
        response = await async_client.post(
            "/api/world/bible/validation-runs",
            json={
                "novel_id": novel_id,
                "operation_id": str(uuid.uuid4()),
                "scope": "targeted",
                "target_type": "semantic_gap",
                "root_type": "core_entity",
                "target_id": str(entity.id),
                "context_confirmation_id": confirmed.json()["id"],
            },
        )
        assert response.status_code == 202, response.text
        run = await db_session.get(WorldValidationRun, uuid.UUID(response.json()["id"]))
        assert run.manifest_json["semantic_items"]
        assert run.manifest_json["focused_request"]["max_depth"] == 1
        assert all(
            not item["text"] for item in run.manifest_json["focused_result"]["evidence"]
        )
        # Simulate completion to check read-time freshness without a paid model.
        run.status = "completed"
        run.verdict = "pass"
        run.gate = "pass"
        await db_session.flush()
        entity.summary = "潮门每次耗盐两袋"
        await db_session.flush()
        changed = await async_client.get(
            f"/api/world/bible/validation-runs/{run.id}", params={"novel_id": novel_id}
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["status"] == "stale"
        assert changed.json()["gate"] == "block"
