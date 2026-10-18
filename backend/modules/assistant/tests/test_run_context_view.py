from types import SimpleNamespace
from uuid import uuid4

from modules.assistant.schemas import RunResponse
from modules.assistant.service import AssistantService


def test_run_view_exposes_only_submitted_context_not_private_runtime():
    context = {"page": "world", "focus_label": "对象：沈砚"}
    run = SimpleNamespace(
        id=uuid4(),
        session_id=uuid4(),
        status="completed",
        result_json={},
        request_json={
            "context": context,
            "agent_executor": {"kind": "gateway", "secret": "private"},
        },
        checkpoint_json={"private": True},
        budget_json={},
        error=None,
        task_id=None,
        updated_at=None,
    )
    view = RunResponse.model_validate(AssistantService().view(run))
    assert view.context == context
    assert "private" not in view.model_dump_json()
    run.request_json = {}
    assert AssistantService().view(run)["context"] is None
