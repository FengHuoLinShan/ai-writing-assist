"""
Writing 对外契约

定义其他模块可以安全依赖的正文草稿接口和数据类。
其他模块只能导入 contracts.py 和 facade.py，禁止直接导入 models/repositories/services。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

# AO-5 / ADR-0031：正文区间引用是 evidence Context 的引用词汇（所有消费方
# 都是 evidence 编译产物里的 source_ref 锚点），契约定义归 evidence；
# writing.facade 产出该契约，这里保持兼容再出口（writing→evidence 为
# 裁定的合法方向）。
from modules.evidence.source_ref_contracts import (
    ManuscriptScanCursor as ManuscriptScanCursor,
)
from modules.evidence.source_ref_contracts import (
    SourceRangeRefContract as SourceRangeRefContract,
)


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
    knowledge_review: dict[str, Any] | None = None
    editorial_ready_at: datetime | None = None
    editorial_ready_hash: str | None = None
    # 保存触发失效传播时的作者语言公共视图（P2-C C3 透传；含 affected/
    # unknown_scope/receipt_id 最小键集，见 evolution 消费登记契约）。
    # 读路径与未触发失效的保存为 None；additive 字段置尾保持旧位置构造。
    invalidation: dict[str, Any] | None = None


@dataclass(frozen=True)
class WritingProjectStatsContract:
    """项目正文统计契约。只统计每章最新版本。"""

    novel_id: str
    chapter_count: int = 0
    word_count: int = 0


@dataclass(frozen=True)
class WritingAuthorAttentionItemContract:
    """One actionable Writing item for the project-owned read projection."""

    key: str
    title: str
    summary: str
    author_action: Literal["needs_decision", "can_improve"]
    severity: Literal["high", "medium", "low", "info"]
    chapter_index: int
    scene_id: str | None
    item_id: str | None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class ManuscriptSearchHitContract:
    """One literal manuscript hit backed by a SourceRangeRef."""

    source_ref: SourceRangeRefContract
    title: str | None
    snippet: str
    match_start: int
    match_end: int
    match_count: int = 1
    """Number of literal occurrences represented by this hit."""
    source_refs: list[SourceRangeRefContract] = field(default_factory=list)
    """All represented ranges when a result is grouped by chapter."""


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


@dataclass(frozen=True)
class ManuscriptTermHit:
    source_ref: SourceRangeRefContract
    title: str | None
    terms: list[str]
    match_count: int


@dataclass(frozen=True)
class ManuscriptTermScan:
    hits: list[ManuscriptTermHit]
    cursor: ManuscriptScanCursor | None
    scanned_chapters: list[int]
    total_chapters: int
