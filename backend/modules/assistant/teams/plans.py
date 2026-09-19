"""Select one immutable plan, then use the existing confirmed action batch."""

from uuid import UUID

from sqlalchemy import select

from core.errors import ConflictError, NotFoundError
from infrastructure.llm.agent_runtime import AgentRunBudget
from modules.assistant.contracts import AssistantOperationContext
from modules.assistant.evidence_tools import AssistantToolContext, fingerprint
from modules.assistant.models import AssistantActionBatch
from modules.assistant.operations import prepare_actions
from modules.assistant.schemas import ProposedAction, WorkContext
from modules.assistant.service import AssistantService
from modules.project.facade import require_active_project


async def select_plan(db, run_id, selection, owner_id):
    await require_active_project(db, selection.novel_id)
    service = AssistantService()
    run = await service.require_run(db, selection.novel_id, run_id, lock=True)
    if str(run.owner_id) != owner_id or not run.request_json.get("team"):
        raise NotFoundError("方案不存在")
    result = dict(run.result_json)
    plan = next(
        (item for item in result.get("plans", []) if item["key"] == selection.plan_key),
        None,
    )
    if not plan or plan["fingerprint"] != selection.expected_hash:
        raise ConflictError("方案已变化，请重新打开", code="team_plan_changed")
    existing = await db.scalar(
        select(AssistantActionBatch).where(
            AssistantActionBatch.novel_id == UUID(selection.novel_id),
            AssistantActionBatch.run_id == run.id,
        )
    )
    if existing:
        if result.get("selected_plan") != selection.plan_key:
            raise ConflictError(
                "本轮已选择另一方案，请在新一轮讨论中改选", code="team_plan_selected"
            )
        return await service.get_run(db, selection.novel_id, run_id)
    if (
        run.status != "completed"
        or result.get("knowledge_review", {}).get("status") != "passed"
    ):
        raise ConflictError("请等待方案完成知识复核", code="team_plan_unreviewed")
    service.require_team_enabled(run.request_json["team"]["id"])
    work = WorkContext.model_validate(run.request_json["context"])
    scope = AssistantToolContext(
        db,
        selection.novel_id,
        owner_id,
        work,
        None,
        AgentRunBudget.model_validate(run.budget_json),
        None,
        evidence_refs=run.checkpoint_json.get("evidence_refs", {}),
    )
    await scope.revalidate(list(scope.evidence_refs))
    proposals = [
        ProposedAction.model_validate(
            {
                key: value
                for key, value in action.items()
                if key in ProposedAction.model_fields
            }
        )
        for action in plan["actions"]
    ]
    actions = await prepare_actions(
        db,
        selection.novel_id,
        proposals,
        context=AssistantOperationContext(run_id, owner_id, work),
    )
    if actions != plan["actions"]:
        raise ConflictError(
            "方案依据或操作版本已变化，请重新查证", code="team_plan_stale"
        )
    digest = fingerprint(actions)
    batch = AssistantActionBatch(
        novel_id=run.novel_id,
        run_id=run.id,
        fingerprint=digest,
        actions_json=actions,
        status="pending",
    )
    db.add(batch)
    await db.flush()
    run.result_json = {
        **result,
        "actions": actions,
        "selected_plan": selection.plan_key,
        "batch": {"id": str(batch.id), "fingerprint": digest, "status": "pending"},
    }
    run.status = "waiting_approval"
    await db.flush()
    return await service.get_run(db, selection.novel_id, run_id)


async def enqueue_plan_regression(db, batch_id, novel_id, owner_id):
    """Queue an explicitly confirmed, separately metered domain regression host."""
    from uuid import uuid5

    from core.errors import DomainError
    from modules.assistant.schemas import TurnCreate

    await require_active_project(db, novel_id)
    batch = await db.scalar(
        select(AssistantActionBatch)
        .where(
            AssistantActionBatch.id == UUID(batch_id),
            AssistantActionBatch.novel_id == UUID(novel_id),
        )
        .with_for_update()
    )
    if batch is None:
        raise NotFoundError("复核授权不存在")
    service = AssistantService()
    run = await service.require_run(db, novel_id, str(batch.run_id))
    if str(run.owner_id) != owner_id or not batch.authorization_json.get("review_after"):
        raise NotFoundError("复核授权不存在")
    previous = dict(run.result_json.get("regression") or {})
    references = dict(previous.get("references") or {})
    checked = set(previous.get("checked_action_keys") or [])
    omissions, targets, keys = [], [], []
    work = WorkContext.model_validate(
        batch.authorization_json.get("postconditions", {}).get("work")
        or run.request_json["context"]
    )
    for item in batch.results_json:
        if item["status"] != "completed" or item["key"] in checked:
            continue
        title = next(
            (
                action["title"]
                for action in batch.actions_json
                if action["key"] == item["key"]
            ),
            "这项修改",
        )
        result = item.get("result") or {}
        target = result.get("target") or result
        kind = target.get("type") or result.get("type")
        if kind == "writing_draft":
            capability = (
                "writing.review"
                if work.context_confirmation_id
                else "writing.review_world"
            )
            arguments = {"draft_ids": [target["id"]]}
        elif kind in {
            "world_entity",
            "core_entity",
            "world_bible_page",
            "world_bible_page_draft",
        }:
            capability = "world.review"
            arguments = {
                "root_type": "core_entity"
                if kind in {"world_entity", "core_entity"}
                else kind,
                "root_id": target["id"],
            }
        else:
            omissions.append(f"{title}的文学/结构影响需在原工作区继续核对")
            continue
        targets.append({"capability": capability, "arguments": arguments, "title": title})
        keys.append(item["key"])
    if targets:
        identity = str(uuid5(batch.id, "post-review:" + fingerprint(sorted(keys))))
        try:
            async with db.begin_nested():
                if team := run.request_json.get("team"):
                    service.require_team_enabled(team["id"])
                child = await service.submit(
                    db,
                    str(run.session_id),
                    TurnCreate(
                        novel_id=novel_id,
                        operation_id=identity,
                        message="复核本次已确认的修改，检查原问题及回归；不重复写入。",
                        context=work,
                        allow_web=False,
                    ),
                    owner_id,
                    continuation_of=str(run.id),
                    regression_targets=targets,
                )
        except DomainError as error:
            omissions.append(
                "修改已执行；专项协作已关闭，未启动新的复核。"
                if error.code == "team_unavailable"
                else "修改已执行；原资料范围需重新确认后才能继续复核。"
            )
        else:
            references[identity] = {
                "type": "assistant_run",
                "id": child["id"],
                "task_id": child["task_id"],
                "session_id": child["session_id"],
                "label": "查看修改后复核",
            }
            checked.update(keys)
    regression = {
        "references": references,
        "omissions": omissions,
        "checked_action_keys": sorted(checked),
        "status": "queued" if references else "not_checked",
        "authority": "修改已执行；领域复核尚未完成，不代表质量通过",
    }
    run.result_json = {**run.result_json, "regression": regression}
    await db.flush()
    return regression


async def run_plan_regression(deps, targets):
    from types import SimpleNamespace

    from modules.assistant.operations import execute_suggestion
    from modules.assistant.schemas import AssistantAnswer

    keys, omissions = [], []
    for target in targets:
        if target["capability"] not in {
            "writing.review",
            "writing.review_world",
            "world.review",
        }:
            raise ConflictError("复核协议包含未注册的操作")
        result = await execute_suggestion(
            SimpleNamespace(deps=deps), target["capability"], target["arguments"]
        )
        if result.get("evidence_id"):
            keys.append(result["evidence_id"])
        review = result.get("review_result") or {}
        if review.get("status") != "completed":
            omissions.append(f"{target['title']}尚未完整复核")
        omissions.extend(review.get("not_checked", []))
    return AssistantAnswer(
        answer="修订后复核已结束。请核对各领域回执的具体问题与实际覆盖；任务结束不代表文学质量通过。",
        evidence_ids=keys,
        omissions=list(dict.fromkeys(omissions))[:20],
    )
