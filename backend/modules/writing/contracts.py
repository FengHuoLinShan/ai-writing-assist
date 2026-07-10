"""
Writing 对外契约

定义其他模块可以安全依赖的正文草稿接口和数据类。
其他模块只能导入 contracts.py 和 facade.py，禁止直接导入 models/repositories/services。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class WritingDraftContract:
    """正文草稿契约 — 其他模块通过此契约获取草稿信息"""

    novel_id: str
    chapter_index: int
    id: str | None = None
    title: str | None = None
    content: str | None = None
    content_hash: str = ""
    version_number: int = 1
    status: str = "draft"
    conflict_check_snapshot_json: dict | None = None
    provenance_json: dict[str, Any] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # Additive author-facing projection fields stay at the end so positional
    # construction used by older consumers keeps its original field order.
    display_state: str = "active"
    source: str = "manual"
    attention_reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WritingProjectStatsContract:
    """项目正文统计契约。只统计每章最新版本。"""

    novel_id: str
    chapter_count: int = 0
    word_count: int = 0


@dataclass(frozen=True)
class SourceRangeRefContract:
    """Stable reference to one range in a concrete writing draft version."""

    draft_id: str
    chapter_index: int
    version_number: int
    content_mode: str
    start_offset: int
    end_offset: int
    source_hash: str
    range_hash: str


@dataclass(frozen=True)
class ManuscriptSearchHitContract:
    """One literal manuscript hit backed by a SourceRangeRef."""

    source_ref: SourceRangeRefContract
    title: str | None
    snippet: str
    match_start: int
    match_end: int


@dataclass(frozen=True)
class ManuscriptReadContract:
    """Validated original-text read with paragraph context."""

    source_ref: SourceRangeRefContract
    title: str | None
    text: str
    highlight_start: int
    highlight_end: int
    paragraph_before: int
    paragraph_after: int
