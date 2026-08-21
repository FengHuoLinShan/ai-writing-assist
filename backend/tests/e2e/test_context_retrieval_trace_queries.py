from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.evidence.compilation.models import ContextRetrievalTrace
from modules.evidence.compilation.services.retrieval_trace_service import (
    RetrievalTraceService,
)
from modules.project.models import Project

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


def _trace(
    novel_id: uuid.UUID,
    *,
    drop_counts: object,
    safe_empty_reason: str | None,
    created_at: datetime | None = None,
) -> ContextRetrievalTrace:
    values = {
        "novel_id": novel_id,
        "content_mode": "canonical",
        "consumer_action": "e2e",
        "retrieval_purpose": "generic_context",
        "reveal_mode": "author",
        "plan_version": "e2e-v1",
        "plan_hash": uuid.uuid4().hex,
        "clause_summaries": [],
        "candidate_count": 0,
        "unique_count": 0,
        "hydrated_count": 0,
        "drop_counts": drop_counts,
        "safe_empty_reason": safe_empty_reason,
        "degraded": False,
        "warning_codes": [],
        "latency_metadata": {},
    }
    if created_at is not None:
        values["created_at"] = created_at
    return ContextRetrievalTrace(**values)  # type: ignore[arg-type]


async def test_postgres_trace_aggregation_matches_sqlite_safety_semantics(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4()
    other_novel_id = uuid.uuid4()
    db_session.add_all(
        [
            Project(id=novel_id, title="trace aggregate e2e"),
            Project(id=other_novel_id, title="other trace aggregate e2e"),
        ]
    )
    await db_session.flush()
    db_session.add_all(
        [
            _trace(
                novel_id,
                drop_counts={
                    "valid": 2,
                    "numeric_string": "3",
                    "negative": -1,
                    "too_large": 10**20,
                },
                safe_empty_reason="",
            ),
            _trace(
                novel_id,
                drop_counts={"valid": 4},
                safe_empty_reason="classified",
            ),
            _trace(
                novel_id,
                drop_counts=["not", "an", "object"],
                safe_empty_reason=None,
            ),
            _trace(
                other_novel_id,
                drop_counts={"valid": 100},
                safe_empty_reason="other_project",
            ),
        ]
    )
    await db_session.flush()

    summary = await RetrievalTraceService().summarize(
        db_session,
        novel_id=str(novel_id),
        content_mode="canonical",
        window_hours=1,
    )

    assert summary["query_count"] == 3
    assert summary["empty_count"] == 3
    assert summary["unclassified_empty_count"] == 2
    assert summary["safe_empty_reasons"] == {"classified": 1}
    assert summary["drop_counts"] == {"valid": 6}


async def test_postgres_trace_prune_combines_age_cap_and_novel_isolation(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4()
    other_novel_id = uuid.uuid4()
    old_time = datetime.now(UTC) - timedelta(days=40)
    db_session.add_all(
        [
            Project(id=novel_id, title="trace prune e2e"),
            Project(id=other_novel_id, title="other trace prune e2e"),
        ]
    )
    await db_session.flush()
    target_old = _trace(
        novel_id,
        drop_counts={},
        safe_empty_reason="no_query_clause",
        created_at=old_time,
    )
    target_recent = _trace(
        novel_id,
        drop_counts={},
        safe_empty_reason="no_query_clause",
    )
    other_old = _trace(
        other_novel_id,
        drop_counts={},
        safe_empty_reason="no_query_clause",
        created_at=old_time,
    )
    db_session.add_all([target_old, target_recent, other_old])
    await db_session.flush()

    service = RetrievalTraceService()
    assert (
        await service.prune(
            db_session,
            novel_id=str(novel_id),
            retention_days=30,
            retain_latest=1,
            dry_run=False,
        )
        == 1
    )
    assert await db_session.get(ContextRetrievalTrace, target_old.id) is None
    assert await db_session.get(ContextRetrievalTrace, target_recent.id) is not None
    assert await db_session.get(ContextRetrievalTrace, other_old.id) is not None
