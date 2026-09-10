"""Durable World Bible validation runs and canon-write gates."""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, NotFoundError, ValidationError
from infrastructure.llm.agent_step_harness import run_managed_structured
from infrastructure.llm.redaction import redact_diagnostic
from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
from infrastructure.tasks.facade import (
    enqueue_task_with_optional_operation,
    get_operation_task,
    require_running_task_attempt,
)
from modules.project.facade import (
    build_project_llm_execution_snapshot,
    create_project_snapshot_llm_client,
    get_project_context,
    restore_project_llm_execution_settings,
)
from modules.world.models import (
    CoreEntity,
    CreationSuggestion,
    WorldBiblePage,
    WorldBiblePageDraft,
    WorldValidationReviewItem,
    WorldValidationRun,
)
from modules.world.schemas import (
    WorldBiblePageCreate,
    WorldBiblePageDraftCreate,
    WorldBiblePageResponse,
    WorldDesignCheckpointPayload,
    WorldValidationFinding,
    WorldValidationFindingsPage,
    WorldValidationPolicy,
    WorldValidationPolicyDraftInfo,
    WorldValidationPolicyDraftUpsert,
    WorldValidationPolicyStatus,
    WorldValidationReviewItemRecord,
    WorldValidationReviewListResponse,
    WorldValidationRunCreate,
    WorldValidationRunListResponse,
    WorldValidationRunResponse,
    WorldValidationSemanticOutput,
    WorldValidationWarningAcceptRequest,
)
from modules.world.services.worldbuilding.adoption_package_service import (
    WorldAdoptionPackageService,
)
from modules.world.services.worldbuilding.world_authority_service import (
    WorldAuthorityService,
)
from modules.world.services.worldbuilding.world_bible_lifecycle_service import (
    WorldBibleLifecycleService,
)
from modules.world.services.worldbuilding.world_impact_service import (
    WorldImpactService,
)
from modules.world.services.worldbuilding.world_validation_engine import (
    build_review_packets,
    deterministic_findings,
    overall_result,
    stable_hash,
    validate_semantic_output,
)
from shared.utils import parse_uuid

if TYPE_CHECKING:
    from modules.evidence.contracts import ConfirmedAIActionContext

_POLICY_PAGE_KEY = "validation-policy"
_ADOPTED_STATUSES = ("canonical", "confirmed")


class WorldValidationService:
    def __init__(self) -> None:
        self._lifecycle = WorldBibleLifecycleService()
        self._authority = WorldAuthorityService()
        self._adoption = WorldAdoptionPackageService()
        self._impact = WorldImpactService()

    @staticmethod
    def builtin_policy() -> WorldValidationPolicy:
        return WorldValidationPolicy(
            schema_version="world_validation_policy.v1",
            policy_version="builtin-v1",
        )

    @staticmethod
    def assistant_advisory_policy() -> WorldValidationPolicy:
        """An opt-in diagnostic default, never a replacement Canon policy."""
        return WorldValidationPolicy(
            schema_version="world_validation_policy.v1",
            policy_version="assistant-advisory-v1",
            semantic_enabled=True,
            max_packets=6,
            required_questions=[
                {
                    "question_id": "internal-consistency",
                    "gate": "structure",
                    "question": (
                        "资料中是否存在可以用精确引文证明的直接矛盾？"
                        "资料不足、刻意留白与角色误解不能判为矛盾。"
                    ),
                },
                {
                    "question_id": "causal-consequences",
                    "gate": "narrative",
                    "question": (
                        "已声明的规则、代价和结果是否有缺失的因果环节？"
                        "区分明确冲突、待作者决定的建议与尚无证据。"
                    ),
                },
            ],
        )

    async def active_policy(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> tuple[WorldValidationPolicy, str] | None:
        candidates = await self._active_policy_candidates(db, novel_id)
        if not candidates:
            return None
        _, policy = candidates[0]
        return policy, stable_hash(policy.model_dump(mode="json"))

    async def _active_policy_candidates(
        self, db: AsyncSession, novel_id: str, *, include_disabled: bool = False
    ) -> list[tuple[WorldBiblePage, WorldValidationPolicy]]:
        pages = list(
            (
                await db.execute(
                    select(WorldBiblePage)
                    .where(
                        WorldBiblePage.novel_id == parse_uuid(novel_id, "novel_id"),
                        WorldBiblePage.status.in_(_ADOPTED_STATUSES),
                        WorldBiblePage.page_type == "rule",
                    )
                    .order_by(WorldBiblePage.id)
                )
            )
            .scalars()
            .all()
        )
        candidates: list[tuple[WorldBiblePage, WorldValidationPolicy]] = []
        for page in pages:
            raw = dict(page.page_meta_json or {}).get("validation_policy")
            if not isinstance(raw, dict):
                continue
            policy = WorldValidationPolicy.model_validate(raw)
            if policy.enabled or include_disabled:
                candidates.append((page, policy))
        if len(candidates) > 1:
            raise ConflictError("Multiple active World validation policies exist")
        return candidates

    async def policy_status(
        self, db: AsyncSession, novel_id: str
    ) -> WorldValidationPolicyStatus:
        active = await self.active_policy(db, novel_id)
        policy = active[0] if active else self.builtin_policy()
        estimate: dict[str, int] = {
            "planned_input_characters": 0,
            "planned_packets": 0,
        }
        if policy.semantic_enabled:
            manifest, _, _ = await self._freeze_manifest(
                db,
                novel_id=novel_id,
                scope="full",
                target_type=None,
                target_id=None,
            )
            _, estimate = build_review_packets(
                run_id="estimate",
                scope="full",
                policy=policy,
                manifest=manifest,
            )
        estimated_characters = estimate["planned_input_characters"]
        estimated_packets = estimate["planned_packets"]
        return WorldValidationPolicyStatus(
            active=active is not None,
            policy_version=active[0].policy_version if active else None,
            semantic_enabled=policy.semantic_enabled,
            estimated_input_characters=estimated_characters,
            estimated_packets=estimated_packets,
            max_input_characters=policy.max_input_characters,
            max_packets=policy.max_packets,
            will_exceed_budget=(
                estimated_characters > policy.max_input_characters
                or estimated_packets > policy.max_packets
            ),
            policy=policy if active else None,
            draft=await self._policy_draft_info(db, novel_id),
        )

    async def _policy_draft_info(
        self, db: AsyncSession, novel_id: str
    ) -> WorldValidationPolicyDraftInfo | None:
        page = await db.scalar(
            select(WorldBiblePage).where(
                WorldBiblePage.novel_id == parse_uuid(novel_id, "novel_id"),
                WorldBiblePage.page_key == _POLICY_PAGE_KEY,
            )
        )
        if page is None:
            return None
        draft = await db.scalar(
            select(WorldBiblePageDraft)
            .where(
                WorldBiblePageDraft.novel_id == parse_uuid(novel_id, "novel_id"),
                WorldBiblePageDraft.page_id == page.id,
            )
            .order_by(WorldBiblePageDraft.created_at.desc())
        )
        if draft is None:
            return None
        raw = dict(draft.page_meta_json or {}).get("validation_policy")
        if not isinstance(raw, dict):
            return None
        return WorldValidationPolicyDraftInfo(
            draft_id=str(draft.id),
            page_id=str(page.id) if page.id else None,
            updated_at=draft.updated_at,
            policy=WorldValidationPolicy.model_validate(raw),
        )

    async def save_policy_draft(
        self,
        db: AsyncSession,
        novel_id: str,
        data: WorldValidationPolicyDraftUpsert,
    ):
        """Persist an author-edited policy onto the rule page draft (ADR-0022).

        Publishing still goes through the standard draft publish flow, which
        enforces a full-scope validation because rule pages are full-scope
        targets; the active policy (and its hash) only change on admission.
        """
        from modules.world.schemas import WorldBiblePageDraftUpdate

        nid = parse_uuid(novel_id, "novel_id")
        page = await db.scalar(
            select(WorldBiblePage).where(
                WorldBiblePage.novel_id == nid,
                WorldBiblePage.page_key == _POLICY_PAGE_KEY,
            )
        )
        if page is None:
            staged = await self._lifecycle.create_page(
                db,
                WorldBiblePageCreate(
                    novel_id=novel_id,
                    page_key=_POLICY_PAGE_KEY,
                    page_type="rule",
                    title="世界书校验策略",
                    status="draft",
                    page_meta_json={
                        "validation_policy": data.policy.model_dump(mode="json")
                    },
                    free_text=data.summary or "项目校验政策草稿。",
                    created_by="world_health",
                ),
            )
            draft = await self._lifecycle.create_draft(
                db,
                WorldBiblePageDraftCreate(
                    novel_id=novel_id,
                    page_id=staged.id,
                    created_by="world_health",
                ),
            )
            return draft
        draft = await db.scalar(
            select(WorldBiblePageDraft)
            .where(
                WorldBiblePageDraft.novel_id == nid,
                WorldBiblePageDraft.page_id == page.id,
            )
            .order_by(WorldBiblePageDraft.created_at.desc())
        )
        if draft is None:
            draft = await self._lifecycle.create_draft(
                db,
                WorldBiblePageDraftCreate(
                    novel_id=novel_id,
                    page_id=str(page.id),
                    created_by="world_health",
                ),
            )
        meta = dict(draft.page_meta_json or {})
        meta["validation_policy"] = data.policy.model_dump(mode="json")
        update = WorldBiblePageDraftUpdate(page_meta_json=meta)
        if data.summary:
            update = WorldBiblePageDraftUpdate(
                page_meta_json=meta, free_text=data.summary
            )
        return await self._lifecycle.update_draft(db, novel_id, str(draft.id), update)

    async def activate_builtin_policy(
        self, db: AsyncSession, novel_id: str
    ) -> WorldBiblePageResponse:
        candidates = await self._active_policy_candidates(db, novel_id)
        if candidates:
            return WorldBiblePageResponse.model_validate(candidates[0][0])
        existing = await db.scalar(
            select(WorldBiblePage).where(
                WorldBiblePage.novel_id == parse_uuid(novel_id, "novel_id"),
                WorldBiblePage.page_key == _POLICY_PAGE_KEY,
            )
        )
        if existing is not None:
            if await self.active_policy(db, novel_id) is None:
                raise ConflictError(
                    "A validation policy page already exists but is not active"
                )
            return WorldBiblePageResponse.model_validate(existing)
        policy = self.builtin_policy().model_copy(
            update={"policy_version": "project-default-v1"}
        )
        context = await get_project_context(db, novel_id)
        if context is None or not context.owner_id:
            raise ConflictError("Active project owner is unavailable")
        expected_canon_head = await self._authority.lock_head_for_admission(db, novel_id)
        async with db.begin_nested():
            staged = await self._lifecycle.create_page(
                db,
                WorldBiblePageCreate(
                    novel_id=novel_id,
                    page_key=_POLICY_PAGE_KEY,
                    page_type="rule",
                    title="世界书校验策略",
                    status="draft",
                    page_meta_json={"validation_policy": policy.model_dump(mode="json")},
                    free_text=(
                        "已启用世界书结构、证据、依赖和作者裁定门禁。"
                        "语义审计需在高级策略中明确启用。"
                    ),
                    created_by="world_health",
                ),
            )
            draft = await self._lifecycle.create_draft(
                db,
                WorldBiblePageDraftCreate(
                    novel_id=novel_id,
                    page_id=staged.id,
                    created_by="world_health",
                ),
            )
            return await self._lifecycle.admit_draft(
                db,
                novel_id,
                draft.id,
                authorizer_id=context.owner_id,
                expected_canon_head=expected_canon_head,
            )

    async def create_run(
        self,
        db: AsyncSession,
        data: WorldValidationRunCreate,
        *,
        assistant_advisory: bool = False,
        llm_execution_snapshot: dict | None = None,
    ) -> WorldValidationRunResponse:
        request_payload = data.model_dump(mode="json", exclude={"operation_id"})
        existing = await get_operation_task(
            db,
            operation_id=str(data.operation_id),
            task_type="world_validation",
            novel_id=data.novel_id,
            request_payload=request_payload,
        )
        if existing is not None:
            run = await self._get_model(db, data.novel_id, str(data.operation_id))
            return self.response(run)
        if data.scope == "full":
            active = await db.scalar(
                select(WorldValidationRun.id).where(
                    WorldValidationRun.novel_id == parse_uuid(data.novel_id, "novel_id"),
                    WorldValidationRun.scope == "full",
                    WorldValidationRun.status.in_(("queued", "running")),
                )
            )
            if active is not None:
                raise ConflictError(
                    "A full World Bible validation is already running",
                    code="world_validation_full_in_progress",
                    context={"run_id": str(active)},
                )

        active_policy = await self.active_policy(db, data.novel_id)
        published = (
            await self._active_policy_candidates(db, data.novel_id, include_disabled=True)
            if assistant_advisory
            else []
        )
        if assistant_advisory and active_policy is None and published:
            raise ConflictError("作者已关闭世界复核政策，请在世界复核设置中调整")
        advisory = assistant_advisory and active_policy is None
        fallback = self.assistant_advisory_policy() if advisory else self.builtin_policy()
        policy, policy_hash = active_policy or (
            fallback,
            stable_hash(fallback.model_dump(mode="json")),
        )
        manifest, dependency_hash, target_hash = await self._freeze_manifest(
            db,
            novel_id=data.novel_id,
            scope=data.scope,
            target_type=data.target_type,
            target_id=data.target_id,
            root_type=data.root_type,
        )
        snapshot = {}
        if policy.semantic_enabled:
            if llm_execution_snapshot is None:
                snapshot = await build_project_llm_execution_snapshot(db, data.novel_id)
            else:
                await restore_project_llm_execution_settings(
                    db, data.novel_id, llm_execution_snapshot
                )
                snapshot = llm_execution_snapshot
        impact = await self._impact.snapshot(
            db,
            data.novel_id,
            scope=data.scope,
            target_type=data.target_type,
            target_id=data.target_id,
            root_type=data.root_type,
        )
        plan: dict[str, Any] = {}
        if policy.semantic_enabled:
            _, estimate = build_review_packets(
                run_id="estimate",
                scope=data.scope,
                policy=policy,
                manifest=manifest,
            )
            plan = {
                "planned_packets": int(estimate.get("planned_packets") or 0),
                "planned_input_characters": int(
                    estimate.get("planned_input_characters") or 0
                ),
            }
        run = WorldValidationRun(
            id=data.operation_id,
            novel_id=parse_uuid(data.novel_id, "novel_id"),
            trigger=data.trigger,
            scope=data.scope,
            scope_json={
                "target_type": data.target_type,
                "target_id": data.target_id,
                "target_hash": target_hash,
                "root_type": data.root_type,
                **({"purpose": "assistant_advisory"} if advisory else {}),
                "required_question_ids": [
                    item.question_id for item in policy.required_questions
                ],
            },
            status="queued",
            policy_version=policy.policy_version,
            policy_hash=policy_hash,
            manifest_json=manifest,
            manifest_hash=stable_hash(manifest),
            dependency_hash=dependency_hash,
            model_snapshot_json=snapshot,
            impact_json=impact,
            plan_json={
                **plan,
                **(
                    {"advisory_policy": policy.model_dump(mode="json")}
                    if advisory
                    else {}
                ),
            },
        )
        db.add(run)
        await db.flush()
        receipt = await enqueue_task_with_optional_operation(
            db,
            operation_id=str(data.operation_id),
            task_type="world_validation",
            novel_id=data.novel_id,
            request_payload=request_payload,
            meta={
                "novel_id": data.novel_id,
                "run_id": str(run.id),
                "context_confirmation_id": data.context_confirmation_id,
            },
        )
        run.task_id = uuid.UUID(receipt.task_id)
        await db.flush()
        return await self._enriched_response(db, [run])

    async def get(
        self,
        db: AsyncSession,
        novel_id: str,
        run_id: str,
    ) -> WorldValidationRunResponse:
        run = await self._get_model(db, novel_id, run_id)
        await self._refresh_freshness(db, run)
        return await self._enriched_response(db, [run])

    async def latest(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        scope: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
    ) -> WorldValidationRunResponse | None:
        statement = select(WorldValidationRun).where(
            WorldValidationRun.novel_id == parse_uuid(novel_id, "novel_id")
        )
        if scope:
            statement = statement.where(WorldValidationRun.scope == scope)
        runs = (
            (
                await db.execute(
                    statement.order_by(WorldValidationRun.created_at.desc()).limit(100)
                )
            )
            .scalars()
            .all()
        )
        run = next(
            (
                item
                for item in runs
                if (
                    target_type is None
                    or item.scope_json.get("target_type") == target_type
                )
                and (target_id is None or item.scope_json.get("target_id") == target_id)
            ),
            None,
        )
        if run is None:
            return None
        await self._refresh_freshness(db, run)
        return await self._enriched_response(db, [run])

    async def list_runs(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        limit: int = 10,
    ) -> WorldValidationRunListResponse:
        nid = parse_uuid(novel_id, "novel_id")
        total = int(
            await db.scalar(
                select(func.count())
                .select_from(WorldValidationRun)
                .where(WorldValidationRun.novel_id == nid)
            )
            or 0
        )
        runs = list(
            (
                await db.execute(
                    select(WorldValidationRun)
                    .where(WorldValidationRun.novel_id == nid)
                    .order_by(WorldValidationRun.created_at.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        for run in runs:
            await self._refresh_freshness(db, run)
        items = await self._enriched_responses(db, runs)
        return WorldValidationRunListResponse(items=items, total=total)

    async def accept_warnings(
        self,
        db: AsyncSession,
        novel_id: str,
        run_id: str,
        data: WorldValidationWarningAcceptRequest,
    ) -> WorldValidationRunResponse:
        run = await self._get_model(db, novel_id, run_id, for_update=True)
        await self._refresh_freshness(db, run)
        receipt_hash = self._receipt_hash(run)
        warning_ids = {
            item.get("finding_id")
            for item in run.findings_json
            if item.get("severity") == "warning"
        }
        if run.status != "completed" or run.gate != "warn":
            raise ConflictError("Only a fresh warning validation can be accepted")
        if data.expected_receipt_hash != receipt_hash:
            raise ConflictError("Validation receipt changed; review the latest result")
        if set(data.finding_ids) != warning_ids:
            raise ValidationError("All warning finding ids must be accepted exactly once")
        context = await get_project_context(db, novel_id)
        if context is None or not context.owner_id:
            raise ConflictError("Active project owner is unavailable")
        run.warning_receipt_json = {
            "receipt_hash": receipt_hash,
            "finding_ids": sorted(warning_ids),
            "reason": data.reason,
            "accepted_by": context.owner_id,
            "accepted_at": datetime.now(UTC).isoformat(),
        }
        await db.flush()
        return await self._enriched_response(db, [run])

    async def require_gate(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        validation_run_id: str | None,
        target_type: str,
        target_id: str,
        target_hash: str,
    ) -> None:
        active_policy = await self.active_policy(db, novel_id)
        if active_policy is None:
            return
        if not validation_run_id:
            self._required_validation(None, "run_required")
        run = await self._get_model(db, novel_id, validation_run_id or "")
        if run.scope_json.get("purpose") == "assistant_advisory":
            self._required_validation(run, "advisory_only")
        await self._refresh_freshness(db, run)
        requires_full = await self._target_requires_full_scope(
            db, novel_id, target_type=target_type, target_id=target_id
        )
        if requires_full and run.scope != "full":
            self._required_validation(run, "full_scope_required")
        if run.scope == "full":
            source_key = (
                f"draft:{target_id}"
                if target_type == "world_bible_draft"
                else f"adoption:{target_id}"
            )
            if not any(
                item.get("source_key") == source_key
                for item in run.manifest_json.get("items") or []
            ):
                self._required_validation(run, "target_not_in_full_manifest")
        else:
            expected = {
                "target_type": target_type,
                "target_id": target_id,
                "target_hash": target_hash,
            }
            if any(run.scope_json.get(key) != value for key, value in expected.items()):
                self._required_validation(run, "target_changed")
        if run.status != "completed":
            self._required_validation(run, run.status)
        if run.gate == "block":
            # Author adjudication (ADR-0022): an author-required block can be
            # cleared by explicit per-finding dispositions bound to this run;
            # deterministic errors still block.
            if run.verdict != "author-required":
                self._required_validation(run, run.status)
            state = await self._review_state(db, run)
            if state["reviewed"] < state["required"]:
                self._required_validation(run, "review_pending")
        elif run.gate == "warn":
            receipt = dict(run.warning_receipt_json or {})
            if receipt.get("receipt_hash") == self._receipt_hash(run):
                return
            state = await self._review_state(db, run)
            warning_ids = {
                str(item.get("finding_id"))
                for item in run.findings_json
                if item.get("severity") == "warning"
            }
            if not warning_ids <= set(state["reviewed_finding_ids"]):
                self._required_validation(run, "warnings_not_accepted")

    async def _target_requires_full_scope(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        target_type: str,
        target_id: str,
    ) -> bool:
        if target_type == "world_adoption_package":
            return True
        if target_type != "world_bible_draft":
            return False
        draft = await db.scalar(
            select(WorldBiblePageDraft).where(
                WorldBiblePageDraft.id == parse_uuid(target_id, "target_id"),
                WorldBiblePageDraft.novel_id == parse_uuid(novel_id, "novel_id"),
            )
        )
        return draft is not None and self._is_full_scope_draft(draft)

    @staticmethod
    def _is_full_scope_draft(draft: WorldBiblePageDraft) -> bool:
        metadata = dict(draft.page_meta_json or {})
        return (
            draft.page_type in {"rule", "schema", "terminology", "world_core"}
            or isinstance(metadata.get("validation_policy"), dict)
            or bool(draft.linked_asset_refs_json)
        )

    async def require_legacy_canon_write_allowed(
        self, db: AsyncSession, novel_id: str, *, next_action: str
    ) -> None:
        if await self.active_policy(db, novel_id) is not None:
            raise ConflictError(
                "This canon change must use a validated World adoption package",
                code="required_validation",
                context={"next_action": next_action},
            )

    async def execute_run(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        run_id: str,
        attempt: int,
        task_id: str,
        lease_id: str,
        confirmed_context: ConfirmedAIActionContext | None = None,
    ) -> dict[str, Any]:
        await require_running_task_attempt(
            db,
            task_id=task_id,
            task_type="world_validation",
            novel_id=novel_id,
            lease_id=lease_id,
            attempt=attempt,
        )
        run = await self._get_model(db, novel_id, run_id, for_update=True)
        if str(run.task_id) != task_id:
            raise ConflictError("World validation task ownership changed")
        if run.status == "completed":
            return self.response(run).model_dump(mode="json")
        if run.status == "stale":
            return self.response(run).model_dump(mode="json")
        run.status = "running"
        run.attempt_count = max(run.attempt_count, attempt)
        run.started_at = run.started_at or datetime.now(UTC)
        run.error_code = None
        run.error_summary = None
        await db.commit()

        try:
            policy = await self._policy_for_run(db, run)
            checkpoint_raw = dict(
                (run.manifest_json.get("world_state_checkpoint") or {}).get("payload")
                or {}
            )
            checkpoint = (
                WorldDesignCheckpointPayload.model_validate(checkpoint_raw)
                if checkpoint_raw
                else None
            )
            findings = deterministic_findings(policy, run.manifest_json, checkpoint)
            findings.extend(
                WorldValidationFinding.model_validate(item)
                for item in run.findings_json
                if item.get("layer") == "semantic"
            )
            packet_hashes = [
                dict(item)
                for item in run.packet_hashes_json
                if item.get("input_hash") and item.get("result_hash")
            ]
            coverage = list(run.coverage_ledger_json or [])
            if policy.semantic_enabled and confirmed_context is None:
                raise ValidationError(
                    "Semantic World validation requires confirmed Context"
                )
            semantic_manifest = (
                self._confirmed_semantic_manifest(
                    run.manifest_json,
                    confirmed_context,
                )
                if policy.semantic_enabled and confirmed_context is not None
                else run.manifest_json
            )
            completed_before = {
                item["input_hash"]
                for item in run.packet_hashes_json
                if item.get("input_hash") and item.get("result_hash")
            }
            packets, budget = build_review_packets(
                run_id=run_id,
                scope=run.scope,
                policy=policy,
                manifest=semantic_manifest,
                completed_input_hashes=completed_before,
                allow_over_budget=True,
            )
            total_planned = int(budget.get("planned_packets") or 0)
            insufficient = policy.semantic_enabled and not packets
            if insufficient:
                coverage = [
                    {
                        "question_id": item.question_id,
                        "answered": False,
                        "skip_reason": "semantic_budget_exceeded",
                    }
                    for item in policy.required_questions
                ]
            elif (
                policy.semantic_enabled
                and not any(item.severity == "error" for item in findings)
                and packets
            ):
                (
                    semantic_findings,
                    semantic_coverage,
                    hashes,
                ) = await self._semantic_review(
                    db,
                    novel_id=novel_id,
                    run_id=run_id,
                    task_id=task_id,
                    lease_id=lease_id,
                    attempt=attempt,
                    policy=policy,
                    snapshot=run.model_snapshot_json,
                    packets=packets,
                )
                findings = [
                    *deterministic_findings(policy, run.manifest_json, checkpoint),
                    *semantic_findings,
                ]
                packet_hashes = hashes
                completed_hashes = {item["input_hash"] for item in hashes}
                answered = {
                    str(item.get("question_id"))
                    for item in semantic_coverage
                    if item.get("answered")
                }
                coverage = [
                    *semantic_coverage,
                    *(
                        {
                            "question_id": item.question_id,
                            "answered": False,
                            "skip_reason": "semantic_budget_exceeded",
                        }
                        for item in policy.required_questions
                        if item.question_id not in answered
                    ),
                ]
                insufficient = policy.semantic_enabled and (
                    len(completed_hashes) < total_planned
                )
                budget["used_packets"] = len(completed_hashes)
                budget["used_input_characters"] = sum(
                    len(packet["content"]["text"])
                    for packet in packets
                    if packet["input_hash"] in completed_hashes
                )
            elif policy.semantic_enabled and not insufficient:
                coverage = [
                    {
                        "question_id": item.question_id,
                        "answered": False,
                        "skip_reason": "deterministic_block",
                    }
                    for item in policy.required_questions
                ]

            verdict, gate = overall_result(findings, insufficient_evidence=insufficient)
            await require_running_task_attempt(
                db,
                task_id=task_id,
                task_type="world_validation",
                novel_id=novel_id,
                lease_id=lease_id,
                attempt=attempt,
            )
            run = await self._get_model(db, novel_id, run_id, for_update=True)
            stale_reason = await self._matches_frozen_inputs(db, run)
            if stale_reason:
                self._mark_stale(run, stale_reason)
            else:
                finding_payloads = [item.model_dump(mode="json") for item in findings]
                receipt_hash = stable_hash(
                    {
                        "manifest_hash": run.manifest_hash,
                        "policy_hash": run.policy_hash,
                        "dependency_hash": run.dependency_hash,
                        "packet_hashes": packet_hashes,
                        "verdict": verdict,
                        "gate": gate,
                    }
                )
                run.status = "completed"
                run.verdict = verdict
                run.gate = gate
                run.findings_json = finding_payloads
                run.omissions_json = ["semantic_budget_exceeded"] if insufficient else []
                run.coverage_ledger_json = coverage
                run.budget_ledger_json = budget
                run.packet_hashes_json = [
                    *packet_hashes,
                    {"receipt_hash": receipt_hash},
                ]
                run.finished_at = datetime.now(UTC)
            await db.commit()
            return self.response(run).model_dump(mode="json")
        except Exception as exc:
            await db.rollback()
            await require_running_task_attempt(
                db,
                task_id=task_id,
                task_type="world_validation",
                novel_id=novel_id,
                lease_id=lease_id,
                attempt=attempt,
            )
            failed = await self._get_model(db, novel_id, run_id, for_update=True)
            if failed.status == "stale":
                return self.response(failed).model_dump(mode="json")
            failed.status = "failed"
            failed.gate = "block"
            failed.error_code = type(exc).__name__[:64]
            failed.error_summary = redact_diagnostic(exc, limit=500)
            failed.finished_at = datetime.now(UTC)
            await db.commit()
            raise

    @staticmethod
    def _confirmed_semantic_manifest(
        manifest: dict[str, Any],
        confirmed_context: ConfirmedAIActionContext,
    ) -> dict[str, Any]:
        selected = confirmed_context.confirmation.selected_asset_ids
        aliases = {
            "entity": "world_entities",
            "core_entity": "world_entities",
            "character": "characters",
        }
        items = [
            dict(item)
            for item in manifest.get("items") or []
            if str(item.get("target_id") or "")
            in set(
                selected.get(
                    aliases.get(
                        str(item.get("target_type") or ""),
                        str(item.get("target_type") or ""),
                    ),
                    [],
                )
            )
        ]
        if not items:
            raise ValidationError(
                "Confirmed Context contains no World sources for semantic validation"
            )
        return {**manifest, "items": items, "world_state_checkpoint": None}

    async def _semantic_review(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        run_id: str,
        task_id: str,
        lease_id: str,
        attempt: int,
        policy: WorldValidationPolicy,
        snapshot: dict[str, Any],
        packets: list[dict[str, Any]],
    ) -> tuple[list[WorldValidationFinding], list[dict[str, Any]], list[dict[str, str]]]:
        settings = await restore_project_llm_execution_settings(db, novel_id, snapshot)
        model = str(settings.get("llm", {}).get("model") or "")
        if not model:
            raise ValidationError("World validation requires a frozen project LLM model")
        client = create_project_snapshot_llm_client(
            settings,
            timeout_override=policy.per_packet_timeout_seconds,
            novel_id=novel_id,
        )
        run = await self._get_model(db, novel_id, run_id)
        advisory = run.scope_json.get("purpose") == "assistant_advisory"
        findings = [
            WorldValidationFinding.model_validate(item)
            for item in run.findings_json
            if item.get("layer") == "semantic"
        ]
        coverage = list(run.coverage_ledger_json or [])
        hashes = [
            dict(item)
            for item in run.packet_hashes_json
            if item.get("input_hash") and item.get("result_hash")
        ]
        completed = {item["input_hash"] for item in hashes}
        await db.commit()
        try:
            for packet in packets:
                if packet["input_hash"] in completed:
                    continue
                if advisory:
                    current = await self._get_model(db, novel_id, run_id)
                    reason = await self._matches_frozen_inputs(db, current)
                    if reason:
                        self._mark_stale(current, reason)
                        await db.commit()
                        raise ConflictError("诊断资料或世界政策已变化")
                    await db.commit()
                request = LLMCallRequest(
                    model=model,
                    temperature=0,
                    max_tokens=policy.max_output_tokens_per_packet,
                    messages=[
                        LLMMessage(
                            role="system",
                            content=(
                                "你是只读的小说世界书校验器。逐一回答 questions；"
                                "不得新增正典、不得猜测缺失事实。"
                                "引用必须逐字来自本分片。每个 question_id "
                                "恰好输出一次；无证据时用 mixed/KEEP-GATE。"
                            ),
                        ),
                        LLMMessage(
                            role="user",
                            content=json.dumps(packet, ensure_ascii=False, default=str),
                        ),
                    ],
                )
                output = await run_managed_structured(
                    client,
                    request,
                    WorldValidationSemanticOutput,
                    step_name=(
                        f"world.validation.packet_{int(packet['shard_index']) + 1}"
                    ),
                    timeout=policy.per_packet_timeout_seconds,
                )
                packet_findings, packet_coverage = validate_semantic_output(
                    packet, output
                )
                result_hash = stable_hash(
                    [packet["input_hash"], output.model_dump(mode="json")]
                )
                await require_running_task_attempt(
                    db,
                    task_id=task_id,
                    task_type="world_validation",
                    novel_id=novel_id,
                    lease_id=lease_id,
                    attempt=attempt,
                )
                current = await self._get_model(db, novel_id, run_id, for_update=True)
                if str(current.task_id) != task_id:
                    raise ConflictError("World validation task ownership changed")
                findings.extend(packet_findings)
                coverage.extend(packet_coverage)
                hashes.append(
                    {"input_hash": str(packet["input_hash"]), "result_hash": result_hash}
                )
                completed.add(str(packet["input_hash"]))
                current.findings_json = [
                    item.model_dump(mode="json") for item in findings
                ]
                current.coverage_ledger_json = coverage
                current.packet_hashes_json = hashes
                current.budget_ledger_json = {
                    "used_packets": len(completed),
                    "used_input_characters": sum(
                        len(item["content"]["text"])
                        for item in packets
                        if item["input_hash"] in completed
                    ),
                }
                await db.commit()
        finally:
            await client.close()
        return findings, coverage, hashes

    async def _policy_for_run(
        self, db: AsyncSession, run: WorldValidationRun
    ) -> WorldValidationPolicy:
        if run.scope_json.get("purpose") == "assistant_advisory":
            policy = WorldValidationPolicy.model_validate(
                run.plan_json.get("advisory_policy")
            )
            if (
                await self._active_policy_candidates(
                    db, str(run.novel_id), include_disabled=True
                )
                or stable_hash(policy.model_dump(mode="json")) != run.policy_hash
            ):
                self._mark_stale(run)
                await db.commit()
                raise ConflictError("World diagnostic policy was superseded")
            return policy
        if run.policy_version == "builtin-v1":
            return self.builtin_policy()
        active = await self.active_policy(db, str(run.novel_id))
        if active is None or active[1] != run.policy_hash:
            self._mark_stale(run)
            await db.commit()
            raise ConflictError("World validation policy changed")
        return active[0]

    async def _freeze_manifest(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        scope: str,
        target_type: str | None,
        target_id: str | None,
        root_type: str | None = None,
    ) -> tuple[dict[str, Any], str, str | None]:
        nid = parse_uuid(novel_id, "novel_id")
        target_hash: str | None = None
        if scope == "full":
            pages = (
                (
                    await db.execute(
                        select(WorldBiblePage)
                        .where(
                            WorldBiblePage.novel_id == nid,
                            WorldBiblePage.status.in_(_ADOPTED_STATUSES),
                        )
                        .order_by(WorldBiblePage.page_key, WorldBiblePage.id)
                    )
                )
                .scalars()
                .all()
            )
            items = [self._page_manifest_item(page) for page in pages]
            critical_drafts = list(
                (
                    await db.execute(
                        select(WorldBiblePageDraft)
                        .where(WorldBiblePageDraft.novel_id == nid)
                        .order_by(WorldBiblePageDraft.id)
                    )
                )
                .scalars()
                .all()
            )
            items.extend(
                self._draft_manifest_item(draft)
                for draft in critical_drafts
                if self._is_full_scope_draft(draft)
            )
            pending_packages = list(
                (
                    await db.execute(
                        select(CreationSuggestion)
                        .where(
                            CreationSuggestion.novel_id == nid,
                            CreationSuggestion.target_type == "world_adoption_package",
                            CreationSuggestion.status == "pending",
                        )
                        .order_by(CreationSuggestion.id)
                    )
                )
                .scalars()
                .all()
            )
            items.extend(
                self._adoption_manifest_item(package) for package in pending_packages
            )
        elif target_type == "world_bible_draft" and target_id:
            draft = await db.scalar(
                select(WorldBiblePageDraft).where(
                    WorldBiblePageDraft.id == parse_uuid(target_id, "target_id"),
                    WorldBiblePageDraft.novel_id == nid,
                )
            )
            if draft is None:
                raise NotFoundError("World Bible draft not found")
            impact = await self._lifecycle.preview_publish_impact(db, novel_id, target_id)
            target_hash = impact.impact_scope_hash
            items = [self._draft_manifest_item(draft)]
        elif target_type == "semantic_gap" and target_id:
            items, target_hash = await self._semantic_gap_items(
                db, nid, root_type=root_type, root_id=target_id
            )
        elif target_type == "world_adoption_package" and target_id:
            preview = await self._adoption.preview(db, novel_id, target_id)
            target_hash = preview.expected_preview_hash
            suggestion = await db.scalar(
                select(CreationSuggestion).where(
                    CreationSuggestion.id == parse_uuid(target_id, "target_id"),
                    CreationSuggestion.novel_id == nid,
                )
            )
            if suggestion is None:
                raise NotFoundError("World adoption package not found")
            items = [self._adoption_manifest_item(suggestion)]
        else:
            raise ValidationError("Unsupported World validation target")
        lookup_pages = list(
            (
                await db.execute(
                    select(WorldBiblePage)
                    .where(WorldBiblePage.novel_id == nid)
                    .order_by(WorldBiblePage.page_key, WorldBiblePage.id)
                )
            )
            .scalars()
            .all()
        )
        lookup_drafts = list(
            (
                await db.execute(
                    select(WorldBiblePageDraft)
                    .where(WorldBiblePageDraft.novel_id == nid)
                    .order_by(WorldBiblePageDraft.id)
                )
            )
            .scalars()
            .all()
        )
        lookup = [
            self._lookup_manifest_item(page, target_type="world_bible_page")
            for page in lookup_pages
        ]
        lookup.extend(
            self._lookup_manifest_item(draft, target_type="world_bible_draft")
            for draft in lookup_drafts
        )
        checkpoint_suggestion = await db.scalar(
            select(CreationSuggestion)
            .where(
                CreationSuggestion.novel_id == nid,
                CreationSuggestion.target_type == "world_design_checkpoint",
            )
            .order_by(CreationSuggestion.created_at.desc(), CreationSuggestion.id.desc())
            .limit(1)
        )
        world_state_checkpoint: dict[str, Any] | None = None
        if checkpoint_suggestion is not None:
            checkpoint_payload = WorldDesignCheckpointPayload.model_validate(
                checkpoint_suggestion.payload_json
            ).model_dump(mode="json", by_alias=True)
            world_state_checkpoint = {
                "suggestion_id": str(checkpoint_suggestion.id),
                "content_hash": stable_hash(checkpoint_payload),
                "payload": checkpoint_payload,
            }
        manifest = {
            "scope": scope,
            "items": items,
            "lookup": lookup,
            "world_state_checkpoint": world_state_checkpoint,
        }
        dependencies = sorted(
            (
                {
                    "source_key": item["source_key"],
                    "relation": str(ref.get("relation") or "informs"),
                    "target_type": str(ref.get("target_type") or ref.get("type") or ""),
                    "target_id": str(ref.get("target_id") or ref.get("id") or ""),
                    "target_path": str(ref.get("target_path") or ""),
                    "target_hash": str(ref.get("target_hash") or ""),
                }
                for item in items
                for ref in item.get("linked_asset_refs") or []
                if isinstance(ref, dict)
            ),
            key=lambda item: (
                item["source_key"],
                item["relation"],
                item["target_type"],
                item["target_id"],
                item["target_path"],
                item["target_hash"],
            ),
        )
        return manifest, stable_hash(dependencies), target_hash

    @staticmethod
    def _page_manifest_item(page: WorldBiblePage) -> dict[str, Any]:
        body = WorldValidationService._content(page.free_text, page.sections_json, {})
        content = WorldValidationService._content(
            page.free_text, page.sections_json, page.page_meta_json
        )
        return {
            "source_key": f"page:{page.id}",
            "identity_key": f"page:{page.id}",
            "target_type": "world_bible_page",
            "target_id": str(page.id),
            "title": page.title,
            "page_type": page.page_type,
            "status": page.status,
            "version": page.version_number,
            "content_hash": stable_hash(content),
            "content": content,
            "body": body,
            "metadata": dict(page.page_meta_json or {}),
            "anchors": WorldValidationService._markdown_anchors(
                page.free_text or "", page.sections_json or []
            ),
            "linked_asset_refs": list(page.linked_asset_refs_json or []),
        }

    @staticmethod
    def _draft_manifest_item(draft: WorldBiblePageDraft) -> dict[str, Any]:
        body = WorldValidationService._content(draft.free_text, draft.sections_json, {})
        content = WorldValidationService._content(
            draft.free_text, draft.sections_json, draft.page_meta_json
        )
        return {
            "source_key": f"draft:{draft.id}",
            "identity_key": (
                f"page:{draft.page_id}" if draft.page_id else f"draft:{draft.id}"
            ),
            "target_type": "world_bible_draft",
            "target_id": str(draft.id),
            "title": draft.title,
            "page_type": draft.page_type,
            "status": "draft",
            "version": draft.base_version_number or 0,
            "content_hash": stable_hash(content),
            "content": content,
            "body": body,
            "metadata": dict(draft.page_meta_json or {}),
            "anchors": WorldValidationService._markdown_anchors(
                draft.free_text or "", draft.sections_json or []
            ),
            "linked_asset_refs": list(draft.linked_asset_refs_json or []),
        }

    @staticmethod
    def _adoption_manifest_item(suggestion: CreationSuggestion) -> dict[str, Any]:
        payload = dict(suggestion.payload_json or {})
        return {
            "source_key": f"adoption:{suggestion.id}",
            "identity_key": f"adoption:{suggestion.id}",
            "target_type": "world_adoption_package",
            "target_id": str(suggestion.id),
            "title": "世界设定采用包",
            "page_type": "adoption_package",
            "status": suggestion.status,
            "version": 1,
            "content_hash": stable_hash(payload),
            "content": json.dumps(payload, ensure_ascii=False, sort_keys=True),
            "body": "",
            "metadata": {},
            "anchors": [],
            "linked_asset_refs": [],
        }

    @staticmethod
    def _lookup_manifest_item(
        item: WorldBiblePage | WorldBiblePageDraft,
        *,
        target_type: str,
    ) -> dict[str, Any]:
        metadata = dict(item.page_meta_json or {})
        imported = dict((metadata.get("worldbook_import") or {}).get("frontmatter") or {})
        aliases = imported.get("aliases", metadata.get("aliases", []))
        if not isinstance(aliases, list):
            aliases = []
        source_path = str(
            (metadata.get("worldbook_import") or {}).get("source_path") or ""
        )
        return {
            "source_key": (
                f"draft:{item.id}"
                if isinstance(item, WorldBiblePageDraft)
                else f"page:{item.id}"
            ),
            "identity_key": (
                f"page:{item.page_id}"
                if isinstance(item, WorldBiblePageDraft) and item.page_id
                else (
                    f"draft:{item.id}"
                    if isinstance(item, WorldBiblePageDraft)
                    else f"page:{item.id}"
                )
            ),
            "target_type": target_type,
            "target_id": str(item.id),
            "title": item.title,
            "aliases": [str(value) for value in aliases if str(value).strip()][:100],
            "source_path": source_path,
            "anchors": WorldValidationService._markdown_anchors(
                item.free_text or "", item.sections_json or []
            ),
        }

    @staticmethod
    def _markdown_anchors(body: str, sections: list[Any]) -> list[str]:
        anchors = [
            match.group(1).strip()
            for line in body.splitlines()
            if (match := re.match(r"^#{1,6}\s+(.+?)\s*$", line))
        ]
        anchors.extend(
            str(section.get("title") or "").strip()
            for section in sections
            if isinstance(section, dict) and str(section.get("title") or "").strip()
        )
        return sorted(set(anchors), key=str.casefold)[:256]

    @staticmethod
    def _content(free_text: str | None, sections: list, meta: dict) -> str:
        return "\n\n".join(
            part
            for part in (
                free_text or "",
                json.dumps(sections or [], ensure_ascii=False, sort_keys=True),
                json.dumps(meta or {}, ensure_ascii=False, sort_keys=True),
            )
            if part and part not in {"[]", "{}"}
        )

    async def _matches_frozen_inputs(
        self, db: AsyncSession, run: WorldValidationRun
    ) -> str | None:
        """Return the stale reason, or None when every frozen input matches."""
        active = await self.active_policy(db, str(run.novel_id))
        if run.scope_json.get("purpose") == "assistant_advisory":
            if await self._active_policy_candidates(
                db, str(run.novel_id), include_disabled=True
            ):
                return "policy"
            frozen_policy = run.plan_json.get("advisory_policy") or {}
            if stable_hash(frozen_policy) != run.policy_hash:
                return "policy"
        current_policy_hash = (
            active[1]
            if active is not None
            else stable_hash(self.builtin_policy().model_dump(mode="json"))
        )
        manifest, dependency_hash, target_hash = await self._freeze_manifest(
            db,
            novel_id=str(run.novel_id),
            scope=run.scope,
            target_type=run.scope_json.get("target_type"),
            target_id=run.scope_json.get("target_id"),
            root_type=run.scope_json.get("root_type"),
        )
        if (
            run.scope_json.get("purpose") != "assistant_advisory"
            and current_policy_hash != run.policy_hash
        ):
            return "policy"
        if stable_hash(manifest) != run.manifest_hash:
            return "manifest"
        if dependency_hash != run.dependency_hash:
            return "dependency"
        if target_hash != run.scope_json.get("target_hash"):
            return "target"
        return None

    async def _refresh_freshness(self, db: AsyncSession, run: WorldValidationRun) -> None:
        if run.status not in {"completed", "stale"}:
            return
        try:
            reason = await self._matches_frozen_inputs(db, run)
        except (ConflictError, NotFoundError, ValidationError):
            reason = "manifest"
        if reason and run.status != "stale":
            self._mark_stale(run, reason)
            await db.flush()

    @staticmethod
    def _mark_stale(run: WorldValidationRun, reason: str = "manifest") -> None:
        run.status = "stale"
        run.verdict = "insufficient-evidence"
        run.gate = "block"
        run.stale_reason = reason
        run.warning_receipt_json = {}
        run.finished_at = datetime.now(UTC)

    async def _get_model(
        self,
        db: AsyncSession,
        novel_id: str,
        run_id: str,
        *,
        for_update: bool = False,
    ) -> WorldValidationRun:
        statement = select(WorldValidationRun).where(
            WorldValidationRun.id == parse_uuid(run_id, "run_id"),
            WorldValidationRun.novel_id == parse_uuid(novel_id, "novel_id"),
        )
        if for_update:
            statement = statement.with_for_update()
        run = await db.scalar(statement)
        if run is None:
            raise NotFoundError("World validation run not found")
        return run

    @staticmethod
    def _receipt_hash(run: WorldValidationRun) -> str | None:
        for item in reversed(run.packet_hashes_json or []):
            if isinstance(item, dict) and item.get("receipt_hash"):
                return str(item["receipt_hash"])
        return None

    @staticmethod
    def response(
        run: WorldValidationRun,
        *,
        review_items: list[WorldValidationReviewItem] | None = None,
    ) -> WorldValidationRunResponse:
        scope = dict(run.scope_json or {})
        findings = run.findings_json or []
        packets_done = sum(
            1
            for item in run.packet_hashes_json or []
            if item.get("input_hash") and item.get("result_hash")
        )
        plan = dict(run.plan_json or {})
        reviewable = WorldValidationService._reviewable_finding_ids(findings)
        items = review_items or []
        reviewed = [item for item in items if item.finding_id in reviewable]
        return WorldValidationRunResponse(
            id=str(run.id),
            novel_id=str(run.novel_id),
            task_id=str(run.task_id) if run.task_id else None,
            trigger=run.trigger,
            scope=run.scope,
            target_type=scope.get("target_type"),
            target_id=scope.get("target_id"),
            status=run.status,
            verdict=run.verdict,
            gate=run.gate,
            policy_version=run.policy_version,
            manifest_hash=run.manifest_hash,
            dependency_hash=run.dependency_hash,
            receipt_hash=WorldValidationService._receipt_hash(run),
            findings=findings,
            omissions=run.omissions_json or [],
            coverage_ledger=run.coverage_ledger_json or [],
            budget_ledger=run.budget_ledger_json or {},
            warning_receipt=run.warning_receipt_json or {},
            attempt_count=run.attempt_count,
            impact=dict(run.impact_json or {}),
            plan=plan,
            stale_reason=run.stale_reason,
            continued_count=run.continued_count,
            review={
                "required": len(reviewable),
                "reviewed": len(reviewed),
                "pending_finding_ids": sorted(
                    reviewable - {i.finding_id for i in reviewed}
                ),
                "items": [
                    {
                        "finding_id": item.finding_id,
                        "disposition": item.disposition,
                        "note": item.note,
                        "reviewed_at": item.reviewed_at.isoformat()
                        if item.reviewed_at
                        else None,
                    }
                    for item in sorted(items, key=lambda i: i.finding_id)
                ],
            },
            progress={
                "packets_planned": plan.get("planned_packets"),
                "packets_completed": packets_done,
                "findings_total": len(findings),
                "findings_errors": sum(
                    1 for item in findings if item.get("severity") == "error"
                ),
                "findings_warnings": sum(
                    1 for item in findings if item.get("severity") == "warning"
                ),
                "omissions": list(run.omissions_json or []),
            },
            error_code=run.error_code,
            error_summary=run.error_summary,
            started_at=run.started_at,
            finished_at=run.finished_at,
            created_at=run.created_at,
            updated_at=run.updated_at,
        )

    @staticmethod
    def _reviewable_finding_ids(findings: list) -> set[str]:
        return {
            str(item.get("finding_id"))
            for item in findings
            if isinstance(item, dict)
            and (
                item.get("action") == "AUTHOR-REQUIRED"
                or item.get("severity") == "warning"
            )
        }

    async def _review_state(
        self, db: AsyncSession, run: WorldValidationRun
    ) -> dict[str, Any]:
        rows = list(
            (
                await db.execute(
                    select(WorldValidationReviewItem).where(
                        WorldValidationReviewItem.novel_id == run.novel_id,
                        WorldValidationReviewItem.run_id == run.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        reviewable = self._reviewable_finding_ids(run.findings_json or [])
        reviewed = [item for item in rows if item.finding_id in reviewable]
        return {
            "required": len(reviewable),
            "reviewed": len(reviewed),
            "reviewed_finding_ids": {item.finding_id for item in rows},
        }

    async def _enriched_responses(
        self, db: AsyncSession, runs: list[WorldValidationRun]
    ) -> list[WorldValidationRunResponse]:
        if not runs:
            return []
        rows = list(
            (
                await db.execute(
                    select(WorldValidationReviewItem).where(
                        WorldValidationReviewItem.novel_id == runs[0].novel_id,
                        WorldValidationReviewItem.run_id.in_([run.id for run in runs]),
                    )
                )
            )
            .scalars()
            .all()
        )
        by_run: dict[str, list[WorldValidationReviewItem]] = {}
        for row in rows:
            by_run.setdefault(str(row.run_id), []).append(row)
        return [
            self.response(run, review_items=by_run.get(str(run.id), [])) for run in runs
        ]

    async def _enriched_response(
        self, db: AsyncSession, runs: list[WorldValidationRun]
    ) -> WorldValidationRunResponse:
        return (await self._enriched_responses(db, runs))[0]

    # ------------------------------------------------------------------
    # Per-finding review records (ADR-0022)
    # ------------------------------------------------------------------

    async def list_review_items(
        self,
        db: AsyncSession,
        novel_id: str,
        run_id: str,
    ) -> WorldValidationReviewListResponse:
        run = await self._get_model(db, novel_id, run_id)
        rows = list(
            (
                await db.execute(
                    select(WorldValidationReviewItem)
                    .where(
                        WorldValidationReviewItem.novel_id == run.novel_id,
                        WorldValidationReviewItem.run_id == run.id,
                    )
                    .order_by(WorldValidationReviewItem.reviewed_at)
                )
            )
            .scalars()
            .all()
        )
        return WorldValidationReviewListResponse(
            items=[
                WorldValidationReviewItemRecord(
                    finding_id=row.finding_id,
                    disposition=row.disposition,
                    note=row.note,
                    finding_snapshot=dict(row.finding_snapshot or {}),
                    reviewed_at=row.reviewed_at,
                )
                for row in rows
            ],
            total=len(rows),
        )

    async def review_items(
        self,
        db: AsyncSession,
        novel_id: str,
        run_id: str,
        data,
    ) -> WorldValidationRunResponse:
        run = await self._get_model(db, novel_id, run_id, for_update=True)
        await self._refresh_freshness(db, run)
        if run.status != "completed":
            raise ConflictError(
                "Only a completed validation run can be reviewed",
                code="validation_run_not_reviewable",
            )
        findings = {
            str(item.get("finding_id")): item
            for item in run.findings_json or []
            if isinstance(item, dict)
        }
        reviewable = self._reviewable_finding_ids(run.findings_json or [])
        unknown = [
            item.finding_id for item in data.items if item.finding_id not in findings
        ]
        if unknown:
            raise ValidationError("Unknown finding ids cannot be reviewed")
        not_reviewable = [
            item.finding_id for item in data.items if item.finding_id not in reviewable
        ]
        if not_reviewable:
            raise ValidationError(
                "Only author-required or warning findings can be reviewed"
            )
        context = await get_project_context(db, novel_id)
        if context is None or not context.owner_id:
            raise ConflictError("Active project owner is unavailable")
        rows = {
            row.finding_id: row
            for row in (
                await db.execute(
                    select(WorldValidationReviewItem).where(
                        WorldValidationReviewItem.novel_id == run.novel_id,
                        WorldValidationReviewItem.run_id == run.id,
                    )
                )
            )
            .scalars()
            .all()
        }
        now = datetime.now(UTC)
        seen: set[str] = set()
        for item in data.items:
            if item.finding_id in seen:
                raise ValidationError("Each finding can be reviewed at most once")
            seen.add(item.finding_id)
            finding = findings[item.finding_id]
            row = rows.get(item.finding_id)
            if row is None:
                row = WorldValidationReviewItem(
                    novel_id=run.novel_id,
                    run_id=run.id,
                    finding_id=item.finding_id,
                )
                db.add(row)
                rows[item.finding_id] = row
            row.disposition = item.disposition
            row.note = item.note or ""
            row.finding_snapshot = {
                "action": finding.get("action"),
                "severity": finding.get("severity"),
                "category": finding.get("category"),
                "message": finding.get("message"),
                "source_key": finding.get("source_key"),
                "target_hash": run.scope_json.get("target_hash"),
                "manifest_hash": run.manifest_hash,
                "reviewed_by": context.owner_id,
            }
            row.reviewed_at = now
        await db.flush()
        return await self._enriched_response(db, [run])

    async def findings_page(
        self,
        db: AsyncSession,
        novel_id: str,
        run_id: str,
        *,
        severity: str | None = None,
        action: str | None = None,
        category: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> WorldValidationFindingsPage:
        run = await self._get_model(db, novel_id, run_id)
        await self._refresh_freshness(db, run)
        findings = [item for item in run.findings_json or [] if isinstance(item, dict)]
        if severity:
            findings = [item for item in findings if item.get("severity") == severity]
        if action:
            findings = [item for item in findings if item.get("action") == action]
        if category:
            findings = [item for item in findings if item.get("category") == category]
        findings.sort(
            key=lambda item: (
                0 if item.get("severity") == "error" else 1,
                str(item.get("category") or ""),
                str(item.get("finding_id") or ""),
            )
        )
        total = len(findings)
        start = max(0, (page - 1) * page_size)
        slice_ = findings[start : start + page_size]
        rows = list(
            (
                await db.execute(
                    select(WorldValidationReviewItem).where(
                        WorldValidationReviewItem.novel_id == run.novel_id,
                        WorldValidationReviewItem.run_id == run.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        dispositions = {row.finding_id: row.disposition for row in rows}
        return WorldValidationFindingsPage(
            items=[WorldValidationFinding.model_validate(item) for item in slice_],
            total=total,
            page=page,
            page_size=page_size,
            dispositions=dispositions,
        )

    # ------------------------------------------------------------------
    # Batch continuation (ADR-0022: 分批续接 on the same run row)
    # ------------------------------------------------------------------

    async def continue_run(
        self,
        db: AsyncSession,
        novel_id: str,
        run_id: str,
        *,
        context_confirmation_id: str | None = None,
    ) -> WorldValidationRunResponse:
        run = await self._get_model(db, novel_id, run_id, for_update=True)
        await self._refresh_freshness(db, run)
        resumable = run.status == "failed" or (
            run.status == "completed" and "semantic_budget_exceeded" in run.omissions_json
        )
        if not resumable:
            raise ConflictError(
                "Only a failed or budget-interrupted validation can be continued",
                code="validation_run_not_continuable",
            )
        if run.scope == "full":
            active = await db.scalar(
                select(WorldValidationRun.id).where(
                    WorldValidationRun.novel_id == run.novel_id,
                    WorldValidationRun.scope == "full",
                    WorldValidationRun.status.in_(("queued", "running")),
                    WorldValidationRun.id != run.id,
                )
            )
            if active is not None:
                raise ConflictError(
                    "A full World Bible validation is already running",
                    code="world_validation_full_in_progress",
                    context={"run_id": str(active)},
                )
        run.status = "queued"
        run.verdict = None
        run.gate = None
        run.error_code = None
        run.error_summary = None
        run.omissions_json = []
        run.finished_at = None
        run.continued_count = (run.continued_count or 0) + 1
        await db.flush()
        receipt = await enqueue_task_with_optional_operation(
            db,
            operation_id=None,
            task_type="world_validation",
            novel_id=novel_id,
            request_payload={
                "novel_id": novel_id,
                "run_id": run_id,
                "continued": True,
            },
            meta={
                "novel_id": novel_id,
                "run_id": run_id,
                "context_confirmation_id": context_confirmation_id,
            },
        )
        run.task_id = uuid.UUID(receipt.task_id)
        await db.flush()
        return await self._enriched_response(db, [run])

    # ------------------------------------------------------------------
    # Semantic gap scope (ADR-0022: root object + one declared hop)
    # ------------------------------------------------------------------

    async def _semantic_gap_items(
        self,
        db: AsyncSession,
        nid,
        *,
        root_type: str | None,
        root_id: str,
    ) -> tuple[list[dict[str, Any]], str]:
        if root_type not in {"world_bible_page", "core_entity", "world_bible_page_draft"}:
            raise ValidationError("semantic_gap validation requires a valid root_type")
        items: list[dict[str, Any]] = []
        if root_type == "core_entity":
            entity = await db.scalar(
                select(CoreEntity).where(
                    CoreEntity.id == parse_uuid(root_id, "root_id"),
                    CoreEntity.novel_id == nid,
                    CoreEntity.status == "canonical",
                )
            )
            if entity is None:
                raise NotFoundError("Semantic gap root entity not found")
            items.append(self._entity_manifest_item(entity))
            pages = list(
                (
                    await db.execute(
                        select(WorldBiblePage)
                        .where(
                            WorldBiblePage.novel_id == nid,
                            WorldBiblePage.status.in_(_ADOPTED_STATUSES),
                        )
                        .order_by(WorldBiblePage.page_key, WorldBiblePage.id)
                    )
                )
                .scalars()
                .all()
            )
            for page in pages:
                if self._declares_dependency_on_entity(page, str(entity.id)):
                    items.append(self._page_manifest_item(page))
        else:
            model = (
                WorldBiblePage if root_type == "world_bible_page" else WorldBiblePageDraft
            )
            statement = select(model).where(
                model.id == parse_uuid(root_id, "root_id"),
                model.novel_id == nid,
            )
            if root_type == "world_bible_page":
                statement = statement.where(WorldBiblePage.status.in_(_ADOPTED_STATUSES))
            root = await db.scalar(statement)
            if root is None:
                raise NotFoundError("Semantic gap root page not found")
            root_item = (
                self._page_manifest_item(root)
                if root_type == "world_bible_page"
                else self._draft_manifest_item(root)
            )
            items.append(root_item)
            for ref in root.linked_asset_refs_json or []:
                if not isinstance(ref, dict):
                    continue
                if str(ref.get("relation") or "informs") not in {"requires", "derives"}:
                    continue
                ref_type = str(ref.get("target_type") or ref.get("type") or "")
                ref_id = str(ref.get("target_id") or ref.get("id") or "")
                if ref_type in {"world_bible_page", "page"}:
                    page = await db.scalar(
                        select(WorldBiblePage).where(
                            WorldBiblePage.id == parse_uuid(ref_id, "ref_id"),
                            WorldBiblePage.novel_id == nid,
                            WorldBiblePage.status.in_(_ADOPTED_STATUSES),
                        )
                    )
                    if page is not None:
                        items.append(self._page_manifest_item(page))
                elif ref_type in {"core_entity", "entity"}:
                    entity = await db.scalar(
                        select(CoreEntity).where(
                            CoreEntity.id == parse_uuid(ref_id, "ref_id"),
                            CoreEntity.novel_id == nid,
                            CoreEntity.status == "canonical",
                        )
                    )
                    if entity is not None:
                        items.append(self._entity_manifest_item(entity))
        deduped = {item["source_key"]: item for item in items}
        items = list(deduped.values())
        target_hash = stable_hash(
            {
                "items": sorted(
                    (item["source_key"], item["content_hash"]) for item in items
                )
            }
        )
        return items, target_hash

    @staticmethod
    def _declares_dependency_on_entity(page: WorldBiblePage, entity_id: str) -> bool:
        for ref in page.linked_asset_refs_json or []:
            if not isinstance(ref, dict):
                continue
            ref_id = str(ref.get("target_id") or ref.get("id") or "")
            ref_type = str(ref.get("target_type") or ref.get("type") or "")
            if (
                ref_id == entity_id
                and ref_type in {"core_entity", "entity"}
                and str(ref.get("relation") or "informs") in {"requires", "derives"}
            ):
                return True
        return False

    @staticmethod
    def _entity_manifest_item(entity) -> dict[str, Any]:
        parts = [
            str(part)
            for part in (entity.name, entity.summary, entity.public_info)
            if part
        ]
        content_json = dict(getattr(entity, "content_json", None) or {})
        if content_json:
            parts.append(json.dumps(content_json, ensure_ascii=False, sort_keys=True))
        content = "\n\n".join(parts)
        return {
            "source_key": f"entity:{entity.id}",
            "identity_key": f"entity:{entity.id}",
            "target_type": "core_entity",
            "target_id": str(entity.id),
            "title": entity.name,
            "page_type": f"entity:{entity.entity_type}",
            "status": entity.status,
            "version": 1,
            "content_hash": stable_hash(content),
            "content": content,
            "body": content,
            "metadata": {},
            "anchors": [],
            "linked_asset_refs": [],
        }

    @staticmethod
    def _required_validation(run: WorldValidationRun | None, reason: str) -> None:
        raise ConflictError(
            "A fresh World Bible validation receipt is required",
            code="required_validation",
            context={
                "run_id": str(run.id) if run else None,
                "status": run.status if run else None,
                "reason": reason,
                "next_action": "run_world_validation",
            },
        )


__all__ = ["WorldValidationService"]
