"""Assistant-owned safe result receipts and registered specialist entry points."""

from uuid import UUID

from sqlalchemy import select

from core.config import get_settings
from modules.assistant.contracts import ForecastDomainFact
from modules.assistant.models import AssistantRun
from modules.assistant.session_models import AssistantMessage, AssistantSession

INSTRUCTIONS = {
    ("assistant.discussion_next.v1"): (
        "判断现在缺的是证据、作者决定还是具体动作，提出一个最小下一步。讨论与猜测不是正史。"
    ),
}


async def inspect(db, novel_id, focus, excluded):
    if (
        focus.page not in {"assistant", "project", "today"}
        and not focus.prior_forecast_run_id
    ) or excluded:
        return []
    facts = []
    rows = (
        await db.scalars(
            select(AssistantRun)
            .where(
                AssistantRun.novel_id == UUID(novel_id),
                AssistantRun.request_json["protocol"]
                .as_string()
                .is_distinct_from("forecast_v1"),
                AssistantRun.status.in_(
                    ["completed", "failed", "cancelled", "budget_exceeded"]
                ),
            )
            .order_by(AssistantRun.created_at.desc())
            .limit(10)
        )
    ).all()
    for row in rows[:3]:
        facts.append(
            ForecastDomainFact(
                capability_id="assistant.task_result_ready.v1",
                subject=str(row.id),
                title="查看这次助手工作的结果",
                summary="运行已经结束；已有预览可审阅，未完成部分需要核对后再恢复。完成不等于采用。",
                source={
                    "run_id": str(row.id),
                    "task_id": str(row.task_id),
                    "status": row.status,
                    "result_refs": (row.result_json or {}).get("result_refs", []),
                    "completion": (row.result_json or {}).get("completion"),
                },
                scope_label="最近十次普通助手运行的终态回执，展示前三项",
                target={"page": "assistant", "run_id": str(row.id)},
            )
        )
    if focus.assistant_session_id:
        session = await db.scalar(
            select(AssistantSession).where(
                AssistantSession.novel_id == UUID(novel_id),
                AssistantSession.id == focus.assistant_session_id,
            )
        )
        if session:
            messages = (
                await db.scalars(
                    select(AssistantMessage)
                    .where(
                        AssistantMessage.novel_id == UUID(novel_id),
                        AssistantMessage.session_id == session.id,
                    )
                    .order_by(AssistantMessage.created_at.desc())
                    .limit(12)
                )
            ).all()
            facts.append(
                ForecastDomainFact(
                    capability_id="assistant.discussion_next.v1",
                    subject=str(session.id),
                    title="本次讨论",
                    summary="仅使用你选中的这次讨论，明确区分想法和已经确认的行动。",
                    source={
                        "messages": [
                            {
                                "id": str(item.id),
                                "role": item.role,
                                "content": item.content,
                            }
                            for item in reversed(messages)
                        ]
                    },
                    scope_label="所选讨论最近十二条消息",
                    target={"page": "assistant"},
                )
            )
    if focus.prior_forecast_run_id:
        previous = await db.scalar(
            select(AssistantRun).where(
                AssistantRun.novel_id == UUID(novel_id),
                AssistantRun.id == focus.prior_forecast_run_id,
                AssistantRun.request_json["protocol"].as_string() == "forecast_v1",
                AssistantRun.request_json["scope"]["persona"].as_string() == "author",
            )
        )
        if previous:
            report = (previous.result_json or {}).get("coverage") or {}
            facts.append(
                ForecastDomainFact(
                    capability_id="assistant.coverage_revisit.v1",
                    subject=str(previous.id),
                    title="回看上次未检查的部分",
                    summary="原记录保留了未检查、失效与遗漏原因；这次只在当前已授权范围内重新核对。",
                    source={
                        "run_id": str(previous.id),
                        "coverage": report,
                        "current_instruction": focus.explicit_instruction,
                    },
                    scope_label="明确选中的上一轮覆盖回执；不循环启动新分析",
                    target={"page": "assistant", "run_id": str(previous.id)},
                    actionable=bool(
                        report.get("omissions")
                        or (report.get("counts") or {}).get("not_checked")
                    ),
                )
            )
    if focus.explicit_instruction:
        enabled = get_settings().collaboration_v2_enabled
        facts.append(
            ForecastDomainFact(
                capability_id="assistant.specialist_entry.v1",
                subject="registered_case",
                title="需要更深入时，可发起创作试验",
                summary="先选择资料和请求上限，再以调查、试改或盲读配方处理这个问题。",
                source={
                    "enabled": enabled,
                    "question": focus.explicit_instruction,
                    "network_default": False,
                },
                scope_label="当前已注册的创作试验入口",
                actionable=enabled,
                target={"page": "assistant", "tab": "creative"},
                unknowns=["专项结论仍需核对；默认不联网。"],
            )
        )
    return facts
