"""Pure persisted-turn evidence; never reconcile a task or replay a tool."""

from copy import deepcopy
from uuid import UUID

from sqlalchemy import select

from core.errors import NotFoundError
from modules.assistant.models import AssistantActionBatch, AssistantRun
from modules.project.facade import get_any_project_context, require_active_project


async def read_map_spatial_evaluation_turn(db, novel_id, run_id):
    with db.no_autoflush:
        await require_active_project(db, novel_id)
        project = await get_any_project_context(db, novel_id)
        run = await db.scalar(
            select(AssistantRun).where(
                AssistantRun.novel_id == UUID(str(novel_id)),
                AssistantRun.id == UUID(str(run_id)),
            )
        )
        if (
            run is None
            or project is None
            or project.project_kind != "author"
            or str(run.owner_id) != str(project.owner_id)
            or run.mode != "author"
        ):
            raise NotFoundError("没有找到本作品的作者助手运行")
        batch = await db.scalar(
            select(AssistantActionBatch).where(
                AssistantActionBatch.novel_id == run.novel_id,
                AssistantActionBatch.run_id == run.id,
            )
        )
        request, checkpoint = run.request_json or {}, run.checkpoint_json or {}
        context = request.get("context") or {}
        context = {
            key: deepcopy(context.get(key))
            for key in (
                "page",
                "chapter_index",
                "scene_id",
                "target",
                "draft_id",
                "source_hash",
                "scope",
                "excluded_targets",
                "context_confirmation_id",
                "context_confirmation_action",
            )
        }
        result = run.result_json or {}
        if isinstance(context["target"], dict):
            context["target"] = {
                key: context["target"][key]
                for key in ("type", "id", "target_type", "target_id")
                if key in context["target"]
            }
        return {
            "schema_version": 1,
            "novel_id": str(run.novel_id),
            "run_id": str(run.id),
            "operation_id": str(run.operation_id) if run.operation_id else None,
            "status": run.status,
            "task_id": str(run.task_id) if run.task_id else None,
            "request_hash": run.request_hash,
            "request": {"message": request.get("message"), "context": context},
            "scene_ids": [context["scene_id"]] if context["scene_id"] else [],
            "scene_scope_status": "known" if context["scene_id"] else "unknown",
            "result": {
                key: deepcopy(result.get(key))
                for key in (
                    "answer",
                    "actions",
                    "findings",
                    "omissions",
                    "sources",
                    "knowledge_scope_receipt",
                    "knowledge_review",
                    "batch",
                )
            },
            "answer_status": "known"
            if run.status in {"completed", "waiting_approval"} and result.get("answer")
            else "unknown",
            "events": deepcopy(checkpoint.get("events")),
            "evidence_refs": {
                key: deepcopy(value)
                for key, value in (checkpoint.get("evidence_refs") or {}).items()
                if value.get("map_spatial_guard") or value.get("spatial_advisory")
            },
            # Completed turns discard model history. A catalog or an answer is
            # not proof that a read tool was invoked.
            "tool_invocations": None,
            "tool_invocations_status": "unknown",
            "action_batch": {
                "id": str(batch.id),
                "status": batch.status,
                "fingerprint": batch.fingerprint,
                "actions": deepcopy(batch.actions_json),
                "results": deepcopy(batch.results_json),
                "authorization": {
                    key: deepcopy((batch.authorization_json or {}).get(key))
                    for key in ("selected", "confirmed_at", "fingerprint", "review_after")
                },
            }
            if batch
            else None,
            "usage": {
                key: value
                for key, value in (run.budget_json or {}).items()
                if isinstance(value, (int, float)) and not isinstance(value, bool)
            }
            or None,
            "truncated": False,
            "omitted_count": 0,
            "human_validated": False,
        }
