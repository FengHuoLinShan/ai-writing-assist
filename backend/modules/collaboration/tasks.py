"""Existing worker leases own V2 execution and transactional outbox delivery."""

from uuid import UUID

from sqlalchemy import select

from infrastructure.tasks.registry import task_handler
from modules.collaboration.models import DomainOutbox
from modules.collaboration.runtime import execute
from modules.evidence.facade import mark_asset_context_changed


@task_handler(
    "collaboration_run",
    recovery_policy="manual_resume",
    root_capability_id="collaboration.run",
    run_request_limit=30,
    run_deadline_seconds=1800,
    run_id=lambda task: str(task.meta["run_id"]),
)
async def handle_collaboration_run(db, task):
    return await execute(db, task)


@task_handler("collaboration_projection", recovery_policy="auto_requeue", max_attempts=3)
async def deliver_creative_outbox(db, task):
    outbox = await db.scalar(
        select(DomainOutbox)
        .where(
            DomainOutbox.novel_id == task.novel_id,
            DomainOutbox.receipt_id == UUID(task.meta["receipt_id"]),
        )
        .with_for_update()
    )
    if outbox is None or outbox.status == "completed":
        return {"replayed": True}
    for result in outbox.payload_json:
        old = result["before"]
        await mark_asset_context_changed(
            db,
            novel_id=str(task.novel_id),
            asset_type={
                "scene": "outline_scene",
                "world_bible_draft": "world_bible_page_draft",
            }.get(old["kind"], old["kind"]),
            asset_id=str(old["id"]),
            reason="creative_workspace_merged",
        )
    outbox.status = "completed"
    await db.flush()
    return {"replayed": False, "receipt_id": str(outbox.receipt_id)}
