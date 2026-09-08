"""Bind the existing image workflow to an immutable spatial map version."""

from __future__ import annotations

import json

from sqlalchemy import select

from core.errors import ConflictError, ValidationError
from modules.evidence.facade import prepare_confirmed_ai_action
from modules.world.map_atlas_models import MapAtlasPage
from modules.world.map_structure_schemas import MapDocument
from modules.world.map_structure_service import MapStructureService
from modules.world.map_structure_workflow import confirmed_spatial_sources


async def validate_image_structure(db, run, page=None):
    snapshot = run.context_snapshot or {}
    revision_id = (
        page.source_map_revision_id if page else snapshot.get("source_map_revision_id")
    )
    node_id = str(page.node_id) if page else str(snapshot.get("target_node_id"))
    if not revision_id:
        return None
    confirmation_id = snapshot.get("context_confirmation_id")
    if not confirmation_id:
        raise ValidationError("结构引导生图缺少参考资料确认")
    novel_id = str(run.novel_id)
    service = MapStructureService()
    node = await service.node(db, novel_id, node_id)
    revision = await service.revision(db, novel_id, node_id, revision_id)
    if revision.status != "saved":
        raise ConflictError("图片来源地图尚未保存")
    prepared = await prepare_confirmed_ai_action(
        db,
        novel_id=novel_id,
        action="world.map_atlas.generate",
        confirmation_id=str(confirmation_id),
    )
    allowed = await confirmed_spatial_sources(db, novel_id, prepared)
    allowed_refs = {
        (
            item["ref"].kind,
            item["ref"].id,
            item["ref"].source_hash,
            json.dumps(item["ref"].source_ref, sort_keys=True),
        )
        for item in allowed.values()
    }
    document = MapDocument.model_validate(revision.document)
    for feature in document.features:
        if feature.entity_id and f"entity:{feature.entity_id}" not in allowed:
            raise ValidationError("地图包含未进入本次确认的地点，请调整地图或资料选择")
    for item in [*document.features, *document.constraints]:
        for ref in item.sources:
            identity = (
                ref.kind,
                ref.id,
                ref.source_hash,
                json.dumps(ref.source_ref, sort_keys=True),
            )
            if identity not in allowed_refs:
                raise ValidationError("地图包含未进入本次确认的来源，请重新核对参考资料")
            await service.source(db, novel_id, ref)
    if page and page.source_geometry_hash != revision.geometry_hash:
        raise ConflictError("图片绑定的空间指纹不一致")
    return node, revision, prepared


async def prepare_structure_image(db, task, run):
    from modules.world.map_atlas_workflow import _image_prompt, _require_attempt

    node, revision, prepared = await validate_image_structure(db, run)
    run = await _require_attempt(db, task, str(run.novel_id), str(run.id))
    existing = await db.scalar(
        select(MapAtlasPage).where(
            MapAtlasPage.novel_id == run.novel_id,
            MapAtlasPage.run_id == run.id,
            MapAtlasPage.node_id == node.id,
        )
    )
    if existing is None:
        document = MapDocument.model_validate(revision.document)
        refs = {
            ref.model_dump_json(): ref
            for item in [*document.features, *document.constraints]
            for ref in item.sources
        }
        page = MapAtlasPage(
            novel_id=run.novel_id,
            run_id=run.id,
            node_id=node.id,
            title=node.title,
            visual_brief="依据结构参考图表现地形与建筑；保留地点、道路、河流和区域的对应关系。空间未知处保持示意。",
            prompt="",
            evidence={
                "supported": [ref.quote for ref in refs.values() if ref.quote],
                "visual_fill": ["材质、光影与画风细节仅为视觉补全"],
                "conflicts": [],
            },
            source_manifest=[
                {
                    "source_type": ref.kind,
                    "title": "已确认空间资料",
                    "summary": ref.quote or "已确认地图引用",
                    "source_hash": ref.source_hash,
                    "source_status": "canonical",
                }
                for ref in refs.values()
            ],
            source_map_revision_id=revision.id,
            source_geometry_hash=revision.geometry_hash,
            generation_status="prepared",
            review_status="candidate",
            reference_page_ids=[],
        )
        page.prompt = _image_prompt(page, run.style_note or "清晰、克制的俯视地图")
        db.add(page)
    run.atlas_plan = {
        "style_brief": run.style_note or "清晰、克制的俯视地图",
        "structure_revision_id": str(revision.id),
    }
    run.planned_page_count = 1
    run.status = "prompt_review" if run.review_image_prompts else "generating"
    run.context_snapshot = {
        **run.context_snapshot,
        "compiled_context_fingerprint": prepared.confirmation.context_fingerprint,
    }
    await db.flush()
