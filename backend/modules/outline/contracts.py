"""
Outline 对外契约

定义其他模块可以安全依赖的大纲模块接口和数据类。
其他模块只能导入 contracts.py 和 facade.py，禁止直接导入 models/repositories/services。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PlotThreadContract:
    """剧情线契约 — 其他模块通过此契约获取剧情线信息"""

    novel_id: str
    """项目 ID"""
    thread_id: str
    """剧情线 ID"""
    name: str
    """剧情线名称"""
    thread_type: str
    """剧情线类型"""
    summary: str | None = None
    """概要"""
    visible_goal: str | None = None
    """对外可见目标"""
    current_stage: str | None = None
    """当前阶段"""
    start_chapter: int | None = None
    """起始章节"""
    planned_payoff_chapter: int | None = None
    """计划收束章节"""
    status: str = "draft"
    """状态"""


@dataclass(frozen=True)
class OutlineArcContract:
    """篇章纲契约 — 其他模块通过此契约获取篇章信息"""

    novel_id: str
    """项目 ID"""
    arc_id: str
    """篇章 ID"""
    title: str
    """篇章标题"""
    arc_index: int | None = None
    """篇章序号"""
    start_chapter: int | None = None
    """起始章节"""
    end_chapter: int | None = None
    """结束章节"""
    arc_goal: str | None = None
    """篇章目标"""
    core_conflict: str | None = None
    """核心冲突"""
    status: str = "draft"
    """状态"""


@dataclass(frozen=True)
class ChapterCardContract:
    """章节卡契约 — 其他模块通过此契约获取章节卡信息"""

    novel_id: str
    """项目 ID"""
    card_id: str
    """章节卡 ID"""
    chapter_index: int
    """章节序号"""
    title: str | None = None
    """章节标题"""
    chapter_goal: str = ""
    """章节目标"""
    main_conflict: str = ""
    """主要冲突"""
    arc_id: str | None = None
    """所属篇章 ID"""
    emotional_point: str | None = None
    """情绪点"""
    plot_function: str | None = None
    """剧情功能"""
    status: str = "draft"
    """状态"""


@dataclass(frozen=True)
class ForeshadowingPlanContract:
    """伏笔计划契约 — 其他模块通过此契约获取伏笔信息"""

    novel_id: str
    """项目 ID"""
    plan_id: str
    """伏笔计划 ID"""
    name: str
    """伏笔名称"""
    summary: str | None = None
    """概要"""
    surface_meaning: str | None = None
    """表面含义"""
    planned_seed_chapter: int | None = None
    """计划埋设章节"""
    planned_payoff_chapter: int | None = None
    """计划收束章节"""
    status: str = "draft"
    """状态"""


@dataclass(frozen=True)
class RevealPlanContract:
    """揭示计划契约 — 其他模块通过此契约获取揭示信息"""

    novel_id: str
    """项目 ID"""
    plan_id: str
    """揭示计划 ID"""
    target_type: str
    """揭示目标类型"""
    target_id: str
    """揭示目标 ID"""
    secret_summary: str = ""
    """秘密概要"""
    status: str = "draft"
    """状态"""


# facade 返回类型（Pydantic schema），供跨模块导入使用
from modules.outline.schemas import (  # noqa: F401
    ChapterCardContext,   # facade.get_chapter_card / create_chapter_cards_from_candidate 返回
    OutlineArcContext,    # facade.get_arc_context 返回
    PlotThreadContext,    # facade.get_active_threads 返回
)
