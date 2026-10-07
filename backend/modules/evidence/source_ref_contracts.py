"""正文区间引用契约 — evidence Context 产物里的稳定引用锚点。

AO-5 / ADR-0031：所有消费方（evidence 编译、world 地图、story 场景源、
assistant 工具）引用的都是 evidence 编译产物中的 ``source_ref`` 锚点，
契约定义归 evidence；writing.facade 负责按稿源事实产出该契约，
``writing.contracts`` 保持兼容再出口（writing→evidence 为裁定的合法方向）。

本文件是零内部依赖的叶子模块：evidence 包初始化链
（``evidence/__init__ → contracts → compilation/*``）的任何位置都可以
安全导入，不触发部分初始化循环。
"""

from __future__ import annotations

from dataclasses import dataclass


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
class ManuscriptScanCursor:
    """流式正文扫描的续读位置。"""

    chapter_position: int = 0
    start_offset: int = 0
