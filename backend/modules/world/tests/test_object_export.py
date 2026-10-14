"""G4b 作者手动导出图片包：只读清单端点与窄 mask 读取的门禁与口径。"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import AccountPrincipal
from modules.world import object_export
from modules.world.map_atlas_models import MapAtlasNode, MapAtlasPage, MapAtlasRun
from modules.world.map_atlas_storage import page_object_key
from modules.world.models import CoreEntity
from tests.utils import _create_project

PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080200000090"
    "7753de0000000c4944415408d763f8cfc00000030101"
    "00c9fe92ef0000000049454e44ae426082"
)


class MemoryAtlasStorage:
    """Test double holding one page's objects in memory."""

    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects
        self.read_keys: list[str] = []

    async def iter_png_chunks(self, key: str, *, chunk_size: int = 64 * 1024):
        self.read_keys.append(key)
        payload = self.objects[key]
        for offset in range(0, len(payload), chunk_size):
            yield payload[offset : offset + chunk_size]


def _png_sha() -> str:
    return hashlib.sha256(PNG_BYTES).hexdigest()


async def _map_page(
    db: AsyncSession,
    novel_id: str,
    *,
    review_status: str = "candidate",
    generation_status: str = "review_ready",
    object_key: str | None = None,
    mask_object_key: str | None = None,
    title: str = "地图页",
    sha256: str | None = None,
    byte_size: int | None = None,
    page_id: uuid.UUID | None = None,
) -> str:
    nid = uuid.UUID(hex=novel_id) if len(novel_id) == 32 else uuid.UUID(novel_id)
    run = MapAtlasRun(novel_id=nid, run_kind="initial", status="completed")
    db.add(run)
    await db.flush()
    node = MapAtlasNode(
        novel_id=nid,
        created_by_run_id=run.id,
        semantic_key=f"node:{uuid.uuid4()}",
        title=title,
        level="region",
        status="adopted",
    )
    db.add(node)
    await db.flush()
    page = MapAtlasPage(
        id=page_id or uuid.uuid4(),
        novel_id=nid,
        run_id=run.id,
        node_id=node.id,
        generation_status=generation_status,
        review_status=review_status,
        title=title,
        visual_brief="测试",
        prompt="测试",
        object_key=object_key,
        mask_object_key=mask_object_key,
        sha256=sha256,
        media_type="image/png" if object_key else None,
        byte_size=byte_size,
    )
    db.add(page)
    await db.flush()
    return str(page.id)


async def _entity_with_image(
    db: AsyncSession,
    novel_id: str,
    name: str,
    *,
    status: str = "canonical",
) -> tuple[str, str]:
    nid = uuid.UUID(hex=novel_id) if len(novel_id) == 32 else uuid.UUID(novel_id)
    version = uuid.uuid4()
    entity = CoreEntity(
        id=uuid.uuid4(),
        novel_id=nid,
        entity_type="character",
        name=name,
        summary=name,
        status=status,
        image_version=version,
    )
    db.add(entity)
    await db.flush()
    return str(entity.id), str(version)


@pytest.fixture
def export_buckets(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    from dataclasses import replace

    from core.config import get_settings

    buckets = {"map": "test-map-bucket", "world": "test-world-bucket"}
    settings = replace(
        get_settings(),
        map_atlas_s3_bucket=buckets["map"],
        world_object_s3_bucket=buckets["world"],
    )
    monkeypatch.setattr(
        "modules.world.object_export.get_settings", lambda: settings
    )
    return buckets


async def test_export_manifest_lists_readable_pages_masks_and_world_variants(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_project_id: str,
    export_buckets: dict[str, str],
) -> None:
    """清单覆盖全部 review 状态的地图页、mask 与含归档对象的两变体。"""
    nid = test_project_id
    adopted_key = page_object_key(nid, "44444444-4444-4444-8444-000000000001")
    rejected_key = page_object_key(nid, "44444444-4444-4444-8444-000000000002")
    transient_key = page_object_key(nid, "44444444-4444-4444-8444-000000000003")
    prepared_key = page_object_key(nid, "44444444-4444-4444-8444-000000000004")
    adopted_id = await _map_page(
        db_session,
        nid,
        review_status="adopted",
        object_key=adopted_key,
        sha256=_png_sha(),
        byte_size=len(PNG_BYTES),
        title="主世界",
    )
    await _map_page(
        db_session,
        nid,
        review_status="rejected",
        object_key=rejected_key,
        sha256=_png_sha(),
        byte_size=len(PNG_BYTES),
        title="废弃稿",
    )
    await _map_page(
        db_session,
        nid,
        generation_status="uploaded",
        object_key=transient_key,
        title="刚传完",
    )
    await _map_page(
        db_session,
        nid,
        generation_status="prepared",
        object_key=prepared_key,
        mask_object_key=page_object_key(
            nid, "44444444-4444-4444-8444-000000000004", mask=True
        ),
        title="编辑中",
    )
    entity_id, version = await _entity_with_image(db_session, nid, "主角")
    await _entity_with_image(db_session, nid, "旧反派", status="deprecated")

    no_image = CoreEntity(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(test_project_id),
        entity_type="item",
        name="无图道具",
        summary="无图",
        status="canonical",
    )
    db_session.add(no_image)
    await db_session.flush()

    response = await async_client.get(f"/api/world/{nid}/image-export")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    payload = response.json()
    assert payload["novel_id"] == str(uuid.UUID(test_project_id))
    rows = {(row["category"], row["key"]): row for row in payload["objects"]}

    novel_uuid = uuid.UUID(test_project_id)
    protagonist_full = (
        f"world-objects/{novel_uuid}/entities/"
        f"{uuid.UUID(entity_id)}/images/{uuid.UUID(version)}/full.webp"
    )
    assert set(rows) >= {
        ("map_page", adopted_key),
        ("map_page", rejected_key),
        ("map_page", transient_key),
        ("map_mask", page_object_key(
            nid, "44444444-4444-4444-8444-000000000004", mask=True
        )),
        ("world_full", protagonist_full),
        ("world_thumbnail", protagonist_full.replace("/full.webp", "/thumbnail.webp")),
    }
    by_category: dict[str, list[dict[str, Any]]] = {}
    for row in payload["objects"]:
        by_category.setdefault(row["category"], []).append(row)
    assert len(by_category["world_full"]) == 2  # 主角 + 归档旧反派
    assert len(by_category["world_thumbnail"]) == 2
    assert len(by_category["map_page"]) == 3
    assert len(by_category["map_mask"]) == 1
    world_keys = [row["key"] for row in by_category["world_full"]]
    assert all(key.startswith(f"world-objects/{novel_uuid}/") for key in world_keys)
    assert len(set(world_keys)) == 2

    adopted_row = rows[("map_page", adopted_key)]
    assert adopted_row["sha256"] == _png_sha()
    assert adopted_row["byte_size"] == len(PNG_BYTES)
    assert adopted_row["content_type"] == "image/png"
    assert adopted_row["page_id"] == adopted_id
    assert adopted_row["title"] == "主世界"
    assert adopted_row["bucket"] == export_buckets["map"]

    mask_row = next(iter(by_category["map_mask"]))
    assert mask_row["content_type"] == "image/png"
    assert mask_row["sha256"] is None

    world_row = next(iter(by_category["world_full"]))
    assert world_row["content_type"] == "image/webp"
    assert world_row["bucket"] == export_buckets["world"]
    assert world_row["entity_id"] == entity_id
    assert world_row["image_version"] == version
    assert world_row["title"] in {"主角", "旧反派"}


async def test_export_manifest_empty_project(
    async_client: AsyncClient,
    test_project_id: str,
) -> None:
    response = await async_client.get(f"/api/world/{test_project_id}/image-export")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json() == {
        "novel_id": str(uuid.UUID(test_project_id)),
        "objects": [],
    }


async def test_export_manifest_stays_inside_one_project(
    async_client: AsyncClient,
    db_session: AsyncSession,
    export_buckets: dict[str, str],
) -> None:
    novel_a = uuid.uuid4().hex
    novel_b = uuid.uuid4().hex
    await _create_project(db_session, novel_a)
    await _create_project(db_session, novel_b)
    entity_id, version = await _entity_with_image(db_session, novel_a, "A 的对象")
    await _entity_with_image(db_session, novel_b, "B 的对象")

    response = await async_client.get(f"/api/world/{novel_a}/image-export")
    assert response.status_code == 200
    keys = {row["key"] for row in response.json()["objects"]}
    assert keys == {
        f"world-objects/{uuid.UUID(novel_a)}/entities/"
        f"{uuid.UUID(entity_id)}/images/{uuid.UUID(version)}/full.webp",
        f"world-objects/{uuid.UUID(novel_a)}/entities/"
        f"{uuid.UUID(entity_id)}/images/{uuid.UUID(version)}/thumbnail.webp",
    }


async def test_export_manifest_rejects_other_owner(
    async_client: AsyncClient,
    test_project_id: str,
) -> None:
    token = bind_principal(
        AccountPrincipal(
            account_id=uuid.uuid4(),
            status="active",
            identity_type="email",
            support_code="EXPORT-TEST",
        )
    )
    try:
        response = await async_client.get(f"/api/world/{test_project_id}/image-export")
        assert response.status_code == 404
    finally:
        reset_principal(token)


async def test_export_manifest_rejects_demo_readonly_principal(
    async_client: AsyncClient,
    test_project_id: str,
) -> None:
    token = bind_principal(
        AccountPrincipal(
            account_id=uuid.uuid4(),
            status="active",
            identity_type="email",
            support_code="EXPORT-TEST",
            access_scope="demo_readonly",
            demo_project_id=uuid.uuid4(),
        )
    )
    try:
        response = await async_client.get(f"/api/world/{test_project_id}/image-export")
        assert response.status_code == 404
    finally:
        reset_principal(token)


async def test_export_manifest_hides_unknown_project(
    async_client: AsyncClient,
) -> None:
    unknown = uuid.uuid4().hex
    response = await async_client.get(f"/api/world/{unknown}/image-export")
    assert response.status_code == 404


async def test_mask_read_streams_owner_page_mask_only(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_project_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mask_page_id = uuid.UUID("55555555-5555-4555-8555-000000000001")
    mask_key = page_object_key(test_project_id, str(mask_page_id), mask=True)
    page_id = await _map_page(
        db_session,
        test_project_id,
        generation_status="prepared",
        mask_object_key=mask_key,
        title="编辑中",
        page_id=mask_page_id,
    )
    await _map_page(
        db_session,
        test_project_id,
        object_key=page_object_key(
            test_project_id, "55555555-5555-4555-8555-000000000002"
        ),
        title="无蒙版页",
    )
    storage = MemoryAtlasStorage({mask_key: PNG_BYTES})
    monkeypatch.setattr(object_export, "MapAtlasStorage", lambda: storage)

    ok = await async_client.get(
        f"/api/world/{test_project_id}/image-export/pages/{page_id}/mask"
    )
    assert ok.status_code == 200
    assert ok.headers["content-type"] == "image/png"
    assert ok.headers["cache-control"] == "private, no-store"
    assert ok.content == PNG_BYTES
    assert storage.read_keys == [mask_key]

    missing = await async_client.get(
        f"/api/world/{test_project_id}/image-export/pages/"
        f"{uuid.uuid4()}/mask"
    )
    assert missing.status_code == 404

    other_novel = uuid.uuid4().hex
    await _create_project(db_session, other_novel)
    cross = await async_client.get(
        f"/api/world/{other_novel}/image-export/pages/{page_id}/mask"
    )
    assert cross.status_code == 404


async def test_mask_read_rejects_demo_readonly_principal(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    page_id = await _map_page(
        db_session,
        test_project_id,
        mask_object_key=page_object_key(
            test_project_id, "66666666-6666-4666-8666-000000000001", mask=True
        ),
    )
    token = bind_principal(
        AccountPrincipal(
            account_id=uuid.uuid4(),
            status="active",
            identity_type="email",
            support_code="EXPORT-TEST",
            access_scope="demo_readonly",
            demo_project_id=uuid.uuid4(),
        )
    )
    try:
        response = await async_client.get(
            f"/api/world/{test_project_id}/image-export/pages/{page_id}/mask"
        )
        assert response.status_code == 404
    finally:
        reset_principal(token)


async def test_build_manifest_row_shape_matches_author_export_contract(
    db_session: AsyncSession,
    test_project_id: str,
    export_buckets: dict[str, str],
) -> None:
    """author_export 行必需字段齐备：bucket/key/content_type 一个不少。"""
    object_key = page_object_key(test_project_id, "77777777-7777-4777-8777-000000000001")
    await _map_page(
        db_session,
        test_project_id,
        review_status="deprecated",
        object_key=object_key,
        sha256=_png_sha(),
        byte_size=len(PNG_BYTES),
    )
    manifest = await object_export.build_image_export_manifest(
        db_session, test_project_id
    )
    assert len(manifest.objects) == 1
    row: dict[str, Any] = manifest.objects[0].model_dump()
    assert row["category"] == "map_page"
    assert row["bucket"] == export_buckets["map"]
    assert row["key"] == object_key
    assert row["content_type"] == "image/png"
    assert row["sha256"] == _png_sha()
    assert row["byte_size"] == len(PNG_BYTES)
