"""Stable, read-only plot-thread seam for context consumers."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from modules.story.outline_state.contracts import PlotThreadContract
from modules.story.outline_state.services import PlotThreadService


def _contract(item) -> PlotThreadContract:
    return PlotThreadContract(
        id=str(item.id),
        novel_id=str(item.novel_id),
        name=item.name,
        thread_type=item.thread_type,
        summary=item.summary,
        visible_goal=item.visible_goal,
        hidden_truth=item.hidden_truth,
        start_chapter=item.start_chapter,
        planned_payoff_chapter=item.planned_payoff_chapter,
        current_stage=item.current_stage,
        related_character_ids=list(item.related_character_ids or []),
        related_entity_ids=list(item.related_entity_ids or []),
        reader_known_state=item.reader_known_state,
        author_known_state=item.author_known_state,
        status=item.status,
    )


async def get_plot_threads_for_context(
    db: AsyncSession,
    novel_id: str,
    *,
    thread_ids: list[str] | None = None,
    chapter_index: int | None = None,
) -> list[PlotThreadContract]:
    """Load explicit threads first, then active threads for a real chapter anchor."""
    service = PlotThreadService()
    items: list[PlotThreadContract] = []
    seen: set[str] = set()
    for thread_id in dict.fromkeys(thread_ids or []):
        thread = await service.get(db, thread_id, novel_id=novel_id)
        contract = _contract(thread)
        if contract.id not in seen:
            seen.add(contract.id)
            items.append(contract)
    if chapter_index is not None:
        for contract in await service.get_active(db, novel_id, chapter_index):
            if contract.id not in seen:
                seen.add(contract.id)
                items.append(contract)
    return items
