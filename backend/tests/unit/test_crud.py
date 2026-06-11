"""
core/crud.py 单元测试

测试 CrudService 泛型基类：子类验证、CRUD 五动词、novel_id 隔离、
404 行为、分页限制。
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from pydantic import BaseModel

from core.crud import CrudService

# --- 测试辅助类 ---


class FakeModel:
    """模拟 ORM 模型实例"""

    def __init__(self, id, novel_id, **kwargs):
        self.id = id
        self.novel_id = novel_id
        for k, v in kwargs.items():
            setattr(self, k, v)


class CreateData(BaseModel):
    name: str


class UpdateData(BaseModel):
    name: str | None = None


class ResponseModel(BaseModel):
    id: uuid.UUID
    novel_id: uuid.UUID
    name: str

    model_config = {"from_attributes": True}


# --- 合法的子类 ---


class ValidCrudService(CrudService[FakeModel, CreateData, UpdateData, ResponseModel]):
    repo = MagicMock()
    response = ResponseModel
    label = "TestEntity"


# --- Fixtures ---

NOVEL_ID = "c8f2a1e456784b3d9f1a2b3c4d5e6f71"
ENTITY_ID = "b1234567890a4b3d9f1a2b3c4d5e6f71"


@pytest.fixture
def nid():
    return uuid.UUID(hex=NOVEL_ID)


@pytest.fixture
def eid():
    return uuid.UUID(hex=ENTITY_ID)


@pytest.fixture
def svc():
    return ValidCrudService()


@pytest.fixture
def mock_repo(svc):
    svc.repo.reset_mock()
    return svc.repo


# --- 测试 ---


class TestCrudServiceSubclassValidation:
    """__init_subclass__ 验证必填 ClassVar"""

    def test_missing_repo_raises_type_error(self):
        with pytest.raises(TypeError, match="'repo'"):

            class _(CrudService):
                response = ResponseModel
                label = "X"

    def test_missing_response_raises_type_error(self):
        with pytest.raises(TypeError, match="'response'"):

            class _(CrudService):
                repo = MagicMock()
                label = "X"

    def test_missing_label_raises_type_error(self):
        with pytest.raises(TypeError, match="'label'"):

            class _(CrudService):
                repo = MagicMock()
                response = ResponseModel

    def test_id_param_defaults_to_id(self):
        class Svc(CrudService):
            repo = MagicMock()
            response = ResponseModel
            label = "X"

        assert Svc.id_param == "id"

    def test_valid_subclass_passes(self):
        # ValidCrudService 已成功定义，不需要额外断言
        assert ValidCrudService.label == "TestEntity"


class TestCrudServiceGet:
    """get(id, novel_id)"""

    @pytest.mark.asyncio
    async def test_get_returns_response_for_found_object(self, svc, mock_repo, eid, nid):
        obj = FakeModel(id=eid, novel_id=nid, name="测试")
        mock_repo.get = AsyncMock(return_value=obj)

        result = await svc.get(None, ENTITY_ID, novel_id=NOVEL_ID)

        assert isinstance(result, ResponseModel)
        assert result.name == "测试"
        mock_repo.get.assert_awaited_once_with(None, eid)

    @pytest.mark.asyncio
    async def test_get_raises_404_when_not_found(self, svc, mock_repo):
        mock_repo.get = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc:
            await svc.get(None, ENTITY_ID, novel_id=NOVEL_ID)
        assert exc.value.status_code == 404
        assert "TestEntity" in exc.value.detail

    @pytest.mark.asyncio
    async def test_get_raises_404_when_novel_id_mismatch(self, svc, mock_repo, eid):
        other_nid = uuid.uuid4()
        obj = FakeModel(id=eid, novel_id=other_nid)
        mock_repo.get = AsyncMock(return_value=obj)

        with pytest.raises(HTTPException) as exc:
            await svc.get(None, ENTITY_ID, novel_id=NOVEL_ID)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_raises_422_for_invalid_id(self, svc):
        with pytest.raises(HTTPException) as exc:
            await svc.get(None, "not-a-uuid", novel_id=NOVEL_ID)
        assert exc.value.status_code == 422

    @pytest.mark.asyncio
    async def test_get_raises_422_for_invalid_novel_id(self, svc, mock_repo, eid, nid):
        obj = FakeModel(id=eid, novel_id=nid, name="x")
        mock_repo.get = AsyncMock(return_value=obj)

        with pytest.raises(HTTPException) as exc:
            await svc.get(None, ENTITY_ID, novel_id="bad-novel-id")
        assert exc.value.status_code == 422
        assert "novel_id" in exc.value.detail


class TestCrudServiceList:
    """list(novel_id, skip, limit)"""

    @pytest.mark.asyncio
    async def test_list_returns_items_and_total(self, svc, mock_repo, nid):
        objs = [
            FakeModel(id=uuid.uuid4(), novel_id=nid, name=f"item_{i}") for i in range(3)
        ]
        mock_repo.get_by_novel = AsyncMock(return_value=(objs, 3))

        items, total = await svc.list(None, NOVEL_ID)

        assert total == 3
        assert len(items) == 3
        assert all(isinstance(it, ResponseModel) for it in items)

    @pytest.mark.asyncio
    async def test_list_caps_limit_at_max_page_size(self, svc, mock_repo):
        mock_repo.get_by_novel = AsyncMock(return_value=([], 0))

        await svc.list(None, NOVEL_ID, limit=9999)

        call_limit = mock_repo.get_by_novel.call_args[1]["limit"]
        assert call_limit == 50  # MAX_PAGE_SIZE


class TestCrudServiceCreate:
    """create(novel_id, data)"""

    @pytest.mark.asyncio
    async def test_create_calls_repo_and_returns_response(self, svc, mock_repo, eid, nid):
        data = CreateData(name="新对象")
        obj = FakeModel(id=eid, novel_id=nid, name="新对象")
        mock_repo.create = AsyncMock(return_value=obj)

        result = await svc.create(None, NOVEL_ID, data)

        assert result.name == "新对象"
        mock_repo.create.assert_awaited_once_with(None, nid, data)


class TestCrudServiceUpdate:
    """update(id, data, novel_id)"""

    @pytest.mark.asyncio
    async def test_update_returns_updated_response(self, svc, mock_repo, eid, nid):
        existing = FakeModel(id=eid, novel_id=nid, name="旧名")
        updated = FakeModel(id=eid, novel_id=nid, name="新名")
        mock_repo.get = AsyncMock(return_value=existing)
        mock_repo.update = AsyncMock(return_value=updated)
        data = UpdateData(name="新名")

        result = await svc.update(None, ENTITY_ID, data, novel_id=NOVEL_ID)

        assert result.name == "新名"
        mock_repo.update.assert_awaited_once_with(None, eid, data)

    @pytest.mark.asyncio
    async def test_update_raises_404_when_not_found(self, svc, mock_repo):
        mock_repo.get = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc:
            await svc.update(None, ENTITY_ID, UpdateData(name="x"), novel_id=NOVEL_ID)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_update_raises_404_when_novel_mismatch(self, svc, mock_repo, eid):
        existing = FakeModel(id=eid, novel_id=uuid.uuid4())
        mock_repo.get = AsyncMock(return_value=existing)

        with pytest.raises(HTTPException) as exc:
            await svc.update(None, ENTITY_ID, UpdateData(name="x"), novel_id=NOVEL_ID)
        assert exc.value.status_code == 404


class TestCrudServiceDelete:
    """delete(id, novel_id)"""

    @pytest.mark.asyncio
    async def test_delete_calls_repo(self, svc, mock_repo, eid, nid):
        existing = FakeModel(id=eid, novel_id=nid, name="x")
        mock_repo.get = AsyncMock(return_value=existing)
        mock_repo.delete = AsyncMock(return_value=True)

        await svc.delete(None, ENTITY_ID, novel_id=NOVEL_ID)

        mock_repo.delete.assert_awaited_once_with(None, eid)

    @pytest.mark.asyncio
    async def test_delete_raises_404_when_repo_returns_false(
        self, svc, mock_repo, eid, nid
    ):
        existing = FakeModel(id=eid, novel_id=nid, name="x")
        mock_repo.get = AsyncMock(return_value=existing)
        mock_repo.delete = AsyncMock(return_value=False)

        with pytest.raises(HTTPException) as exc:
            await svc.delete(None, ENTITY_ID, novel_id=NOVEL_ID)
        assert exc.value.status_code == 404
