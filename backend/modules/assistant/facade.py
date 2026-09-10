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
    mark_changed as mark_changed,
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
