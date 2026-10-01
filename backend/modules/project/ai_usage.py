"""Owner-facing AI usage summary in author language (secondary diagnostics)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

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
    for capability_id, bucket in sorted(raw["capabilities"].items()):
        total_requests += int(bucket["requests"])
        total_prompt += int(bucket["prompt_tokens"])
        total_completion += int(bucket["completion_tokens"])
        capabilities.append(
            {
                "capability": capability_id,
                "label": _capability_label(capability_id),
                "tasks": int(bucket["tasks"]),
                "requests": int(bucket["requests"]),
                "input_tokens": int(bucket["prompt_tokens"]),
                "output_tokens": int(bucket["completion_tokens"]),
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
            "input_tokens": total_prompt,
            "output_tokens": total_completion,
        },
        "capabilities": capabilities,
    }
