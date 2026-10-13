"""journey overview operations for InteractionService."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, ValidationError
from infrastructure.tasks.facade import (
    get_latest_coalesced_task,
)
from modules.account.facade import is_anonymous_rp_principal
from modules.interaction.models import (
    InteractionJourney,
    InteractionMessageNode,
    InteractionOverviewRevision,
)
from modules.interaction.prompts import render_overview_sections
from modules.interaction.schemas import (
    InteractionOverviewResponse,
    InteractionOverviewSections,
)
from modules.interaction.service_support import (
    MAX_ACTIVE_STORY_ATTEMPTS as MAX_ACTIVE_STORY_ATTEMPTS,
)
from modules.interaction.service_support import (
    RECENT_MESSAGE_LIMIT as RECENT_MESSAGE_LIMIT,
)
from modules.interaction.service_support import (
    SEE_SEA_HEARTBEAT_TTL_SECONDS as SEE_SEA_HEARTBEAT_TTL_SECONDS,
)
from modules.interaction.service_support import (
    SEE_SEA_MANUAL_CLAIM_SECONDS as SEE_SEA_MANUAL_CLAIM_SECONDS,
)
from modules.interaction.service_support import (
    SUMMARY_TRIGGER_TOKENS as SUMMARY_TRIGGER_TOKENS,
)
from modules.interaction.service_support import (
    _enqueue_overview_refresh_task as _enqueue_overview_refresh_task,
)
from modules.interaction.service_support import (
    _fallback_title as _fallback_title,
)
from modules.interaction.service_support import (
    _parse_uuid as _parse_uuid,
)
from modules.interaction.service_support import (
    _summary_compressible_prefix_end as _summary_compressible_prefix_end,
)
from modules.interaction.service_support import (
    estimate_story_tokens as estimate_story_tokens,
)
from modules.interaction.service_support import (
    path_hash as path_hash,
)
from modules.project.contracts import ProjectLLMConfigurationError
from modules.project.facade import (
    build_project_llm_execution_snapshot,
)


class JourneyOverviewMixin:
    async def get_overview(
        self,
        db: AsyncSession,
        *,
        journey_id: str,
    ) -> InteractionOverviewResponse:
        journey = await self._owned_journey(db, journey_id)
        head = await self._repo.get_overview_head(db, journey=journey)
        path = await self._repo.get_selected_path(db, journey=journey)
        if head is not None:
            ids = [node.id for node in path]
            if head.anchor_node_id not in ids:
                head = None
            else:
                anchor_index = ids.index(head.anchor_node_id)
                if path_hash(path[: anchor_index + 1]) != head.path_hash:
                    head = None
        latest_task = await get_latest_coalesced_task(
            db,
            task_type="interaction_summary_refresh",
            novel_id=str(journey.novel_id),
            scope=("interaction_summary", str(journey.id)),
        )
        refreshing = latest_task is not None and latest_task.status in {
            "pending",
            "running",
        }
        failed = self._overview_failure_applies(journey, path)
        status = (
            "refreshing"
            if refreshing
            else ("failed" if failed else ("ready" if head is not None else "forming"))
        )
        return InteractionOverviewResponse(
            sections=InteractionOverviewSections.model_validate(
                head.sections if head else {}
            ),
            source=head.source if head else "automatic",
            overview_epoch=journey.overview_epoch,
            anchor_node_id=(
                str(anchor)
                if head and (anchor := self._overview_coverage_anchor(head))
                else None
            ),
            updated_at=head.created_at if head else None,
            is_refreshing=refreshing,
            status=status,
            base_revision_id=str(head.id) if head else None,
            base_selected_leaf_node_id=(str(path[-1].id) if path else None),
            base_selected_path_hash=(path_hash(path) if path else None),
        )

    async def update_overview(
        self,
        db: AsyncSession,
        *,
        journey_id: str,
        sections: InteractionOverviewSections,
        expected_overview_epoch: int,
        expected_selection_epoch: int,
        base_revision_id: str | None = None,
        base_selected_leaf_node_id: str | None = None,
        base_selected_path_hash: str | None = None,
    ) -> InteractionOverviewResponse:
        journey = await self._active_journey_for_update(db, journey_id)
        if (
            expected_selection_epoch > journey.selection_epoch
            or expected_overview_epoch > journey.overview_epoch
        ):
            raise ConflictError(
                "旅程在别处发生了变化",
                code="interaction_overview_conflict",
            )
        path = await self._repo.get_selected_path(db, journey=journey)
        if not path:
            raise ConflictError("当前发展不存在")
        previous = await self._repo.get_overview_head(db, journey=journey)
        if base_selected_leaf_node_id is None or base_selected_path_hash is None:
            # Legacy internal callers still use the current edit baseline.
            if (
                expected_selection_epoch != journey.selection_epoch
                or expected_overview_epoch != journey.overview_epoch
            ):
                raise ConflictError(
                    "旅程在别处发生了变化", code="interaction_overview_conflict"
                )
            base_revision_id = str(previous.id) if previous else None
            base_selected_leaf_node_id = str(path[-1].id)
            base_selected_path_hash = path_hash(path)
        base_leaf_id = _parse_uuid(
            base_selected_leaf_node_id, "base_selected_leaf_node_id"
        )
        current_ids = [node.id for node in path]
        if (
            base_leaf_id not in current_ids
            or path_hash(path[: current_ids.index(base_leaf_id) + 1])
            != base_selected_path_hash
        ):
            raise ConflictError(
                "旅程在别处发生了变化", code="interaction_overview_conflict"
            )
        base_revision = None
        if base_revision_id is None:
            if (
                previous is not None
                or expected_selection_epoch != journey.selection_epoch
                or expected_overview_epoch != journey.overview_epoch
                or base_leaf_id != path[-1].id
            ):
                raise ConflictError(
                    "旅程在别处发生了变化", code="interaction_overview_conflict"
                )
        else:
            base_revision = await self._repo.get_overview_revision(
                db,
                journey=journey,
                revision_id=_parse_uuid(base_revision_id, "base_revision_id"),
            )
            original_path = path[: current_ids.index(base_leaf_id) + 1]
            if base_revision is None or not self._overview_matches_path(
                base_revision, original_path
            ):
                raise ConflictError(
                    "旅程在别处发生了变化", code="interaction_overview_conflict"
                )
            if previous is None or not await self._automatic_overview_descends_from(
                db,
                journey=journey,
                current=previous,
                base=base_revision,
            ):
                raise ConflictError(
                    "回顾已在别处手动修改", code="interaction_overview_conflict"
                )
        old_sections = InteractionOverviewSections.model_validate(
            previous.sections if previous else {}
        )
        if "long_term_agreements" not in sections.model_fields_set:
            sections = sections.model_copy(
                update={"long_term_agreements": old_sections.long_term_agreements}
            )
        if not sections.has_content() and not (
            previous is not None
            and old_sections.long_term_agreements
            and not render_overview_sections(old_sections)
        ):
            raise ValidationError("回顾内容不能为空")
        if previous is not None:
            previous.promoted = False
        revision = InteractionOverviewRevision(
            novel_id=journey.novel_id,
            journey_id=journey.id,
            anchor_node_id=base_leaf_id,
            path_hash=base_selected_path_hash,
            # No overview has compressed any original node on a first manual save.
            # An explicit empty prefix differs from legacy NULL/NULL coverage.
            coverage_anchor_node_id=(
                self._overview_coverage_anchor(base_revision) if base_revision else None
            ),
            coverage_path_hash=(
                self._overview_coverage_hash(base_revision)
                if base_revision
                else path_hash([])
            ),
            sections=sections.model_dump(),
            source="manual",
            based_on_revision_id=base_revision.id if base_revision else None,
            started_overview_epoch=journey.overview_epoch,
            promoted=True,
            producer={"kind": "user"},
        )
        db.add(revision)
        await db.flush()
        journey.overview_head_revision_id = revision.id
        journey.overview_epoch += 1
        await self._repo.notify_state_changed(db, journey)
        self._repo.touch(journey)
        enqueued = False
        if not is_anonymous_rp_principal() and await self._overview_refresh_is_due(
            db, journey=journey, path=path
        ):
            try:
                snapshot = await build_project_llm_execution_snapshot(
                    db,
                    str(journey.novel_id),
                )
                await _enqueue_overview_refresh_task(
                    db,
                    journey=journey,
                    path=path,
                    snapshot=snapshot,
                )
                enqueued = True
            except ProjectLLMConfigurationError:
                # The user's correction is valid without a connected model. The
                # uncovered raw tail remains in story compilation until a later
                # automatic refresh can absorb it.
                pass
        return InteractionOverviewResponse(
            sections=InteractionOverviewSections.model_validate(revision.sections),
            source=revision.source,
            overview_epoch=journey.overview_epoch,
            anchor_node_id=(
                str(anchor)
                if (anchor := self._overview_coverage_anchor(revision))
                else None
            ),
            updated_at=revision.created_at,
            is_refreshing=enqueued,
            status="refreshing" if enqueued else "ready",
            base_revision_id=str(revision.id),
            base_selected_leaf_node_id=str(path[-1].id),
            base_selected_path_hash=path_hash(path),
        )

    async def retry_overview(
        self,
        db: AsyncSession,
        *,
        journey_id: str,
    ) -> InteractionOverviewResponse:
        if is_anonymous_rp_principal():
            raise ValidationError("匿名体验不提供后台回顾")
        journey = await self._active_journey_for_update(db, journey_id)
        path = await self._repo.get_selected_path(db, journey=journey)
        if not self._story_started(path):
            raise ConflictError("故事开始后才会形成回顾")
        if not self._overview_failure_applies(journey, path):
            raise ConflictError("当前回顾不需要重新整理")
        snapshot = await build_project_llm_execution_snapshot(
            db,
            str(journey.novel_id),
            **({"web_search_enabled": True} if journey.web_search_enabled else {}),
        )
        await _enqueue_overview_refresh_task(
            db,
            journey=journey,
            path=path,
            snapshot=snapshot,
        )
        journey.overview_failure = {}
        return await self.get_overview(db, journey_id=journey_id)

    @staticmethod
    def _overview_matches_path(
        overview: InteractionOverviewRevision,
        path: list[InteractionMessageNode],
    ) -> bool:
        ids = [node.id for node in path]
        if overview.anchor_node_id not in ids:
            return False
        anchor_index = ids.index(overview.anchor_node_id)
        return path_hash(path[: anchor_index + 1]) == overview.path_hash

    @staticmethod
    def _overview_coverage_anchor(
        overview: InteractionOverviewRevision,
    ) -> uuid.UUID | None:
        if (
            overview.coverage_anchor_node_id is None
            and overview.coverage_path_hash == path_hash([])
        ):
            return None
        return overview.coverage_anchor_node_id or overview.anchor_node_id

    @staticmethod
    def _overview_coverage_hash(
        overview: InteractionOverviewRevision,
    ) -> str:
        return overview.coverage_path_hash or overview.path_hash

    @classmethod
    def _overview_coverage_matches_path(
        cls,
        overview: InteractionOverviewRevision,
        path: list[InteractionMessageNode],
    ) -> bool:
        anchor = cls._overview_coverage_anchor(overview)
        if anchor is None:
            return cls._overview_coverage_hash(overview) == path_hash([])
        ids = [node.id for node in path]
        if anchor not in ids:
            return False
        anchor_index = ids.index(anchor)
        return path_hash(path[: anchor_index + 1]) == cls._overview_coverage_hash(
            overview
        )

    @staticmethod
    def _overview_failure_applies(
        journey: InteractionJourney,
        path: list[InteractionMessageNode],
    ) -> bool:
        failure = dict(journey.overview_failure or {})
        failed_hash = str(failure.get("path_hash") or "")
        anchor_value = failure.get("anchor_node_id")
        if anchor_value:
            try:
                anchor_id = uuid.UUID(str(anchor_value))
            except (TypeError, ValueError):
                return False
            ids = [node.id for node in path]
            if anchor_id not in ids or not failed_hash:
                return False
            anchor_index = ids.index(anchor_id)
            return path_hash(path[: anchor_index + 1]) == failed_hash
        node_ids = [str(value) for value in (failure.get("node_ids") or [])]
        if not node_ids or not failed_hash or len(path) < len(node_ids):
            return False
        prefix = path[: len(node_ids)]
        return [str(node.id) for node in prefix] == node_ids and path_hash(
            prefix
        ) == failed_hash

    async def _best_overview_for_path(
        self,
        db: AsyncSession,
        *,
        journey: InteractionJourney,
        path: list[InteractionMessageNode],
    ) -> InteractionOverviewRevision | None:
        positions = {node.id: index for index, node in enumerate(path)}
        candidates = await self._repo.list_overview_revisions_for_anchors(
            db,
            journey=journey,
            anchor_node_ids=list(positions),
        )
        valid = [
            candidate
            for candidate in candidates
            if path_hash(path[: positions[candidate.anchor_node_id] + 1])
            == candidate.path_hash
        ]
        manuals = [candidate for candidate in valid if candidate.source == "manual"]
        latest_manual = max(
            manuals,
            key=lambda candidate: candidate.started_overview_epoch,
            default=None,
        )
        if latest_manual is not None:
            compatible = []
            for candidate in valid:
                if candidate.id == latest_manual.id or (
                    candidate.source == "automatic"
                    and await self._automatic_overview_descends_from(
                        db,
                        journey=journey,
                        current=candidate,
                        base=latest_manual,
                    )
                ):
                    compatible.append(candidate)
            valid = compatible
        best = None
        best_key = (-1, -1)
        for candidate in valid:
            position = positions[candidate.anchor_node_id]
            key = (position, candidate.started_overview_epoch)
            if key <= best_key:
                continue
            best = candidate
            best_key = key
        return best

    async def _activate_best_overview_head(
        self,
        db: AsyncSession,
        *,
        journey: InteractionJourney,
        path: list[InteractionMessageNode],
    ) -> InteractionOverviewRevision | None:
        current = await self._repo.get_overview_head(db, journey=journey)
        best = await self._best_overview_for_path(
            db,
            journey=journey,
            path=path,
        )
        if current is None and best is None:
            return None
        if current is not None and best is not None and current.id == best.id:
            return current
        if current is not None:
            current.promoted = False
        if best is not None:
            best.promoted = True
            journey.overview_head_revision_id = best.id
        else:
            journey.overview_head_revision_id = None
        journey.overview_epoch += 1
        await self._repo.notify_state_changed(db, journey)
        return best

    async def _automatic_overview_descends_from(
        self,
        db: AsyncSession,
        *,
        journey: InteractionJourney,
        current: InteractionOverviewRevision,
        base: InteractionOverviewRevision,
    ) -> bool:
        candidate = current
        seen: set[uuid.UUID] = set()
        for _ in range(1000):
            if candidate.id == base.id:
                return True
            if candidate.id in seen or candidate.source != "automatic":
                return False
            seen.add(candidate.id)
            if candidate.based_on_revision_id is None:
                return False
            parent = await self._repo.get_overview_revision(
                db,
                journey=journey,
                revision_id=candidate.based_on_revision_id,
            )
            if parent is None:
                return False
            candidate = parent
        return False

    async def _overview_manual_ancestor(
        self,
        db: AsyncSession,
        *,
        journey: InteractionJourney,
        current: InteractionOverviewRevision,
    ) -> InteractionOverviewRevision | None:
        candidate = current
        seen: set[uuid.UUID] = set()
        for _ in range(1000):
            if candidate.source == "manual":
                return candidate
            if (
                candidate.id in seen
                or candidate.source != "automatic"
                or candidate.based_on_revision_id is None
            ):
                return None
            seen.add(candidate.id)
            parent = await self._repo.get_overview_revision(
                db,
                journey=journey,
                revision_id=candidate.based_on_revision_id,
            )
            if parent is None:
                return None
            candidate = parent
        return None

    async def _overview_refresh_is_due(
        self,
        db: AsyncSession,
        *,
        journey: InteractionJourney,
        path: list[InteractionMessageNode],
    ) -> bool:
        if not self._story_started(path) or self._overview_failure_applies(
            journey,
            path,
        ):
            return False
        head = await self._repo.get_overview_head(db, journey=journey)
        start_index = 0
        if (
            head is not None
            and self._overview_matches_path(head, path)
            and self._overview_coverage_matches_path(head, path)
        ):
            current_ids = [node.id for node in path]
            anchor = self._overview_coverage_anchor(head)
            start_index = current_ids.index(anchor) + 1 if anchor else 0
        uncovered = path[start_index:]
        prefix_end = _summary_compressible_prefix_end(uncovered)
        return (
            sum(node.token_estimate for node in uncovered[:prefix_end])
            >= SUMMARY_TRIGGER_TOKENS
        )

    async def _maybe_enqueue_overview_after_formalization(
        self,
        db: AsyncSession,
        *,
        journey: InteractionJourney,
        snapshot: dict,
    ) -> str | None:
        if is_anonymous_rp_principal():
            return None
        path = await self._repo.get_selected_path(db, journey=journey)
        await self._activate_best_overview_head(
            db,
            journey=journey,
            path=path,
        )
        if not await self._overview_refresh_is_due(
            db,
            journey=journey,
            path=path,
        ):
            return None
        return await _enqueue_overview_refresh_task(
            db,
            journey=journey,
            path=path,
            snapshot=snapshot,
        )
