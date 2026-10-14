"""作者手动导出图片包的只读路由：导出清单与窄 mask 读取。

object key 的暴露口径（G4b 用户裁定）：不对非 owner、不经通用 API 暴露；
仅 owner + novel_id 的导出清单端点返回，响应 no-store，不写业务日志。
两个端点都以 ``allow_demo_readonly=False`` 拒绝匿名演示身份。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Response
from fastapi.responses import StreamingResponse

from core.api_params import NovelIdPath
from core.dependencies import DbSession
from modules.project.facade import require_active_project
from modules.world.api._shared import router
from modules.world.object_export import (
    ImageExportManifest,
    build_image_export_manifest,
    read_page_mask,
)


async def _require_owner_novel_id(db: DbSession, novel_id: NovelIdPath) -> str:
    await require_active_project(db, novel_id, allow_demo_readonly=False)
    return novel_id


OwnerNovelId = Annotated[str, Depends(_require_owner_novel_id)]


@router.get(
    "/{novel_id}/image-export",
    response_model=ImageExportManifest,
)
async def get_image_export_manifest(
    db: DbSession,
    novel_id: OwnerNovelId,
    response: Response,
) -> ImageExportManifest:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return await build_image_export_manifest(db, novel_id)


@router.get("/{novel_id}/image-export/pages/{page_id}/mask")
async def read_export_page_mask(
    db: DbSession,
    novel_id: OwnerNovelId,
    page_id: str,
) -> StreamingResponse:
    chunks = await read_page_mask(db, novel_id, page_id)
    return StreamingResponse(
        chunks,
        media_type="image/png",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
