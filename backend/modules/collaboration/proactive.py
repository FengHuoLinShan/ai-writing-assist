"""Follow explicit source grants; keep one authoritative run and cumulative budget."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select

from core.config import get_settings
from core.container import get
from core.errors import ConflictError, DomainError
from infrastructure.llm.collaboration import content_hash
from modules.collaboration.cases import require_case
from modules.collaboration.contracts import Grant, ResourceRef, RunCreate
from modules.collaboration.models import CollaborationCase, CollaborationRun
from modules.writing.facade import (
    get_draft,
    get_latest_draft_for_chapter,
    list_drafts_by_ids,
)


async def changed_cases(db, novel_id, case_ids, kind, identity):
    kind = {"outline_scene": "scene", "world_bible_draft": "world_bible_draft"}.get(
        kind, kind
    )
    rows = (
        await db.scalars(
            select(CollaborationCase).where(
                CollaborationCase.novel_id == UUID(novel_id),
                CollaborationCase.id.in_([UUID(value) for value in case_ids]),
                CollaborationCase.status == "active",
            )
        )
    ).all()
    ports = get("collaboration.resources")
    if kind not in ports:
        return []
    current = (
        await get_draft(db, novel_id, str(identity)) if kind == "writing_draft" else None
    )
    if current:
        current = await get_latest_draft_for_chapter(db, novel_id, current.chapter_index)
    try:
        source_hash = (
            current.content_hash
            if current
            else (
                await ports[kind].read(db, novel_id, ResourceRef(kind=kind, id=identity))
            ).source_hash
        )
    except DomainError:
        source_hash = "unavailable"
    ids = {
        ref["id"]
        for row in rows
        for ref in [*row.grant_json["resources"], *row.grant_json.get("excluded", [])]
        if ref["kind"] == "writing_draft"
    }
    chapters = (
        {
            str(value.id): value.chapter_index
            for value in await list_drafts_by_ids(db, novel_id, list(ids))
        }
        if ids
        else {}
    )
    result = []
    for row in rows:
        grant = Grant.model_validate(row.grant_json)
        if (
            not grant.follow_changes
            or grant.expires_at <= datetime.now(UTC)
            or row.requests_used + 4 > grant.request_limit
        ):
            continue
        if any(
            str(ref.id) == str(identity)
            or current
            and ref.kind == "writing_draft"
            and chapters.get(str(ref.id)) == current.chapter_index
            for ref in grant.excluded
        ):
            continue
        matched = any(
            ref.kind == kind
            and (
                str(ref.id) == str(identity)
                or kind == "writing_draft"
                and current
                and chapters.get(str(ref.id)) == current.chapter_index
            )
            for ref in grant.resources
        )
        if matched or grant.read_scope == "project" and kind in grant.read_kinds:
            if (
                current
                and grant.cutoff_chapter
                and current.chapter_index > grant.cutoff_chapter
            ):
                continue
            result.append(
                {
                    "case_id": str(row.id),
                    "source_hash": content_hash(
                        [
                            kind,
                            current.chapter_index if current else str(identity),
                            source_hash,
                        ]
                    ),
                }
            )
    return result


async def submit_changed_case(db, novel_id, case_id):
    from modules.collaboration.cases import submit_run

    case = await require_case(db, novel_id, case_id, lock=True, execute=True)
    grant = Grant.model_validate(case.grant_json)
    if not grant.follow_changes or not get_settings().collaboration_v2_enabled:
        raise ConflictError("自动跟进授权已关闭", code="GRANT_CHANGED")
    active = await db.scalar(
        select(CollaborationRun.id).where(
            CollaborationRun.case_id == case.id,
            CollaborationRun.novel_id == case.novel_id,
            CollaborationRun.status.in_(["pending", "running"]),
        )
    )
    if active:
        raise ConflictError("原目标仍在执行", code="ACTIVE_RUN_CONFLICT")
    refs = []
    for ref in grant.resources:
        if ref.kind == "writing_draft":
            before = await get_draft(db, novel_id, str(ref.id))
            if before is None:
                raise ConflictError("原资料已不可重新定位", code="SOURCE_STALE")
            latest = await get_latest_draft_for_chapter(
                db, novel_id, before.chapter_index
            )
            if latest is None:
                raise ConflictError("当前稿不可访问", code="SOURCE_STALE")
            refs.append(ResourceRef(kind=ref.kind, id=latest.id))
        else:
            refs.append(ref)
    renewed = grant.model_copy(update={"resources": refs})
    if renewed != grant:
        case.grant_history_json = [
            *(case.grant_history_json or []),
            {
                "grant": case.grant_json,
                "reason": "follow_authorized_logical_sources",
                "ended_at": datetime.now(UTC).isoformat(),
                "requests_used": case.requests_used,
            },
        ]
        case.grant_json = renewed.model_dump(mode="json")
    return await submit_run(
        db,
        novel_id,
        case_id,
        RunCreate(
            operation_id=uuid4(),
            expected_goal_version=case.goal_version,
            request="已授权资料有变化，核对与当前目标有关的直接影响，保留其他内容。",
        ),
        background=True,
    )
