from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from pydantic import BaseModel

from evals.cli import _validate_review_model_assignment
from evals.project_executor import ProjectStructuredExecutor
from infrastructure.llm.profiles import ResolvedLLMProfile


class _Output(BaseModel):
    decision: str


class _Client:
    def __init__(self) -> None:
        self.request = None
        self.schema = None
        self.kwargs = None

    async def generate_structured(self, request, schema, **kwargs):
        self.request = request
        self.schema = schema
        self.kwargs = kwargs
        return schema(decision="accepted")


@pytest.mark.asyncio
async def test_project_executor_uses_novel_scoped_project_client() -> None:
    client = _Client()
    opened: dict[str, object] = {}

    @asynccontextmanager
    async def open_client(db, novel_id, *, timeout_override):
        opened.update({"db": db, "novel_id": novel_id, "timeout": timeout_override})
        yield client

    profile = ResolvedLLMProfile(
        provider_id="deepseek",
        label="DeepSeek",
        api_key="secret-never-hashed-directly",
        base_url="https://example.invalid/v1",
        model="deepseek-v4-flash",
        timeout=180,
        max_tokens=4096,
        extra={"thinking": {"type": "disabled"}},
    )
    db = object()
    executor = ProjectStructuredExecutor(
        db,  # type: ignore[arg-type]
        "novel-1",
        profile,
        open_client_fn=open_client,
    )

    result = await executor.generate_structured(
        "审查这个 case",
        _Output,
        step_name="review",
    )

    assert result.decision == "accepted"
    assert opened == {"db": db, "novel_id": "novel-1", "timeout": 300}
    assert client.request.model == "deepseek-v4-flash"
    assert client.request.max_tokens == 8192
    assert client.request.extra == {"thinking": {"type": "disabled"}}
    assert client.schema is _Output
    assert client.kwargs == {"max_fix_attempts": 2, "format_repair_attempts": 1}
    assert executor.meta.model == "deepseek-v4-flash"
    assert len(executor.meta.executor_hash) == 64


@pytest.mark.parametrize(
    ("role", "model"),
    [
        ("reviewer-a", "deepseek-v4-flash"),
        ("scene-reviewer-b", "gpt-5.6-luna"),
        ("scene-adjudicator", "gpt-5.6-terra"),
    ],
)
def test_review_model_assignment_accepts_current_policy(role: str, model: str) -> None:
    _validate_review_model_assignment(role, model)


def test_review_model_assignment_rejects_legacy_policy() -> None:
    with pytest.raises(ValueError, match="requires model deepseek-v4-flash"):
        _validate_review_model_assignment("reviewer-a", "gpt-5.6-terra")


def test_review_model_assignment_rejects_unknown_role() -> None:
    with pytest.raises(ValueError, match="reviewer role must be"):
        _validate_review_model_assignment("custom-reviewer", "gpt-5.6-luna")
