"""BaseCRUDService — novel-scoped CRUD template.

ADR-0002: 4 typevar 表达类型差异, 4 ClassVar 注入实现, 不上 port。
EntityRevisionService opt-in, 不继承。
"""

from __future__ import annotations

import uuid
from typing import Any, ClassVar, Protocol, TypeVar

from fastapi import HTTPException
from fastapi import status as http_status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from shared.utils import parse_uuid

ModelT = TypeVar("ModelT")
CreateT = TypeVar("CreateT", bound=BaseModel)
UpdateT = TypeVar("UpdateT", bound=BaseModel)
ResponseT = TypeVar("ResponseT", bound=BaseModel)


class _CrudRepo(Protocol[ModelT, CreateT, UpdateT]):
    """5 个 repo 必须实现的最小接口。duck-typed, 不强制 runtime_checkable。"""

    def get(self, db: AsyncSession, id: uuid.UUID) -> ModelT | None: ...
    def get_by_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        skip: int,
        limit: int,
    ) -> tuple[list[ModelT], int]: ...
    def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        data: CreateT,
    ) -> ModelT: ...
    def update(
        self,
        db: AsyncSession,
        id: uuid.UUID,
        data: UpdateT,
    ) -> ModelT | None: ...
    def delete(self, db: AsyncSession, id: uuid.UUID) -> bool: ...


class CrudService[ModelT, CreateT, UpdateT, ResponseT]:
    """Novel-scoped CRUD 模板。

    Invariants:
      - novel_id 隔离: novel_id 给定时, repo 读出的对象必须与 novel_id 匹配;
        不匹配一律抛 404 (不区分 403/404, 避免泄露存在性)。
      - 404 抛 HTTPException(404, detail="<label> {id} not found"),
        label 由子类提供。
      - parse_uuid 抛 ValueError → 由调用方决定是否转 4xx; 本类不吞。
      - Response.model_validate 在每次返回前调用, 保证序列化路径一致。
      - DB flush / commit 异常向上传播, 不捕获 (per world/CLAUDE.md §8)。

    Subclass 必须提供 (ClassVar, __init_subclass__ 守卫):
      - repo:           满足 _CrudRepo 的实例
      - response:       用于 model_validate 的 Pydantic 类
      - label:          用于 404 detail 的字符串 (例: "CoreEntity")
      - id_param:       parse_uuid 第二参 (例: "entity_id"), 默认 "id"
    """

    repo: _CrudRepo
    response: ClassVar[type[BaseModel]]
    list_response: ClassVar[type[BaseModel] | None] = None
    label: ClassVar[str]
    id_param: ClassVar[str] = "id"

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for attr in ("repo", "response", "label"):
            if not hasattr(cls, attr) or getattr(cls, attr, None) is None:
                raise TypeError(
                    f"{cls.__name__} 必须声明 ClassVar {attr!r}",
                )
        if not hasattr(cls, "id_param"):
            cls.id_param = "id"

    # ============================================================
    # 5 verbs
    # ============================================================

    async def get(
        self,
        db: AsyncSession,
        id: str,
        *,
        novel_id: str,
    ) -> ResponseT:
        rid = parse_uuid(id, self.id_param)
        nid = parse_uuid(novel_id, "novel_id")
        obj = await self.repo.get(db, rid)
        self._assert_found_in_novel(obj, id, nid)
        return self._to_response(obj)  # type: ignore[return-value]

    async def list(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[ResponseT], int]:
        nid = parse_uuid(novel_id, "novel_id")
        limit = min(limit, MAX_PAGE_SIZE)
        objs, total = await self.repo.get_by_novel(
            db,
            nid,
            skip=skip,
            limit=limit,
        )
        return [self._to_response(o) for o in objs], total  # type: ignore[misc]

    async def list_with_response(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> BaseModel:
        """Like `list()`, but wraps result in `list_response` if configured."""
        items, total = await self.list(db, novel_id, skip=skip, limit=limit)
        if self.list_response is None:
            raise TypeError(
                f"{self.__class__.__name__}.list_response is not set",
            )
        return self.list_response(items=items, total=total)  # type: ignore[return-value]

    async def create(
        self,
        db: AsyncSession,
        novel_id: str,
        data: CreateT,
    ) -> ResponseT:
        nid = parse_uuid(novel_id, "novel_id")
        obj = await self.repo.create(db, nid, data)
        return self._to_response(obj)  # type: ignore[return-value]

    async def update(
        self,
        db: AsyncSession,
        id: str,
        data: UpdateT,
        *,
        novel_id: str,
    ) -> ResponseT:
        rid = parse_uuid(id, self.id_param)
        nid = parse_uuid(novel_id, "novel_id")
        existing = await self.repo.get(db, rid)
        self._assert_found_in_novel(existing, id, nid)
        obj = await self.repo.update(db, rid, data)
        self._assert_found_in_novel(obj, id, nid)
        return self._to_response(obj)  # type: ignore[return-value]

    async def delete(
        self,
        db: AsyncSession,
        id: str,
        *,
        novel_id: str,
    ) -> None:
        rid = parse_uuid(id, self.id_param)
        nid = parse_uuid(novel_id, "novel_id")
        existing = await self.repo.get(db, rid)
        self._assert_found_in_novel(existing, id, nid)
        if hasattr(existing, "status"):
            setattr(existing, "status", "deprecated")
            await db.flush()
            return
        ok = await self.repo.delete(db, rid)
        if not ok:
            self._raise_404(id)

    # ============================================================
    # 内部 helper
    # ============================================================

    def _to_response(self, obj: ModelT) -> ResponseT:
        return self.response.model_validate(obj)  # type: ignore[return-value]

    def _assert_found_in_novel(
        self,
        obj: ModelT | None,
        id: str,
        nid: uuid.UUID,
    ) -> None:
        """UUID-UUID 比对 (per ADR-0002)。"""
        if obj is None:
            self._raise_404(id)
        if getattr(obj, "novel_id", None) != nid:
            self._raise_404(id)

    def _raise_404(self, id: str) -> None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"{self.label} {id} not found",
        )
