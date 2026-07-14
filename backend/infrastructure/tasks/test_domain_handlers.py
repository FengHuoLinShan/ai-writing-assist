from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class _TaskStub:
    def __init__(self, meta: dict | None = None) -> None:
        self.meta = meta or {}
        self.progress_updates: list[float] = []

    def update_progress(self, progress: float) -> None:
        self.progress_updates.append(progress)


@pytest.mark.asyncio
async def test_world_entity_extraction_reports_coarse_progress() -> None:
    from modules.world.tasks import handle_world_entity_extraction

    task = _TaskStub(
        {
            "novel_id": "11111111-1111-1111-1111-111111111111",
            "start_chapter": 1,
            "end_chapter": 3,
        }
    )
    result = MagicMock(
        total_chapters=3,
        total_created=2,
        total_skipped=1,
        failed_chapters=[],
        items=[],
    )

    with patch("modules.world.tasks.EntityExtractionService") as service_cls:
        service = service_cls.return_value
        service.extract_entities_from_chapters = AsyncMock(return_value=result)

        await handle_world_entity_extraction(AsyncMock(), task)

    assert task.progress_updates == [0.1, 0.85, 0.95, 1.0]


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


@pytest.mark.asyncio
async def test_plot_structure_generate_reports_coarse_progress() -> None:
    from modules.outline.tasks import handle_plot_structure_generate

    task = _TaskStub(
        {
            "novel_id": "11111111-1111-1111-1111-111111111111",
            "start_chapter": 1,
            "end_chapter": 3,
        }
    )

    with patch("modules.outline.generator.PlotStructureGenerator") as generator_cls:
        generator = generator_cls.return_value
        generator.generate = AsyncMock(
            return_value={
                "total_threads": 1,
                "total_arcs": 1,
                "total_scenes": 0,
            }
        )

        await handle_plot_structure_generate(AsyncMock(), task)

    assert task.progress_updates == [0.1, 0.85, 0.95]
    assert generator.generate.await_args.kwargs["persist"] is False


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
    assert "not implemented" in result["message"]
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
    assert "not implemented" in result["message"]
    assert task.progress_updates == [0.1, 1.0]


@pytest.mark.asyncio
async def test_chapter_card_extraction_requires_novel_id() -> None:
    from modules.outline.tasks import handle_chapter_card_extraction

    with pytest.raises(ValueError, match="novel_id is required"):
        await handle_chapter_card_extraction(AsyncMock(), _TaskStub())
