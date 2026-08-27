"""Minimal immutable Canon foundation for documentary world resources."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from pydantic import TypeAdapter
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from core.errors import ConflictError, NotFoundError, ValidationError
from modules.account.facade import current_account_id
from modules.project.facade import require_active_project_exclusive
from modules.world.authority_schemas import (
    WORLD_AUTHORIZATION_POLICY_REF,
    WORLD_BASE_SCHEMA_REF,
    WORLD_CANON_MANIFEST_SCHEMA,
    WORLD_CANON_RECEIPT_SCHEMA,
    WORLD_KERNEL_SPEC_VERSION,
    BinaryRelationStatementV1,
    EntityProfileFieldSchemaV1,
    EntityProfileRelationSchemaV1,
    NameStatementV1,
    ResourceRevisionRefV1,
    StatementValueV1,
    TimelessScopeV1,
    TimeScopeV1,
    TypedScalarStatementV1,
    WorldCanonAdmissionReceiptV1,
    WorldCanonInitializePreviewRequest,
    WorldCanonInitializePreviewResponse,
    WorldCanonInitializeRequest,
    WorldCanonManifestV1,
    WorldCanonRevertRequest,
    WorldCanonSummaryResponse,
    WorldFormalQueryObligations,
    WorldFormalQueryRequest,
    WorldFormalQueryResponse,
    WorldPromotionApplyRequest,
    WorldPromotionCandidateV1,
    WorldPromotionPreviewRequest,
    WorldPromotionPreviewResponse,
)
from modules.world.models import (
    CoreEntity,
    EntityProfileTemplate,
    EntityProfileTemplateRevision,
    EntityRevision,
    WorldAssertion,
    WorldBiblePage,
    WorldBiblePageRevision,
    WorldBiblePageTemplate,
    WorldBiblePageTemplateRevision,
    WorldCanonHead,
    WorldCanonRevision,
)
from modules.world.schemas import WorldContextBundle, WorldEntityContext
from shared.utils import parse_uuid

_POLICY_DIGEST = hashlib.sha256(WORLD_AUTHORIZATION_POLICY_REF.encode()).hexdigest()
_ADOPTED_PAGE_STATUSES = frozenset({"canonical", "confirmed"})
_CORE_ENTITY_SELECTORS = frozenset(
    {"name", "summary", "public_info", "hidden_truth", "content_json"}
)
_STATEMENT_ADAPTER = TypeAdapter(StatementValueV1)
_TIME_SCOPE_ADAPTER = TypeAdapter(TimeScopeV1)
_NAME_SCHEMA_REF = {
    "kind": "builtin",
    "version": 1,
    "ref": WORLD_BASE_SCHEMA_REF,
    "selector": "name",
}


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def world_manifest_digest(manifest: WorldCanonManifestV1) -> str:
    return hashlib.sha256(
        canonical_json_bytes(manifest.model_dump(mode="json"))
    ).hexdigest()


def world_assertion_content_hash(
    *,
    regime_kind: str,
    polarity: str,
    statement: StatementValueV1,
    schema_ref: dict,
    time_scope: TimeScopeV1,
) -> str:
    return hashlib.sha256(
        canonical_json_bytes(
            {
                "regime_kind": regime_kind,
                "polarity": polarity,
                "statement": statement.model_dump(mode="json"),
                "schema_ref": schema_ref,
                "time_scope": time_scope.model_dump(mode="json"),
            }
        )
    ).hexdigest()


def _preview_digest(head_id: uuid.UUID, manifest: WorldCanonManifestV1) -> str:
    return hashlib.sha256(
        canonical_json_bytes(
            {
                "expected_previous_head": str(head_id),
                "manifest": manifest.model_dump(mode="json"),
            }
        )
    ).hexdigest()


def _promotion_preview_digest(
    head_id: uuid.UUID, items: list[WorldPromotionCandidateV1]
) -> str:
    return hashlib.sha256(
        canonical_json_bytes(
            {
                "expected_previous_head": str(head_id),
                "items": [item.model_dump(mode="json") for item in items],
            }
        )
    ).hexdigest()


class WorldAuthorityService:
    async def ensure_initialized(
        self,
        db: AsyncSession,
        novel_id: str | uuid.UUID,
        *,
        committer_principal: str | None = None,
    ) -> tuple[WorldCanonHead, WorldCanonRevision]:
        nid = self._uuid(novel_id, "novel_id")
        head = await db.get(WorldCanonHead, nid)
        if head is not None:
            return head, await self._load_revision(db, nid, head.canon_revision_id)

        await require_active_project_exclusive(db, str(nid))
        head = await db.get(WorldCanonHead, nid)
        if head is not None:
            return head, await self._load_revision(db, nid, head.canon_revision_id)

        now = datetime.now(UTC)
        revision_id = uuid.uuid4()
        manifest = self._empty_manifest(nid)
        digest = world_manifest_digest(manifest)
        receipt = self._receipt(
            novel_id=nid,
            canon_revision_id=revision_id,
            manifest_digest=digest,
            committer_principal=committer_principal or str(current_account_id()),
            action="initialize",
            committed_at=now,
            expected_previous_head=None,
        )
        revision = WorldCanonRevision(
            id=revision_id,
            novel_id=nid,
            parent_id=None,
            kernel_spec_version=WORLD_KERNEL_SPEC_VERSION,
            manifest_json=manifest.model_dump(mode="json"),
            manifest_digest=digest,
            admission_receipt_json=receipt.model_dump(mode="json"),
            created_at=now,
        )
        db.add(revision)
        await db.flush()
        head = WorldCanonHead(
            novel_id=nid,
            canon_revision_id=revision.id,
            head_version=0,
            updated_at=now,
        )
        db.add(head)
        await db.flush()
        return head, revision

    async def current_summary(
        self, db: AsyncSession, novel_id: str
    ) -> WorldCanonSummaryResponse:
        head, revision = await self.ensure_initialized(db, novel_id)
        return self._summary(revision, head=head, current=True)

    async def revision_summary(
        self,
        db: AsyncSession,
        novel_id: str,
        canon_revision_id: str | uuid.UUID,
    ) -> WorldCanonSummaryResponse:
        nid = self._uuid(novel_id, "novel_id")
        rid = self._uuid(canon_revision_id, "canon_revision_id")
        head, _ = await self.ensure_initialized(db, nid)
        revision = await self._load_revision(db, nid, rid)
        return self._summary(
            revision,
            head=head if head.canon_revision_id == revision.id else None,
            current=head.canon_revision_id == revision.id,
        )

    async def initialize_preview(
        self,
        db: AsyncSession,
        novel_id: str,
        request: WorldCanonInitializePreviewRequest,
    ) -> WorldCanonInitializePreviewResponse:
        nid = self._uuid(novel_id, "novel_id")
        head, revision = await self.ensure_initialized(db, nid)
        self._require_c0(revision)
        manifest = await self._manifest_for_page_revision_ids(
            db, nid, request.page_revision_ids
        )
        return WorldCanonInitializePreviewResponse(
            expected_previous_head=head.canon_revision_id,
            preview_digest=_preview_digest(head.canon_revision_id, manifest),
            resource_count=len(manifest.resources),
        )

    async def initialize(
        self,
        db: AsyncSession,
        novel_id: str,
        request: WorldCanonInitializeRequest,
    ) -> WorldCanonSummaryResponse:
        nid = self._uuid(novel_id, "novel_id")
        head, revision = await self._locked_head(db, nid)
        self._require_c0(revision)
        if head.canon_revision_id != request.expected_previous_head:
            self._head_changed()
        manifest = await self._manifest_for_page_revision_ids(
            db, nid, request.page_revision_ids
        )
        if _preview_digest(head.canon_revision_id, manifest) != request.preview_digest:
            raise ConflictError(
                "World Canon initialization preview is stale",
                code="world_canon_head_changed",
            )
        committed = await self._commit_manifest(
            db,
            head=head,
            parent=revision,
            manifest=manifest,
            action="initialize",
            expected_previous_head=request.expected_previous_head,
        )
        return self._summary(committed, head=head, current=True)

    async def revert(
        self,
        db: AsyncSession,
        novel_id: str,
        request: WorldCanonRevertRequest,
    ) -> WorldCanonSummaryResponse:
        nid = self._uuid(novel_id, "novel_id")
        head, current = await self._locked_head(db, nid)
        if head.canon_revision_id != request.expected_previous_head:
            self._head_changed()
        target = await self._load_revision(db, nid, request.target_canon_revision_id)
        manifest = self._manifest(target)
        await self._validate_manifest_refs(db, manifest)
        committed = await self._commit_manifest(
            db,
            head=head,
            parent=current,
            manifest=manifest,
            action="revert",
            expected_previous_head=request.expected_previous_head,
        )
        return self._summary(committed, head=head, current=True)

    async def promotion_preview(
        self,
        db: AsyncSession,
        novel_id: str,
        request: WorldPromotionPreviewRequest,
    ) -> WorldPromotionPreviewResponse:
        nid = self._uuid(novel_id, "novel_id")
        head, _ = await self.ensure_initialized(db, nid)
        for item in request.items:
            await self._validate_promotion_candidate(db, nid, item)
        self._require_unique_promotion_items(request.items)
        return WorldPromotionPreviewResponse(
            expected_previous_head=head.canon_revision_id,
            preview_digest=_promotion_preview_digest(
                head.canon_revision_id, request.items
            ),
            item_count=len(request.items),
        )

    async def promote(
        self,
        db: AsyncSession,
        novel_id: str,
        request: WorldPromotionApplyRequest,
    ) -> WorldCanonSummaryResponse:
        nid = self._uuid(novel_id, "novel_id")
        head, current = await self._locked_head(db, nid)
        if head.canon_revision_id != request.expected_previous_head:
            self._head_changed()
        for item in request.items:
            await self._validate_promotion_candidate(db, nid, item)
        self._require_unique_promotion_items(request.items)
        if _promotion_preview_digest(head.canon_revision_id, request.items) != (
            request.preview_digest
        ):
            self._head_changed()

        manifest = self._manifest(current)
        resources = list(manifest.resources)
        selected = list(manifest.selected_assertion_ids)
        for item in request.items:
            resources = self._without_resource(
                resources,
                item.schema_revision_ref.resource_kind,
                item.schema_revision_ref.resource_id,
            )
            resources.append(item.schema_revision_ref)
            selected.append(await self._ensure_promoted_assertion(db, nid, item))
        manifest = manifest.model_copy(
            update={
                "resources": sorted(resources, key=lambda ref: ref.sort_key()),
                "selected_assertion_ids": sorted(set(selected), key=str),
            }
        )
        committed = await self._commit_manifest(
            db,
            head=head,
            parent=current,
            manifest=manifest,
            action="promote",
            expected_previous_head=request.expected_previous_head,
        )
        return self._summary(committed, head=head, current=True)

    async def formal_query(
        self,
        db: AsyncSession,
        novel_id: str,
        request: WorldFormalQueryRequest,
    ) -> WorldFormalQueryResponse:
        nid = self._uuid(novel_id, "novel_id")
        try:
            _head, current = await self.ensure_initialized(db, nid)
        except ValidationError:
            head = await db.get(WorldCanonHead, nid)
            if head is None:
                raise
            return self._invalid_formal_query_response(head.canon_revision_id)
        try:
            revision = (
                current
                if request.canon_revision_id is None
                else await self._load_revision(db, nid, request.canon_revision_id)
            )
        except ValidationError:
            return self._invalid_formal_query_response(request.canon_revision_id)
        manifest = self._manifest(revision)
        await self._validate_query_statement(db, nid, request.statement)
        try:
            await self._validate_manifest_refs(db, manifest)
        except ValidationError:
            return self._invalid_formal_query_response(revision.id)
        if not isinstance(request.time_scope, TimelessScopeV1):
            return WorldFormalQueryResponse(
                verdict="unknown",
                product_verdict="incomplete",
                canon_revision_id=revision.id,
                positive_support_count=0,
                negative_support_count=0,
                obligations=WorldFormalQueryObligations(
                    source_scope="open",
                    formal_coverage="open",
                    identity="open",
                    execution="unsupported-family",
                ),
            )
        truncated = len(manifest.selected_assertion_ids) > request.max_assertions
        assertion_ids = manifest.selected_assertion_ids[: request.max_assertions]
        assertions = list(
            (
                await db.scalars(
                    select(WorldAssertion).where(WorldAssertion.id.in_(assertion_ids))
                )
            ).all()
        )
        positive: list[WorldAssertion] = []
        negative: list[WorldAssertion] = []
        expected_statement = request.statement.model_dump(mode="json")
        expected_time = request.time_scope.model_dump(mode="json")
        for assertion in assertions:
            await self._validate_assertion(db, assertion)
            if (
                assertion.regime_kind == "world"
                and assertion.statement_payload_json == expected_statement
                and assertion.time_scope_json == expected_time
            ):
                (positive if assertion.polarity == "positive" else negative).append(
                    assertion
                )
        verdict = (
            "both"
            if positive and negative
            else "true"
            if positive
            else "false"
            if negative
            else "unknown"
        )
        sources = []
        for assertion in [*positive, *negative]:
            label = await self._source_summary(db, assertion)
            if label not in sources:
                sources.append(label)
        execution = "budget-truncated" if truncated else "complete"
        return WorldFormalQueryResponse(
            verdict=verdict,
            product_verdict=(
                "verified-formal-relative"
                if verdict != "unknown" and not truncated
                else "incomplete"
            ),
            canon_revision_id=revision.id,
            positive_support_count=len(positive),
            negative_support_count=len(negative),
            source_summaries=sources,
            direct_authority_ids=(
                [assertion.id for assertion in [*positive, *negative]]
                if request.diagnostics
                else []
            ),
            obligations=WorldFormalQueryObligations(
                source_scope="open",
                formal_coverage="machine" if verdict != "unknown" else "open",
                identity="machine",
                execution=execution,
            ),
        )

    @staticmethod
    def _invalid_formal_query_response(
        canon_revision_id: uuid.UUID,
    ) -> WorldFormalQueryResponse:
        return WorldFormalQueryResponse(
            verdict="unknown",
            product_verdict="invalid",
            canon_revision_id=canon_revision_id,
            positive_support_count=0,
            negative_support_count=0,
            obligations=WorldFormalQueryObligations(
                source_scope="open",
                formal_coverage="open",
                identity="open",
                execution="invalid-context",
            ),
        )

    async def canon_context(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        canon_revision_id: str | uuid.UUID | None = None,
        entity_ids: list[str] | None = None,
        reveal_mode: str = "author_safe",
        limit: int = 20,
    ) -> WorldContextBundle:
        """Project C-pinned facts and documentary resources without legacy fallback."""
        nid = self._uuid(novel_id, "novel_id")
        _head, current = await self.ensure_initialized(db, nid)
        revision = (
            current
            if canon_revision_id is None
            else await self._load_revision(
                db,
                nid,
                self._uuid(canon_revision_id, "canon_revision_id"),
            )
        )
        manifest = self._manifest(revision)
        await self._validate_manifest_refs(db, manifest)
        assertions = list(
            (
                await db.scalars(
                    select(WorldAssertion).where(
                        WorldAssertion.id.in_(manifest.selected_assertion_ids)
                    )
                )
            ).all()
        )
        primary_names: dict[uuid.UUID, str] = {}
        aliases: dict[uuid.UUID, list[str]] = {}
        facts: dict[uuid.UUID, list[str]] = {}
        related: dict[uuid.UUID, set[uuid.UUID]] = {}
        parsed: list[tuple[WorldAssertion, StatementValueV1]] = []
        for assertion in assertions:
            statement = _STATEMENT_ADAPTER.validate_python(
                assertion.statement_payload_json
            )
            parsed.append((assertion, statement))
            if isinstance(statement, NameStatementV1):
                if statement.name_kind == "primary" and assertion.polarity == "positive":
                    primary_names[statement.subject_entity_id] = statement.value
                elif statement.name_kind == "alias" and assertion.polarity == "positive":
                    aliases.setdefault(statement.subject_entity_id, []).append(
                        statement.value
                    )
        for assertion, statement in parsed:
            sign = "" if assertion.polarity == "positive" else "不成立："
            if isinstance(statement, NameStatementV1):
                continue
            if hasattr(statement, "subject_entity_id"):
                value = f"{statement.value}{statement.unit or ''}"
                facts.setdefault(statement.subject_entity_id, []).append(
                    f"{sign}{statement.field_key} = {value}"
                )
            else:
                target_name = primary_names.get(
                    statement.target_entity_id, "未命名对象"
                )
                facts.setdefault(statement.source_entity_id, []).append(
                    f"{sign}{statement.relation_type} → {target_name}"
                )
                related.setdefault(statement.source_entity_id, set()).add(
                    statement.target_entity_id
                )

        requested_ids = (
            {self._uuid(item, "entity_id") for item in entity_ids}
            if entity_ids
            else None
        )
        items: list[WorldEntityContext] = []
        for ref in manifest.resources:
            if ref.resource_kind == "core_entity":
                if requested_ids is not None and ref.resource_id not in requested_ids:
                    continue
                entity_revision = await db.get(EntityRevision, ref.revision_id)
                snapshot = entity_revision.snapshot
                fact_lines = facts.get(ref.resource_id, [])
                summary_parts = [str(snapshot.get("summary") or "").strip()]
                if fact_lines:
                    summary_parts.append("[正典事实] " + "；".join(fact_lines))
                items.append(
                    WorldEntityContext(
                        entity_id=ref.resource_id,
                        entity_type=str(snapshot.get("entity_type") or "custom"),
                        name=primary_names.get(
                            ref.resource_id,
                            f"资料：{snapshot.get('name') or '未命名对象'}",
                        ),
                        summary="\n".join(part for part in summary_parts if part),
                        public_info=snapshot.get("public_info"),
                        hidden_truth=(
                            snapshot.get("hidden_truth")
                            if reveal_mode == "author_full"
                            else None
                        ),
                        importance=float(snapshot.get("importance") or 0.5),
                        importance_level=str(
                            snapshot.get("importance_level") or "normal"
                        ),
                        reveal_level=str(
                            snapshot.get("reveal_level") or "author_only"
                        ),
                        aliases=sorted(set(aliases.get(ref.resource_id, []))),
                        related_entity_ids=[
                            str(item)
                            for item in sorted(
                                related.get(ref.resource_id, set()), key=str
                            )
                        ],
                        source_type="world_entity_revision",
                        source_revision_id=str(ref.revision_id),
                        canon_revision_id=str(revision.id),
                    )
                )
            elif ref.resource_kind == "world_bible_page" and requested_ids is None:
                page_revision = await db.get(WorldBiblePageRevision, ref.revision_id)
                snapshot = page_revision.snapshot_json
                section_text = "\n".join(
                    "\n".join(
                        part
                        for part in [
                            str(item.get("title") or "").strip(),
                            str(item.get("body_markdown") or "").strip(),
                        ]
                        if part
                    )
                    for item in snapshot.get("sections_json", [])
                    if isinstance(item, dict)
                )
                content = "\n".join(
                    item
                    for item in [
                        str(snapshot.get("free_text") or "").strip(),
                        section_text,
                    ]
                    if item
                )
                items.append(
                    WorldEntityContext(
                        entity_id=ref.resource_id,
                        entity_type="world_bible_page",
                        name=str(snapshot.get("title") or "未命名资料"),
                        summary=content[:5000],
                        source_type="world_bible_page_revision",
                        source_revision_id=str(ref.revision_id),
                        canon_revision_id=str(revision.id),
                    )
                )
        return WorldContextBundle(
            novel_id=str(nid),
            entities=items[:limit],
            total_count=len(items),
            reveal_mode=reveal_mode,
            canon_revision_id=str(revision.id),
            canon_manifest_digest=revision.manifest_digest,
        )

    async def record_page_revision(
        self,
        db: AsyncSession,
        page: WorldBiblePage,
        revision: WorldBiblePageRevision,
        *,
        action: str,
    ) -> WorldCanonRevision:
        head, current = await self._locked_head(db, page.novel_id)
        manifest = self._manifest(current)
        resources = [
            item
            for item in manifest.resources
            if not (
                item.resource_kind == "world_bible_page" and item.resource_id == page.id
            )
        ]
        inactive_resources = [
            item
            for item in manifest.inactive_resource_refs
            if not (
                item.resource_kind == "world_bible_page" and item.resource_id == page.id
            )
        ]
        ref = ResourceRevisionRefV1(
            resource_kind="world_bible_page",
            resource_id=page.id,
            revision_kind="world_bible_page_revision",
            revision_id=revision.id,
            selector="whole",
        )
        await self._validate_resource_ref(db, page.novel_id, ref)
        if page.status in _ADOPTED_PAGE_STATUSES:
            resources.append(ref)
        else:
            inactive_resources.append(ref)
        manifest = manifest.model_copy(
            update={
                "resources": sorted(resources, key=lambda item: item.sort_key()),
                "inactive_resource_refs": sorted(
                    inactive_resources, key=lambda item: item.sort_key()
                ),
            }
        )
        return await self._commit_manifest(
            db,
            head=head,
            parent=current,
            manifest=manifest,
            action="publish_page" if action == "publish_page" else "canonical_edit",
            expected_previous_head=head.canon_revision_id,
        )

    async def record_entity_revision(
        self,
        db: AsyncSession,
        entity: CoreEntity,
        *,
        action: str = "canonical_edit",
    ) -> WorldCanonRevision:
        """Seal an Entity revision and atomically select its primary Name."""
        head, current = await self._locked_head(db, entity.novel_id)
        revision = EntityRevision(
            entity_id=entity.id,
            novel_id=entity.novel_id,
            snapshot=self._entity_snapshot(entity),
            revision_reason={
                "adopt": "canon_adopt",
                "promote": "canon_promote",
                "canonical_edit": "canon_edit",
            }[action],
        )
        db.add(revision)
        await db.flush()
        ref = ResourceRevisionRefV1(
            resource_kind="core_entity",
            resource_id=entity.id,
            revision_kind="entity_revision",
            revision_id=revision.id,
            selector="whole",
        )
        await self._validate_resource_ref(db, entity.novel_id, ref)
        manifest = self._manifest(current)
        resources = self._without_resource(manifest.resources, "core_entity", entity.id)
        inactive = self._without_resource(
            manifest.inactive_resource_refs, "core_entity", entity.id
        )
        selected = await self._without_name_assertions(
            db, manifest.selected_assertion_ids, entity.id
        )
        if entity.status == "canonical":
            resources.append(ref)
            selected.extend(
                await self._ensure_name_assertions(db, entity, revision)
            )
        else:
            inactive.append(ref)
        manifest = manifest.model_copy(
            update={
                "resources": sorted(resources, key=lambda item: item.sort_key()),
                "inactive_resource_refs": sorted(
                    inactive, key=lambda item: item.sort_key()
                ),
                "selected_assertion_ids": sorted(set(selected), key=str),
            }
        )
        return await self._commit_manifest(
            db,
            head=head,
            parent=current,
            manifest=manifest,
            action=action,
            expected_previous_head=head.canon_revision_id,
        )

    async def _locked_head(
        self, db: AsyncSession, novel_id: uuid.UUID
    ) -> tuple[WorldCanonHead, WorldCanonRevision]:
        await self.ensure_initialized(db, novel_id)
        result = await db.execute(
            select(WorldCanonHead)
            .where(WorldCanonHead.novel_id == novel_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        head = result.scalar_one()
        return head, await self._load_revision(db, novel_id, head.canon_revision_id)

    async def _commit_manifest(
        self,
        db: AsyncSession,
        *,
        head: WorldCanonHead,
        parent: WorldCanonRevision,
        manifest: WorldCanonManifestV1,
        action: str,
        expected_previous_head: uuid.UUID,
    ) -> WorldCanonRevision:
        if parent.id != head.canon_revision_id or parent.id != expected_previous_head:
            self._head_changed()
        await self._validate_manifest_refs(db, manifest)
        now = datetime.now(UTC)
        revision_id = uuid.uuid4()
        digest = world_manifest_digest(manifest)
        receipt = self._receipt(
            novel_id=head.novel_id,
            canon_revision_id=revision_id,
            manifest_digest=digest,
            committer_principal=str(current_account_id()),
            action=action,
            committed_at=now,
            expected_previous_head=expected_previous_head,
        )
        revision = WorldCanonRevision(
            id=revision_id,
            novel_id=head.novel_id,
            parent_id=parent.id,
            kernel_spec_version=WORLD_KERNEL_SPEC_VERSION,
            manifest_json=manifest.model_dump(mode="json"),
            manifest_digest=digest,
            admission_receipt_json=receipt.model_dump(mode="json"),
            created_at=now,
        )
        db.add(revision)
        await db.flush()
        result = await db.execute(
            update(WorldCanonHead)
            .where(
                WorldCanonHead.novel_id == head.novel_id,
                WorldCanonHead.canon_revision_id == expected_previous_head,
                WorldCanonHead.head_version == head.head_version,
            )
            .values(
                canon_revision_id=revision.id,
                head_version=head.head_version + 1,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            self._head_changed()
        set_committed_value(head, "canon_revision_id", revision.id)
        set_committed_value(head, "head_version", head.head_version + 1)
        set_committed_value(head, "updated_at", now)
        return revision

    async def _manifest_for_page_revision_ids(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        revision_ids: list[uuid.UUID],
    ) -> WorldCanonManifestV1:
        if len(revision_ids) != len(set(revision_ids)):
            raise ValidationError(
                "World Canon resource revisions must be unique",
                code="world_canon_invalid_reference",
                status_code=422,
            )
        refs: list[ResourceRevisionRefV1] = []
        stable_ids: set[uuid.UUID] = set()
        for revision_id in revision_ids:
            revision = await db.get(WorldBiblePageRevision, revision_id)
            if revision is None or revision.novel_id != novel_id:
                self._invalid_ref()
            if revision.page_id in stable_ids:
                raise ValidationError(
                    "A Canon manifest may select one revision per resource",
                    code="world_canon_manifest_not_closed",
                    status_code=422,
                )
            stable_ids.add(revision.page_id)
            ref = ResourceRevisionRefV1(
                resource_kind="world_bible_page",
                resource_id=revision.page_id,
                revision_kind="world_bible_page_revision",
                revision_id=revision.id,
                selector="whole",
            )
            await self._validate_resource_ref(db, novel_id, ref)
            refs.append(ref)
        return WorldCanonManifestV1(
            novel_id=novel_id,
            resources=sorted(refs, key=lambda item: item.sort_key()),
            schema_refs=[WORLD_BASE_SCHEMA_REF],
            policy_refs=sorted([WORLD_BASE_SCHEMA_REF, WORLD_AUTHORIZATION_POLICY_REF]),
        )

    async def _validate_manifest_refs(
        self, db: AsyncSession, manifest: WorldCanonManifestV1
    ) -> None:
        stable_resources: set[tuple[str, uuid.UUID]] = set()
        for ref in [*manifest.resources, *manifest.inactive_resource_refs]:
            stable = (ref.resource_kind, ref.resource_id)
            if stable in stable_resources:
                raise ValidationError(
                    "A Canon manifest may select one revision per resource",
                    code="world_canon_manifest_not_closed",
                    status_code=422,
                )
            stable_resources.add(stable)
            await self._validate_resource_ref(db, manifest.novel_id, ref)
        if manifest.selected_assertion_ids:
            result = await db.execute(
                select(WorldAssertion).where(
                    WorldAssertion.novel_id == manifest.novel_id,
                    WorldAssertion.id.in_(manifest.selected_assertion_ids),
                )
            )
            assertions = list(result.scalars())
            if {item.id for item in assertions} != set(manifest.selected_assertion_ids):
                self._invalid_ref()
            for assertion in assertions:
                await self._validate_assertion(db, assertion)

    async def _validate_assertion(
        self, db: AsyncSession, assertion: WorldAssertion
    ) -> None:
        try:
            statement = _STATEMENT_ADAPTER.validate_python(
                assertion.statement_payload_json
            )
            time_scope = _TIME_SCOPE_ADAPTER.validate_python(assertion.time_scope_json)
            source_ref = ResourceRevisionRefV1.model_validate(
                assertion.source_revision_ref_json
            )
            hard_ground_refs = [
                ResourceRevisionRefV1.model_validate(item)
                for item in assertion.hard_ground_refs_json
            ]
            cite_refs = [
                ResourceRevisionRefV1.model_validate(item)
                for item in assertion.cite_refs_json
            ]
        except PydanticValidationError:
            self._invalid_ref()
        if (
            assertion.regime_kind != "world"
            or assertion.belief_holder_entity_id is not None
            or assertion.polarity not in {"positive", "negative"}
            or assertion.statement_kind != statement.kind
            or assertion.statement_version != statement.version
            or not isinstance(time_scope, TimelessScopeV1)
            or (
                isinstance(statement, NameStatementV1)
                and assertion.schema_ref_json != _NAME_SCHEMA_REF
            )
            or world_assertion_content_hash(
                regime_kind=assertion.regime_kind,
                polarity=assertion.polarity,
                statement=statement,
                schema_ref=assertion.schema_ref_json,
                time_scope=time_scope,
            )
            != assertion.content_hash
        ):
            self._invalid_ref()
        if not isinstance(statement, NameStatementV1):
            try:
                schema_ref = ResourceRevisionRefV1.model_validate(
                    assertion.schema_ref_json
                )
            except PydanticValidationError:
                self._invalid_ref()
            if schema_ref.resource_kind != "entity_profile_template":
                self._invalid_ref()
            await self._validate_resource_ref(db, assertion.novel_id, schema_ref)
        entity_ids = (
            [statement.subject_entity_id]
            if hasattr(statement, "subject_entity_id")
            else [statement.source_entity_id, statement.target_entity_id]
        )
        entities = await db.execute(
            select(CoreEntity.id).where(
                CoreEntity.novel_id == assertion.novel_id,
                CoreEntity.id.in_(entity_ids),
            )
        )
        if set(entities.scalars()) != set(entity_ids):
            self._invalid_ref()
        for ref in [source_ref, *hard_ground_refs, *cite_refs]:
            await self._validate_resource_ref(db, assertion.novel_id, ref)

    async def _validate_promotion_candidate(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        item: WorldPromotionCandidateV1,
    ) -> None:
        if not isinstance(item.time_scope, TimelessScopeV1):
            raise ValidationError(
                "Only timeless promotion is supported in world-kernel.v1",
                code="world_statement_unsupported",
                status_code=422,
            )
        await self._validate_query_statement(db, novel_id, item.statement)
        await self._validate_resource_ref(db, novel_id, item.schema_revision_ref)
        await self._validate_statement_schema(db, novel_id, item)
        await self._validate_resource_ref(db, novel_id, item.source_revision_ref)
        for ref in item.cite_refs:
            await self._validate_resource_ref(db, novel_id, ref)

    async def _validate_statement_schema(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        item: WorldPromotionCandidateV1,
    ) -> None:
        revision = await db.get(
            EntityProfileTemplateRevision,
            item.schema_revision_ref.revision_id,
        )
        statement = item.statement
        source_id = (
            statement.subject_entity_id
            if isinstance(statement, TypedScalarStatementV1)
            else statement.source_entity_id
        )
        source = await db.get(CoreEntity, source_id)
        if (
            revision is None
            or source is None
            or revision.novel_id != novel_id
            or source.novel_id != novel_id
            or source.entity_type != revision.profile_type
        ):
            self._invalid_ref()
        if isinstance(statement, TypedScalarStatementV1):
            try:
                fields = [
                    EntityProfileFieldSchemaV1.model_validate(raw)
                    for raw in revision.template_schema_json.get("fields", [])
                ]
            except PydanticValidationError:
                self._invalid_ref()
            field = next(
                (
                    candidate
                    for candidate in fields
                    if candidate.key == statement.field_key
                ),
                None,
            )
            if (
                field is None
                or field.value_type != statement.value_type
                or field.unit != statement.unit
                or (
                    field.value_type == "enum"
                    and statement.value not in field.enum_values
                )
            ):
                self._invalid_ref()
            return
        if not isinstance(statement, BinaryRelationStatementV1):
            self._invalid_ref()
        try:
            relations = [
                EntityProfileRelationSchemaV1.model_validate(raw)
                for raw in revision.template_schema_json.get("relations", [])
            ]
        except PydanticValidationError:
            self._invalid_ref()
        relation = next(
            (
                candidate
                for candidate in relations
                if candidate.relation_type == statement.relation_type
            ),
            None,
        )
        target = await db.get(CoreEntity, statement.target_entity_id)
        if (
            relation is None
            or relation.relation_kind != statement.relation_kind
            or target is None
            or target.novel_id != novel_id
            or (
                relation.target_entity_types
                and target.entity_type not in relation.target_entity_types
            )
        ):
            self._invalid_ref()

    async def _validate_query_statement(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        statement: StatementValueV1,
    ) -> None:
        entity_ids = (
            [statement.subject_entity_id]
            if hasattr(statement, "subject_entity_id")
            else [statement.source_entity_id, statement.target_entity_id]
        )
        result = await db.execute(
            select(CoreEntity.id).where(
                CoreEntity.novel_id == novel_id,
                CoreEntity.id.in_(entity_ids),
            )
        )
        if set(result.scalars()) != set(entity_ids):
            self._invalid_ref()

    async def _ensure_promoted_assertion(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        item: WorldPromotionCandidateV1,
    ) -> uuid.UUID:
        content_hash = world_assertion_content_hash(
            regime_kind="world",
            polarity=item.polarity,
            statement=item.statement,
            schema_ref=item.schema_revision_ref.model_dump(mode="json"),
            time_scope=item.time_scope,
        )
        existing = await db.scalar(
            select(WorldAssertion).where(
                WorldAssertion.novel_id == novel_id,
                WorldAssertion.content_hash == content_hash,
            )
        )
        if existing is not None:
            await self._validate_assertion(db, existing)
            return existing.id
        assertion = WorldAssertion(
            novel_id=novel_id,
            regime_kind="world",
            belief_holder_entity_id=None,
            polarity=item.polarity,
            statement_kind=item.statement.kind,
            statement_version=item.statement.version,
            statement_payload_json=item.statement.model_dump(mode="json"),
            schema_ref_json=item.schema_revision_ref.model_dump(mode="json"),
            time_scope_json=item.time_scope.model_dump(mode="json"),
            source_revision_ref_json=item.source_revision_ref.model_dump(mode="json"),
            hard_ground_refs_json=[
                item.source_revision_ref.model_dump(mode="json")
            ],
            cite_refs_json=[ref.model_dump(mode="json") for ref in item.cite_refs],
            provenance_actor_ref=str(current_account_id()),
            content_hash=content_hash,
            created_at=datetime.now(UTC),
        )
        db.add(assertion)
        await db.flush()
        return assertion.id

    @staticmethod
    def _require_unique_promotion_items(
        items: list[WorldPromotionCandidateV1],
    ) -> None:
        keys = [
            canonical_json_bytes(
                {
                    "polarity": item.polarity,
                    "statement": item.statement.model_dump(mode="json"),
                    "time_scope": item.time_scope.model_dump(mode="json"),
                }
            )
            for item in items
        ]
        if len(keys) != len(set(keys)):
            raise ValidationError(
                "Promotion items must be unique",
                code="world_canon_manifest_not_closed",
                status_code=422,
            )

    async def _source_summary(
        self,
        db: AsyncSession,
        assertion: WorldAssertion,
    ) -> str:
        ref = ResourceRevisionRefV1.model_validate(
            assertion.source_revision_ref_json
        )
        if ref.resource_kind == "world_bible_page":
            revision = await db.get(WorldBiblePageRevision, ref.revision_id)
            return f"世界书：{revision.snapshot_json.get('title') or '未命名资料'}"
        if ref.resource_kind == "core_entity":
            revision = await db.get(EntityRevision, ref.revision_id)
            return f"世界对象：{revision.snapshot.get('name') or '未命名对象'}"
        return "已采用的结构化世界资料"

    async def _ensure_name_assertions(
        self,
        db: AsyncSession,
        entity: CoreEntity,
        revision: EntityRevision,
    ) -> list[uuid.UUID]:
        names = [(entity.name, "primary", "field:name")]
        raw_aliases = (entity.content_json or {}).get("aliases", [])
        if not isinstance(raw_aliases, list):
            self._invalid_ref()
        seen = {entity.name}
        for item in raw_aliases:
            if isinstance(item, str):
                value, status = item.strip(), None
            elif isinstance(item, dict):
                value = str(item.get("alias", item.get("name", ""))).strip()
                status = item.get("status")
            else:
                self._invalid_ref()
            if (
                value
                and value not in seen
                and status in {None, "active", "canonical", "confirmed", "published"}
            ):
                names.append((value, "alias", "field:content_json"))
                seen.add(value)
        return [
            await self._ensure_name_assertion(
                db,
                entity,
                revision,
                value=value,
                name_kind=name_kind,
                source_selector=source_selector,
            )
            for value, name_kind, source_selector in names
        ]

    async def _ensure_name_assertion(
        self,
        db: AsyncSession,
        entity: CoreEntity,
        revision: EntityRevision,
        *,
        value: str,
        name_kind: str,
        source_selector: str,
    ) -> uuid.UUID:
        statement = NameStatementV1(
            subject_entity_id=entity.id,
            value=value,
            name_kind=name_kind,
        )
        time_scope = TimelessScopeV1()
        content_hash = world_assertion_content_hash(
            regime_kind="world",
            polarity="positive",
            statement=statement,
            schema_ref=_NAME_SCHEMA_REF,
            time_scope=time_scope,
        )
        existing = await db.scalar(
            select(WorldAssertion).where(
                WorldAssertion.novel_id == entity.novel_id,
                WorldAssertion.content_hash == content_hash,
            )
        )
        if existing is not None:
            await self._validate_assertion(db, existing)
            return existing.id
        source_ref = ResourceRevisionRefV1(
            resource_kind="core_entity",
            resource_id=entity.id,
            revision_kind="entity_revision",
            revision_id=revision.id,
            selector=source_selector,
        )
        assertion = WorldAssertion(
            novel_id=entity.novel_id,
            regime_kind="world",
            belief_holder_entity_id=None,
            polarity="positive",
            statement_kind=statement.kind,
            statement_version=statement.version,
            statement_payload_json=statement.model_dump(mode="json"),
            schema_ref_json=_NAME_SCHEMA_REF,
            time_scope_json=time_scope.model_dump(mode="json"),
            source_revision_ref_json=source_ref.model_dump(mode="json"),
            hard_ground_refs_json=[],
            cite_refs_json=[],
            provenance_actor_ref=str(current_account_id()),
            content_hash=content_hash,
            created_at=datetime.now(UTC),
        )
        db.add(assertion)
        await db.flush()
        return assertion.id

    async def _without_name_assertions(
        self,
        db: AsyncSession,
        assertion_ids: list[uuid.UUID],
        entity_id: uuid.UUID,
    ) -> list[uuid.UUID]:
        if not assertion_ids:
            return []
        result = await db.execute(
            select(WorldAssertion).where(WorldAssertion.id.in_(assertion_ids))
        )
        kept: list[uuid.UUID] = []
        for assertion in result.scalars():
            try:
                statement = _STATEMENT_ADAPTER.validate_python(
                    assertion.statement_payload_json
                )
            except PydanticValidationError:
                self._invalid_ref()
            if not (
                isinstance(statement, NameStatementV1)
                and statement.subject_entity_id == entity_id
            ):
                kept.append(assertion.id)
        return kept

    @staticmethod
    def _without_resource(
        refs: list[ResourceRevisionRefV1],
        resource_kind: str,
        resource_id: uuid.UUID,
    ) -> list[ResourceRevisionRefV1]:
        return [
            item
            for item in refs
            if not (
                item.resource_kind == resource_kind
                and item.resource_id == resource_id
            )
        ]

    @staticmethod
    def _entity_snapshot(entity: CoreEntity) -> dict:
        return {
            "entity_type": entity.entity_type,
            "name": entity.name,
            "summary": entity.summary,
            "public_info": entity.public_info,
            "hidden_truth": entity.hidden_truth,
            "content_json": entity.content_json,
            "importance": entity.importance,
            "importance_level": entity.importance_level,
            "reveal_level": entity.reveal_level,
            "status": entity.status,
        }

    async def _validate_resource_ref(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        ref: ResourceRevisionRefV1,
    ) -> None:
        if ref.resource_kind == "world_bible_page":
            page = await db.get(WorldBiblePage, ref.resource_id)
            revision = await db.get(WorldBiblePageRevision, ref.revision_id)
            if (
                page is None
                or revision is None
                or page.novel_id != novel_id
                or revision.novel_id != novel_id
                or revision.page_id != page.id
            ):
                self._invalid_ref()
            self._validate_page_selector(revision, ref.selector)
            await self._validate_card_subject(db, novel_id, revision)
            return
        if ref.resource_kind == "world_bible_page_template":
            head = await db.get(WorldBiblePageTemplate, ref.resource_id)
            revision = await db.get(WorldBiblePageTemplateRevision, ref.revision_id)
            if (
                head is None
                or revision is None
                or head.novel_id != novel_id
                or revision.novel_id != novel_id
                or revision.template_id != head.id
                or ref.selector != "whole"
            ):
                self._invalid_ref()
            return
        if ref.resource_kind == "core_entity":
            entity = await db.get(CoreEntity, ref.resource_id)
            revision = await db.get(EntityRevision, ref.revision_id)
            selector = ref.selector.removeprefix("field:")
            if (
                entity is None
                or revision is None
                or entity.novel_id != novel_id
                or revision.novel_id != novel_id
                or revision.entity_id != entity.id
                or (
                    ref.selector != "whole"
                    and not (
                        ref.selector.startswith("field:")
                        and selector in _CORE_ENTITY_SELECTORS
                    )
                )
            ):
                self._invalid_ref()
            return
        if ref.resource_kind == "entity_profile_template":
            head = await db.get(EntityProfileTemplate, ref.resource_id)
            revision = await db.get(EntityProfileTemplateRevision, ref.revision_id)
            if (
                head is None
                or revision is None
                or head.novel_id != novel_id
                or revision.novel_id != novel_id
                or revision.template_id != head.id
                or ref.selector != "whole"
            ):
                self._invalid_ref()
            return
        self._invalid_ref()

    @staticmethod
    def _validate_page_selector(revision: WorldBiblePageRevision, selector: str) -> None:
        if selector in {"whole", "free_text"}:
            return
        if selector.startswith("section:"):
            section_id = selector.removeprefix("section:")
            matches = [
                item
                for item in revision.snapshot_json.get("sections_json", [])
                if isinstance(item, dict) and item.get("section_id") == section_id
            ]
            if len(matches) == 1:
                return
        WorldAuthorityService._invalid_ref()

    @staticmethod
    async def _validate_card_subject(
        db: AsyncSession,
        novel_id: uuid.UUID,
        revision: WorldBiblePageRevision,
    ) -> None:
        page_meta = revision.snapshot_json.get("page_meta_json") or {}
        if not isinstance(page_meta, dict):
            WorldAuthorityService._invalid_ref()
        subject = page_meta.get("card_subject_ref_v1")
        if subject is None:
            return
        if not isinstance(subject, dict) or set(subject) != {"kind", "entity_id"}:
            WorldAuthorityService._invalid_ref()
        if subject.get("kind") != "core_entity":
            WorldAuthorityService._invalid_ref()
        try:
            entity_id = uuid.UUID(str(subject.get("entity_id")))
        except (TypeError, ValueError):
            WorldAuthorityService._invalid_ref()
        entity = await db.get(CoreEntity, entity_id)
        if entity is None or entity.novel_id != novel_id:
            WorldAuthorityService._invalid_ref()

    async def _load_revision(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        revision_id: uuid.UUID,
    ) -> WorldCanonRevision:
        revision = await db.get(WorldCanonRevision, revision_id)
        if revision is None or revision.novel_id != novel_id:
            raise NotFoundError("World Canon revision not found")
        manifest = self._manifest(revision)
        try:
            receipt = WorldCanonAdmissionReceiptV1.model_validate(
                revision.admission_receipt_json
            )
        except PydanticValidationError as exc:
            raise ValidationError(
                "World Canon admission receipt is invalid",
                code="world_canon_manifest_not_closed",
                status_code=422,
            ) from exc
        if (
            revision.kernel_spec_version != WORLD_KERNEL_SPEC_VERSION
            or manifest.novel_id != novel_id
            or world_manifest_digest(manifest) != revision.manifest_digest
            or receipt.novel_id != novel_id
            or receipt.canon_revision_id != revision.id
            or receipt.manifest_digest != revision.manifest_digest
            or receipt.expected_previous_head != revision.parent_id
            or receipt.authorization_policy_ref != WORLD_AUTHORIZATION_POLICY_REF
            or receipt.authorization_policy_digest != _POLICY_DIGEST
        ):
            raise ValidationError(
                "World Canon manifest or receipt is invalid",
                code="world_canon_manifest_not_closed",
                status_code=422,
            )
        return revision

    @staticmethod
    def _manifest(revision: WorldCanonRevision) -> WorldCanonManifestV1:
        try:
            return WorldCanonManifestV1.model_validate(revision.manifest_json)
        except PydanticValidationError as exc:
            raise ValidationError(
                "World Canon manifest is invalid",
                code="world_canon_manifest_not_closed",
                status_code=422,
            ) from exc

    @staticmethod
    def _empty_manifest(novel_id: uuid.UUID) -> WorldCanonManifestV1:
        return WorldCanonManifestV1(
            schema_version=WORLD_CANON_MANIFEST_SCHEMA,
            novel_id=novel_id,
            kernel_spec_version=WORLD_KERNEL_SPEC_VERSION,
            resources=[],
            selected_assertion_ids=[],
            schema_refs=[WORLD_BASE_SCHEMA_REF],
            rule_refs=[],
            policy_refs=sorted([WORLD_BASE_SCHEMA_REF, WORLD_AUTHORIZATION_POLICY_REF]),
            calendar_refs=[],
            correspondence_refs=[],
            inactive_resource_refs=[],
        )

    @staticmethod
    def _receipt(**values) -> WorldCanonAdmissionReceiptV1:  # noqa: ANN003
        return WorldCanonAdmissionReceiptV1(
            schema_version=WORLD_CANON_RECEIPT_SCHEMA,
            authorization_scope="world.canon.commit",
            authorization_policy_ref=WORLD_AUTHORIZATION_POLICY_REF,
            authorization_policy_digest=_POLICY_DIGEST,
            decision="allowed",
            **values,
        )

    @staticmethod
    def _summary(
        revision: WorldCanonRevision,
        *,
        head: WorldCanonHead | None,
        current: bool,
    ) -> WorldCanonSummaryResponse:
        manifest = WorldAuthorityService._manifest(revision)
        return WorldCanonSummaryResponse(
            canon_revision_id=revision.id,
            parent_id=revision.parent_id,
            manifest_digest=revision.manifest_digest,
            created_at=revision.created_at,
            resource_count=len(manifest.resources),
            assertion_count=len(manifest.selected_assertion_ids),
            head_version=head.head_version if head else None,
            current=current,
        )

    @staticmethod
    def _require_c0(revision: WorldCanonRevision) -> None:
        manifest = WorldAuthorityService._manifest(revision)
        if (
            revision.parent_id is not None
            or manifest.resources
            or manifest.selected_assertion_ids
        ):
            raise ConflictError(
                "World Canon is already initialized",
                code="world_canon_initialization_required",
            )

    @staticmethod
    def _uuid(value: str | uuid.UUID, field: str) -> uuid.UUID:
        if isinstance(value, uuid.UUID):
            return value
        return parse_uuid(value, field)

    @staticmethod
    def _head_changed() -> None:
        raise ConflictError(
            "World Canon head changed",
            code="world_canon_head_changed",
        )

    @staticmethod
    def _invalid_ref() -> None:
        raise ValidationError(
            "World Canon reference is invalid",
            code="world_canon_invalid_reference",
            status_code=422,
        )


__all__ = [
    "WorldAuthorityService",
    "canonical_json_bytes",
    "world_manifest_digest",
]
