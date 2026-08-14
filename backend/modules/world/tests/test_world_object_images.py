from __future__ import annotations

import io
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from httpx import AsyncClient
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, DomainError, NotFoundError
from modules.world.map_atlas_tasks import handle_world_object_image_cleanup
from modules.world.models import CoreEntity
from modules.world.services.core.entity_type_transition_service import (
    EntityTypeTransitionService,
)
from modules.world.world_object_images import (
    FULL_MAX_BYTES,
    MAX_UPLOAD_BYTES,
    THUMBNAIL_MAX_BYTES,
    WorldObjectImageService,
    WorldObjectImageStorage,
    delete_unreferenced_image_version,
    normalize_world_object_image,
    project_image_prefix,
)


def _image_bytes(
    *,
    width: int = 400,
    height: int = 800,
    format: str = "PNG",
) -> bytes:
    image = Image.new("RGB", (width, height), "red")
    if height >= 4:
        image.paste("blue", (0, height // 3, width, height))
    output = io.BytesIO()
    image.save(output, format=format, exif=b"discard-me" if format == "JPEG" else b"")
    return output.getvalue()


class MemoryStorage:
    def __init__(self, fail_put: int | None = None) -> None:
        self.objects: dict[str, bytes] = {}
        self.deleted: list[str] = []
        self.puts = 0
        self.fail_put = fail_put

    async def put_webp(self, key: str, payload: bytes) -> None:
        self.puts += 1
        if self.puts == self.fail_put:
            raise RuntimeError("storage unavailable")
        self.objects[key] = payload

    async def get_webp(self, key: str, *, max_bytes: int) -> bytes:
        payload = self.objects[key]
        assert len(payload) <= max_bytes
        return payload

    async def delete_object(self, key: str) -> None:
        self.deleted.append(key)
        self.objects.pop(key, None)


class MissingStorage(MemoryStorage):
    async def get_webp(self, key: str, *, max_bytes: int) -> bytes:
        raise ClientError(
            {
                "Error": {"Code": "NoSuchKey"},
                "ResponseMetadata": {"HTTPStatusCode": 404},
            },
            "GetObject",
        )


class UnavailableStorage(MemoryStorage):
    async def put_webp(self, key: str, payload: bytes) -> None:
        raise ClientError(
            {
                "Error": {"Code": "ServiceUnavailable"},
                "ResponseMetadata": {"HTTPStatusCode": 503},
            },
            "PutObject",
        )


def test_normalize_rejects_spoofed_broken_and_boundary_payloads() -> None:
    for payload in (b"GIF89a" + b"x" * 20, b"\x89PNG\r\n\x1a\ntruncated"):
        with pytest.raises(ValueError, match="PNG|JPEG"):
            normalize_world_object_image(payload, is_character=False)
    with pytest.raises(ValueError, match="6MiB"):
        normalize_world_object_image(b"x" * MAX_UPLOAD_BYTES, is_character=False)
    with pytest.raises(ValueError, match="4096"):
        normalize_world_object_image(
            _image_bytes(width=4097, height=1),
            is_character=False,
        )


def test_normalize_outputs_bounded_metadata_free_webp_with_character_crop() -> None:
    character = normalize_world_object_image(
        _image_bytes(format="JPEG"),
        is_character=True,
    )
    other = normalize_world_object_image(_image_bytes(), is_character=False)
    assert len(character.full) <= FULL_MAX_BYTES
    assert len(character.thumbnail) <= THUMBNAIL_MAX_BYTES
    with Image.open(io.BytesIO(character.full)) as full:
        assert full.format == "WEBP"
        assert max(full.size) <= 896
        assert "exif" not in full.info
    with Image.open(io.BytesIO(character.thumbnail)) as upper_crop:
        assert upper_crop.size == (192, 192)
        character_red = upper_crop.resize((1, 1)).getpixel((0, 0))[0]
    with Image.open(io.BytesIO(other.thumbnail)) as center_crop:
        other_red = center_crop.resize((1, 1)).getpixel((0, 0))[0]
    assert character_red > other_red


def test_world_object_bucket_does_not_fall_back_to_map_bucket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "modules.world.world_object_images.get_settings",
        lambda: SimpleNamespace(
            world_object_s3_bucket="",
            map_atlas_s3_bucket="atlas",
        ),
    )
    with pytest.raises(RuntimeError, match="WORLD_OBJECT_S3_BUCKET"):
        WorldObjectImageStorage(client=object())


@pytest.mark.asyncio
async def test_upload_replace_read_and_cross_novel_isolation(
    db_session: AsyncSession,
    test_project_id: str,
    test_entity_id: str,
) -> None:
    storage = MemoryStorage()
    service = WorldObjectImageService(storage)  # type: ignore[arg-type]
    first = await service.upload(
        db_session,
        novel_id=test_project_id,
        entity_id=test_entity_id,
        payload=_image_bytes(),
    )
    assert first.has_image is True
    first_version = (
        await db_session.get(CoreEntity, uuid.UUID(test_entity_id))
    ).image_version
    assert await service.get(
        db_session,
        novel_id=test_project_id,
        entity_id=test_entity_id,
        variant="thumbnail",
    )

    await service.upload(
        db_session,
        novel_id=test_project_id,
        entity_id=test_entity_id,
        payload=_image_bytes(format="JPEG"),
    )
    entity = await db_session.get(CoreEntity, uuid.UUID(test_entity_id))
    assert entity.image_version != first_version
    assert len(storage.objects) == 4
    assert (
        await delete_unreferenced_image_version(
            db_session,
            storage,  # type: ignore[arg-type]
            novel_id=test_project_id,
            entity_id=test_entity_id,
            image_version=str(first_version),
        )
        == 2
    )
    assert len(storage.objects) == 2

    with pytest.raises(NotFoundError):
        await service.get(
            db_session,
            novel_id=str(uuid.uuid4()),
            entity_id=test_entity_id,
            variant="full",
        )


@pytest.mark.asyncio
async def test_quota_failure_keeps_old_state_and_cleans_new_objects(
    db_session: AsyncSession,
    test_project_id: str,
    test_entity_id: str,
) -> None:
    for index in range(50):
        db_session.add(
            CoreEntity(
                novel_id=uuid.UUID(test_project_id),
                entity_type="item",
                name=f"item-{index}",
                status="canonical",
                image_version=uuid.uuid4(),
            )
        )
    await db_session.flush()
    await db_session.commit()
    storage = MemoryStorage()
    service = WorldObjectImageService(storage)  # type: ignore[arg-type]
    with pytest.raises(ConflictError, match="50"):
        await service.upload(
            db_session,
            novel_id=test_project_id,
            entity_id=test_entity_id,
            payload=_image_bytes(),
        )
    assert storage.objects == {}
    assert len(storage.deleted) == 2
    entity = await db_session.get(CoreEntity, uuid.UUID(test_entity_id))
    assert entity.image_version is None


@pytest.mark.asyncio
async def test_partial_storage_failure_compensates_first_variant(
    db_session: AsyncSession,
    test_project_id: str,
    test_entity_id: str,
) -> None:
    storage = MemoryStorage(fail_put=2)
    service = WorldObjectImageService(storage)  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="storage unavailable"):
        await service.upload(
            db_session,
            novel_id=test_project_id,
            entity_id=test_entity_id,
            payload=_image_bytes(),
        )
    assert storage.objects == {}
    assert len(storage.deleted) == 2


@pytest.mark.asyncio
async def test_storage_unavailable_returns_retryable_domain_error(
    db_session: AsyncSession,
    test_project_id: str,
    test_entity_id: str,
) -> None:
    with pytest.raises(DomainError) as caught:
        await WorldObjectImageService(UnavailableStorage()).upload(  # type: ignore[arg-type]
            db_session,
            novel_id=test_project_id,
            entity_id=test_entity_id,
            payload=_image_bytes(),
        )
    assert caught.value.status_code == 503
    assert caught.value.code == "image_storage_unavailable"


@pytest.mark.asyncio
async def test_missing_stored_variant_is_not_found(
    db_session: AsyncSession,
    test_project_id: str,
    test_entity_id: str,
) -> None:
    entity = await db_session.get(CoreEntity, uuid.UUID(test_entity_id))
    assert entity is not None
    entity.image_version = uuid.uuid4()
    await db_session.flush()

    with pytest.raises(NotFoundError):
        await WorldObjectImageService(MissingStorage()).get(  # type: ignore[arg-type]
            db_session,
            novel_id=test_project_id,
            entity_id=test_entity_id,
            variant="full",
        )


@pytest.mark.asyncio
async def test_type_change_cannot_overfill_target_image_quota(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    for index in range(50):
        db_session.add(
            CoreEntity(
                novel_id=uuid.UUID(test_project_id),
                entity_type="item",
                name=f"occupied-{index}",
                status="canonical",
                image_version=uuid.uuid4(),
            )
        )
    character = CoreEntity(
        novel_id=uuid.UUID(test_project_id),
        entity_type="character",
        name="typed image",
        status="canonical",
        image_version=uuid.uuid4(),
    )
    db_session.add(character)
    await db_session.flush()

    with pytest.raises(ConflictError, match="50"):
        await EntityTypeTransitionService().transition(
            db_session,
            entity=character,
            new_type="item",
        )


@pytest.mark.asyncio
async def test_cleanup_handler_dispatches_project_prefix() -> None:
    prefix = project_image_prefix(str(uuid.uuid4()))
    storage = MagicMock(spec=WorldObjectImageStorage)
    storage.delete_prefix = AsyncMock(return_value=2)
    with patch(
        "modules.world.map_atlas_tasks.WorldObjectImageStorage",
        autospec=True,
        return_value=storage,
    ):
        result = await handle_world_object_image_cleanup(
            None,
            SimpleNamespace(
                meta={"cleanup_kind": "project_prefix", "object_prefix": prefix}
            ),
        )
    storage.delete_prefix.assert_awaited_once_with(prefix)
    assert result["deleted_objects"] == 2


@pytest.mark.asyncio
async def test_authenticated_upload_and_read_api_contract(
    async_client: AsyncClient,
    test_project_id: str,
    test_entity_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.world import api

    storage = MemoryStorage()
    monkeypatch.setattr(api, "_entity_image_service", WorldObjectImageService(storage))
    uploaded = await async_client.put(
        f"/api/world/entities/{test_entity_id}/image",
        params={"novel_id": test_project_id},
        files={"image": ("portrait.png", _image_bytes(), "image/png")},
    )
    assert uploaded.status_code == 200
    assert uploaded.json()["has_image"] is True
    assert "image_version" not in uploaded.json()

    fetched = await async_client.get(
        f"/api/world/entities/{test_entity_id}/image",
        params={"novel_id": test_project_id, "variant": "full"},
    )
    assert fetched.status_code == 200
    assert fetched.headers["content-type"] == "image/webp"
    assert fetched.headers["cache-control"] == "private, no-store"
    with Image.open(io.BytesIO(fetched.content)) as image:
        assert image.format == "WEBP"
