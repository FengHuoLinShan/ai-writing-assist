"""Composition registry for read-only notice providers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.assistant.editorial_notice_source import NOTICE_SOURCE_SPEC as _EDITORIAL
from modules.assistant.forecast_notice_source import NOTICE_SOURCE_SPEC as _FORECAST
from modules.assistant.notice_sources import NOTICE_SOURCE_SPEC as _ASSISTANT
from modules.evolution.notice_sources import NOTICE_SOURCE_SPEC as _MAP_SOURCE
from modules.story.notice_sources import NOTICE_SOURCE_SPEC as _STORY
from modules.writing.notice_sources import NOTICE_SOURCE_SPECS as _WRITING

NoticeReader = Callable[[AsyncSession, str, dict[str, object]], Awaitable[list[dict]]]
NoticeDecider = Callable[
    [AsyncSession, str, dict[str, object], str, Any], Awaitable[dict[str, Any]]
]


@dataclass(frozen=True)
class NoticeSourceSpec:
    source_id: str
    label: str
    list_notices: NoticeReader
    decide: NoticeDecider | None = None
    timeout_seconds: float = 2.0


def _materialize(spec: dict[str, Any]) -> NoticeSourceSpec:
    if set(spec) - {"source_id", "label", "list_notices", "decide", "timeout_seconds"}:
        raise ValueError("提醒来源声明包含未知字段")
    source = NoticeSourceSpec(**spec)
    if not source.source_id or not source.label or not callable(source.list_notices):
        raise ValueError("提醒来源声明不完整")
    if not 0.05 <= source.timeout_seconds <= 10:
        raise ValueError("提醒来源超时必须在 0.05 到 10 秒之间")
    return source


_specs = [_ASSISTANT, _EDITORIAL, _FORECAST, _STORY, *_WRITING, _MAP_SOURCE]
notice_sources: dict[str, NoticeSourceSpec] = {}
for _raw in _specs:
    _source = _materialize(_raw)
    if _source.source_id in notice_sources:
        raise ValueError(f"提醒来源重复注册：{_source.source_id}")
    notice_sources[_source.source_id] = _source
