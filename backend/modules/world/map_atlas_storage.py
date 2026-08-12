"""Private S3 storage owned by the AI map-atlas submodule."""

from __future__ import annotations

import asyncio
import hashlib
import struct
import uuid
import zlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from sqlalchemy import or_, select

from core.config import get_settings, validate_map_atlas_s3_endpoint_url
from modules.world.map_atlas_models import MapAtlasPage

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_IMAGE_BYTES = 50 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class PngMetadata:
    width: int
    height: int
    byte_size: int
    sha256: str
    has_alpha: bool


def validate_png(payload: bytes, *, require_alpha: bool = False) -> PngMetadata:
    """Validate a complete bounded PNG without decoding untrusted pixels."""
    if not payload or len(payload) >= MAX_IMAGE_BYTES:
        raise ValueError("PNG 必须小于 50MB")
    if len(payload) < 45 or payload[:8] != PNG_SIGNATURE:
        raise ValueError("仅支持 PNG 图片")

    offset = len(PNG_SIGNATURE)
    width = height = color_type = None
    saw_idat = saw_iend = saw_transparency = False
    chunk_index = 0
    while offset < len(payload):
        if len(payload) - offset < 12:
            raise ValueError("PNG 数据被截断")
        length = struct.unpack(">I", payload[offset : offset + 4])[0]
        chunk_type = payload[offset + 4 : offset + 8]
        chunk_end = offset + 12 + length
        if chunk_end > len(payload):
            raise ValueError("PNG 数据被截断")
        chunk_data = payload[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack(">I", payload[offset + 8 + length : chunk_end])[0]
        actual_crc = zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise ValueError("PNG 校验失败")
        if not all(
            65 <= character <= 90 or 97 <= character <= 122
            for character in chunk_type
        ):
            raise ValueError("PNG chunk 类型无效")

        if chunk_index == 0:
            if chunk_type != b"IHDR" or length != 13:
                raise ValueError("PNG 缺少有效的 IHDR")
            width, height = struct.unpack(">II", chunk_data[:8])
            bit_depth, color_type, compression, filtering, interlace = chunk_data[8:]
            allowed_depths = {
                0: {1, 2, 4, 8, 16},
                2: {8, 16},
                3: {1, 2, 4, 8},
                4: {8, 16},
                6: {8, 16},
            }
            if bit_depth not in allowed_depths.get(color_type, set()):
                raise ValueError("PNG 颜色格式无效")
            if compression != 0 or filtering != 0 or interlace not in {0, 1}:
                raise ValueError("PNG IHDR 参数无效")
        elif chunk_type == b"IHDR":
            raise ValueError("PNG 包含重复 IHDR")
        elif chunk_type == b"IDAT":
            saw_idat = True
        elif chunk_type == b"tRNS":
            if saw_idat or color_type not in {0, 2, 3}:
                raise ValueError("PNG 透明度 chunk 无效")
            saw_transparency = True
        elif chunk_type == b"IEND":
            if length != 0 or not saw_idat:
                raise ValueError("PNG IEND 无效")
            if chunk_end != len(payload):
                raise ValueError("PNG IEND 之后存在额外数据")
            saw_iend = True
            break
        offset = chunk_end
        chunk_index += 1

    if not saw_iend or width is None or height is None or color_type is None:
        raise ValueError("PNG 缺少完整 IEND")
    if width < 1 or height < 1 or width > 8192 or height > 8192:
        raise ValueError("PNG 尺寸无效")
    has_alpha = color_type in {4, 6} or saw_transparency
    if require_alpha and not has_alpha:
        raise ValueError("蒙版 PNG 必须包含 alpha 通道")
    return PngMetadata(
        width=width,
        height=height,
        byte_size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        has_alpha=has_alpha,
    )


def require_matching_mask(source: bytes, mask: bytes) -> tuple[PngMetadata, PngMetadata]:
    source_meta = validate_png(source)
    mask_meta = validate_png(mask, require_alpha=True)
    if (source_meta.width, source_meta.height) != (mask_meta.width, mask_meta.height):
        raise ValueError("蒙版必须与来源图片尺寸一致")
    return source_meta, mask_meta


def page_object_key(
    novel_id: str,
    page_id: str,
    *,
    mask: bool = False,
    attempt_token: str | None = None,
) -> str:
    novel = uuid.UUID(str(novel_id))
    page = uuid.UUID(str(page_id))
    prefix = f"map-atlas/{novel}/pages/{page}"
    if mask:
        if attempt_token is not None:
            raise ValueError("mask keys do not accept attempt tokens")
        return f"{prefix}/mask.png"
    if attempt_token is None:
        # Read compatibility for pages created before attempt-scoped uploads.
        return f"{prefix}/image.png"
    normalized = str(attempt_token).strip()
    if (
        not normalized
        or len(normalized) > 80
        or any(
            character not in "0123456789abcdefghijklmnopqrstuvwxyz-"
            for character in normalized
        )
    ):
        raise ValueError("invalid map atlas attempt token")
    return f"{prefix}/attempts/{normalized}/image.png"


def project_object_prefix(novel_id: str) -> str:
    return f"map-atlas/{uuid.UUID(str(novel_id))}/"


def require_project_object_prefix(prefix: str) -> str:
    """Accept only one canonical project prefix, never the atlas root."""
    parts = str(prefix).split("/")
    if len(parts) != 3 or parts[0] != "map-atlas" or parts[2] != "":
        raise ValueError("invalid map atlas project prefix")
    expected = project_object_prefix(parts[1])
    if prefix != expected:
        raise ValueError("invalid map atlas project prefix")
    return expected


def require_page_object_key(key: str) -> str:
    """Accept only a canonical image or mask key owned by one atlas page."""
    parts = str(key).split("/")
    if len(parts) < 5 or parts[0] != "map-atlas" or parts[2] != "pages":
        raise ValueError("invalid map atlas page object key")
    if len(parts) == 5 and parts[4] in {"image.png", "mask.png"}:
        expected = page_object_key(parts[1], parts[3], mask=parts[4] == "mask.png")
    elif len(parts) == 7 and parts[4] == "attempts" and parts[6] == "image.png":
        expected = page_object_key(parts[1], parts[3], attempt_token=parts[5])
    else:
        raise ValueError("invalid map atlas page object key")
    if key != expected:
        raise ValueError("invalid map atlas page object key")
    return expected


def require_owned_page_object_key(key: str, novel_id: str, page_id: str) -> str:
    """Require one canonical key to belong to the expected project and page."""
    canonical = require_page_object_key(key)
    owner_prefix = (
        f"map-atlas/{uuid.UUID(str(novel_id))}/pages/{uuid.UUID(str(page_id))}/"
    )
    if not canonical.startswith(owner_prefix):
        raise ValueError("map atlas page object key owner mismatch")
    return canonical


class MapAtlasStorage:
    """Small async wrapper around one synchronous boto3 S3 client."""

    def __init__(self, *, client: Any | None = None, bucket: str | None = None) -> None:
        settings = get_settings()
        self.bucket = (bucket or settings.map_atlas_s3_bucket).strip()
        if not self.bucket:
            raise RuntimeError("MAP_ATLAS_S3_BUCKET is required")
        endpoint_url = validate_map_atlas_s3_endpoint_url(
            settings.map_atlas_s3_endpoint_url
        )
        self._client = client or boto3.client(
            "s3",
            region_name=settings.map_atlas_s3_region,
            endpoint_url=endpoint_url or None,
            aws_access_key_id=settings.map_atlas_s3_access_key_id or None,
            aws_secret_access_key=settings.map_atlas_s3_secret_access_key or None,
            config=Config(
                connect_timeout=10,
                read_timeout=60,
                retries={"max_attempts": 3, "mode": "standard"},
                s3={
                    "addressing_style": (
                        "path" if settings.map_atlas_s3_force_path_style else "auto"
                    )
                },
            ),
        )

    async def put_png(self, key: str, payload: bytes) -> PngMetadata:
        metadata = validate_png(payload)
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self.bucket,
            Key=key,
            Body=payload,
            ContentType="image/png",
            Metadata={"sha256": metadata.sha256},
        )
        return metadata

    async def get_png(self, key: str) -> bytes:
        payload = b"".join([chunk async for chunk in self.iter_png_chunks(key)])
        validate_png(payload)
        return payload

    async def get_png_if_exists(self, key: str) -> bytes | None:
        try:
            return await self.get_png(key)
        except ClientError as error:
            response = error.response or {}
            code = str((response.get("Error") or {}).get("Code") or "")
            status = (response.get("ResponseMetadata") or {}).get("HTTPStatusCode")
            if code in {"404", "NoSuchKey", "NotFound"} or status == 404:
                return None
            raise

    async def iter_png_chunks(
        self,
        key: str,
        *,
        chunk_size: int = 64 * 1024,
    ) -> AsyncIterator[bytes]:
        """Stream one private object without buffering it in the API process."""
        if chunk_size < 1:
            raise ValueError("chunk_size must be positive")
        response = await asyncio.to_thread(
            self._client.get_object,
            Bucket=self.bucket,
            Key=key,
        )
        content_length = response.get("ContentLength")
        if content_length is not None and int(content_length) >= MAX_IMAGE_BYTES:
            raise ValueError("PNG 必须小于 50MB")
        body = response["Body"]
        total = 0
        try:
            while True:
                chunk = await asyncio.to_thread(body.read, chunk_size)
                if not chunk:
                    break
                total += len(chunk)
                if total >= MAX_IMAGE_BYTES:
                    raise ValueError("PNG 必须小于 50MB")
                yield chunk
        finally:
            close = getattr(body, "close", None)
            if callable(close):
                await asyncio.to_thread(close)

    async def delete_object(self, key: str) -> None:
        def delete_all_versions() -> None:
            versions_supported = True
            try:
                versions = self._list_versions(key, exact_key=key)
            except (AttributeError, NotImplementedError, ClientError) as error:
                if not self._version_listing_unsupported(error):
                    raise
                versions_supported = False
                versions = []
            if versions:
                self._delete_entries(versions)
            current = self._list_current_keys(key, exact_key=key)
            if current or not versions_supported:
                self._client.delete_object(Bucket=self.bucket, Key=key)
            if self._list_current_keys(key, exact_key=key):
                raise RuntimeError("S3 object cleanup did not converge")
            if versions_supported and self._list_versions(key, exact_key=key):
                raise RuntimeError("S3 versioned object cleanup did not converge")

        await asyncio.to_thread(delete_all_versions)

    async def delete_prefix(self, prefix: str) -> int:
        def delete_all() -> int:
            deleted = 0
            versions_supported = True
            try:
                versions = self._list_versions(prefix)
            except (AttributeError, NotImplementedError, ClientError) as error:
                if not self._version_listing_unsupported(error):
                    raise
                versions_supported = False
                versions = []
            if versions:
                self._delete_entries(versions)
                deleted += len(versions)
            while True:
                keys = self._list_current_keys(prefix)
                if not keys:
                    break
                self._delete_entries([{"Key": key} for key in keys])
                deleted += len(keys)
            if self._list_current_keys(prefix):
                raise RuntimeError("S3 prefix cleanup did not converge")
            if versions_supported and self._list_versions(prefix):
                raise RuntimeError("S3 versioned prefix cleanup did not converge")
            return deleted

        return await asyncio.to_thread(delete_all)

    def _list_current_keys(
        self,
        prefix: str,
        *,
        exact_key: str | None = None,
    ) -> list[str]:
        response = self._client.list_objects_v2(
            Bucket=self.bucket,
            Prefix=prefix,
            MaxKeys=1000,
        )
        if not isinstance(response, dict):
            return []
        return [
            str(item["Key"])
            for item in response.get("Contents", [])
            if exact_key is None or item.get("Key") == exact_key
        ]

    def _list_versions(
        self,
        prefix: str,
        *,
        exact_key: str | None = None,
    ) -> list[dict[str, str]]:
        entries: list[dict[str, str]] = []
        markers: dict[str, str] = {}
        while True:
            response = self._client.list_object_versions(
                Bucket=self.bucket,
                Prefix=prefix,
                MaxKeys=1000,
                **markers,
            )
            if not isinstance(response, dict):
                raise NotImplementedError
            for group in ("Versions", "DeleteMarkers"):
                entries.extend(
                    {"Key": str(item["Key"]), "VersionId": str(item["VersionId"])}
                    for item in response.get(group, [])
                    if exact_key is None or item.get("Key") == exact_key
                )
            if not response.get("IsTruncated"):
                return entries
            next_key = response.get("NextKeyMarker")
            next_version = response.get("NextVersionIdMarker")
            if not next_key:
                raise RuntimeError("S3 version listing returned no continuation marker")
            markers = {"KeyMarker": str(next_key)}
            if next_version:
                markers["VersionIdMarker"] = str(next_version)

    def _delete_entries(self, entries: list[dict[str, str]]) -> None:
        for offset in range(0, len(entries), 1000):
            response = self._client.delete_objects(
                Bucket=self.bucket,
                Delete={"Objects": entries[offset : offset + 1000], "Quiet": True},
            )
            errors = response.get("Errors", [])
            if errors:
                raise RuntimeError(
                    f"S3 cleanup failed for {len(errors)} object version(s)"
                )

    @staticmethod
    def _version_listing_unsupported(error: BaseException) -> bool:
        if isinstance(error, (AttributeError, NotImplementedError)):
            return True
        if not isinstance(error, ClientError):
            return False
        response = error.response or {}
        code = str((response.get("Error") or {}).get("Code") or "")
        status = (response.get("ResponseMetadata") or {}).get("HTTPStatusCode")
        return code in {"NotImplemented", "UnsupportedOperation"} or status in {
            405,
            501,
        }


async def delete_unreferenced_page_object(
    db: Any,
    storage: MapAtlasStorage,
    key: str,
) -> bool:
    """Delete one canonical object only after a fresh reference check."""
    canonical = require_page_object_key(key)
    await db.rollback()
    referenced_page_id = await db.scalar(
        select(MapAtlasPage.id)
        .where(
            or_(
                MapAtlasPage.object_key == canonical,
                MapAtlasPage.mask_object_key == canonical,
            )
        )
        .limit(1)
    )
    await db.rollback()
    if referenced_page_id is not None:
        return False
    await storage.delete_object(canonical)
    return True
