"""
core/base.py 单元测试

测试 ORM Mixin 类：UUIDMixin、TimestampMixin、StatusMixin、NovelMixin。
使用 SQLite 内存数据库创建表并验证字段行为。
"""

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import String, select, text
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Mapped, mapped_column

from core.base import (
    Base,
    NovelMixin,
    StatusMixin,
    TimestampMixin,
    UUIDMixin,
)

SQLITE_URL = "sqlite+aiosqlite:///:memory:"


class _TestModel(Base, UUIDMixin, TimestampMixin, StatusMixin, NovelMixin):
    __tablename__ = "base_test_models"
    name: Mapped[str] = mapped_column(String(100), nullable=False)


@pytest_asyncio.fixture(autouse=True)
async def _engine():
    """共享 SQLite engine，每个测试前建表，测试后删表"""
    engine = create_async_engine(SQLITE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db(_engine):
    """基于共享 engine 创建 session"""
    async with AsyncSession(_engine, expire_on_commit=False) as session:
        yield session


class TestUUIDMixin:
    """UUIDMixin — UUID 主键自动生成"""

    def test_uuid_ddl_uses_text_affinity_only_for_sqlite(self):
        id_type = _TestModel.__table__.c.id.type

        assert str(id_type.compile(dialect=sqlite.dialect())) == "CHAR(32)"
        assert str(id_type.compile(dialect=postgresql.dialect())) == "UUID"

    async def test_id_auto_generated(self, db):
        obj = _TestModel(novel_id=uuid.uuid4(), name="test")
        db.add(obj)
        await db.flush()
        assert isinstance(obj.id, uuid.UUID)

    async def test_id_is_unique_per_instance(self, db):
        nid = uuid.uuid4()
        o1 = _TestModel(novel_id=nid, name="a")
        o2 = _TestModel(novel_id=nid, name="b")
        db.add_all([o1, o2])
        await db.flush()
        assert o1.id != o2.id

    async def test_id_can_be_set_explicitly(self, db):
        explicit_id = uuid.uuid4()
        obj = _TestModel(id=explicit_id, novel_id=uuid.uuid4(), name="test")
        db.add(obj)
        await db.flush()
        assert obj.id == explicit_id

    async def test_scientific_notation_like_uuid_round_trips_as_text(self, db):
        """SQLite must not coerce UUID hex such as ``1e999...`` to float infinity."""
        explicit_id = uuid.UUID("1e" + "9" * 30)
        novel_id = uuid.UUID("2e" + "8" * 30)
        db.add(
            _TestModel(
                id=explicit_id,
                novel_id=novel_id,
                name="numeric-affinity-regression",
            )
        )
        await db.flush()
        db.expunge_all()

        loaded = await db.scalar(select(_TestModel).where(_TestModel.id == explicit_id))
        assert loaded is not None
        assert loaded.id == explicit_id
        assert loaded.novel_id == novel_id

        storage_types = (
            await db.execute(
                text(
                    "SELECT typeof(id), typeof(novel_id) "
                    "FROM base_test_models WHERE name = :name"
                ),
                {"name": "numeric-affinity-regression"},
            )
        ).one()
        assert storage_types == ("text", "text")


class TestTimestampMixin:
    """TimestampMixin — created_at / updated_at 自动时间戳"""

    async def test_created_at_set_on_insert(self, db):
        obj = _TestModel(novel_id=uuid.uuid4(), name="test")
        db.add(obj)
        await db.flush()
        assert isinstance(obj.created_at, datetime)
        now = datetime.now(UTC)
        assert abs((now - obj.created_at).total_seconds()) < 5

    async def test_updated_at_set_on_insert(self, db):
        obj = _TestModel(novel_id=uuid.uuid4(), name="test")
        db.add(obj)
        await db.flush()
        assert isinstance(obj.updated_at, datetime)

    async def test_updated_at_changes_on_update(self, db):
        obj = _TestModel(novel_id=uuid.uuid4(), name="test")
        db.add(obj)
        await db.flush()
        old_updated = obj.updated_at
        obj.name = "updated"
        await db.flush()
        assert obj.updated_at is not None
        if old_updated is not None:
            assert obj.updated_at >= old_updated


class TestStatusMixin:
    """StatusMixin — status 默认值为 'draft'"""

    async def test_status_defaults_to_draft(self, db):
        obj = _TestModel(novel_id=uuid.uuid4(), name="test")
        db.add(obj)
        await db.flush()
        assert obj.status == "draft"

    async def test_status_can_be_set_explicitly(self, db):
        obj = _TestModel(novel_id=uuid.uuid4(), name="test", status="canonical")
        db.add(obj)
        await db.flush()
        assert obj.status == "canonical"


class TestNovelMixin:
    """NovelMixin — novel_id 外键"""

    async def test_novel_id_is_required(self, db):
        with pytest.raises(Exception):
            obj = _TestModel(name="no novel")
            db.add(obj)
            await db.flush()

    async def test_novel_id_stored_correctly(self, db):
        nid = uuid.uuid4()
        obj = _TestModel(novel_id=nid, name="test")
        db.add(obj)
        await db.flush()
        assert obj.novel_id == nid


class TestBase:
    """Base — DeclarativeBase 基类"""

    def test_base_is_declarative_base(self):
        from sqlalchemy.orm import DeclarativeBase

        assert issubclass(Base, DeclarativeBase)
