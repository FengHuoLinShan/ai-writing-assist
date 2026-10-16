"""Story-owned author plans and verified continuity comparison at one cutoff."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, text

from core.errors import ConflictError, NotFoundError, ValidationError
from infrastructure.llm.collaboration import content_hash
from modules.evidence.contracts import VisibilityContextContract
from modules.evidence.facade import read_novel_evidence, read_object_dossier_brief
from modules.project.facade import get_any_project_context, require_active_project
from modules.story.facade import get_scene_contract, get_scene_story_assets
from modules.story.models import CharacterArcPlanHead, CharacterArcPlanRevision
from modules.world.facade import get_characters_context
from modules.writing.facade import build_manuscript_range_ref

from .schemas import (
    ArcCutoffView,
    ArcEvidenceEvent,
    ArchiveArcPlanInput,
    ArcPlanPreviewResponse,
    ArcPlanRevisionView,
    ArcPlanView,
    ArcPlanWriteInput,
    CharacterArcComparisonResponse,
    RestoreArcPlanInput,
    SceneCharacterOption,
    SceneCharacterOptionsResponse,
)


def _dump(value):
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


def _chapter_indices(scene) -> list[int]:
    values = []
    for raw in scene.chapter_ids or []:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value > 0:
            values.append(value)
    return sorted(set(values))


def _summary_value(value):
    if isinstance(value, str):
        return value[:320]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return f"已记录 {len(value)} 项状态"
    if isinstance(value, dict):
        for key in ("label", "summary", "name", "title"):
            text = value.get(key)
            if isinstance(text, str) and text.strip():
                return text.strip()[:320]
        return f"已记录 {len(value)} 项结构化状态"
    return "状态已记录"


async def _owned_project(db, novel_id: str):
    await require_active_project(db, novel_id, allow_demo_readonly=False)
    project = await get_any_project_context(db, novel_id)
    if project is None or project.project_kind != "author":
        raise NotFoundError("作品不可访问")
    return project


async def _scene(db, novel_id: str, scene_id: str):
    scene = await get_scene_contract(db, novel_id, scene_id)
    if scene is None or scene.status not in {"draft", "canonical"}:
        raise NotFoundError("当前场景不可用于人物弧线对照")
    return scene


async def _scene_characters(db, novel_id: str, scene):
    assets = await get_scene_story_assets(db, novel_id=novel_id, scene_id=str(scene.id))
    value = _dump(assets)
    ids = {
        str(item.get("character_id"))
        for item in value.get("character_cards") or []
        if isinstance(item, dict) and item.get("character_id")
    }
    if scene.pov_character_id:
        ids.add(str(scene.pov_character_id))
    if not ids:
        return []
    context = await get_characters_context(
        db, novel_id, list(sorted(ids)), reveal_mode="character"
    )
    options = []
    for item in context.characters:
        character_id = str(item.character_id)
        if character_id not in ids:
            continue
        options.append(
            SceneCharacterOption(
                character_id=UUID(character_id),
                character_name=item.name,
                is_pov=character_id == str(scene.pov_character_id or ""),
            )
        )
    options.sort(
        key=lambda item: (not item.is_pov, item.character_name, str(item.character_id))
    )
    return options


async def scene_character_options(db, novel_id: str, scene_id: str):
    await _owned_project(db, novel_id)
    scene = await _scene(db, novel_id, scene_id)
    options = await _scene_characters(db, novel_id, scene)
    chapters = _chapter_indices(scene)
    gaps = []
    if not options:
        gaps.append("当前场景没有可核验的人物 POV 或已保存人物卡。")
    if not chapters:
        gaps.append("场景尚无章节映射，截止点可以查看计划，但不能声称正文事实已验证。")
    return SceneCharacterOptionsResponse(
        scene_id=UUID(str(scene.id)),
        scene_title=scene.title or "未命名场景",
        scene_index=scene.scene_index,
        chapter_indices=chapters,
        characters=options,
        gaps=gaps,
    )


async def _require_selected_character(db, novel_id: str, scene, character_id: str):
    options = await _scene_characters(db, novel_id, scene)
    chosen = next(
        (item for item in options if str(item.character_id) == character_id), None
    )
    if chosen is None:
        raise NotFoundError("人物不属于当前场景或已不可访问")
    return chosen


async def _head(db, novel_id: str, character_id: str, *, lock=False):
    query = select(CharacterArcPlanHead).where(
        CharacterArcPlanHead.novel_id == UUID(str(novel_id)),
        CharacterArcPlanHead.character_id == UUID(str(character_id)),
    )
    if lock:
        query = query.with_for_update()
    return await db.scalar(query.execution_options(populate_existing=True))


async def _lock_character_plan(db, novel_id: str, character_id: str) -> None:
    """Serialize the first write too, when no head row exists to lock."""
    bind = db.get_bind()
    if bind is None or bind.dialect.name != "postgresql":
        return
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"story.character_arc_plan:{novel_id}:{character_id}"},
    )


def _assert_owner(row, project):
    if row is not None and str(row.owner_id) != str(project.owner_id):
        raise NotFoundError("人物弧计划不可访问")


async def _revision(db, novel_id: str, revision_id: str, *, head_id=None):
    query = select(CharacterArcPlanRevision).where(
        CharacterArcPlanRevision.novel_id == UUID(str(novel_id)),
        CharacterArcPlanRevision.id == UUID(str(revision_id)),
    )
    if head_id is not None:
        query = query.where(CharacterArcPlanRevision.head_id == UUID(str(head_id)))
    return await db.scalar(query)


def _revision_view(revision):
    return ArcPlanRevisionView(
        revision_id=revision.id,
        version=revision.version_number,
        plan_text=revision.plan_text,
        content_hash=revision.content_hash,
        source=revision.source,
        audience=revision.audience,
        created_at=revision.created_at,
        restored_from_revision_id=revision.restored_from_revision_id,
    )


def _revision_plan_view(revision, character_name):
    return ArcPlanView(
        character_id=revision.character_id,
        character_name=character_name,
        version=revision.version_number,
        revision_id=revision.id,
        plan_text=revision.plan_text,
        content_hash=revision.content_hash,
        source=revision.source,
        audience=revision.audience,
        confirmed_by_owner=True,
        updated_at=revision.created_at,
    )


async def _plan_view(db, novel_id, head, character_name):
    if head is None or head.deleted_at is not None or head.current_revision_id is None:
        return None
    revision = await _revision(
        db, novel_id, str(head.current_revision_id), head_id=str(head.id)
    )
    if (
        revision is None
        or revision.character_id != head.character_id
        or revision.owner_id != head.owner_id
        or revision.version_number != head.version_number
    ):
        return None
    return _revision_plan_view(revision, character_name)


def _cutoff(scene):
    chapters = _chapter_indices(scene)
    chapter_cutoff = max(chapters) if chapters else None
    return ArcCutoffView(
        scene_id=UUID(str(scene.id)),
        scene_index=scene.scene_index,
        scene_title=scene.title or "未命名场景",
        chapter_indices=chapters,
        chapter_cutoff=chapter_cutoff,
        order_fingerprint=content_hash(
            {
                "scene_id": str(scene.id),
                "scene_index": scene.scene_index,
                "chapters": chapters,
            }
        ),
    )


async def _verified_event(db, novel_id, scene, chapter_cutoff, item):
    provenance = item.get("provenance") or {}
    if (
        item.get("layer") != "fact"
        or bool(item.get("possibly_false"))
        or provenance.get("status") != "exact"
    ):
        return None
    occurred_at = item.get("occurred_at")
    if not isinstance(occurred_at, dict):
        return None
    occurred_scene = occurred_at.get("scene_index")
    if type(occurred_scene) is not int or occurred_scene > scene.scene_index:
        return None
    refs = item.get("source_refs") or provenance.get("source_refs") or []
    for source in refs[:4]:
        if not isinstance(source, dict) or source.get("content_mode") != "canonical":
            continue
        try:
            source_chapter = int(source.get("chapter_index"))
            if chapter_cutoff is None or source_chapter > chapter_cutoff:
                continue
            start = int(source["start_offset"])
            end = int(source["end_offset"])
            if start < 0 or end <= start:
                continue
            draft_id = str(UUID(str(source["draft_id"])))
            source_hash = str(source["source_hash"])
            range_hash = str(source["range_hash"])
            version_number = int(source["version_number"])
            ref = await build_manuscript_range_ref(
                db,
                novel_id,
                draft_id=draft_id,
                start_offset=start,
                end_offset=end,
                content_mode="canonical",
            )
            if (
                ref.chapter_index != source_chapter
                or ref.version_number != version_number
                or ref.source_hash != source_hash
                or ref.range_hash != range_hash
            ):
                continue
            evidence = _dump(
                await read_novel_evidence(
                    db,
                    novel_id=novel_id,
                    source_ref=ref,
                    visibility=VisibilityContextContract(
                        mode="author", cutoff_chapter=chapter_cutoff
                    ),
                    before=0,
                    after=0,
                )
            )
            decision = evidence.get("visibility_decision") or {}
            actual_ref = evidence.get("source_ref") or {}
            if (
                evidence.get("degraded") is True
                or evidence.get("index_fresh") is not True
                or decision.get("mode") != "author"
                or decision.get("visible") is not True
                or str(actual_ref.get("draft_id")) != draft_id
                or actual_ref.get("chapter_index") != source_chapter
                or actual_ref.get("version_number") != version_number
                or actual_ref.get("content_mode") != "canonical"
                or actual_ref.get("start_offset") != start
                or actual_ref.get("end_offset") != end
                or actual_ref.get("source_hash") != source_hash
                or actual_ref.get("range_hash") != range_hash
            ):
                continue
            quote = str(evidence.get("text") or "").strip()
            if not quote:
                continue
            return ArcEvidenceEvent(
                field=str(item.get("field") or "人物状态"),
                value=_summary_value(item.get("value")),
                occurred_at=occurred_at,
                chapter_index=source_chapter,
                source_label=f"第 {source_chapter} 章正式正文",
                quote=quote[:1200],
                source_hash=source_hash,
                range_hash=range_hash,
            )
        except (KeyError, TypeError, ValueError, NotFoundError, ValidationError):
            continue
    return None


async def compare_character_arc(db, novel_id: str, scene_id: str, character_id: str):
    project = await _owned_project(db, novel_id)
    scene = await _scene(db, novel_id, scene_id)
    character = await _require_selected_character(db, novel_id, scene, character_id)
    brief = _dump(
        await read_object_dossier_brief(
            db,
            novel_id=novel_id,
            scene_id=str(scene.id),
            entity_ids=[str(character.character_id)],
            reveal_mode="author_full",
            content_mode="canonical",
            include_patterns=False,
        )
    )
    if str(brief.get("novel_id")) != str(novel_id) or str(brief.get("scene_id")) != str(
        scene.id
    ):
        raise NotFoundError("截止点证据不可访问")
    cutoff = _cutoff(scene)
    head = await _head(db, novel_id, str(character.character_id))
    _assert_owner(head, project)
    plan = await _plan_view(db, novel_id, head, character.character_name)
    unknowns = []
    if head is not None and head.deleted_at is not None:
        unknowns.append("作者人物弧计划已归档。")
    elif head is not None and plan is None:
        unknowns.append("人物弧当前修订指针与版本不一致，计划内容未展示。")
    elif plan is None:
        unknowns.append("尚无作者已确认的人物弧计划。")
    if cutoff.chapter_cutoff is None:
        unknowns.append("当前场景没有章节映射，不能核验正文中的实际经历。")
    coverage = brief.get("coverage", "unknown")
    if coverage != "complete":
        unknowns.append("截止 Scene 的人物状态资料覆盖不完整；缺失部分仍未知。")
    unknowns.extend(str(value) for value in brief.get("omissions") or [])
    unknown_layers = list(brief.get("unknown_layers") or [])
    if unknown_layers:
        unknowns.extend(f"{layer} 层资料未知或不完整。" for layer in unknown_layers)

    actual_events = []
    skipped_facts = 0
    if cutoff.chapter_cutoff is not None:
        for item in brief.get("continuity_items") or []:
            if not isinstance(item, dict):
                continue
            if item.get("layer") != "fact" or bool(item.get("possibly_false")):
                skipped_facts += 1
                continue
            verified = await _verified_event(
                db, novel_id, scene, cutoff.chapter_cutoff, item
            )
            if verified is None:
                skipped_facts += 1
            else:
                actual_events.append(verified)
            if len(actual_events) >= 60:
                unknowns.append("实际证据展示达到 60 条上限；其余记录未列出。")
                break
    if skipped_facts:
        unknowns.append(
            f"有 {skipped_facts} 条状态未满足已发生事实与正式正文来源核验，"
            "未列入实际经历。"
        )
    if not actual_events:
        unknowns.append("截止点没有可核验的正文连续性事实；不能据此判断人物弧是否完成。")
    unknowns = list(dict.fromkeys(unknowns))[:30]
    fingerprint = content_hash(
        {
            "character_id": str(character.character_id),
            "plan_revision": str(plan.revision_id) if plan else None,
            "plan_hash": plan.content_hash if plan else None,
            "cutoff": cutoff.model_dump(mode="json"),
            "brief_fingerprint": brief.get("fingerprint"),
            "continuity_fingerprint": brief.get("continuity_fingerprint"),
            "events": [event.model_dump(mode="json") for event in actual_events],
            "coverage": coverage,
            "unknowns": unknowns,
        }
    )
    return CharacterArcComparisonResponse(
        character_id=character.character_id,
        character_name=character.character_name,
        plan=plan,
        plan_archived=bool(head and head.deleted_at is not None),
        cutoff=cutoff,
        actual_events=actual_events,
        unknowns=unknowns,
        coverage=coverage
        if coverage in {"complete", "partial", "unknown"}
        else "unknown",
        comparison_basis_fingerprint=fingerprint,
    )


async def _validated_plan_target(db, novel_id, scene_id, character_id):
    scene = await _scene(db, novel_id, scene_id)
    character = await _require_selected_character(db, novel_id, scene, character_id)
    return scene, character


async def preview_plan_save(db, novel_id: str, data: ArcPlanWriteInput):
    project = await _owned_project(db, novel_id)
    scene, character = await _validated_plan_target(
        db, novel_id, str(data.scene_id), str(data.character_id)
    )
    request_hash = content_hash(
        [
            str(data.scene_id),
            str(data.character_id),
            data.expected_version,
            data.plan_text,
        ]
    )
    prior = await db.scalar(
        select(CharacterArcPlanRevision).where(
            CharacterArcPlanRevision.novel_id == UUID(str(novel_id)),
            CharacterArcPlanRevision.character_id == data.character_id,
            CharacterArcPlanRevision.operation_id == data.operation_id,
        )
    )
    if prior is not None:
        if str(prior.owner_id) != str(project.owner_id):
            raise NotFoundError("人物弧计划不可访问")
        if prior.request_hash != request_hash or prior.source != "author_confirmed":
            raise ConflictError(
                "操作标识已用于另一份人物弧计划", code="OPERATION_MISMATCH"
            )
        base = (
            await _revision(
                db, novel_id, str(prior.base_revision_id), head_id=str(prior.head_id)
            )
            if prior.base_revision_id
            else None
        )
        fingerprint = content_hash(
            {
                "novel_id": str(novel_id),
                "scene_id": str(scene.id),
                "character_id": str(character.character_id),
                "expected_version": data.expected_version,
                "current_revision_id": str(base.id) if base else None,
                "current_hash": base.content_hash if base else None,
                "proposed_hash": prior.content_hash,
            }
        )
        return ArcPlanPreviewResponse(
            scene_id=scene.id,
            character_id=character.character_id,
            character_name=character.character_name,
            expected_version=data.expected_version,
            current_version=data.expected_version,
            preview_fingerprint=fingerprint,
            current_plan_text=base.plan_text if base else None,
            proposed_plan_text=prior.plan_text,
            effect="该确认请求已成功写入；重试将返回原版本，不会新增修订。",
        )
    head = await _head(db, novel_id, str(character.character_id))
    _assert_owner(head, project)
    if head is not None and head.deleted_at is not None:
        raise NotFoundError("人物弧计划已归档，请先恢复")
    current_version = head.version_number if head else 0
    if current_version != data.expected_version:
        raise ConflictError(
            "人物弧计划版本已变化，请重新读取后再预览",
            code="STALE_VERSION",
            context={"current_version": current_version},
        )
    current = (
        await _revision(db, novel_id, str(head.current_revision_id), head_id=str(head.id))
        if head and head.current_revision_id
        else None
    )
    fingerprint = content_hash(
        {
            "novel_id": str(novel_id),
            "scene_id": str(scene.id),
            "character_id": str(character.character_id),
            "expected_version": data.expected_version,
            "current_revision_id": str(current.id) if current else None,
            "current_hash": current.content_hash if current else None,
            "proposed_hash": content_hash(data.plan_text),
        }
    )
    return ArcPlanPreviewResponse(
        scene_id=scene.id,
        character_id=character.character_id,
        character_name=character.character_name,
        expected_version=data.expected_version,
        current_version=current_version,
        preview_fingerprint=fingerprint,
        current_plan_text=current.plan_text if current else None,
        proposed_plan_text=data.plan_text,
        effect="保存为作者确认、仅供导演使用的人物弧计划修订；不会写入正文或人物已知状态。",
    )


async def save_plan(db, novel_id: str, data: ArcPlanWriteInput, preview_fingerprint: str):
    project = await _owned_project(db, novel_id)
    _scene, character = await _validated_plan_target(
        db, novel_id, str(data.scene_id), str(data.character_id)
    )
    await _lock_character_plan(db, novel_id, str(data.character_id))
    request_hash = content_hash(
        [
            str(data.scene_id),
            str(data.character_id),
            data.expected_version,
            data.plan_text,
        ]
    )
    prior = await db.scalar(
        select(CharacterArcPlanRevision).where(
            CharacterArcPlanRevision.novel_id == UUID(str(novel_id)),
            CharacterArcPlanRevision.character_id == data.character_id,
            CharacterArcPlanRevision.operation_id == data.operation_id,
        )
    )
    if prior is not None:
        if str(prior.owner_id) != str(project.owner_id):
            raise NotFoundError("人物弧计划不可访问")
        if prior.request_hash != request_hash:
            raise ConflictError(
                "操作标识已用于另一份人物弧计划", code="OPERATION_MISMATCH"
            )
        return _revision_plan_view(prior, character.character_name)

    preview = await preview_plan_save(db, novel_id, data)
    if not preview_fingerprint or preview.preview_fingerprint != preview_fingerprint:
        raise ConflictError("预览内容或当前版本已变化，请重新预览", code="PREVIEW_STALE")

    head = await _head(db, novel_id, str(data.character_id), lock=True)
    _assert_owner(head, project)
    current_version = head.version_number if head else 0
    if head is not None and head.deleted_at is not None:
        raise NotFoundError("人物弧计划已归档，请先恢复")
    if current_version != data.expected_version:
        raise ConflictError(
            "人物弧计划版本已变化，请重新读取后再预览",
            code="STALE_VERSION",
            context={"current_version": current_version},
        )
    if head is None:
        head = CharacterArcPlanHead(
            novel_id=UUID(str(novel_id)),
            character_id=data.character_id,
            owner_id=UUID(str(project.owner_id)),
            version_number=0,
            current_revision_id=None,
        )
        db.add(head)
        await db.flush()
    revision = CharacterArcPlanRevision(
        novel_id=UUID(str(novel_id)),
        head_id=head.id,
        character_id=data.character_id,
        owner_id=UUID(str(project.owner_id)),
        version_number=current_version + 1,
        plan_text=data.plan_text,
        source="author_confirmed",
        audience="director_only",
        operation_id=data.operation_id,
        request_hash=request_hash,
        content_hash=content_hash(data.plan_text),
        base_revision_id=head.current_revision_id,
        restored_from_revision_id=None,
    )
    db.add(revision)
    await db.flush()
    head.current_revision_id = revision.id
    head.version_number = revision.version_number
    await db.flush()
    character = await _require_selected_character(
        db, novel_id, _scene, str(data.character_id)
    )
    return await _plan_view(db, novel_id, head, character.character_name)


async def plan_history(db, novel_id: str, scene_id: str, character_id: str):
    project = await _owned_project(db, novel_id)
    scene, character = await _validated_plan_target(db, novel_id, scene_id, character_id)
    head = await _head(db, novel_id, character_id)
    _assert_owner(head, project)
    if head is None:
        return {
            "character_id": character.character_id,
            "character_name": character.character_name,
            "deleted": False,
            "items": [],
        }
    revisions = (
        await db.scalars(
            select(CharacterArcPlanRevision)
            .where(
                CharacterArcPlanRevision.novel_id == UUID(str(novel_id)),
                CharacterArcPlanRevision.head_id == head.id,
            )
            .order_by(CharacterArcPlanRevision.version_number.desc())
            .limit(50)
        )
    ).all()
    return {
        "character_id": character.character_id,
        "character_name": character.character_name,
        "deleted": head.deleted_at is not None,
        "current_version": head.version_number,
        "items": [_revision_view(item).model_dump(mode="json") for item in revisions],
    }


async def restore_revision(db, novel_id: str, data: RestoreArcPlanInput):
    project = await _owned_project(db, novel_id)
    scene, character = await _validated_plan_target(
        db, novel_id, str(data.scene_id), str(data.character_id)
    )
    await _lock_character_plan(db, novel_id, str(data.character_id))
    request_hash = content_hash(
        [
            str(data.scene_id),
            str(data.character_id),
            str(data.revision_id),
            data.expected_version,
        ]
    )
    prior = await db.scalar(
        select(CharacterArcPlanRevision).where(
            CharacterArcPlanRevision.novel_id == UUID(str(novel_id)),
            CharacterArcPlanRevision.character_id == data.character_id,
            CharacterArcPlanRevision.operation_id == data.operation_id,
        )
    )
    if prior is not None:
        if str(prior.owner_id) != str(project.owner_id):
            raise NotFoundError("人物弧计划不可访问")
        if prior.request_hash != request_hash:
            raise ConflictError("操作标识已用于另一份恢复请求", code="OPERATION_MISMATCH")
        return _revision_plan_view(prior, character.character_name)
    head = await _head(db, novel_id, str(data.character_id), lock=True)
    _assert_owner(head, project)
    if head is None or head.deleted_at is not None:
        raise NotFoundError("人物弧计划不存在或已归档")
    if head.version_number != data.expected_version:
        raise ConflictError(
            "人物弧计划版本已变化，请刷新历史后再恢复",
            code="STALE_VERSION",
            context={"current_version": head.version_number},
        )
    target = await _revision(db, novel_id, str(data.revision_id), head_id=str(head.id))
    if target is None or target.source == "author_archive":
        raise NotFoundError("人物弧历史版本不可访问")
    revision = CharacterArcPlanRevision(
        novel_id=UUID(str(novel_id)),
        head_id=head.id,
        character_id=data.character_id,
        owner_id=UUID(str(project.owner_id)),
        version_number=head.version_number + 1,
        plan_text=target.plan_text,
        source="author_restore",
        audience="director_only",
        operation_id=data.operation_id,
        request_hash=request_hash,
        content_hash=target.content_hash,
        base_revision_id=head.current_revision_id,
        restored_from_revision_id=target.id,
    )
    db.add(revision)
    await db.flush()
    head.current_revision_id = revision.id
    head.version_number = revision.version_number
    await db.flush()
    return await _plan_view(db, novel_id, head, character.character_name)


async def archive_plan(db, novel_id: str, data: ArchiveArcPlanInput):
    project = await _owned_project(db, novel_id)
    scene, character = await _validated_plan_target(
        db, novel_id, str(data.scene_id), str(data.character_id)
    )
    await _lock_character_plan(db, novel_id, str(data.character_id))
    request_hash = content_hash(
        [str(data.scene_id), str(data.character_id), data.expected_version, "archive"]
    )
    prior = await db.scalar(
        select(CharacterArcPlanRevision).where(
            CharacterArcPlanRevision.novel_id == UUID(str(novel_id)),
            CharacterArcPlanRevision.character_id == data.character_id,
            CharacterArcPlanRevision.operation_id == data.operation_id,
        )
    )
    if prior is not None:
        if str(prior.owner_id) != str(project.owner_id):
            raise NotFoundError("人物弧计划不可访问")
        if prior.request_hash != request_hash or prior.source != "author_archive":
            raise ConflictError(
                "操作标识已用于另一项人物弧操作", code="OPERATION_MISMATCH"
            )
        return {
            "character_id": character.character_id,
            "deleted": True,
            "version": prior.version_number,
            "revision_id": prior.id,
        }
    head = await _head(db, novel_id, str(data.character_id), lock=True)
    _assert_owner(head, project)
    if head is None or head.deleted_at is not None:
        raise NotFoundError("人物弧计划不存在或已归档")
    if head.version_number != data.expected_version:
        raise ConflictError(
            "人物弧计划版本已变化，请刷新后再归档",
            code="STALE_VERSION",
            context={"current_version": head.version_number},
        )
    current = await _revision(
        db, novel_id, str(head.current_revision_id), head_id=str(head.id)
    )
    if current is None or current.source == "author_archive":
        raise NotFoundError("人物弧计划当前版本不可访问")
    revision = CharacterArcPlanRevision(
        novel_id=UUID(str(novel_id)),
        head_id=head.id,
        character_id=data.character_id,
        owner_id=UUID(str(project.owner_id)),
        version_number=head.version_number + 1,
        plan_text=current.plan_text,
        source="author_archive",
        audience="director_only",
        operation_id=data.operation_id,
        request_hash=request_hash,
        content_hash=current.content_hash,
        base_revision_id=current.id,
        restored_from_revision_id=None,
    )
    db.add(revision)
    await db.flush()
    head.current_revision_id = revision.id
    head.version_number = revision.version_number
    head.deleted_at = datetime.now(UTC)
    head.deleted_by = UUID(str(project.owner_id))
    await db.flush()
    return {
        "character_id": character.character_id,
        "deleted": True,
        "version": head.version_number,
        "revision_id": revision.id,
    }


async def unarchive_plan(db, novel_id: str, data: ArchiveArcPlanInput):
    project = await _owned_project(db, novel_id)
    scene, character = await _validated_plan_target(
        db, novel_id, str(data.scene_id), str(data.character_id)
    )
    await _lock_character_plan(db, novel_id, str(data.character_id))
    request_hash = content_hash(
        [str(data.scene_id), str(data.character_id), data.expected_version, "unarchive"]
    )
    prior = await db.scalar(
        select(CharacterArcPlanRevision).where(
            CharacterArcPlanRevision.novel_id == UUID(str(novel_id)),
            CharacterArcPlanRevision.character_id == data.character_id,
            CharacterArcPlanRevision.operation_id == data.operation_id,
        )
    )
    if prior is not None:
        if str(prior.owner_id) != str(project.owner_id):
            raise NotFoundError("人物弧计划不可访问")
        if prior.request_hash != request_hash or prior.source != "author_unarchive":
            raise ConflictError(
                "操作标识已用于另一项人物弧操作", code="OPERATION_MISMATCH"
            )
        return _revision_plan_view(prior, character.character_name)
    head = await _head(db, novel_id, str(data.character_id), lock=True)
    _assert_owner(head, project)
    if head is None or head.deleted_at is None:
        raise NotFoundError("已归档人物弧计划不存在")
    if head.version_number != data.expected_version:
        raise ConflictError(
            "人物弧计划版本已变化，请刷新后再恢复",
            code="STALE_VERSION",
            context={"current_version": head.version_number},
        )
    current = await _revision(
        db, novel_id, str(head.current_revision_id), head_id=str(head.id)
    )
    if current is None or current.source != "author_archive":
        raise NotFoundError("归档中的人物弧计划当前版本不可访问")
    revision = CharacterArcPlanRevision(
        novel_id=UUID(str(novel_id)),
        head_id=head.id,
        character_id=data.character_id,
        owner_id=UUID(str(project.owner_id)),
        version_number=head.version_number + 1,
        plan_text=current.plan_text,
        source="author_unarchive",
        audience="director_only",
        operation_id=data.operation_id,
        request_hash=request_hash,
        content_hash=current.content_hash,
        base_revision_id=current.id,
        restored_from_revision_id=None,
    )
    db.add(revision)
    await db.flush()
    head.current_revision_id = revision.id
    head.version_number = revision.version_number
    head.deleted_at = None
    head.deleted_by = None
    await db.flush()
    return await _plan_view(db, novel_id, head, character.character_name)
