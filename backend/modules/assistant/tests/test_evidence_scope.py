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

    focus_entity_id = str(uuid4())
    focused_author_turn = WorkContext(
        page="world",
        target={"target_type": "world_entity", "target_id": focus_entity_id},
        focus_ref={
            "kind": "entity",
            "entity_id": focus_entity_id,
            "updated_at": "2026-10-18T08:00:00Z",
        },
    )
    roleplay = WorkContext(task_hint="roleplay")
    assert not history_visible(
        roleplay, focused_author_turn.model_dump(mode="json"), None
    )
    assert not history_visible(roleplay, WorkContext().model_dump(mode="json"), None)
    assert history_visible(roleplay, roleplay.model_dump(mode="json"), None)
    assert not history_visible(roleplay, None, None)
    assert not history_visible(roleplay, {"scope": "invalid"}, None)
    roleplay.context_confirmation_id = cid
    assert not history_visible(roleplay, focused_author_turn.model_dump(mode="json"), cid)


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
async def test_world_focus_is_materialized_as_exact_author_evidence(
    db_session, test_project_id
):
    from modules.account.facade import current_account_id
    from modules.assistant.evidence_tools import inspect_current
    from modules.world.facade import create_world_object_dossier_entry
    from modules.world.schemas.dossier import DossierEntryCreate
    from tests.utils import _create_entity

    entity = await _create_entity(db_session, test_project_id, "character", "沈砚")
    selected = await create_world_object_dossier_entry(
        db_session,
        test_project_id,
        str(entity.id),
        DossierEntryCreate(
            facing={"kind": "core", "key": "identity_position"},
            content="他把旧钥匙交给了船医。",
        ),
    )
    await create_world_object_dossier_entry(
        db_session,
        test_project_id,
        str(entity.id),
        DossierEntryCreate(
            facing={"kind": "core", "key": "appearance"},
            content="不应混入的无关档案。",
        ),
    )
    focus_ref = {
        "kind": "dossier_entry",
        "entity_id": str(entity.id),
        "entry_group_id": str(selected.entry_group_id),
        "revision_id": str(selected.id),
    }
    context = AssistantToolContext(
        db_session,
        test_project_id,
        str(current_account_id()),
        WorkContext(
            page="world",
            target={"target_type": "world_entity", "target_id": str(entity.id)},
            focus_ref=focus_ref,
            focus_label="UI-only label",
        ),
        None,
        AgentRunBudget(),
        None,
    )

    result = await inspect_current(SimpleNamespace(deps=context))
    assert result["world_focus"]["source_kind"] == "world_focus"
    assert result["world_focus"]["kind"] == "dossier_entry"
    assert result["world_focus"]["content"]["content"] == "他把旧钥匙交给了船医。"
    assert "不应混入" not in str(result)
    assert "UI-only label" not in str(result)
    assert str(selected.id) not in str(result)
    assert "作者视角资料" in result["world_focus"]["warning"]
    assert "_world_focus" not in result and "_target_ref" not in result
    from modules.assistant.service import display_sources

    source = display_sources(context.evidence_refs, [result["evidence_id"]])[0]
    assert source["target_ref"] == {
        "target_type": "world_entity",
        "target_id": str(entity.id),
    }
    assert "他把旧钥匙交给了船医。" in source["snippet"]
    await context.revalidate([result["evidence_id"]])

    excluded = AssistantToolContext(
        db_session,
        test_project_id,
        str(current_account_id()),
        WorkContext(
            page="world",
            target={"target_type": "world_entity", "target_id": str(entity.id)},
            focus_ref=focus_ref,
            excluded_targets=[str(selected.id)],
        ),
        None,
        AgentRunBudget(),
        None,
    )
    excluded_result = await inspect_current(SimpleNamespace(deps=excluded))
    assert "未读取其内容" in excluded_result["omission"]
    assert not excluded.evidence_refs


@pytest.mark.asyncio
async def test_relation_focus_revalidation_detects_endpoint_material_changes(
    db_session, test_project_id
):
    from core.errors import ConflictError
    from modules.account.facade import current_account_id
    from modules.assistant.evidence_tools import inspect_current
    from modules.world.facade import upsert_relation
    from tests.utils import _create_entity

    source = await _create_entity(db_session, test_project_id, "character", "沈砚")
    target = await _create_entity(db_session, test_project_id, "faction", "潮门守卫")
    relation = await upsert_relation(
        db_session,
        test_project_id,
        str(source.id),
        str(target.id),
        "member_of",
        description="旧版本关系描述。",
        relation_kind="social",
    )
    relation.strength = 0.0
    await db_session.flush()
    context = AssistantToolContext(
        db_session,
        test_project_id,
        str(current_account_id()),
        WorkContext(
            page="world",
            target={"target_type": "world_entity", "target_id": str(source.id)},
            focus_ref={
                "kind": "relation",
                "entity_id": str(source.id),
                "relation_id": str(relation.id),
                "updated_at": relation.updated_at.isoformat(),
            },
        ),
        None,
        AgentRunBudget(),
        None,
    )
    result = await inspect_current(SimpleNamespace(deps=context))
    assert result["world_focus"]["content"]["target_name"] == "潮门守卫"
    from modules.assistant.service import display_sources

    citation = display_sources(context.evidence_refs, [result["evidence_id"]])[0]
    for expected in (
        "作者视角资料；不证明任何角色已知",
        "关系：成员",
        "类别：社会关系",
        "关系强度：0",
        "状态：已采用",
        "生效范围：未限定起止",
        "旧版本关系描述。",
    ):
        assert expected in citation["snippet"]
    assert "member_of" not in citation["snippet"]
    await context.revalidate([result["evidence_id"]])

    target.name = "新改名的潮门守卫"
    await db_session.flush()
    with pytest.raises(ConflictError, match="世界焦点已变化"):
        await context.revalidate([result["evidence_id"]])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("validity", "expected"),
    [
        ({"start": {"kind": "scene", "id": "private-scene"}}, "从指定场景起"),
        ({"end": {"kind": "chapter", "id": "private-chapter"}}, "至指定章节止"),
        (
            {
                "start": {"kind": "chapter", "id": "private-chapter"},
                "end": {"kind": "scene", "id": "private-scene"},
            },
            "从指定章节起，至指定场景止",
        ),
    ],
)
async def test_world_relation_citation_keeps_validity_and_warning(validity, expected):
    from core.container import container_scope
    from core.service_keys import WORLD_READ_ASSISTANT_FOCUS
    from modules.evidence.facade import read_assistant_world_focus

    async def read_focus(db, novel_id, focus_ref):
        return {
            "kind": "relation",
            "title": "沈砚与潮门守卫的关系",
            "content": {
                "relation_type_label": "成员",
                "relation_kind": "social",
                "validity": validity,
                "quote": "长依据" * 1500,
            },
        }

    with container_scope({WORLD_READ_ASSISTANT_FOCUS: read_focus}):
        evidence = await read_assistant_world_focus(
            None, novel_id=str(uuid4()), focus_ref={}
        )
    from modules.assistant.service import display_sources

    citation = display_sources({"focus": evidence}, ["focus"])[0]
    assert expected in citation["snippet"]
    assert "不证明任何角色已知" in citation["snippet"]
    assert "不代表当前场景仍然有效" in citation["snippet"]
    assert "private-" not in citation["snippet"]
    assert citation["excerpted"]


@pytest.mark.asyncio
async def test_roleplay_and_confirmed_context_do_not_expand_world_focus(
    db_session, test_project_id, monkeypatch
):
    import modules.evidence.facade as evidence_facade
    from modules.account.facade import current_account_id
    from modules.assistant.evidence_tools import inspect_current

    def unexpected_read(*_args, **_kwargs):
        pytest.fail("author world focus must not be read outside author scope")

    monkeypatch.setattr(evidence_facade, "read_assistant_world_focus", unexpected_read)
    focus_ref = {
        "kind": "entity",
        "entity_id": str(uuid4()),
        "updated_at": "2026-10-18T00:00:00+00:00",
    }
    roleplay = AssistantToolContext(
        db_session,
        test_project_id,
        str(current_account_id()),
        WorkContext(
            page="world",
            target={"target_type": "world_entity", "target_id": focus_ref["entity_id"]},
            focus_ref=focus_ref,
            task_hint="roleplay",
        ),
        None,
        AgentRunBudget(),
        None,
    )
    result = await inspect_current(SimpleNamespace(deps=roleplay))
    assert "不能证明角色已知" in result["omission"]
    assert not roleplay.evidence_refs

    confirmed = AssistantToolContext(
        db_session,
        test_project_id,
        str(current_account_id()),
        WorkContext(
            page="world",
            target={"target_type": "world_entity", "target_id": focus_ref["entity_id"]},
            focus_ref=focus_ref,
        ),
        None,
        AgentRunBudget(),
        None,
    )
    confirmed.fixed_context = {"title": "已确认范围", "text": "只允许此确认资料。"}
    result = await inspect_current(SimpleNamespace(deps=confirmed))
    assert "未额外读取" in result["omission"]
    assert result["confirmed_context"]["text"] == "只允许此确认资料。"


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


async def test_selected_objects_are_paginated_versioned_and_never_expand_scope(
    db_session, test_project_id, project_factory
):
    from core.errors import ConflictError, NotFoundError
    from modules.account.facade import current_account_id
    from modules.assistant.contracts import AssistantOperationContext
    from modules.assistant.evidence_tools import inspect_current
    from modules.assistant.operation_scope import require_operation_targets
    from modules.assistant.service import _validate_context_focus
    from tests.utils import _create_entity

    entities = [
        await _create_entity(db_session, test_project_id, "character", f"对象{i}")
        for i in range(7)
    ]
    refs = [
        {"kind": "entity", "entity_id": str(item.id), "updated_at": item.updated_at}
        for item in entities[:6]
    ]
    work = WorkContext(
        page="world", selected_entities=refs, excluded_targets=[str(entities[1].id)]
    )
    await _validate_context_focus(db_session, test_project_id, work)
    deps = AssistantToolContext(
        db_session,
        test_project_id,
        str(current_account_id()),
        work,
        None,
        AgentRunBudget(),
        None,
    )
    first = await inspect_current(SimpleNamespace(deps=deps))
    assert len(first["objects"]) == 4
    assert (
        first["selected_count"] == 6
        and first["excluded_count"] == 1
        and first["next_offset"] == 5
    )
    assert (
        "对象1" not in str(first)
        and "对象5" not in str(first)
        and "对象6" not in str(first)
    )
    second = await inspect_current(SimpleNamespace(deps=deps), offset=5)
    assert len(second["objects"]) == 1 and second["next_offset"] is None
    assert (
        deps.remember(
            {
                "target_ref": {
                    "target_type": "world_entity",
                    "target_id": str(entities[6].id),
                },
                "snippet": "未选资料",
            }
        )
        is None
    )
    assert deps.remember({"snippet": "缺少可证明目标的汇总"}) is None
    context = AssistantOperationContext(str(uuid4()), str(current_account_id()), work)
    await require_operation_targets(
        db_session, test_project_id, context, [("core_entity", str(entities[0].id))]
    )
    with pytest.raises(ConflictError, match="超出"):
        await require_operation_targets(
            db_session, test_project_id, context, [("core_entity", str(entities[6].id))]
        )
    with pytest.raises(ConflictError, match="超出"):
        await require_operation_targets(
            db_session, test_project_id, context, [], aggregate=True
        )
    other = str(await project_factory.create_project())
    with pytest.raises(NotFoundError):
        await _validate_context_focus(db_session, other, work)
    from datetime import timedelta

    entities[0].summary = "已变化"
    entities[0].updated_at = entities[0].updated_at + timedelta(seconds=1)
    await db_session.flush()
    with pytest.raises(ConflictError):
        await _validate_context_focus(db_session, test_project_id, work)


def test_selected_object_contract_rejects_mixed_duplicate_and_roleplay_contexts():
    from datetime import UTC, datetime

    from pydantic import ValidationError

    ref = {"kind": "entity", "entity_id": uuid4(), "updated_at": datetime.now(UTC)}
    for extra in (
        {"page": "writing"},
        {"target": {"target_type": "world_entity", "target_id": str(ref["entity_id"])}},
        {"task_hint": "roleplay"},
        {"selection": "另一焦点"},
    ):
        with pytest.raises(ValidationError):
            WorkContext.model_validate(
                {"page": "world", "selected_entities": [ref], **extra}
            )
    with pytest.raises(ValidationError):
        WorkContext(page="world", selected_entities=[ref, ref])


def test_selected_objects_history_does_not_expand_even_with_same_confirmation():
    from datetime import UTC, datetime

    from modules.assistant.service import history_visible

    confirmation = uuid4()
    work = WorkContext(
        page="world",
        selected_entities=[
            {"kind": "entity", "entity_id": uuid4(), "updated_at": datetime.now(UTC)}
        ],
        context_confirmation_id=confirmation,
        context_confirmation_action="world.review",
    )
    assert history_visible(work, work.model_dump(mode="json"), confirmation)
    assert not history_visible(
        work, WorkContext(page="world").model_dump(mode="json"), confirmation
    )
    changed = work.model_copy(update={"selected_entities": None})
    assert not history_visible(changed, work.model_dump(mode="json"), confirmation)
