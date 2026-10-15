"""World-owned storage and review for Evolution's spatial clue candidates."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from core.container import get
from core.errors import ConflictError, NotFoundError, ValidationError
from core.service_keys import STORY_SCENE_SOURCE
from modules.project.facade import (
    require_active_project,
    require_active_project_exclusive,
)
from modules.world.map_spatial_clue_models import MapSpatialClueRecord
from modules.world.map_spatial_clue_schemas import (
    MapSpatialClue,
    MapSpatialClueBatch,
    MapSpatialClueContext,
    MapSpatialClueContextItem,
    MapSpatialClueContextType,
    MapSpatialClueDecisionRequest,
    MapSpatialClueEvidenceResponse,
    MapSpatialClueListResponse,
    MapSpatialClueRejection,
    MapSpatialClueResponse,
    MapSpatialClueResultRef,
    MapSpatialClueSourceBinding,
    MapSpatialClueStageResult,
    MapSpatialClueStatus,
    MapSpatialClueTypeProposalDraft,
    MapSpatialClueTypeProposalResponse,
    SpatialVocabularyKind,
)
from modules.world.models import CoreEntity
from modules.world.project_vocabulary_models import (
    ProjectVocabularyRevision,
    ProjectVocabularyTerm,
)
from modules.world.project_vocabulary_schemas import (
    ModelVocabularyProposal,
    VocabularyEvidence,
    VocabularyReviewReceipt,
    VocabularyTermFields,
    normalize_vocabulary_key,
    vocabulary_evidence_hash,
    vocabulary_proposal_hash,
)
from modules.world.project_vocabulary_service import (
    persist_reviewed_model_vocabulary_proposal,
)
from modules.writing.facade import build_manuscript_range_ref, read_manuscript_range
from shared.utils import parse_uuid

_SPATIAL_KINDS = tuple(SpatialVocabularyKind.__args__)
_VISIBLE_CLUE_STATUSES = {
    "pending_review",
    "pending_verification",
    "adopted",
}


async def _lock_project_for_spatial_write(db: AsyncSession, novel_id: str) -> None:
    # A reading worker may already hold FOR SHARE. Two such workers must not
    # deadlock while upgrading; keep a failed NOWAIT inside its own savepoint.
    try:
        async with db.begin_nested():
            await require_active_project_exclusive(db, novel_id, nowait=True)
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) == "55P03":
            raise ConflictError("作品正在更新，请稍后重新提交空间线索") from exc
        raise


def _digest(value: Any) -> str:
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def spatial_clue_review_hash(clue: MapSpatialClue) -> str:
    """Hash the exact proposed clue body, excluding only its independent review."""
    return _digest(clue.model_dump(mode="json", exclude={"review"}))


def _type_proposal_fields(proposal: ModelVocabularyProposal) -> VocabularyTermFields:
    return VocabularyTermFields(
        name=proposal.name,
        description=proposal.description,
        aliases=proposal.aliases,
        traits=proposal.traits,
    )


def _type_fields_match(
    snapshot: dict[str, Any], kind: str, fields: VocabularyTermFields
) -> bool:
    stored = VocabularyTermFields.model_validate(
        {key: snapshot[key] for key in ("name", "description", "aliases", "traits")}
    )
    return vocabulary_proposal_hash(kind, stored) == vocabulary_proposal_hash(
        kind, fields
    )


def _type_name_keys(fields: VocabularyTermFields) -> set[str]:
    return {
        key
        for value in (fields.name, *fields.aliases)
        if (key := normalize_vocabulary_key(value))
    }


def _semantic_signature(clue: MapSpatialClue) -> str:
    payload = clue.model_dump(
        mode="json",
        exclude={"review", "quote", "clue_key", "type_proposal", "type_proposal_draft"},
    )
    proposal = clue.type_proposal or clue.type_proposal_draft
    if proposal is not None:
        payload["proposed_type"] = proposal.model_dump(
            mode="json", include={"kind", "name", "description", "aliases", "traits"}
        )
    return _digest(payload)


def _response(row: MapSpatialClueRecord) -> MapSpatialClueResponse:
    clue = MapSpatialClue.model_validate(row.clue_payload)
    type_proposal = None
    proposal = clue.type_proposal or clue.type_proposal_draft
    type_kind = clue.type_kind
    if proposal is not None:
        type_kind = proposal.kind
        evidence = (
            [(str(item.scene_id), item.quote) for item in proposal.evidence]
            if isinstance(proposal, ModelVocabularyProposal)
            else [(row.scene_id, clue.quote)]
        )
        type_proposal = MapSpatialClueTypeProposalResponse(
            kind=proposal.kind,
            name=proposal.name,
            description=proposal.description,
            aliases=proposal.aliases,
            traits=proposal.traits,
            evidence=[
                MapSpatialClueEvidenceResponse(scene_id=scene_id, quote=quote)
                for scene_id, quote in evidence
            ],
        )
    return MapSpatialClueResponse(
        id=row.id,
        novel_id=row.novel_id,
        scene_id=row.scene_id,
        scene_index=row.scene_index,
        clue_key=row.clue_key,
        status=row.status,
        fingerprint=row.fingerprint,
        kind=clue.kind,
        subject=clue.subject,
        target=clue.target,
        relation=clue.relation,
        type_ref=clue.type_ref,
        type_revision_id=clue.type_revision_id,
        type_kind=type_kind,
        type_proposal=type_proposal,
        modality=clue.modality,
        quote=clue.quote,
        attributes=clue.attributes,
        verification_note=row.verification_note,
        merged_into_id=row.merged_into_id,
    )


def _result_ref(row: MapSpatialClueRecord) -> MapSpatialClueResultRef:
    return MapSpatialClueResultRef(
        clue_key=row.clue_key, clue_id=row.id, status=row.status
    )


async def _invalidate_auto_drafts_for_clue(
    db: AsyncSession, novel_id: str, clue_id: str
) -> None:
    from modules.world.map_auto_draft_service import invalidate_auto_drafts_for_clue

    await invalidate_auto_drafts_for_clue(
        db,
        novel_id,
        clue_id,
        reason="草图依赖的空间线索已合并或拒绝，请重新映射。",
    )


async def _scene_contract(db, novel_id: str, scene_id: str, scene_index: int):
    scene = await get(STORY_SCENE_SOURCE).get_scene_contract(db, novel_id, scene_id)
    if (
        scene is None
        or parse_uuid(scene.novel_id, "novel_id") != parse_uuid(novel_id, "novel_id")
        or scene.scene_index != scene_index
        or scene.status not in {"draft", "canonical"}
    ):
        raise ValidationError("Scene identity, order, or status changed")
    return scene


async def _resolve_binding(
    db,
    novel_id: str,
    scene_id: str,
    scene_index: int,
    binding,
) -> list[dict[str, Any]]:
    """Re-read exact current Scene spans and manuscript bytes in the bound mode."""
    await _scene_contract(db, novel_id, scene_id, scene_index)
    spans = await get(STORY_SCENE_SOURCE).get_scene_spans_for_scene(
        db,
        novel_id,
        scene_id,
        status_filter=["draft", "canonical"],
        content_mode=binding.content_mode,
    )
    precise = [
        span
        for span in spans
        if span.mapping_status in {"exact", "reanchored"}
        and span.source_draft_id
        and span.source_content_hash
        and span.start_offset is not None
        and span.end_offset is not None
    ]
    ranges = binding.ranges()
    ordered_spans = sorted(
        precise,
        key=lambda span: (span.chapter_index, span.start_offset, span.id),
    )
    if not ordered_spans or len(ordered_spans) != len(ranges):
        raise ValidationError(
            "Scene source coverage changed; spatial discovery needs review"
        )

    resolved: list[dict[str, Any]] = []
    validation_sources = []
    for source, span in zip(ranges, ordered_spans, strict=True):
        if (
            len(source.content_hash) != 64
            or str(span.source_draft_id) != source.draft_id
            or span.chapter_index != source.chapter_index
            or span.source_content_hash != source.content_hash
            or span.start_offset != source.start_offset
            or (source.end_offset is not None and span.end_offset != source.end_offset)
        ):
            raise ValidationError("Scene source boundary or draft hash changed")
        end_offset = (
            source.end_offset if source.end_offset is not None else span.end_offset
        )
        if end_offset is None or end_offset <= source.start_offset:
            raise ValidationError("Scene source range is incomplete")
        validation_sources.append(
            {
                "draft_id": source.draft_id,
                "chapter_index": source.chapter_index,
                "content_hash": source.content_hash,
                "start_offset": source.start_offset,
                "end_offset": end_offset,
            }
        )

    await get(STORY_SCENE_SOURCE).validate_scene_source_ranges(
        db,
        novel_id,
        scene_id,
        scene_index,
        validation_sources,
        content_mode=binding.content_mode,
    )
    for source, span, source_data in zip(
        ranges, ordered_spans, validation_sources, strict=True
    ):
        ref = await build_manuscript_range_ref(
            db,
            novel_id,
            draft_id=source.draft_id,
            start_offset=source_data["start_offset"],
            end_offset=source_data["end_offset"],
            content_mode=binding.content_mode,
        )
        if ref.source_hash != source.content_hash:
            raise ValidationError("Bound manuscript draft hash is stale")
        if source.range_hash is not None and ref.range_hash != source.range_hash:
            raise ValidationError("Bound manuscript range hash is stale")
        read = await read_manuscript_range(db, novel_id, ref, before=0, after=0)
        exact_text = read.text[read.highlight_start : read.highlight_end]
        if (
            not 0 <= read.highlight_start < read.highlight_end <= len(read.text)
            or len(exact_text) != ref.end_offset - ref.start_offset
            or hashlib.sha256(exact_text.encode("utf-8")).hexdigest() != ref.range_hash
        ):
            raise ValidationError("Manuscript range read is not exact")
        resolved.append(
            {
                "binding": source,
                "span": span,
                "source_ref": ref,
                "text": exact_text,
            }
        )
    return resolved


async def _evidence_is_current(
    db,
    novel_id: str,
    evidence: VocabularyEvidence,
    *,
    through_scene_index: int | None = None,
    content_mode: str | None = None,
) -> bool:
    """Evidence snapshots are not trusted; bind every quote to a current Scene span."""
    scene_id = str(evidence.scene_id)
    scene = await get(STORY_SCENE_SOURCE).get_scene_contract(db, novel_id, scene_id)
    if (
        scene is None
        or parse_uuid(scene.novel_id, "novel_id") != parse_uuid(novel_id, "novel_id")
        or scene.status not in {"draft", "canonical"}
        or (through_scene_index is not None and scene.scene_index > through_scene_index)
    ):
        return False
    for mode in (content_mode,) if content_mode else ("canonical", "working"):
        spans = await get(STORY_SCENE_SOURCE).get_scene_spans_for_scene(
            db,
            novel_id,
            scene_id,
            status_filter=["draft", "canonical"],
            content_mode=mode,
        )
        ordered = sorted(
            spans, key=lambda span: (span.chapter_index, span.start_offset or 0, span.id)
        )
        if not ordered or any(
            span.mapping_status not in {"exact", "reanchored"}
            or not span.source_draft_id
            or not span.source_content_hash
            or span.start_offset is None
            or span.end_offset is None
            for span in ordered
        ):
            continue
        try:
            ranges = [
                {
                    "draft_id": str(span.source_draft_id),
                    "chapter_index": span.chapter_index,
                    "content_hash": span.source_content_hash,
                    "start_offset": span.start_offset,
                    "end_offset": span.end_offset,
                }
                for span in ordered
            ]
            resolved = await _resolve_binding(
                db,
                novel_id,
                scene_id,
                scene.scene_index,
                MapSpatialClueSourceBinding(
                    **ranges[0], content_mode=mode, additional_sources=ranges[1:]
                ),
            )
        except (ConflictError, NotFoundError, ValidationError, ValueError, TypeError):
            continue
        if any(
            item["binding"].content_hash == evidence.source_hash
            and evidence.quote in item["text"]
            for item in resolved
        ):
            return True
    return False


def _matching_source_hash(clue: MapSpatialClue, resolved_sources: list[dict]) -> str:
    matching = [item for item in resolved_sources if clue.quote in item["text"]]
    if not matching:
        raise ValidationError("Exact clue quote is absent from its bound Scene source")
    hashes = {item["binding"].content_hash for item in matching}
    if len(hashes) != 1:
        raise ValidationError("Exact clue quote matches multiple source revisions")
    return next(iter(hashes))


async def _validate_endpoints(
    db, novel_id: str, batch: MapSpatialClueBatch, clue: MapSpatialClue
) -> None:
    allowed = {item.entity_id: item.state for item in batch.allowed_endpoint_ids}
    requested = {
        endpoint.entity_id: endpoint.state
        for endpoint in (clue.subject, clue.target)
        if endpoint is not None and endpoint.entity_id is not None
    }
    if any(allowed.get(entity_id) != state for entity_id, state in requested.items()):
        raise ValidationError("Clue endpoint was not in this discovery input")
    if not requested:
        return
    rows = (
        await db.scalars(
            select(CoreEntity).where(
                CoreEntity.novel_id == parse_uuid(novel_id, "novel_id"),
                CoreEntity.id.in_(list(requested)),
            )
        )
    ).all()
    actual = {
        row.id: ("canonical" if row.status == "canonical" else "candidate")
        for row in rows
        if row.status in {"canonical", "draft", "candidate"}
    }
    if actual != requested:
        raise ValidationError(
            "Clue endpoint state changed or no longer belongs to this novel"
        )


def _type_references(clue: MapSpatialClue) -> list[tuple[UUID, UUID, str]]:
    refs = []
    if clue.type_ref is not None:
        refs.append((clue.type_ref, clue.type_revision_id, clue.type_kind))
    for ref in (clue.attributes.transport_type, clue.attributes.traveler_type):
        if ref is not None:
            refs.append((ref.type_ref, ref.type_revision_id, ref.kind))
    return refs


async def _validate_type_references(
    db, novel_id: str, batch: MapSpatialClueBatch, clue: MapSpatialClue
) -> None:
    allowed = {
        (item.type_ref, item.type_revision_id): item.kind
        for item in batch.allowed_type_revisions
    }
    refs = _type_references(clue)
    if any(
        allowed.get((type_ref, revision_id)) != kind
        for type_ref, revision_id, kind in refs
    ):
        raise ValidationError("Clue type revision was not in this discovery context")
    if not refs:
        return
    for type_ref, revision_id, kind in refs:
        row = (
            await db.execute(
                select(ProjectVocabularyTerm, ProjectVocabularyRevision)
                .join(
                    ProjectVocabularyRevision,
                    and_(
                        ProjectVocabularyRevision.novel_id
                        == ProjectVocabularyTerm.novel_id,
                        ProjectVocabularyRevision.term_id == ProjectVocabularyTerm.id,
                        ProjectVocabularyRevision.id
                        == ProjectVocabularyTerm.current_revision_id,
                    ),
                )
                .where(
                    ProjectVocabularyTerm.novel_id == parse_uuid(novel_id, "novel_id"),
                    ProjectVocabularyTerm.id == type_ref,
                    ProjectVocabularyTerm.current_revision_id == revision_id,
                    ProjectVocabularyTerm.kind == kind,
                    ProjectVocabularyTerm.status.in_(["active", "emerging"]),
                )
            )
        ).one_or_none()
        if row is None:
            raise ValidationError("Clue type identity or revision changed")


async def _revalidate_stored_clue(
    db,
    novel_id: str,
    row: MapSpatialClueRecord,
    clue: MapSpatialClue,
    *,
    allow_identity_transitions: bool = False,
) -> dict[str, CoreEntity]:
    binding = MapSpatialClueSourceBinding.model_validate(row.source_binding)
    sources = await _resolve_binding(db, novel_id, row.scene_id, row.scene_index, binding)
    source_hash = _matching_source_hash(clue, sources)
    evidence = [
        VocabularyEvidence(
            scene_id=parse_uuid(row.scene_id, "scene_id"),
            quote=clue.quote,
            source_hash=source_hash,
        )
    ]
    if (
        clue.review.proposal_hash != spatial_clue_review_hash(clue)
        or clue.review.evidence_hash != vocabulary_evidence_hash(evidence)
        or clue.review.verdict != "supported"
    ):
        raise ValidationError("Clue review no longer matches current source evidence")
    endpoints = {
        endpoint.entity_id: endpoint.state
        for endpoint in (clue.subject, clue.target)
        if endpoint is not None and endpoint.entity_id is not None
    }
    current_endpoints: dict[str, CoreEntity] = {}
    if endpoints:
        rows = (
            await db.scalars(
                select(CoreEntity).where(
                    CoreEntity.novel_id == parse_uuid(novel_id, "novel_id"),
                    CoreEntity.id.in_(list(endpoints)),
                )
            )
        ).all()
        by_id = {entity.id: entity for entity in rows}
        for entity_id, expected_state in endpoints.items():
            entity = by_id.get(entity_id)
            if (
                allow_identity_transitions
                and entity is not None
                and entity.status == "merged"
            ):
                redirect = (entity.content_json or {}).get("merged_into")
                seen = {entity.id}
                while redirect:
                    target_id = parse_uuid(str(redirect), "merged_entity_id")
                    if target_id in seen:
                        break
                    seen.add(target_id)
                    target = await db.scalar(
                        select(CoreEntity).where(
                            CoreEntity.novel_id == parse_uuid(novel_id, "novel_id"),
                            CoreEntity.id == target_id,
                        )
                    )
                    if target is None:
                        break
                    if target.status == "merged":
                        redirect = (target.content_json or {}).get("merged_into")
                        continue
                    entity = target
                    break
            if entity is None or entity.status not in {
                "canonical",
                "candidate",
                "draft",
            }:
                raise ValidationError("Clue endpoint identity changed")
            actual_state = "canonical" if entity.status == "canonical" else "candidate"
            if actual_state != expected_state and not (
                allow_identity_transitions
                and expected_state == "candidate"
                and actual_state == "canonical"
            ):
                raise ValidationError("Clue endpoint identity changed")
            current_endpoints[str(entity_id)] = entity
    for type_ref, revision_id, kind in _type_references(clue):
        row_type = (
            await db.execute(
                select(ProjectVocabularyTerm.id)
                .join(
                    ProjectVocabularyRevision,
                    and_(
                        ProjectVocabularyRevision.novel_id
                        == ProjectVocabularyTerm.novel_id,
                        ProjectVocabularyRevision.term_id == ProjectVocabularyTerm.id,
                        ProjectVocabularyRevision.id
                        == ProjectVocabularyTerm.current_revision_id,
                    ),
                )
                .where(
                    ProjectVocabularyTerm.novel_id == parse_uuid(novel_id, "novel_id"),
                    ProjectVocabularyTerm.id == type_ref,
                    ProjectVocabularyTerm.current_revision_id == revision_id,
                    ProjectVocabularyTerm.kind == kind,
                    ProjectVocabularyTerm.status.in_(["active", "emerging"]),
                )
            )
        ).scalar_one_or_none()
        if row_type is None:
            raise ValidationError("Clue type identity or revision changed")
    if clue.type_proposal is not None:
        reviewed = await _validate_type_proposal(
            db,
            novel_id,
            clue.type_proposal,
            current_scene_id=parse_uuid(row.scene_id, "scene_id"),
            current_scene_index=row.scene_index,
            content_mode=binding.content_mode,
        )
        if not reviewed:
            raise ValidationError("Clue type proposal has no passing independent review")
    return current_endpoints


async def _validate_type_proposal(
    db,
    novel_id: str,
    proposal: ModelVocabularyProposal,
    *,
    current_scene_id: UUID,
    current_scene_index: int,
    content_mode: str,
) -> bool:
    if proposal.kind not in _SPATIAL_KINDS:
        raise ValidationError("Type proposal is not a spatial vocabulary kind")
    for evidence in proposal.evidence:
        if not await _evidence_is_current(
            db,
            novel_id,
            evidence,
            through_scene_index=(
                current_scene_index
                if evidence.scene_id == current_scene_id
                else current_scene_index - 1
            ),
            content_mode=content_mode,
        ):
            raise ValidationError(
                "Type proposal contains stale or unverifiable Scene evidence"
            )
    if not any(item.scene_id == current_scene_id for item in proposal.evidence):
        raise ValidationError("Type proposal omits evidence from the current Scene")
    existing_terms = (
        await db.execute(
            select(ProjectVocabularyTerm, ProjectVocabularyRevision)
            .join(
                ProjectVocabularyRevision,
                and_(
                    ProjectVocabularyRevision.novel_id == ProjectVocabularyTerm.novel_id,
                    ProjectVocabularyRevision.term_id == ProjectVocabularyTerm.id,
                    ProjectVocabularyRevision.id
                    == ProjectVocabularyTerm.current_revision_id,
                ),
            )
            .where(
                ProjectVocabularyTerm.novel_id == parse_uuid(novel_id, "novel_id"),
                ProjectVocabularyTerm.kind == proposal.kind,
                ProjectVocabularyTerm.source == "model",
            )
        )
    ).all()
    fields = _type_proposal_fields(proposal)
    proposal_keys = _type_name_keys(fields)
    matching_terms = []
    for term, revision in existing_terms:
        snapshot = revision.snapshot_json
        existing_fields = VocabularyTermFields.model_validate(
            {key: snapshot[key] for key in ("name", "description", "aliases", "traits")}
        )
        if not proposal_keys & _type_name_keys(existing_fields):
            continue
        matching_terms.append((term, revision, existing_fields))
    if len(matching_terms) > 1:
        raise ValidationError("Type proposal matches multiple existing project terms")
    for term, revision, existing_fields in matching_terms:
        snapshot = revision.snapshot_json
        if term.author_confirmed:
            continue
        if snapshot.get("proposal_run_id") != str(proposal.proposal_run_id):
            raise ValidationError("Type proposal does not bind the original proposal run")
        if not _type_fields_match(snapshot, proposal.kind, fields):
            raise ValidationError(
                "Type proposal changed the original emerging type meaning"
            )
        prior = {
            (str(item.scene_id), item.quote, item.source_hash)
            for item in (
                VocabularyEvidence.model_validate(raw)
                for raw in snapshot.get("evidence", [])
            )
        }
        submitted = {
            (str(item.scene_id), item.quote, item.source_hash)
            for item in proposal.evidence
        }
        if not prior.issubset(submitted):
            raise ValidationError(
                "Type proposal dropped evidence from its original proposal"
            )
    receipt = proposal.independent_review
    if receipt is None:
        return False
    if (
        receipt.proposal_run_id != proposal.proposal_run_id
        or receipt.proposal_hash
        != vocabulary_proposal_hash(proposal.kind, _type_proposal_fields(proposal))
        or receipt.evidence_hash != vocabulary_evidence_hash(proposal.evidence)
    ):
        raise ValidationError(
            "Type proposal review is not bound to its current meaning and evidence"
        )
    return receipt.verdict == "passed"


async def _persist_type_proposal(
    db,
    novel_id: str,
    *,
    draft: MapSpatialClueTypeProposalDraft | None,
    proposal: ModelVocabularyProposal | None,
    current_evidence: VocabularyEvidence,
    current_scene_index: int,
    content_mode: str,
) -> None:
    if draft is None and proposal is None:
        return
    if draft is not None:
        payload = ModelVocabularyProposal(
            kind=draft.kind,
            proposal_run_id=draft.proposal_run_id,
            name=draft.name,
            description=draft.description,
            aliases=draft.aliases,
            traits=draft.traits,
            evidence=[current_evidence],
        )
    else:
        payload = proposal
    if payload is None:
        return
    await _validate_type_proposal(
        db,
        novel_id,
        payload,
        current_scene_id=current_evidence.scene_id,
        current_scene_index=current_scene_index,
        content_mode=content_mode,
    )
    await persist_reviewed_model_vocabulary_proposal(db, novel_id, payload)


async def stage_spatial_discovery(
    db: AsyncSession, novel_id: str, batch: MapSpatialClueBatch | dict
) -> MapSpatialClueStageResult:
    """Persist independently reviewed clue candidates without changing map heads."""
    await _lock_project_for_spatial_write(db, novel_id)
    batch = MapSpatialClueBatch.model_validate(batch)
    scene_id = str(parse_uuid(batch.scene_id, "scene_id"))
    try:
        resolved_sources = await _resolve_binding(
            db, novel_id, scene_id, batch.scene_index, batch.source_binding
        )
    except (ConflictError, NotFoundError, ValidationError, ValueError, TypeError) as exc:
        return MapSpatialClueStageResult(
            rejected=[
                MapSpatialClueRejection(
                    clue_key=clue.clue_key,
                    code="source_binding_invalid",
                    message="Scene 来源已变化或无法验证；请重新读取后再试。",
                )
                for clue in batch.clues
            ],
            diagnostics=[str(exc)[:500]],
        )

    result = MapSpatialClueStageResult()
    for clue in batch.clues:
        try:
            await _validate_endpoints(db, novel_id, batch, clue)
            await _validate_type_references(db, novel_id, batch, clue)
            source_hash = _matching_source_hash(clue, resolved_sources)
            scene_uuid = parse_uuid(scene_id, "scene_id")
            clue_evidence = [
                VocabularyEvidence(
                    scene_id=scene_uuid,
                    quote=clue.quote,
                    source_hash=source_hash,
                )
            ]
            if clue.review.proposal_hash != spatial_clue_review_hash(clue):
                raise ValidationError(
                    "Independent clue review does not match this proposal"
                )
            if clue.review.evidence_hash != vocabulary_evidence_hash(clue_evidence):
                raise ValidationError(
                    "Independent clue review does not match exact source evidence"
                )

            type_review_ok = True
            if clue.type_proposal is not None:
                type_review_ok = await _validate_type_proposal(
                    db,
                    novel_id,
                    clue.type_proposal,
                    current_scene_id=scene_uuid,
                    current_scene_index=batch.scene_index,
                    content_mode=batch.source_binding.content_mode,
                )

            fingerprint = _digest(
                {
                    "novel_id": novel_id,
                    "run_id": batch.run_id,
                    "attempt_id": batch.attempt_id,
                    "scene_id": scene_id,
                    "scene_index": batch.scene_index,
                    "source_manifest_hash": batch.source_manifest_hash,
                    "source_binding": batch.source_binding.model_dump(mode="json"),
                    "method_fingerprint": batch.method_fingerprint,
                    "clue": clue.model_dump(mode="json"),
                }
            )
            existing = await db.scalar(
                select(MapSpatialClueRecord)
                .where(
                    MapSpatialClueRecord.novel_id == parse_uuid(novel_id, "novel_id"),
                    MapSpatialClueRecord.run_id == batch.run_id,
                    MapSpatialClueRecord.attempt_id == batch.attempt_id,
                    MapSpatialClueRecord.clue_key == clue.clue_key,
                )
                .with_for_update()
            )
            if existing is not None:
                if existing.fingerprint != fingerprint:
                    raise ConflictError(
                        "Discovery replay changed an existing clue payload"
                    )
                row = existing
            else:
                if clue.review.verdict == "supported" and (
                    clue.type_proposal_draft is not None
                    or (clue.type_proposal is not None and type_review_ok)
                ):
                    await _persist_type_proposal(
                        db,
                        novel_id,
                        draft=clue.type_proposal_draft,
                        proposal=clue.type_proposal,
                        current_evidence=clue_evidence[0],
                        current_scene_index=batch.scene_index,
                        content_mode=batch.source_binding.content_mode,
                    )
                pending_verification = (
                    clue.review.verdict != "supported" or not type_review_ok
                )
                note = None
                if clue.review.verdict == "unsupported":
                    note = "独立复核认为证据不支持该空间线索，等待作者核查。"
                elif clue.review.verdict == "uncertain":
                    note = "独立复核无法确定该空间线索，等待作者核查。"
                elif not type_review_ok:
                    note = "空间类型缺少绑定当前提案和完整证据的通过复核。"
                row = MapSpatialClueRecord(
                    novel_id=parse_uuid(novel_id, "novel_id"),
                    run_id=batch.run_id,
                    attempt_id=batch.attempt_id,
                    scene_id=scene_id,
                    scene_index=batch.scene_index,
                    clue_key=clue.clue_key,
                    source_manifest_hash=batch.source_manifest_hash,
                    method_fingerprint=batch.method_fingerprint,
                    source_content_mode=batch.source_binding.content_mode,
                    source_binding=batch.source_binding.model_dump(mode="json"),
                    clue_payload=clue.model_dump(mode="json"),
                    fingerprint=fingerprint,
                    status="pending_verification"
                    if pending_verification
                    else "pending_review",
                    verification_note=note,
                )
                db.add(row)
                await db.flush()
            ref = _result_ref(row)
            result.result_refs.append(ref)
            (
                result.pending
                if row.status == "pending_verification"
                else result.accepted
            ).append(ref)
        except (
            ConflictError,
            NotFoundError,
            ValidationError,
            ValueError,
            TypeError,
        ) as exc:
            result.rejected.append(
                MapSpatialClueRejection(
                    clue_key=clue.clue_key,
                    code="clue_invalid",
                    message="线索身份、词条、复核或原文证据已变化；该项未写入候选。",
                )
            )
            result.diagnostics.append(str(exc)[:500])
    return result


async def read_spatial_discovery_context(
    db: AsyncSession,
    novel_id: str,
    *,
    scene_id: str,
    scene_index: int,
    endpoint_ids: list[str],
    endpoint_surfaces: list[str],
    type_limit: int,
    clue_limit: int,
    run_id: str | None = None,
) -> MapSpatialClueContext:
    """Return bounded, same-project, strictly earlier spatial context."""
    await require_active_project(db, novel_id)
    await _scene_contract(db, novel_id, scene_id, scene_index)
    if not 0 <= type_limit <= 64 or not 0 <= clue_limit <= 128:
        raise ValidationError("Spatial discovery context limit is out of range")
    if run_id is not None and (not run_id.strip() or len(run_id) > 120):
        raise ValidationError("Spatial discovery run identity is invalid")
    nid = parse_uuid(novel_id, "novel_id")
    endpoint_uuid_ids = [parse_uuid(item, "endpoint_id") for item in endpoint_ids]
    endpoint_surfaces = [
        item.strip().casefold() for item in endpoint_surfaces if item.strip()
    ]
    states: dict[str, str] = {}
    if endpoint_uuid_ids:
        entities = (
            await db.scalars(
                select(CoreEntity).where(
                    CoreEntity.novel_id == nid,
                    CoreEntity.id.in_(endpoint_uuid_ids),
                )
            )
        ).all()
        states = {
            str(entity.id): "canonical" if entity.status == "canonical" else "candidate"
            for entity in entities
            if entity.status in {"canonical", "candidate", "draft"}
        }

    clue_rows = (
        await db.scalars(
            select(MapSpatialClueRecord)
            .where(
                MapSpatialClueRecord.novel_id == nid,
                MapSpatialClueRecord.scene_index < scene_index,
                MapSpatialClueRecord.status.in_(tuple(_VISIBLE_CLUE_STATUSES)),
            )
            .order_by(MapSpatialClueRecord.scene_index.desc(), MapSpatialClueRecord.id)
        )
    ).all()
    selected_clues: list[tuple[int, MapSpatialClueRecord, MapSpatialClue]] = []
    omitted_stale = 0
    requested_entities = {str(item) for item in endpoint_uuid_ids}
    working_evidence_keys: set[tuple[str, str, str]] = set()
    for row in clue_rows:
        same_run_working = (
            run_id is not None
            and row.run_id == run_id
            and row.source_content_mode == "working"
        )
        if row.source_content_mode != "canonical" and not same_run_working:
            omitted_stale += 1
            continue
        try:
            clue = MapSpatialClue.model_validate(row.clue_payload)
            binding = MapSpatialClueSourceBinding.model_validate(row.source_binding)
            resolved = await _resolve_binding(
                db,
                novel_id,
                row.scene_id,
                row.scene_index,
                binding,
            )
            source_hash = _matching_source_hash(clue, resolved)
        except (ConflictError, NotFoundError, ValidationError, ValueError, TypeError):
            omitted_stale += 1
            continue
        if same_run_working and clue.review.verdict == "supported":
            working_evidence_keys.add((row.scene_id, clue.quote, source_hash))
        bound_ids = {
            str(endpoint.entity_id)
            for endpoint in (clue.subject, clue.target)
            if endpoint is not None and endpoint.entity_id is not None
        }
        surfaces = {
            (endpoint.surface or "").casefold()
            for endpoint in (clue.subject, clue.target)
            if endpoint is not None and endpoint.surface is not None
        }
        score = (
            2
            if requested_entities & bound_ids
            else 1
            if set(endpoint_surfaces) & surfaces
            else 0
        )
        if (requested_entities or endpoint_surfaces) and score == 0:
            continue
        selected_clues.append((score, row, clue))
    selected_clues.sort(
        key=lambda item: (-item[0], -item[1].scene_index, str(item[1].id))
    )
    omitted_clues = omitted_stale + max(0, len(selected_clues) - clue_limit)
    clue_items = [
        MapSpatialClueContextItem(
            clue_id=row.id,
            scene_id=row.scene_id,
            scene_index=row.scene_index,
            clue_key=clue.clue_key,
            subject=clue.subject,
            target=clue.target,
            kind=clue.kind,
            relation=clue.relation,
            type_ref=clue.type_ref,
            modality=clue.modality,
            quote=clue.quote,
            status=row.status,
        )
        for _, row, clue in selected_clues[:clue_limit]
    ]

    type_rows = (
        await db.execute(
            select(ProjectVocabularyTerm, ProjectVocabularyRevision)
            .join(
                ProjectVocabularyRevision,
                and_(
                    ProjectVocabularyRevision.novel_id == ProjectVocabularyTerm.novel_id,
                    ProjectVocabularyRevision.term_id == ProjectVocabularyTerm.id,
                    ProjectVocabularyRevision.id
                    == ProjectVocabularyTerm.current_revision_id,
                ),
            )
            .where(
                ProjectVocabularyTerm.novel_id == nid,
                ProjectVocabularyTerm.kind.in_(_SPATIAL_KINDS),
                ProjectVocabularyTerm.status.in_(
                    ["active", "emerging", "archived", "merged"]
                ),
            )
        )
    ).all()
    clue_type_refs = {clue.type_ref for _, _, clue in selected_clues if clue.type_ref}
    type_items = []
    filtered_types = 0
    for term, revision in type_rows:
        snapshot = revision.snapshot_json
        evidence = []
        for raw in snapshot.get("evidence", []):
            try:
                item = VocabularyEvidence.model_validate(raw)
                evidence_scene = await get(STORY_SCENE_SOURCE).get_scene_contract(
                    db, novel_id, str(item.scene_id)
                )
                if (
                    evidence_scene is not None
                    and parse_uuid(evidence_scene.novel_id, "novel_id") == nid
                    and evidence_scene.scene_index < scene_index
                    and evidence_scene.status in {"draft", "canonical"}
                    and (
                        await _evidence_is_current(
                            db, novel_id, item, content_mode="canonical"
                        )
                        or (
                            (str(item.scene_id), item.quote, item.source_hash)
                            in working_evidence_keys
                            and await _evidence_is_current(
                                db, novel_id, item, content_mode="working"
                            )
                        )
                    )
                ):
                    evidence.append(item)
            except (ValidationError, ValueError, TypeError):
                continue
        projected_status = term.status
        if (
            term.source == "model"
            and not term.author_confirmed
            and term.status in {"active", "emerging"}
        ):
            if not evidence:
                filtered_types += 1
                continue
            projected_status = "emerging"
            try:
                reviewed = [
                    VocabularyEvidence.model_validate(raw)
                    for raw in snapshot.get("reviewed_evidence", [])
                ]
                receipt = VocabularyReviewReceipt.model_validate(
                    snapshot["independent_review"]
                )
                proposal_fields = VocabularyTermFields.model_validate(
                    {
                        key: snapshot[key]
                        for key in ("name", "description", "aliases", "traits")
                    }
                )
                evidence_keys = {
                    (str(item.scene_id), item.quote, item.source_hash)
                    for item in evidence
                }
                reviewed_keys = {
                    (str(item.scene_id), item.quote, item.source_hash)
                    for item in reviewed
                }
                if (
                    len({str(item.scene_id) for item in reviewed}) >= 2
                    and reviewed_keys.issubset(evidence_keys)
                    and receipt.proposal_run_id
                    == UUID(str(snapshot.get("proposal_run_id")))
                    and receipt.proposal_hash
                    == vocabulary_proposal_hash(term.kind, proposal_fields)
                    and receipt.evidence_hash == vocabulary_evidence_hash(reviewed)
                    and receipt.verdict == "passed"
                ):
                    projected_status = "active"
            except (KeyError, ValidationError, ValueError, TypeError):
                projected_status = "emerging"
        item = MapSpatialClueContextType.model_validate(
            {
                "id": term.id,
                "revision_id": revision.id,
                "kind": term.kind,
                "status": projected_status,
                "source": term.source,
                "name": snapshot["name"],
                "aliases": snapshot.get("aliases", []),
                "description": snapshot.get("description", ""),
                "traits": snapshot.get("traits", {}),
                "evidence": evidence,
                "proposal_run_id": snapshot.get("proposal_run_id"),
                "redirect_to_id": term.redirect_to_id,
            }
        )
        surface_keys = {
            item.name.casefold(),
            *(alias.casefold() for alias in item.aliases),
        }
        endpoint_score = int(bool(surface_keys & set(endpoint_surfaces)))
        clue_score = int(term.id in clue_type_refs)
        type_items.append(
            (
                (
                    -clue_score,
                    -endpoint_score,
                    item.status,
                    item.kind,
                    item.name.casefold(),
                    str(item.id),
                ),
                item,
            )
        )
    type_items.sort(key=lambda item: item[0])
    omitted_types = filtered_types + max(0, len(type_items) - type_limit)
    context_types = [item for _, item in type_items[:type_limit]]
    return MapSpatialClueContext(
        types=context_types,
        clues=clue_items,
        endpoint_states=states,
        omitted_types=omitted_types,
        omitted_clues=omitted_clues,
    )


async def list_spatial_clues(
    db: AsyncSession,
    novel_id: str,
    *,
    statuses: list[MapSpatialClueStatus] | None = None,
    scene_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> MapSpatialClueListResponse:
    await require_active_project(db, novel_id)
    if not 1 <= limit <= 200 or offset < 0:
        raise ValidationError("Spatial clue page is out of range")
    conditions = [MapSpatialClueRecord.novel_id == parse_uuid(novel_id, "novel_id")]
    if statuses:
        conditions.append(MapSpatialClueRecord.status.in_(statuses))
    if scene_id is not None:
        conditions.append(
            MapSpatialClueRecord.scene_id == str(parse_uuid(scene_id, "scene_id"))
        )
    total = int(
        (
            await db.scalar(
                select(func.count()).select_from(MapSpatialClueRecord).where(*conditions)
            )
        )
        or 0
    )
    rows = (
        await db.scalars(
            select(MapSpatialClueRecord)
            .where(*conditions)
            .order_by(
                MapSpatialClueRecord.scene_index.desc(),
                MapSpatialClueRecord.created_at.desc(),
                MapSpatialClueRecord.id,
            )
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return MapSpatialClueListResponse(
        items=[_response(row) for row in rows], total_count=total
    )


async def review_spatial_clue(
    db: AsyncSession,
    novel_id: str,
    clue_id: str,
    data: MapSpatialClueDecisionRequest,
    *,
    decided_by: str = "author",
) -> MapSpatialClueResponse:
    await _lock_project_for_spatial_write(db, novel_id)
    nid = parse_uuid(novel_id, "novel_id")
    row = await db.scalar(
        select(MapSpatialClueRecord)
        .where(
            MapSpatialClueRecord.novel_id == nid,
            MapSpatialClueRecord.id == parse_uuid(clue_id, "clue_id"),
        )
        .with_for_update()
    )
    if row is None:
        raise NotFoundError("空间线索不存在")
    if row.fingerprint != data.expected_fingerprint:
        raise ConflictError("线索候选已变化，请刷新后再审")
    if row.status not in {"pending_review", "pending_verification", "adopted"}:
        raise ConflictError("该线索候选已结束审核")

    if data.action == "merge":
        target = await db.scalar(
            select(MapSpatialClueRecord)
            .where(
                MapSpatialClueRecord.novel_id == nid,
                MapSpatialClueRecord.id == data.target_clue_id,
            )
            .with_for_update()
        )
        if target is None or target.id == row.id:
            raise NotFoundError("合并目标线索不存在")
        if target.fingerprint != data.target_fingerprint:
            raise ConflictError("合并目标已变化，请刷新后重试")
        if target.status not in {"pending_review", "pending_verification", "adopted"}:
            raise ConflictError("只能合并到仍可审阅的线索")
        source_clue = MapSpatialClue.model_validate(row.clue_payload)
        target_clue = MapSpatialClue.model_validate(target.clue_payload)
        if _semantic_signature(source_clue) != _semantic_signature(target_clue):
            raise ValidationError("只有端点、关系和属性一致的线索才能合并")
        row.status = "superseded"
        row.merged_into_id = target.id
        row.decision_action = "merge"
        row.decision_reason = data.reason.strip() or None
        row.decided_by = decided_by[:128]
        row.decided_at = datetime.now(UTC)
        await _invalidate_auto_drafts_for_clue(db, novel_id, str(row.id))
        await db.flush()
        return _response(row)

    if data.action == "reject":
        row.status = "rejected"
        row.decision_action = "reject"
        row.decision_reason = data.reason.strip() or None
        row.decided_by = decided_by[:128]
        row.decided_at = datetime.now(UTC)
        await _invalidate_auto_drafts_for_clue(db, novel_id, str(row.id))
        await db.flush()
        return _response(row)

    if row.status != "pending_review":
        raise ConflictError("待核线索不能直接采用，请先完成来源或复核核查")
    clue = MapSpatialClue.model_validate(row.clue_payload)
    try:
        await _revalidate_stored_clue(db, novel_id, row, clue)
    except (ConflictError, NotFoundError, ValidationError, ValueError, TypeError):
        row.status = "pending_verification"
        row.verification_note = "原文或场景边界已经变化，请重新提取并核查。"
        await db.flush()
        return _response(row)
    row.status = "adopted"
    row.verification_note = "作者已确认该线索候选；尚未写入正式地图版本。"
    row.decision_action = "adopt"
    row.decision_reason = data.reason.strip() or None
    row.decided_by = decided_by[:128]
    row.decided_at = datetime.now(UTC)
    await db.flush()
    return _response(row)


__all__ = [
    "list_spatial_clues",
    "read_spatial_discovery_context",
    "review_spatial_clue",
    "spatial_clue_review_hash",
    "stage_spatial_discovery",
]
