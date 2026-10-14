"""Owner-scoped, read-only image export manifest for author backup packages.

G4b 作者手动导出图片包的服务层：只读清单行 + 窄 mask 读取。清单行提供
``deploy/scripts/object_backup.py`` 对 ``author_export`` 行要求的全部字段
（bucket/key/content_type/sha256/byte_size），浏览器打包器再按行经既有图片
读取端点逐张拉取、校验并写入 ZIP。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from core.errors import NotFoundError
from modules.world.map_atlas_models import MapAtlasPage
from modules.world.map_atlas_storage import (
    MapAtlasStorage,
    require_owned_page_object_key,
)
from modules.world.models import CoreEntity
from modules.world.world_object_images import image_object_key
from shared.utils import parse_uuid

# 与 ``MapAtlasService.read_page_image`` 的读取门禁保持一致：只有 uploaded
# （生成完成的瞬态）与 review_ready 页有可读图片。G4a 的引用 SQL
# （object_references.sql）计入所有 ``object_key IS NOT NULL`` 的页，其中
# prepared/failed/prompt_only 页没有可读对象；导出集合是引用集合的子集，
# 恢复对账（require_target_references 只要求清单 ⊆ 目标 DB 引用）不受影响。
READABLE_PAGE_GENERATION_STATES = ("uploaded", "review_ready")

ExportCategory = Literal["map_page", "map_mask", "world_full", "world_thumbnail"]


class ImageExportObject(BaseModel):
    """一行可直接进入 author_export 清单的对象引用与拉取信息。

    ``page_id``/``entity_id``/``image_version`` 只服务于浏览器端经既有
    owner 门禁读取端点逐张拉取；``title`` 仅供打包器生成作者可读文件名。
    """

    model_config = {"extra": "forbid"}

    novel_id: str
    category: ExportCategory
    bucket: str
    key: str
    content_type: str
    sha256: str | None = None
    byte_size: int | None = None
    page_id: str | None = None
    entity_id: str | None = None
    image_version: str | None = None
    title: str | None = None


class ImageExportManifest(BaseModel):
    model_config = {"extra": "forbid"}

    novel_id: str
    objects: list[ImageExportObject]


def _map_page_row(page: MapAtlasPage, novel_id: str, bucket: str) -> ImageExportObject:
    return ImageExportObject(
        novel_id=novel_id,
        category="map_page",
        bucket=bucket,
        key=page.object_key or "",
        content_type=page.media_type or "image/png",
        sha256=page.sha256,
        byte_size=page.byte_size,
        page_id=str(page.id),
        title=page.title,
    )


def _map_mask_row(page: MapAtlasPage, novel_id: str, bucket: str) -> ImageExportObject:
    return ImageExportObject(
        novel_id=novel_id,
        category="map_mask",
        bucket=bucket,
        key=page.mask_object_key or "",
        content_type="image/png",
        page_id=str(page.id),
        title=page.title,
    )


async def build_image_export_manifest(
    db: AsyncSession,
    novel_id: str,
) -> ImageExportManifest:
    """List every author-exportable object row for one project.

    地图页覆盖全部 review 状态（candidate/adopted/rejected/deprecated），
    世界对象含归档（deprecated）对象的 full 与 thumbnail 两个变体；
    mask 与 G4a 引用 SQL 同口径：凡 ``mask_object_key`` 非空即列入。
    """
    nid = parse_uuid(novel_id, "novel_id")
    settings = get_settings()
    map_bucket = settings.map_atlas_s3_bucket.strip()
    world_bucket = settings.world_object_s3_bucket.strip()
    rows: list[ImageExportObject] = []

    pages = (
        (
            await db.execute(
                select(MapAtlasPage)
                .where(
                    MapAtlasPage.novel_id == nid,
                    or_(
                        and_(
                            MapAtlasPage.object_key.isnot(None),
                            MapAtlasPage.generation_status.in_(
                                READABLE_PAGE_GENERATION_STATES
                            ),
                        ),
                        MapAtlasPage.mask_object_key.isnot(None),
                    ),
                )
                .order_by(MapAtlasPage.created_at, MapAtlasPage.id)
            )
        )
        .scalars()
        .all()
    )
    for page in pages:
        if page.object_key and page.generation_status in (
            READABLE_PAGE_GENERATION_STATES
        ):
            rows.append(_map_page_row(page, novel_id, map_bucket))
        if page.mask_object_key:
            rows.append(_map_mask_row(page, novel_id, map_bucket))

    entities = (
        (
            await db.execute(
                select(CoreEntity)
                .where(
                    CoreEntity.novel_id == nid,
                    CoreEntity.image_version.isnot(None),
                )
                .order_by(CoreEntity.name, CoreEntity.id)
            )
        )
        .scalars()
        .all()
    )
    for entity in entities:
        for variant in ("full", "thumbnail"):
            rows.append(
                ImageExportObject(
                    novel_id=novel_id,
                    category=f"world_{variant}",  # type: ignore[arg-type]
                    bucket=world_bucket,
                    key=image_object_key(
                        novel_id, str(entity.id), str(entity.image_version), variant
                    ),
                    content_type="image/webp",
                    entity_id=str(entity.id),
                    image_version=str(entity.image_version),
                    title=entity.name,
                )
            )

    return ImageExportManifest(novel_id=str(nid), objects=rows)


async def read_page_mask(
    db: AsyncSession,
    novel_id: str,
    page_id: str,
    *,
    storage: MapAtlasStorage | None = None,
) -> AsyncIterator[bytes]:
    """Stream one page mask under the same owner + novel_id gate as the manifest."""
    nid = parse_uuid(novel_id, "novel_id")
    pid = parse_uuid(page_id, "page_id")
    page = (
        await db.execute(
            select(MapAtlasPage).where(
                MapAtlasPage.novel_id == nid,
                MapAtlasPage.id == pid,
            )
        )
    ).scalar_one_or_none()
    if page is None or not page.mask_object_key:
        raise NotFoundError("地图蒙版不存在")
    key = require_owned_page_object_key(page.mask_object_key, novel_id, page_id)
    reader = storage or MapAtlasStorage()
    return reader.iter_png_chunks(key)
