"""Bounded, single-host work DAG; the host owns authority and durable commits."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, Literal

from anyio import CancelScope
from pydantic import BaseModel, ConfigDict, Field


@asynccontextmanager
async def checkpoint_transaction(lock, db):
    """Return a shared host session idle even when a tool cancel scope unwinds.

    Only DB work is shielded. The host commit still checks the task lease and
    rejects a cancelled/replaced writer; provider waits stay cancellable.
    """
    async with lock:
        with CancelScope(shield=True):
            try:
                yield
            except BaseException:
                await db.rollback()
                raise


class WorkItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    role: str = Field(min_length=1, max_length=64)
    depends_on: list[str] = Field(default_factory=list, max_length=12)
    input_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: Literal[
        "pending", "running", "succeeded", "failed", "blocked", "cancelled"
    ] = "pending"
    attempt: int = Field(default=0, ge=0)
    output: dict[str, Any] | None = None
    output_hash: str | None = None
    stop_reason: str | None = None


def content_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
        ).encode()
    ).hexdigest()


class MemberFailureError(Exception):
    """A safe, local failure. All other errors stop the whole host."""

    def __init__(
        self,
        reason: Literal[
            "budget", "provider", "invalid_output", "content_filter", "unavailable"
        ],
    ):
        self.reason = reason
        super().__init__(reason)


async def run_work_items(
    items: list[WorkItem],
    *,
    roles: set[str],
    execute: Callable[[WorkItem], Awaitable[dict]],
    checkpoint: Callable[[list[dict]], Awaitable[None]],
    concurrency: int = 3,
    retry_failed: bool = False,
) -> list[WorkItem]:
    """Only publish completed outputs after the host has durably saved them.

    No tool/history sharing or automatic retries. Recovery reuses verified receipts;
    a host lease failure cancels siblings. Only explicit MemberFailureError is local.
    """
    if not 1 <= concurrency <= 3 or not 1 <= len(items) <= 12:
        raise ValueError("Collaboration exceeds its frozen size")
    by_key = {item.key: item for item in items}
    if len(by_key) != len(items):
        raise ValueError("Duplicate work key")
    visiting, visited = set(), set()

    def visit(key):
        if key in visiting:
            raise ValueError("Cyclic work dependencies")
        if key in visited:
            return
        visiting.add(key)
        item = by_key[key]
        if item.role not in roles or len(set(item.depends_on)) != len(item.depends_on):
            raise ValueError("Unregistered role or repeated dependency")
        for dependency in item.depends_on:
            if dependency not in by_key:
                raise ValueError("Dependency belongs to another run")
            visit(dependency)
        visiting.remove(key)
        visited.add(key)

    for item in items:
        visit(item.key)
        if item.status == "succeeded":
            if item.output is None or content_hash(item.output) != item.output_hash:
                raise ValueError("Completed work receipt is invalid")
        elif item.status == "running" or (
            retry_failed and item.status in {"failed", "blocked"}
        ):
            item.status, item.stop_reason = "pending", None
            item.output, item.output_hash = None, None

    lock = asyncio.Lock()

    async def save():
        payload = [item.model_dump(mode="json") for item in items]
        if len(json.dumps(payload, ensure_ascii=False).encode()) > 1024 * 1024:
            raise ValueError("Collaboration checkpoint exceeds 1 MiB")
        await checkpoint(payload)

    async def one(item):
        async with lock:
            item.status = "running"
            item.attempt += 1
            await save()
        try:
            output = await execute(item.model_copy(deep=True))
        except MemberFailureError as error:
            async with lock:
                item.status, item.stop_reason = "failed", error.reason
                await save()
        else:
            async with lock:
                item.output, item.output_hash = output, content_hash(output)
                item.status = "succeeded"
                await save()

    while pending := [item for item in items if item.status == "pending"]:
        blocked = False
        for item in pending:
            if any(
                by_key[key].status in {"failed", "blocked", "cancelled"}
                for key in item.depends_on
            ):
                item.status, item.stop_reason = "blocked", "dependency"
                blocked = True
        ready = [
            item
            for item in pending
            if item.status == "pending"
            and all(by_key[key].status == "succeeded" for key in item.depends_on)
        ]
        await save()
        if not ready:
            if blocked:
                continue
            raise ValueError("Pending work has no runnable or terminal dependency path")
        tasks = [asyncio.create_task(one(item)) for item in ready[:concurrency]]
        try:
            await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
    return items
