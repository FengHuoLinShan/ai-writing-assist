"""Phase 0 canon initialization, exact resolution, admission, and replay."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, DomainError, NotFoundError
from modules.project.facade import get_project_context
from modules.world.authority import (
    BOOTSTRAP_POLICY_REF,
    EXPLICIT_AUTHOR_POLICY_REF,
    STATEMENT_SCHEMA_REF,
    AssertBatchInputV1,
    AssertRefV1,
    AssertValueV1,
    CanonAdmissionPreviewRequest,
    CanonAdmissionPreviewResponse,
    CanonAdmissionReceiptV1,
    CanonAdmissionRequest,
    CanonHeadResponse,
    CanonManifestV1,
    CanonRevisionResponse,
    EntityRelationStatementV1,
    EntityScalarStatementV1,
    ExactResourceRevisionRef,
    FamilyCutoverInputV1,
    PageDraftSnapshotV1,
    PagePublishInputV1,
    PagePublishPreviewInputV1,
    ResourceRef,
    RevertInputV1,
    RevertPreviewInputV1,
    TargetRefV1,
    VersionedArtifactRef,
    assertion_content_digest,
    bootstrap_decision_id,
    canonical_digest,
    empty_canon_manifest,
    resource_revision_digest,
)
from modules.world.models import (
    CoreEntity,
    EntityProfileTemplate,
    EntityProfileTemplateRevision,
    WorldAssertion,
    WorldBiblePage,
    WorldBiblePageDraft,
    WorldBiblePageRevision,
    WorldCanonHead,
    WorldCanonRevision,
)
from modules.world.services.worldbuilding.world_bible_lifecycle_service import (
    WorldBibleLifecycleService,
)
from shared.utils import parse_uuid


def _fail(
    message: str,
    *,
    code: str,
    status_code: int,
) -> DomainError:
    return DomainError(message, code=code, status_code=status_code)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class WorldAuthorityService:
    """Own the one append-only canon head for an author project."""

    async def initialize_empty_canon(
        self,
        db: AsyncSession,
        novel_id: str | uuid.UUID,
    ) -> WorldCanonRevision:
        nid = parse_uuid(str(novel_id), "novel_id")
        head = await db.get(WorldCanonHead, nid)
        if head is not None:
            revision = await db.get(WorldCanonRevision, head.current_revision_id)
            if revision is None:
                raise ConflictError(
                    "World canon head is invalid", code="canon_reference_invalid"
                )
            await self._validate_manifest_replay(db, revision)
            return revision

        manifest = empty_canon_manifest()
        manifest_json = manifest.model_dump(mode="json")
        manifest_digest = canonical_digest(manifest_json)
        admission_input = {
            "kind": "bootstrap_empty",
            "version": 1,
            "novel_id": str(nid),
            "expected_previous_head": None,
        }
        decision_digest = canonical_digest(admission_input)
        revision_id = uuid.uuid4()
        decision_id = bootstrap_decision_id(nid)
        committed_at = datetime.now(UTC)
        receipt = CanonAdmissionReceiptV1.model_validate(
            {
                "kind": "canon_admission_receipt",
                "version": 1,
                "novel_id": str(nid),
                "canon_revision_id": str(revision_id),
                "manifest_digest": manifest_digest,
                "decision": {"id": str(decision_id), "digest": decision_digest},
                "authorizer": {
                    "kind": "bootstrap",
                    "version": 1,
                    "subject": "world.canon.bootstrap",
                },
                "executor": {
                    "kind": "bootstrap",
                    "version": 1,
                    "subject": "world.canon.bootstrap",
                },
                "authorization_policy": BOOTSTRAP_POLICY_REF.model_dump(mode="json"),
                "authorization_decision": "allow",
                "action": "bootstrap_empty_canon",
                "affected_families": [],
                "affected_resources": [],
                "admission_input": admission_input,
                "admission_input_digest": decision_digest,
                "expected_previous_head": None,
                "committed_at": committed_at,
            }
        ).model_dump(mode="json")
        revision = WorldCanonRevision(
            id=revision_id,
            novel_id=nid,
            version_number=0,
            parent_revision_id=None,
            manifest_json=manifest_json,
            manifest_digest=manifest_digest,
            receipt_json=receipt,
            decision_id=decision_id,
            decision_digest=decision_digest,
            created_at=committed_at,
        )
        db.add(revision)
        await db.flush()
        db.add(
            WorldCanonHead(
                novel_id=nid,
                current_revision_id=revision_id,
                updated_at=committed_at,
            )
        )
        await db.flush()
        return revision

    async def get_head(self, db: AsyncSession, novel_id: str) -> CanonHeadResponse:
        nid = parse_uuid(novel_id, "novel_id")
        head = await db.get(WorldCanonHead, nid)
        if head is None:
            raise NotFoundError("World canon head not found")
        revision = await self._get_revision_model(db, nid, head.current_revision_id)
        await self._validate_manifest_replay(db, revision)
        return CanonHeadResponse(
            novel_id=nid,
            current_revision=await self._response(db, revision),
        )

    async def get_revision(
        self,
        db: AsyncSession,
        novel_id: str,
        revision_id: str,
    ) -> CanonRevisionResponse:
        revision = await self._get_revision_model(
            db,
            parse_uuid(novel_id, "novel_id"),
            parse_uuid(revision_id, "revision_id"),
        )
        await self._validate_manifest_replay(db, revision)
        return await self._response(db, revision)

    async def preview(
        self,
        db: AsyncSession,
        request: CanonAdmissionPreviewRequest,
    ) -> CanonAdmissionPreviewResponse:
        self._require_same_novel(request.novel_id, request.input.novel_id)
        head, _current = await self._locked_head(db, request.novel_id)
        if head.current_revision_id != request.expected_previous_head:
            raise _fail(
                "World canon changed; preview again",
                code="canon_admission_stale",
                status_code=409,
            )
        if isinstance(request.input, PagePublishPreviewInputV1):
            normalized, changes = await self._preview_page_publish(db, request.input)
        elif isinstance(request.input, RevertPreviewInputV1):
            normalized, changes = await self._preview_revert(db, request.input, _current)
        else:  # pragma: no cover - discriminated union is closed
            raise _fail(
                "Unsupported admission input",
                code="canon_reference_invalid",
                status_code=422,
            )
        return CanonAdmissionPreviewResponse(
            current_head_id=head.current_revision_id,
            normalized_input=normalized,
            input_digest=self._canonical_digest(normalized),
            changes=changes,
        )

    async def admit(
        self,
        db: AsyncSession,
        request: CanonAdmissionRequest,
        *,
        authorizer_id: uuid.UUID,
        validation_prechecked: bool = False,
    ) -> CanonRevisionResponse:
        self._require_same_novel(request.novel_id, request.input.novel_id)
        await self._require_authorizer(db, request.novel_id, authorizer_id)
        decision_digest = self._decision_digest(
            request.input,
            request.expected_previous_head,
        )
        existing = await db.scalar(
            select(WorldCanonRevision).where(
                WorldCanonRevision.novel_id == request.novel_id,
                WorldCanonRevision.decision_id == request.decision_id,
            )
        )
        if existing is not None:
            if existing.decision_digest != decision_digest:
                raise _fail(
                    "Decision ID was already used for different input",
                    code="canon_decision_id_reused",
                    status_code=409,
                )
            await self._validate_manifest_replay(db, existing)
            return await self._response(db, existing)

        head, current = await self._locked_head(db, request.novel_id)
        if head.current_revision_id != request.expected_previous_head:
            raise _fail(
                "World canon changed; preview again",
                code="canon_admission_stale",
                status_code=409,
            )

        if isinstance(request.input, PagePublishInputV1):
            manifest, affected, action, public_changes = await self._admit_page_publish(
                db,
                request.input,
                current,
                validation_prechecked=validation_prechecked,
            )
        elif isinstance(request.input, RevertInputV1):
            manifest, affected, action, public_changes = await self._admit_revert(
                db, request.input, current
            )
        elif isinstance(request.input, AssertBatchInputV1):
            for assertion in request.input.assertions:
                self._validate_assert_wire(assertion)
            raise _fail(
                "Assertion admission is not enabled in Phase 0",
                code="unsupported_statement_kind",
                status_code=422,
            )
        elif isinstance(request.input, FamilyCutoverInputV1):
            raise _fail(
                "Family cutover requires its own accepted specification",
                code="canon_authorization_denied",
                status_code=403,
            )
        else:
            raise _fail(
                "Bootstrap is only available during project initialization",
                code="canon_authorization_denied",
                status_code=403,
            )
        return await self._append_revision(
            db,
            novel_id=request.novel_id,
            head=head,
            current=current,
            manifest=manifest,
            decision_id=request.decision_id,
            decision_digest=decision_digest,
            admission_input=request.input.model_dump(mode="json"),
            authorizer_id=authorizer_id,
            action=action,
            affected_resources=affected,
            public_changes=public_changes,
        )

    async def resolve_target(
        self,
        db: AsyncSession,
        target: TargetRefV1,
        *,
        novel_id: uuid.UUID,
        for_admission: bool = False,
    ) -> Any:
        ref = target.revision
        self._require_same_novel(novel_id, ref.resource.novel_id)
        snapshot = await self._resolve_revision(db, ref, for_admission=for_admission)
        selector = target.selector
        if selector.kind == "whole":
            return snapshot
        if ref.resource.kind == "world_bible_page":
            if selector.kind == "world_bible_page.field":
                return snapshot.get(selector.payload.field)
            if selector.kind == "world_bible_page.metadata":
                if selector.payload.key not in snapshot.get("page_meta_json", {}):
                    self._invalid_reference("Selected metadata is unavailable")
                return snapshot["page_meta_json"][selector.payload.key]
            if selector.kind == "world_bible_page.section":
                matches = [
                    item
                    for item in snapshot.get("sections_json", [])
                    if item.get("section_id") == selector.payload.section_id
                ]
                if len(matches) != 1:
                    self._invalid_reference("Selected section is not unique")
                return matches[0]
        elif (
            ref.resource.kind == "entity_profile_template"
            and selector.kind == "entity_profile_template.field"
        ):
            fields = snapshot.get("template_schema_json", {}).get("fields", [])
            matches = [
                item for item in fields if item.get("key") == selector.payload.field_key
            ]
            if len(matches) != 1:
                self._invalid_reference("Selected template field is not unique")
            return matches[0]
        self._invalid_reference("Selector does not match resource")

    async def _preview_page_publish(
        self,
        db: AsyncSession,
        request: PagePublishPreviewInputV1,
    ) -> tuple[PagePublishInputV1, dict[str, Any]]:
        draft = await self._get_draft(db, request.novel_id, request.draft_id)
        draft_snapshot = self._draft_snapshot(draft)
        await self._validate_card_subject(
            db, request.novel_id, draft_snapshot.page_meta_json
        )
        impact = await WorldBibleLifecycleService().preview_publish_impact(
            db, str(request.novel_id), str(request.draft_id)
        )
        if (
            request.expected_impact_scope_hash is not None
            and request.expected_impact_scope_hash != impact.impact_scope_hash
        ):
            raise _fail(
                "World Bible references changed; preview again",
                code="canon_admission_stale",
                status_code=409,
            )
        normalized = PagePublishInputV1(
            novel_id=request.novel_id,
            draft_snapshot=draft_snapshot,
            impact_scope_hash=impact.impact_scope_hash,
            validation_run_id=request.validation_run_id,
        )
        return normalized, {
            "action": "publish_page",
            "affected_page_count": len(impact.affected_pages),
        }

    async def _preview_revert(
        self,
        db: AsyncSession,
        request: RevertPreviewInputV1,
        current: WorldCanonRevision,
    ) -> tuple[RevertInputV1, dict[str, Any]]:
        target = await self._get_revision_model(
            db, request.novel_id, request.target_revision_id
        )
        self._require_revert_compatible(current.manifest_json, target.manifest_json)
        await self._validate_manifest_replay(db, target)
        return RevertInputV1(
            novel_id=request.novel_id,
            target_revision_id=request.target_revision_id,
        ), {"action": "restore_history", "target_version": target.version_number}

    async def _admit_page_publish(
        self,
        db: AsyncSession,
        request: PagePublishInputV1,
        current: WorldCanonRevision,
        *,
        validation_prechecked: bool,
    ) -> tuple[CanonManifestV1, list[dict[str, Any]], str, dict[str, Any]]:
        draft = await self._get_draft(
            db, request.novel_id, request.draft_snapshot.draft_id, for_update=True
        )
        if self._draft_snapshot(draft) != request.draft_snapshot:
            raise _fail(
                "World Bible draft changed; preview again",
                code="canon_admission_stale",
                status_code=409,
            )
        await self._validate_card_subject(
            db, request.novel_id, request.draft_snapshot.page_meta_json
        )
        page = await WorldBibleLifecycleService().publish_draft(
            db,
            str(request.novel_id),
            str(request.draft_snapshot.draft_id),
            expected_impact_scope_hash=request.impact_scope_hash,
            validation_run_id=(
                str(request.validation_run_id) if request.validation_run_id else None
            ),
            _validation_prechecked=validation_prechecked,
        )
        revision = await db.scalar(
            select(WorldBiblePageRevision).where(
                WorldBiblePageRevision.novel_id == request.novel_id,
                WorldBiblePageRevision.page_id == parse_uuid(page.id, "page_id"),
                WorldBiblePageRevision.version_number == page.version_number,
            )
        )
        if revision is None:
            raise ConflictError("Published page revision was not sealed")
        exact_ref = ExactResourceRevisionRef(
            resource=ResourceRef(
                kind="world_bible_page",
                novel_id=request.novel_id,
                resource_id=revision.page_id,
            ),
            revision_id=revision.id,
            revision_digest=revision.revision_digest,
        )
        await self._resolve_revision(db, exact_ref, for_admission=True)
        manifest = CanonManifestV1.model_validate(current.manifest_json)
        active_resources = [
            item
            for item in manifest.active_resources
            if not (
                item.resource.kind == exact_ref.resource.kind
                and item.resource.resource_id == exact_ref.resource.resource_id
            )
        ]
        active_resources.append(exact_ref)
        active_resources.sort(
            key=lambda item: (item.resource.kind, str(item.resource.resource_id))
        )
        updated = manifest.model_copy(update={"active_resources": active_resources})
        return (
            updated,
            [exact_ref.model_dump(mode="json")],
            "page_publish",
            {
                "published_page_id": page.id,
                "publication_receipt": (
                    page.validation_receipt.model_dump(mode="json")
                    if page.validation_receipt
                    else None
                ),
            },
        )

    async def _admit_revert(
        self,
        db: AsyncSession,
        request: RevertInputV1,
        current: WorldCanonRevision,
    ) -> tuple[CanonManifestV1, list[dict[str, Any]], str, dict[str, Any]]:
        target = await self._get_revision_model(
            db, request.novel_id, request.target_revision_id
        )
        self._require_revert_compatible(current.manifest_json, target.manifest_json)
        await self._validate_manifest_replay(db, target)
        manifest = CanonManifestV1.model_validate(target.manifest_json)
        return (
            manifest,
            [item.model_dump(mode="json") for item in manifest.active_resources],
            "revert",
            {},
        )

    async def _append_revision(
        self,
        db: AsyncSession,
        *,
        novel_id: uuid.UUID,
        head: WorldCanonHead,
        current: WorldCanonRevision,
        manifest: CanonManifestV1,
        decision_id: uuid.UUID,
        decision_digest: str,
        admission_input: dict[str, Any],
        authorizer_id: uuid.UUID,
        action: str,
        affected_resources: list[dict[str, Any]],
        public_changes: dict[str, Any],
    ) -> CanonRevisionResponse:
        manifest_json = manifest.model_dump(mode="json")
        await self._validate_manifest_refs(db, novel_id, manifest)
        manifest_digest = self._canonical_digest(manifest_json)
        revision_id = uuid.uuid4()
        committed_at = datetime.now(UTC)
        receipt = CanonAdmissionReceiptV1.model_validate(
            {
                "kind": "canon_admission_receipt",
                "version": 1,
                "novel_id": str(novel_id),
                "canon_revision_id": str(revision_id),
                "manifest_digest": manifest_digest,
                "decision": {"id": str(decision_id), "digest": decision_digest},
                "authorizer": {
                    "kind": "account",
                    "version": 1,
                    "account_id": str(authorizer_id),
                },
                "executor": {
                    "kind": "account_request",
                    "version": 1,
                    "account_id": str(authorizer_id),
                },
                "authorization_policy": EXPLICIT_AUTHOR_POLICY_REF.model_dump(
                    mode="json"
                ),
                "authorization_decision": "allow",
                "action": action,
                "affected_families": [],
                "affected_resources": affected_resources,
                "admission_input": admission_input,
                "admission_input_digest": self._canonical_digest(admission_input),
                "expected_previous_head": str(current.id),
                "committed_at": committed_at,
            }
        ).model_dump(mode="json")
        revision = WorldCanonRevision(
            id=revision_id,
            novel_id=novel_id,
            version_number=current.version_number + 1,
            parent_revision_id=current.id,
            manifest_json=manifest_json,
            manifest_digest=manifest_digest,
            receipt_json=receipt,
            decision_id=decision_id,
            decision_digest=decision_digest,
            created_at=committed_at,
        )
        db.add(revision)
        await db.flush()
        result = await db.execute(
            update(WorldCanonHead)
            .where(
                WorldCanonHead.novel_id == novel_id,
                WorldCanonHead.current_revision_id == current.id,
            )
            .values(current_revision_id=revision_id, updated_at=committed_at)
        )
        if result.rowcount != 1:
            raise _fail(
                "World canon changed; no changes were saved",
                code="canon_head_conflict",
                status_code=409,
            )
        head.current_revision_id = revision_id
        head.updated_at = committed_at
        await db.flush()
        response = await self._response(db, revision)
        changes = {**response.changes, **public_changes}
        return response.model_copy(update={"changes": changes})

    async def _resolve_revision(
        self,
        db: AsyncSession,
        ref: ExactResourceRevisionRef,
        *,
        for_admission: bool,
    ) -> dict[str, Any]:
        resource = ref.resource
        if resource.kind == "world_bible_page":
            revision = await db.scalar(
                select(WorldBiblePageRevision).where(
                    WorldBiblePageRevision.id == ref.revision_id,
                    WorldBiblePageRevision.novel_id == resource.novel_id,
                    WorldBiblePageRevision.page_id == resource.resource_id,
                )
            )
            if revision is None:
                self._unavailable_reference()
            if revision.revision_digest != ref.revision_digest:
                self._digest_mismatch()
            actual = resource_revision_digest(
                resource, revision.id, revision.snapshot_json
            )
            if actual != ref.revision_digest:
                self._digest_mismatch()
            await self._validate_card_subject(
                db, resource.novel_id, revision.snapshot_json.get("page_meta_json")
            )
            if for_admission:
                head = await db.scalar(
                    select(WorldBiblePage).where(
                        WorldBiblePage.id == resource.resource_id,
                        WorldBiblePage.novel_id == resource.novel_id,
                        WorldBiblePage.status.in_({"canonical", "confirmed"}),
                    )
                )
                if head is None:
                    self._unavailable_reference()
            return revision.snapshot_json
        if resource.kind == "entity_profile_template":
            revision = await db.scalar(
                select(EntityProfileTemplateRevision).where(
                    EntityProfileTemplateRevision.id == ref.revision_id,
                    EntityProfileTemplateRevision.novel_id == resource.novel_id,
                    EntityProfileTemplateRevision.template_id == resource.resource_id,
                )
            )
            if revision is None:
                self._unavailable_reference()
            if revision.revision_digest != ref.revision_digest:
                self._digest_mismatch()
            actual = resource_revision_digest(
                resource, revision.id, revision.snapshot_json
            )
            if actual != ref.revision_digest:
                self._digest_mismatch()
            if for_admission:
                head = await db.scalar(
                    select(EntityProfileTemplate).where(
                        EntityProfileTemplate.id == resource.resource_id,
                        EntityProfileTemplate.novel_id == resource.novel_id,
                        EntityProfileTemplate.status == "active",
                    )
                )
                if head is None:
                    self._unavailable_reference()
            return revision.snapshot_json
        self._invalid_reference("Unknown resource kind")

    async def _validate_manifest_replay(
        self,
        db: AsyncSession,
        revision: WorldCanonRevision,
    ) -> None:
        try:
            manifest = CanonManifestV1.model_validate(revision.manifest_json)
            manifest_digest = canonical_digest(manifest)
        except (TypeError, ValueError):
            self._digest_mismatch()
        if manifest_digest != revision.manifest_digest:
            self._digest_mismatch()
        try:
            receipt = CanonAdmissionReceiptV1.model_validate(revision.receipt_json)
        except (TypeError, ValueError):
            self._digest_mismatch()
        if (
            receipt.novel_id != revision.novel_id
            or receipt.canon_revision_id != revision.id
            or receipt.manifest_digest != revision.manifest_digest
            or receipt.decision.id != revision.decision_id
            or receipt.decision.digest != revision.decision_digest
            or receipt.expected_previous_head != revision.parent_revision_id
            or _as_utc(receipt.committed_at) != _as_utc(revision.created_at)
        ):
            self._digest_mismatch()
        for ref in receipt.affected_resources:
            self._require_same_novel(revision.novel_id, ref.resource.novel_id)
            await self._resolve_revision(db, ref, for_admission=False)
        await self._validate_manifest_refs(db, revision.novel_id, manifest)

    async def _validate_manifest_refs(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        manifest: CanonManifestV1,
    ) -> None:
        for ref in manifest.active_resources:
            self._require_same_novel(novel_id, ref.resource.novel_id)
            await self._resolve_revision(db, ref, for_admission=False)
        if manifest.validation_policy_ref is not None:
            ref = manifest.validation_policy_ref
            self._require_same_novel(novel_id, ref.resource.novel_id)
            if ref.resource.kind != "world_bible_page":
                self._invalid_reference("Validation policy must be a World Bible page")
            await self._resolve_revision(db, ref, for_admission=False)
        if manifest.calendar_ref is not None:
            self._invalid_reference("No supported world calendar is registered")
        for dependency in manifest.pinned_dependencies:
            self._require_same_novel(novel_id, dependency.revision.resource.novel_id)
            await self.resolve_target(db, dependency, novel_id=novel_id)
        selected_ids = {ref.assert_id for ref in manifest.selected_assertions}
        checked: dict[uuid.UUID, str] = {}
        for ref in manifest.selected_assertions:
            await self._validate_assertion_ref(
                db,
                novel_id,
                ref,
                selected_ids=selected_ids,
                visiting=set(),
                checked=checked,
            )

    async def _validate_assertion_ref(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        ref: AssertRefV1,
        *,
        selected_ids: set[uuid.UUID],
        visiting: set[uuid.UUID],
        checked: dict[uuid.UUID, str],
    ) -> None:
        self._require_same_novel(novel_id, ref.novel_id)
        checked_digest = checked.get(ref.assert_id)
        if checked_digest is not None:
            if checked_digest != ref.assert_digest:
                self._digest_mismatch()
            return
        if ref.assert_id in visiting:
            raise _fail(
                "Assertion grounds contain a cycle",
                code="canon_ground_cycle",
                status_code=422,
            )
        assertion = await db.scalar(
            select(WorldAssertion).where(
                WorldAssertion.id == ref.assert_id,
                WorldAssertion.novel_id == novel_id,
            )
        )
        if assertion is None:
            self._unavailable_reference()
        if assertion.content_digest != ref.assert_digest:
            self._digest_mismatch()
        try:
            value = AssertValueV1.model_validate(
                {
                    "novel_id": assertion.novel_id,
                    "regime": assertion.regime,
                    "polarity": assertion.polarity,
                    "statement": assertion.statement_json,
                    "schema_ref": assertion.schema_ref_json,
                    "time_scope": assertion.time_scope_json,
                    "source_refs": assertion.source_refs_json,
                    "hard_grounds": assertion.hard_ground_refs_json,
                    "provenance_actor_ref": assertion.provenance_actor_ref_json,
                }
            )
        except ValueError:
            self._digest_mismatch()
        if assertion_content_digest(value) != assertion.content_digest:
            self._digest_mismatch()
        self._validate_assert_wire(value)
        statement = value.statement
        if isinstance(statement, EntityScalarStatementV1):
            schema_ref = statement.field.schema_revision
            if schema_ref.resource.kind != "entity_profile_template":
                self._invalid_reference("Scalar schema must be a profile template")
            await self._resolve_revision(db, schema_ref, for_admission=False)
        referent_ids = [statement.subject.referent_id]
        if isinstance(statement, EntityRelationStatementV1):
            referent_ids.append(statement.object.referent_id)
        existing_referents = set(
            (
                await db.scalars(
                    select(CoreEntity.id).where(
                        CoreEntity.novel_id == novel_id,
                        CoreEntity.id.in_(referent_ids),
                    )
                )
            ).all()
        )
        if existing_referents != set(referent_ids):
            self._unavailable_reference()
        for source in value.source_refs:
            await self.resolve_target(db, source, novel_id=novel_id)
        visiting.add(ref.assert_id)
        for ground in value.hard_grounds:
            if isinstance(ground, AssertRefV1):
                if ground.assert_id not in selected_ids:
                    raise _fail(
                        "Assertion ground is not selected by this Canon revision",
                        code="canon_ground_cycle",
                        status_code=422,
                    )
                await self._validate_assertion_ref(
                    db,
                    novel_id,
                    ground,
                    selected_ids=selected_ids,
                    visiting=visiting,
                    checked=checked,
                )
            else:
                if ground.revision.resource.kind == "world_bible_page":
                    self._invalid_reference(
                        "Document pages cannot be formal hard grounds"
                    )
                await self.resolve_target(db, ground, novel_id=novel_id)
        visiting.remove(ref.assert_id)
        checked[ref.assert_id] = ref.assert_digest

    async def _validate_card_subject(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        page_meta: Any,
    ) -> None:
        if not isinstance(page_meta, dict):
            self._invalid_reference("World Bible page metadata must be an object")
        subject = page_meta.get("card_subject_ref_v1")
        if subject is None:
            return
        if (
            not isinstance(subject, dict)
            or set(subject) != {"kind", "entity_id"}
            or subject.get("kind") != "core_entity"
        ):
            self._invalid_reference("World Bible card subject is invalid")
        try:
            entity_id = uuid.UUID(str(subject["entity_id"]))
        except (TypeError, ValueError) as exc:
            raise _fail(
                "World Bible card subject is invalid",
                code="canon_reference_invalid",
                status_code=422,
            ) from exc
        exists = await db.scalar(
            select(CoreEntity.id).where(
                CoreEntity.id == entity_id,
                CoreEntity.novel_id == novel_id,
            )
        )
        if exists is None:
            self._unavailable_reference()

    async def _locked_head(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
    ) -> tuple[WorldCanonHead, WorldCanonRevision]:
        head = await db.scalar(
            select(WorldCanonHead)
            .where(WorldCanonHead.novel_id == novel_id)
            .with_for_update()
        )
        if head is None:
            raise NotFoundError("World canon head not found")
        current = await self._get_revision_model(db, novel_id, head.current_revision_id)
        await self._validate_manifest_replay(db, current)
        return head, current

    @staticmethod
    async def _get_revision_model(
        db: AsyncSession,
        novel_id: uuid.UUID,
        revision_id: uuid.UUID,
    ) -> WorldCanonRevision:
        revision = await db.scalar(
            select(WorldCanonRevision).where(
                WorldCanonRevision.id == revision_id,
                WorldCanonRevision.novel_id == novel_id,
            )
        )
        if revision is None:
            raise NotFoundError("World canon revision not found")
        return revision

    async def _response(
        self,
        db: AsyncSession,
        revision: WorldCanonRevision,
    ) -> CanonRevisionResponse:
        changes: dict[str, Any] = {
            "resource_count": len(revision.manifest_json.get("active_resources", [])),
            "assertion_count": len(revision.manifest_json.get("selected_assertions", [])),
        }
        if revision.receipt_json.get("action") == "page_publish":
            affected = revision.receipt_json.get("affected_resources", [])
            if affected:
                changes["published_page_id"] = affected[0]["resource"]["resource_id"]
        if revision.parent_revision_id is not None:
            parent = await self._get_revision_model(
                db, revision.novel_id, revision.parent_revision_id
            )
            changes["resource_count_delta"] = changes["resource_count"] - len(
                parent.manifest_json.get("active_resources", [])
            )
            changes["assertion_count_delta"] = changes["assertion_count"] - len(
                parent.manifest_json.get("selected_assertions", [])
            )
        return CanonRevisionResponse(
            id=revision.id,
            novel_id=revision.novel_id,
            version_number=revision.version_number,
            parent_revision_id=revision.parent_revision_id,
            manifest_digest=revision.manifest_digest,
            created_at=revision.created_at,
            changes=changes,
        )

    @staticmethod
    async def _get_draft(
        db: AsyncSession,
        novel_id: uuid.UUID,
        draft_id: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> WorldBiblePageDraft:
        stmt = select(WorldBiblePageDraft).where(
            WorldBiblePageDraft.id == draft_id,
            WorldBiblePageDraft.novel_id == novel_id,
        )
        if for_update:
            stmt = stmt.with_for_update()
        draft = await db.scalar(stmt)
        if draft is None:
            raise NotFoundError("World Bible draft not found")
        return draft

    @staticmethod
    def _draft_snapshot(draft: WorldBiblePageDraft) -> PageDraftSnapshotV1:
        if draft.updated_at is None:
            raise ConflictError("World Bible draft has no revision timestamp")
        return PageDraftSnapshotV1(
            draft_id=draft.id,
            page_id=draft.page_id,
            base_version_number=draft.base_version_number,
            title=draft.title,
            page_type=draft.page_type,
            page_meta_json=draft.page_meta_json,
            free_text=draft.free_text,
            sections_json=draft.sections_json,
            linked_asset_refs_json=draft.linked_asset_refs_json,
            sort_order=draft.sort_order,
            template_key=draft.template_key,
            template_version=draft.template_version,
            updated_at=draft.updated_at,
        )

    @staticmethod
    def _require_same_novel(left: uuid.UUID, right: uuid.UUID) -> None:
        if left != right:
            raise _fail(
                "Canonical reference is unavailable",
                code="canon_reference_unavailable",
                status_code=404,
            )

    @staticmethod
    async def _require_authorizer(
        db: AsyncSession,
        novel_id: uuid.UUID,
        authorizer_id: uuid.UUID,
    ) -> None:
        context = await get_project_context(db, str(novel_id))
        if context is None or context.owner_id != str(authorizer_id):
            raise _fail(
                "Canon admission is not authorized",
                code="canon_authorization_denied",
                status_code=403,
            )

    @classmethod
    def _decision_digest(cls, input_value: Any, expected_head: uuid.UUID) -> str:
        return cls._canonical_digest(
            {
                "kind": "canon_decision",
                "version": 1,
                "expected_previous_head": expected_head,
                "admission_input_digest": cls._canonical_digest(input_value),
            }
        )

    @staticmethod
    def _canonical_digest(value: Any) -> str:
        try:
            return canonical_digest(value)
        except (TypeError, ValueError) as exc:
            raise _fail(
                "Canonical input is invalid",
                code="canon_reference_invalid",
                status_code=422,
            ) from exc

    @classmethod
    def _validate_assert_wire(cls, assertion: AssertValueV1) -> None:
        cls._require_same_novel(assertion.novel_id, assertion.statement.subject.novel_id)
        if assertion.statement.kind == "entity_relation":
            cls._require_same_novel(
                assertion.novel_id, assertion.statement.object.novel_id
            )
        if assertion.time_scope.kind != "timeless":
            raise _fail(
                "No supported world calendar is registered",
                code="unsupported_calendar",
                status_code=422,
            )
        if assertion.statement.kind in {"entity_name", "entity_relation"}:
            if not isinstance(assertion.schema_ref, VersionedArtifactRef):
                cls._invalid_reference("Statement schema must use the sealed artifact")
            if assertion.schema_ref != STATEMENT_SCHEMA_REF:
                cls._invalid_reference("Statement schema artifact does not match")
        elif assertion.statement.kind == "entity_scalar":
            if not isinstance(assertion.schema_ref, ExactResourceRevisionRef):
                cls._invalid_reference("Scalar schema must be an exact template revision")
            if assertion.schema_ref != assertion.statement.field.schema_revision:
                cls._invalid_reference("Scalar field schema does not match")
            cls._require_same_novel(
                assertion.novel_id,
                assertion.statement.field.schema_revision.resource.novel_id,
            )
        for source in assertion.source_refs:
            cls._require_same_novel(assertion.novel_id, source.revision.resource.novel_id)
        for ground in assertion.hard_grounds:
            cls._require_same_novel(
                assertion.novel_id,
                (
                    ground.novel_id
                    if ground.kind == "assert_ref"
                    else ground.revision.resource.novel_id
                ),
            )
            if (
                ground.kind == "target_ref"
                and ground.revision.resource.kind == "world_bible_page"
            ):
                cls._invalid_reference("Document pages cannot be formal hard grounds")

    @staticmethod
    def _require_revert_compatible(
        current_manifest: dict[str, Any],
        target_manifest: dict[str, Any],
    ) -> None:
        current = CanonManifestV1.model_validate(current_manifest)
        target = CanonManifestV1.model_validate(target_manifest)
        for family, authority in current.family_authority.items():
            if (
                authority == "canon-owned"
                and target.family_authority[family] != authority
            ):
                raise _fail(
                    "History restore would reverse a family cutover",
                    code="incompatible_revert_target",
                    status_code=409,
                )

    @staticmethod
    def _invalid_reference(message: str) -> None:
        raise _fail(message, code="canon_reference_invalid", status_code=422)

    @staticmethod
    def _unavailable_reference() -> None:
        raise _fail(
            "Canonical reference is unavailable",
            code="canon_reference_unavailable",
            status_code=404,
        )

    @staticmethod
    def _digest_mismatch() -> None:
        raise _fail(
            "Canonical revision digest does not match",
            code="canon_revision_digest_mismatch",
            status_code=409,
        )
