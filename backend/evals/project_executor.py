"""Structured eval execution through a novel's effective project LLM profile."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.profiles import ResolvedLLMProfile
from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
from modules.project.facade import open_project_llm_client

StructuredResultT = TypeVar("StructuredResultT", bound=BaseModel)
OpenClientFn = Callable[..., AbstractAsyncContextManager[Any]]


class ProjectStructuredExecutor:
    """HighQualityEvalLLM-compatible executor using project credentials."""

    reasoning_effort = None
    cache_profile = "project_profile_structured"
    cost_status = "unavailable_project_provider"

    def __init__(
        self,
        db: AsyncSession,
        novel_id: str,
        profile: ResolvedLLMProfile,
        *,
        open_client_fn: OpenClientFn = open_project_llm_client,
    ) -> None:
        if not profile.model:
            raise ValueError("project eval reviewer model is required")
        self.db = db
        self.novel_id = novel_id
        self.profile = profile
        self.model = profile.model
        self._open_client_fn = open_client_fn

    @property
    def meta(self) -> Any:
        summary = self.profile.sanitized_summary()
        executor_hash = hashlib.sha256(
            json.dumps(
                {
                    "transport": "project_profile",
                    "novel_id": self.novel_id,
                    "profile": summary,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        return type(
            "ProjectExecutionMeta",
            (),
            {
                "model": self.model,
                "executor_hash": executor_hash,
                "reasoning_effort": None,
            },
        )()

    async def generate_structured(
        self,
        prompt: str,
        response_model: type[StructuredResultT],
        *,
        step_name: str,
    ) -> StructuredResultT:
        del step_name
        request = LLMCallRequest(
            model=self.model,
            messages=[
                LLMMessage(
                    role="system",
                    content=(
                        "你是评测数据审查员。只输出满足目标 JSON schema 的对象，"
                        "不要 Markdown，不要解释 schema 之外的内容。"
                    ),
                ),
                LLMMessage(role="user", content=prompt),
            ],
            temperature=0.1,
            max_tokens=max(8192, int(self.profile.max_tokens)),
            response_format={"type": "json_object"},
            extra=dict(self.profile.extra),
        )
        async with self._open_client_fn(
            self.db,
            self.novel_id,
            timeout_override=min(1800, max(300, int(self.profile.timeout))),
        ) as client:
            return await client.generate_structured(
                request,
                response_model,
                max_fix_attempts=2,
                format_repair_attempts=1,
            )
