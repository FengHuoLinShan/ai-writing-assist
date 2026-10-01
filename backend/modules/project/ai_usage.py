"""Owner-facing AI usage summary in author language (secondary diagnostics)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.project.facade import get_project_context, require_active_project

# 次级诊断入口的作者语言映射；未登记的能力显示原始能力编号，
# 便于排查而不误导。
_CAPABILITY_LABELS: dict[str, str] = {
    "writing.generation": "AI 写作",
    "writing.semantic_review": "正文独立审查",
    "writing.targeted_revision": "定向返修",
    "writing.comment_revision": "批注改写",
    "writing.conflict_check": "设定冲突检查",
    "assistant.editorial": "编辑台审读",
    "assistant.forecast": "前瞻助手",
    "outline.analyze": "大纲整理",
    "world.generation": "世界观生成",
    "evidence.indexing": "资料索引",
}


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
                "label": _CAPABILITY_LABELS.get(
                    capability_id, f"其他 AI 能力（{capability_id}）"
                ),
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
