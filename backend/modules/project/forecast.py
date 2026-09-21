"""Reuse the author workspace's current continuation and attention projections."""

from modules.assistant.contracts import ForecastDomainFact
from modules.project.facade import inspect_project_workspace


async def inspect(db, novel_id, focus, excluded):
    if focus.page not in {"project", "today"} or excluded:
        return []
    summary = await inspect_project_workspace(db, novel_id)
    facts = []
    continuation = summary.get("continuation")
    if continuation:
        facts.append(
            ForecastDomainFact(
                capability_id="project.resume.v1",
                subject="last_saved_chapter",
                title=f"继续：{continuation['title']}",
                summary="这是最近保存的工作章节，可以回到原位置继续。",
                source=continuation,
                scope_label="原项目工作台记录的最近保存章节；不代表重要性排名",
                target={
                    "page": "writing",
                    "chapter_index": continuation["chapter_index"],
                },
            )
        )
    attention = summary.get("attention") or {}
    for item in attention.get("items", [])[:3]:
        facts.append(
            ForecastDomainFact(
                capability_id="project.attention_digest.v1",
                subject=item["key"],
                title=item["title"],
                summary=item["summary"],
                source=item,
                scope_label="原工作台的待决事项；未检查的内容不视为正常",
                target={"page": "today"},
            )
        )
    if focus.explicit_instruction:
        facts.append(
            ForecastDomainFact(
                capability_id="project.author_task_candidate.v1",
                subject="author_instruction",
                title="把明确安排留待稍后处理",
                summary=focus.explicit_instruction,
                source={
                    "instruction": focus.explicit_instruction,
                    "author_tasks": summary.get("author_tasks"),
                },
                scope_label="本次明确输入；点击并确认后才创建待办",
                target={"page": "today"},
            )
        )
    return facts
