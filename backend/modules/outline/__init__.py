"""
modules/outline — 结构化剧情模块

系统核心创作模块，把事实层中的世界对象、人物、地理历史、记忆和时间线
转化为可执行的剧情结构（剧情线、篇章纲、章节卡、伏笔计划、揭示计划）。
"""

from __future__ import annotations

from modules.outline.contracts import (
    ChapterCardContract,
    ForeshadowingPlanContract,
    OutlineArcContract,
    PlotThreadContract,
    RevealPlanContract,
)
from modules.outline.facade import (
    create_arc,
    create_chapter_cards_from_candidate,
    create_thread,
    get_active_threads,
    get_arc_context,
    get_chapter_card,
    list_arc_summaries,
    list_thread_summaries,
    update_arc,
    update_thread,
)
from modules.outline.models import (
    ChapterCard,
    ForeshadowingPlan,
    OutlineArc,
    PlotThread,
    RevealPlan,
)
from modules.outline.schemas import (
    ChapterCardContext,
    ChapterCardCreate,
    ChapterCardListResponse,
    ChapterCardResponse,
    ChapterCardUpdate,
    ForeshadowingPlanCreate,
    ForeshadowingPlanListResponse,
    ForeshadowingPlanResponse,
    ForeshadowingPlanUpdate,
    OutlineArcContext,
    OutlineArcCreate,
    OutlineArcListResponse,
    OutlineArcResponse,
    OutlineArcUpdate,
    PlotThreadContext,
    PlotThreadCreate,
    PlotThreadListResponse,
    PlotThreadResponse,
    PlotThreadUpdate,
    RevealPlanCreate,
    RevealPlanListResponse,
    RevealPlanResponse,
    RevealPlanUpdate,
)
from modules.outline.services import (
    ChapterCardService,
    ForeshadowingPlanService,
    OutlineArcService,
    PlotThreadService,
    RevealPlanService,
)

__all__ = [
    # ORM Models
    "PlotThread",
    "OutlineArc",
    "ChapterCard",
    "ForeshadowingPlan",
    "RevealPlan",
    # Pydantic Schemas
    "PlotThreadCreate",
    "PlotThreadUpdate",
    "PlotThreadResponse",
    "PlotThreadListResponse",
    "PlotThreadContext",
    "OutlineArcCreate",
    "OutlineArcUpdate",
    "OutlineArcResponse",
    "OutlineArcListResponse",
    "OutlineArcContext",
    "ChapterCardCreate",
    "ChapterCardUpdate",
    "ChapterCardResponse",
    "ChapterCardListResponse",
    "ChapterCardContext",
    "ForeshadowingPlanCreate",
    "ForeshadowingPlanUpdate",
    "ForeshadowingPlanResponse",
    "ForeshadowingPlanListResponse",
    "RevealPlanCreate",
    "RevealPlanUpdate",
    "RevealPlanResponse",
    "RevealPlanListResponse",
    # Contracts
    "PlotThreadContract",
    "OutlineArcContract",
    "ChapterCardContract",
    "ForeshadowingPlanContract",
    "RevealPlanContract",
    # Services
    "PlotThreadService",
    "OutlineArcService",
    "ChapterCardService",
    "ForeshadowingPlanService",
    "RevealPlanService",
    # Facade
    "get_chapter_card",
    "get_active_threads",
    "get_arc_context",
    "create_chapter_cards_from_candidate",
    "create_thread",
    "update_thread",
    "create_arc",
    "update_arc",
    "list_thread_summaries",
    "list_arc_summaries",
]
