"""图片请求幂等复用（B9）测试：哈希租户隔离、损坏校验、force 绕过、复用命中。"""

from __future__ import annotations

import base64
import hashlib
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.image_request_reuse import (
    compute_request_hash,
    find_reusable_asset,
    invalidate_reusable_asset,
    record_reusable_asset,
)
from modules.world.models import CoreEntity
from modules.world.models.image_candidate import WorldObjectImageCandidate
from modules.world.world_object_image_generation import (
    WorldObjectImageCandidate,
    _world_object_request_hash,
)

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC"
)


# ============================================================
# 幂等键
# ============================================================


def test_request_hash_isolates_tenants_and_state() -> None:
    base = compute_request_hash(
        novel_id="11111111-1111-1111-1111-111111111111",
        owner_id="22222222-2222-2222-2222-222222222222",
        state_snapshot_hash="abc",
        prompt="港口城市鸟瞰",
        model="gpt-image-2",
    )
    other_novel = compute_request_hash(
        novel_id="33333333-3333-3333-3333-333333333333",
        owner_id="22222222-2222-2222-2222-222222222222",
        state_snapshot_hash="abc",
        prompt="港口城市鸟瞰",
        model="gpt-image-2",
    )
    other_state = compute_request_hash(
        novel_id="11111111-1111-1111-1111-111111111111",
        owner_id="22222222-2222-2222-2222-222222222222",
        state_snapshot_hash="changed",
        prompt="港口城市鸟瞰",
        model="gpt-image-2",
    )
    other_prompt = compute_request_hash(
        novel_id="11111111-1111-1111-1111-111111111111",
        owner_id="22222222-2222-2222-2222-222222222222",
        state_snapshot_hash="abc",
        prompt="另一张图",
        model="gpt-image-2",
    )
    other_model = compute_request_hash(
        novel_id="11111111-1111-1111-1111-111111111111",
        owner_id="22222222-2222-2222-2222-222222222222",
        state_snapshot_hash="abc",
        prompt="港口城市鸟瞰",
        model="local-cli",
    )

    assert len({base, other_novel, other_state, other_prompt, other_model}) == 5


# ============================================================
# 复用服务：命中 / 跨项目不命中 / 损坏 / force
# ============================================================


def _owner() -> str:
    return "22222222-2222-2222-2222-222222222222"


@pytest.mark.asyncio
async def test_reuse_hit_and_cross_project_miss(db_session, test_project_id, project_factory) -> None:
    other_novel = str(await project_factory.create_project(title="另一本"))

    async def validator(row) -> tuple:
        return _PNG, hashlib.sha256(_PNG).hexdigest(), 1, 1

    request_hash = "a" * 64
    await record_reusable_asset(
        db_session,
        novel_id=test_project_id,
        owner_id=_owner(),
        request_hash=request_hash,
        source_type="map_atlas",
        object_key="map-atlas/x/pages/y/attempts/t/image.png",
        asset_sha256=hashlib.sha256(_PNG).hexdigest(),
        byte_size=len(_PNG),
    )

    hit = await find_reusable_asset(
        db_session,
        novel_id=test_project_id,
        owner_id=_owner(),
        request_hash=request_hash,
        validate_asset=validator,
    )
    assert hit is not None
    assert hit["reuse_count_source"] if "reuse_count_source" in hit else True
    assert hit["object_key"].startswith("map-atlas/")

    # 跨项目同参数不命中（租户维度在哈希与查询双保险里）
    miss = await find_reusable_asset(
        db_session,
        novel_id=other_novel,
        owner_id=_owner(),
        request_hash=request_hash,
        validate_asset=validator,
    )
    assert miss is None


@pytest.mark.asyncio
async def test_corrupt_asset_is_deleted_and_treated_as_miss(
    db_session, test_project_id
) -> None:
    request_hash = "b" * 64
    row = await record_reusable_asset(
        db_session,
        novel_id=test_project_id,
        owner_id=_owner(),
        request_hash=request_hash,
        source_type="map_atlas",
        object_key="map-atlas/x/pages/y/image.png",
        asset_sha256=hashlib.sha256(_PNG).hexdigest(),
        byte_size=len(_PNG),
    )

    async def broken_validator(row_) -> tuple | None:
        return None  # 资产缺失/损坏

    miss = await find_reusable_asset(
        db_session,
        novel_id=test_project_id,
        owner_id=_owner(),
        request_hash=request_hash,
        validate_asset=broken_validator,
    )
    assert miss is None

    # 记录被删除：再次查询（修复后的校验器）仍按未命中
    async def healthy_validator(row_) -> tuple:
        return _PNG, hashlib.sha256(_PNG).hexdigest(), 1, 1

    still_miss = await find_reusable_asset(
        db_session,
        novel_id=test_project_id,
        owner_id=_owner(),
        request_hash=request_hash,
        validate_asset=healthy_validator,
    )
    assert still_miss is None
    assert row.id


@pytest.mark.asyncio
async def test_sha_mismatch_is_rejected(db_session, test_project_id) -> None:
    request_hash = "c" * 64
    await record_reusable_asset(
        db_session,
        novel_id=test_project_id,
        owner_id=_owner(),
        request_hash=request_hash,
        source_type="map_atlas",
        object_key="map-atlas/x/pages/y/image.png",
        asset_sha256="0" * 64,
        byte_size=len(_PNG),
    )

    async def validator(row) -> tuple:
        return _PNG, hashlib.sha256(_PNG).hexdigest(), 1, 1

    miss = await find_reusable_asset(
        db_session,
        novel_id=test_project_id,
        owner_id=_owner(),
        request_hash=request_hash,
        validate_asset=validator,
    )
    assert miss is None


@pytest.mark.asyncio
async def test_force_invalidate_and_record_overwrite(db_session, test_project_id) -> None:
    request_hash = "d" * 64

    async def validator(row) -> tuple:
        return _PNG, hashlib.sha256(_PNG).hexdigest(), 1, 1

    await record_reusable_asset(
        db_session,
        novel_id=test_project_id,
        owner_id=_owner(),
        request_hash=request_hash,
        source_type="map_atlas",
        object_key="old-key",
    )
    await invalidate_reusable_asset(
        db_session, novel_id=test_project_id, request_hash=request_hash
    )
    assert (
        await find_reusable_asset(
            db_session,
            novel_id=test_project_id,
            owner_id=_owner(),
            request_hash=request_hash,
            validate_asset=validator,
        )
        is None
    )

    # 重新生成后覆盖登记，键唯一不冲突
    await record_reusable_asset(
        db_session,
        novel_id=test_project_id,
        owner_id=_owner(),
        request_hash=request_hash,
        source_type="map_atlas",
        object_key="new-key",
    )
    hit = await find_reusable_asset(
        db_session,
        novel_id=test_project_id,
        owner_id=_owner(),
        request_hash=request_hash,
        validate_asset=validator,
    )
    assert hit is not None and hit["object_key"] == "new-key"


# ============================================================
# 世界对象路径：命中复用不排队；force 重新排队
# ============================================================


@pytest.mark.asyncio
async def test_world_object_candidate_reuses_and_force_refreshes(
    async_client, db_session, test_project_id, test_character_id, monkeypatch
) -> None:
    from modules.local_agent.facade import AgentExecutor

    from modules.account.facade import current_account_id

    owner = str(current_account_id())

    # 预置一个来源候选（含资产）与复用登记，模拟上一次成功生成。
    from sqlalchemy import select as _select

    entity = (
        await db_session.execute(
            _select(CoreEntity).where(CoreEntity.id == uuid.UUID(test_character_id))
        )
    ).scalar_one()
    source = WorldObjectImageCandidate(
        novel_id=uuid.UUID(test_project_id),
        entity_id=uuid.UUID(test_character_id),
        owner_id=uuid.UUID(owner),
        status="review_ready",
        prompt="半身像，写实风格",
        executor_json={"kind": "pi", "device_id": "device-1"},
        image_data=_PNG,
        width=1,
        height=1,
        sha256=hashlib.sha256(_PNG).hexdigest(),
    )
    db_session.add(source)
    await db_session.flush()
    executor = AgentExecutor(kind="pi", device_id="device-1")
    request_hash = _world_object_request_hash(
        novel_id=test_project_id,
        owner_id=owner,
        entity=entity,
        prompt="半身像，写实风格",
        executor=executor,
    )
    await record_reusable_asset(
        db_session,
        novel_id=test_project_id,
        owner_id=owner,
        request_hash=request_hash,
        source_type="world_object",
        object_key=f"world-object-candidate:{source.id}",
        asset_sha256=hashlib.sha256(_PNG).hexdigest(),
        byte_size=len(_PNG),
        created_from_id=source.id,
    )
    await db_session.commit()

    # 配对执行器（force 路径需要）
    created_pair = await async_client.post(
        "/api/local-agent/devices/pair",
        json={"novel_id": test_project_id, "name": "作者的 Mac"},
    )
    assert created_pair.status_code == 200, created_pair.text
    paired = await async_client.post(
        "/api/local-agent/companion/activate",
        json={"code": created_pair.json()["code"]},
    )
    device_id = paired.json()["device_id"]
    selected = await async_client.put(
        "/api/local-agent/executor",
        json={"novel_id": test_project_id, "kind": "pi", "device_id": device_id},
    )
    assert selected.status_code == 200, selected.text

    # 同参数第二次请求：直接得到 review_ready 副本，不排队（外部调用为 0）。
    reused = await async_client.post(
        f"/api/world/entities/{test_character_id}/image-candidates",
        json={"novel_id": test_project_id, "prompt": "半身像，写实风格"},
    )
    assert reused.status_code == 200, reused.text
    body = reused.json()
    assert body["status"] == "review_ready"
    assert not body.get("task_id")

    # 「重新生成」绕过复用：重新排队。
    forced = await async_client.post(
        f"/api/world/entities/{test_character_id}/image-candidates",
        json={
            "novel_id": test_project_id,
            "prompt": "半身像，写实风格",
            "force_refresh": True,
        },
    )
    assert forced.status_code == 200, forced.text
    forced_body = forced.json()
    assert forced_body["status"] == "queued"
    assert forced_body["task_id"]


# ============================================================
# 地图册幂等键：状态快照敏感
# ============================================================


def test_map_atlas_page_request_hash_reacts_to_state_snapshot() -> None:
    from types import SimpleNamespace

    run = SimpleNamespace(
        novel_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        layout="landscape",
        quality="fine",
    )
    def _page(**overrides):
        fields = {
            "visual_brief": "港口鸟瞰",
            "prompt": "港口城市鸟瞰图",
            "source_geometry_hash": "g1",
            "edit_instruction": None,
            "reference_page_ids": [],
            "source_manifest": [],
            "mask_object_key": None,
            "derived_from_page_id": None,
            "model": "gpt-image-2",
        }
        fields.update(overrides)
        return SimpleNamespace(**fields)

    page_a = _page()
    page_b = _page(source_geometry_hash="g2")
    page_c = _page(edit_instruction="去掉船只")

    owner = "22222222-2222-2222-2222-222222222222"
    hash_a = _map_atlas_hash(run, page_a, owner)
    hash_b = _map_atlas_hash(run, page_b, owner)
    hash_c = _map_atlas_hash(run, page_c, owner)

    assert len({hash_a, hash_b, hash_c}) == 3


def _map_atlas_hash(run, page, owner: str) -> str:
    from modules.world.map_atlas_workflow import _page_request_hash

    return _page_request_hash(run, page, owner_id=owner, provider="openai")
