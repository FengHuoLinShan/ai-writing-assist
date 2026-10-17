"""Author-managed and model-emerged vocabulary with immutable snapshots."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, NotFoundError, ValidationError
from modules.project.facade import (
    require_active_project,
    require_active_project_exclusive,
)
from modules.world.project_vocabulary_models import (
    ProjectVocabularyRevision,
    ProjectVocabularyTerm,
)
from modules.world.project_vocabulary_presets import PRESETS, PresetItem
from modules.world.project_vocabulary_schemas import (
    ModelVocabularyProposal,
    ProjectVocabularyReadItem,
    ProjectVocabularyReadResponse,
    VocabularyEvidence,
    VocabularyMergeRequest,
    VocabularyPresetApplyResponse,
    VocabularyReviewReceipt,
    VocabularySplitRequest,
    VocabularyTermCreate,
    VocabularyTermFields,
    VocabularyTermResponse,
    VocabularyTermUpdate,
    normalize_vocabulary_key,
    vocabulary_evidence_hash,
    vocabulary_proposal_hash,
)
from shared.utils import parse_uuid

_TOMBSTONE_STATUSES = frozenset({"archived", "merged"})
_STATUS_ORDER = {"active": 0, "emerging": 1, "archived": 2, "merged": 3}


def _digest(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _field_snapshot(fields: VocabularyTermFields) -> dict[str, Any]:
    dumped = fields.model_dump(mode="json")
    payload = {key: dumped[key] for key in ("name", "description", "aliases", "traits")}
    normalized_seen = {normalize_vocabulary_key(payload["name"])}
    aliases: list[str] = []
    for alias in payload["aliases"]:
        key = normalize_vocabulary_key(alias)
        if key and key not in normalized_seen:
            normalized_seen.add(key)
            aliases.append(alias)
    payload["aliases"] = aliases
    return payload


def _keys_from_snapshot(snapshot: dict[str, Any]) -> set[str]:
    return {
        key
        for value in [snapshot.get("name", ""), *snapshot.get("aliases", [])]
        if (key := normalize_vocabulary_key(str(value)))
    }


async def _current_records(
    db: AsyncSession,
    novel_id: uuid.UUID,
    *,
    kind: str | None = None,
    ids: set[uuid.UUID] | None = None,
    lock: bool = False,
) -> list[tuple[ProjectVocabularyTerm, ProjectVocabularyRevision]]:
    statement = (
        select(ProjectVocabularyTerm, ProjectVocabularyRevision)
        .join(
            ProjectVocabularyRevision,
            and_(
                ProjectVocabularyRevision.novel_id == ProjectVocabularyTerm.novel_id,
                ProjectVocabularyRevision.id == ProjectVocabularyTerm.current_revision_id,
                ProjectVocabularyRevision.term_id == ProjectVocabularyTerm.id,
            ),
        )
        .where(ProjectVocabularyTerm.novel_id == novel_id)
    )
    if kind is not None:
        statement = statement.where(ProjectVocabularyTerm.kind == kind)
    if ids is not None:
        statement = statement.where(ProjectVocabularyTerm.id.in_(ids))
    if lock:
        statement = statement.with_for_update(of=ProjectVocabularyTerm)
    result = await db.execute(statement.execution_options(populate_existing=lock))
    return list(result.all())


async def _current_record(
    db: AsyncSession, novel_id: uuid.UUID, type_ref: uuid.UUID, *, lock: bool
) -> tuple[ProjectVocabularyTerm, ProjectVocabularyRevision]:
    statement = (
        select(ProjectVocabularyTerm, ProjectVocabularyRevision)
        .join(
            ProjectVocabularyRevision,
            and_(
                ProjectVocabularyRevision.novel_id == ProjectVocabularyTerm.novel_id,
                ProjectVocabularyRevision.id == ProjectVocabularyTerm.current_revision_id,
                ProjectVocabularyRevision.term_id == ProjectVocabularyTerm.id,
            ),
        )
        .where(
            ProjectVocabularyTerm.novel_id == novel_id,
            ProjectVocabularyTerm.id == type_ref,
        )
    )
    if lock:
        statement = statement.with_for_update(of=ProjectVocabularyTerm)
    row = (
        await db.execute(statement.execution_options(populate_existing=lock))
    ).one_or_none()
    if row is None:
        raise NotFoundError("项目词条不存在")
    return row


def _term_response(
    term: ProjectVocabularyTerm,
    revision: ProjectVocabularyRevision,
) -> VocabularyTermResponse:
    snapshot = revision.snapshot_json
    return VocabularyTermResponse.model_validate(
        {
            "id": term.id,
            "novel_id": term.novel_id,
            "kind": term.kind,
            "source": term.source,
            "status": term.status,
            "revision_id": revision.id,
            "revision_number": revision.revision_number,
            "previous_revision_id": revision.previous_revision_id,
            "name": snapshot["name"],
            "description": snapshot["description"],
            "aliases": snapshot["aliases"],
            "traits": snapshot["traits"],
            "content_hash": revision.content_hash,
            "author_confirmed": term.author_confirmed,
            "redirect_to_id": term.redirect_to_id,
            "preset_id": term.preset_id,
            "preset_version": term.preset_version,
            "preset_item_key": term.preset_item_key,
            "evidence": snapshot.get("evidence", []),
            "proposal_run_id": snapshot.get("proposal_run_id"),
        }
    )


def _read_item(
    term: ProjectVocabularyTerm,
    revision: ProjectVocabularyRevision,
) -> ProjectVocabularyReadItem:
    snapshot = revision.snapshot_json
    return ProjectVocabularyReadItem.model_validate(
        {
            "id": term.id,
            "kind": term.kind,
            "source": term.source,
            "status": term.status,
            "revision_id": revision.id,
            "revision_number": revision.revision_number,
            "name": snapshot["name"],
            "description": snapshot["description"],
            "aliases": snapshot["aliases"],
            "traits": snapshot["traits"],
            "content_hash": revision.content_hash,
            "redirect_to_id": term.redirect_to_id,
        }
    )


def _base_snapshot(
    fields: VocabularyTermFields,
    *,
    status: str,
    evidence: list[VocabularyEvidence] | None = None,
    independent_review: VocabularyReviewReceipt | None = None,
    proposal_run_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    snapshot = _field_snapshot(fields)
    evidence_items = evidence or []
    reviewed_evidence = (
        evidence_items
        if independent_review is not None
        and independent_review.verdict == "passed"
        and independent_review.evidence_hash == vocabulary_evidence_hash(evidence_items)
        else []
    )
    snapshot.update(
        {
            "status": status,
            "evidence": [item.model_dump(mode="json") for item in evidence_items],
            "reviewed_evidence": [
                item.model_dump(mode="json") for item in reviewed_evidence
            ],
            "independent_review": (
                independent_review.model_dump(mode="json")
                if independent_review is not None
                else None
            ),
            "proposal_run_id": str(proposal_run_id) if proposal_run_id else None,
        }
    )
    return snapshot


async def _create_term(
    db: AsyncSession,
    novel_id: uuid.UUID,
    kind: str,
    fields: VocabularyTermFields,
    *,
    source: str,
    status: str,
    author_confirmed: bool,
    change_reason: str,
    preset_id: str | None = None,
    preset_version: int | None = None,
    preset_item_key: str | None = None,
    evidence: list[VocabularyEvidence] | None = None,
    independent_review: VocabularyReviewReceipt | None = None,
    proposal_run_id: uuid.UUID | None = None,
) -> tuple[ProjectVocabularyTerm, ProjectVocabularyRevision]:
    term_id = uuid.uuid4()
    term = ProjectVocabularyTerm(
        id=term_id,
        novel_id=novel_id,
        kind=kind,
        source=source,
        status=status,
        current_revision_id=None,
        redirect_to_id=None,
        author_confirmed=author_confirmed,
        preset_id=preset_id,
        preset_version=preset_version,
        preset_item_key=preset_item_key,
    )
    db.add(term)
    await db.flush()
    snapshot = _base_snapshot(
        fields,
        status=status,
        evidence=evidence,
        independent_review=independent_review,
        proposal_run_id=proposal_run_id,
    )
    revision = ProjectVocabularyRevision(
        id=uuid.uuid4(),
        novel_id=novel_id,
        term_id=term_id,
        revision_number=1,
        previous_revision_id=None,
        snapshot_json=snapshot,
        content_hash=_digest(snapshot),
        change_reason=change_reason,
    )
    db.add(revision)
    term.current_revision_id = revision.id
    await db.flush()
    if (
        term.source == "model"
        and not term.author_confirmed
        and change_reason.startswith("model")
    ):
        from modules.world.map_notification_service import mark_map_changed

        await mark_map_changed(db, term.novel_id, "project_vocabulary_term", term.id)
    return term, revision


async def _append_revision(
    db: AsyncSession,
    term: ProjectVocabularyTerm,
    current: ProjectVocabularyRevision,
    snapshot: dict[str, Any],
    *,
    status: str,
    change_reason: str,
    redirect_to_id: uuid.UUID | None = None,
) -> tuple[ProjectVocabularyTerm, ProjectVocabularyRevision]:
    revision = ProjectVocabularyRevision(
        id=uuid.uuid4(),
        novel_id=term.novel_id,
        term_id=term.id,
        revision_number=current.revision_number + 1,
        previous_revision_id=current.id,
        snapshot_json=snapshot,
        content_hash=_digest(snapshot),
        change_reason=change_reason,
    )
    db.add(revision)
    term.current_revision_id = revision.id
    term.status = status
    term.redirect_to_id = redirect_to_id
    await db.flush()
    if (
        term.source == "model"
        and not term.author_confirmed
        and change_reason.startswith("model")
    ):
        from modules.world.map_notification_service import mark_map_changed

        await mark_map_changed(db, term.novel_id, "project_vocabulary_term", term.id)
    return term, revision


def _resolve_redirect(
    record: tuple[ProjectVocabularyTerm, ProjectVocabularyRevision],
    records: dict[uuid.UUID, tuple[ProjectVocabularyTerm, ProjectVocabularyRevision]],
) -> tuple[ProjectVocabularyTerm, ProjectVocabularyRevision]:
    seen: set[uuid.UUID] = set()
    kind = record[0].kind
    while record[0].status == "merged":
        term = record[0]
        if term.id in seen or term.redirect_to_id not in records:
            raise ConflictError("词条合并链无效，需由作者核对")
        seen.add(term.id)
        record = records[term.redirect_to_id]
        if record[0].kind != kind:
            raise ConflictError("词条合并链跨越词表种类")
    return record


async def _ensure_unique_keys(
    db: AsyncSession,
    novel_id: uuid.UUID,
    kind: str,
    snapshot: dict[str, Any],
    *,
    ignored_ids: set[uuid.UUID] | None = None,
) -> None:
    keys = _keys_from_snapshot(snapshot)
    if not keys:
        raise ValidationError("名称和别名至少需要一个可识别字符")
    ignored_ids = ignored_ids or set()
    rows = await _current_records(db, novel_id, kind=kind, lock=True)
    records = {term.id: (term, revision) for term, revision in rows}
    for term, revision in rows:
        resolved, _ = _resolve_redirect((term, revision), records)
        if term.id in ignored_ids or resolved.id in ignored_ids:
            continue
        if keys & _keys_from_snapshot(revision.snapshot_json):
            raise ConflictError("同一词表种类中已存在同名或等价别名")


async def create_project_vocabulary_term(
    db: AsyncSession, novel_id: str, data: VocabularyTermCreate
) -> VocabularyTermResponse:
    await require_active_project_exclusive(db, novel_id)
    novel_uuid = parse_uuid(novel_id, "novel_id")
    snapshot = _base_snapshot(data, status="active")
    await _ensure_unique_keys(db, novel_uuid, data.kind, snapshot)
    term, revision = await _create_term(
        db,
        novel_uuid,
        data.kind,
        data,
        source="author",
        status="active",
        author_confirmed=True,
        change_reason="author_created",
    )
    return _term_response(term, revision)


async def read_project_vocabulary(
    db: AsyncSession,
    novel_id: str,
    *,
    kind: str | None = None,
    limit: int = 100,
    include_archived: bool = True,
) -> ProjectVocabularyReadResponse:
    """Read a capped, deterministic list and report the exact omitted count."""
    await require_active_project(db, novel_id)
    if not 1 <= limit <= 500:
        raise ValidationError("词表读取上限必须在 1 到 500 之间")
    novel_uuid = parse_uuid(novel_id, "novel_id")
    rows = await _current_records(db, novel_uuid, kind=kind)
    if not include_archived:
        rows = [row for row in rows if row[0].status not in _TOMBSTONE_STATUSES]
    rows.sort(
        key=lambda row: (
            row[0].kind,
            _STATUS_ORDER.get(row[0].status, 99),
            normalize_vocabulary_key(row[1].snapshot_json["name"]),
            str(row[0].id),
        )
    )
    total_count = len(rows)
    selected = rows[:limit]
    return ProjectVocabularyReadResponse(
        items=[_read_item(term, revision) for term, revision in selected],
        total_count=total_count,
        omitted_count=total_count - len(selected),
    )


async def get_project_vocabulary_term(
    db: AsyncSession, novel_id: str, type_ref: str
) -> VocabularyTermResponse:
    await require_active_project(db, novel_id)
    novel_uuid = parse_uuid(novel_id, "novel_id")
    term_uuid = parse_uuid(type_ref, "type_ref")
    term, revision = await _current_record(db, novel_uuid, term_uuid, lock=False)
    return _term_response(term, revision)


async def get_project_vocabulary_term_revision(
    db: AsyncSession, novel_id: str, type_ref: str, revision_id: str
) -> VocabularyTermResponse:
    await require_active_project(db, novel_id)
    novel_uuid = parse_uuid(novel_id, "novel_id")
    term_uuid = parse_uuid(type_ref, "type_ref")
    revision_uuid = parse_uuid(revision_id, "revision_id")
    row = (
        await db.execute(
            select(ProjectVocabularyTerm, ProjectVocabularyRevision)
            .join(
                ProjectVocabularyRevision,
                and_(
                    ProjectVocabularyRevision.novel_id == ProjectVocabularyTerm.novel_id,
                    ProjectVocabularyRevision.term_id == ProjectVocabularyTerm.id,
                ),
            )
            .where(
                ProjectVocabularyTerm.novel_id == novel_uuid,
                ProjectVocabularyTerm.id == term_uuid,
                ProjectVocabularyRevision.novel_id == novel_uuid,
                ProjectVocabularyRevision.id == revision_uuid,
            )
        )
    ).one_or_none()
    if row is None:
        raise NotFoundError("项目词条修订不存在")
    return _term_response(*row)


async def update_project_vocabulary_term(
    db: AsyncSession,
    novel_id: str,
    type_ref: str,
    data: VocabularyTermUpdate,
) -> VocabularyTermResponse:
    await require_active_project_exclusive(db, novel_id)
    novel_uuid = parse_uuid(novel_id, "novel_id")
    term_uuid = parse_uuid(type_ref, "type_ref")
    term, current = await _current_record(db, novel_uuid, term_uuid, lock=True)
    if current.id != data.expected_revision_id:
        raise ConflictError("词条已在别处更新；请刷新后重试")
    if term.status in _TOMBSTONE_STATUSES:
        raise ConflictError("已归档或合并的词条需先恢复，不能直接编辑")
    snapshot = _base_snapshot(data, status="active")
    await _ensure_unique_keys(
        db,
        novel_uuid,
        term.kind,
        snapshot,
        ignored_ids={term.id},
    )
    snapshot["evidence"] = current.snapshot_json.get("evidence", [])
    snapshot["reviewed_evidence"] = current.snapshot_json.get("reviewed_evidence", [])
    snapshot["independent_review"] = current.snapshot_json.get("independent_review")
    snapshot["proposal_run_id"] = current.snapshot_json.get("proposal_run_id")
    term, revision = await _append_revision(
        db,
        term,
        current,
        snapshot,
        status="active",
        change_reason="author_updated",
    )
    term.author_confirmed = True
    await db.flush()
    return _term_response(term, revision)


async def archive_project_vocabulary_term(
    db: AsyncSession,
    novel_id: str,
    type_ref: str,
    expected_revision_id: uuid.UUID,
) -> VocabularyTermResponse:
    await require_active_project_exclusive(db, novel_id)
    novel_uuid = parse_uuid(novel_id, "novel_id")
    term_uuid = parse_uuid(type_ref, "type_ref")
    term, current = await _current_record(db, novel_uuid, term_uuid, lock=True)
    if current.id != expected_revision_id:
        raise ConflictError("词条已在别处更新；请刷新后重试")
    if term.status in _TOMBSTONE_STATUSES:
        raise ConflictError("词条已经归档或合并")
    snapshot = dict(current.snapshot_json)
    snapshot["status"] = "archived"
    term, revision = await _append_revision(
        db,
        term,
        current,
        snapshot,
        status="archived",
        change_reason="author_archived",
    )
    term.author_confirmed = True
    await db.flush()
    return _term_response(term, revision)


async def restore_project_vocabulary_term(
    db: AsyncSession,
    novel_id: str,
    type_ref: str,
    expected_revision_id: uuid.UUID,
) -> VocabularyTermResponse:
    await require_active_project_exclusive(db, novel_id)
    novel_uuid = parse_uuid(novel_id, "novel_id")
    term_uuid = parse_uuid(type_ref, "type_ref")
    term, current = await _current_record(db, novel_uuid, term_uuid, lock=True)
    if current.id != expected_revision_id:
        raise ConflictError("词条已在别处更新；请刷新后重试")
    if term.status != "archived":
        raise ConflictError("只有归档词条可以恢复")
    snapshot = dict(current.snapshot_json)
    snapshot["status"] = "active"
    await _ensure_unique_keys(
        db,
        novel_uuid,
        term.kind,
        snapshot,
        ignored_ids={term.id},
    )
    term, revision = await _append_revision(
        db,
        term,
        current,
        snapshot,
        status="active",
        change_reason="author_restored",
    )
    term.author_confirmed = True
    await db.flush()
    return _term_response(term, revision)


async def merge_project_vocabulary_terms(
    db: AsyncSession, novel_id: str, data: VocabularyMergeRequest
) -> VocabularyTermResponse:
    await require_active_project_exclusive(db, novel_id)
    novel_uuid = parse_uuid(novel_id, "novel_id")
    term_ids = sorted(data.expected_revision_ids, key=str)
    records: dict[uuid.UUID, tuple[ProjectVocabularyTerm, ProjectVocabularyRevision]] = {}
    for type_ref in term_ids:
        records[type_ref] = await _current_record(db, novel_uuid, type_ref, lock=True)
    for type_ref, (term, revision) in records.items():
        if revision.id != data.expected_revision_ids[type_ref]:
            raise ConflictError("参与合并的词条已更新；请刷新后重试")
        if term.status in _TOMBSTONE_STATUSES:
            raise ConflictError("归档或已合并词条不能再次合并")
    target, target_revision = records[data.target_id]
    if any(term.kind != target.kind for term, _ in records.values()):
        raise ValidationError("只能合并同一种类的项目词条")

    snapshot = dict(target_revision.snapshot_json)
    aliases = list(snapshot.get("aliases", []))
    for type_ref in data.source_ids:
        source_term, source_revision = records[type_ref]
        for alias in [
            source_revision.snapshot_json["name"],
            *source_revision.snapshot_json["aliases"],
        ]:
            if normalize_vocabulary_key(alias) not in _keys_from_snapshot(
                {"name": snapshot["name"], "aliases": aliases}
            ):
                aliases.append(alias)
    if len(aliases) > 24:
        raise ValidationError("合并后的别名超过 24 个，请先整理别名后重试")
    snapshot["aliases"] = aliases
    snapshot["status"] = "active"
    await _ensure_unique_keys(
        db,
        novel_uuid,
        target.kind,
        snapshot,
        ignored_ids=set(records),
    )
    target, target_revision = await _append_revision(
        db,
        target,
        target_revision,
        snapshot,
        status="active",
        change_reason="author_merge_target",
    )
    target.author_confirmed = True
    for type_ref in data.source_ids:
        source_term, source_revision = records[type_ref]
        source_snapshot = dict(source_revision.snapshot_json)
        source_snapshot["status"] = "merged"
        source_snapshot["redirect_to_id"] = str(target.id)
        source_term, _ = await _append_revision(
            db,
            source_term,
            source_revision,
            source_snapshot,
            status="merged",
            change_reason="author_merged",
            redirect_to_id=target.id,
        )
        source_term.author_confirmed = True
    await db.flush()
    return _term_response(target, target_revision)


async def split_project_vocabulary_term(
    db: AsyncSession,
    novel_id: str,
    type_ref: str,
    data: VocabularySplitRequest,
) -> tuple[VocabularyTermResponse, VocabularyTermResponse]:
    await require_active_project_exclusive(db, novel_id)
    novel_uuid = parse_uuid(novel_id, "novel_id")
    term_uuid = parse_uuid(type_ref, "type_ref")
    term, current = await _current_record(db, novel_uuid, term_uuid, lock=True)
    if current.id != data.expected_revision_id:
        raise ConflictError("词条已在别处更新；请刷新后重试")
    if term.status in _TOMBSTONE_STATUSES:
        raise ConflictError("归档或已合并词条不能拆分")
    retained = _base_snapshot(data.retained, status="active")
    split_off = _base_snapshot(data.split_off, status="active")
    first_keys = _keys_from_snapshot(retained)
    if first_keys & _keys_from_snapshot(split_off):
        raise ValidationError("拆分后的两个词条必须有不同名称和别名")
    for candidate in (retained, split_off):
        await _ensure_unique_keys(
            db,
            novel_uuid,
            term.kind,
            candidate,
            ignored_ids={term.id},
        )
    retained["reviewed_evidence"] = current.snapshot_json.get("reviewed_evidence", [])
    retained["evidence"] = current.snapshot_json.get("evidence", [])
    retained["independent_review"] = current.snapshot_json.get("independent_review")
    retained["proposal_run_id"] = current.snapshot_json.get("proposal_run_id")
    term, retained_revision = await _append_revision(
        db,
        term,
        current,
        retained,
        status="active",
        change_reason="author_split_retained",
    )
    term.author_confirmed = True
    split_term, split_revision = await _create_term(
        db,
        novel_uuid,
        term.kind,
        data.split_off,
        source="author",
        status="active",
        author_confirmed=True,
        change_reason="author_split_created",
    )
    return _term_response(term, retained_revision), _term_response(
        split_term, split_revision
    )


def _evidence_key(item: VocabularyEvidence) -> tuple[str, str, str]:
    return str(item.scene_id), item.source_hash, item.quote


def _union_evidence(
    first: list[dict[str, Any]], second: list[VocabularyEvidence]
) -> list[VocabularyEvidence]:
    items = [VocabularyEvidence.model_validate(item) for item in first]
    seen = {_evidence_key(item) for item in items}
    for item in second:
        if _evidence_key(item) not in seen:
            seen.add(_evidence_key(item))
            items.append(item)
    return sorted(items, key=lambda item: _evidence_key(item))


def _review_matches(
    evidence: list[VocabularyEvidence],
    review: VocabularyReviewReceipt | None,
    *,
    kind: str,
    fields: VocabularyTermFields,
    proposal_run_id: uuid.UUID,
) -> bool:
    if review is None:
        return False
    if (
        review.proposal_run_id != proposal_run_id
        or review.reviewer_run_id == proposal_run_id
    ):
        raise ConflictError("独立复核未绑定原生成运行")
    if review.proposal_hash != vocabulary_proposal_hash(kind, fields):
        raise ConflictError("独立复核与当前词条含义或特性不匹配，请重新复核")
    expected_hash = vocabulary_evidence_hash(evidence)
    if review.evidence_hash != expected_hash:
        raise ConflictError("独立复核与当前证据不匹配，请重新复核")
    return review.verdict == "passed"


def _stored_fields(snapshot: dict[str, Any]) -> VocabularyTermFields:
    return VocabularyTermFields.model_validate(
        {key: snapshot[key] for key in ("name", "description", "aliases", "traits")}
    )


def _proposal_fields(proposal: ModelVocabularyProposal) -> VocabularyTermFields:
    return VocabularyTermFields(
        name=proposal.name,
        description=proposal.description,
        aliases=proposal.aliases,
        traits=proposal.traits,
    )


async def persist_reviewed_model_vocabulary_proposal(
    db: AsyncSession,
    novel_id: str,
    proposal: ModelVocabularyProposal,
) -> dict[str, Any]:
    """Persist an M1-reviewed proposal after source and review revalidation.

    This seam binds receipt metadata to the exact quote/source-hash set. It cannot itself
    prove that quotes remain verbatim or that the review was semantically independent.
    """
    await require_active_project_exclusive(db, novel_id)
    novel_uuid = parse_uuid(novel_id, "novel_id")
    fields = _proposal_fields(proposal)
    proposed_snapshot = _base_snapshot(fields, status="emerging")
    keys = _keys_from_snapshot(proposed_snapshot)
    rows = await _current_records(db, novel_uuid, kind=proposal.kind, lock=True)
    records = {term.id: (term, revision) for term, revision in rows}
    matches = {}
    for term, revision in rows:
        if keys & _keys_from_snapshot(revision.snapshot_json):
            resolved = _resolve_redirect((term, revision), records)
            matches[resolved[0].id] = resolved
    archived = next(
        (row for row in matches.values() if row[0].status == "archived"), None
    )
    if archived is not None:
        term, current = archived
        return {
            "action": "restore_suggested",
            "item": _term_response(term, current),
            "existing_type_ref": term.id,
        }
    if len(matches) > 1:
        raise ConflictError("模型提案匹配到多个同名词条，需由作者消歧")
    if matches:
        term, current = next(iter(matches.values()))
        if term.source != "model" or term.author_confirmed:
            return {
                "action": "reused",
                "item": _term_response(term, current),
                "existing_type_ref": term.id,
            }
        evidence = _union_evidence(
            current.snapshot_json.get("evidence", []), proposal.evidence
        )
        reviewed_evidence = current.snapshot_json.get("reviewed_evidence", [])
        if proposal.independent_review is not None:
            review_passed = _review_matches(
                evidence,
                proposal.independent_review,
                kind=term.kind,
                fields=_stored_fields(current.snapshot_json),
                proposal_run_id=uuid.UUID(current.snapshot_json["proposal_run_id"]),
            )
        else:
            review_passed = False
        new_status = term.status
        if review_passed:
            reviewed_evidence = [item.model_dump(mode="json") for item in evidence]
            new_status = (
                "active"
                if len({str(item.scene_id) for item in evidence}) >= 2
                else "emerging"
            )
        elif proposal.independent_review is not None:
            reviewed_evidence = []
            new_status = "emerging"
        current_evidence = [
            VocabularyEvidence.model_validate(item)
            for item in current.snapshot_json.get("evidence", [])
        ]
        evidence_changed = [_evidence_key(item) for item in evidence] != [
            _evidence_key(item) for item in current_evidence
        ]
        if (
            not evidence_changed
            and new_status == term.status
            and proposal.independent_review is None
        ):
            return {
                "action": "reused",
                "item": _term_response(term, current),
                "existing_type_ref": term.id,
            }
        snapshot = dict(current.snapshot_json)
        snapshot["evidence"] = [item.model_dump(mode="json") for item in evidence]
        snapshot["reviewed_evidence"] = reviewed_evidence
        if proposal.independent_review is not None:
            snapshot["independent_review"] = proposal.independent_review.model_dump(
                mode="json"
            )
        snapshot["status"] = new_status
        term, revision = await _append_revision(
            db,
            term,
            current,
            snapshot,
            status=new_status,
            change_reason="model_evidence_accumulated",
        )
        return {
            "action": "updated",
            "item": _term_response(term, revision),
            "existing_type_ref": term.id,
        }

    if proposal.independent_review is not None:
        _review_matches(
            proposal.evidence,
            proposal.independent_review,
            kind=proposal.kind,
            fields=fields,
            proposal_run_id=proposal.proposal_run_id,
        )
    status = (
        "active"
        if len({str(item.scene_id) for item in proposal.evidence}) >= 2
        and _review_matches(
            proposal.evidence,
            proposal.independent_review,
            kind=proposal.kind,
            fields=fields,
            proposal_run_id=proposal.proposal_run_id,
        )
        else "emerging"
    )
    await _ensure_unique_keys(db, novel_uuid, proposal.kind, proposed_snapshot)
    term, revision = await _create_term(
        db,
        novel_uuid,
        proposal.kind,
        fields,
        source="model",
        status=status,
        author_confirmed=False,
        change_reason="model_proposal",
        evidence=proposal.evidence,
        independent_review=proposal.independent_review,
        proposal_run_id=proposal.proposal_run_id,
    )
    snapshot = dict(revision.snapshot_json)
    snapshot["status"] = status
    if snapshot != revision.snapshot_json:
        # _create_term already wrote this status in the immutable snapshot.
        raise AssertionError("model vocabulary snapshot status drifted")
    return {
        "action": "created",
        "item": _term_response(term, revision),
        "existing_type_ref": term.id,
    }


async def replace_model_vocabulary_evidence(
    db: AsyncSession,
    novel_id: str,
    type_ref: str,
    expected_revision_id: uuid.UUID,
    evidence: list[VocabularyEvidence],
    independent_review: VocabularyReviewReceipt | None,
) -> VocabularyTermResponse:
    """Replace stale evidence and activate only when evidence and review agree."""
    await require_active_project_exclusive(db, novel_id)
    novel_uuid = parse_uuid(novel_id, "novel_id")
    term_uuid = parse_uuid(type_ref, "type_ref")
    term, current = await _current_record(db, novel_uuid, term_uuid, lock=True)
    if current.id != expected_revision_id:
        raise ConflictError("词条证据已变化；请重新读取后重试")
    if term.source != "model" or term.author_confirmed:
        return _term_response(term, current)
    evidence = sorted(evidence, key=_evidence_key)
    if len({_evidence_key(item) for item in evidence}) != len(evidence):
        evidence = list({_evidence_key(item): item for item in evidence}.values())
        evidence.sort(key=_evidence_key)
    snapshot = dict(current.snapshot_json)
    snapshot["evidence"] = [item.model_dump(mode="json") for item in evidence]
    reviewed_evidence = current.snapshot_json.get("reviewed_evidence", [])
    old_evidence = [
        VocabularyEvidence.model_validate(item)
        for item in current.snapshot_json.get("evidence", [])
    ]
    evidence_changed = [_evidence_key(item) for item in evidence] != [
        _evidence_key(item) for item in old_evidence
    ]
    if independent_review is None and not evidence_changed:
        independent_review = (
            VocabularyReviewReceipt.model_validate(
                current.snapshot_json["independent_review"]
            )
            if current.snapshot_json.get("independent_review")
            else None
        )
        if independent_review is not None:
            reviewed = [
                VocabularyEvidence.model_validate(item) for item in reviewed_evidence
            ]
            _review_matches(
                reviewed,
                independent_review,
                kind=term.kind,
                fields=_stored_fields(current.snapshot_json),
                proposal_run_id=uuid.UUID(current.snapshot_json["proposal_run_id"]),
            )
        status = term.status
    else:
        if independent_review is not None:
            _review_matches(
                evidence,
                independent_review,
                kind=term.kind,
                fields=_stored_fields(current.snapshot_json),
                proposal_run_id=uuid.UUID(current.snapshot_json["proposal_run_id"]),
            )
        status = (
            "active"
            if independent_review is not None
            and independent_review.verdict == "passed"
            and len({str(item.scene_id) for item in evidence}) >= 2
            else "emerging"
        )
        reviewed_evidence = (
            [item.model_dump(mode="json") for item in evidence]
            if independent_review is not None and independent_review.verdict == "passed"
            else []
        )
    snapshot["independent_review"] = (
        independent_review.model_dump(mode="json")
        if independent_review is not None
        else None
    )
    snapshot["reviewed_evidence"] = reviewed_evidence
    snapshot["status"] = status
    if snapshot == current.snapshot_json:
        return _term_response(term, current)
    term, revision = await _append_revision(
        db,
        term,
        current,
        snapshot,
        status=status,
        change_reason="model_evidence_reconciled",
    )
    return _term_response(term, revision)


async def invalidate_model_vocabulary_evidence(
    db: AsyncSession,
    novel_id: str,
    invalid_scene_ids: set[uuid.UUID],
) -> list[VocabularyTermResponse]:
    """Remove rescinded Scene support and invalidate its bound review receipt."""
    if not invalid_scene_ids:
        return []
    await require_active_project_exclusive(db, novel_id)
    novel_uuid = parse_uuid(novel_id, "novel_id")
    changed: list[VocabularyTermResponse] = []
    for term, current in await _current_records(db, novel_uuid, lock=True):
        if (
            term.source != "model"
            or term.author_confirmed
            or term.status in _TOMBSTONE_STATUSES
        ):
            continue
        evidence = [
            VocabularyEvidence.model_validate(item)
            for item in current.snapshot_json.get("evidence", [])
        ]
        remaining = [item for item in evidence if item.scene_id not in invalid_scene_ids]
        if len(remaining) == len(evidence):
            continue
        snapshot = dict(current.snapshot_json)
        snapshot["evidence"] = [item.model_dump(mode="json") for item in remaining]
        prior_review = current.snapshot_json.get("independent_review")
        reviewed_evidence = [
            VocabularyEvidence.model_validate(item)
            for item in current.snapshot_json.get("reviewed_evidence", [])
        ]
        review_is_current = False
        if prior_review is not None:
            receipt = VocabularyReviewReceipt.model_validate(prior_review)
            review_is_current = _review_matches(
                reviewed_evidence,
                receipt,
                kind=term.kind,
                fields=_stored_fields(current.snapshot_json),
                proposal_run_id=uuid.UUID(current.snapshot_json["proposal_run_id"]),
            )
        valid_keys = {_evidence_key(item) for item in remaining}
        still_reviewed = [
            item for item in reviewed_evidence if _evidence_key(item) in valid_keys
        ]
        still_reviewed_scenes = {str(item.scene_id) for item in still_reviewed}
        status = (
            "active"
            if term.status == "active"
            and review_is_current
            and len(still_reviewed_scenes) >= 2
            else "emerging"
        )
        snapshot["independent_review"] = prior_review if status == "active" else None
        snapshot["reviewed_evidence"] = (
            [item.model_dump(mode="json") for item in reviewed_evidence]
            if status == "active"
            else []
        )
        snapshot["status"] = status
        term, revision = await _append_revision(
            db,
            term,
            current,
            snapshot,
            status=status,
            change_reason="model_evidence_invalidated",
        )
        changed.append(_term_response(term, revision))
    return changed


def _preset_fields(item: PresetItem) -> VocabularyTermFields:
    return VocabularyTermFields(
        name=item.name,
        description=item.description,
        aliases=list(item.aliases),
        traits=item.traits or {},
    )


async def apply_vocabulary_presets(
    db: AsyncSession, novel_id: str, preset_ids: list[str]
) -> VocabularyPresetApplyResponse:
    """Copy selected versioned presets once; later updates never rewrite copies."""
    await require_active_project_exclusive(db, novel_id)
    novel_uuid = parse_uuid(novel_id, "novel_id")
    if (
        not preset_ids
        or len(preset_ids) > len(PRESETS)
        or len(set(preset_ids)) != len(preset_ids)
    ):
        raise ValidationError("题材预设选择无效")
    unknown = set(preset_ids) - PRESETS.keys()
    if unknown:
        raise ValidationError("未知题材预设")
    existing = await db.scalars(
        select(ProjectVocabularyTerm).where(
            ProjectVocabularyTerm.novel_id == novel_uuid,
            ProjectVocabularyTerm.preset_id.in_(preset_ids),
        )
    )
    applied_keys = {(term.preset_id, term.preset_item_key) for term in existing}
    current = await _current_records(db, novel_uuid, lock=True)
    known_keys: dict[str, set[str]] = {}
    for term, revision in current:
        known_keys.setdefault(term.kind, set()).update(
            _keys_from_snapshot(revision.snapshot_json)
        )
    applied = already_applied = duplicate_skipped = 0
    created: list[VocabularyTermResponse] = []
    for preset_id in preset_ids:
        preset = PRESETS[preset_id]
        for version, items in ((preset.version, preset.items), *preset.extensions):
            for item in items:
                identity = (preset.id, item.key)
                if identity in applied_keys:
                    already_applied += 1
                    continue
                fields = _preset_fields(item)
                snapshot = _base_snapshot(fields, status="active")
                keys = _keys_from_snapshot(snapshot)
                if known_keys.get(item.kind, set()) & keys:
                    duplicate_skipped += 1
                    continue
                term, revision = await _create_term(
                    db,
                    novel_uuid,
                    item.kind,
                    fields,
                    source="preset",
                    status="active",
                    author_confirmed=True,
                    change_reason="preset_copied",
                    preset_id=preset.id,
                    preset_version=version,
                    preset_item_key=item.key,
                )
                known_keys.setdefault(item.kind, set()).update(keys)
                applied_keys.add(identity)
                created.append(_term_response(term, revision))
                applied += 1
    return VocabularyPresetApplyResponse(
        applied=applied,
        already_applied=already_applied,
        duplicate_skipped=duplicate_skipped,
        items=created,
    )


async def resolve_vocabulary_type_revisions(
    db: AsyncSession,
    novel_id: str,
    refs: set[tuple[uuid.UUID, uuid.UUID]],
    *,
    follow_merged_redirects: bool = False,
) -> dict[tuple[uuid.UUID, uuid.UUID], dict[str, object]]:
    """Resolve only exact same-project (stable type, pinned revision) pairs."""
    await require_active_project(db, novel_id)
    if not refs:
        return {}
    novel_uuid = parse_uuid(novel_id, "novel_id")
    pair_filters = [
        and_(
            ProjectVocabularyTerm.id == type_ref,
            ProjectVocabularyRevision.id == revision_id,
        )
        for type_ref, revision_id in refs
    ]
    statement = (
        select(ProjectVocabularyTerm, ProjectVocabularyRevision)
        .join(
            ProjectVocabularyRevision,
            and_(
                ProjectVocabularyRevision.novel_id == ProjectVocabularyTerm.novel_id,
                ProjectVocabularyRevision.term_id == ProjectVocabularyTerm.id,
            ),
        )
        .where(
            ProjectVocabularyTerm.novel_id == novel_uuid,
            ProjectVocabularyRevision.novel_id == novel_uuid,
            or_(*pair_filters),
        )
    )
    result = await db.execute(statement)
    rows = result.all()
    current_records = {}
    if follow_merged_redirects and any(term.status == "merged" for term, _ in rows):
        pending_ids = {term.id for term, _ in rows if term.status == "merged"}
        while pending_ids:
            missing_ids = pending_ids - current_records.keys()
            if not missing_ids:
                break
            fetched = await _current_records(
                db,
                novel_uuid,
                ids=missing_ids,
            )
            current_records.update(
                {term.id: (term, revision) for term, revision in fetched}
            )
            pending_ids = {
                term.redirect_to_id
                for term, _ in fetched
                if term.status == "merged"
                and term.redirect_to_id is not None
                and term.redirect_to_id not in current_records
            }
    resolved: dict[tuple[uuid.UUID, uuid.UUID], dict[str, object]] = {}
    for term, revision in rows:
        item = {
            "kind": term.kind,
            "status": term.status,
            "revision_id": revision.id,
            "name": revision.snapshot_json.get("name", ""),
            "description": revision.snapshot_json.get("description", ""),
            "traits": revision.snapshot_json.get("traits", {}),
        }
        if follow_merged_redirects:
            effective_term, effective_revision = (term, revision)
            if term.status == "merged":
                effective_term, effective_revision = _resolve_redirect(
                    (term, revision), current_records
                )
            item.update(
                {
                    "effective_status": effective_term.status,
                    "effective_traits": effective_revision.snapshot_json.get(
                        "traits", {}
                    ),
                }
            )
        resolved[(term.id, revision.id)] = item
    if resolved.keys() != refs:
        raise NotFoundError("项目词条或固定修订不存在")
    return resolved
