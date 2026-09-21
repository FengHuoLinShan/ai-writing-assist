"""World owns rule decisions and relationship consequences, without adoption."""

INSTRUCTIONS = {
    "world.rule_decision.v1": (
        "只提出影响当前规则使用的一项必要决定；条件、"
        "代价、例外未知时列为未知，不强制补制度百科。"
    ),
    "world.relationship_effect.v1": (
        "区分已采用关系与一次会面或陈述；按当前证据给"
        "出合作、交易或对白的条件式后果，不自动建立长"
        "期关系。"
    ),
}


async def prepare_direction(db, novel_id, ctx, direction):
    from core.errors import ValidationError
    from modules.world.services.worldbuilding.world_bible_lifecycle_service import (
        WorldBibleLifecycleService,
    )

    target = ctx.focus.target
    if not target or target.resource_kind not in {
        "world_bible_draft",
        "world_bible_page",
    }:
        raise ValidationError("请先选择要保存方案的世界资料工作稿")
    service = WorldBibleLifecycleService()
    value = (
        await service.get_draft(db, novel_id, str(target.resource_id))
        if target.resource_kind == "world_bible_draft"
        else await service.get_page_model(db, novel_id, str(target.resource_id))
    )
    return "world.edit_page_draft", {
        "draft_id" if target.resource_kind == "world_bible_draft" else "page_id": str(
            target.resource_id
        ),
        "free_text": (value.free_text or "")
        + "\n\n待核对的局部方案（未发布）：\n"
        + direction["proposal"],
    }


async def inspect(db, novel_id, focus, excluded):
    from dataclasses import asdict
    from uuid import UUID

    from sqlalchemy import select

    from infrastructure.llm.collaboration import content_hash
    from modules.assistant.contracts import ForecastDomainFact
    from modules.world.attention_facade import get_author_attention_summary
    from modules.world.map_atlas_models import MapAtlasNode, MapAtlasRevision
    from modules.world.services.worldbuilding.world_impact_service import (
        WorldImpactService,
    )

    if focus.page not in {"world", "map", "assistant"} or excluded:
        return []
    facts = []
    target = focus.target
    impact_target = target
    if target and target.resource_kind == "world_bible_draft":
        from modules.world.models import WorldBiblePageDraft

        draft = await db.scalar(
            select(WorldBiblePageDraft).where(
                WorldBiblePageDraft.novel_id == UUID(novel_id),
                WorldBiblePageDraft.id == target.resource_id,
            )
        )
        if draft and draft.page_id:
            impact_target = target.model_copy(
                update={"resource_kind": "world_bible_page", "resource_id": draft.page_id}
            )
    if impact_target and impact_target.resource_kind in {
        "world_bible_page",
        "core_entity",
    }:
        preview = (
            await WorldImpactService().preview(
                db,
                novel_id,
                target_type=impact_target.resource_kind,
                target_id=str(impact_target.resource_id),
            )
        ).model_dump(mode="json")
        facts.append(
            ForecastDomainFact(
                capability_id="world.rule_impact.v1",
                subject=str(target.resource_id),
                title="先核对这些明确引用",
                summary="原影响清单区分显式引用、文字提及与未覆盖范围；可以从这里逐域核对。",
                source=preview,
                scope_label="原世界影响服务的实际枚举范围",
                target={"page": "world", "target_id": str(target.resource_id)},
                unknowns=["这是引用影响清单，不是语义因果证明；修改范围仍由作者决定。"],
            )
        )
    if target and target.resource_kind == "map_atlas_node":
        row = (
            await db.execute(
                select(MapAtlasNode, MapAtlasRevision)
                .join(
                    MapAtlasRevision,
                    (MapAtlasNode.current_revision_id == MapAtlasRevision.id)
                    & (MapAtlasNode.novel_id == MapAtlasRevision.novel_id),
                )
                .where(
                    MapAtlasNode.novel_id == UUID(novel_id),
                    MapAtlasNode.id == target.resource_id,
                )
            )
        ).first()
        if row:
            node, revision = row
            document = revision.document or {}
            facts.append(
                ForecastDomainFact(
                    capability_id="world.map_precondition.v1",
                    subject=str(node.id),
                    title="路线先核对通行条件",
                    summary="先按当前保存地图核对距离、移动方式、耗时和进入条件；未标明的条件保持待定。",
                    source={
                        "node": str(node.id),
                        "status": node.status,
                        "revision": str(revision.id),
                        "document_hash": content_hash(document),
                        "constraints": document.get("constraints", []),
                        "features": document.get("features", []),
                    },
                    scope_label="当前保存地图的结构约束；未从图片像素推算距离",
                    unknowns=["没有距离、速度或道路条件时，不承诺到达时间。"],
                    target={"page": "map", "node_id": str(node.id)},
                )
            )
    if focus.page == "world":
        summary = await get_author_attention_summary(db, novel_id)
        for item in summary.items[:3]:
            source = asdict(item)
            source["updated_at"] = str(source["updated_at"])
            facts.append(
                ForecastDomainFact(
                    capability_id="world.asset_review_priority.v1",
                    subject=item.key,
                    title=item.title,
                    summary=item.summary,
                    source=source,
                    scope_label="原世界待决队列的前三项；完整列表在原页面",
                    target={"page": "world", "target_id": item.item_id},
                )
            )
    return facts
