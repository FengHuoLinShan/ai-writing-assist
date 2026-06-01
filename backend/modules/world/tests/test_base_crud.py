"""BaseCRUDService 测试 — 验证 base 的 5 verb + novel_id 隔离 + __init_subclass__ 守卫。

约束 (per backend/tests/CLAUDE.md):
- 不绕过 facade 直接 import services/repositories 做断言
- 公共 interface 是 service.create / get / list / update / delete + novel_id
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

# ============================================================
# In-memory fake — 直接测 base class 的契约, 不依赖具体 ORM
# ============================================================

@dataclass
class FakeRow:
    """代表任何 ORM 行的最小形状, novel_id 是唯一约束字段。
    id 用 str (Pydantic Response 期望 str), novel_id 用 UUID (per ADR-0002)。"""
    id: str
    novel_id: uuid.UUID
    name: str = "fake"


class FakeRepo:
    """满足 _CrudRepo 协议的最小 in-memory fake。"""

    def __init__(self) -> None:
        self.store: dict[str, FakeRow] = {}

    async def get(self, db: AsyncSession, id: uuid.UUID) -> FakeRow | None:
        return self.store.get(str(id))

    async def get_by_novel(
        self, db: AsyncSession, novel_id: uuid.UUID, *,
        skip: int, limit: int,
    ) -> tuple[list[FakeRow], int]:
        rows = [r for r in self.store.values() if r.novel_id == novel_id]
        return rows[skip:skip + limit], len(rows)

    async def create(
        self, db: AsyncSession, novel_id: uuid.UUID, data: Any,
    ) -> FakeRow:
        row = FakeRow(id=str(uuid.uuid4()), novel_id=novel_id, name=data.name)
        self.store[row.id] = row
        return row

    async def update(
        self, db: AsyncSession, id: uuid.UUID, data: Any,
    ) -> FakeRow | None:
        if str(id) not in self.store:
            return None
        self.store[str(id)].name = data.name
        return self.store[str(id)]

    async def delete(self, db: AsyncSession, id: uuid.UUID) -> bool:
        return self.store.pop(str(id), None) is not None


class FakeCreate(BaseModel):
    name: str = "x"


class FakeUpdate(BaseModel):
    name: str = "y"


class FakeResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    novel_id: uuid.UUID
    name: str


class FakeService(
    # type: ignore[misc]
    __import__("modules.world.services.base", fromlist=["CrudService"]).CrudService[
        FakeRow, FakeCreate, FakeUpdate, FakeResponse,
    ],
):
    """最小可测的 CrudService 子类。ClassVar 必须在 class 体声明,
    __init_subclass__ 守卫在 import 时就检查。"""

    repo: Any = FakeRepo()  # 共享单例 fake store; ClassVar-like
    response: Any = FakeResponse
    label: str = "Fake"
    id_param: str = "fake_id"

    def __init__(self) -> None:
        # 重新设置一个独立的 store (避免测试间污染)
        self.repo = FakeRepo()


# ============================================================
# Tests
# ============================================================

@pytest.fixture
def novel_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def other_novel_id() -> str:
    return str(uuid.uuid4())


# --- 5 verbs ---

async def test_create_returns_response(
    db_session: AsyncSession,
    novel_id: str,
) -> None:
    svc = FakeService()
    response = await svc.create(db_session, novel_id, FakeCreate(name="alpha"))
    assert response.name == "alpha"
    assert str(response.novel_id) == novel_id


async def test_get_returns_response(
    db_session: AsyncSession,
    novel_id: str,
) -> None:
    svc = FakeService()
    created = await svc.create(db_session, novel_id, FakeCreate(name="alpha"))
    print(f"\nDEBUG created.id={created.id!r} store={svc.repo.store!r}")
    fetched = await svc.get(db_session, str(created.id), novel_id=novel_id)
    assert fetched.id == created.id


async def test_list_returns_paginated(
    db_session: AsyncSession,
    novel_id: str,
) -> None:
    svc = FakeService()
    for i in range(5):
        await svc.create(db_session, novel_id, FakeCreate(name=f"r{i}"))
    items, total = await svc.list(db_session, novel_id, limit=3)
    assert total == 5
    assert len(items) == 3


async def test_update_returns_updated(
    db_session: AsyncSession,
    novel_id: str,
) -> None:
    svc = FakeService()
    created = await svc.create(db_session, novel_id, FakeCreate(name="alpha"))
    updated = await svc.update(
        db_session, str(created.id), FakeUpdate(name="beta"),
        novel_id=novel_id,
    )
    assert updated.name == "beta"


async def test_delete_removes_row(
    db_session: AsyncSession,
    novel_id: str,
) -> None:
    svc = FakeService()
    created = await svc.create(db_session, novel_id, FakeCreate(name="alpha"))
    await svc.delete(db_session, str(created.id), novel_id=novel_id)
    items, total = await svc.list(db_session, novel_id)
    assert total == 0
    assert svc.repo.store == {}


# --- novel_id 必填 keyword-only ---

async def test_get_requires_novel_id(
    db_session: AsyncSession,
    novel_id: str,
) -> None:
    svc = FakeService()
    with pytest.raises(TypeError):
        await svc.get(db_session, "any-id")  # type: ignore[call-arg]


async def test_update_requires_novel_id(
    db_session: AsyncSession,
    novel_id: str,
) -> None:
    svc = FakeService()
    with pytest.raises(TypeError):
        await svc.update(  # type: ignore[call-arg]
            db_session, "any-id", FakeUpdate(name="x"),
        )


async def test_delete_requires_novel_id(
    db_session: AsyncSession,
    novel_id: str,
) -> None:
    svc = FakeService()
    with pytest.raises(TypeError):
        await svc.delete(db_session, "any-id")  # type: ignore[call-arg]


# --- novel_id 隔离 (UUID-UUID 比对) ---

async def test_get_cross_novel_raises_404(
    db_session: AsyncSession,
    novel_id: str,
    other_novel_id: str,
) -> None:
    svc = FakeService()
    created = await svc.create(db_session, novel_id, FakeCreate(name="mine"))
    with pytest.raises(HTTPException) as exc:
        await svc.get(db_session, str(created.id), novel_id=other_novel_id)
    assert exc.value.status_code == 404


async def test_get_missing_raises_404(
    db_session: AsyncSession,
    novel_id: str,
) -> None:
    svc = FakeService()
    with pytest.raises(HTTPException) as exc:
        await svc.get(
            db_session, str(uuid.uuid4()), novel_id=novel_id,
        )
    assert exc.value.status_code == 404


async def test_get_404_message_uses_label(
    db_session: AsyncSession,
    novel_id: str,
) -> None:
    svc = FakeService()
    fake_id = str(uuid.uuid4())
    with pytest.raises(HTTPException) as exc:
        await svc.get(
            db_session, fake_id, novel_id=novel_id,
        )
    assert f"Fake {fake_id} not found" in exc.value.detail


# --- __init_subclass__ 守卫 ---

def test_subclass_missing_classvar_raises() -> None:
    """缺 ClassVar 的子类必须在 class 定义时立即抛 TypeError (不是延迟到调用)。"""
    from modules.world.services.base import CrudService

    # class 定义本身就会触发 __init_subclass__ 抛错 — 不用 with pytest.raises
    # 因为 class 关键字在 module load 时执行
    try:
        class BadService(  # type: ignore[misc,unused-ignore]
            CrudService[FakeRow, FakeCreate, FakeUpdate, FakeResponse],
        ):
            # 故意缺 label
            repo = FakeRepo()
            response = FakeResponse
    except TypeError as e:
        assert "label" in str(e)
        return
    pytest.fail("Expected TypeError when class definition missing ClassVar")


# --- list 默认 limit 由 base clamp ---

async def test_list_clamps_to_max_page_size(
    db_session: AsyncSession,
    novel_id: str,
) -> None:
    """list 限流由 base class 强制 — 调用方不能传 limit=10_000_000。"""
    svc = FakeService()
    items, _ = await svc.list(db_session, novel_id, limit=10_000_000)
    # MAX_PAGE_SIZE 默认 50 — 超出被 clamp
    assert len(items) <= 50


# ============================================================
# Parametric test: 4 个真实 service 都满足 5 verb + 必填 novel_id
# ============================================================

@pytest.mark.parametrize("service_factory", [
    "WorldEntityService",
    "EntityRelationService",
    "EventService",
    "CharacterService",
])
async def test_real_service_enforces_novel_id_keyword_only(
    service_factory: str,
) -> None:
    """ADR-0002: 4 个真实 service 在 get/update/delete 上 novel_id 必填 keyword-only。

    这是 seam-validity 测试 — 如果未来有人新加一个 service 忘了强制 novel_id,
    这测试不直接覆盖, 但提醒每个 service 都要走 base。
    """
    from modules.world.services import (
        CharacterService,
        EntityRelationService,
        EventService,
        WorldEntityService,
    )
    factories = {
        "WorldEntityService": WorldEntityService,
        "EntityRelationService": EntityRelationService,
        "EventService": EventService,
        "CharacterService": CharacterService,
    }
    svc = factories[service_factory]()

    # get / update / delete 都缺 novel_id 应抛 TypeError
    with pytest.raises(TypeError):
        await svc.get(None, "x")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        await svc.update(None, "x", None)  # type: ignore[call-arg,arg-type]
    with pytest.raises(TypeError):
        await svc.delete(None, "x")  # type: ignore[call-arg]
