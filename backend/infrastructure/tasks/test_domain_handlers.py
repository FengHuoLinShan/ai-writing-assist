from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


class _TaskStub:
    def __init__(self, meta: dict | None = None) -> None:
        self.meta = meta or {}
        self.progress_updates: list[float] = []

    def update_progress(self, progress: float) -> None:
        self.progress_updates.append(progress)


def test_world_bible_projection_refresh_handler_is_registered() -> None:
    import modules.world.tasks  # noqa: F401
    from infrastructure.tasks.registry import get_registry

    handler = get_registry().get_handler("world_bible_projection_refresh")

    assert handler is not None
    assert callable(handler)


def test_world_bible_synopsis_refresh_handler_is_registered() -> None:
    import modules.world.tasks  # noqa: F401
    from infrastructure.tasks.registry import get_registry

    handler = get_registry().get_handler("world_bible_synopsis_refresh")

    assert handler is not None
    assert callable(handler)


def test_removed_outline_chapter_scene_extract_handler_is_not_registered() -> None:
    import modules.outline.tasks  # noqa: F401
    from infrastructure.tasks.registry import get_registry

    handler = get_registry().get_handler("outline_chapter_scenes_extract")

    assert handler is None


def test_removed_world_entity_extraction_handler_is_not_registered() -> None:
    import modules.world.tasks  # noqa: F401
    from infrastructure.tasks.registry import get_registry

    handler = get_registry().get_handler("world_entity_extraction")

    assert handler is None


@pytest.mark.asyncio
async def test_plot_structure_generate_fails_closed_as_retired() -> None:
    from modules.outline.tasks import handle_plot_structure_generate

    task = _TaskStub(
        {
            "novel_id": "11111111-1111-1111-1111-111111111111",
            "start_chapter": 1,
            "end_chapter": 3,
            "llm_execution_snapshot": {"profile_hash": "frozen"},
        }
    )
    db = AsyncMock()
    db.task_checkpoint_enabled = True

    result = await handle_plot_structure_generate(db, task)

    assert task.progress_updates == [1.0]
    assert result["status"] == "unsupported"
    assert result["task_type"] == "plot_structure_generate"
    assert "已停用" in result["message"]


@pytest.mark.asyncio
async def test_chapter_card_extraction_returns_unsupported_result() -> None:
    import modules.outline.tasks  # noqa: F401
    from infrastructure.tasks.registry import get_registry

    handler = get_registry().get_handler("chapter_card_extraction")
    assert handler is not None

    task = _TaskStub(
        {
            "novel_id": "11111111-1111-1111-1111-111111111111",
            "start_chapter": 1,
            "end_chapter": 3,
        }
    )

    result = await handler(AsyncMock(), task)

    assert result["status"] == "unsupported"
    assert result["task_type"] == "chapter_card_extraction"
    assert result["novel_id"] == "11111111-1111-1111-1111-111111111111"
    assert result["start_chapter"] == 1
    assert result["end_chapter"] == 3
    assert "已停用" in result["message"]
    assert task.progress_updates == [0.1, 1.0]


@pytest.mark.asyncio
async def test_chapter_scene_generate_returns_unsupported_result() -> None:
    import modules.outline.tasks  # noqa: F401
    from infrastructure.tasks.registry import get_registry

    handler = get_registry().get_handler("chapter_scene_generate")
    assert handler is not None

    task = _TaskStub(
        {
            "novel_id": "11111111-1111-1111-1111-111111111111",
            "start_chapter": 2,
            "end_chapter": 4,
        }
    )

    result = await handler(AsyncMock(), task)

    assert result["status"] == "unsupported"
    assert result["task_type"] == "chapter_scene_generate"
    assert result["start_chapter"] == 2
    assert result["end_chapter"] == 4
    assert "已停用" in result["message"]
    assert task.progress_updates == [0.1, 1.0]


@pytest.mark.asyncio
async def test_chapter_card_extraction_requires_novel_id() -> None:
    from modules.outline.tasks import handle_chapter_card_extraction

    with pytest.raises(ValueError, match="novel_id is required"):
        await handle_chapter_card_extraction(AsyncMock(), _TaskStub())
