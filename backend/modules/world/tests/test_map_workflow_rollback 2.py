"""Workflow-scoped rollback for deep-import map observations."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.map_facade import (
    count_deep_import_map_observations_by_workflow,
    rollback_deep_import_map_observations_by_workflow,
)
from modules.world.map_models import MapObservation


@pytest.mark.asyncio
async def test_map_observation_rollback_is_scoped_preserves_audit_and_is_idempotent(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4()
    other_novel_id = uuid.uuid4()
    observations = [
        MapObservation(
            novel_id=novel_id,
            dynamic_type="location",
            review_state="candidate",
            source_ref={"workflow_id": "wf-rollback", "auto_ingested": True},
        ),
        MapObservation(
            novel_id=novel_id,
            dynamic_type="status",
            review_state="conflicted",
            source_ref={"workflow_id": "wf-other", "auto_ingested": True},
        ),
        MapObservation(
            novel_id=other_novel_id,
            dynamic_type="location",
            review_state="candidate",
            source_ref={"workflow_id": "wf-rollback", "auto_ingested": True},
        ),
        MapObservation(
            novel_id=novel_id,
            dynamic_type="location",
            review_state="candidate",
            source_ref={
                "workflow_id": "wf-rollback",
                "auto_ingested": True,
                "user_edited": True,
            },
        ),
    ]
    db_session.add_all(observations)
    await db_session.flush()

    assert (
        await count_deep_import_map_observations_by_workflow(
            db_session, str(novel_id), "wf-rollback"
        )
        == 2
    )
    assert (
        await rollback_deep_import_map_observations_by_workflow(
            db_session, str(novel_id), "wf-rollback"
        )
        == 1
    )
    assert observations[0].review_state == "ignored"
    assert observations[0].source_ref["rolled_back"] is True
    assert observations[0].source_ref["rollback_reason"] == "workflow_abandoned"
    assert observations[1].review_state == "conflicted"
    assert observations[2].review_state == "candidate"
    assert observations[3].review_state == "candidate"
    assert (
        await rollback_deep_import_map_observations_by_workflow(
            db_session, str(novel_id), "wf-rollback"
        )
        == 0
    )
