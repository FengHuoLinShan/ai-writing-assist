"""Story owns open questions, conditional reactions and information windows."""

INSTRUCTIONS = {
    ("story.open_question.v1"): (
        "先找可回读的异常、未完成承诺或因果疑问，再给竞争解释。问题有依据不表示任何解释为真；普通遗物或情感细节不"
        "必变成秘密，也不要求回收。"
    ),
    ("story.character_response.v1"): (
        "只依据所提供的人物资料和已观察刺激提出动机不同的反应。资料缺失保持未知；性格不决定唯一行动，意图不等于成"
        "功事件。"
    ),
    "story.scene_transition.v1": (
        "考虑当前结果到下一场的最小过渡、直接切场或继"
        "续留白，不重排场景。没有下一场安排时给条件式"
        "选择。"
    ),
    ("story.information_window.v1"): (
        "结合已登记计划与当前可回读变化讨论轻量回应、发展或继续潜伏。不编造回收章号，不将唯一已知渠道当成唯一可能"
        "渠道。"
    ),
}


async def inspect(db, novel_id, focus, excluded):
    from uuid import UUID

    from sqlalchemy import select

    from modules.assistant.contracts import ForecastDomainFact
    from modules.story.facade import get_scene_story_assets
    from modules.story.outline_state.models import Scene

    if not focus.scene_id or excluded:
        return []
    scene = await db.scalar(
        select(Scene).where(Scene.novel_id == UUID(novel_id), Scene.id == focus.scene_id)
    )
    if scene is None:
        return []
    assets = await get_scene_story_assets(db, novel_id=novel_id, scene_id=str(scene.id))
    value = assets.model_dump(mode="json") if hasattr(assets, "model_dump") else assets
    return [
        ForecastDomainFact(
            capability_id="story.structure_impact.v1",
            subject=str(scene.id),
            title="场景调整后，先核对原文连接",
            summary="这些章节与场景片段是当前明确的结构连接；调整信息顺序前可逐处核对。",
            source={
                "scene_id": str(scene.id),
                "chapter_ids": scene.chapter_ids or [],
                "scene_chunks": scene.scene_chunks or [],
                "updated_at": str(scene.updated_at),
            },
            scope_label="当前场景的显式章节映射",
            unknowns=["未以相邻场景或文字相似推断因果，尚未复核调整后的读者信息顺序。"],
            target={"page": "scene", "scene_id": str(scene.id)},
        ),
        ForecastDomainFact(
            capability_id="writing.recall_pack.v1",
            subject=str(scene.id),
            title="本场已有剧本与人物卡",
            summary="已采用的场景资料可作为接续前的检查清单，仍需按本次写作范围确认。",
            source={"scene_id": str(scene.id), "assets": value},
            scope_label="当前场景采用的故事资料",
            target={"page": "scene", "scene_id": str(scene.id)},
        ),
    ]
