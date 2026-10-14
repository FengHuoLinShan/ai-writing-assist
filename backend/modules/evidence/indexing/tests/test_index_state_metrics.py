"""Metric reads preserve nullable fingerprint semantics without loading state rows."""

import uuid

from sqlalchemy import event

from modules.evidence.indexing.index_state import RagIndexStateService
from modules.evidence.indexing.models import RagIndexState


async def test_metrics_preserve_nulls_ranges_without_hydration(
    db_session, test_project_id
):
    values = []
    for index in range(600):
        row = {
            "chapter_index": index + 1,
            "content_mode": "working" if index < 500 else "canonical",
            "status": ("succeeded", "pending", "failed")[index % 3],
            "requested_hash": None if index % 2 == 0 else "new",
            "requested_source_id": None,
            "indexed_source_id": uuid.uuid4() if index % 7 == 0 else None,
        }
        row["indexed_hash"] = "old" if index % 5 == 0 else row["requested_hash"]
        values.append(row)
        db_session.add(RagIndexState(novel_id=uuid.UUID(test_project_id), **row))
    await db_session.flush()
    db_session.expunge_all()

    hydrated = []

    def record_hydration(session, instance):
        if isinstance(instance, RagIndexState):
            hydrated.append(instance.id)

    event.listen(db_session.sync_session, "loaded_as_persistent", record_hydration)
    service = RagIndexStateService()
    try:
        summary = await service.summary(db_session, test_project_id)
        actual = await service.freshness(
            db_session,
            novel_id=test_project_id,
            content_mode="working",
            chapter_from=11,
            chapter_to=70,
        )
    finally:
        event.remove(db_session.sync_session, "loaded_as_persistent", record_hydration)

    def counts(rows):
        fresh = sum(
            row["status"] == "succeeded"
            and row["requested_hash"] == row["indexed_hash"]
            and row["requested_source_id"] == row["indexed_source_id"]
            for row in rows
        )
        return {"total": len(rows), "fresh": fresh, "stale": len(rows) - fresh}

    assert summary == {
        "by_content_mode": {
            mode: counts([row for row in values if row["content_mode"] == mode])
            for mode in ("canonical", "working")
        }
    }
    selected = [
        row
        for row in values
        if row["content_mode"] == "working" and 11 <= row["chapter_index"] <= 70
    ]
    assert actual == {
        "content_mode": "working",
        **counts(selected),
        "statuses": sorted({row["status"] for row in selected}),
    }
    assert not hydrated, f"metrics loaded {len(hydrated)} ORM rows"
