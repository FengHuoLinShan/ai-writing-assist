"""Stable discussion service used by the World compatibility entry."""

from modules.assistant.operation_scope import (
    require_operation_targets as require_operation_targets,
)
from modules.assistant.proactive import (
    decide_notice as decide_notice,
)
from modules.assistant.proactive import (
    execute_review_task as execute_review_task,
)
from modules.assistant.proactive import (
    list_notices as list_notices,
)
from modules.assistant.proactive import (
    mark_changed as _mark_proactive_changed,
)
from modules.assistant.proactive import (
    policy as policy,
)
from modules.assistant.proactive import (
    recheck_notice as recheck_notice,
)
from modules.assistant.proactive import (
    save_policy as save_policy,
)
from modules.assistant.proactive import (
    schedule_due as schedule_due,
)
from modules.assistant.sessions import AssistantSessionService as AssistantSessionService


async def mark_editorial_ready(db, novel_id, chapter_index, draft_id, content_hash):
    from modules.assistant.editorial_queue import mark_ready

    await mark_ready(db, novel_id, chapter_index, draft_id, content_hash)


async def mark_changed(db, novel_id, asset_type, asset_id, *, related_scene_ids=None):
    from modules.assistant.editorial import mark_reference_changed

    await mark_reference_changed(db, novel_id, asset_type)
    await _mark_proactive_changed(
        db, novel_id, asset_type, asset_id, related_scene_ids=related_scene_ids
    )


async def submit_cocreation(db, data):
    from modules.assistant.service import AssistantService

    return await AssistantService().submit_cocreation(db, data)


def project_assistant_enabled():
    from modules.assistant.service import get_settings

    return get_settings().assistant_enabled


async def inspect_discussion(db, novel_id, session_id):
    session = await AssistantSessionService()._require_session(db, novel_id, session_id)
    return {
        "title": session.title,
        "source": {
            "kind": session.source_kind,
            "id": str(session.source_id) if session.source_id else None,
        },
        "checkpoint_id": str(session.current_checkpoint_id)
        if session.current_checkpoint_id
        else None,
        "checkpoint_round": session.checkpoint_round,
        "checkpoint_depth": session.checkpoint_depth,
        "workflow_preset": session.workflow_preset,
        "status": session.status,
    }


async def run_discussion_scope(db, novel_id, run_id, owner_id, *, lock=False):
    from modules.assistant.service import AssistantService

    return await AssistantService().discussion_scope(
        db, novel_id, run_id, owner_id, lock=lock
    )


async def forecast_feed(db, novel_id, data, *, persona="author"):
    from modules.assistant.forecast.service import feed

    return await feed(db, novel_id, data, persona=persona)


async def forecast_submit(db, novel_id, data, *, persona="author"):
    from modules.assistant.forecast.runtime import submit

    return await submit(db, novel_id, data, persona=persona)


async def forecast_run(db, novel_id, run_id, *, persona="author"):
    from modules.assistant.forecast.runtime import view

    return await view(db, novel_id, run_id, persona=persona)


async def forecast_cancel(db, novel_id, run_id, *, persona="author"):
    from modules.assistant.forecast.runtime import cancel

    return await cancel(db, novel_id, run_id, persona=persona)


async def forecast_decide(db, novel_id, candidate_id, data, *, persona="author"):
    from modules.assistant.forecast.service import decide

    return await decide(db, novel_id, candidate_id, data, persona=persona)


async def forecast_candidate(db, novel_id, candidate_id, *, persona="author"):
    from core.errors import ConflictError
    from modules.assistant.forecast.ranking import hidden_by_decision
    from modules.assistant.forecast.service import _notice, require_candidate

    candidate, ctx = await require_candidate(db, novel_id, candidate_id, persona=persona)
    if hidden_by_decision(await _notice(db, candidate)):
        raise ConflictError("该建议已被暂缓或拒绝，请先重新留意")
    return candidate, ctx


async def forecast_resume(db, novel_id, run_id, *, persona="author"):
    from modules.assistant.forecast.runtime import resume

    return await resume(db, novel_id, run_id, persona=persona)


async def lock_background_slot(db, novel_id):
    from modules.assistant.proactive import _watch
    from modules.project.facade import require_active_project

    await require_active_project(db, novel_id)
    return await _watch(db, novel_id, lock=True)


async def register_creative_watch(db, novel_id, case_id, active):
    from modules.assistant.creative_queue import register

    return await register(db, novel_id, case_id, active)


async def project_creative_run(db, novel_id, run_id, **values):
    from modules.assistant.creative_queue import project_run

    return await project_run(db, novel_id, run_id, **values)
