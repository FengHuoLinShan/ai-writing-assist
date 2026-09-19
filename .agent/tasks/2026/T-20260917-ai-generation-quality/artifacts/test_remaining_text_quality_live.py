"""Real outline, assistant proposal and map text paths over isolated synthetic data."""

import json
import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select

from test_ai_quality_live import measured_provider  # noqa: F401
from infrastructure.tasks.facade import run_task_inline
from modules.account.settings_service import SettingsService
from modules.evidence.facade import confirm_context
from modules.world.tests.test_world_cocreation_sessions import _create_project

pytestmark = [
    pytest.mark.real_llm,
    pytest.mark.skipif(
        os.getenv("RUN_AI_QUALITY_LIVE") != "1" or not os.getenv("DEEPSEEK_API_KEY"),
        reason="explicit paid acceptance and process credential required",
    ),
]


def save(name, result):
    (Path(os.environ["AI_QUALITY_ARTIFACTS"]) / f"{name}.json").write_text(
        json.dumps(result, ensure_ascii=False, default=str, indent=2)
    )


async def test_outline_arithmetic_rejection(async_client, db_session, measured_provider):
    from modules.project.facade import open_project_llm_client
    from modules.story.outline_state.story_outline_generation import (
        StoryOutlineGenerationPlan,
        StoryOutlineGenerationService,
    )
    from modules.story.outline_state.story_outline_schemas import (
        StoryOutlineContent,
        StoryOutlineGenerateRequest,
    )

    await SettingsService().connect_account_llm_provider(
        db_session, "deepseek", os.environ["DEEPSEEK_API_KEY"]
    )
    novel_id = await _create_project(async_client, "总纲账目精确回归")
    fixture = (
        Path(__file__).resolve().parents[2]
        / ".agent/tasks/2026/T-20260917-ai-generation-quality/artifacts/outline-arithmetic-regression.json"
    )
    candidate = StoryOutlineContent.model_validate_json(fixture.read_text())
    plan = StoryOutlineGenerationPlan(
        request=StoryOutlineGenerateRequest(
            novel_id=novel_id,
            author_intent="原创现实主义修船铺债务故事。提供完整主方案，明确高潮选择、结局与代价，账目必须自洽。",
            planned_scale="三万字中篇",
            coverage="开端到结局",
        ),
        context={
            "project": {"title": "原创修船铺"},
            "world_bible_synopsis": None,
            "world_bible_pages": [],
            "core_world_rules": [],
            "selected_characters": [],
            "selected_world_entities": [],
            "current_story_outline": None,
        },
        context_provenance={},
        source_fingerprint="synthetic-arithmetic",
    )
    async with open_project_llm_client(db_session, novel_id) as client:
        audit = await StoryOutlineGenerationService._audit_preview(
            client, plan, candidate
        )
    save("outline-arithmetic", audit.model_dump(mode="json"))
    assert audit.verdict == "revise", audit
    assert any(
        any(term in issue for term in ["二十六", "二十八", "26", "28", "金额", "解押"])
        for issue in audit.violations
    ), audit


async def test_outline_real(async_client, db_session, measured_provider):
    await SettingsService().connect_account_llm_provider(
        db_session, "deepseek", os.environ["DEEPSEEK_API_KEY"]
    )
    novel_id = await _create_project(async_client, "合成总纲质量验收")
    intent = "原创现实主义中篇：姐妹接手母亲留下的修船铺，必须在三十天内决定共同经营还是卖掉偿债。姐姐想留下、妹妹想远行，两人都善意但有盲点。不得用突然遗产、中大奖、贵人无条件资助来解决债务，不得让任何人死亡替代选择。结局明确落在姐妹做出的选择与代价。"
    confirmation = await confirm_context(
        db_session,
        novel_id=novel_id,
        action="outline.story_outline.generate",
        task=intent,
        scope="project",
        budget_tokens=4000,
    )
    response = await async_client.post(
        "/api/outline/story-outline/generate",
        json={
            "novel_id": novel_id,
            "context_confirmation_id": confirmation.id,
            "author_intent": intent,
            "planned_scale": "中篇，约三万字。",
            "coverage": "覆盖开端、升级、危机、高潮选择与结局。",
        },
    )
    assert response.status_code == 201, response.text
    result = await run_task_inline(
        db_session,
        task_id=response.json()["task_id"],
        expected_task_type="story_outline_generate",
    )
    save("outline", result)
    assert result["knowledge_review"]["status"] == "passed", result
    assert result["major_storylines"] and result["macro_movements"]


async def test_assistant_real(async_client, db_session, measured_provider):
    from modules.assistant.models import AssistantRun
    from modules.project.models import ProjectAuthorTask

    await SettingsService().connect_account_llm_provider(
        db_session, "deepseek", os.environ["DEEPSEEK_API_KEY"]
    )
    novel_id = await _create_project(async_client, "合成助手质量验收")
    response = await async_client.post(
        "/api/assistant/sessions", json={"novel_id": novel_id}
    )
    assert response.status_code == 201, response.text
    session_id = response.json()["id"]
    operation = str(uuid.uuid4())
    submitted = await async_client.post(
        f"/api/assistant/sessions/{session_id}/turns",
        json={
            "novel_id": novel_id,
            "operation_id": operation,
            "allow_web": False,
            "message": "请拟一条待办，标题就是‘核对双胞胎人物的出生年份’。只生成待我确认的添加提案，不要直接添加，也不要假定作品已经有双胞胎人物。无需联网。",
        },
    )
    assert submitted.status_code == 202, submitted.text
    db_session.task_checkpoint_enabled = True
    terminal = await run_task_inline(
        db_session, task_id=operation, expected_task_type="assistant_turn"
    )
    run = await db_session.get(AssistantRun, uuid.UUID(operation))
    count = await db_session.scalar(
        select(func.count(ProjectAuthorTask.id)).where(
            ProjectAuthorTask.novel_id == uuid.UUID(novel_id)
        )
    )
    save(
        "assistant",
        {"terminal": terminal, "result": run.result_json, "persisted_tasks": count},
    )
    assert terminal["status"] == "waiting_approval", terminal
    assert count == 0
    assert run.result_json.get("actions"), run.result_json


async def test_map_text_real(async_client, db_session, measured_provider):
    from modules.world.map_atlas_models import MapAtlasRevision
    from modules.world.map_structure_schemas import MapGenerateRequest, MapNodeCreate
    from modules.world.map_structure_service import (
        MAP_ACTION,
        MAP_TASK,
        MapStructureService,
    )
    from modules.world.map_structure_workflow import enqueue_structure
    from modules.world.models import CoreEntity

    await SettingsService().connect_account_llm_provider(
        db_session, "deepseek", os.environ["DEEPSEEK_API_KEY"]
    )
    novel_id = await _create_project(async_client, "合成地图文本质量验收")
    entities = [
        CoreEntity(
            novel_id=uuid.UUID(novel_id),
            name=name,
            entity_type="location",
            status="canonical",
            reveal_level="revealed",
            public_info=detail,
            summary=detail,
        )
        for name, detail in [
            ("石港", "石港是南部港口。"),
            ("松城", "松城位于石港以北，两地的距离尚未确定。"),
        ]
    ]
    db_session.add_all(entities)
    await db_session.flush()
    ids = [str(entity.id) for entity in entities]
    node = await MapStructureService().create_node(
        db_session, novel_id, MapNodeCreate(title="双城区域")
    )
    confirmation = await confirm_context(
        db_session,
        novel_id=novel_id,
        action=MAP_ACTION,
        task="整理石港和松城的空间关系，不补造距离。",
        scope="world",
        location_ids=ids,
        entity_ids=ids,
        reveal_mode="author_full",
        budget_tokens=8000,
    )
    submitted = await enqueue_structure(
        db_session,
        novel_id,
        node["id"],
        MapGenerateRequest(
            operation_id=uuid.uuid4(),
            base_revision_id=node["current_revision_id"],
            context_confirmation_id=confirmation.id,
            location_ids=ids,
        ),
    )
    db_session.task_checkpoint_enabled = True
    result = await run_task_inline(
        db_session, task_id=submitted["task_id"], expected_task_type=MAP_TASK
    )
    revision = await db_session.get(MapAtlasRevision, uuid.UUID(result["revision_id"]))
    save(
        "map-text",
        {
            "result": result,
            "document": revision.document,
            "problems": revision.problems,
            "status": revision.status,
        },
    )
    assert revision.status == "candidate"
    relations = revision.document["constraints"]
    assert any(
        item["relation"] == "north"
        and item["subject"] == f"loc:{ids[1]}"
        and item["target"] == f"loc:{ids[0]}"
        for item in relations
    ), relations
    assert all(item.get("sources") for item in relations)
