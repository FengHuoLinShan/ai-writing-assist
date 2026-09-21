"""Read the existing import owner and exact review groups; never enqueue work."""

from core.errors import DomainError
from modules.assistant.contracts import ForecastDomainFact
from modules.imports.assistant_tools import read_organization_status
from modules.imports.review_resolution import review_summary


async def inspect(db, novel_id, focus, excluded):
    if focus.page != "imports" or excluded:
        return []
    receipt = await read_organization_status(db, novel_id)
    facts, decisions = [], {}
    from modules.imports.review_resolution import inspect_resolution

    for row in receipt["items"][:3]:
        if str(row["id"]) in excluded:
            continue
        common = dict(
            subject=row["id"],
            source=row,
            scope_label="原整理流程的范围、代次与当前恢复资格",
            target={"page": "imports", "task_id": row["task_id"]},
        )
        if row["recovery_required"] or row["status"] in {
            "failed",
            "cancelled",
            "interrupted",
        }:
            resumable = "resume" in row["available_actions"]
            facts.append(
                ForecastDomainFact(
                    capability_id="imports.recovery_next.v1",
                    title="先处理未完成的整理",
                    preparations=[
                        {
                            "action_id": "imports.prepare_resume",
                            "label": "预览继续原流程",
                            "capability": "imports.resume",
                            "arguments": {"task_id": row["task_id"]},
                        }
                    ]
                    if resumable
                    else [],
                    summary="可从原回执继续未完成的部分。"
                    if resumable
                    else "原流程当前没有恢复资格，请查看失败范围与已有成果。",
                    **common,
                )
            )
        if row["status"] in {"completed", "succeeded"}:
            try:
                detail = await inspect_resolution(
                    db, novel_id=novel_id, task_id=row["task_id"]
                )
            except DomainError:
                detail = None
            if detail:
                for value in detail["summary"].get("groups", []):
                    decisions.setdefault(value["key"], (row["task_id"], value))
            facts.append(
                ForecastDomainFact(
                    capability_id="imports.next_stage.v1",
                    title="这个整理阶段已有回执",
                    summary="可先审阅已有成果，再决定继续其他整理阶段或回到写作。不会重复启动已完成阶段。",
                    **common,
                )
            )
    summary = await review_summary(db, novel_id)
    candidates = summary["candidates"]
    # Preserve exact group keys and fingerprints; priority only affects presentation.
    scenes = {str(item["id"]): item for item in summary["scenes"]}
    for group in candidates[:3]:
        chapter = group.get("meta", {}).get("source_chapter_index")
        scene = scenes.get(str(group.get("meta", {}).get("scene_id")), {})
        chapters = [
            int(value) for value in scene.get("chapter_ids", []) if str(value).isdigit()
        ]
        if chapter:
            chapters.append(int(chapter))
        preparations = []
        if chapters:
            preparations.append(
                {
                    "action_id": "imports.prepare_resolution",
                    "label": "预览只查证这一组",
                    "capability": "imports.resolve_review",
                    "arguments": {
                        "start_chapter": min(chapters),
                        "end_chapter": max(chapters),
                        "asset_keys": [group["key"]],
                        "repair_scenes": False,
                    },
                }
            )
        decision = decisions.get(group["key"])
        if decision and decision[1].get("fingerprint") == group.get("fingerprint"):
            preparations.append(
                {
                    "action_id": "imports.prepare_acceptance",
                    "label": "预览采用这组具体结果",
                    "capability": "imports.accept_review",
                    "arguments": {
                        "task_id": decision[0],
                        "candidate_keys": [group["key"]],
                        "expected_fingerprints": {group["key"]: group["fingerprint"]},
                    },
                }
            )
        facts.append(
            ForecastDomainFact(
                capability_id="imports.review_bottleneck.v1",
                subject=group["key"],
                title="先核对这组待决资料",
                summary="这一组仍在原待决队列，先看来源与影响，再选择专项核对或原领域采用。",
                source={**group, "review_decision": decision},
                preparations=preparations,
                scope_label="原整理待决组；这里只展示前三组，完整队列仍在原页面",
                target={"page": "imports", "asset_key": group["key"]},
                unknowns=["待决不证明内容有误，未替代作者决定。"],
            )
        )
    return facts
