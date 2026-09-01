"""Persistence helpers for the interaction aggregate."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import String, cast, func, literal, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from modules.interaction.models import (
    InteractionAccountPreference,
    InteractionBranchSelection,
    InteractionGenerationAttempt,
    InteractionJourney,
    InteractionMessageNode,
    InteractionOverviewRevision,
    InteractionSourceRevision,
    InteractionSummarySegment,
)

ROOT_PARENT_KEY = "__root__"
ACTIVE_ATTEMPT_STATUSES = {"pending", "preparing_context", "running"}
UNRESOLVED_ATTEMPT_STATUSES = {
    *ACTIVE_ATTEMPT_STATUSES,
    "awaiting_continue",
}


def parent_key(parent_node_id: uuid.UUID | None) -> str:
    return str(parent_node_id) if parent_node_id is not None else ROOT_PARENT_KEY


class InteractionRepository:
    async def get_source_revision(
        self,
        db: AsyncSession,
        *,
        revision_id: uuid.UUID,
        owner_id: uuid.UUID,
        for_update: bool = False,
    ) -> InteractionSourceRevision | None:
        stmt = select(InteractionSourceRevision).where(
            InteractionSourceRevision.id == revision_id,
            InteractionSourceRevision.owner_id == owner_id,
        )
        if for_update:
            stmt = stmt.with_for_update()
        return (await db.execute(stmt)).scalar_one_or_none()

    async def list_source_revisions(
        self,
        db: AsyncSession,
        *,
        owner_id: uuid.UUID,
    ) -> list[InteractionSourceRevision]:
        return list(
            (
                await db.execute(
                    select(InteractionSourceRevision)
                    .where(InteractionSourceRevision.owner_id == owner_id)
                    .order_by(
                        InteractionSourceRevision.source_novel_id,
                        InteractionSourceRevision.version_number.desc(),
                    )
                )
            )
            .scalars()
            .all()
        )

    async def latest_source_revision(
        self,
        db: AsyncSession,
        *,
        source_novel_id: uuid.UUID,
        owner_id: uuid.UUID,
    ) -> InteractionSourceRevision | None:
        return (
            await db.execute(
                select(InteractionSourceRevision)
                .where(
                    InteractionSourceRevision.source_novel_id == source_novel_id,
                    InteractionSourceRevision.owner_id == owner_id,
                )
                .order_by(InteractionSourceRevision.version_number.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def source_revision_by_manifest(
        self,
        db: AsyncSession,
        *,
        source_novel_id: uuid.UUID,
        owner_id: uuid.UUID,
        manifest_hash: str,
    ) -> InteractionSourceRevision | None:
        return (
            await db.execute(
                select(InteractionSourceRevision).where(
                    InteractionSourceRevision.source_novel_id == source_novel_id,
                    InteractionSourceRevision.owner_id == owner_id,
                    InteractionSourceRevision.manifest_hash == manifest_hash,
                )
            )
        ).scalar_one_or_none()

    async def source_reference_count(
        self,
        db: AsyncSession,
        *,
        source_novel_id: uuid.UUID,
    ) -> int:
        return int(
            (
                await db.execute(
                    select(func.count(InteractionJourney.id))
                    .join(
                        InteractionSourceRevision,
                        InteractionSourceRevision.id
                        == InteractionJourney.source_revision_id,
                    )
                    .where(InteractionSourceRevision.source_novel_id == source_novel_id)
                )
            ).scalar_one()
            or 0
        )

    async def get_journey(
        self,
        db: AsyncSession,
        *,
        journey_id: uuid.UUID,
        owner_id: uuid.UUID,
        status: str | None = "active",
        for_update: bool = False,
    ) -> InteractionJourney | None:
        conditions = [
            InteractionJourney.id == journey_id,
            InteractionJourney.owner_id == owner_id,
        ]
        if status is not None:
            conditions.append(InteractionJourney.status == status)
        stmt = select(InteractionJourney).where(*conditions)
        if for_update:
            stmt = stmt.execution_options(populate_existing=True).with_for_update()
        return (await db.execute(stmt)).scalar_one_or_none()

    async def list_journeys(
        self,
        db: AsyncSession,
        *,
        owner_id: uuid.UUID,
        status: str,
        search: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list[InteractionJourney], int]:
        conditions = [
            InteractionJourney.owner_id == owner_id,
            InteractionJourney.status == status,
        ]
        cleaned_search = (search or "").strip()
        if cleaned_search:
            pattern = f"%{cleaned_search[:100]}%"
            conditions.append(
                or_(
                    InteractionJourney.title.ilike(pattern),
                    InteractionJourney.opening_text.ilike(pattern),
                )
            )
        total = (
            await db.execute(select(func.count(InteractionJourney.id)).where(*conditions))
        ).scalar_one()
        items = list(
            (
                await db.execute(
                    select(InteractionJourney)
                    .where(*conditions)
                    .order_by(
                        InteractionJourney.latest_activity_at.desc(),
                        InteractionJourney.id.desc(),
                    )
                    .offset(offset)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return items, int(total)

    async def get_nodes_for_journey_cards(
        self,
        db: AsyncSession,
        *,
        journeys: list[InteractionJourney],
        node_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, InteractionMessageNode]:
        if not journeys or not node_ids:
            return {}
        journey_ids = [journey.id for journey in journeys]
        novel_ids = [journey.novel_id for journey in journeys]
        rows = list(
            (
                await db.execute(
                    select(InteractionMessageNode).where(
                        InteractionMessageNode.id.in_(node_ids),
                        InteractionMessageNode.journey_id.in_(journey_ids),
                        InteractionMessageNode.novel_id.in_(novel_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        return {row.id: row for row in rows}

    async def get_overviews_for_journey_cards(
        self,
        db: AsyncSession,
        *,
        journeys: list[InteractionJourney],
    ) -> dict[uuid.UUID, InteractionOverviewRevision]:
        revision_ids = [
            journey.overview_head_revision_id
            for journey in journeys
            if journey.overview_head_revision_id is not None
        ]
        if not revision_ids:
            return {}
        rows = list(
            (
                await db.execute(
                    select(InteractionOverviewRevision).where(
                        InteractionOverviewRevision.id.in_(revision_ids),
                        InteractionOverviewRevision.journey_id.in_(
                            [journey.id for journey in journeys]
                        ),
                        InteractionOverviewRevision.novel_id.in_(
                            [journey.novel_id for journey in journeys]
                        ),
                    )
                )
            )
            .scalars()
            .all()
        )
        return {row.id: row for row in rows}

    async def get_attempts_for_journey_cards(
        self,
        db: AsyncSession,
        *,
        owner_id: uuid.UUID,
        journeys: list[InteractionJourney],
    ) -> dict[uuid.UUID, InteractionGenerationAttempt]:
        leaf_ids = [
            journey.selected_leaf_node_id
            for journey in journeys
            if journey.selected_leaf_node_id is not None
        ]
        if not leaf_ids:
            return {}
        rows = list(
            (
                await db.execute(
                    select(InteractionGenerationAttempt)
                    .where(
                        InteractionGenerationAttempt.owner_id == owner_id,
                        InteractionGenerationAttempt.journey_id.in_(
                            [journey.id for journey in journeys]
                        ),
                        InteractionGenerationAttempt.response_to_node_id.in_(leaf_ids),
                    )
                    .order_by(
                        InteractionGenerationAttempt.created_at.desc(),
                        InteractionGenerationAttempt.id.desc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        journeys_by_id = {journey.id: journey for journey in journeys}
        result: dict[uuid.UUID, InteractionGenerationAttempt] = {}
        for row in rows:
            journey = journeys_by_id.get(row.journey_id)
            if (
                journey is None
                or row.journey_id in result
                or row.response_to_node_id != journey.selected_leaf_node_id
                or row.started_selection_epoch != journey.selection_epoch
                or row.novel_id != journey.novel_id
            ):
                continue
            result[row.journey_id] = row
        return result

    async def get_node(
        self,
        db: AsyncSession,
        *,
        journey: InteractionJourney,
        node_id: uuid.UUID,
        for_update: bool = False,
    ) -> InteractionMessageNode | None:
        stmt = select(InteractionMessageNode).where(
            InteractionMessageNode.id == node_id,
            InteractionMessageNode.journey_id == journey.id,
            InteractionMessageNode.novel_id == journey.novel_id,
        )
        if for_update:
            stmt = stmt.execution_options(populate_existing=True).with_for_update()
        return (await db.execute(stmt)).scalar_one_or_none()

    async def get_nodes_in_order(
        self,
        db: AsyncSession,
        *,
        journey: InteractionJourney,
        node_ids: list[uuid.UUID],
    ) -> list[InteractionMessageNode]:
        if not node_ids:
            return []
        rows = list(
            (
                await db.execute(
                    select(InteractionMessageNode).where(
                        InteractionMessageNode.journey_id == journey.id,
                        InteractionMessageNode.novel_id == journey.novel_id,
                        InteractionMessageNode.id.in_(node_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        by_id = {row.id: row for row in rows}
        if len(by_id) != len(node_ids):
            raise RuntimeError("interaction context references a missing node")
        return [by_id[node_id] for node_id in node_ids]

    async def get_ancestry(
        self,
        db: AsyncSession,
        *,
        journey: InteractionJourney,
        node: InteractionMessageNode,
    ) -> list[InteractionMessageNode]:
        node_id_text = cast(InteractionMessageNode.id, String)
        ancestry = select(
            InteractionMessageNode.id.label("id"),
            InteractionMessageNode.parent_node_id.label("parent_node_id"),
            literal(0).label("depth"),
            (literal("|") + node_id_text + literal("|")).label("visited"),
        ).where(
            InteractionMessageNode.id == node.id,
            InteractionMessageNode.journey_id == journey.id,
            InteractionMessageNode.novel_id == journey.novel_id,
        )
        ancestry = ancestry.cte("interaction_ancestry", recursive=True)
        parent = aliased(InteractionMessageNode)
        parent_id_text = cast(parent.id, String)
        ancestry = ancestry.union_all(
            select(
                parent.id,
                parent.parent_node_id,
                ancestry.c.depth + 1,
                ancestry.c.visited + parent_id_text + literal("|"),
            )
            .join(ancestry, parent.id == ancestry.c.parent_node_id)
            .where(
                parent.journey_id == journey.id,
                parent.novel_id == journey.novel_id,
                ~ancestry.c.visited.like(literal("%|") + parent_id_text + literal("|%")),
            )
        )
        path = list(
            (
                await db.execute(
                    select(InteractionMessageNode)
                    .join(ancestry, ancestry.c.id == InteractionMessageNode.id)
                    .order_by(ancestry.c.depth.desc())
                )
            )
            .scalars()
            .all()
        )
        if not path or path[-1].id != node.id or path[0].parent_node_id is not None:
            raise RuntimeError("interaction node ancestry is invalid")
        for index, item in enumerate(path):
            expected_parent = path[index - 1].id if index else None
            if item.parent_node_id != expected_parent:
                raise RuntimeError("interaction node ancestry is invalid")
        return path

    async def get_journey_for_task(
        self,
        db: AsyncSession,
        *,
        journey_id: uuid.UUID,
        novel_id: uuid.UUID,
        for_update: bool = False,
    ) -> InteractionJourney | None:
        stmt = select(InteractionJourney).where(
            InteractionJourney.id == journey_id,
            InteractionJourney.novel_id == novel_id,
            InteractionJourney.status == "active",
        )
        if for_update:
            stmt = stmt.execution_options(populate_existing=True).with_for_update()
        return (await db.execute(stmt)).scalar_one_or_none()

    async def get_attempt_for_task(
        self,
        db: AsyncSession,
        *,
        journey: InteractionJourney,
        attempt_id: uuid.UUID,
        task_id: uuid.UUID,
        for_update: bool = False,
    ) -> InteractionGenerationAttempt | None:
        stmt = select(InteractionGenerationAttempt).where(
            InteractionGenerationAttempt.id == attempt_id,
            InteractionGenerationAttempt.journey_id == journey.id,
            InteractionGenerationAttempt.novel_id == journey.novel_id,
            InteractionGenerationAttempt.owner_id == journey.owner_id,
            InteractionGenerationAttempt.task_id == task_id,
        )
        if for_update:
            stmt = stmt.execution_options(populate_existing=True).with_for_update()
        return (await db.execute(stmt)).scalar_one_or_none()

    async def get_selected_path(
        self,
        db: AsyncSession,
        *,
        journey: InteractionJourney,
    ) -> list[InteractionMessageNode]:
        selections = list(
            (
                await db.execute(
                    select(InteractionBranchSelection).where(
                        InteractionBranchSelection.journey_id == journey.id,
                        InteractionBranchSelection.novel_id == journey.novel_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        selected_by_parent = {
            item.parent_key: item.selected_child_node_id for item in selections
        }
        ordered_ids: list[uuid.UUID] = []
        seen: set[uuid.UUID] = set()
        key = ROOT_PARENT_KEY
        while key in selected_by_parent:
            node_id = selected_by_parent[key]
            if node_id in seen:
                raise RuntimeError("interaction branch selection cycle detected")
            seen.add(node_id)
            ordered_ids.append(node_id)
            key = str(node_id)
        if not ordered_ids:
            return []
        rows = list(
            (
                await db.execute(
                    select(InteractionMessageNode).where(
                        InteractionMessageNode.journey_id == journey.id,
                        InteractionMessageNode.novel_id == journey.novel_id,
                        InteractionMessageNode.id.in_(ordered_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        by_id = {row.id: row for row in rows}
        if len(by_id) != len(ordered_ids):
            raise RuntimeError("interaction selected path references a missing node")
        return [by_id[node_id] for node_id in ordered_ids]

    async def set_selected_child(
        self,
        db: AsyncSession,
        *,
        journey: InteractionJourney,
        parent_node_id: uuid.UUID | None,
        child_node_id: uuid.UUID,
    ) -> None:
        key = parent_key(parent_node_id)
        row = (
            await db.execute(
                select(InteractionBranchSelection)
                .where(
                    InteractionBranchSelection.journey_id == journey.id,
                    InteractionBranchSelection.novel_id == journey.novel_id,
                    InteractionBranchSelection.parent_key == key,
                )
                .execution_options(populate_existing=True)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            row = InteractionBranchSelection(
                novel_id=journey.novel_id,
                journey_id=journey.id,
                parent_node_id=parent_node_id,
                parent_key=key,
                selected_child_node_id=child_node_id,
            )
            db.add(row)
        else:
            row.parent_node_id = parent_node_id
            row.selected_child_node_id = child_node_id
        await db.flush()

    async def list_children(
        self,
        db: AsyncSession,
        *,
        journey: InteractionJourney,
        parent_node_id: uuid.UUID | None,
    ) -> list[InteractionMessageNode]:
        condition = (
            InteractionMessageNode.parent_node_id.is_(None)
            if parent_node_id is None
            else InteractionMessageNode.parent_node_id == parent_node_id
        )
        return list(
            (
                await db.execute(
                    select(InteractionMessageNode)
                    .where(
                        InteractionMessageNode.journey_id == journey.id,
                        InteractionMessageNode.novel_id == journey.novel_id,
                        condition,
                    )
                    .order_by(
                        InteractionMessageNode.created_at.asc(),
                        InteractionMessageNode.id.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )

    async def list_tree_nodes(
        self,
        db: AsyncSession,
        *,
        journey: InteractionJourney,
    ) -> list[InteractionMessageNode]:
        return list(
            (
                await db.execute(
                    select(InteractionMessageNode)
                    .where(
                        InteractionMessageNode.journey_id == journey.id,
                        InteractionMessageNode.novel_id == journey.novel_id,
                    )
                    .order_by(
                        InteractionMessageNode.created_at.asc(),
                        InteractionMessageNode.id.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )

    async def get_account_preference(
        self,
        db: AsyncSession,
        *,
        owner_id: uuid.UUID,
        for_update: bool = False,
    ) -> InteractionAccountPreference | None:
        stmt = select(InteractionAccountPreference).where(
            InteractionAccountPreference.owner_id == owner_id
        )
        if for_update:
            stmt = stmt.execution_options(populate_existing=True).with_for_update()
        return (await db.execute(stmt)).scalar_one_or_none()

    async def lock_account_preference(
        self,
        db: AsyncSession,
        *,
        owner_id: uuid.UUID,
    ) -> None:
        bind = db.get_bind()
        if bind is not None and bind.dialect.name == "postgresql":
            await db.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"interaction_preference:{owner_id}"},
            )

    async def lock_owner_generation_slots(
        self,
        db: AsyncSession,
        *,
        owner_id: uuid.UUID,
    ) -> None:
        bind = db.get_bind()
        if bind is not None and bind.dialect.name == "postgresql":
            await db.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"interaction_generation:{owner_id}"},
            )

    async def count_active_attempts(
        self,
        db: AsyncSession,
        *,
        owner_id: uuid.UUID,
    ) -> int:
        value = (
            await db.execute(
                select(func.count(InteractionGenerationAttempt.id)).where(
                    InteractionGenerationAttempt.owner_id == owner_id,
                    InteractionGenerationAttempt.status.in_(
                        sorted(ACTIVE_ATTEMPT_STATUSES)
                    ),
                )
            )
        ).scalar_one()
        return int(value)

    async def get_attempt_by_idempotency(
        self,
        db: AsyncSession,
        *,
        owner_id: uuid.UUID,
        idempotency_key: str,
    ) -> InteractionGenerationAttempt | None:
        return (
            await db.execute(
                select(InteractionGenerationAttempt).where(
                    InteractionGenerationAttempt.owner_id == owner_id,
                    InteractionGenerationAttempt.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()

    async def get_attempt(
        self,
        db: AsyncSession,
        *,
        journey: InteractionJourney,
        attempt_id: uuid.UUID,
        for_update: bool = False,
    ) -> InteractionGenerationAttempt | None:
        stmt = select(InteractionGenerationAttempt).where(
            InteractionGenerationAttempt.id == attempt_id,
            InteractionGenerationAttempt.owner_id == journey.owner_id,
            InteractionGenerationAttempt.journey_id == journey.id,
            InteractionGenerationAttempt.novel_id == journey.novel_id,
        )
        if for_update:
            stmt = stmt.execution_options(populate_existing=True).with_for_update()
        return (await db.execute(stmt)).scalar_one_or_none()

    async def get_active_attempt(
        self,
        db: AsyncSession,
        *,
        journey: InteractionJourney,
        for_update: bool = False,
    ) -> InteractionGenerationAttempt | None:
        stmt = (
            select(InteractionGenerationAttempt)
            .where(
                InteractionGenerationAttempt.owner_id == journey.owner_id,
                InteractionGenerationAttempt.journey_id == journey.id,
                InteractionGenerationAttempt.novel_id == journey.novel_id,
                InteractionGenerationAttempt.status.in_(sorted(ACTIVE_ATTEMPT_STATUSES)),
            )
            .order_by(
                InteractionGenerationAttempt.created_at.desc(),
                InteractionGenerationAttempt.id.desc(),
            )
            .limit(1)
        )
        if for_update:
            stmt = stmt.execution_options(populate_existing=True).with_for_update()
        return (await db.execute(stmt)).scalar_one_or_none()

    async def get_unresolved_attempt(
        self,
        db: AsyncSession,
        *,
        journey: InteractionJourney,
        for_update: bool = False,
    ) -> InteractionGenerationAttempt | None:
        stmt = (
            select(InteractionGenerationAttempt)
            .where(
                InteractionGenerationAttempt.owner_id == journey.owner_id,
                InteractionGenerationAttempt.journey_id == journey.id,
                InteractionGenerationAttempt.novel_id == journey.novel_id,
                InteractionGenerationAttempt.status.in_(
                    sorted(UNRESOLVED_ATTEMPT_STATUSES)
                ),
            )
            .order_by(
                InteractionGenerationAttempt.created_at.desc(),
                InteractionGenerationAttempt.id.desc(),
            )
            .limit(1)
        )
        if for_update:
            stmt = stmt.execution_options(populate_existing=True).with_for_update()
        return (await db.execute(stmt)).scalar_one_or_none()

    async def list_attempts_for_task_reconciliation(
        self,
        db: AsyncSession,
    ) -> list[InteractionGenerationAttempt]:
        return list(
            (
                await db.execute(
                    select(InteractionGenerationAttempt)
                    .where(
                        InteractionGenerationAttempt.task_id.is_not(None),
                        InteractionGenerationAttempt.status.in_(
                            sorted(ACTIVE_ATTEMPT_STATUSES)
                        ),
                    )
                    .order_by(
                        InteractionGenerationAttempt.novel_id.asc(),
                        InteractionGenerationAttempt.created_at.asc(),
                        InteractionGenerationAttempt.id.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )

    async def get_latest_attempt(
        self,
        db: AsyncSession,
        *,
        journey: InteractionJourney,
        for_update: bool = False,
    ) -> InteractionGenerationAttempt | None:
        stmt = (
            select(InteractionGenerationAttempt)
            .where(
                InteractionGenerationAttempt.owner_id == journey.owner_id,
                InteractionGenerationAttempt.journey_id == journey.id,
                InteractionGenerationAttempt.novel_id == journey.novel_id,
            )
            .order_by(
                InteractionGenerationAttempt.created_at.desc(),
                InteractionGenerationAttempt.id.desc(),
            )
            .limit(1)
        )
        if for_update:
            stmt = stmt.execution_options(populate_existing=True).with_for_update()
        return (await db.execute(stmt)).scalar_one_or_none()

    async def get_latest_attempt_for_selected_leaf(
        self,
        db: AsyncSession,
        *,
        journey: InteractionJourney,
        response_to_node_id: uuid.UUID,
    ) -> InteractionGenerationAttempt | None:
        return (
            await db.execute(
                select(InteractionGenerationAttempt)
                .where(
                    InteractionGenerationAttempt.owner_id == journey.owner_id,
                    InteractionGenerationAttempt.journey_id == journey.id,
                    InteractionGenerationAttempt.novel_id == journey.novel_id,
                    InteractionGenerationAttempt.response_to_node_id
                    == response_to_node_id,
                    InteractionGenerationAttempt.started_selection_epoch
                    == journey.selection_epoch,
                )
                .order_by(
                    InteractionGenerationAttempt.created_at.desc(),
                    InteractionGenerationAttempt.id.desc(),
                )
                .limit(1)
            )
        ).scalar_one_or_none()

    async def list_unadopted_failure_records(
        self,
        db: AsyncSession,
        *,
        journey: InteractionJourney,
    ) -> list[InteractionGenerationAttempt]:
        return list(
            (
                await db.execute(
                    select(InteractionGenerationAttempt)
                    .where(
                        InteractionGenerationAttempt.owner_id == journey.owner_id,
                        InteractionGenerationAttempt.journey_id == journey.id,
                        InteractionGenerationAttempt.novel_id == journey.novel_id,
                        InteractionGenerationAttempt.status == "failed",
                        InteractionGenerationAttempt.result_node_id.is_(None),
                        func.length(func.trim(InteractionGenerationAttempt.visible_text))
                        > 0,
                    )
                    .order_by(
                        InteractionGenerationAttempt.created_at.desc(),
                        InteractionGenerationAttempt.id.desc(),
                    )
                )
            )
            .scalars()
            .all()
        )

    async def get_overview_head(
        self,
        db: AsyncSession,
        *,
        journey: InteractionJourney,
    ) -> InteractionOverviewRevision | None:
        if journey.overview_head_revision_id is None:
            return None
        return (
            await db.execute(
                select(InteractionOverviewRevision).where(
                    InteractionOverviewRevision.id == journey.overview_head_revision_id,
                    InteractionOverviewRevision.journey_id == journey.id,
                    InteractionOverviewRevision.novel_id == journey.novel_id,
                    InteractionOverviewRevision.promoted.is_(True),
                )
            )
        ).scalar_one_or_none()

    async def get_overview_revision(
        self,
        db: AsyncSession,
        *,
        journey: InteractionJourney,
        revision_id: uuid.UUID,
    ) -> InteractionOverviewRevision | None:
        return (
            await db.execute(
                select(InteractionOverviewRevision).where(
                    InteractionOverviewRevision.id == revision_id,
                    InteractionOverviewRevision.journey_id == journey.id,
                    InteractionOverviewRevision.novel_id == journey.novel_id,
                )
            )
        ).scalar_one_or_none()

    async def list_overview_revisions_for_anchors(
        self,
        db: AsyncSession,
        *,
        journey: InteractionJourney,
        anchor_node_ids: list[uuid.UUID],
    ) -> list[InteractionOverviewRevision]:
        if not anchor_node_ids:
            return []
        return list(
            (
                await db.execute(
                    select(InteractionOverviewRevision)
                    .where(
                        InteractionOverviewRevision.journey_id == journey.id,
                        InteractionOverviewRevision.novel_id == journey.novel_id,
                        InteractionOverviewRevision.anchor_node_id.in_(anchor_node_ids),
                    )
                    .order_by(
                        InteractionOverviewRevision.created_at.desc(),
                        InteractionOverviewRevision.id.desc(),
                    )
                )
            )
            .scalars()
            .all()
        )

    async def latest_summary_segment(
        self,
        db: AsyncSession,
        *,
        journey: InteractionJourney,
        path_hash: str,
    ) -> InteractionSummarySegment | None:
        return (
            await db.execute(
                select(InteractionSummarySegment)
                .where(
                    InteractionSummarySegment.journey_id == journey.id,
                    InteractionSummarySegment.novel_id == journey.novel_id,
                    InteractionSummarySegment.path_hash == path_hash,
                )
                .order_by(
                    InteractionSummarySegment.ordinal.desc(),
                    InteractionSummarySegment.id.desc(),
                )
                .limit(1)
            )
        ).scalar_one_or_none()

    async def count_summary_segments(
        self,
        db: AsyncSession,
        *,
        journey: InteractionJourney,
    ) -> int:
        value = (
            await db.execute(
                select(func.count(InteractionSummarySegment.id)).where(
                    InteractionSummarySegment.journey_id == journey.id,
                    InteractionSummarySegment.novel_id == journey.novel_id,
                )
            )
        ).scalar_one()
        return int(value)

    async def list_summary_segments(
        self,
        db: AsyncSession,
        *,
        journey: InteractionJourney,
    ) -> list[InteractionSummarySegment]:
        return list(
            (
                await db.execute(
                    select(InteractionSummarySegment)
                    .where(
                        InteractionSummarySegment.journey_id == journey.id,
                        InteractionSummarySegment.novel_id == journey.novel_id,
                    )
                    .order_by(
                        InteractionSummarySegment.created_at.asc(),
                        InteractionSummarySegment.id.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )

    @staticmethod
    def touch(journey: InteractionJourney) -> None:
        journey.latest_activity_at = datetime.now(UTC)
