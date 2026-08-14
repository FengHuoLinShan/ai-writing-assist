"""Private, bounded images attached to world objects."""

from __future__ import annotations

import asyncio
import io
import uuid
import warnings
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from botocore.exceptions import BotoCoreError, ClientError
from PIL import Image, ImageOps
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from core.errors import ConflictError, DomainError, NotFoundError
from infrastructure.tasks.facade import enqueue_task
from modules.project.facade import get_project_context, lock_project_ids_for_owner
from modules.world.map_atlas_storage import MapAtlasStorage
from modules.world.models import CoreEntity
from modules.world.schemas import CoreEntityResponse
from shared.utils import parse_uuid

MAX_UPLOAD_BYTES = 6 * 1024 * 1024
MAX_DIMENSION = 4096
MAX_PIXELS = MAX_DIMENSION * MAX_DIMENSION
FULL_MAX_EDGE = 896
FULL_MAX_BYTES = 256 * 1024
THUMBNAIL_SIZE = 192
THUMBNAIL_MAX_BYTES = 16 * 1024
CHARACTER_IMAGE_LIMIT = 20
OTHER_IMAGE_LIMIT = 50


@dataclass(frozen=True, slots=True)
class NormalizedImages:
    full: bytes
    thumbnail: bytes


def _encode_webp(image: Image.Image, *, byte_limit: int) -> bytes:
    for quality in (82, 74, 66, 58, 50, 42, 34, 26, 18, 10, 5):
        output = io.BytesIO()
        image.save(output, format="WEBP", quality=quality, method=6)
        payload = output.getvalue()
        if len(payload) <= byte_limit:
            return payload
    raise ValueError("图片内容过于复杂，无法压缩到限制内")


def normalize_world_object_image(
    payload: bytes,
    *,
    is_character: bool,
) -> NormalizedImages:
    """Validate a real PNG/JPEG and emit metadata-free bounded WebP variants."""
    if not payload or len(payload) >= MAX_UPLOAD_BYTES:
        raise ValueError("图片必须小于 6MiB")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(payload)) as probe:
                if (
                    probe.format not in {"PNG", "JPEG"}
                    or getattr(probe, "n_frames", 1) != 1
                ):
                    raise ValueError("仅支持 PNG 或 JPEG 图片")
                width, height = probe.size
                if (
                    width < 1
                    or height < 1
                    or width > MAX_DIMENSION
                    or height > MAX_DIMENSION
                    or width * height > MAX_PIXELS
                ):
                    raise ValueError("图片尺寸不能超过 4096×4096")
                probe.verify()
            with Image.open(io.BytesIO(payload)) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("图片尺寸不能超过 4096×4096") from exc
    except (OSError, SyntaxError) as exc:
        raise ValueError("仅支持完整的 PNG 或 JPEG 图片") from exc

    full = image.copy()
    full.thumbnail((FULL_MAX_EDGE, FULL_MAX_EDGE), Image.Resampling.LANCZOS)
    thumbnail = ImageOps.fit(
        image,
        (THUMBNAIL_SIZE, THUMBNAIL_SIZE),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.25 if is_character else 0.5),
    )
    return NormalizedImages(
        full=_encode_webp(full, byte_limit=FULL_MAX_BYTES),
        thumbnail=_encode_webp(thumbnail, byte_limit=THUMBNAIL_MAX_BYTES),
    )


def image_object_key(
    novel_id: str,
    entity_id: str,
    image_version: str,
    variant: Literal["thumbnail", "full"],
) -> str:
    return (
        f"world-objects/{uuid.UUID(str(novel_id))}/entities/"
        f"{uuid.UUID(str(entity_id))}/images/{uuid.UUID(str(image_version))}/{variant}.webp"
    )


def project_image_prefix(novel_id: str) -> str:
    return f"world-objects/{uuid.UUID(str(novel_id))}/"


def require_project_image_prefix(prefix: str) -> str:
    parts = str(prefix).split("/")
    if len(parts) != 3 or parts[0] != "world-objects" or parts[2] != "":
        raise ValueError("invalid world object project prefix")
    expected = project_image_prefix(parts[1])
    if prefix != expected:
        raise ValueError("invalid world object project prefix")
    return expected


class WorldObjectImageStorage(MapAtlasStorage):
    """Reuse the existing private S3 client and convergent deletion mechanics."""

    def __init__(self, *, client: Any | None = None, bucket: str | None = None) -> None:
        configured_bucket = (
            bucket if bucket is not None else get_settings().world_object_s3_bucket
        ).strip()
        if not configured_bucket:
            raise RuntimeError("WORLD_OBJECT_S3_BUCKET is required")
        super().__init__(
            client=client,
            bucket=configured_bucket,
        )

    async def put_webp(self, key: str, payload: bytes) -> None:
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self.bucket,
            Key=key,
            Body=payload,
            ContentType="image/webp",
        )

    async def get_webp(self, key: str, *, max_bytes: int) -> bytes:
        response = await asyncio.to_thread(
            self._client.get_object,
            Bucket=self.bucket,
            Key=key,
        )
        if int(response.get("ContentLength") or 0) > max_bytes:
            raise ValueError("已存储图片超出限制")
        body = response["Body"]
        try:
            payload = await asyncio.to_thread(body.read, max_bytes + 1)
        finally:
            close = getattr(body, "close", None)
            if callable(close):
                await asyncio.to_thread(close)
        if len(payload) > max_bytes:
            raise ValueError("已存储图片超出限制")
        return payload


class WorldObjectImageService:
    def __init__(self, storage: WorldObjectImageStorage | None = None) -> None:
        self.storage = storage

    def _storage(self) -> WorldObjectImageStorage:
        return self.storage or WorldObjectImageStorage()

    @staticmethod
    async def _entity(
        db: AsyncSession,
        novel_id: str,
        entity_id: str,
        *,
        lock: bool = False,
    ) -> CoreEntity:
        stmt = select(CoreEntity).where(
            CoreEntity.id == parse_uuid(entity_id, "entity_id"),
            CoreEntity.novel_id == parse_uuid(novel_id, "novel_id"),
        )
        if lock:
            stmt = stmt.with_for_update()
        entity = (await db.execute(stmt)).scalar_one_or_none()
        if entity is None:
            raise NotFoundError(f"CoreEntity {entity_id} not found")
        return entity

    async def upload(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        entity_id: str,
        payload: bytes,
    ) -> CoreEntityResponse:
        context = await get_project_context(db, novel_id)
        if context is None or context.owner_id is None:
            raise NotFoundError(f"Project {novel_id} not found")
        entity = await self._entity(db, novel_id, entity_id)
        prepared_character = entity.entity_type == "character"
        images = normalize_world_object_image(
            payload,
            is_character=prepared_character,
        )
        version = uuid.uuid4()
        storage = self._storage()
        keys = {
            variant: image_object_key(novel_id, entity_id, str(version), variant)
            for variant in ("full", "thumbnail")
        }
        try:
            await storage.put_webp(keys["full"], images.full)
            await storage.put_webp(keys["thumbnail"], images.thumbnail)

            entity = await self._entity(db, novel_id, entity_id, lock=True)
            project_ids = await lock_project_ids_for_owner(
                db,
                uuid.UUID(context.owner_id),
            )
            character = entity.entity_type == "character"
            if character != prepared_character:
                raise ConflictError("对象类型已变更，请重新上传图片")
            category = (
                CoreEntity.entity_type == "character"
                if character
                else CoreEntity.entity_type != "character"
            )
            count = int(
                (
                    await db.execute(
                        select(func.count(CoreEntity.id)).where(
                            CoreEntity.novel_id.in_(project_ids),
                            CoreEntity.image_version.is_not(None),
                            category,
                            CoreEntity.id != entity.id,
                        )
                    )
                ).scalar_one()
            )
            limit = CHARACTER_IMAGE_LIMIT if character else OTHER_IMAGE_LIMIT
            if count >= limit:
                raise ConflictError(
                    f"账号的{'人物' if character else '其他对象'}图片已达上限 {limit} 张"
                )

            previous = entity.image_version
            entity.image_version = version
            entity.image_updated_at = datetime.now(UTC)
            await db.flush()
            final_count = int(
                (
                    await db.execute(
                        select(func.count(CoreEntity.id)).where(
                            CoreEntity.novel_id.in_(project_ids),
                            CoreEntity.image_version.is_not(None),
                            category,
                        )
                    )
                ).scalar_one()
            )
            if final_count > limit:
                raise ConflictError("图片配额已被占用，请稍后重试")
            if previous is not None:
                enqueue_task(
                    db,
                    "world_object_image_cleanup",
                    meta={
                        "cleanup_kind": "image_version",
                        "project_id": novel_id,
                        "entity_id": entity_id,
                        "image_version": str(previous),
                    },
                    novel_id=None,
                )
            response = CoreEntityResponse.model_validate(entity)
            await db.commit()
            return response
        except Exception as exc:
            await db.rollback()
            cleanup_needed = False
            # A timed-out PUT can still have reached S3; this version is unique and
            # unreferenced after rollback, so always converge both exact keys.
            for key in keys.values():
                try:
                    await storage.delete_object(key)
                except Exception:
                    cleanup_needed = True
            if cleanup_needed:
                enqueue_task(
                    db,
                    "world_object_image_cleanup",
                    meta={
                        "cleanup_kind": "image_version",
                        "project_id": novel_id,
                        "entity_id": entity_id,
                        "image_version": str(version),
                    },
                    novel_id=None,
                )
                try:
                    await db.commit()
                except Exception:
                    await db.rollback()
            if isinstance(exc, (BotoCoreError, ClientError)):
                raise DomainError(
                    "图片存储暂不可用，请稍后重试",
                    code="image_storage_unavailable",
                    status_code=503,
                ) from exc
            raise

    async def get(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        entity_id: str,
        variant: Literal["thumbnail", "full"],
    ) -> bytes:
        if await get_project_context(db, novel_id) is None:
            raise NotFoundError(f"Project {novel_id} not found")
        entity = await self._entity(db, novel_id, entity_id)
        if entity.image_version is None:
            raise NotFoundError(f"CoreEntityImage {entity_id} not found")
        try:
            return await self._storage().get_webp(
                image_object_key(
                    novel_id,
                    entity_id,
                    str(entity.image_version),
                    variant,
                ),
                max_bytes=(
                    THUMBNAIL_MAX_BYTES if variant == "thumbnail" else FULL_MAX_BYTES
                ),
            )
        except ClientError as exc:
            response = exc.response or {}
            code = str((response.get("Error") or {}).get("Code") or "")
            status = (response.get("ResponseMetadata") or {}).get("HTTPStatusCode")
            if code in {"404", "NoSuchKey", "NotFound"} or status == 404:
                raise NotFoundError(f"CoreEntityImage {entity_id} not found") from exc
            raise DomainError(
                "图片存储暂不可用，请稍后重试",
                code="image_storage_unavailable",
                status_code=503,
            ) from exc
        except BotoCoreError as exc:
            raise DomainError(
                "图片存储暂不可用，请稍后重试",
                code="image_storage_unavailable",
                status_code=503,
            ) from exc


async def require_image_type_change_quota(
    db: AsyncSession,
    entity: CoreEntity,
    new_type: str,
) -> None:
    """Keep account image quotas valid when an imaged object changes category."""
    if entity.image_version is None:
        return
    was_character = entity.entity_type == "character"
    will_be_character = new_type == "character"
    if was_character == will_be_character:
        return
    context = await get_project_context(db, str(entity.novel_id))
    if context is None or context.owner_id is None:
        raise NotFoundError(f"Project {entity.novel_id} not found")
    project_ids = await lock_project_ids_for_owner(db, uuid.UUID(context.owner_id))
    category = (
        CoreEntity.entity_type == "character"
        if will_be_character
        else CoreEntity.entity_type != "character"
    )
    count = int(
        (
            await db.execute(
                select(func.count(CoreEntity.id)).where(
                    CoreEntity.novel_id.in_(project_ids),
                    CoreEntity.image_version.is_not(None),
                    category,
                    CoreEntity.id != entity.id,
                )
            )
        ).scalar_one()
    )
    limit = CHARACTER_IMAGE_LIMIT if will_be_character else OTHER_IMAGE_LIMIT
    if count >= limit:
        raise ConflictError(
            f"账号的{'人物' if will_be_character else '其他对象'}图片已达上限 {limit} 张"
        )


async def delete_unreferenced_image_version(
    db: AsyncSession,
    storage: WorldObjectImageStorage,
    *,
    novel_id: str,
    entity_id: str,
    image_version: str,
) -> int:
    referenced = await db.scalar(
        select(CoreEntity.id).where(
            CoreEntity.novel_id == uuid.UUID(str(novel_id)),
            CoreEntity.id == uuid.UUID(str(entity_id)),
            CoreEntity.image_version == uuid.UUID(str(image_version)),
        )
    )
    if referenced is not None:
        return 0
    for variant in ("thumbnail", "full"):
        await storage.delete_object(
            image_object_key(novel_id, entity_id, image_version, variant)
        )
    return 2
