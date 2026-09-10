import uuid

import pytest
from pydantic import BaseModel
from sqlalchemy import func, select

from core.container import container_scope
from core.errors import ConflictError
from modules.account.facade import current_account_id
from modules.assistant.contracts import AssistantOperation, AssistantOperationContext
from modules.assistant.evidence_tools import fingerprint
from modules.assistant.models import AssistantActionBatch, AssistantRun
from modules.assistant.operations import decide_batch, prepare_actions
from modules.assistant.schemas import BatchDecision, ProposedAction, WorkContext
from modules.project.models import ProjectAuthorTask


@pytest.mark.asyncio
async def test_author_task_update_uses_existing_version_guard(
    db_session, test_project_id
):
    from modules.project.assistant_tools import OPERATIONS, UpdateAuthorTask
    from modules.project.author_task_service import AuthorTaskService
    from modules.project.schemas import AuthorTaskCreateRequest

    task = await AuthorTaskService().create_task(
        db_session, test_project_id, AuthorTaskCreateRequest(title="核对人物年龄")
    )
    args = UpdateAuthorTask(task_id=task.id, changes={"status": "completed"})
    operation = OPERATIONS["project.update_task"]
    preview = await operation.prepare(db_session, test_project_id, args)
    row = await db_session.get(ProjectAuthorTask, uuid.UUID(task.id))
    row.title = "另一处更新的任务"
    await db_session.flush()
    with pytest.raises(ConflictError):
        await operation.apply(db_session, test_project_id, args, preview)
    preview = await operation.prepare(db_session, test_project_id, args)
    await operation.apply(db_session, test_project_id, args, preview)
    await db_session.refresh(row)
    assert row.status == "completed" and row.title == "另一处更新的任务"


@pytest.mark.asyncio
@pytest.mark.parametrize("external_change", [False, True])
async def test_partial_retry_revalidates_own_world_write_postcondition(
    db_session, test_project_id, external_change
):
    from infrastructure.llm.agent_runtime import AgentRunBudget
    from modules.assistant.evidence_tools import AssistantToolContext
    from modules.evidence.facade import inspect_novel_target
    from modules.story.tests.test_story_service import _character
    from modules.world.assistant_tools import OPERATIONS, EditEntity
    from modules.world.schemas import CoreEntityUpdate
    from modules.world.services.core.entity_service import WorldEntityService

    db, nid = db_session, test_project_id
    entity_id = str(await _character(db, nid))
    owner = str(current_account_id())
    ctx = AssistantToolContext(
        db, nid, owner, WorkContext(), None, AgentRunBudget(), None
    )
    target = {"target_type": "core_entity", "target_id": entity_id}
    ref = {
        "target_ref": target,
        "inspection": await inspect_novel_target(
            db,
            novel_id=nid,
            target_ref=target,
            visibility=ctx.visibility,
            content_mode="working",
        ),
    }
    run = AssistantRun(
        novel_id=uuid.UUID(nid),
        owner_id=uuid.UUID(owner),
        request_hash="a" * 64,
        checkpoint_json={"evidence_refs": {fingerprint(ref): ref}},
    )
    db.add(run)
    await db.flush()
    calls, failing = [], True

    class Args(BaseModel):
        title: str

    async def preview(db, novel_id, args, *, context):
        return {"title": args.title, "after": args.title}

    async def apply(db, novel_id, args, snapshot, *, context):
        calls.append(args.title)
        if failing:
            raise ConflictError("暂时失败")
        return {"label": "已完成"}

    with container_scope(
        {
            "assistant.operations": {
                **OPERATIONS,
                "test.todo": AssistantOperation("待办", Args, preview, apply),
            }
        }
    ):
        actions = await prepare_actions(
            db,
            nid,
            [
                ProposedAction(
                    key="edit",
                    capability="world.edit_entity",
                    title="改名",
                    arguments=EditEntity(
                        entity_id=entity_id, changes={"name": "新名字"}
                    ).model_dump(mode="json"),
                ),
                ProposedAction(
                    key="todo",
                    capability="test.todo",
                    title="跟进",
                    arguments={"title": "跟进"},
                ),
            ],
            context=AssistantOperationContext(str(run.id), owner, WorkContext()),
        )
        batch = AssistantActionBatch(
            novel_id=run.novel_id,
            run_id=run.id,
            actions_json=actions,
            fingerprint=fingerprint(actions),
        )
        db.add(batch)
        await db.flush()
        decision = BatchDecision(
            novel_id=nid,
            fingerprint=batch.fingerprint,
            selected=["edit", "todo"],
            confirmed=True,
        )
        assert (await decide_batch(db, str(batch.id), decision, owner))[
            "status"
        ] == "partial"
        assert (
            await WorldEntityService().get(db, entity_id, novel_id=nid)
        ).name == "新名字"
        await db.commit()
        if external_change:
            await WorldEntityService().update(
                db, entity_id, CoreEntityUpdate(name="后来外部修改"), novel_id=nid
            )
        failing = False
        retry = decision.model_copy(update={"retry_operation_id": uuid.uuid4()})
        if external_change:
            with pytest.raises(ConflictError, match="参考资料已变化"):
                await decide_batch(db, str(batch.id), retry, owner)
            assert calls == ["跟进"]
        else:
            assert (await decide_batch(db, str(batch.id), retry, owner))[
                "status"
            ] == "completed"
            assert calls == ["跟进", "跟进"]
        # Original citations remain historical; only confirmation has postconditions.
        assert run.checkpoint_json["evidence_refs"][fingerprint(ref)] == ref


@pytest.mark.asyncio
async def test_partial_batch_retry_preserves_success_and_rejects_replay(
    db_session, test_project_id
):
    db, nid = db_session, test_project_id
    owner_id = str(current_account_id())
    calls, failing = [], True

    class Args(BaseModel):
        name: str

    async def preview(db, novel_id, args, *, context):
        assert context.owner_id == owner_id
        return {"title": args.name, "target_key": args.name, "after": args.name}

    async def apply(db, novel_id, args, snapshot, *, context):
        calls.append(args.name)
        if args.name == "second" and failing:
            raise ConflictError("synthetic dependency unavailable")
        db.add(ProjectAuthorTask(novel_id=uuid.UUID(novel_id), title=args.name))
        return {"label": args.name}

    run = AssistantRun(
        novel_id=uuid.UUID(nid),
        owner_id=uuid.UUID(owner_id),
        request_hash="a" * 64,
        status="waiting_approval",
    )
    db.add(run)
    await db.flush()
    with container_scope(
        {
            "assistant.operations": {
                "project.test_write": AssistantOperation("test", Args, preview, apply)
            }
        }
    ):
        actions = await prepare_actions(
            db,
            nid,
            [
                ProposedAction(
                    key=name,
                    capability="project.test_write",
                    title=name,
                    arguments={"name": name},
                    depends_on=["second"] if name == "third" else [],
                )
                for name in ["first", "second", "third"]
            ],
            context=AssistantOperationContext(str(run.id), owner_id, WorkContext()),
        )
        batch = AssistantActionBatch(
            novel_id=run.novel_id,
            run_id=run.id,
            actions_json=actions,
            fingerprint=fingerprint(actions),
        )
        db.add(batch)
        await db.flush()
        decision = BatchDecision(
            novel_id=nid,
            fingerprint=batch.fingerprint,
            selected=["first", "second", "third"],
            confirmed=True,
        )
        result = await decide_batch(db, str(batch.id), decision, owner_id)
        assert [item["status"] for item in result["results"]] == [
            "completed",
            "failed",
            "blocked",
        ]
        failing = False
        await decide_batch(db, str(batch.id), decision, owner_id)
        assert calls == ["first", "second"]
        retry = decision.model_copy(update={"retry_operation_id": uuid.uuid4()})
        assert (await decide_batch(db, str(batch.id), retry, owner_id))[
            "status"
        ] == "completed"
        await decide_batch(db, str(batch.id), retry, owner_id)
        assert calls == ["first", "second", "second", "third"]
        assert await db.scalar(select(func.count()).select_from(ProjectAuthorTask)) == 3


@pytest.mark.asyncio
async def test_world_review_uses_concrete_context_and_rejects_excluded_root(
    db_session, async_client, test_project_id, account_llm_connection
):
    from modules.world.assistant_review_tools import ReviewWorld, _prepare, _submit

    response = await async_client.post(
        "/api/world/bible/drafts",
        json={
            "novel_id": test_project_id,
            "title": "贸易规则",
            "page_type": "background",
            "free_text": "城门每晚关闭。",
        },
    )
    assert response.status_code == 201
    root_id = response.json()["id"]
    args = ReviewWorld(root_type="world_bible_page_draft", root_id=root_id)
    context = AssistantOperationContext(
        str(uuid.uuid4()), str(current_account_id()), WorkContext(scope="project")
    )
    preview = await _prepare(db_session, test_project_id, args, context=context)
    assert len(preview["context_fingerprint"]) == 64
    submitted = await _submit(db_session, test_project_id, args, context=context)
    assert submitted["task_id"]
    from infrastructure.tasks.models import AsyncTask
    from modules.evidence.facade import prepare_confirmed_ai_action
    from modules.world.services.worldbuilding.world_validation_service import (
        WorldValidationService,
    )

    validation = WorldValidationService()
    run = await validation._get_model(db_session, test_project_id, submitted["run_id"])
    queued = await db_session.get(AsyncTask, uuid.UUID(submitted["task_id"]))
    confirmed = await prepare_confirmed_ai_action(
        db_session,
        novel_id=test_project_id,
        action="world.validation.semantic",
        confirmation_id=queued.meta["context_confirmation_id"],
    )
    semantic = validation._confirmed_semantic_manifest(run.manifest_json, confirmed)
    assert any(item["target_id"] == root_id for item in semantic["items"])
    assert run.scope_json["purpose"] == "assistant_advisory"
    assert (await validation._policy_for_run(db_session, run)).semantic_enabled
    assert await validation.active_policy(db_session, test_project_id) is None
    assert await validation._matches_frozen_inputs(db_session, run) is None
    excluded = AssistantOperationContext(
        context.run_id,
        context.owner_id,
        WorkContext(scope="project", excluded_targets=[root_id]),
    )
    with pytest.raises(ConflictError):
        await _prepare(db_session, test_project_id, args, context=excluded)
    from modules.assistant import proactive
    from modules.world.assistant_review_tools import review_findings
    from modules.world.schemas import WorldValidationFinding

    source = next(
        item for item in run.manifest_json["items"] if item["target_id"] == root_id
    )
    run.findings_json = [
        WorldValidationFinding(
            finding_id="rule-1",
            layer="semantic",
            severity="warning",
            category="consistency",
            action="AUTHOR-REQUIRED",
            message="城门时间需要核对",
            source_key=source["source_key"],
            location="line:1",
            excerpt="城门每晚关闭",
        ).model_dump()
    ]
    projected = await review_findings(db_session, test_project_id, {"id": str(run.id)})
    assert projected[0]["location"]["id"] == root_id
    assert projected[0]["location"]["section"] == "line:1"
    await proactive._notice(
        db_session,
        test_project_id,
        key=["world", root_id],
        title="城门时间",
        summary="待核对",
        sources=[projected[0]["location"]],
        result_ref={"type": "world_validation", "task_id": str(queued.id)},
    )
    run.status = "completed"
    assert not (await proactive.list_notices(db_session, test_project_id))["items"][0][
        "needs_recheck"
    ]
    await validation._authority.initialize_empty_canon(db_session, test_project_id)
    await validation.activate_builtin_policy(db_session, test_project_id)
    assert await validation._matches_frozen_inputs(db_session, run) == "policy"
    assert (await proactive.list_notices(db_session, test_project_id))["items"][0][
        "needs_recheck"
    ]
    with pytest.raises(ConflictError) as denied:
        await validation.require_gate(
            db_session,
            novel_id=test_project_id,
            validation_run_id=str(run.id),
            target_type="world_bible_draft",
            target_id=root_id,
            target_hash=run.scope_json["target_hash"],
        )
    assert denied.value.code == "required_validation"


@pytest.mark.asyncio
async def test_confirmed_alias_relation_and_new_chapter_keep_domain_ownership(
    db_session, test_project_id
):
    from modules.world.assistant_tools import (
        AddAlias,
        AddRelation,
        _alias_apply,
        _alias_preview,
        _relation_apply,
        _relation_preview,
    )
    from modules.world.models import CoreEntity
    from modules.writing.assistant_tools import NewChapter, _new_apply, _new_preview
    from modules.writing.facade import get_draft

    nid = uuid.UUID(test_project_id)
    first = CoreEntity(
        novel_id=nid, name="潮港", entity_type="location", status="canonical"
    )
    second = CoreEntity(
        novel_id=nid, name="灯塔", entity_type="location", status="canonical"
    )
    db_session.add_all([first, second])
    await db_session.flush()
    context = AssistantOperationContext(
        str(uuid.uuid4()), str(current_account_id()), WorkContext(scope="project")
    )
    alias = AddAlias(entity_id=first.id, alias="旧港")
    await _alias_apply(
        db_session,
        test_project_id,
        alias,
        await _alias_preview(db_session, test_project_id, alias, context=context),
        context=context,
    )
    await db_session.refresh(first)
    assert first.content_json["aliases"][0]["alias"] == "旧港"
    relation = AddRelation(
        source_id=first.id,
        target_id=second.id,
        relation_type="相邻",
        relation_kind="spatial",
        strength=0,
    )
    ref = await _relation_apply(
        db_session,
        test_project_id,
        relation,
        await _relation_preview(db_session, test_project_id, relation, context=context),
        context=context,
    )
    assert ref["type"] == "world_relation"
    chapter = NewChapter(title="抵达潮港", content="雾气仍未散去。")
    preview = await _new_preview(db_session, test_project_id, chapter, context=context)
    saved = await _new_apply(
        db_session, test_project_id, chapter, preview, context=context
    )
    draft = await get_draft(db_session, test_project_id, saved["id"])
    assert (
        draft.status == "draft"
        and draft.provenance_json["approved_by"] == context.owner_id
    )
    assert draft.provenance_json["review_required"] is True
