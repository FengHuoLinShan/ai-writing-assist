"""Owner-scoped public projections, without model histories or raw manifests."""

from uuid import UUID

from sqlalchemy import select

from core.errors import DomainError
from infrastructure.llm.collaboration import content_hash
from infrastructure.tasks.models import AsyncTask
from modules.collaboration.cases import execution_status, require_case, require_run
from modules.collaboration.contracts import Grant, InputManifest
from modules.collaboration.models import (
    CollaborationArtifact,
    CollaborationWorkItem,
    CreativeWorkspace,
)
from modules.evidence.facade import revalidate_creative_manifest


async def resource_choices(db, novel_id, kind, offset, query):
    from core.container import get
    from modules.project.facade import require_active_project

    await require_active_project(db, novel_id)
    sources = await get("collaboration.resources")[kind].inventory(db, novel_id)
    sources = [
        item for item in sources if not query or query.casefold() in item.label.casefold()
    ]
    selected = sources[offset : offset + 100]
    return {
        "items": [
            {
                "kind": item.kind,
                "id": str(item.id),
                "label": item.label,
                "chapter_index": item.chapter_index,
                "length": len(item.content.get("content", "")),
            }
            for item in selected
        ],
        "next_offset": offset + 100 if len(sources) > offset + 100 else None,
    }


async def run_view(db, novel_id, run_id):
    run = await require_run(db, novel_id, run_id)
    task = await db.get(AsyncTask, run.task_id) if run.task_id else None
    local = (run.llm_snapshot_json.get("primary") or {}).get("local_agent") or {}
    case = await require_case(db, novel_id, run.case_id)
    stale = case.goal_version != run.manifest_json["goal_version"]
    try:
        await revalidate_creative_manifest(
            db,
            novel_id,
            Grant.model_validate(case.grant_json),
            InputManifest.model_validate(run.manifest_json),
        )
    except DomainError:
        stale = True
    artifacts = (
        await db.scalars(
            select(CollaborationArtifact)
            .where(
                CollaborationArtifact.novel_id == UUID(novel_id),
                CollaborationArtifact.run_id == run.id,
            )
            .order_by(CollaborationArtifact.created_at, CollaborationArtifact.id)
        )
    ).all()
    work = (
        await db.scalars(
            select(CollaborationWorkItem).where(
                CollaborationWorkItem.novel_id == UUID(novel_id),
                CollaborationWorkItem.run_id == run.id,
            )
        )
    ).all()
    budget = run.budget_json or {}
    from infrastructure.llm.agent_runtime import AgentRunBudget
    from infrastructure.tasks.facade import list_task_lifecycle_contracts

    limits = AgentRunBudget.model_validate(budget)
    grant = Grant.model_validate(case.grant_json)
    life = (
        await list_task_lifecycle_contracts(
            db,
            novel_id=novel_id,
            task_ids=[str(run.task_id)] if run.task_id else [],
            max_heartbeat_gap=0,
        )
    ).get(str(run.task_id))
    status = await execution_status(db, run)
    can_resume = bool(
        not local
        and not stale
        and life
        and ("resume" in life.available_actions or status == "partial")
        and status in {"failed", "cancelled", "partial"}
        and not limits.pending_usage
        and limits.remaining_seconds > 0
        and limits.requests + 4 <= grant.run_request_limit
        and case.requests_used + 4 <= grant.request_limit
    )
    return {
        "id": str(run.id),
        "case_id": str(run.case_id),
        "task_id": str(run.task_id) if run.task_id else None,
        "local_agent": {
            "kind": local["kind"],
            "approved": bool((task.meta or {}).get("_local_approved")),
        }
        if local and task
        else None,
        "status": status,
        "can_resume": can_resume,
        "stale": stale,
        "error_code": run.error_code,
        "question_for_author": None
        if stale
        else run.result_json.get("question_for_author"),
        "coverage": run.result_json.get("coverage"),
        "missing_deliverables": run.result_json.get("missing_deliverables", []),
        "work": [
            {"id": str(row.id), "status": row.status, "generation": row.generation}
            for row in work
        ],
        "artifacts": [
            {
                "id": str(row.id),
                "kind": row.kind,
                "workspace_revision_id": str(row.workspace_revision_id)
                if row.workspace_revision_id
                else None,
                "result": row.payload_json,
                "evidence": [
                    {
                        "key": source["kind"] + ":" + source["id"],
                        "label": source["label"],
                        "excerpt": str(
                            source["content"].get("content")
                            or source["content"].get("text")
                            or source["content"].get("excerpt")
                            or source["content"].get("free_text")
                            or ""
                        )[:1200],
                        "url": source["content"].get("url")
                        if source["kind"] == "external_reference"
                        else None,
                        "read_range": source.get("read_range"),
                        "source_hash": source["source_hash"],
                    }
                    for source in row.manifest_json.get("resources", [])
                ],
            }
            for row in artifacts
            if not stale and row.output_hash == content_hash(row.payload_json)
        ],
        "usage": {
            key: budget.get(key)
            for key in (
                "requests",
                "prompt_tokens",
                "completion_tokens",
                "usage_complete",
                "pending_usage",
                "usage_unknown",
            )
        },
    }


async def workspace_list(db, novel_id, case_id):
    await require_case(db, novel_id, case_id)
    rows = (
        await db.scalars(
            select(CreativeWorkspace)
            .where(
                CreativeWorkspace.novel_id == UUID(novel_id),
                CreativeWorkspace.case_id == UUID(str(case_id)),
            )
            .order_by(CreativeWorkspace.created_at)
        )
    ).all()
    return [
        {
            "id": str(row.id),
            "label": row.label,
            "status": row.status,
            "revision_id": str(row.current_revision_id),
        }
        for row in rows
    ]
