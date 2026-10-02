"""图片请求幂等复用（B9）测试：哈希租户隔离、损坏校验、force 绕过、复用命中。"""

from __future__ import annotations

import base64
import hashlib
import uuid

import pytest

from modules.world.image_request_reuse import (
    compute_request_hash,
    find_reusable_asset,
    invalidate_reusable_asset,
    record_reusable_asset,
)
from modules.world.models import CoreEntity
from modules.world.models.image_candidate import WorldObjectImageCandidate
from modules.world.world_object_image_generation import _world_object_request_hash

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
async def test_reuse_hit_and_cross_project_miss(
    db_session, test_project_id, project_factory
) -> None:
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
    assert hit["object_key"].startswith("map-atlas/")
    assert hit["asset"] == _PNG

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
    from modules.account.facade import current_account_id
    from modules.local_agent.facade import AgentExecutor

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

    from modules.world.map_atlas_workflow import _page_request_hash

    def with_inputs(reference=b"base", mask=b"left"):
        return _page_request_hash(
            run,
            page_a,
            owner_id=owner,
            provider="openai",
            references=[("reference.png", reference, "image/png")],
            mask=("mask.png", mask, "image/png"),
        )

    assert with_inputs() == with_inputs()
    assert (
        len({with_inputs(), with_inputs(mask=b"right"), with_inputs(reference=b"new")})
        == 3
    )


def _map_atlas_hash(run, page, owner: str) -> str:
    from modules.world.map_atlas_workflow import _page_request_hash

    return _page_request_hash(run, page, owner_id=owner, provider="openai")


# ============================================================
# 地图册付费路径：命中复用零外部调用；regenerate 绕过并重新登记（P1-6）
# ============================================================


@pytest.mark.asyncio
async def test_map_atlas_page_reuses_without_provider_call(
    db_session, test_project_id, monkeypatch
) -> None:
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock, patch

    from infrastructure.llm.image_client import GeneratedImage
    from infrastructure.tasks.models import AsyncTask
    from modules.world.map_atlas_models import MapAtlasNode, MapAtlasPage, MapAtlasRun
    from modules.world.map_atlas_storage import MapAtlasStorage, validate_png
    from modules.world.map_atlas_workflow import _generate_page, _page_request_hash
    from modules.world.tests.test_map_atlas import OPAQUE_PNG

    novel_uuid = uuid.UUID(test_project_id)
    task = AsyncTask(
        task_type="map_atlas_generate",
        novel_id=novel_uuid,
        status="running",
        attempt=1,
        lease_id=str(uuid.uuid4()),
        recovery_policy="manual_resume",
        meta={},
    )
    db_session.add(task)
    await db_session.flush()
    run = MapAtlasRun(
        novel_id=novel_uuid,
        task_id=task.id,
        run_kind="initial",
        status="generating",
        layout="portrait",
        quality="standard",
    )
    db_session.add(run)
    await db_session.flush()
    task.meta = {"novel_id": test_project_id, "run_id": str(run.id)}
    node = MapAtlasNode(
        novel_id=novel_uuid,
        created_by_run_id=run.id,
        semantic_key="world",
        title="世界",
        level="world",
    )
    db_session.add(node)
    await db_session.flush()
    page = MapAtlasPage(
        novel_id=novel_uuid,
        run_id=run.id,
        node_id=node.id,
        generation_status="prepared",
        title="世界",
        visual_brief="世界地图",
        prompt="no text",
        source_geometry_hash="geom-1",
    )
    db_session.add(page)
    await db_session.commit()

    objects: dict[str, bytes] = {}
    storage = MagicMock(spec=MapAtlasStorage)

    async def get_if_exists(key: str) -> bytes | None:
        return objects.get(key)

    async def put_png(key: str, payload: bytes):
        objects[key] = payload
        return validate_png(payload)

    storage.get_png_if_exists = AsyncMock(side_effect=get_if_exists)
    storage.put_png = AsyncMock(side_effect=put_png)
    storage.delete_object = AsyncMock(side_effect=lambda key: objects.pop(key, None))

    # 预置复用登记：旧对象已存在且校验信息一致。
    from modules.account.facade import current_account_id

    owner = str(current_account_id())
    legacy_key = (
        f"map-atlas/{novel_uuid}/pages/{uuid.uuid4()}/attempts/legacy-1/image.png"
    )
    objects[legacy_key] = OPAQUE_PNG
    legacy_meta = validate_png(OPAQUE_PNG)
    request_hash = _page_request_hash(run, page, owner_id=owner, provider="openai")
    await record_reusable_asset(
        db_session,
        novel_id=test_project_id,
        owner_id=owner,
        request_hash=request_hash,
        source_type="map_atlas",
        object_key=legacy_key,
        asset_sha256=legacy_meta.sha256,
        byte_size=len(OPAQUE_PNG),
        width=legacy_meta.width,
        height=legacy_meta.height,
    )
    await db_session.commit()

    image_client = SimpleNamespace(
        generate=AsyncMock(return_value=GeneratedImage(OPAQUE_PNG, "request-1")),
        edit=AsyncMock(return_value=GeneratedImage(OPAQUE_PNG, "request-1")),
    )

    @asynccontextmanager
    async def image_client_context(*_args, **_kwargs):
        yield image_client

    with (
        patch(
            "modules.world.map_atlas_workflow.MapAtlasStorage",
            autospec=True,
            return_value=storage,
        ),
        patch(
            "modules.world.map_atlas_workflow.open_project_image_client",
            autospec=True,
        ) as open_client,
    ):
        open_client.side_effect = image_client_context
        assert await _generate_page(db_session, task, run, page)

    await db_session.refresh(page)
    assert page.generation_status == "review_ready"
    # 付费路径验收：同参数第二次请求的外部调用计数为 0。
    assert image_client.generate.await_count == 0
    assert image_client.edit.await_count == 0
    assert (page.evidence or {}).get("image_reuse", {}).get("reused") is True
    assert page.sha256 == legacy_meta.sha256
    assert page.object_key != legacy_key  # 复制到本页 attempt key
    assert page.object_key in objects

    # regenerate（派生页、无修改要求）绕过复用：真实调用 provider 并重新登记。
    derived = MapAtlasPage(
        novel_id=novel_uuid,
        run_id=run.id,
        node_id=node.id,
        derived_from_page_id=page.id,
        generation_status="prepared",
        title="世界",
        visual_brief="世界地图",
        prompt="no text",
        source_geometry_hash="geom-1",
    )
    db_session.add(derived)
    run.task_id = task.id
    await db_session.commit()

    second_task = AsyncTask(
        task_type="map_atlas_generate",
        novel_id=novel_uuid,
        status="running",
        attempt=2,
        lease_id=str(uuid.uuid4()),
        recovery_policy="manual_resume",
        meta={"novel_id": test_project_id, "run_id": str(run.id)},
    )
    db_session.add(second_task)
    await db_session.flush()
    derived.run_id = run.id
    run.task_id = second_task.id
    await db_session.commit()

    with (
        patch(
            "modules.world.map_atlas_workflow.MapAtlasStorage",
            autospec=True,
            return_value=storage,
        ),
        patch(
            "modules.world.map_atlas_workflow.open_project_image_client",
            autospec=True,
        ) as open_client2,
    ):
        open_client2.side_effect = image_client_context
        assert await _generate_page(db_session, second_task, run, derived)

    await db_session.refresh(derived)
    assert derived.generation_status == "review_ready"
    # 派生页（regenerate）有 derived_from_page_id，走 edit 调用路径。
    assert image_client.edit.await_count == 1
    assert image_client.generate.await_count == 0
    assert not (derived.evidence or {}).get("image_reuse", {}).get("reused")


@pytest.mark.parametrize("stale_registration", [False, True])
async def test_world_object_reuse_never_returns_another_entity(
    db_session,
    test_project_id,
    test_character_id,
    test_entity_id,
    monkeypatch,
    stale_registration,
) -> None:
    from modules.account.facade import current_account_id
    from modules.local_agent.facade import AgentExecutor
    from modules.world.world_object_image_generation import (
        WorldObjectImageCandidateCreate,
        WorldObjectImageGenerationService,
    )

    owner = str(current_account_id())
    source_entity = await db_session.get(CoreEntity, uuid.UUID(test_character_id))
    target = await db_session.get(CoreEntity, uuid.UUID(test_entity_id))
    executor = AgentExecutor(kind="pi", device_id=str(uuid.uuid4()))
    source = WorldObjectImageCandidate(
        novel_id=source_entity.novel_id,
        entity_id=source_entity.id,
        owner_id=uuid.UUID(owner),
        status="review_ready",
        prompt="写实半身像",
        executor_json={"kind": "pi"},
        image_data=_PNG,
        width=1,
        height=1,
        sha256=hashlib.sha256(_PNG).hexdigest(),
    )
    db_session.add(source)
    await db_session.flush()

    def request_hash(entity):
        return _world_object_request_hash(
            novel_id=test_project_id,
            owner_id=owner,
            entity=entity,
            prompt=source.prompt,
            executor=executor,
        )

    assert request_hash(source_entity) != request_hash(target)
    await record_reusable_asset(
        db_session,
        novel_id=test_project_id,
        owner_id=owner,
        request_hash=request_hash(target if stale_registration else source_entity),
        source_type="world_object",
        object_key=f"world-object-candidate:{source.id}",
        asset_sha256=source.sha256,
        byte_size=len(_PNG),
        created_from_id=source.id,
    )

    async def selected(*_args, **_kwargs):
        return executor

    monkeypatch.setattr(
        "modules.world.world_object_image_generation.selected_executor", selected
    )
    view = await WorldObjectImageGenerationService().create_candidate(
        db_session,
        novel_id=test_project_id,
        entity_id=test_entity_id,
        owner_id=owner,
        data=WorldObjectImageCandidateCreate(
            novel_id=test_project_id, prompt=source.prompt
        ),
    )
    assert view.entity_id == test_entity_id
    assert view.status == "queued"
    assert view.reused is False


async def test_reuse_insert_conflict_keeps_caller_writes(
    db_session,
    test_project_id,
    test_character_id,
    monkeypatch,
) -> None:
    from types import SimpleNamespace

    from sqlalchemy import select

    from modules.account.facade import current_account_id

    owner = str(current_account_id())
    candidate = WorldObjectImageCandidate(
        novel_id=uuid.UUID(test_project_id),
        entity_id=uuid.UUID(test_character_id),
        owner_id=uuid.UUID(owner),
        status="generating",
        prompt="offline",
        executor_json={"kind": "pi"},
    )
    db_session.add(candidate)
    await record_reusable_asset(
        db_session,
        novel_id=test_project_id,
        owner_id=owner,
        request_hash="e" * 64,
        source_type="world_object",
        object_key="previous.png",
    )
    await db_session.commit()
    candidate_id = candidate.id
    candidate.status = "review_ready"
    candidate.image_data = _PNG
    execute = db_session.execute
    stale_read = True

    async def race(*args, **kwargs):
        nonlocal stale_read
        if stale_read:
            stale_read = False
            return SimpleNamespace(scalar_one_or_none=lambda: None)
        return await execute(*args, **kwargs)

    monkeypatch.setattr(db_session, "execute", race)
    await record_reusable_asset(
        db_session,
        novel_id=test_project_id,
        owner_id=owner,
        request_hash="e" * 64,
        source_type="world_object",
        object_key="new.png",
        created_from_id=candidate_id,
    )
    await db_session.commit()
    status, data = (
        await db_session.execute(
            select(
                WorldObjectImageCandidate.status, WorldObjectImageCandidate.image_data
            ).where(WorldObjectImageCandidate.id == candidate_id)
        )
    ).one()
    assert status == "review_ready"
    assert data == _PNG
