"""Map atlas local-CLI image backend (ADR-0029, WP3)."""

from __future__ import annotations

import base64
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError
from infrastructure.tasks.models import AsyncTask
from modules.local_agent.facade import AgentExecutor, ReviewedImage
from modules.world.map_atlas_facade import map_capabilities
from modules.world.map_atlas_models import MapAtlasNode, MapAtlasPage, MapAtlasRun
from modules.world.map_atlas_schemas import MapAtlasRunCreate
from modules.world.map_atlas_service import MapAtlasService
from modules.world.map_atlas_storage import MapAtlasStorage, page_object_key, validate_png
from modules.world.map_atlas_workflow import (
    _generate_page,
    _is_local_image_run,
    reconcile_map_atlas_task_owners,
)

OPAQUE_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC"
)


def _executor() -> AgentExecutor:
    return AgentExecutor(kind="pi", device_id=str(uuid.uuid4()))


# ------------------------------ create_run ------------------------------


@pytest.mark.asyncio
async def test_create_run_local_backend_skips_account_image_connection(
    db_session: AsyncSession, test_project_id: str
) -> None:
    task_id = str(uuid.uuid4())
    with (
        patch(
            "modules.world.map_atlas_service.selected_executor",
            autospec=True,
            return_value=_executor(),
        ),
        patch(
            "modules.world.map_atlas_service.build_project_image_execution_snapshot",
            autospec=True,
        ) as image_snapshot,
        patch(
            "modules.world.map_atlas_service.build_project_llm_execution_snapshot",
            autospec=True,
            return_value={"snapshot_hash": "llm"},
        ),
        patch(
            "modules.world.map_atlas_service.enqueue_coalesced_task",
            autospec=True,
            return_value=SimpleNamespace(task_id=task_id, reused=False),
        ) as enqueue,
    ):
        result = await MapAtlasService(storage=SimpleNamespace()).create_run(
            db_session,
            test_project_id,
            MapAtlasRunCreate(image_backend="local_cli"),
        )
    image_snapshot.assert_not_awaited()
    assert result["status"] == "planning"
    run = await db_session.get(MapAtlasRun, uuid.UUID(result["id"]))
    assert run.image_execution_snapshot["provider_id"] == "local-cli"
    assert run.image_execution_snapshot["kind"] == "pi"
    assert run.context_snapshot["image_backend"] == "local_cli"
    meta = enqueue.call_args.kwargs["meta"]
    assert meta["_local_agent"] is True
    assert meta["_local_approved"] is False


@pytest.mark.asyncio
async def test_create_run_local_backend_requires_paired_executor(
    db_session: AsyncSession, test_project_id: str
) -> None:
    with (
        patch(
            "modules.world.map_atlas_service.selected_executor",
            autospec=True,
            return_value=AgentExecutor(),  # kind="gateway"
        ),
        patch(
            "modules.world.map_atlas_service.build_project_llm_execution_snapshot",
            autospec=True,
            return_value={"snapshot_hash": "llm"},
        ),
    ):
        with pytest.raises(ConflictError) as excinfo:
            await MapAtlasService(storage=SimpleNamespace()).create_run(
                db_session,
                test_project_id,
                MapAtlasRunCreate(image_backend="local_cli"),
            )
    assert excinfo.value.code == "local_image_executor_required"


@pytest.mark.asyncio
async def test_create_run_account_backend_still_requires_connection(
    db_session: AsyncSession, test_project_id: str
) -> None:
    task_id = str(uuid.uuid4())
    with (
        patch(
            "modules.world.map_atlas_service.build_project_image_execution_snapshot",
            autospec=True,
            return_value={"snapshot_hash": "image"},
        ) as image_snapshot,
        patch(
            "modules.world.map_atlas_service.build_project_llm_execution_snapshot",
            autospec=True,
            return_value={"snapshot_hash": "llm"},
        ),
        patch(
            "modules.world.map_atlas_service.enqueue_coalesced_task",
            autospec=True,
            return_value=SimpleNamespace(task_id=task_id, reused=False),
        ) as enqueue,
    ):
        result = await MapAtlasService(storage=SimpleNamespace()).create_run(
            db_session,
            test_project_id,
            MapAtlasRunCreate(),
        )
    image_snapshot.assert_awaited_once()
    run = await db_session.get(MapAtlasRun, uuid.UUID(result["id"]))
    assert "provider_id" not in (run.image_execution_snapshot or {})
    assert "_local_agent" not in enqueue.call_args.kwargs["meta"]


# ------------------------------ capabilities ------------------------------


@pytest.mark.asyncio
async def test_map_capabilities_reports_local_cli(
    db_session: AsyncSession, test_project_id: str
) -> None:
    unavailable = await map_capabilities(db_session, test_project_id)
    assert unavailable["local_cli"]["available"] is False

    with patch(
        "modules.local_agent.facade.selected_executor",
        autospec=True,
        return_value=_executor(),
    ):
        available = await map_capabilities(db_session, test_project_id)
    assert available["local_cli"]["available"] is True
    assert available["local_cli"]["kind"] == "pi"


# ------------------------------ _generate_page (local) ------------------------------


async def _make_run_node_page(
    db_session: AsyncSession,
    test_project_id: str,
    *,
    with_mask: bool = False,
) -> tuple[AsyncTask, MapAtlasRun, MapAtlasPage]:
    novel_id = uuid.UUID(test_project_id)
    task = AsyncTask(
        task_type="map_atlas_generate",
        novel_id=novel_id,
        status="running",
        attempt=1,
        lease_id=str(uuid.uuid4()),
        recovery_policy="manual_resume",
        meta={},
    )
    db_session.add(task)
    await db_session.flush()
    run = MapAtlasRun(
        novel_id=novel_id,
        task_id=task.id,
        run_kind="initial",
        status="generating",
        image_execution_snapshot={
            "version": 1,
            "provider_id": "local-cli",
            "kind": "pi",
            "device_id": str(uuid.uuid4()),
        },
    )
    db_session.add(run)
    await db_session.flush()
    task.meta = {"novel_id": test_project_id, "run_id": str(run.id)}
    node = MapAtlasNode(
        novel_id=novel_id,
        created_by_run_id=run.id,
        semantic_key="world",
        title="世界",
        level="world",
    )
    db_session.add(node)
    await db_session.flush()
    page_id = uuid.uuid4()
    mask_key = (
        page_object_key(test_project_id, str(page_id), mask=True) if with_mask else None
    )
    page = MapAtlasPage(
        id=page_id,
        novel_id=novel_id,
        run_id=run.id,
        node_id=node.id,
        generation_status="prepared",
        title="世界",
        visual_brief="世界地图",
        prompt="no text",
        mask_object_key=mask_key,
    )
    db_session.add(page)
    await db_session.commit()
    db_session.expunge(task)
    return task, run, page


@pytest.mark.asyncio
async def test_generate_page_local_backend_uses_run_local_image(
    db_session: AsyncSession, test_project_id: str
) -> None:
    task, run, page = await _make_run_node_page(
        db_session, test_project_id, with_mask=True
    )
    assert _is_local_image_run(run) is True

    objects: dict[str, bytes] = {"__mask__": OPAQUE_PNG}
    storage = MagicMock(spec=MapAtlasStorage)

    async def get_png(key: str) -> bytes:
        return objects["__mask__"]

    async def put_png(key: str, payload: bytes):
        objects[key] = payload
        return validate_png(payload)

    storage.get_png = AsyncMock(side_effect=get_png)
    storage.put_png = AsyncMock(side_effect=put_png)

    reviewed = ReviewedImage(data=OPAQUE_PNG, width=1024, height=1024, sha256="e" * 64)

    with (
        patch(
            "modules.world.map_atlas_workflow.MapAtlasStorage",
            autospec=True,
            return_value=storage,
        ),
        patch(
            "modules.world.map_atlas_workflow.get_project_context",
            autospec=True,
            return_value=SimpleNamespace(owner_id=str(uuid.uuid4())),
        ),
        patch(
            "modules.world.map_atlas_workflow.run_local_image",
            autospec=True,
            return_value=reviewed,
        ) as run_local,
        patch(
            "modules.world.map_atlas_workflow.fit_cover",
            autospec=True,
            return_value=reviewed,
        ),
    ):
        assert await _generate_page(db_session, task, run, page)

    inputs = run_local.await_args.kwargs["inputs"]
    names = [item[0] for item in inputs]
    assert "mask.png" in names
    for name, media_type, data in inputs:
        assert media_type == "image/png"
        assert isinstance(data, bytes)

    await db_session.refresh(page)
    assert page.generation_status == "review_ready"
    assert page.provider == "local-cli"
    assert page.model == "pi"
    assert page.provider_request_id is None


@pytest.mark.asyncio
async def test_generate_page_local_failure_is_never_possible_charge(
    db_session: AsyncSession, test_project_id: str
) -> None:
    task, run, page = await _make_run_node_page(db_session, test_project_id)
    storage = MagicMock(spec=MapAtlasStorage)

    with (
        patch(
            "modules.world.map_atlas_workflow.MapAtlasStorage",
            autospec=True,
            return_value=storage,
        ),
        patch(
            "modules.world.map_atlas_workflow.get_project_context",
            autospec=True,
            return_value=SimpleNamespace(owner_id=str(uuid.uuid4())),
        ),
        patch(
            "modules.world.map_atlas_workflow.run_local_image",
            autospec=True,
            side_effect=ConflictError("本机图片任务失败", code="local_image_failed"),
        ),
    ):
        assert not await _generate_page(db_session, task, run, page)

    await db_session.refresh(page)
    assert page.generation_status == "failed"
    assert page.error_code == "local_image_failed"
    await db_session.refresh(run)
    assert run.status == "partial"
    # A local failure never claims a possible duplicate charge.
    assert run.error_code != "retry_requires_confirmation" or page.error_code != (
        "possible_duplicate_charge"
    )


# ------------------------------ reconcile ------------------------------


@pytest.mark.asyncio
async def test_reconcile_local_in_flight_page_fails_without_duplicate_charge(
    db_session: AsyncSession, test_project_id: str
) -> None:
    task, run, page = await _make_run_node_page(db_session, test_project_id)
    page.generation_status = "provider_in_flight"
    page.provider = "local-cli"
    page.model = "pi"
    await db_session.commit()

    with patch(
        "modules.world.map_atlas_workflow.list_task_lifecycle_contracts",
        autospec=True,
        return_value={},
    ):
        assert await reconcile_map_atlas_task_owners(db_session) == 1

    await db_session.refresh(page)
    assert page.generation_status == "failed"
    assert page.error_code == "local_image_interrupted"
