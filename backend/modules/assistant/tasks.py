"""Queue entry for the domain-owned assistant run."""

from infrastructure.tasks.registry import task_handler
from modules.assistant.service import AssistantService


@task_handler(
    "assistant_turn",
    recovery_policy="manual_resume",
    # 非 pro 主循环 12（AgentRunBudget author 上限），pro 加 2 次独立复核
    # 结构化调用（1+2 修复）×R3 = 18 ⇒ 30。pro 标志在 AssistantRun.request_json
    # （不在 task meta 上，同步 resolver 取不到），静态按 pro 上界 30 兜底；
    # 非 pro 的 12 次上限仍由领域 AgentRunBudget 先行约束。deadline 与
    # Agent 30 分钟窗口（budget.remaining_seconds）一致。
    root_capability_id="assistant.turn",
    run_request_limit=30,
    run_deadline_seconds=1800.0,
)
async def handle_assistant_turn(db, task):
    return await AssistantService().execute(db, task)


@task_handler(
    "assistant_forecast",
    recovery_policy="manual_resume",
    root_capability_id="assistant.forecast",
    run_request_limit=4,
    run_deadline_seconds=1800.0,
    run_id=lambda task: str(task.meta["run_id"]),
)
async def handle_assistant_forecast(db, task):
    from modules.assistant.forecast.runtime import execute

    return await execute(db, task)


@task_handler(
    "assistant_editorial_review",
    recovery_policy="manual_resume",
    root_capability_id="assistant.editorial",
    run_request_limit=4,
    run_deadline_seconds=1800.0,
    run_id=lambda task: str(task.meta["review_id"]),
)
async def handle_assistant_editorial_review(db, task):
    from modules.assistant.editorial import execute

    return await execute(db, task)


@task_handler(
    "assistant_editorial_recheck",
    recovery_policy="manual_resume",
    root_capability_id="assistant.editorial",
    run_request_limit=1,
    run_deadline_seconds=1800.0,
    run_id=lambda task: str(task.meta["issue_id"]),
)
async def handle_assistant_editorial_recheck(db, task):
    from modules.assistant.editorial import execute_recheck

    return await execute_recheck(db, task)
