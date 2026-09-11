"""Retry structured world outputs that cite unknown frozen-source keys."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Iterable

from infrastructure.llm.client import LLMClient
from infrastructure.llm.errors import LLMInvalidResponseError
from infrastructure.llm.schemas import LLMCallRequest, LLMMessage


async def run_structured_with_known_keys[OutputT](
    client: LLMClient,
    request: LLMCallRequest,
    *,
    generate: Callable[[], Awaitable[OutputT]],
    known_keys: set[str],
    keys_of: Callable[[OutputT], Iterable[str]],
    repair_note: str,
    error_message: str,
) -> OutputT:
    for attempt in range(2):
        generated = await generate()
        unknown = sorted({key for key in keys_of(generated) if key not in known_keys})
        if not unknown:
            return generated
        if attempt == 0:
            request.messages.append(
                LLMMessage(
                    role="user",
                    content=repair_note + json.dumps(unknown, ensure_ascii=False),
                )
            )
    raise LLMInvalidResponseError(
        error_message,
        provider=str(client.provider),
        model=request.model,
    )
