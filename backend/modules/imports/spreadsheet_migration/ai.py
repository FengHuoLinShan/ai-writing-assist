"""AI 整理对外接口（计划 §3.7）— L5 车道实现任务与整理逻辑。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from modules.imports.models import ImportMigrationSession


@dataclass(frozen=True)
class AiEstimate:
    """一次 AI 整理的成本预估。"""

    rows: int = 0
    chars: int = 0
    packets: int = 0
    requests: int = 0


@dataclass(frozen=True)
class TaskRef:
    """提交 AI 任务后的引用。"""

    task_id: str
    status: str  # queued / running / done / failed
    reused: bool = False


@dataclass(frozen=True)
class AiPlanningItem:
    """一条可并入 planning 的 AI 产出条目（已通过审查且作者接受）。"""

    proposal_ref: str
    operation: str  # outline / cleanup
    sheet_key: str
    row_refs: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AiPlanningInput:
    """planning 阶段可合并的全部 AI 条目。"""

    items: list[AiPlanningItem] = field(default_factory=list)


__all__ = [
    "AiEstimate",
    "AiPlanningInput",
    "AiPlanningItem",
    "TaskRef",
    "ai_items_for_planning",
    "estimate_ai_run",
    "submit_ai_run",
]


def estimate_ai_run(
    rows_by_sheet: dict[str, list[list[str]]],
    mapping: dict[str, Any],
    scope: dict[str, Any],
) -> AiEstimate:
    """估算 AI 整理的行数、字符量、分包数和请求数。"""
    raise NotImplementedError("L5 车道实现")


async def submit_ai_run(
    db: AsyncSession,
    *,
    novel_id: str,
    session: ImportMigrationSession,
    scope: dict[str, Any],
    operation_id: str,
) -> TaskRef:
    """提交 spreadsheet_migration_ai 任务；同 scope 复用进行中的任务。"""
    raise NotImplementedError("L5 车道实现")


def ai_items_for_planning(
    ai_result_json: dict[str, Any] | None,
    decisions: dict[str, Any],
) -> AiPlanningInput:
    """从 AI 结果中筛出已通过审查且作者接受的条目，供 planning 合并。"""
    raise NotImplementedError("L5 车道实现")
