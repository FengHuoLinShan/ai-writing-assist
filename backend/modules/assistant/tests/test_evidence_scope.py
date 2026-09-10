from types import SimpleNamespace
from uuid import uuid4

import pytest

from infrastructure.llm.agent_runtime import AgentRunBudget
from modules.assistant.evidence_tools import AssistantToolContext
from modules.assistant.schemas import WorkContext


@pytest.mark.asyncio
async def test_author_tasks_reads_future_inbox_and_keeps_scope(
    db_session, test_project_id
):
    from datetime import date

    from modules.account.facade import current_account_id
    from modules.assistant.evidence_tools import author_tasks
    from modules.project.author_task_service import AuthorTaskService
    from modules.project.schemas import AuthorTaskCreateRequest

    tasks = AuthorTaskService()
    await tasks.create_task(
        db_session,
        test_project_id,
        AuthorTaskCreateRequest(title="明天核对桥梁", due_date=date(2026, 9, 11)),
    )
    await tasks.create_task(
        db_session, test_project_id, AuthorTaskCreateRequest(title="无日期待办")
    )
    ctx = AssistantToolContext(
        db_session,
        test_project_id,
        str(current_account_id()),
        WorkContext(),
        None,
        AgentRunBudget(),
        None,
    )
    found = await author_tasks(SimpleNamespace(deps=ctx), "2026-09-10", "later")
    assert [item["title"] for item in found["inspection"]["item"]["items"]] == [
        "明天核对桥梁"
    ]
    found = await author_tasks(SimpleNamespace(deps=ctx), "2026-09-10", "inbox")
    assert [item["title"] for item in found["inspection"]["item"]["items"]] == [
        "无日期待办"
    ]
    ctx.work = WorkContext(excluded_targets=[str(uuid4())])
    assert "omission" in await author_tasks(SimpleNamespace(deps=ctx), "2026-09-10")


def test_public_review_receipt_keeps_domain_identity_coverage_and_omissions():
    from modules.assistant.service import display_sources

    reference = {
        "type": "world_validation",
        "id": str(uuid4()),
        "task_id": str(uuid4()),
        "target": {"type": "core_entity", "id": str(uuid4())},
    }
    result = {
        "status": "completed",
        "coverage_ledger": [{"status": "checked"}],
        "omissions": ["没有覆盖隐含假设"],
    }
    shown = display_sources(
        {
            "read": {
                "domain_reference": reference,
                "review_result": result,
                "source_guard": {"private": "not-public"},
            }
        },
        ["read"],
    )[0]
    assert shown["domain_reference"] == reference
    assert shown["review_result"] == result
    assert "source_guard" not in shown


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind",
    [
        "world.edit_entity",
        "world.add_alias",
        "story.save_card",
        "story.save_script",
        "story.create_arc",
        "writing.revise",
    ],
)
async def test_domain_previews_refuse_excluded_targets_before_reading(kind):
    from core.container import get
    from core.errors import ConflictError
    from modules.assistant.contracts import AssistantOperationContext

    target = str(uuid4())
    arguments = {
        "world.edit_entity": {"entity_id": target, "changes": {"name": "提案"}},
        "world.add_alias": {"entity_id": target, "alias": "别称"},
        "story.save_card": {
            "scene_id": target,
            "character_id": str(uuid4()),
            "content": {"personality": "谨慎"},
        },
        "story.save_script": {
            "scene_id": target,
            "file_key": "opening",
            "title": "开场",
            "content": "文字",
        },
        "story.create_arc": {"title": "篇章", "related_thread_ids": [target]},
        "writing.revise": {
            "draft_id": target,
            "source_hash": "a" * 64,
            "replacements": [
                {"start": 0, "end": 1, "original": "旧", "replacement": "新"}
            ],
        },
    }[kind]
    context = AssistantOperationContext(
        str(uuid4()), str(uuid4()), WorkContext(excluded_targets=[target])
    )
    operation = get("assistant.operations")[kind]
    with pytest.raises(ConflictError, match="排除资料"):
        await operation.prepare(
            object(),
            str(uuid4()),
            operation.schema.model_validate(arguments),
            context=context,
        )


def test_discussion_history_preserves_scope_and_never_restores_broader_material():
    from modules.assistant.service import history_visible

    current = WorkContext(chapter_index=3, excluded_targets=["core_entity:hidden"])
    assert history_visible(current, current.model_dump(), None)
    assert not history_visible(current, WorkContext(scope="project").model_dump(), None)
    assert not history_visible(current, WorkContext(chapter_index=4).model_dump(), None)
    assert not history_visible(current, WorkContext(chapter_index=3).model_dump(), None)
    assert not history_visible(current, None, None)
    cid = uuid4()
    confirmed = WorkContext(
        context_confirmation_id=cid, context_confirmation_action="writing.generate"
    )
    assert history_visible(confirmed, None, cid)
    assert not history_visible(confirmed, None, uuid4())
    assert history_visible(WorkContext(page="world"), None, None)


@pytest.mark.asyncio
async def test_session_checkpoint_is_author_only_and_stays_a_design_candidate(
    db_session, test_project_id
):
    from uuid import UUID

    from core.errors import NotFoundError
    from modules.account.facade import current_account_id
    from modules.assistant.evidence_tools import session_context
    from modules.assistant.models import AssistantSession
    from modules.evidence.contracts import VisibilityContextContract
    from modules.evidence.facade import inspect_novel_target
    from modules.world.models.worldbuilding import CreationSuggestion

    checkpoint = CreationSuggestion(
        novel_id=UUID(test_project_id),
        source_module="world",
        review_group="world_adoption",
        target_type="world_design_checkpoint",
        payload_json={
            "schema_version": "world_design_checkpoint.v1",
            "principle": "潮门必须维护",
        },
        evidence_refs_json=[],
        risk_level="low",
        status="pending",
    )
    db_session.add(checkpoint)
    await db_session.flush()
    session = AssistantSession(
        novel_id=UUID(test_project_id),
        title="潮门世界",
        source_kind="project",
        current_checkpoint_id=checkpoint.id,
    )
    db_session.add(session)
    await db_session.flush()
    ctx = AssistantToolContext(
        db_session,
        test_project_id,
        str(current_account_id()),
        WorkContext(page="world"),
        None,
        AgentRunBudget(),
        None,
        session_id=str(session.id),
    )
    result = await session_context(SimpleNamespace(deps=ctx))
    material = result["checkpoint"]["inspection"]["item"]
    assert material["status"] == "pending" and "不是正式" in material["authority"]
    await ctx.revalidate(list(ctx.evidence_refs))
    target = {"target_type": "world_checkpoint", "target_id": str(checkpoint.id)}
    denied = await inspect_novel_target(
        db_session,
        novel_id=test_project_id,
        target_ref=target,
        content_mode="working",
        visibility=VisibilityContextContract(mode="reader", cutoff_chapter=1),
    )
    assert not denied["visible"]
    with pytest.raises(NotFoundError):
        await inspect_novel_target(
            db_session,
            novel_id=str(uuid4()),
            target_ref=target,
            content_mode="working",
            visibility=VisibilityContextContract(mode="author"),
        )


@pytest.mark.asyncio
async def test_current_work_read_uses_evidence_and_blocks_prefixed_exclusions(
    db_session, test_project_id
):
    from modules.account.facade import current_account_id
    from modules.assistant.evidence_tools import inspect_current
    from modules.writing.facade import create_draft_only

    draft = await create_draft_only(
        db_session, test_project_id, 1, "第一章", "城门已经关闭。"
    )
    context = AssistantToolContext(
        db_session,
        test_project_id,
        str(current_account_id()),
        WorkContext(draft_id=draft.id, chapter_index=1),
        None,
        AgentRunBudget(),
        None,
    )
    response = await inspect_current(SimpleNamespace(deps=context))
    assert response["source_ref"]["draft_id"] == draft.id
    assert "城门已经关闭" in str(response)
    context.work = WorkContext(
        draft_id=draft.id, excluded_targets=[f"writing_draft:{draft.id}"]
    )
    context.evidence_refs = {}
    response = await inspect_current(SimpleNamespace(deps=context))
    assert "城门已经关闭" not in str(response)
    assert not context.evidence_refs


@pytest.mark.asyncio
async def test_draft_and_map_inspection_is_author_only(
    db_session, async_client, test_project_id
):
    from modules.evidence.contracts import VisibilityContextContract
    from modules.evidence.facade import inspect_novel_target
    from modules.world.map_structure_schemas import MapNodeCreate
    from modules.world.map_structure_service import MapStructureService

    draft = await async_client.post(
        "/api/world/bible/drafts",
        json={
            "novel_id": test_project_id,
            "title": "隐藏资料",
            "free_text": "秘密候选",
            "page_type": "background",
        },
    )
    node = await MapStructureService().create_node(
        db_session, test_project_id, MapNodeCreate(title="待完善地图")
    )
    for kind, target in [
        ("world_bible_page_draft", draft.json()["id"]),
        ("map_atlas_node", node["id"]),
    ]:
        ref = {"target_type": kind, "target_id": str(target)}
        view = await inspect_novel_target(
            db_session,
            novel_id=test_project_id,
            target_ref=ref,
            content_mode="working",
            visibility=VisibilityContextContract(mode="author"),
        )
        assert view["visible"]
        hidden = await inspect_novel_target(
            db_session,
            novel_id=test_project_id,
            target_ref=ref,
            content_mode="working",
            visibility=VisibilityContextContract(mode="reader", cutoff_chapter=1),
        )
        assert not hidden["visible"] and hidden["item"] is None


def test_canonical_target_refs_obey_author_exclusions_before_model_access():
    excluded = str(uuid4())
    for exclusion in [excluded, f"world_entity:{excluded}"]:
        context = AssistantToolContext(
            None,
            str(uuid4()),
            str(uuid4()),
            WorkContext(excluded_targets=[exclusion]),
            None,
            AgentRunBudget(),
            None,
        )
        assert (
            context.remember(
                {
                    "target_ref": {"target_type": "world_entity", "target_id": excluded},
                    "snippet": "excluded material",
                }
            )
            is None
        )
        assert context.evidence_refs == {}
