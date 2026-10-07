"""World object image generation candidates via the local CLI (ADR-0029, WP2)."""

from __future__ import annotations

import base64
import hashlib
import uuid
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFoundError
from infrastructure.tasks.models import AsyncTask
from modules.local_agent.facade import ReviewedImage
from modules.world.models import CoreEntity, WorldObjectImageCandidate
from modules.world.world_object_image_generation import (
    TASK_TYPE,
    WorldObjectImageGenerationService,
    default_image_prompt,
    handle_world_object_image_generate,
)

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC"
)


async def _pair_executor(
    async_client: AsyncClient, novel_id: str, kind: str = "pi"
) -> str:
    created = await async_client.post(
        "/api/local-agent/devices/pair",
        json={"novel_id": novel_id, "name": "作者的 Mac"},
    )
    assert created.status_code == 200, created.text
    paired = await async_client.post(
        "/api/local-agent/companion/activate",
        json={"code": created.json()["code"]},
    )
    assert paired.status_code == 200, paired.text
    device_id = paired.json()["device_id"]
    selected = await async_client.put(
        "/api/local-agent/executor",
        json={"novel_id": novel_id, "kind": kind, "device_id": device_id},
    )
    assert selected.status_code == 200, selected.text
    return device_id


class MemoryImageStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put_webp(self, key: str, payload: bytes) -> None:
        self.objects[key] = payload

    async def get_webp(self, key: str, *, max_bytes: int) -> bytes:
        return self.objects[key]

    async def delete_object(self, key: str) -> None:
        self.objects.pop(key, None)


# ------------------------------ default prompt ------------------------------


def test_default_prompt_excludes_unconfirmed_content() -> None:
    confirmed = CoreEntity(
        id=uuid.uuid4(),
        novel_id=uuid.uuid4(),
        entity_type="character",
        name="沈知微",
        status="canonical",
        summary="曾任天机阁供奉，擅长机关术。",
        content_json={"性格": "冷静克制", "_meta": {"source": "draft"}},
    )
    prompt = default_image_prompt(confirmed)
    assert "沈知微" in prompt
    assert "曾任天机阁供奉" in prompt
    assert "冷静克制" in prompt
    assert "半身像" in prompt
    assert "文字" in prompt

    unconfirmed = CoreEntity(
        id=uuid.uuid4(),
        novel_id=uuid.uuid4(),
        entity_type="character",
        name="沈知微",
        status="candidate",
        summary="尚未确认的秘密身世设定",
        content_json={"性格": "尚未确认的候选属性"},
    )
    unconfirmed_prompt = default_image_prompt(unconfirmed)
    assert "沈知微" in unconfirmed_prompt
    assert "尚未确认" not in unconfirmed_prompt


# ------------------------------ generation info ------------------------------


@pytest.mark.asyncio
async def test_generation_info_unavailable_without_executor(
    async_client: AsyncClient, test_project_id: str, test_character_id: str
) -> None:
    resp = await async_client.get(
        f"/api/world/entities/{test_character_id}/image-generation",
        params={"novel_id": test_project_id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["available"] is False
    assert body["reason"]
    assert body["candidates"] == []
    assert "沈" not in body["default_prompt"]  # sanity: no leakage, just runs


@pytest.mark.asyncio
async def test_generation_info_available_after_pairing(
    async_client: AsyncClient, test_project_id: str, test_character_id: str
) -> None:
    await _pair_executor(async_client, test_project_id)
    resp = await async_client.get(
        f"/api/world/entities/{test_character_id}/image-generation",
        params={"novel_id": test_project_id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["available"] is True
    assert body["executor_kind"] == "pi"


# ------------------------------ create candidate ------------------------------


@pytest.mark.asyncio
async def test_create_candidate_queues_task_with_local_agent_meta(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_project_id: str,
    test_character_id: str,
) -> None:
    await _pair_executor(async_client, test_project_id)
    created = await async_client.post(
        f"/api/world/entities/{test_character_id}/image-candidates",
        json={"novel_id": test_project_id, "prompt": "半身像，写实风格"},
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["status"] == "queued"
    assert body["task_id"]

    task = await db_session.get(AsyncTask, uuid.UUID(body["task_id"]))
    assert task is not None
    assert task.task_type == TASK_TYPE
    assert task.meta["_local_agent"] is True
    assert task.meta["_local_approved"] is False
    assert task.meta["candidate_id"] == body["id"]


@pytest.mark.asyncio
async def test_create_candidate_conflicts_while_active(
    async_client: AsyncClient, test_project_id: str, test_character_id: str
) -> None:
    await _pair_executor(async_client, test_project_id)
    first = await async_client.post(
        f"/api/world/entities/{test_character_id}/image-candidates",
        json={"novel_id": test_project_id, "prompt": "半身像"},
    )
    assert first.status_code == 200, first.text
    second = await async_client.post(
        f"/api/world/entities/{test_character_id}/image-candidates",
        json={"novel_id": test_project_id, "prompt": "另一张"},
    )
    assert second.status_code == 409
    assert second.json()["error"] == "image_generation_in_progress"


@pytest.mark.asyncio
async def test_create_candidate_without_executor_is_conflict(
    async_client: AsyncClient, test_project_id: str, test_character_id: str
) -> None:
    resp = await async_client.post(
        f"/api/world/entities/{test_character_id}/image-candidates",
        json={"novel_id": test_project_id, "prompt": "半身像"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"] == "local_image_executor_required"


# ------------------------------ cross-novel isolation ------------------------------


@pytest.mark.asyncio
async def test_candidate_not_found_across_novels(
    db_session: AsyncSession,
    test_project_id: str,
    test_character_id: str,
    other_novel_id: str,
) -> None:
    candidate = WorldObjectImageCandidate(
        novel_id=uuid.UUID(test_project_id),
        entity_id=uuid.UUID(test_character_id),
        owner_id=uuid.uuid4(),
        status="review_ready",
        prompt="p",
        executor_json={"kind": "pi", "device_id": str(uuid.uuid4())},
        image_data=_PNG,
        width=1,
        height=1,
        sha256="a" * 64,
    )
    db_session.add(candidate)
    await db_session.commit()

    service = WorldObjectImageGenerationService()
    with pytest.raises(NotFoundError):
        await service.get_candidate(
            db_session, novel_id=other_novel_id, candidate_id=str(candidate.id)
        )


# ------------------------------ task handler ------------------------------


async def _seed_candidate_task(
    db_session: AsyncSession, novel_id: str, entity_id: str
) -> tuple[AsyncTask, WorldObjectImageCandidate]:
    task = AsyncTask(
        task_type=TASK_TYPE,
        novel_id=uuid.UUID(novel_id),
        status="running",
        attempt=1,
        lease_id=str(uuid.uuid4()),
        recovery_policy="never_retry",
        meta={},
    )
    db_session.add(task)
    await db_session.flush()
    candidate = WorldObjectImageCandidate(
        novel_id=uuid.UUID(novel_id),
        entity_id=uuid.UUID(entity_id),
        owner_id=uuid.uuid4(),
        task_id=task.id,
        status="queued",
        prompt="半身像",
        executor_json={"kind": "pi", "device_id": str(uuid.uuid4())},
    )
    db_session.add(candidate)
    await db_session.flush()
    task.meta = {"candidate_id": str(candidate.id), "novel_id": novel_id}
    await db_session.commit()
    return task, candidate


@pytest.mark.asyncio
async def test_handler_happy_path_stores_reviewed_image(
    db_session: AsyncSession, test_project_id: str, test_character_id: str
) -> None:
    task, candidate = await _seed_candidate_task(
        db_session, test_project_id, test_character_id
    )
    digest = hashlib.sha256(_PNG).hexdigest()
    reviewed = ReviewedImage(data=_PNG, width=1, height=1, sha256=digest)
    with patch(
        "modules.world.world_object_image_generation.run_local_image",
        autospec=True,
        return_value=reviewed,
    ):
        result = await handle_world_object_image_generate(db_session, task)
    assert result["status"] == "review_ready"
    await db_session.refresh(candidate)
    assert candidate.status == "review_ready"
    assert candidate.image_data == _PNG
    assert len(candidate.image_data) <= 6 * 1024 * 1024
    assert candidate.sha256 == digest
    from modules.world.world_object_image_generation import _reuse_world_object_candidate
    from modules.world.world_object_images import WorldObjectImageService

    service = WorldObjectImageGenerationService(
        image_service=WorldObjectImageService(MemoryImageStorage())
    )
    await service.adopt_candidate(
        db_session, novel_id=test_project_id, candidate_id=str(candidate.id)
    )
    assert candidate.image_data is None
    reused = await _reuse_world_object_candidate(
        db_session,
        novel_id=test_project_id,
        owner_id=str(candidate.owner_id),
        entity_id=test_character_id,
        request_hash=candidate.request_hash,
    )
    assert reused is not None and reused.image_data == _PNG


@pytest.mark.asyncio
async def test_handler_failure_marks_candidate_failed(
    db_session: AsyncSession, test_project_id: str, test_character_id: str
) -> None:
    task, candidate = await _seed_candidate_task(
        db_session, test_project_id, test_character_id
    )
    with (
        patch(
            "modules.world.world_object_image_generation.run_local_image",
            autospec=True,
            side_effect=RuntimeError("companion offline"),
        ),
        pytest.raises(RuntimeError),
    ):
        await handle_world_object_image_generate(db_session, task)
    await db_session.refresh(candidate)
    assert candidate.status == "failed"
    assert candidate.error


# ------------------------------ adopt / discard ------------------------------


@pytest.mark.asyncio
async def test_adopt_candidate_uploads_and_clears_bytes(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_project_id: str,
    test_character_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.world import api
    from modules.world.world_object_images import WorldObjectImageService

    storage = MemoryImageStorage()
    monkeypatch_service = WorldObjectImageGenerationService(
        image_service=WorldObjectImageService(storage)  # type: ignore[arg-type]
    )
    monkeypatch.setattr(
        api.entities, "_entity_image_generation_service", monkeypatch_service
    )
    candidate = WorldObjectImageCandidate(
        novel_id=uuid.UUID(test_project_id),
        entity_id=uuid.UUID(test_character_id),
        owner_id=uuid.uuid4(),
        status="review_ready",
        prompt="半身像",
        executor_json={"kind": "pi", "device_id": str(uuid.uuid4())},
        image_data=_PNG,
        width=1,
        height=1,
        sha256="c" * 64,
    )
    db_session.add(candidate)
    await db_session.commit()

    resp = await async_client.post(
        f"/api/world/image-candidates/{candidate.id}/adopt",
        json={"novel_id": test_project_id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["candidate"]["status"] == "adopted"

    entity = await db_session.get(CoreEntity, uuid.UUID(test_character_id))
    assert str(entity.image_version) == body["image_version"]
    await db_session.refresh(candidate)
    assert candidate.status == "adopted"
    assert candidate.image_data is None
    assert candidate.adopted_image_version == entity.image_version


@pytest.mark.asyncio
async def test_discard_review_ready_candidate(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_project_id: str,
    test_character_id: str,
) -> None:
    candidate = WorldObjectImageCandidate(
        novel_id=uuid.UUID(test_project_id),
        entity_id=uuid.UUID(test_character_id),
        owner_id=uuid.uuid4(),
        status="review_ready",
        prompt="半身像",
        executor_json={"kind": "pi", "device_id": str(uuid.uuid4())},
        image_data=_PNG,
        width=1,
        height=1,
        sha256="d" * 64,
    )
    db_session.add(candidate)
    await db_session.commit()

    resp = await async_client.post(
        f"/api/world/image-candidates/{candidate.id}/discard",
        json={"novel_id": test_project_id},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "discarded"
    await db_session.refresh(candidate)
    assert candidate.image_data is None


@pytest.mark.asyncio
async def test_discard_queued_candidate_cancels_task(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_project_id: str,
    test_character_id: str,
) -> None:
    task, candidate = await _seed_candidate_task(
        db_session, test_project_id, test_character_id
    )
    task.status = "pending"
    task.meta = {**task.meta, "_local_agent": True, "_local_approved": False}
    await db_session.commit()

    resp = await async_client.post(
        f"/api/world/image-candidates/{candidate.id}/discard",
        json={"novel_id": test_project_id},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "cancelled"
    await db_session.refresh(task)
    assert task.status == "cancelled"


# ------------------------------ convergence & retention ------------------------------


@pytest.mark.asyncio
async def test_convergence_of_dead_task_marks_candidate_failed(
    db_session: AsyncSession, test_project_id: str, test_character_id: str
) -> None:
    task, candidate = await _seed_candidate_task(
        db_session, test_project_id, test_character_id
    )
    candidate.status = "generating"
    task.status = "failed"
    await db_session.commit()

    service = WorldObjectImageGenerationService()
    view = await service.get_candidate(
        db_session, novel_id=test_project_id, candidate_id=str(candidate.id)
    )
    assert view.status == "failed"
    await db_session.refresh(candidate)
    assert candidate.status == "failed"


@pytest.mark.asyncio
async def test_retention_keeps_newest_three_review_ready(
    db_session: AsyncSession, test_project_id: str, test_character_id: str
) -> None:
    service = WorldObjectImageGenerationService()
    entity_id = uuid.UUID(test_character_id)
    novel_id = uuid.UUID(test_project_id)
    candidates = []
    for index in range(5):
        row = WorldObjectImageCandidate(
            novel_id=novel_id,
            entity_id=entity_id,
            owner_id=uuid.uuid4(),
            status="review_ready",
            prompt=f"p{index}",
            executor_json={"kind": "pi", "device_id": str(uuid.uuid4())},
            image_data=_PNG,
            width=1,
            height=1,
            sha256=f"{index}" * 64,
        )
        db_session.add(row)
        await db_session.flush()
        candidates.append(row)
    await db_session.commit()

    await service._retain_newest_review_ready(
        db_session, novel_id=test_project_id, entity_id=entity_id
    )
    await db_session.commit()

    for row in candidates:
        await db_session.refresh(row)
    review_ready = [row for row in candidates if row.status == "review_ready"]
    discarded = [row for row in candidates if row.status == "discarded"]
    assert len(review_ready) == 3
    assert len(discarded) == 2
    assert all(row.image_data is None for row in discarded)
    # The three newest (highest created_at, i.e. last created) survive.
    assert {row.prompt for row in review_ready} == {"p2", "p3", "p4"}
