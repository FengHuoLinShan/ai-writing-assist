"""Change-scoped checks of existing Story revision/staleness projections."""

import hashlib
import json
from uuid import UUID

from sqlalchemy import select

from core.errors import ConflictError
from infrastructure.tasks.facade import enqueue_task
from modules.project.facade import require_active_project
from modules.story.models import SceneScriptFile
from modules.story.outline_state.models import (
    ForeshadowingPlan,
    OutlineArc,
    PlotThread,
    RevealPlan,
    Scene,
    SceneChapterLink,
    StoryOutlineHead,
)
from modules.story.service import StoryService


async def changed(db, novel_id, scene_id, *, asset_type="scene_story_assets"):
    from core.container import get

    try:
        observer = get("source.changed")
    except KeyError:
        return
    await observer(db, str(novel_id), asset_type, str(scene_id))


async def _snapshot(db, novel_id, change, excluded):
    await require_active_project(db, novel_id)
    nid, asset = UUID(novel_id), UUID(change["asset_id"])
    excluded_ids = {value.rsplit(":", 1)[-1] for value in excluded}
    if str(asset) in excluded_ids:
        raise ConflictError("结构检查对象已被排除")
    kind = change["asset_type"]
    root_version = None
    omissions = []
    if kind == "story_outline":
        head = await db.scalar(
            select(StoryOutlineHead).where(
                StoryOutlineHead.novel_id == nid, StoryOutlineHead.id == asset
            )
        )
        root_version = str(head.current_revision_id) if head else None
        scenes = list(
            (
                await db.scalars(
                    select(SceneScriptFile.scene_id)
                    .where(
                        SceneScriptFile.novel_id == nid,
                        SceneScriptFile.status != "deprecated",
                        SceneScriptFile.adopted_revision_id.is_not(None),
                    )
                    .distinct()
                    .order_by(SceneScriptFile.scene_id)
                    .limit(21)
                )
            ).all()
        )
    elif kind in {"foreshadowing_plan", "reveal_plan"}:
        from modules.story.information_dependencies import affected_structure_scenes

        model = ForeshadowingPlan if kind == "foreshadowing_plan" else RevealPlan
        root = await db.scalar(
            select(model).where(model.novel_id == nid, model.id == asset)
        )
        root_version = str(root.updated_at) if root else None
        scenes = await affected_structure_scenes(db, nid, root) if root else []
        if not scenes:
            omissions.append("该信息计划没有明确的关联章节，未推测受影响的场景")
    elif kind in {"scene", "outline_scene", "scene_story_assets"}:
        scenes = [asset]
    elif kind in {"plot_thread", "outline_arc"}:
        model = PlotThread if kind == "plot_thread" else OutlineArc
        root = await db.scalar(
            select(model).where(model.novel_id == nid, model.id == asset)
        )
        if root is None:
            return {"scenes": [], "omissions": ["结构对象已经移除"], "root_version": None}
        start = root.start_chapter
        end = root.planned_payoff_chapter if kind == "plot_thread" else root.end_chapter
        root_version = str(root.updated_at)
        scenes = (
            list(
                (
                    await db.scalars(
                        select(SceneChapterLink.scene_id)
                        .where(
                            SceneChapterLink.novel_id == nid,
                            SceneChapterLink.chapter_index >= start,
                            *(
                                [SceneChapterLink.chapter_index <= end]
                                if end is not None
                                else []
                            ),
                        )
                        .distinct()
                        .order_by(SceneChapterLink.scene_id)
                        .limit(21)
                    )
                ).all()
            )
            if start is not None and (end is not None or kind == "plot_thread")
            else []
        )
        if not scenes:
            omissions.append("尚无明确的关联章节，未推测结构变化影响的场景")
    else:
        return {
            "scenes": [],
            "omissions": ["此结构范围需要从专业工作台检查"],
            "root_version": None,
        }
    scenes = sorted(
        set(scenes) | {UUID(value) for value in change.get("related_scene_ids", [])},
        key=str,
    )
    if change.get("related_overflow"):
        omissions.append("还有未列入本次检查的关联场景，请按范围继续检查")
    if len(scenes) > 20:
        omissions.append("本次只核对最多20个直接关联场景，其余需要按范围继续检查")
    result = []
    for scene_id in scenes[:20]:
        if str(scene_id) in excluded_ids:
            continue
        scene = await db.scalar(
            select(Scene).where(
                Scene.novel_id == nid, Scene.id == scene_id, Scene.status != "deprecated"
            )
        )
        if scene is None:
            continue
        assets = await StoryService().get_scene_story_assets(
            db, novel_id=novel_id, scene_id=str(scene_id)
        )
        stale = [
            {
                "id": item["id"],
                "title": item["title"],
                "basis_hash": item["basis_hash"],
                "expected_basis_hash": item["expected_basis_hash"],
            }
            for item in assets["adopted_scripts"]
            if item.get("stale") and item["id"] not in excluded_ids
        ]
        result.append(
            {
                "scene_id": str(scene_id),
                "title": scene.title,
                "story_context_hash": assets["story_context_hash"],
                "stale_scripts": stale,
                "information_plan_review": [
                    {"id": item["id"], "title": item["title"]}
                    for item in assets["adopted_scripts"]
                ]
                if kind in {"foreshadowing_plan", "reveal_plan"}
                else [],
            }
        )
    return {"scenes": result, "omissions": omissions, "root_version": root_version}


def _hash(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


async def schedule_proactive_review(db, novel_id, change, internal_meta):
    excluded = internal_meta["_assistant_policy"].get("excluded_targets", [])
    material = await _snapshot(db, novel_id, change, excluded)
    task_id = enqueue_task(
        db,
        "story_reference_review",
        novel_id=novel_id,
        meta={
            **internal_meta,
            "change": change,
            "source_hash": _hash(material),
        },
    )
    await db.flush()
    target = {
        "type": "scene"
        if change["asset_type"] in {"scene", "outline_scene", "scene_story_assets"}
        else change["asset_type"],
        "id": change["asset_id"],
    }
    return {"task_id": task_id, "target": target, "label": "结构与剧本的引用检查"}


async def review_references(db, task):
    material = await _snapshot(
        db,
        str(task.novel_id),
        task.meta["change"],
        task.meta["_assistant_policy"].get("excluded_targets", []),
    )
    if _hash(material) != task.meta["source_hash"]:
        raise ConflictError("结构资料已变化，旧检查未使用")
    findings = []
    for scene in material["scenes"]:
        for script in scene["information_plan_review"]:
            findings.append(
                {
                    "kind": "reminder",
                    "code": "information_plan_changed",
                    "title": f"请对照新的信息安排核对 {script['title']}",
                    "description": "关联章节的信息计划已有变更，尚未判断剧本是否矛盾。",
                    "evidence": {"plan_version": material["root_version"]},
                    "location": {"scene_id": scene["scene_id"], "file_id": script["id"]},
                }
            )
        for script in scene["stale_scripts"]:
            findings.append(
                {
                    "kind": "reminder",
                    "code": "story_reference_stale",
                    "title": f"{script['title']} 的采用依据已变化",
                    "description": (
                        "相关场景、人物卡或上游结构已有更新，请核对已采用剧本；"
                        "没有自动修改剧本或正文。"
                    ),
                    "evidence": {
                        "old": script["basis_hash"],
                        "current": script["expected_basis_hash"],
                    },
                    "location": {"scene_id": scene["scene_id"], "file_id": script["id"]},
                }
            )
    return {
        "findings": findings,
        "not_checked": [
            *material["omissions"],
            "只检查引用版本失效，不替代人物行为、因果或正文语义审稿",
        ],
        "source_hash": task.meta["source_hash"],
    }
