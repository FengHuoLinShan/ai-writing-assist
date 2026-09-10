"""Queue entry for the domain-owned assistant run."""

from infrastructure.tasks.registry import task_handler
from modules.assistant.service import AssistantService


@task_handler("assistant_turn", recovery_policy="manual_resume")
async def handle_assistant_turn(db, task):
    return await AssistantService().execute(db, task)
