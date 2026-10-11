"""Owner-facing AI usage summary in author language (secondary diagnostics)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.container import get
from core.service_keys import EVIDENCE_CONFIRMATION_READS
from modules.project.facade import get_project_context, require_active_project

# 次级诊断入口的作者语言映射，键必须与真实能力编号一致
# （注册表见 modules/evidence/compilation/knowledge/policies.py 的
# CAPABILITY_REGISTRY）。解析时先精确匹配，再按点分层级向上升前缀，
# 因此命名空间键（如 writing.conflict_check）覆盖其子能力；
# 未登记的能力显示原始编号，便于排查而不误导。
_CAPABILITY_LABELS: dict[str, str] = {
    "writing.generate": "AI 写作",
    "writing.semantic_review": "正文独立审查",
    "writing.targeted_revision": "定向返修",
    "writing.comment_revision": "批注改写",
    "writing.conflict_check": "设定冲突检查",
    "assistant.editorial": "编辑台审读",
    "assistant.forecast": "前瞻助手",
    "assistant.turn": "作者助手对话",
    "assistant": "作者助手",
    "story.outline.analyze": "大纲整理",
    "story": "剧情结构辅助",
    "world.generation": "世界观生成",
    "world.map_atlas": "世界地图生成",
    "world.map_image": "地图插图生成",
    "world.map_image_prompt": "地图插图提示词",
    "world.map_structure": "地图结构生成",
    "world.world_bible.synopsis": "世界书简介",
    "world.alias_relations.extract": "别名关系抽取",
    "world.entity_fusion": "实体融合",
    "world.validation": "设定校验",
    "world.team_stress": "世界观压力测试",
    "world.ask": "世界观问答",
    "imports": "深度导入与整理",
    "infrastructure.rag_index_chapter": "资料索引",
    "infrastructure.rag_reindex_novel": "资料索引",
    "infrastructure.rag_retry_embeddings": "资料索引",
    "infrastructure.rag_query_planner": "检索规划",
    "infrastructure.embedding": "向量索引",
    "infrastructure.reranker": "重排序",
    "infrastructure.format_repair": "格式修复",
    "infrastructure.account_connection_test": "账户连接测试",
    "infrastructure": "基础设施任务",
    "interaction": "读者互动",
    "collaboration": "协作工作流",
    "evolution": "设定演化",
    "project.smart_dedup": "智能去重",
}

# 按作品成果归因的桶：顺序即设置页展示顺序。归因只读 Evidence 确认
# 记录的结果状态（writing.generate → 候选 → 采用/放弃 由确认记录的
# result_status 跟踪），不改变任何配额或计费策略。
_ATTRIBUTION_BUCKETS: tuple[tuple[str, str], ...] = (
    ("adopted", "已写进作品的成果"),
    ("pending", "进行中或等你处理的候选"),
    ("not_adopted", "未采用或返修"),
    ("failed", "失败与恢复"),
    ("other", "资料整理等辅助消耗"),
)

_TASK_FAILURE_STATUSES = {"failed", "cancelled"}

# 确认记录结果状态 → 归因桶。adopted 之外的失效状态（来源已变化、
# 需重新处理）与已放弃的候选同样没有变成作品，都归入未采用或返修。
_NON_OWNER_BUCKET = "not_adopted"
_STALE_RESULT_STATUSES = {"stale_context", "needs_review"}


def _attribution_bucket(task_status: str, outcome: dict[str, Any] | None) -> str:
    if str(task_status or "") in _TASK_FAILURE_STATUSES:
        return "failed"
    if outcome is None:
        return "other"
    if not outcome.get("owner_task"):
        # 同一确认被重新生成时，旧任务是被取代的尝试，成果不属于它。
        return _NON_OWNER_BUCKET
    result_status = str(outcome.get("result_status") or "")
    if result_status == "adopted":
        return "adopted"
    if result_status == "rejected" or result_status in _STALE_RESULT_STATUSES:
        return _NON_OWNER_BUCKET
    # done / running / confirmed 等都表示还没有确定的采用结果。
    return "pending"


def _capability_label(capability_id: str) -> str:
    parts = str(capability_id or "").split(".")
    for size in range(len(parts), 0, -1):
        label = _CAPABILITY_LABELS.get(".".join(parts[:size]))
        if label:
            return label
    return f"其他 AI 能力（{capability_id}）"


async def get_project_ai_usage(
    db: AsyncSession,
    novel_id: str,
    *,
    days: int = 30,
) -> dict[str, Any]:
    """按能力汇总窗口期 AI 用量，供项目设置的次级诊断入口展示。

    单位为模型计费词元（token）；这是诊断视图，不在主路径展示。
    已知数字只统计取得完整回执的请求；`requests_unknown` 与
    `charge_unconfirmed` 如实保留用量未知与计费未确认的部分，不折算为 0。
    `attribution` 把同一批任务按作品成果归因（经确认记录的结果引用，
    task → 候选 → 采用），只读查询，不改变配额或计费策略。
    """
    from infrastructure.tasks.facade import summarize_project_ai_usage

    await require_active_project(db, novel_id)
    context = await get_project_context(db, novel_id)
    if context is None:
        from core.errors import NotFoundError

        raise NotFoundError("Project not found")
    raw = await summarize_project_ai_usage(db, novel_id=novel_id, days=days)
    capabilities = []
    total_requests = 0
    total_prompt = 0
    total_completion = 0
    total_requests_unknown = 0
    charge_unconfirmed = False
    usage_complete = True
    for capability_id, bucket in sorted(raw["capabilities"].items()):
        total_requests += int(bucket["requests"])
        total_requests_unknown += int(bucket["requests_unknown"])
        total_prompt += int(bucket["prompt_tokens"])
        total_completion += int(bucket["completion_tokens"])
        charge_unconfirmed = charge_unconfirmed or bool(bucket["charge_unconfirmed"])
        usage_complete = usage_complete and bucket["usage_complete"]
        capabilities.append(
            {
                "capability": capability_id,
                "label": _capability_label(capability_id),
                "tasks": int(bucket["tasks"]),
                "requests": int(bucket["requests"]),
                "requests_unknown": int(bucket["requests_unknown"]),
                "input_tokens": int(bucket["prompt_tokens"]),
                "output_tokens": int(bucket["completion_tokens"]),
                "charge_unconfirmed": bool(bucket["charge_unconfirmed"]),
                "usage_complete": bucket["usage_complete"],
            }
        )
    return {
        "window_days": raw["window_days"],
        "tasks_scanned": raw["tasks_scanned"],
        "tasks_with_envelope": raw["tasks_with_envelope"],
        "unreadable_envelopes": raw.get("unreadable_envelopes", 0),
        "scan_truncated": bool(raw.get("scan_truncated")),
        "totals": {
            "requests": total_requests,
            "requests_unknown": total_requests_unknown,
            "input_tokens": total_prompt,
            "output_tokens": total_completion,
            "charge_unconfirmed": charge_unconfirmed,
            "usage_complete": usage_complete,
        },
        "capabilities": capabilities,
        "attribution": await _attribute_usage_by_outcome(db, novel_id=novel_id, raw=raw),
    }


async def _attribute_usage_by_outcome(
    db: AsyncSession,
    *,
    novel_id: str,
    raw: dict[str, Any],
) -> dict[str, Any]:
    """把窗口期任务用量按作品成果归因（只读，不做配额策略变化）。

    经 Evidence 确认记录的结果引用连接任务与采用结果：确认记录跟踪
    生成任务及其候选的采用/放弃/失效状态。没有确认引用的任务（资料
    索引、独立审查等）单列为辅助消耗，不并入任何成果桶；用量未知与
    计费未确认沿用 BR-0a 语义逐桶如实保留。
    """
    task_rows = [row for row in (raw.get("tasks") or []) if isinstance(row, dict)]
    outcomes: dict[str, dict[str, Any]] = {}
    if task_rows:
        outcomes = await get(EVIDENCE_CONFIRMATION_READS).describe_task_outcomes(
            db,
            novel_id=novel_id,
            task_ids=[str(row["task_id"]) for row in task_rows],
        )
    buckets = {
        key: {
            "key": key,
            "label": label,
            "tasks": 0,
            "requests": 0,
            "requests_unknown": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "charge_unconfirmed": False,
            "usage_complete": True,
        }
        for key, label in _ATTRIBUTION_BUCKETS
    }
    for row in task_rows:
        outcome = outcomes.get(str(row.get("task_id") or ""))
        bucket = buckets[_attribution_bucket(str(row.get("status") or ""), outcome)]
        bucket["tasks"] += 1
        bucket["usage_complete"] = bucket["usage_complete"] and row.get(
            "usage_complete", True
        )
        bucket["requests"] += int(row.get("requests") or 0)
        bucket["requests_unknown"] += int(row.get("requests_unknown") or 0)
        bucket["input_tokens"] += int(row.get("input_tokens") or 0)
        bucket["output_tokens"] += int(row.get("output_tokens") or 0)
        bucket["charge_unconfirmed"] = bucket["charge_unconfirmed"] or bool(
            row.get("charge_unconfirmed")
        )
    return {"buckets": list(buckets.values())}
