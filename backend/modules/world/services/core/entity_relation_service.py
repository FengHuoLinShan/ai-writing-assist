"""EntityRelationService — 关系 CRUD。继承 BaseCRUDService (ADR-0002)。"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from core.crud import CrudService
from core.errors import ConflictError, NotFoundError, ValidationError
from core.logging_context import (
    exception_summary_for_log,
    identifier_for_log,
    novel_id_for_log,
)
from modules.world.models import EntityRelation
from modules.world.repositories import (
    CoreEntityRepository,
    EntityRelationRepository,
)
from modules.world.schemas import (
    EntityRelationCreate,
    EntityRelationListResponse,
    EntityRelationResponse,
    EntityRelationReviewBatchDecision,
    EntityRelationReviewBatchRequest,
    EntityRelationReviewEditRequest,
    EntityRelationReviewGroupListResponse,
    EntityRelationUpdate,
    ReviewBatchResponse,
    WorldEntityContext,
)
from modules.world.services.common import parse_uuid
from modules.world.services.core.review_queue import (
    stable_fingerprint,
    suggest_relation_type,
)
from shared.constants import MAX_PAGE_SIZE


def _merge_text(existing: str | None, incoming: str | None) -> str | None:
    current = (existing or "").strip()
    addition = (incoming or "").strip()
    if not addition:
        return current or None
    if not current:
        return addition
    if addition in current:
        return current
    return f"{current}\n{addition}"


_RELATION_ENDPOINT_STATUSES = {"canonical", "draft", "candidate"}
_RELATION_STATUSES = {"candidate", "canonical", "deprecated"}
logger = logging.getLogger(__name__)


class _StaleReviewDecisionError(Exception):
    pass


class EntityRelationService(
    CrudService[
        EntityRelation, EntityRelationCreate, EntityRelationUpdate, EntityRelationResponse
    ],  # noqa: E501
):
    """关系业务服务。

    5 verb 继承自 base; expand_related 跨表, upsert 去重, 留作特例。
    """

    repo = EntityRelationRepository()
    response = EntityRelationResponse
    label = "EntityRelation"
    id_param = "relation_id"

    # expand_related 跨表, 需要第二个 repo — 留作 __init__ 注入
    # (避开 base 的单 repo 假设, 显式化)
    def __init__(self, context_marker=None) -> None:
        # base 的 CrudService 假设单 repo, 跨表操作是例外
        self._entity_repo = CoreEntityRepository()
        self._context_marker = context_marker

    async def _require_distinct_entities_in_novel(
        self,
        db: AsyncSession,
        nid,
        sid,
        tid,
    ):
        if sid == tid:
            raise ValidationError("source_id and target_id must be different")

        source = await self._entity_repo.get(db, sid)
        target = await self._entity_repo.get(db, tid)
        if (
            source is None
            or target is None
            or source.novel_id != nid
            or target.novel_id != nid
        ):
            raise NotFoundError("Source or target entity not found in this novel")
        return source, target

    def _assert_active_relation_endpoint(self, entity: Any, field_name: str) -> None:
        if getattr(entity, "status", None) not in _RELATION_ENDPOINT_STATUSES:
            raise ValidationError(f"{field_name} must be an active entity")
        meta = dict((getattr(entity, "content_json", None) or {}).get("_meta") or {})
        if (
            getattr(entity, "status", None) in {"draft", "candidate"}
            and meta.get("compatibility_shadow") is True
            and meta.get("suggestion_id")
        ):
            raise ValidationError(
                f"{field_name} must adopt its authoritative suggestion first"
            )

    def _relation_snapshot(self, rel: EntityRelation) -> dict[str, object]:
        return {
            "id": str(rel.id),
            "source_id": str(rel.source_id),
            "target_id": str(rel.target_id),
            "relation_type": rel.relation_type,
            "description": rel.description,
            "strength": rel.strength,
            "status": rel.status,
        }

    def _relation_execution_snapshot(self, rel: EntityRelation) -> dict[str, object]:
        updated_at = rel.updated_at
        if updated_at is not None and updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=UTC)
        return {
            **self._relation_snapshot(rel),
            "quote": rel.quote,
            "source_chapter_id": str(rel.source_chapter_id)
            if rel.source_chapter_id
            else None,
            "caused_by_event_id": str(rel.caused_by_event_id)
            if rel.caused_by_event_id
            else None,
            "review_meta": rel.review_meta or {},
            "updated_at": updated_at.astimezone(UTC).isoformat() if updated_at else None,
        }

    def _group_execution_fingerprint(self, relations: list[EntityRelation]) -> str:
        return stable_fingerprint(
            [
                self._relation_execution_snapshot(relation)
                for relation in sorted(relations, key=lambda item: str(item.id))
            ]
        )

    @staticmethod
    def _review_group_id(source_id: object, target_id: object) -> str:
        return f"relation-pair-{stable_fingerprint([source_id, target_id])[:24]}"

    @staticmethod
    def _dedupe_evidence_refs(relations: list[EntityRelation]) -> list[dict]:
        refs: list[dict] = []
        seen: set[str] = set()
        for relation in relations:
            meta = dict(relation.review_meta or {})
            candidates = list(meta.get("evidence_refs") or [])
            fallback = {
                key: value
                for key, value in {
                    "source_type": "scene" if meta.get("scene_id") else None,
                    "scene_id": meta.get("scene_id"),
                    "scene_index": meta.get("scene_index"),
                    "source_chapter_index": meta.get("source_chapter_index"),
                    "quote": relation.quote or meta.get("quote"),
                }.items()
                if value is not None and value != ""
            }
            if fallback:
                candidates.append(fallback)
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                key = stable_fingerprint(candidate)
                if key in seen:
                    continue
                seen.add(key)
                refs.append(dict(candidate))
        return refs

    @staticmethod
    def _merge_quotes(relations: list[EntityRelation]) -> str | None:
        quotes: list[str] = []
        for relation in relations:
            for quote in [relation.quote, (relation.review_meta or {}).get("quote")]:
                normalized = str(quote or "").strip()
                if normalized and normalized not in quotes:
                    quotes.append(normalized)
        return "\n".join(quotes) or None

    def _review_meta(
        self,
        *,
        action: str,
        before: dict[str, object],
        after: dict[str, object],
        reviewed_from: str,
    ) -> dict[str, object]:
        return {
            "reviewed_at": datetime.now(UTC).isoformat(),
            "reviewed_by": "manual",
            "reviewed_from": reviewed_from,
            "review_action": action,
            "review_before": before,
            "review_after": after,
        }

    def _response_with_endpoint_names(
        self,
        rel: EntityRelation,
        endpoint_names: dict[str, str] | None = None,
    ) -> EntityRelationResponse:
        response = EntityRelationResponse.model_validate(rel)
        source_name = (
            endpoint_names.get(str(rel.source_id))
            if endpoint_names is not None
            else (rel.source.name if rel.source is not None else None)
        )
        target_name = (
            endpoint_names.get(str(rel.target_id))
            if endpoint_names is not None
            else (rel.target.name if rel.target is not None else None)
        )
        return response.model_copy(
            update={
                "source_name": source_name,
                "target_name": target_name,
            }
        )

    def _to_response(self, obj: EntityRelation) -> EntityRelationResponse:
        return self._response_with_endpoint_names(obj)

    async def rollback_deep_import_candidates_by_workflow(
        self,
        db: AsyncSession,
        novel_id: str,
        workflow_id: str,
    ) -> int:
        """Archive untouched candidate relations owned by one import workflow."""
        nid = parse_uuid(novel_id, "novel_id")
        result = await db.execute(
            select(EntityRelation)
            .where(
                EntityRelation.novel_id == nid,
                EntityRelation.status == "candidate",
            )
            .with_for_update()
        )
        rolled_back_at = datetime.now(UTC).isoformat()
        count = 0
        for relation in result.scalars().all():
            meta = dict(relation.review_meta or {})
            if (
                meta.get("workflow_id") != workflow_id
                or meta.get("user_edited") is True
                or meta.get("reviewed_by") == "manual"
            ):
                continue
            relation.status = "deprecated"
            relation.review_meta = {
                **meta,
                "rolled_back": True,
                "rolled_back_at": rolled_back_at,
                "rollback_reason": "workflow_abandoned",
            }
            db.add(relation)
            count += 1
        await db.flush()
        return count

    # ============================================================
    # Override: create 加端点有效性与重复校验
    # ============================================================

    async def create(  # type: ignore[override]
        self,
        db: AsyncSession,
        novel_id: str,
        data: EntityRelationCreate,
        *,
        _validation_prechecked: bool = False,
    ) -> EntityRelationResponse:
        if data.status == "canonical" and not _validation_prechecked:
            await self._require_legacy_canon_write_allowed(db, novel_id)
        nid = parse_uuid(novel_id, "novel_id")
        sid = parse_uuid(data.source_id, "source_id")
        tid = parse_uuid(data.target_id, "target_id")

        source, target = await self._require_distinct_entities_in_novel(
            db,
            nid,
            sid,
            tid,
        )
        self._assert_active_relation_endpoint(source, "source_id")
        self._assert_active_relation_endpoint(target, "target_id")

        duplicate = await self.repo.find_duplicate_relation(
            db,
            nid,
            sid,
            tid,
            data.relation_type,
        )
        if duplicate is not None:
            raise ConflictError("Relation already exists")

        created = await super().create(db, novel_id, data)
        response = created.model_copy(
            update={
                "source_name": getattr(source, "name", ""),
                "target_name": getattr(target, "name", ""),
            }
        )
        if created.status == "canonical":
            await self._mark_synopsis_changed(db, novel_id, created.id)
        return response

    async def create_or_merge(
        self,
        db: AsyncSession,
        novel_id: str,
        data: EntityRelationCreate,
        *,
        _validation_prechecked: bool = False,
    ) -> dict[str, object]:
        """Create a relation or merge evidence into an existing same edge."""

        if data.status == "canonical" and not _validation_prechecked:
            await self._require_legacy_canon_write_allowed(db, novel_id)

        nid = parse_uuid(novel_id, "novel_id")
        sid = parse_uuid(data.source_id, "source_id")
        tid = parse_uuid(data.target_id, "target_id")
        source, target = await self._require_distinct_entities_in_novel(
            db,
            nid,
            sid,
            tid,
        )
        self._assert_active_relation_endpoint(source, "source_id")
        self._assert_active_relation_endpoint(target, "target_id")

        existing = await self.repo.find_duplicate_relation(
            db,
            nid,
            sid,
            tid,
            data.relation_type,
        )
        if existing is None:
            created = await super().create(db, novel_id, data)
            response = created.model_copy(
                update={
                    "source_name": getattr(source, "name", ""),
                    "target_name": getattr(target, "name", ""),
                }
            )
            if created.status == "canonical":
                await self._mark_synopsis_changed(db, novel_id, created.id)
            return {"action": "created", "relation": response}

        # A review-only import must never mutate an already adopted relation.
        # Treat the matching active edge as deterministic dedup and leave its
        # content, provenance, and strength untouched until an author makes an
        # explicit decision through the suggestion/review flow.
        if existing.status == "canonical" and data.status != "canonical":
            return {
                "action": "deduplicated",
                "relation": self._response_with_endpoint_names(existing),
            }

        existing.description = _merge_text(existing.description, data.description)
        existing.quote = _merge_text(existing.quote, data.quote)
        existing.strength = max(
            float(existing.strength if existing.strength is not None else 0.0),
            float(data.strength),
        )
        if data.review_meta:
            existing.review_meta = {
                **(existing.review_meta or {}),
                **data.review_meta,
            }
        if existing.status != "canonical" and data.status:
            existing.status = data.status
        if existing.source_chapter_id is None and data.source_chapter_id:
            existing.source_chapter_id = parse_uuid(data.source_chapter_id)
        if existing.caused_by_event_id is None and data.caused_by_event_id:
            existing.caused_by_event_id = parse_uuid(data.caused_by_event_id)
        db.add(existing)
        await db.flush()
        response = EntityRelationResponse.model_validate(existing).model_copy(
            update={
                "source_name": getattr(source, "name", ""),
                "target_name": getattr(target, "name", ""),
            }
        )
        if existing.status == "canonical":
            await self._mark_synopsis_changed(db, novel_id, existing.id)
        return {"action": "merged", "relation": response}

    async def list_review_groups(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        q: str | None = None,
        relation_type: str | None = None,
        source_chapter_id: str | None = None,
        scene_id: str | None = None,
        scene_index: int | None = None,
        source_chapter_index: int | None = None,
        strength_min: float | None = None,
        strength_max: float | None = None,
        has_quote: bool | None = None,
        type_kind: str | None = None,
        multi_type_only: bool = False,
        skip: int = 0,
        limit: int = 20,
    ) -> EntityRelationReviewGroupListResponse:
        nid = parse_uuid(novel_id, "novel_id")
        chapter_id = (
            parse_uuid(source_chapter_id, "source_chapter_id")
            if source_chapter_id
            else None
        )
        # A filter decides which directed pairs enter the result.  Once a pair
        # matches, the response must contain its complete candidate snapshot;
        # otherwise its fingerprint can never be submitted successfully.
        candidates = await self.repo.list_review_candidates(db, nid)
        normalized_query = str(q or "").strip().casefold()

        def matches(relation: EntityRelation) -> bool:
            meta = dict(relation.review_meta or {})
            if relation_type and relation.relation_type != relation_type:
                return False
            if chapter_id and relation.source_chapter_id != chapter_id:
                return False
            if (
                strength_min is not None
                and float(relation.strength if relation.strength is not None else 0.0)
                < strength_min
            ):
                return False
            if (
                strength_max is not None
                and float(relation.strength if relation.strength is not None else 0.0)
                > strength_max
            ):
                return False
            if normalized_query:
                haystack = " ".join(
                    str(value or "")
                    for value in (
                        relation.relation_type,
                        relation.description,
                        relation.quote,
                        getattr(relation.source, "name", None),
                        getattr(relation.target, "name", None),
                    )
                ).casefold()
                if normalized_query not in haystack:
                    return False
            if scene_id and str(meta.get("scene_id") or "") != scene_id:
                return False
            if scene_index is not None and meta.get("scene_index") != scene_index:
                return False
            if (
                source_chapter_index is not None
                and meta.get("source_chapter_index") != source_chapter_index
            ):
                return False
            quote_present = bool(
                str(relation.quote or meta.get("quote") or "").strip()
                or meta.get("evidence_refs")
            )
            if has_quote is not None and quote_present is not has_quote:
                return False
            suggested = suggest_relation_type(relation.relation_type)
            is_recommended = suggested == relation.relation_type
            if type_kind == "recommended" and not is_recommended:
                return False
            if type_kind == "custom" and is_recommended:
                return False
            return True

        all_grouped: dict[tuple[str, str], list[EntityRelation]] = {}
        for relation in candidates:
            key = (str(relation.source_id), str(relation.target_id))
            all_grouped.setdefault(key, []).append(relation)
        matched_pairs = {
            (str(relation.source_id), str(relation.target_id))
            for relation in candidates
            if matches(relation)
        }
        grouped = {
            key: members for key, members in all_grouped.items() if key in matched_pairs
        }
        if multi_type_only:
            grouped = {
                key: items
                for key, items in grouped.items()
                if len({item.relation_type for item in items}) > 1
            }

        pair_keys = set(grouped)
        canonical_by_pair: dict[tuple[str, str], list[EntityRelation]] = {}
        if pair_keys:
            lookup_pairs = {
                (members[0].source_id, members[0].target_id)
                for members in grouped.values()
            }
            lookup_pairs.update(
                (target_id, source_id) for source_id, target_id in lookup_pairs.copy()
            )
            canonical = await self.repo.list_canonical_pairs(db, nid, list(lookup_pairs))
            for relation in canonical:
                key = (str(relation.source_id), str(relation.target_id))
                canonical_by_pair.setdefault(key, []).append(relation)

        ordered_groups = sorted(
            grouped.items(),
            key=lambda item: max(
                relation.created_at or datetime.min.replace(tzinfo=UTC)
                for relation in item[1]
            ),
            reverse=True,
        )
        item_total = sum(len(items) for _key, items in ordered_groups)
        page = ordered_groups[skip : skip + min(limit, MAX_PAGE_SIZE)]
        groups: list[dict[str, object]] = []
        for (source_id, target_id), members in page:
            members = sorted(
                members,
                key=lambda relation: (
                    -(relation.strength if relation.strength is not None else 0.0),
                    relation.relation_type,
                    str(relation.id),
                ),
            )
            first = members[0]
            reverse_members = all_grouped.get((target_id, source_id), [])
            member_payloads: list[dict[str, object]] = []
            scene_indices: set[int] = set()
            chapter_indices: set[int] = set()
            evidence_count = 0
            for relation in members:
                meta = dict(relation.review_meta or {})
                if isinstance(meta.get("scene_index"), int):
                    scene_indices.add(meta["scene_index"])
                if isinstance(meta.get("source_chapter_index"), int):
                    chapter_indices.add(meta["source_chapter_index"])
                refs = list(meta.get("evidence_refs") or [])
                quote = relation.quote or meta.get("quote")
                evidence_count += max(len(refs), 1 if quote else 0)
                suggested = suggest_relation_type(relation.relation_type)
                payload = self._response_with_endpoint_names(relation).model_dump(
                    mode="json"
                )
                payload.update(
                    {
                        "suggested_relation_type": suggested,
                        "type_kind": "recommended"
                        if suggested == relation.relation_type
                        else "custom",
                        "evidence_summary": {
                            "source": meta.get("source"),
                            "workflow_id": meta.get("workflow_id"),
                            "scene_id": meta.get("scene_id"),
                            "scene_index": meta.get("scene_index"),
                            "source_chapter_index": meta.get("source_chapter_index"),
                            "quote": quote,
                            "evidence_refs": refs,
                        },
                    }
                )
                member_payloads.append(payload)
            groups.append(
                {
                    "group_id": self._review_group_id(source_id, target_id),
                    "source_id": source_id,
                    "source_name": getattr(first.source, "name", None),
                    "target_id": target_id,
                    "target_name": getattr(first.target, "name", None),
                    "member_count": len(members),
                    "type_variants": sorted(
                        {relation.relation_type for relation in members}
                    ),
                    "evidence_count": evidence_count,
                    "scene_indices": sorted(scene_indices),
                    "source_chapter_indices": sorted(chapter_indices),
                    "members": member_payloads,
                    "canonical_relations": [
                        self._response_with_endpoint_names(relation).model_dump(
                            mode="json"
                        )
                        for relation in canonical_by_pair.get((source_id, target_id), [])
                    ],
                    "reverse_candidate_count": len(reverse_members),
                    "reverse_type_variants": sorted(
                        {relation.relation_type for relation in reverse_members}
                    ),
                    "reverse_canonical_relations": [
                        self._response_with_endpoint_names(relation).model_dump(
                            mode="json"
                        )
                        for relation in canonical_by_pair.get((target_id, source_id), [])
                    ],
                    "execution_fingerprint": self._group_execution_fingerprint(members),
                }
            )
        return EntityRelationReviewGroupListResponse(
            groups=groups,
            group_total=len(ordered_groups),
            item_total=item_total,
            skip=skip,
            limit=min(limit, MAX_PAGE_SIZE),
        )

    async def _prelock_review_batch(
        self,
        db: AsyncSession,
        novel_id: str,
        data: EntityRelationReviewBatchRequest,
    ) -> None:
        """Acquire every predictable batch lock before any savepoint writes."""
        nid = parse_uuid(novel_id, "novel_id")
        member_ids = []
        endpoint_ids = []
        canonical_targets = []
        for decision in data.decisions:
            for relation_id in decision.member_relation_ids:
                try:
                    member_ids.append(parse_uuid(relation_id, "relation_id"))
                except Exception:
                    continue
            if decision.action not in {"accept", "merge"}:
                continue
            try:
                source_id = parse_uuid(decision.source_id, "source_id")
                target_id = parse_uuid(decision.target_id, "target_id")
            except Exception:
                continue
            endpoint_ids.extend([source_id, target_id])
            canonical_targets.append(
                (source_id, target_id, str(decision.relation_type or "").strip())
            )

        seeds = []
        for relation_id in sorted(set(member_ids), key=str):
            relation = await self.repo.get(db, relation_id)
            if (
                relation is not None
                and relation.novel_id == nid
                and relation.status == "candidate"
            ):
                seeds.append(relation)
        pairs = {(item.source_id, item.target_id) for item in seeds}
        candidate_rows = await self.repo.list_candidate_pairs(db, nid, list(pairs))
        canonical_rows = await self.repo.list_canonical_targets(
            db,
            nid,
            [target for target in canonical_targets if target[2]],
        )

        # Entity rows are shared with alias/fusion workflows, so lock them
        # first; each table then uses a single UUID order for the whole batch.
        await self._entity_repo.get_many_for_update(db, nid, endpoint_ids)
        await self.repo.get_many_for_update(
            db,
            nid,
            [row.id for row in [*candidate_rows, *canonical_rows]],
        )

    async def review_batch(
        self,
        db: AsyncSession,
        novel_id: str,
        data: EntityRelationReviewBatchRequest,
    ) -> ReviewBatchResponse:
        if any(item.action in {"accept", "merge"} for item in data.decisions):
            await self._require_legacy_canon_write_allowed(db, novel_id)
        await self._prelock_review_batch(db, novel_id, data)
        results: list[dict[str, object]] = []
        for decision in data.decisions:
            try:
                async with db.begin_nested():
                    result = await self._apply_review_decision(db, novel_id, decision)
                results.append(
                    {
                        "client_decision_id": decision.client_decision_id,
                        "status": "success",
                        "action": decision.action,
                        **result,
                    }
                )
            except _StaleReviewDecisionError:
                results.append(
                    {
                        "client_decision_id": decision.client_decision_id,
                        "status": "stale",
                        "action": decision.action,
                        "error_code": "stale_execution",
                        "message": "待处理关系已发生变化，请刷新后重试",
                    }
                )
            except SQLAlchemyError:
                # Do not flatten a persistence fault into a normal item result;
                # the outer transaction must roll back and surface the failure.
                raise
            except Exception as exc:
                results.append(
                    {
                        "client_decision_id": decision.client_decision_id,
                        "status": "failed",
                        "action": decision.action,
                        "error_code": getattr(exc, "code", "review_failed"),
                        "message": getattr(exc, "message", "关系复核失败"),
                    }
                )
        succeeded = sum(item["status"] == "success" for item in results)
        stale = sum(item["status"] == "stale" for item in results)
        return ReviewBatchResponse(
            requested_count=len(data.decisions),
            succeeded_count=succeeded,
            stale_count=stale,
            failed_count=len(results) - succeeded - stale,
            results=results,
        )

    async def _apply_review_decision(
        self,
        db: AsyncSession,
        novel_id: str,
        decision: EntityRelationReviewBatchDecision,
    ) -> dict[str, object]:
        nid = parse_uuid(novel_id, "novel_id")
        member_ids = [
            parse_uuid(relation_id, "relation_id")
            for relation_id in decision.member_relation_ids
        ]
        seed = await self.repo.get(db, sorted(member_ids)[0])
        if seed is None or seed.novel_id != nid or seed.status != "candidate":
            raise _StaleReviewDecisionError
        locked = await self.repo.get_candidate_pair_for_update(
            db,
            nid,
            seed.source_id,
            seed.target_id,
        )
        if decision.group_id != self._review_group_id(
            seed.source_id,
            seed.target_id,
        ):
            raise _StaleReviewDecisionError
        if self._group_execution_fingerprint(locked) != (
            decision.expected_execution_fingerprint
        ):
            raise _StaleReviewDecisionError
        locked_by_id = {str(relation.id): relation for relation in locked}
        selected = [
            locked_by_id[relation_id]
            for relation_id in decision.member_relation_ids
            if relation_id in locked_by_id
        ]
        if len(selected) != len(decision.member_relation_ids):
            raise _StaleReviewDecisionError
        if len({(item.source_id, item.target_id) for item in locked}) != 1:
            raise ValidationError("review group must use one directed entity pair")

        if decision.action == "ignore":
            archived: list[str] = []
            for relation in selected:
                before = self._relation_execution_snapshot(relation)
                relation.status = "deprecated"
                after = self._relation_execution_snapshot(relation)
                relation.review_meta = {
                    **(relation.review_meta or {}),
                    **self._review_meta(
                        action="relation_review_ignored",
                        before=before,
                        after=after,
                        reviewed_from="world_relations_review_batch",
                    ),
                }
                db.add(relation)
                archived.append(str(relation.id))
            await db.flush()
            return {
                "affected_ids": archived,
                "archived_relation_ids": archived,
            }

        sid = parse_uuid(decision.source_id, "source_id")
        tid = parse_uuid(decision.target_id, "target_id")
        relation_type = str(decision.relation_type or "").strip()
        if sid == tid:
            raise ValidationError("source_id and target_id must be different")
        endpoints = await self._entity_repo.get_many_for_update(db, nid, [sid, tid])
        endpoint_by_id = {entity.id: entity for entity in endpoints}
        source = endpoint_by_id.get(sid)
        target = endpoint_by_id.get(tid)
        if source is None or target is None:
            raise NotFoundError("Source or target entity not found in this novel")
        self._assert_active_relation_endpoint(source, "source_id")
        self._assert_active_relation_endpoint(target, "target_id")
        primary = locked_by_id.get(str(decision.primary_relation_id))
        if primary is None or primary not in selected:
            raise _StaleReviewDecisionError

        canonical = await self.repo.find_canonical_relation(
            db, nid, sid, tid, relation_type
        )
        target_relation = canonical or primary
        if canonical is None:
            duplicate = await self.repo.find_duplicate_relation(
                db,
                nid,
                sid,
                tid,
                relation_type,
                exclude_rel_id=primary.id,
            )
            if duplicate is not None and duplicate not in selected:
                raise ConflictError(f"Relation already exists: {duplicate.id}")

        selected_snapshots = {
            str(relation.id): self._relation_execution_snapshot(relation)
            for relation in selected
        }
        original_endpoint_ids = {
            str(endpoint_id)
            for relation in locked
            for endpoint_id in (relation.source_id, relation.target_id)
        }
        before = self._relation_execution_snapshot(target_relation)
        evidence_sources = list(
            {
                str(relation.id): relation for relation in [target_relation, *selected]
            }.values()
        )
        merged_quote = self._merge_quotes(evidence_sources)
        merged_evidence_refs = self._dedupe_evidence_refs(evidence_sources)
        target_relation.source_id = sid
        target_relation.target_id = tid
        target_relation.relation_type = relation_type
        target_relation.description = decision.description
        if decision.strength is not None:
            target_relation.strength = decision.strength
        target_relation.quote = merged_quote
        target_relation.status = "canonical"
        after = self._relation_execution_snapshot(target_relation)
        current_meta = dict(target_relation.review_meta or {})
        history = list(current_meta.get("review_history") or [])
        history.append(
            {
                **self._review_meta(
                    action=f"relation_review_{decision.action}",
                    before=before,
                    after=after,
                    reviewed_from="world_relations_review_batch",
                ),
                "merged_relation_ids": [str(item.id) for item in selected],
                "merged_sources": [
                    {
                        "relation": selected_snapshots[str(item.id)],
                    }
                    for item in selected
                ],
            }
        )
        target_relation.review_meta = {
            **current_meta,
            "evidence_refs": merged_evidence_refs,
            "review_history": history,
            **self._review_meta(
                action=f"relation_review_{decision.action}",
                before=before,
                after=after,
                reviewed_from="world_relations_review_batch",
            ),
        }
        db.add(target_relation)

        archived: list[str] = []
        for relation in selected:
            if relation.id == target_relation.id:
                continue
            member_before = selected_snapshots[str(relation.id)]
            relation.status = "deprecated"
            member_after = self._relation_execution_snapshot(relation)
            relation.review_meta = {
                **(relation.review_meta or {}),
                "merged_into_relation_id": str(target_relation.id),
                **self._review_meta(
                    action="relation_review_merged",
                    before=member_before,
                    after=member_after,
                    reviewed_from="world_relations_review_batch",
                ),
            }
            db.add(relation)
            archived.append(str(relation.id))
        await db.flush()
        await self._mark_synopsis_changed(db, novel_id, target_relation.id)
        await self._mark_endpoint_context_changed(
            db,
            novel_id=novel_id,
            entity_ids={
                str(sid),
                str(tid),
                *original_endpoint_ids,
            },
        )
        affected = [str(target_relation.id), *archived]
        return {
            "affected_ids": list(dict.fromkeys(affected)),
            "canonical_relation_id": str(target_relation.id),
            "archived_relation_ids": archived,
        }

    async def list(  # type: ignore[override]
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        status: str | None = None,
        relation_type: str | None = None,
        q: str | None = None,
        source_chapter_id: str | None = None,
        strength_min: float | None = None,
        strength_max: float | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> EntityRelationListResponse:
        nid = parse_uuid(novel_id, "novel_id")
        chapter_id = (
            parse_uuid(source_chapter_id, "source_chapter_id")
            if source_chapter_id
            else None
        )
        limit = min(limit, MAX_PAGE_SIZE)
        relations, total = await self.repo.get_by_novel(
            db,
            nid,
            status=status,
            relation_type=relation_type,
            q=q,
            source_chapter_id=chapter_id,
            strength_min=strength_min,
            strength_max=strength_max,
            skip=skip,
            limit=limit,
        )
        endpoint_ids = list(
            {
                endpoint_id
                for relation in relations
                for endpoint_id in (relation.source_id, relation.target_id)
            }
        )
        endpoints = await self._entity_repo.get_by_ids(db, nid, endpoint_ids)
        endpoint_names = {str(entity.id): entity.name for entity in endpoints}
        return EntityRelationListResponse(
            items=[
                self._response_with_endpoint_names(rel, endpoint_names)
                for rel in relations
            ],
            total=total,
        )

    async def update(  # type: ignore[override]
        self,
        db: AsyncSession,
        id: str,
        data: EntityRelationUpdate,
        *,
        novel_id: str,
    ) -> EntityRelationResponse:
        rid = parse_uuid(id, self.id_param)
        nid = parse_uuid(novel_id, "novel_id")
        rel = await self.repo.get(db, rid)
        if rel is None or rel.novel_id != nid:
            raise NotFoundError(f"EntityRelation {id} not found")
        if rel.status == "canonical" or data.status == "canonical":
            await self._require_legacy_canon_write_allowed(db, novel_id)
        before = self._relation_snapshot(rel)
        if data.status is not None and data.status not in _RELATION_STATUSES:
            raise ValidationError("Invalid relation status")
        updated = await self.repo.update(db, rel, data)
        if updated is None:
            raise NotFoundError(f"EntityRelation {id} not found")
        if data.status is not None and before["status"] != updated.status:
            after = self._relation_snapshot(updated)
            updated.review_meta = {
                **(updated.review_meta or {}),
                **self._review_meta(
                    action="relation_status_updated",
                    before=before,
                    after=after,
                    reviewed_from="world_relations_update",
                ),
            }
            db.add(updated)
            await db.flush()
        if before["status"] == "canonical" or updated.status == "canonical":
            await self._mark_synopsis_changed(db, novel_id, updated.id)
        return self._response_with_endpoint_names(updated)

    async def review_edit(
        self,
        db: AsyncSession,
        novel_id: str,
        rel_id: str,
        data: EntityRelationReviewEditRequest,
    ) -> dict[str, object]:
        nid = parse_uuid(novel_id, "novel_id")
        rid = parse_uuid(rel_id, self.id_param)
        rel = await self.repo.get(db, rid)
        if rel is None or rel.novel_id != nid:
            raise NotFoundError(f"EntityRelation {rel_id} not found")
        if rel.status == "deprecated":
            raise ValidationError("Deprecated relation cannot be reviewed")
        if rel.status == "canonical" or data.confirm_review:
            await self._require_legacy_canon_write_allowed(db, novel_id)

        before = self._relation_snapshot(rel)
        sid = parse_uuid(data.source_id, "source_id") if data.source_id else rel.source_id
        tid = parse_uuid(data.target_id, "target_id") if data.target_id else rel.target_id
        relation_type = (data.relation_type or rel.relation_type or "").strip()
        if not relation_type:
            raise ValidationError("relation_type cannot be blank")
        source, target = await self._require_distinct_entities_in_novel(
            db,
            nid,
            sid,
            tid,
        )
        self._assert_active_relation_endpoint(source, "source_id")
        self._assert_active_relation_endpoint(target, "target_id")

        duplicate = await self.repo.find_duplicate_relation(
            db,
            nid,
            sid,
            tid,
            relation_type,
            exclude_rel_id=rid,
        )
        if duplicate is not None:
            raise ConflictError(f"Relation already exists: {duplicate.id}")

        rel.source_id = sid
        rel.target_id = tid
        rel.relation_type = relation_type
        if data.description is not None:
            rel.description = data.description
        if data.strength is not None:
            rel.strength = data.strength
        if data.confirm_review:
            rel.status = "canonical"

        after = self._relation_snapshot(rel)
        rel.review_meta = {
            **(rel.review_meta or {}),
            **self._review_meta(
                action="relation_review_edit",
                before=before,
                after=after,
                reviewed_from="world_relations_review_edit",
            ),
        }
        db.add(rel)
        await db.flush()
        rel = await self.repo.get(db, rid) or rel
        response = self._response_with_endpoint_names(rel)
        if before["status"] == "canonical" or rel.status == "canonical":
            await self._mark_synopsis_changed(db, novel_id, rel.id)
        return {
            "relation": response.model_dump(mode="json"),
            "affected_ids": [str(rel.id)],
            "review_meta": rel.review_meta or {},
        }

    @staticmethod
    async def _mark_synopsis_changed(
        db: AsyncSession,
        novel_id: str,
        relation_id,
    ) -> None:
        from modules.world.services.worldbuilding.synopsis_invalidation import (
            mark_synopsis_source_changed,
        )

        await mark_synopsis_source_changed(
            db,
            novel_id,
            source_type="entity_relation",
            source_id=str(relation_id),
        )

    async def _mark_endpoint_context_changed(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        entity_ids: set[str],
    ) -> None:
        marker = self._context_marker
        if marker is None:
            from modules.evidence.facade import mark_asset_context_changed

            marker = mark_asset_context_changed
        for entity_id in sorted(entity_ids):
            try:
                await marker(
                    db,
                    novel_id=novel_id,
                    asset_type="world_entity",
                    asset_id=entity_id,
                    reason="relation_review_batch",
                )
            except Exception as exc:
                logger.warning(
                    "world_relation_context_invalidation_failed novel_id=%s "
                    "entity_id=%s; relation_write_remains_valid; reason=%s",
                    novel_id_for_log(novel_id),
                    identifier_for_log(entity_id),
                    exception_summary_for_log(exc),
                )

    # ============================================================
    # 特例方法
    # ============================================================

    async def get_traceable_relations(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_id: str,
    ) -> EntityRelationListResponse:
        """获取某章节建立的所有可追溯关系。"""
        nid = parse_uuid(novel_id, "novel_id")
        cid = parse_uuid(chapter_id, "chapter_id")
        relations = await self.repo.get_traceable_relations(db, nid, cid)
        return EntityRelationListResponse(
            items=[self._response_with_endpoint_names(r) for r in relations],
            total=len(relations),
        )

    async def expand_related(
        self,
        db: AsyncSession,
        novel_id: str,
        seed_entity_ids: list[str],
        depth: int = 1,
        limit: int = 20,
    ) -> list[WorldEntityContext]:
        """图遍历扩展 — 跨 CoreEntity 表, 留作特例。"""
        nid = parse_uuid(novel_id, "novel_id")
        limit = min(limit, MAX_PAGE_SIZE)

        seed_ids = [parse_uuid(seed_id, "entity_id") for seed_id in seed_entity_ids]
        related_ids = {
            str(rid)
            for rid in await self.repo.get_related_entity_ids_for_seeds(
                db,
                nid,
                seed_ids,
                depth=depth,
                limit=limit,
            )
        }

        if not related_ids:
            return []

        related_list = list(related_ids)[:limit]
        eids = [parse_uuid(eid, "entity_id") for eid in related_list]
        entities = await self._entity_repo.get_by_ids(db, nid, eids)

        return [
            WorldEntityContext(
                entity_id=str(entity.id),
                entity_type=entity.entity_type,
                name=entity.name,
                summary=entity.summary,
                public_info=entity.public_info,
                importance=entity.importance,
                importance_level=entity.importance_level,
                reveal_level=entity.reveal_level,
                status=entity.status,
                related_entity_ids=list(related_ids),
            )
            for entity in entities
        ]

    async def get_by_entity(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_id: str,
    ) -> EntityRelationListResponse:
        """获取实体的关联关系（source + target）"""
        nid = parse_uuid(novel_id, "novel_id")
        eid = parse_uuid(entity_id, "entity_id")
        source_rels = await self.repo.get_by_source(
            db,
            nid,
            eid,
            limit=MAX_PAGE_SIZE,
        )
        target_rels = await self.repo.get_by_target(
            db,
            nid,
            eid,
            limit=MAX_PAGE_SIZE,
        )
        all_rels = source_rels + target_rels
        return EntityRelationListResponse(
            items=[self._response_with_endpoint_names(r) for r in all_rels],
            total=len(all_rels),
        )

    async def upsert(
        self,
        db: AsyncSession,
        novel_id: str,
        source_id: str,
        target_id: str,
        relation_type: str,
        description: str | None = None,
    ) -> EntityRelationResponse:
        """按 source + target + relation_type 去重创建/更新。"""
        await self._require_legacy_canon_write_allowed(db, novel_id)
        nid = parse_uuid(novel_id, "novel_id")
        sid = parse_uuid(source_id, "source_id")
        tid = parse_uuid(target_id, "target_id")
        source, target = await self._require_distinct_entities_in_novel(
            db,
            nid,
            sid,
            tid,
        )
        self._assert_active_relation_endpoint(source, "source_id")
        self._assert_active_relation_endpoint(target, "target_id")
        rel = await self.repo.upsert(
            db,
            nid,
            sid,
            tid,
            relation_type,
            description=description,
        )
        return EntityRelationResponse.model_validate(rel).model_copy(
            update={
                "source_name": getattr(source, "name", ""),
                "target_name": getattr(target, "name", ""),
            }
        )

    @staticmethod
    async def _require_legacy_canon_write_allowed(
        db: AsyncSession, novel_id: str
    ) -> None:
        from modules.world.services.worldbuilding.world_validation_service import (
            WorldValidationService,
        )

        await WorldValidationService().require_legacy_canon_write_allowed(
            db, novel_id, next_action="create_world_adoption_package"
        )
