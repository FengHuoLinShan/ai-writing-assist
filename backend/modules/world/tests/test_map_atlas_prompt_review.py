from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from core.errors import ConflictError
from core.errors import ValidationError as DomainValidationError
from modules.world.map_atlas_models import MapAtlasNode, MapAtlasPage, MapAtlasRun
from modules.world.map_atlas_schemas import (
    MapAtlasConfirmPromptsRequest,
    MapAtlasNodeUpdate,
    MapAtlasPromptConfirmation,
    MapAtlasPromptUpdate,
)
from modules.world.map_atlas_service import MapAtlasService
from modules.world.map_atlas_storage import MapAtlasStorage


async def _prompt_run(db, novel_id: str, *, pages: int = 1):
    run = MapAtlasRun(
        novel_id=uuid.UUID(novel_id),
        run_kind="initial",
        status="prompt_review",
        review_image_prompts=True,
        atlas_plan={"nodes": [{}]},
        planned_page_count=pages,
    )
    db.add(run)
    await db.flush()
    result = []
    for index in range(pages):
        node = MapAtlasNode(
            novel_id=run.novel_id,
            created_by_run_id=run.id,
            semantic_key=f"manual:{uuid.uuid4()}",
            title=f"node-{index}",
            level="region",
        )
        db.add(node)
        await db.flush()
        page = MapAtlasPage(
            novel_id=run.novel_id,
            run_id=run.id,
            node_id=node.id,
            title=node.title,
            visual_brief="brief",
            prompt=f"prompt-{index}",
        )
        db.add(page)
        result.append(page)
    await db.flush()
    return run, result


@pytest.mark.asyncio
async def test_all_external_confirmation_makes_no_image_connection(
    db_session, test_project_id
) -> None:
    run, pages = await _prompt_run(db_session, test_project_id, pages=2)
    service = MapAtlasService()
    for page in pages:
        await service.update_prompt(
            db_session,
            test_project_id,
            str(page.id),
            MapAtlasPromptUpdate(
                prompt=page.prompt,
                generation_choice="external",
                expected_updated_at=page.updated_at,
            ),
        )
    request = MapAtlasConfirmPromptsRequest(
        pages=[
            MapAtlasPromptConfirmation(
                page_id=page.id, expected_updated_at=page.updated_at
            )
            for page in pages
        ]
    )
    with patch(
        "modules.world.map_atlas_service.build_project_image_execution_snapshot",
        autospec=True,
    ) as image_snapshot:
        response = await service.confirm_prompts(
            db_session, test_project_id, str(run.id), request
        )

    image_snapshot.assert_not_called()
    assert response["status"] == "review_ready"
    assert response["completed_page_count"] == 2
    assert {page.generation_status for page in pages} == {"prompt_only"}


@pytest.mark.asyncio
async def test_prompt_cas_and_freeze(db_session, test_project_id) -> None:
    run, (page,) = await _prompt_run(db_session, test_project_id)
    stale = page.updated_at
    service = MapAtlasService()
    await service.update_prompt(
        db_session,
        test_project_id,
        str(page.id),
        MapAtlasPromptUpdate(
            prompt="new prompt",
            generation_choice="external",
            expected_updated_at=stale,
        ),
    )
    with pytest.raises(ConflictError, match="别处更新"):
        await service.update_prompt(
            db_session,
            test_project_id,
            str(page.id),
            MapAtlasPromptUpdate(
                prompt="stale",
                generation_choice="external",
                expected_updated_at=stale,
            ),
        )
    await service.confirm_prompts(
        db_session,
        test_project_id,
        str(run.id),
        MapAtlasConfirmPromptsRequest(
            pages=[
                MapAtlasPromptConfirmation(
                    page_id=page.id, expected_updated_at=page.updated_at
                )
            ]
        ),
    )
    with pytest.raises(ConflictError, match="已锁定"):
        await service.update_prompt(
            db_session,
            test_project_id,
            str(page.id),
            MapAtlasPromptUpdate(
                prompt="too late",
                generation_choice="external",
                expected_updated_at=page.updated_at,
            ),
        )


@pytest.mark.asyncio
async def test_prompt_review_can_pause_and_resume_without_enqueue(
    db_session, test_project_id
) -> None:
    run, _pages = await _prompt_run(db_session, test_project_id)
    service = MapAtlasService()
    stopped = await service.stop_run(db_session, test_project_id, str(run.id))
    assert stopped["stop_requested"] is True
    assert run.status == "paused"
    with patch.object(service, "_enqueue_run_task", autospec=True) as enqueue:
        resumed = await service.resume_run(
            db_session,
            test_project_id,
            str(run.id),
            confirm_possible_duplicate_charge=False,
        )
    enqueue.assert_not_called()
    assert resumed["status"] == "prompt_review"


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [b"GIF89a" + b"\0" * 100, b"\xff\xd8broken"])
async def test_upload_validation_does_not_reach_storage(
    db_session, test_project_id, payload
) -> None:
    storage = MagicMock(spec=MapAtlasStorage)
    service = MapAtlasService(storage=storage)

    with pytest.raises(DomainValidationError):
        await service.upload_page(
            db_session,
            test_project_id,
            payload=payload,
            title="map",
            level="region",
            parent_id=None,
            node_id=None,
        )

    storage.put_png.assert_not_called()


def test_node_update_normalizes_title() -> None:
    timestamp = "2026-08-13T00:00:00Z"
    with pytest.raises(ValueError, match="title must not be empty"):
        MapAtlasNodeUpdate(title="   ", expected_updated_at=timestamp)
    data = MapAtlasNodeUpdate(title="  新城  ", expected_updated_at=timestamp)
    assert data.title == "新城"
