"""Author goals, standing grants and one durable execution identity per request."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from core.config import get_settings
from core.errors import ConflictError, NotFoundError, ValidationError
from infrastructure.llm.agent_runtime import AgentRunBudget
from infrastructure.llm.collaboration import content_hash
from infrastructure.tasks.facade import cancel_exact_task, enqueue_operation_task
from modules.account.facade import current_account_id
from modules.collaboration.contracts import Grant, Recipe
from modules.collaboration.models import (
    CollaborationCase,
    CollaborationRun,
    CollaborationWorkItem,
)
from modules.collaboration.recipes import get_recipe
from modules.evidence.facade import collect_creative_manifest, creative_context_text
from modules.local_agent.facade import local_task_meta
from modules.project.facade import (
    build_project_llm_execution_snapshot,
    get_any_project_context,
    require_active_project,
    require_active_project_exclusive,
)


def enabled():
    if (
        not get_settings().assistant_enabled
        or not get_settings().collaboration_v2_enabled
    ):
        raise ValidationError(
            "创作试验尚未开启", code="COLLABORATION_UNAVAILABLE", status_code=503
        )


async def require_case(db, novel_id, case_id, *, lock=False, execute=False):
    await require_active_project(db, str(novel_id))
    query = select(CollaborationCase).where(
        CollaborationCase.novel_id == UUID(str(novel_id)),
        CollaborationCase.id == UUID(str(case_id)),
    )
    if lock:
        from modules.assistant.facade import lock_background_slot

        await lock_background_slot(db, str(novel_id))
        query = query.with_for_update()
    case = await db.scalar(query.execution_options(populate_existing=True))
    project = await get_any_project_context(db, str(novel_id))
    if case is None or project is None or str(case.owner_id) != str(project.owner_id):
        raise NotFoundError("创作任务不可访问")
    if execute:
        enabled()
        if case.recipe_json["id"] in get_settings().creative_disabled_recipes:
            raise ConflictError(
                "这一类创作试验已暂停，已有成果仍可查看", code="RECIPE_UNAVAILABLE"
            )
        grant = Grant.model_validate(case.grant_json)
        if case.status != "active" or grant.expires_at <= datetime.now(UTC):
            raise ConflictError("本次授权已结束，请更新授权后继续", code="GRANT_EXPIRED")
    return case


async def require_run(db, novel_id, run_id, *, lock=False):
    query = select(CollaborationRun).where(
        CollaborationRun.novel_id == UUID(str(novel_id)),
        CollaborationRun.id == UUID(str(run_id)),
    )
    if lock:
        existing = await db.scalar(query)
        if existing is None:
            raise NotFoundError("试验运行不可访问")
        await require_case(db, novel_id, existing.case_id, lock=True)
        query = query.with_for_update()
    run = await db.scalar(query.execution_options(populate_existing=True))
    if run is None:
        raise NotFoundError("试验运行不可访问")
    await require_case(db, novel_id, run.case_id)
    if lock and run.status in {"pending", "running"}:
        status = await execution_status(db, run)
        if status != run.status:
            run.status, run.error_code = status, "TASK_INTERRUPTED"
            await sync_background_projection(
                db, run, await require_case(db, novel_id, run.case_id)
            )
    return run


async def execution_status(db, run):
    if run.status not in {"pending", "running"} or not run.task_id:
        return run.status
    from infrastructure.tasks.facade import list_task_lifecycle_contracts

    life = (
        await list_task_lifecycle_contracts(
            db,
            novel_id=str(run.novel_id),
            task_ids=[str(run.task_id)],
            max_heartbeat_gap=0,
        )
    ).get(str(run.task_id))
    if life and life.status in {"failed", "cancelled"}:
        return life.status
    return run.status


def case_view(case):
    return {
        "id": str(case.id),
        "goal": case.goal,
        "goal_version": case.goal_version,
        "constraints": case.constraints_json,
        "status": case.status,
        "grant": case.grant_json,
        "grant_hash": content_hash(case.grant_json),
        "recipe": case.recipe_json,
        "requests_used": case.requests_used,
    }


async def create_case(db, novel_id, data):
    enabled()
    await require_active_project_exclusive(db, novel_id)
    request_hash = content_hash(data.model_dump(mode="json"))
    prior = await db.scalar(
        select(CollaborationCase).where(
            CollaborationCase.novel_id == UUID(novel_id),
            CollaborationCase.operation_id == data.operation_id,
        )
    )
    if prior:
        if prior.request_hash != request_hash:
            raise ConflictError("请求标识已用于其他任务", code="OPERATION_MISMATCH")
        return case_view(prior)
    if data.grant.expires_at <= datetime.now(UTC):
        raise ValidationError("请选择未来的授权截止时间")
    manifest = await collect_creative_manifest(db, novel_id, data.grant, 1)
    creative_context_text(manifest)
    recipe = get_recipe(data.recipe_id)
    if recipe.id in get_settings().creative_disabled_recipes:
        raise ValidationError("这一类创作试验已暂停", code="RECIPE_UNAVAILABLE")
    if data.custom_recipe:
        custom = data.custom_recipe
        if set(custom.capabilities) - set(recipe.capabilities):
            raise ValidationError("自定义配方不能扩大基础配方的能力")
        checks = list(dict.fromkeys([*recipe.required_checks, *custom.required_checks]))
        if len(checks) > 12:
            raise ValidationError("保留原检查后，合计最多十二项检查，请合并重复要求")
        recipe = Recipe.model_validate(
            {
                **recipe.model_dump(),
                "label": custom.label,
                "strategy": custom.strategy,
                "questions": custom.questions,
                "capabilities": custom.capabilities,
                "required_checks": checks,
            }
        )
    if recipe.id == "import_consult" and (
        data.grant.import_scope is None or data.grant.resources
    ):
        raise ValidationError("导入会诊请只选择精确的原导入组")
    if recipe.id == "blind_reader" and (
        data.grant.context_confirmation_id
        or any(ref.kind != "writing_draft" for ref in data.grant.resources)
    ):
        raise ValidationError("盲读只接收所选正文，不接收作者资料确认包")
    if recipe.id == "blind_reader" and data.grant.import_scope:
        raise ValidationError("盲读不能接收未采用的导入候选")
    if recipe.id == "blind_reader" and data.grant.allow_web:
        raise ValidationError("盲读只能使用已读正文，不能追加网页资料")
    if recipe.id == "blind_reader" and data.grant.cutoff_chapter is None:
        raise ValidationError("读者检查需要明确阅读截止点")
    case = CollaborationCase(
        novel_id=UUID(novel_id),
        owner_id=current_account_id(),
        operation_id=data.operation_id,
        request_hash=request_hash,
        goal=data.goal,
        constraints_json=data.constraints,
        grant_json=data.grant.model_dump(mode="json"),
        recipe_json=recipe.model_dump(mode="json"),
    )
    db.add(case)
    await db.flush()
    if data.grant.follow_changes:
        from modules.assistant.facade import register_creative_watch

        await register_creative_watch(db, novel_id, case.id, True)
    return case_view(case)


async def update_grant(db, novel_id, case_id, data):
    case = await require_case(db, novel_id, case_id, lock=True)
    if content_hash(case.grant_json) != data.expected_grant_hash:
        raise ConflictError("授权已经更新", code="GRANT_CHANGED")
    previous_grant = Grant.model_validate(case.grant_json)
    restriction_only = data.grant == previous_grant.model_copy(
        update={"follow_changes": False, "allow_background_web": False}
    )
    if data.status == "active" and not restriction_only:
        if (
            data.grant.expires_at <= datetime.now(UTC)
            or data.grant.request_limit < case.requests_used
        ):
            raise ValidationError("授权时间需在未来，累计额度不能小于已经使用的额度")
        await collect_creative_manifest(db, novel_id, data.grant, case.goal_version)
    active = (
        await db.scalars(
            select(CollaborationRun).where(
                CollaborationRun.novel_id == case.novel_id,
                CollaborationRun.case_id == case.id,
                CollaborationRun.status.in_(["pending", "running"]),
            )
        )
    ).all()
    for run in active:
        await stop_run(db, novel_id, str(run.id))
    case.grant_history_json = [
        *(case.grant_history_json or []),
        {
            "grant": case.grant_json,
            "status": case.status,
            "ended_at": datetime.now(UTC).isoformat(),
            "requests_used": case.requests_used,
        },
    ]
    case.grant_json, case.status = data.grant.model_dump(mode="json"), data.status
    from modules.assistant.facade import register_creative_watch

    await register_creative_watch(
        db, novel_id, case.id, data.status == "active" and data.grant.follow_changes
    )
    await db.flush()
    return case_view(case)


async def resume_run(db, novel_id, run_id):
    from infrastructure.tasks.facade import resume_manual_task
    from modules.collaboration.contracts import InputManifest
    from modules.evidence.facade import revalidate_creative_manifest

    prior = await require_run(db, novel_id, run_id)
    case = await require_case(db, novel_id, prior.case_id, lock=True, execute=True)
    run = await require_run(db, novel_id, run_id, lock=True)
    if (run.llm_snapshot_json.get("primary") or {}).get("local_agent"):
        raise ConflictError("本机任务中断后请从当前目标新建试验", code="NOT_RESUMABLE")
    if run.status in {"pending", "running"}:
        return {"run_id": str(run.id), "task_id": str(run.task_id), "replayed": True}
    if run.status not in {"failed", "partial", "cancelled"} or not run.task_id:
        raise ConflictError("此运行不能直接恢复，请从当前目标新建试验")
    grant = Grant.model_validate(case.grant_json)
    budget = AgentRunBudget.model_validate(run.budget_json)
    if (
        budget.pending_usage
        or budget.remaining_seconds <= 0
        or budget.requests + 4 > grant.run_request_limit
        or case.requests_used + 4 > grant.request_limit
    ):
        raise ConflictError(
            "尚有用量未确认或原轮额度不足；不能重置用量后重试", code="USAGE_UNKNOWN"
        )
    manifest = InputManifest.model_validate(run.manifest_json)
    if manifest.goal_version != case.goal_version:
        raise ConflictError("作者目标已变化，请开始新一轮", code="GOAL_CHANGED")
    await revalidate_creative_manifest(db, novel_id, grant, manifest)
    active = await db.scalar(
        select(CollaborationRun.id).where(
            CollaborationRun.novel_id == case.novel_id,
            CollaborationRun.case_id == case.id,
            CollaborationRun.status.in_(["pending", "running"]),
        )
    )
    if active:
        raise ConflictError("此任务已有运行中的试验", code="ACTIVE_RUN_CONFLICT")
    from infrastructure.tasks.facade import list_task_lifecycle_contracts

    life = (
        await list_task_lifecycle_contracts(
            db, novel_id=novel_id, task_ids=[str(run.task_id)], max_heartbeat_gap=0
        )
    ).get(str(run.task_id))
    if run.status != "partial" and (
        life is None or "resume" not in life.available_actions
    ):
        raise ConflictError(
            "原任务没有恢复资格；可在保留累计消费的原目标上新建一轮", code="NOT_RESUMABLE"
        )
    await resume_manual_task(
        db,
        task_id=str(run.task_id),
        task_types={"collaboration_run"},
        novel_id=novel_id,
        allow_completed=run.status == "partial",
    )
    # Keep successful immutable outputs; retry the remaining dependency closure.
    rows = await db.scalars(
        select(CollaborationWorkItem).where(
            CollaborationWorkItem.novel_id == case.novel_id,
            CollaborationWorkItem.run_id == run.id,
        )
    )
    for row in rows:
        if row.status in {"failed", "blocked", "cancelled", "running"}:
            row.status, row.error_code = "pending", None
    run.status, run.error_code = "pending", None
    run.generation += 1
    await sync_background_projection(db, run, case)
    await db.flush()
    return {"run_id": str(run.id), "task_id": str(run.task_id), "replayed": False}


async def update_goal(db, novel_id, case_id, data):
    case = await require_case(db, novel_id, case_id, lock=True, execute=True)
    if case.goal_version != data.expected_version:
        raise ConflictError("目标已经更新，请读取最新内容", code="GOAL_CHANGED")
    case.goal_history_json = [
        *case.goal_history_json,
        {
            "version": case.goal_version,
            "goal": case.goal,
            "constraints": case.constraints_json,
        },
    ]
    case.goal, case.constraints_json = data.goal, data.constraints
    case.goal_version += 1
    await db.flush()
    return case_view(case)


async def submit_run(db, novel_id, case_id, data, *, background=False):
    case = await require_case(db, novel_id, case_id, lock=True, execute=True)
    payload = {**data.model_dump(mode="json"), "background": background}
    request_hash = content_hash({"case_id": str(case.id), **payload})
    prior = await db.scalar(
        select(CollaborationRun).where(
            CollaborationRun.novel_id == UUID(novel_id),
            CollaborationRun.operation_id == data.operation_id,
        )
    )
    if prior:
        if prior.request_hash != request_hash:
            raise ConflictError("请求标识已用于其他试验", code="OPERATION_MISMATCH")
        return {"run_id": str(prior.id), "task_id": str(prior.task_id), "replayed": True}
    if case.goal_version != data.expected_goal_version:
        raise ConflictError("目标已经更新", code="GOAL_CHANGED")
    grant = Grant.model_validate(case.grant_json)
    if case.requests_used + 4 > grant.request_limit:
        raise ConflictError("累计额度不足以完成生成与复核", code="BUDGET_EXCEEDED")
    active = await db.scalar(
        select(CollaborationRun.id).where(
            CollaborationRun.case_id == case.id,
            CollaborationRun.novel_id == case.novel_id,
            CollaborationRun.status.in_(["pending", "running"]),
        )
    )
    if active and (await require_run(db, novel_id, str(active), lock=True)).status in {
        "pending",
        "running",
    }:
        raise ConflictError("此创作任务仍在运行", code="ACTIVE_RUN_CONFLICT")
    manifest = await collect_creative_manifest(db, novel_id, grant, case.goal_version)
    creative_context_text(manifest)
    from infrastructure.llm.web_search import search_snapshot

    web_snapshot = search_snapshot() if grant.allow_web else None
    snapshot = await build_project_llm_execution_snapshot(
        db, novel_id, agent_executor=True
    )
    profiles = {}
    for role, provider_id in grant.model_connections.items():
        profiles[role] = await build_project_llm_execution_snapshot(
            db, novel_id, provider_id=provider_id
        )
    run = CollaborationRun(
        id=data.operation_id,
        novel_id=case.novel_id,
        case_id=case.id,
        operation_id=data.operation_id,
        request_hash=request_hash,
        request_json={
            **payload,
            "goal": case.goal,
            "constraints": case.constraints_json,
            "recipe": case.recipe_json,
            "web_snapshot": web_snapshot,
        },
        manifest_json=manifest.model_dump(mode="json"),
        llm_snapshot_json={"primary": snapshot, "roles": profiles},
        budget_json=AgentRunBudget(policy_version="collaboration_v2").model_dump(
            mode="json"
        ),
    )
    task = await enqueue_operation_task(
        db,
        operation_id=str(data.operation_id),
        task_type="collaboration_run",
        novel_id=novel_id,
        request_payload={"case_id": str(case.id), **payload},
        meta={
            "run_id": str(run.id),
            **local_task_meta(snapshot),
            **({"_task_priority": "background"} if background else {}),
        },
    )
    if task.reused:
        raise ConflictError("请求标识已有其他执行记录", code="OPERATION_MISMATCH")
    run.task_id = UUID(task.task_id)
    db.add(run)
    await db.flush()
    await sync_background_projection(db, run, case)
    return {"run_id": str(run.id), "task_id": task.task_id, "replayed": False}


async def stop_run(db, novel_id, run_id):
    run = await require_run(db, novel_id, run_id, lock=True)
    if run.status in {"pending", "running"}:
        if run.task_id:
            await cancel_exact_task(
                db,
                task_id=str(run.task_id),
                novel_id=novel_id,
                task_types={"collaboration_run"},
                transition_reason="author_stopped_experiment",
            )
        run.status = "cancelled"
        run.generation += 1
        rows = await db.scalars(
            select(CollaborationWorkItem).where(
                CollaborationWorkItem.novel_id == UUID(novel_id),
                CollaborationWorkItem.run_id == run.id,
                CollaborationWorkItem.status.in_(["pending", "running"]),
            )
        )
        for item in rows:
            item.status = "cancelled"
        await sync_background_projection(
            db, run, await require_case(db, novel_id, run.case_id)
        )
        await db.flush()
    return {"run_id": str(run.id), "status": run.status, "usage": run.budget_json}


async def sync_background_projection(db, run, case):
    if not run.request_json.get("background"):
        return
    from modules.assistant.facade import project_creative_run

    await project_creative_run(
        db,
        str(run.novel_id),
        str(run.id),
        owner_id=str(case.owner_id),
        task_id=str(run.task_id),
        status=run.status,
        budget=run.budget_json,
        case_id=str(case.id),
        request_hash=run.request_hash,
    )
