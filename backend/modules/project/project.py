"""
Project 模块

合并了 model / schemas / crud / api 的单文件。
project 是根聚合，本身不含业务逻辑，6 层分离是纯开销。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Sequence

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import JSON, String, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from core.base import Base, TimestampMixin, UUIDMixin
from core.dependencies import DbSession
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from shared.utils import parse_uuid


class Project(Base, UUIDMixin, TimestampMixin):
    """小说项目 — 系统的根聚合"""

    __tablename__ = "projects"

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="项目标题",
    )
    genre: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="题材（如：玄幻、科幻、悬疑）",
    )
    tone: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="风格基调（如：严肃、轻松、黑暗）",
    )
    language: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="zh",
        comment="创作语言",
    )
    target_length: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        comment="目标规模（short/medium/novel/epic）",
    )
    current_stage: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        comment="当前创作阶段（world_building/outlining/writing/revising）",
    )
    default_reveal_policy: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="author_safe",
        comment="默认揭示策略",
    )
    settings: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="小说配置（JSON，如 temporary_entity_expiry_chapters）",
    )

    def __repr__(self) -> str:
        return f"<Project id={self.id} title={self.title!r}>"


# ============================================================
# Pydantic Schemas
# ============================================================


class ProjectCreate(BaseModel):
    """创建项目请求"""

    title: str = Field(..., min_length=1, max_length=255, description="项目标题")
    genre: str | None = Field(None, max_length=64, description="题材")
    tone: str | None = Field(None, max_length=64, description="风格基调")
    language: str = Field(default="zh", max_length=16, description="创作语言")
    target_length: str | None = Field(None, max_length=32, description="目标规模")
    current_stage: str | None = Field(None, max_length=32, description="创作阶段")
    default_reveal_policy: str = Field(default="author_safe", max_length=32, description="默认揭示策略")
    settings: dict = Field(default={}, description="小说配置（JSON）")


class ProjectUpdate(BaseModel):
    """更新项目请求（所有字段可选）"""

    title: Annotated[str | None, Field(None, min_length=1, max_length=255)]
    genre: Annotated[str | None, Field(None, max_length=64)]
    tone: Annotated[str | None, Field(None, max_length=64)]
    language: Annotated[str | None, Field(None, max_length=16)]
    target_length: Annotated[str | None, Field(None, max_length=32)]
    current_stage: Annotated[str | None, Field(None, max_length=32)]
    default_reveal_policy: Annotated[str | None, Field(None, max_length=32)]
    settings: Annotated[dict | None, Field(None, description="小说配置（JSON）")]


class ProjectResponse(BaseModel):
    """项目响应"""

    model_config = ConfigDict(from_attributes=True, json_encoders={uuid.UUID: str})

    id: str
    title: str
    genre: str | None = None
    tone: str | None = None
    language: str = "zh"
    target_length: str | None = None
    current_stage: str | None = None
    default_reveal_policy: str = "author_safe"
    settings: dict = {}
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", mode="before")
    @classmethod
    def coerce_id_to_str(cls, v: object) -> str:
        if isinstance(v, uuid.UUID):
            return str(v)
        if isinstance(v, str):
            return v
        return str(v)


class ProjectListResponse(BaseModel):
    """项目列表响应"""

    items: list[ProjectResponse]
    total: int


# ============================================================
# CRUD
# ============================================================


async def _create_project(db: AsyncSession, data: ProjectCreate) -> Project:
    project = Project(
        title=data.title,
        genre=data.genre,
        tone=data.tone,
        language=data.language or "zh",
        target_length=data.target_length,
        current_stage=data.current_stage,
        default_reveal_policy=data.default_reveal_policy or "author_safe",
        settings=data.settings or {},
    )
    db.add(project)
    await db.flush()
    return project


async def _get_project(db: AsyncSession, project_id: uuid.UUID) -> Project | None:
    stmt = select(Project).where(Project.id == project_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _list_projects(
    db: AsyncSession,
    skip: int = 0,
    limit: int = DEFAULT_PAGE_SIZE,
) -> tuple[list[Project], int]:
    count_stmt = select(func.count(Project.id))
    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0
    stmt = (
        select(Project)
        .offset(skip)
        .limit(limit)
        .order_by(Project.created_at.desc())
    )
    result = await db.execute(stmt)
    items: Sequence[Project] = result.scalars().all()
    return list(items), total


async def _update_project(
    db: AsyncSession,
    project_id: uuid.UUID,
    data: ProjectUpdate,
) -> Project | None:
    project = await _get_project(db, project_id)
    if project is None:
        return None
    update_values: dict[str, object] = {}
    for field in (
        "title", "genre", "tone", "language",
        "target_length", "current_stage", "default_reveal_policy", "settings",
    ):
        value = getattr(data, field, None)
        if value is not None:
            update_values[field] = value
    if update_values:
        stmt = update(Project).where(Project.id == project_id).values(**update_values)
        await db.execute(stmt)
        await db.flush()
        project = await _get_project(db, project_id)
    return project


async def _delete_project(db: AsyncSession, project_id: uuid.UUID) -> bool:
    stmt = delete(Project).where(Project.id == project_id)
    result = await db.execute(stmt)
    await db.flush()
    return result.rowcount > 0


class ProjectRepository:
    """[legacy] 数据访问层包装 — 委托给模块级 CRUD 函数"""

    async def create(self, db: AsyncSession, data: ProjectCreate) -> Project:
        return await _create_project(db, data)

    async def get(self, db: AsyncSession, project_id: uuid.UUID) -> Project | None:
        return await _get_project(db, project_id)

    async def get_multi(self, db: AsyncSession, skip: int = 0, limit: int = DEFAULT_PAGE_SIZE) -> tuple[list[Project], int]:
        return await _list_projects(db, skip=skip, limit=limit)

    async def update(self, db: AsyncSession, project_id: uuid.UUID, data: ProjectUpdate) -> Project | None:
        return await _update_project(db, project_id, data)

    async def delete(self, db: AsyncSession, project_id: uuid.UUID) -> bool:
        return await _delete_project(db, project_id)


class ProjectService:
    """[legacy] 业务服务层包装 — 保留以兼容测试"""

    async def create_project(self, db: AsyncSession, data: ProjectCreate) -> ProjectResponse:
        project = await _create_project(db, data)
        return ProjectResponse.model_validate(project)

    async def get_project(self, db: AsyncSession, project_id: str) -> ProjectResponse:
        pid = parse_uuid(project_id, "project_id")
        project = await _get_project(db, pid)
        if project is None:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
        return ProjectResponse.model_validate(project)

    async def list_projects(self, db: AsyncSession, skip: int = 0, limit: int = DEFAULT_PAGE_SIZE) -> tuple[list[ProjectResponse], int]:
        limit = min(limit, MAX_PAGE_SIZE)
        items, total = await _list_projects(db, skip=skip, limit=limit)
        return [ProjectResponse.model_validate(p) for p in items], total

    async def update_project(self, db: AsyncSession, project_id: str, data: ProjectUpdate) -> ProjectResponse:
        pid = parse_uuid(project_id, "project_id")
        project = await _update_project(db, pid, data)
        if project is None:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
        return ProjectResponse.model_validate(project)

    async def delete_project(self, db: AsyncSession, project_id: str) -> None:
        pid = parse_uuid(project_id, "project_id")
        deleted = await _delete_project(db, pid)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    async def get_project_context(self, db: AsyncSession, novel_id: str) -> ProjectContext | None:
        return await get_project_context(db, novel_id)


# ============================================================
# 对外接口
# ============================================================


class ProjectContext(BaseModel):
    """项目上下文 — 供其他模块读取的项目信息"""

    model_config = ConfigDict(from_attributes=True)

    novel_id: str
    title: str
    genre: str | None = None
    tone: str | None = None
    language: str = "zh"
    target_length: str | None = None
    current_stage: str | None = None
    default_reveal_policy: str = "author_safe"
    settings: dict = {}


async def get_project_context(
    db: AsyncSession,
    novel_id: str,
) -> ProjectContext | None:
    """获取项目上下文（供其他模块使用）"""
    pid = parse_uuid(novel_id, "novel_id")
    project = await _get_project(db, pid)
    if project is None:
        return None
    return ProjectContext(
        novel_id=str(project.id),
        title=project.title,
        genre=project.genre,
        tone=project.tone,
        language=project.language,
        target_length=project.target_length,
        current_stage=project.current_stage,
        default_reveal_policy=project.default_reveal_policy,
        settings=project.settings,
    )


# ============================================================
# API Router
# ============================================================


router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(
    db: DbSession,
    data: ProjectCreate,
) -> ProjectResponse:
    """创建新小说项目"""
    project = await _create_project(db, data)
    return ProjectResponse.model_validate(project)


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    db: DbSession,
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="每页条数",
    ),
) -> ProjectListResponse:
    """获取项目列表"""
    items, total = await _list_projects(db, skip=skip, limit=limit)
    return ProjectListResponse(
        items=[ProjectResponse.model_validate(p) for p in items],
        total=total,
    )


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    db: DbSession,
    project_id: str,
) -> ProjectResponse:
    """获取项目详情"""
    pid = parse_uuid(project_id, "project_id")
    project = await _get_project(db, pid)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return ProjectResponse.model_validate(project)


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(
    db: DbSession,
    project_id: str,
    data: ProjectUpdate,
) -> ProjectResponse:
    """更新项目信息"""
    pid = parse_uuid(project_id, "project_id")
    project = await _update_project(db, pid, data)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return ProjectResponse.model_validate(project)


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    db: DbSession,
    project_id: str,
) -> None:
    """删除项目"""
    pid = parse_uuid(project_id, "project_id")
    deleted = await _delete_project(db, pid)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
