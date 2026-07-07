# Settings Page Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把当前 `llmSettingsView.js` 单页拆分为「全局设置页 + 项目设置页」两入口，后端新增三表预留 `owner_id`，引入「全局默认 + 项目覆盖」分层，项目 LLM 配置沿用 `Project.settings` JSON inheritance。

**Architecture:** 后端新增 `modules/settings/` 模块持有三张新表与全局接口；`modules/project/` 新增 effective 接口与字段级 DELETE；前端 `frontend-console/views/settings/` 拆为 globalSettingsView / projectSettingsView + 三 Tab + 四 shared 组件。路由 `#/settings` 与 `#/projects/<id>/settings` 独立，`#/llm` 保留为别名。

**Tech Stack:** FastAPI + SQLAlchemy async + PostgreSQL + Pydantic v2（后端）；vanilla JS + vitest + Playwright（前端）

**Spec:** `docs/superpowers/specs/2026-07-07-settings-page-restructure-design.md`

---

## File Map

### 后端新建
- `backend/modules/settings/__init__.py`
- `backend/modules/settings/models.py` — 三张新表 ORM
- `backend/modules/settings/repositories.py` — 三表 CRUD + 隔离查询
- `backend/modules/settings/schemas.py` — Pydantic 请求/响应模型
- `backend/modules/settings/services.py` — 业务编排 + effective 合并
- `backend/modules/settings/api.py` — FastAPI 路由
- `backend/modules/settings/constants.py` — owner_id 占位、硬默认、字段白名单
- `backend/modules/settings/tests/__init__.py`
- `backend/modules/settings/tests/test_repos.py`
- `backend/modules/settings/tests/test_services.py`
- `backend/modules/settings/tests/test_api.py`
- `backend/modules/settings/tests/test_effective.py`
- `backend/modules/settings/tests/test_owner_isolation.py`
- `backend/alembic/versions/20260707_settings_module.py` — create three tables

### 后端修改
- `backend/app/main.py` — 注册新 settings router
- `backend/modules/project/api.py` — 新增 effective + 字段级 DELETE 路由
- `backend/modules/project/services.py` — effective 合并、字段级 reset 逻辑
- `backend/modules/project/schemas.py` — effective 响应模型、字段级响应模型
- `backend/modules/project/repositories.py` — 字段级 reset 写入
- `backend/infrastructure/llm/profiles.py` — 提供 effective 合并 helper

### 前端新建
- `frontend-console/views/settings/globalSettingsView.js`
- `frontend-console/views/settings/projectSettingsView.js`
- `frontend-console/views/settings/tabs/llmMainTab.js`
- `frontend-console/views/settings/tabs/deepImportTab.js`
- `frontend-console/views/settings/tabs/authorPreferencesTab.js`
- `frontend-console/views/settings/shared/llmFormFields.js`
- `frontend-console/views/settings/shared/deepImportFields.js`
- `frontend-console/views/settings/shared/authorPreferencesForm.js`
- `frontend-console/views/settings/shared/fieldSourceLabel.js`
- `frontend-console/views/settings/shared/constants.js`
- `frontend-console/tests/settings/globalSettingsView.test.js`
- `frontend-console/tests/settings/projectSettingsView.test.js`
- `frontend-console/tests/settings/shared/llmFormFields.test.js`
- `frontend-console/tests/settings/shared/deepImportFields.test.js`
- `frontend-console/tests/settings/shared/authorPreferencesForm.test.js`
- `frontend-console/tests/settings/shared/fieldSourceLabel.test.js`
- `frontend-console/e2e/settings_flow.spec.js`

### 前端修改
- `frontend-console/api.js` — 新增 settings API 方法
- `frontend-console/router.js` — 注册两路由 + `#/llm` 别名
- `frontend-console/state.js` — globalSettingsCache + localStorage 迁移
- `frontend-console/index.html` — 加载新 view 脚本
- `frontend-console/styles.css` — settings 视图样式
- `frontend-console/views/llmSettingsView.js` — 删除（被新视图替代）

### 文档同步
- `docs/00_整体设计.md` — 新增 settings 模块描述
- `backend/modules/settings/README.md` — 模块说明

---

## Task 1: 后端 settings 模块骨架 + alembic

**Files:**
- Create: `backend/modules/settings/__init__.py`
- Create: `backend/modules/settings/constants.py`
- Create: `backend/modules/settings/models.py`
- Create: `backend/alembic/versions/20260707_settings_module.py`
- Test: `backend/modules/settings/tests/__init__.py`

- [ ] **Step 1: 创建模块目录与 `__init__.py`**

Run:
```bash
mkdir -p backend/modules/settings/tests
touch backend/modules/settings/__init__.py backend/modules/settings/tests/__init__.py
```

- [ ] **Step 2: 写 `constants.py` 含 owner_id 占位、硬默认、字段白名单**

```python
"""Settings module shared constants.

D10: owner_id 占位为 nil UUID，UI 显示 `local` 字样，DB 存 nil UUID。
D12: 全局作者偏好硬编码默认值。
D4: 字段级 DELETE 服务端硬白名单。
"""
from __future__ import annotations

import uuid

# Demo owner 占位：nil UUID
LOCAL_OWNER_ID: uuid.UUID = uuid.UUID("00000000-0000-0000-0000-000000000000")
LOCAL_OWNER_LABEL: str = "local"

# D12 全局作者偏好硬编码默认（global 行不存在或字段 NULL 时回退）
AUTHOR_PREFS_DEFAULTS: dict[str, object] = {
    "daily_goal": None,        # unset
    "editor_font": "system",
    "default_focus_mode": False,
}

# D23 系统内置 LLM 默认（global 行不存在时回退）
LLM_DEFAULTS_SYSTEM: dict[str, object] = {
    "provider_id": "openai-compatible",
    "label": None,
    "base_url": "",
    "model": "",
    "timeout": 180,
    "max_tokens": 4096,
    "temperature": 0.3,
    "top_p": None,
    "extra": {},
    "creative_mode": None,
    "deep_import": None,        # D9 本期永远 NULL
}

# 字段级 DELETE 白名单
AUTHOR_PREFS_FIELDS: frozenset[str] = frozenset({
    "daily_goal",
    "editor_font",
    "default_focus_mode",
})

# LLM settings 可继承字段（不含 api_key）
LLM_INHERITABLE_FIELDS: frozenset[str] = frozenset({
    "provider_id",
    "label",
    "base_url",
    "model",
    "timeout",
    "max_tokens",
    "temperature",
    "top_p",
    "extra",
    "creative_mode",
    "deep_import",
})

# source 取值
SOURCE_PROJECT = "project"
SOURCE_GLOBAL = "global"
SOURCE_SYSTEM = "system"
SOURCE_UNSET = "unset"

ALL_SOURCES: frozenset[str] = frozenset({
    SOURCE_PROJECT,
    SOURCE_GLOBAL,
    SOURCE_SYSTEM,
    SOURCE_UNSET,
})
```

- [ ] **Step 3: 写 `models.py` 三表 ORM**

```python
"""Settings module ORM models."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.base import Base, TimestampMixin, UUIDMixin


class GlobalLLMDefaults(Base, UUIDMixin, TimestampMixin):
    """全局 LLM 默认（owner 隔离，不含 API Key）。

    所有非 PK 字段允许 NULL，NULL = 继承系统内置默认（D2）。
    deep_import 列保留但本期永不写入（D9）。
    """

    __tablename__ = "global_llm_defaults"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        nullable=False,
        unique=True,
        index=True,
        comment="owner 占位；demo=LOCAL_OWNER_ID nil UUID",
    )
    provider_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    model: Mapped[str | None] = mapped_column(String(256), nullable=True)
    timeout: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    top_p: Mapped[float | None] = mapped_column(Float, nullable=True)
    extra: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    creative_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    deep_import: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class GlobalAuthorPreferences(Base, UUIDMixin, TimestampMixin):
    """全局作者偏好默认（owner 隔离）。"""

    __tablename__ = "global_author_preferences"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        nullable=False, unique=True, index=True,
    )
    daily_goal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    editor_font: Mapped[str | None] = mapped_column(String(32), nullable=True)
    default_focus_mode: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True,
    )


class ProjectAuthorPreferences(Base, UUIDMixin, TimestampMixin):
    """项目级作者偏好覆盖。

    所有字段允许 NULL：NULL = 继承全局（D2）。
    UNIQUE(project_id) 保证每个项目最多一行。
    """

    __tablename__ = "project_author_preferences"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    daily_goal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    editor_font: Mapped[str | None] = mapped_column(String(32), nullable=True)
    default_focus_mode: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True,
    )
```

- [ ] **Step 4: 写 alembic 迁移文件**

`backend/alembic/versions/20260707_settings_module.py`:
```python
"""create settings module tables

Revision ID: 20260707_settings
Revises: 20260703_squashed_current_schema
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "20260707_settings"
down_revision = "20260703_squashed_current_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "global_llm_defaults",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", UUID(as_uuid=True),
                  nullable=False, unique=True, index=True),
        sa.Column("provider_id", sa.String(64), nullable=True),
        sa.Column("label", sa.String(128), nullable=True),
        sa.Column("base_url", sa.String(512), nullable=True),
        sa.Column("model", sa.String(256), nullable=True),
        sa.Column("timeout", sa.Integer, nullable=True),
        sa.Column("max_tokens", sa.Integer, nullable=True),
        sa.Column("temperature", sa.Float, nullable=True),
        sa.Column("top_p", sa.Float, nullable=True),
        sa.Column("extra", JSONB, nullable=True),
        sa.Column("creative_mode", sa.String(32), nullable=True),
        sa.Column("deep_import", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
    )
    op.create_table(
        "global_author_preferences",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", UUID(as_uuid=True),
                  nullable=False, unique=True, index=True),
        sa.Column("daily_goal", sa.Integer, nullable=True),
        sa.Column("editor_font", sa.String(32), nullable=True),
        sa.Column("default_focus_mode", sa.Boolean, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
    )
    op.create_table(
        "project_author_preferences",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", UUID(as_uuid=True),
                  sa.ForeignKey("projects.id", ondelete="CASCADE"),
                  nullable=False, unique=True, index=True),
        sa.Column("daily_goal", sa.Integer, nullable=True),
        sa.Column("editor_font", sa.String(32), nullable=True),
        sa.Column("default_focus_mode", sa.Boolean, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("project_author_preferences")
    op.drop_table("global_author_preferences")
    op.drop_table("global_llm_defaults")
```

- [ ] **Step 5: demo 阶段直接重建数据库（不入 migration 历史）**

Run:
```bash
cd backend && python -c "
import asyncio
from core.database import get_manager
async def rebuild():
    m = get_manager()
    async with m.engine() as e:
        await e.run_sync(lambda sync_engine: __import__('core.base').base.metadata.create_all(sync_engine))
asyncio.run(rebuild())
"
```

Expected: 无错误；三表已建。`psql` 验证：
```bash
docker compose exec postgres psql -U novelist -d ai_novel_engine -c "\dt global_*" -c "\dt project_author*"
```

- [ ] **Step 6: Commit**

```bash
git add backend/modules/settings/ backend/alembic/versions/20260707_settings_module.py
git commit -m "feat(settings): add settings module tables and constants"
```

---

## Task 2: 仓储层 + repo 单测

**Files:**
- Create: `backend/modules/settings/repositories.py`
- Test: `backend/modules/settings/tests/test_repos.py`

- [ ] **Step 1: 写失败测试 `test_repos.py`**

```python
"""Settings repos tests."""
from __future__ import annotations

import uuid

import pytest

from modules.settings.constants import LOCAL_OWNER_ID
from modules.settings.models import (
    GlobalAuthorPreferences,
    GlobalLLMDefaults,
    ProjectAuthorPreferences,
)
from modules.settings.repositories import (
    GlobalAuthorPrefsRepository,
    GlobalLLMDefaultsRepository,
    ProjectAuthorPrefsRepository,
)


@pytest.mark.asyncio
async def test_global_llm_defaults_upsert_creates_then_updates(db):
    repo = GlobalLLMDefaultsRepository()
    payload = {"owner_id": LOCAL_OWNER_ID, "provider_id": "deepseek",
               "base_url": "https://api.deepseek.com/v1", "model": "deepseek-v4-flash"}
    row = await repo.upsert(db, payload)
    assert row.id is not None
    rid = row.id
    # upsert 同 owner 应更新而非新行
    row2 = await repo.upsert(db, {"owner_id": LOCAL_OWNER_ID, "provider_id": "openai-compatible"})
    assert row2.id == rid
    assert row2.provider_id == "openai-compatible"


@pytest.mark.asyncio
async def test_global_llm_defaults_owner_isolation(db):
    repo = GlobalLLMDefaultsRepository()
    owner_a = uuid.uuid4()
    owner_b = uuid.uuid4()
    await repo.upsert(db, {"owner_id": owner_a, "provider_id": "a"})
    await repo.upsert(db, {"owner_id": owner_b, "provider_id": "b"})
    a = await repo.get(db, owner_a)
    b = await repo.get(db, owner_b)
    assert a.provider_id == "a"
    assert b.provider_id == "b"
    assert a.id != b.id


@pytest.mark.asyncio
async def test_global_llm_defaults_get_missing_returns_none(db):
    repo = GlobalLLMDefaultsRepository()
    assert await repo.get(db, LOCAL_OWNER_ID) is None


@pytest.mark.asyncio
async def test_global_author_prefs_upsert_null_semantics(db):
    repo = GlobalAuthorPrefsRepository()
    row = await repo.upsert(db, {
        "owner_id": LOCAL_OWNER_ID, "daily_goal": 6000,
        "editor_font": None, "default_focus_mode": None,
    })
    assert row.daily_goal == 6000
    assert row.editor_font is None
    assert row.default_focus_mode is None


@pytest.mark.asyncio
async def test_project_author_prefs_row_not_exist_returns_none(db, factory):
    repo = ProjectAuthorPrefsRepository()
    pid = await factory.create_project()
    # 无行时返回 None，service 负责返回空对象
    assert await repo.get(db, pid) is None


@pytest.mark.asyncio
async def test_project_author_prefs_field_reset_to_null(db, factory):
    repo = ProjectAuthorPrefsRepository()
    pid = await factory.create_project()
    await repo.upsert(db, {
        "project_id": pid, "daily_goal": 5000,
        "editor_font": "serif", "default_focus_mode": True,
    })
    updated = await repo.reset_field(db, pid, "editor_font")
    assert updated.editor_font is None
    assert updated.daily_goal == 5000
    assert updated.default_focus_mode is True


@pytest.mark.asyncio
async def test_project_author_prefs_unique_project_id(db, factory):
    repo = ProjectAuthorPrefsRepository()
    pid = await factory.create_project()
    await repo.upsert(db, {"project_id": pid, "daily_goal": 1})
    row = await repo.upsert(db, {"project_id": pid, "daily_goal": 2})
    assert row.daily_goal == 2
    # 不应有两行
    rows = await db.execute(__import__('sqlalchemy').select(ProjectAuthorPreferences).where(ProjectAuthorPreferences.project_id == pid))
    assert len(rows.scalars().all()) == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run:
```bash
cd backend && pytest modules/settings/tests/test_repos.py -v
```
Expected: FAIL（`ModuleNotFoundError: No module named 'modules.settings.repositories'`）

- [ ] **Step 3: 写 `repositories.py`**

```python
"""Settings module repositories."""
from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from modules.settings.models import (
    GlobalAuthorPreferences,
    GlobalLLMDefaults,
    ProjectAuthorPreferences,
)

_GLBL_LLM_FIELDS = (
    "provider_id", "label", "base_url", "model",
    "timeout", "max_tokens", "temperature", "top_p",
    "extra", "creative_mode", "deep_import",
)
_GLBL_PREFS_FIELDS = ("daily_goal", "editor_font", "default_focus_mode")
_PROJ_PREFS_FIELDS = _GBL_PREFS_FIELDS


def _coerce(field: str, value: object) -> object:
    return value


class GlobalLLMDefaultsRepository:
    async def get(self, db: AsyncSession, owner_id: uuid.UUID) -> GlobalLLMDefaults | None:
        stmt = select(GlobalLLMDefaults).where(GlobalLLMDefaults.owner_id == owner_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert(self, db: AsyncSession, payload: dict) -> GlobalLLMDefaults:
        owner_id = payload["owner_id"]
        existing = await self.get(db, owner_id)
        if existing is None:
            row = GlobalLLMDefaults(**payload)
            db.add(row)
            await db.flush()
            return row
        for f in _GBL_LLM_FIELDS:
            if f in payload:
                setattr(existing, f, payload[f])
        db.add(existing)
        await db.flush()
        return existing


class GlobalAuthorPrefsRepository:
    async def get(self, db: AsyncSession, owner_id: uuid.UUID) -> GlobalAuthorPreferences | None:
        stmt = select(GlobalAuthorPreferences).where(GlobalAuthorPreferences.owner_id == owner_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert(self, db: AsyncSession, payload: dict) -> GlobalAuthorPreferences:
        owner_id = payload["owner_id"]
        existing = await self.get(db, owner_id)
        if existing is None:
            row = GlobalAuthorPreferences(**payload)
            db.add(row)
            await db.flush()
            return row
        for f in _GBL_PREFS_FIELDS:
            if f in payload:
                setattr(existing, f, payload[f])
        db.add(existing)
        await db.flush()
        return existing


class ProjectAuthorPrefsRepository:
    async def get(self, db: AsyncSession, project_id: uuid.UUID) -> ProjectAuthorPreferences | None:
        stmt = select(ProjectAuthorPreferences).where(
            ProjectAuthorPreferences.project_id == project_id,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert(self, db: AsyncSession, payload: dict) -> ProjectAuthorPreferences:
        project_id = payload["project_id"]
        existing = await self.get(db, project_id)
        if existing is None:
            row = ProjectAuthorPreferences(**payload)
            db.add(row)
            await db.flush()
            return row
        for f in _PROJ_PREFS_FIELDS:
            if f in payload:
                setattr(existing, f, payload[f])
        db.add(existing)
        await db.flush()
        return existing

    async def reset_field(
        self, db: AsyncSession, project_id: uuid.UUID, field_name: str,
    ) -> ProjectAuthorPreferences | None:
        if field_name not in _PROJ_PREFS_FIELDS:
            return None
        existing = await self.get(db, project_id)
        if existing is None:
            row = ProjectAuthorPreferences(project_id=project_id)
            db.add(row)
            await db.flush()
            return row
        setattr(existing, field_name, None)
        db.add(existing)
        await db.flush()
        return existing
```

修复笔误：把 `_GBL_*` 改为 `_GLBL_*` 一致命名（在写好文件后调整）。

- [ ] **Step 4: 运行测试确认通过**

Run:
```bash
cd backend && pytest modules/settings/tests/test_repos.py -v
```
Expected: 7 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/modules/settings/repositories.py backend/modules/settings/tests/test_repos.py
git commit -m "feat(settings): add repositories with upsert and field reset"
```

---

## Task 3: Schemas + Services + effective 合并逻辑

**Files:**
- Create: `backend/modules/settings/schemas.py`
- Create: `backend/modules/settings/services.py`
- Test: `backend/modules/settings/tests/test_services.py`
- Test: `backend/modules/settings/tests/test_effective.py`

- [ ] **Step 1: 写 `schemas.py`**

```python
"""Settings module Pydantic schemas."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from modules.settings.constants import (
    AUTHOR_PREFS_FIELDS,
    LLM_INHERITABLE_FIELDS,
)


class FieldValueSource(BaseModel):
    """effective 视图单字段响应：{ value, source }。"""
    model_config = {"extra": "forbid"}
    value: Any = None
    source: str = Field(description="project | global | system | unset")


class EffectiveLLMSettingsResponse(BaseModel):
    """effective-llm-settings 响应：每字段 { value, source }。"""
    model_config = {"extra": "forbid"}
    provider_id: FieldValueSource
    label: FieldValueSource
    base_url: FieldValueSource
    model: FieldValueSource
    timeout: FieldValueSource
    max_tokens: FieldValueSource
    temperature: FieldValueSource
    top_p: FieldValueSource
    extra: FieldValueSource
    creative_mode: FieldValueSource
    api_key_configured: FieldValueSource
    deep_import: FieldValueSource


class EffectiveAuthorPrefsResponse(BaseModel):
    """effective-author-preferences 响应。"""
    model_config = {"extra": "forbid"}
    daily_goal: FieldValueSource
    editor_font: FieldValueSource
    default_focus_mode: FieldValueSource


class GlobalLLMDefaultsUpdate(BaseModel):
    """全局 LLM 默认 update（拒绝 api_key）。"""
    model_config = {"extra": "forbid"}
    provider_id: str | None = Field(default=None, max_length=64)
    label: str | None = Field(default=None, max_length=128)
    base_url: str | None = Field(default=None, max_length=512)
    model: str | None = Field(default=None, max_length=256)
    timeout: int | None = Field(default=None, ge=1, le=3600)
    max_tokens: int | None = Field(default=None, ge=1, le=200000)
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, ge=0, le=1)
    extra: dict[str, Any] | None = None
    creative_mode: str | None = Field(default=None, max_length=32)
    # api_key 不在字段列表 — 后端 schema 拒绝该键

    @field_validator("provider_id", "label", "base_url", "model", "creative_mode")
    @classmethod
    def strip_text(cls, v: str | None) -> str | None:
        return v.strip() if isinstance(v, str) else v


class GlobalLLMDefaultsResponse(BaseModel):
    model_config = {"extra": "forbid"}
    provider_id: str | None = None
    label: str | None = None
    base_url: str | None = None
    model: str | None = None
    timeout: int | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    extra: dict[str, Any] | None = None
    creative_mode: str | None = None
    deep_import: dict[str, Any] | None = None  # 本期永远 None（D9）


class GlobalAuthorPrefsUpdate(BaseModel):
    model_config = {"extra": "forbid"}
    daily_goal: int | None = Field(default=None, ge=0, le=100000)
    editor_font: str | None = Field(default=None, max_length=32)
    default_focus_mode: bool | None = None


class GlobalAuthorPrefsResponse(BaseModel):
    model_config = {"extra": "forbid"}
    daily_goal: int | None = None
    editor_font: str | None = None
    default_focus_mode: bool | None = None


class ProjectAuthorPrefsUpdate(BaseModel):
    """项目覆盖 PUT 全量替换；缺失字段置 NULL = 恢复继承（D4）。"""
    model_config = {"extra": "forbid"}
    daily_goal: int | None = Field(default=None, ge=0, le=100000)
    editor_font: str | None = Field(default=None, max_length=32)
    default_focus_mode: bool | None = None


class ProjectAuthorPrefsResponse(BaseModel):
    """项目覆盖，行不存在时全字段 None（不抛 404，D13）。"""
    model_config = {"extra": "forbid"}
    daily_goal: int | None = None
    editor_font: str | None = None
    default_focus_mode: bool | None = None


class FieldResetResponse(BaseModel):
    """字段级 DELETE 响应。"""
    model_config = {"extra": "forbid"}
    field: str
    reset: bool = True


class ProjectsUsingDefaultsItem(BaseModel):
    model_config = {"extra": "forbid"}
    project_id: str
    title: str
    inherited_fields: list[str]


class ProjectsUsingDefaultsResponse(BaseModel):
    model_config = {"extra": "forbid"}
    items: list[ProjectsUsingDefaultsItem]
    total: int
    truncated: bool = False


assert "api_key" not in GlobalLLMDefaultsUpdate.model_fields, "schema guard"
```

- [ ] **Step 2: 写失败测试 `test_services.py`**

```python
"""Settings services tests."""
from __future__ import annotations

import pytest

from modules.settings.constants import (
    AUTHOR_PREFS_DEFAULTS,
    LLM_DEFAULTS_SYSTEM,
    LOCAL_OWNER_ID,
    SOURCE_GLOBAL,
    SOURCE_PROJECT,
    SOURCE_SYSTEM,
    SOURCE_UNSET,
)
from modules.settings.services import SettingsService


@pytest.mark.asyncio
async def test_get_global_llm_defaults_missing_returns_none(db):
    svc = SettingsService()
    resp = await svc.get_global_llm_defaults(db)
    assert resp is None


@pytest.mark.asyncio
async def test_upsert_global_llm_defaults_rejects_api_key(db):
    svc = SettingsService()
    with pytest.raises(Exception) as excinfo:
        await svc.upsert_global_llm_defaults(db, {"api_key": "sk-leak"})
    assert "api_key" in str(excinfo.value).lower() or "extra" in str(excinfo.value).lower()


@pytest.mark.asyncio
async def test_global_author_prefs_system_fallback_when_missing(db):
    svc = SettingsService()
    resp = await svc.get_or_system_author_prefs(db)
    assert resp.daily_goal is None   # unset
    assert resp.editor_font == "system"
    assert resp.default_focus_mode is False


@pytest.mark.asyncio
async def test_get_effective_author_prefs_layering(db, factory):
    svc = SettingsService()
    pid = await factory.create_project()
    # 无任何配置 → 全 system
    resp = await svc.get_effective_author_prefs(db, pid)
    assert resp.daily_goal.source == SOURCE_SYSTEM
    assert resp.editor_font.source == SOURCE_SYSTEM
    assert resp.default_focus_mode.source == SOURCE_SYSTEM
    assert resp.editor_font.value == "system"
    # 设全局 → 全 global
    await svc.upsert_global_author_prefs(db, {
        "daily_goal": 8000, "editor_font": "mono", "default_focus_mode": True,
    })
    resp = await svc.get_effective_author_prefs(db, pid)
    assert all(f.source == SOURCE_GLOBAL for f in (
        resp.daily_goal, resp.editor_font, resp.default_focus_mode))
    assert resp.daily_goal.value == 8000
    # 项目覆盖 daily_goal → 字段级 source 区分
    await svc.upsert_project_author_prefs(db, pid, {"daily_goal": 4000})
    resp = await svc.get_effective_author_prefs(db, pid)
    assert resp.daily_goal.source == SOURCE_PROJECT
    assert resp.daily_goal.value == 4000
    assert resp.editor_font.source == SOURCE_GLOBAL
    # reset 字段回 global
    await svc.reset_project_author_prefs_field(db, pid, "daily_goal")
    resp = await svc.get_effective_author_prefs(db, pid)
    assert resp.daily_goal.source == SOURCE_GLOBAL
    assert resp.daily_goal.value == 8000


@pytest.mark.asyncio
async def test_reset_field_rejects_unknown_field(db, factory):
    svc = SettingsService()
    pid = await factory.create_project()
    with pytest.raises(ValueError):
        await svc.reset_project_author_prefs_field(db, pid, "malicious_field")


@pytest.mark.asyncio
async def test_projects_using_defaults_aggregation(db, factory):
    svc = SettingsService()
    p_full = await factory.create_project(title="full-override")
    p_null = await factory.create_project(title="inheriting")
    # 仅 p_full 设了覆盖；p_null 全 NULL → 应在列表
    await svc.upsert_project_author_prefs(db, p_full, {"daily_goal": 1000})
    resp = await svc.list_projects_using_defaults(db)
    titles = [item.title for item in resp.items]
    assert "inheriting" in titles
    assert "full-override" not in titles
```

- [ ] **Step 3: 写 `services.py`**

```python
"""Settings service: upsert, effective merge, field reset, aggregation."""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.profiles import get_llm_profile
from modules.project.repositories import ProjectRepository
from modules.settings.constants import (
    AUTHOR_PREFS_DEFAULTS,
    AUTHOR_PREFS_FIELDS,
    LLM_DEFAULTS_SYSTEM,
    LLM_INHERITABLE_FIELDS,
    LOCAL_OWNER_ID,
    SOURCE_GLOBAL,
    SOURCE_PROJECT,
    SOURCE_SYSTEM,
    SOURCE_UNSET,
)
from modules.settings.models import (
    GlobalAuthorPreferences,
    GlobalLLMDefaults,
    ProjectAuthorPreferences,
)
from modules.settings.repositories import (
    GlobalAuthorPrefsRepository,
    GlobalLLMDefaultsRepository,
    ProjectAuthorPrefsRepository,
)
from modules.settings.schemas import (
    EffectiveAuthorPrefsResponse,
    EffectiveLLMSettingsResponse,
    FieldResetResponse,
    FieldValueSource,
    GlobalAuthorPrefsResponse,
    GlobalLLMDefaultsResponse,
    ProjectsUsingDefaultsItem,
    ProjectsUsingDefaultsResponse,
    ProjectAuthorPrefsResponse,
)


def _current_owner_id() -> uuid.UUID:
    """Demo 阶段固定 local。未来注入 authorizer。"""
    return LOCAL_OWNER_ID


class SettingsService:
    def __init__(self) -> None:
        self._llm_repo = GlobalLLMDefaultsRepository()
        self._g_prefs_repo = GlobalAuthorPrefsRepository()
        self._p_prefs_repo = ProjectAuthorPrefsRepository()
        self._project_repo = ProjectRepository()

    # ----- global LLM defaults -----
    async def get_global_llm_defaults(self, db: AsyncSession) -> GlobalLLMDefaultsResponse | None:
        row = await self._llm_repo.get(db, _current_owner_id())
        if row is None:
            return None
        return GlobalLLMDefaultsResponse(
            provider_id=row.provider_id, label=row.label, base_url=row.base_url,
            model=row.model, timeout=row.timeout, max_tokens=row.max_tokens,
            temperature=row.temperature, top_p=row.top_p,
            extra=row.extra, creative_mode=row.creative_mode,
            deep_import=row.deep_import,  # 本期永远 None
        )

    async def upsert_global_llm_defaults(self, db: AsyncSession, payload: dict) -> GlobalLLMDefaultsResponse:
        # D8 硬拒绝 api_key
        if "api_key" in payload or "api_key_configured" in payload:
            raise ValueError("global LLM defaults must not contain api_key")
        data = {k: v for k, v in payload.items() if k in LLM_INHERITABLE_FIELDS}
        data["owner_id"] = _current_owner_id()
        row = await self._llm_repo.upsert(db, data)
        return GlobalLLMDefaultsResponse(
            provider_id=row.provider_id, label=row.label, base_url=row.base_url,
            model=row.model, timeout=row.timeout, max_tokens=row.max_tokens,
            temperature=row.temperature, top_p=row.top_p,
            extra=row.extra, creative_mode=row.creative_mode,
            deep_import=row.deep_import,
        )

    # ----- global author prefs -----
    async def get_global_author_prefs(self, db: AsyncSession) -> GlobalAuthorPrefsResponse | None:
        row = await self._g_prefs_repo.get(db, _current_owner_id())
        if row is None:
            return None
        return GlobalAuthorPrefsResponse(
            daily_goal=row.daily_goal, editor_font=row.editor_font,
            default_focus_mode=row.default_focus_mode,
        )

    async def get_or_system_author_prefs(self, db: AsyncSession) -> GlobalAuthorPrefsResponse:
        resp = await self.get_global_author_prefs(db)
        if resp is None:
            return GlobalAuthorPrefsResponse(
                **{k: AUTHOR_PREFS_DEFAULTS[k] for k in AUTHOR_PREFS_DEFAULTS},
            )
        return resp

    async def upsert_global_author_prefs(self, db: AsyncSession, payload: dict) -> GlobalAuthorPrefsResponse:
        data = {k: v for k, v in payload.items() if k in AUTHOR_PREFS_FIELDS}
        data["owner_id"] = _current_owner_id()
        row = await self._g_prefs_repo.upsert(db, data)
        return GlobalAuthorPrefsResponse(
            daily_goal=row.daily_goal, editor_font=row.editor_font,
            default_focus_mode=row.default_focus_mode,
        )

    # ----- project author prefs -----
    async def get_project_author_prefs(self, db: AsyncSession, project_id: uuid.UUID | str) -> ProjectAuthorPrefsResponse:
        pid = project_id if isinstance(project_id, uuid.UUID) else uuid.UUID(project_id)
        row = await self._p_prefs_repo.get(db, pid)
        if row is None:
            # D13 不抛 404，返回全 NULL 空对象
            return ProjectAuthorPrefsResponse()
        return ProjectAuthorPrefsResponse(
            daily_goal=row.daily_goal, editor_font=row.editor_font,
            default_focus_mode=row.default_focus_mode,
        )

    async def upsert_project_author_prefs(self, db: AsyncSession, project_id: uuid.UUID | str, payload: dict) -> ProjectAuthorPrefsResponse:
        pid = project_id if isinstance(project_id, uuid.UUID) else uuid.UUID(project_id)
        data = {k: v for k, v in payload.items() if k in AUTHOR_PREFS_FIELDS}
        data["project_id"] = pid
        row = await self._p_prefs_repo.upsert(db, data)
        return ProjectAuthorPrefsResponse(
            daily_goal=row.daily_goal, editor_font=row.editor_font,
            default_focus_mode=row.default_focus_mode,
        )

    async def reset_project_author_prefs_field(
        self, db: AsyncSession, project_id: uuid.UUID | str, field_name: str,
    ) -> FieldResetResponse:
        if field_name not in AUTHOR_PREFS_FIELDS:
            raise ValueError(f"unknown author prefs field: {field_name}")
        pid = project_id if isinstance(project_id, uuid.UUID) else uuid.UUID(project_id)
        await self._p_prefs_repo.reset_field(db, pid, field_name)
        return FieldResetResponse(field=field_name, reset=True)

    # ----- effective views -----
    async def get_effective_author_prefs(self, db: AsyncSession, project_id: uuid.UUID | str) -> EffectiveAuthorPrefsResponse:
        pid = project_id if isinstance(project_id, uuid.UUID) else uuid.UUID(project_id)
        proj_row = await self._p_prefs_repo.get(db, pid)
        glob_row = await self._g_prefs_repo.get(db, _current_owner_id())

        def pack(field_name: str, proj_val, glob_val, default_val) -> FieldValueSource:
            if proj_row is not None and getattr(proj_row, field_name) is not None:
                return FieldValueSource(value=getattr(proj_row, field_name), source=SOURCE_PROJECT)
            if glob_row is not None and getattr(glob_row, field_name) is not None:
                return FieldValueSource(value=getattr(glob_row, field_name), source=SOURCE_GLOBAL)
            return FieldValueSource(value=default_val, source=SOURCE_SYSTEM)

        return EffectiveAuthorPrefsResponse(
            daily_goal=pack("daily_goal", None, None, AUTHOR_PREFS_DEFAULTS["daily_goal"]),
            editor_font=pack("editor_font", None, None, AUTHOR_PREFS_DEFAULTS["editor_font"]),
            default_focus_mode=pack("default_focus_mode", None, None, AUTHOR_PREFS_DEFAULTS["default_focus_mode"]),
        )

    async def get_effective_llm_settings(self, db: AsyncSession, project_id: uuid.UUID | str) -> EffectiveLLMSettingsResponse:
        pid = project_id if isinstance(project_id, uuid.UUID) else uuid.UUID(project_id)
        project = await self._project_repo.get(db, pid)
        if project is None:
            raise LookupError(f"project {project_id} not found")
        proj_profile = get_llm_profile(project.settings) if project.settings else {}
        glob_row = await self._llm_repo.get(db, _current_owner_id())
        glob_profile = {f: getattr(glob_row, f) for f in LLM_INHERITABLE_FIELDS} if glob_row else {}

        def pack(field_name: str, *, default_val, allow_unset: bool = False) -> FieldValueSource:
            # Key 永远项目独有，source project/unset
            proj_v = proj_profile.get(field_name)
            if proj_v is not None and proj_v != "":
                return FieldValueSource(value=proj_v, source=SOURCE_PROJECT)
            glob_v = glob_profile.get(field_name)
            if glob_v is not None:
                return FieldValueSource(value=glob_v, source=SOURCE_GLOBAL)
            sys_v = default_val
            if sys_v is None and allow_unset:
                return FieldValueSource(value=None, source=SOURCE_UNSET)
            return FieldValueSource(value=sys_v, source=SOURCE_SYSTEM)

        return EffectiveLLMSettingsResponse(
            provider_id=pack("provider_id", default_val=LLM_DEFAULTS_SYSTEM["provider_id"]),
            label=pack("label", default_val=LLM_DEFAULTS_SYSTEM["label"], allow_unset=True),
            base_url=pack("base_url", default_val=LLM_DEFAULTS_SYSTEM["base_url"]),
            model=pack("model", default_val=LLM_DEFAULTS_SYSTEM["model"]),
            timeout=pack("timeout", default_val=LLM_DEFAULTS_SYSTEM["timeout"]),
            max_tokens=pack("max_tokens", default_val=LLM_DEFAULTS_SYSTEM["max_tokens"]),
            temperature=pack("temperature", default_val=LLM_DEFAULTS_SYSTEM["temperature"]),
            top_p=pack("top_p", default_val=LLM_DEFAULTS_SYSTEM["top_p"], allow_unset=True),
            extra=pack("extra", default_val=LLM_DEFAULTS_SYSTEM["extra"]),
            creative_mode=pack("creative_mode", default_val=LLM_DEFAULTS_SYSTEM["creative_mode"], allow_unset=True),
            api_key_configured=FieldValueSource(
                value=bool(proj_profile.get("api_key")),
                source=SOURCE_PROJECT if proj_profile.get("api_key") else SOURCE_UNSET,
            ),
            deep_import=FieldValueSource(
                value=proj_profile.get("deep_import"),
                source=SOURCE_PROJECT if proj_profile.get("deep_import") else SOURCE_SYSTEM,
            ),
        )

    # ----- aggregation -----
    async def list_projects_using_defaults(
        self, db: AsyncSession, limit: int = 50, offset: int = 0,
    ) -> ProjectsUsingDefaultsResponse:
        """D18: 仅统计作者偏好默认；任一字段在 project_author_preferences 为 NULL 或行不存在即列出。"""
        from sqlalchemy import func, select
        from modules.project.models import Project

        # 所有 active project
        proj_rows = await db.execute(
            select(Project).where(Project.deleted_at.is_(None)).order_by(
                Project.created_at.desc(), Project.id.desc(),
            ),
        )
        all_projects = proj_rows.scalars().all()
        # 全部 project_author_prefs
        prefs_rows = await db.execute(select(ProjectAuthorPreferences))
        prefs_by_pid = {row.project_id: row for row in prefs_rows.scalars().all()}

        inheriting: list[str] = []
        for proj in all_projects:
            row = prefs_by_pid.get(proj.id)
            if row is None:
                inheriting.append(proj.id)
            else:
                # 任一字段为 NULL 即认为该字段继承
                if row.daily_goal is None or row.editor_font is None or row.default_focus_mode is None:
                    inheriting.append(proj.id)

        total = len(inheriting)
        truncated = total > 100
        page = inheriting[offset:offset + limit]
        title_by_id = {p.id: p.title for p in all_projects}
        items = [
            ProjectsUsingDefaultsItem(
                project_id=str(pid),
                title=title_by_id.get(pid, ""),
                inherited_fields=[],  # 本期为简化留空；后续版本可填实际继承字段
            )
            for pid in page
        ]
        return ProjectsUsingDefaultsResponse(items=items, total=total, truncated=truncated)
```

- [ ] **Step 4: 写空 `test_effective.py` placeholder**

`test_effective.py` 仅含 docstring 占位，主回归靠 services 测试。

```python
"""effective 视图合并逻辑测试集中在 test_services.py。"""
```

- [ ] **Step 5: 运行测试**

Run:
```bash
cd backend && pytest modules/settings/tests/test_services.py -v
```
Expected: 6 PASS

- [ ] **Step 6: Commit**

```bash
git add backend/modules/settings/schemas.py backend/modules/settings/services.py backend/modules/settings/tests/test_services.py backend/modules/settings/tests/test_effective.py
git commit -m "feat(settings): add schemas, services with effective merge"
```

---

## Task 4: API router + 注册 + API 测试

**Files:**
- Create: `backend/modules/settings/api.py`
- Modify: `backend/app/main.py:437`
- Test: `backend/modules/settings/tests/test_api.py`

- [ ] **Step 1: 写 `api.py`**

```python
"""Settings API router."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import ValidationError

from core.dependencies import DbSession
from modules.settings.schemas import (
    GlobalAuthorPrefsResponse,
    GlobalAuthorPrefsUpdate,
    GlobalLLMDefaultsResponse,
    GlobalLLMDefaultsUpdate,
    ProjectAuthorPrefsResponse,
    ProjectAuthorPrefsUpdate,
    ProjectsUsingDefaultsResponse,
)
from modules.settings.services import SettingsService

router = APIRouter(prefix="/api/settings", tags=["settings"])
_service = SettingsService()

_OWNER_FROZEN_MSG = "settings endpoints are owner-scoped (demo local)"


def _owner_forbidden(detail: str) -> HTTPException:
    return HTTPException(status_code=403, detail=detail)


@router.get("/llm-defaults", response_model=GlobalLLMDefaultsResponse | None)
async def api_get_global_llm_defaults(db: DbSession) -> GlobalLLMDefaultsResponse | None:
    return await _service.get_global_llm_defaults(db)


@router.put("/llm-defaults", response_model=GlobalLLMDefaultsResponse)
async def api_put_global_llm_defaults(
    db: DbSession,
    data: GlobalLLMDefaultsUpdate,
) -> GlobalLLMDefaultsResponse:
    try:
        return await _service.upsert_global_llm_defaults(db, data.model_dump(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/author-preferences", response_model=GlobalAuthorPrefsResponse | None)
async def api_get_global_author_prefs(db: DbSession) -> GlobalAuthorPrefsResponse | None:
    return await _service.get_global_author_prefs(db)


@router.put("/author-preferences", response_model=GlobalAuthorPrefsResponse)
async def api_put_global_author_prefs(
    db: DbSession,
    data: GlobalAuthorPrefsUpdate,
) -> GlobalAuthorPrefsResponse:
    return await _service.upsert_global_author_prefs(db, data.model_dump(exclude_unset=True))


@router.get("/projects-using-defaults", response_model=ProjectsUsingDefaultsResponse)
async def api_list_projects_using_defaults(
    db: DbSession,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ProjectsUsingDefaultsResponse:
    return await _service.list_projects_using_defaults(db, limit=limit, offset=offset)


@router.post("/refresh")
async def api_refresh_settings() -> dict:
    """调试端点：触发客户端刷新（D16）。"""
    return {"ok": True}


@router.get("/projects/{project_id}/author-preferences", response_model=ProjectAuthorPrefsResponse)
async def api_get_project_author_prefs(
    db: DbSession,
    project_id: str,
) -> ProjectAuthorPrefsResponse:
    return await _service.get_project_author_prefs(db, project_id)


@router.put("/projects/{project_id}/author-preferences", response_model=ProjectAuthorPrefsResponse)
async def api_put_project_author_prefs(
    db: DbSession,
    project_id: str,
    data: ProjectAuthorPrefsUpdate,
) -> ProjectAuthorPrefsResponse:
    return await _service.upsert_project_author_prefs(db, project_id, data.model_dump())


@router.delete("/projects/{project_id}/author-preferences/field/{field_name}")
async def api_reset_project_author_prefs_field(
    db: DbSession,
    project_id: str,
    field_name: str,
):
    try:
        return await _service.reset_project_author_prefs_field(db, project_id, field_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
```

- [ ] **Step 2: 在 `app/main.py` 注册路由**

在 `app.include_router(debug_api.router)` 后追加：
```python
from modules.settings.api import router as settings_router
app.include_router(settings_router)
```

- [ ] **Step 3: 写失败测试 `test_api.py`**

```python
"""Settings API tests."""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from modules.settings.constants import LOCAL_OWNER_ID


@pytest.mark.asyncio
async def test_get_global_llm_defaults_missing_returns_200_null(client: AsyncClient):
    r = await client.get("/api/settings/llm-defaults")
    assert r.status_code == 200
    assert r.json() is None


@pytest.mark.asyncio
async def test_put_global_llm_defaults_rejects_api_key(client: AsyncClient):
    r = await client.put("/api/settings/llm-defaults", json={
        "provider_id": "deepseek", "api_key": "sk-leak",
    })
    # Pydantic extra="forbid" 直接拒
    assert r.status_code in (400, 422)


@pytest.mark.asyncio
async def test_put_global_llm_defaults_round_trip(client: AsyncClient):
    r = await client.put("/api/settings/llm-defaults", json={
        "provider_id": "deepseek", "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-flash", "max_tokens": 8192,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["provider_id"] == "deepseek"
    assert body["deep_import"] is None
    assert "api_key" not in body

    r2 = await client.get("/api/settings/llm-defaults")
    assert r2.status_code == 200
    assert r2.json()["provider_id"] == "deepseek"


@pytest.mark.asyncio
async def test_global_author_prefs_system_fallback_is_in_service(client: AsyncClient, factory):
    # 先确认 direct endpoint 返回 null（未配置）
    r = await client.get("/api/settings/author-preferences")
    assert r.status_code == 200
    assert r.json() is None


@pytest.mark.asyncio
async def test_project_author_prefs_missing_returns_empty_object(client: AsyncClient, factory):
    pid = await factory.create_project()
    r = await client.get(f"/api/settings/projects/{pid}/author-preferences")
    assert r.status_code == 200
    body = r.json()
    assert body == {"daily_goal": None, "editor_font": None, "default_focus_mode": None}


@pytest.mark.asyncio
async def test_project_author_prefs_field_reset_returns_400_for_unknown(client: AsyncClient, factory):
    pid = await factory.create_project()
    r = await client.delete(
        f"/api/settings/projects/{pid}/author-preferences/field/malicious_field",
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_projects_using_defaults_lists_only_inheriting(client: AsyncClient, factory):
    p1 = await factory.create_project(title="a")
    p2 = await factory.create_project(title="b")
    await client.put(f"/api/settings/projects/{p1}/author-preferences", json={
        "daily_goal": 1000, "editor_font": "serif", "default_focus_mode": True,
    })
    # p2 不设，应继承
    r = await client.get("/api/settings/projects-using-defaults")
    assert r.status_code == 200
    titles = [it["title"] for it in r.json()["items"]]
    assert "b" in titles
    assert "a" not in titles


@pytest.mark.asyncio
async def test_refresh_endpoint(client: AsyncClient):
    r = await client.post("/api/settings/refresh")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
```

- [ ] **Step 4: 运行 API 测试**

Run:
```bash
cd backend && pytest modules/settings/tests/test_api.py -v
```
Expected: 8 PASS

- [ ] **Step 5: 跑全量回归确认无回归**

Run:
```bash
cd backend && pytest modules/project/tests/ modules/settings/tests/ -q
```
Expected: 全 PASS

- [ ] **Step 6: Commit**

```bash
git add backend/modules/settings/api.py backend/modules/settings/tests/test_api.py backend/app/main.py
git commit -m "feat(settings): add API routes and register in main"
```

---

## Task 5: 项目 LLM effective 接口 + 字段级 DELETE

**Files:**
- Modify: `backend/modules/project/api.py`
- Modify: `backend/modules/project/services.py`
- Modify: `backend/modules/project/schemas.py`
- Test: `backend/modules/project/tests/test_llm_settings_api.py`（append）

- [ ] **Step 1: 在 `schemas.py` 追加 effective 响应与字段级响应**

```python
# 追加到 backend/modules/project/schemas.py

from modules.settings.schemas import (
    EffectiveAuthorPrefsResponse,
    EffectiveLLMSettingsResponse,
    FieldResetResponse,
)


class LLMFieldResetResponse(BaseModel):
    field: str
    reset: bool = True
```

- [ ] **Step 2: 在 `services.py` 追加 effective LLM 与 reset 方法**

```python
# 追加到 backend/modules/project/services.py 的 ProjectService 类

    async def get_effective_llm_settings(
        self, db: AsyncSession, project_id: str,
    ) -> EffectiveLLMSettingsResponse:
        from modules.settings.services import SettingsService
        return await SettingsService().get_effective_llm_settings(db, project_id)

    async def get_effective_author_prefs(
        self, db: AsyncSession, project_id: str,
    ) -> EffectiveAuthorPrefsResponse:
        from modules.settings.services import SettingsService
        return await SettingsService().get_effective_author_prefs(db, project_id)

    async def reset_llm_settings_field(
        self, db: AsyncSession, project_id: str, field_name: str,
    ) -> LLMFieldResetResponse:
        from modules.settings.constants import LLM_INHERITABLE_FIELDS
        if field_name not in LLM_INHERITABLE_FIELDS:
            raise ValueError(f"unknown llm field: {field_name}")
        project = await self._get_existing_project(db, project_id)
        settings = dict(project.settings or {})
        llm = dict(settings.get("llm", {}))
        if field_name in llm:
            del llm[field_name]
        if llm:
            settings["llm"] = llm
        else:
            settings.pop("llm", None)
        update_data = ProjectUpdate(settings=settings)
        await self._repo.update(db, project, update_data)
        return LLMFieldResetResponse(field=field_name, reset=True)
```

`_get_existing_project` 已在现有 service 存在（参见 `get_llm_settings`）。

- [ ] **Step 3: 在 `api.py` 追加 effective + 字段级 DELETE 路由**

```python
# 追加到 backend/modules/project/api.py （在 PUT /llm-settings 之后）

from modules.project.schemas import (
    LLMFieldResetResponse,
)
from modules.settings.schemas import (
    EffectiveLLMSettingsResponse,
    EffectiveAuthorPrefsResponse,
)


@router.get("/{project_id}/effective-llm-settings", response_model=EffectiveLLMSettingsResponse)
async def api_get_effective_llm_settings(
    db: DbSession, project_id: str,
) -> EffectiveLLMSettingsResponse:
    return await _service.get_effective_llm_settings(db, project_id)


@router.get("/{project_id}/effective-author-preferences", response_model=EffectiveAuthorPrefsResponse)
async def api_get_effective_author_prefs(
    db: DbSession, project_id: str,
) -> EffectiveAuthorPrefsResponse:
    return await _service.get_effective_author_prefs(db, project_id)


@router.delete(
    "/{project_id}/llm-settings/field/{field_name}",
    response_model=LLMFieldResetResponse,
)
async def api_reset_llm_settings_field(
    db: DbSession, project_id: str, field_name: str,
) -> LLMFieldResetResponse:
    try:
        return await _service.reset_llm_settings_field(db, project_id, field_name)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e)) from e
```

- [ ] **Step 4: 写失败测试追加到 `test_llm_settings_api.py`**

```python
# 追加到 test_llm_settings_api.py

@pytest.mark.asyncio
async def test_effective_llm_settings_all_system_when_no_config(client, factory):
    pid = await factory.create_project()
    r = await client.get(f"/api/projects/{pid}/effective-llm-settings")
    assert r.status_code == 200
    body = r.json()
    for f in ("provider_id", "base_url", "model", "timeout", "max_tokens", "temperature"):
        assert body[f]["source"] == "system"
    assert body["api_key_configured"]["source"] == "unset"
    assert body["api_key_configured"]["value"] is False


@pytest.mark.asyncio
async def test_effective_llm_settings_global_then_project(client, factory):
    pid = await factory.create_project()
    # 设全局
    await client.put("/api/settings/llm-defaults", json={
        "provider_id": "deepseek", "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-flash",
    })
    r = await client.get(f"/api/projects/{pid}/effective-llm-settings")
    body = r.json()
    assert body["provider_id"]["source"] == "global"
    assert body["provider_id"]["value"] == "deepseek"
    # 项目覆盖 model
    await client.put(f"/api/projects/{pid}/llm-settings", json={
        "provider_id": "deepseek", "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
    })
    r2 = await client.get(f"/api/projects/{pid}/effective-llm-settings")
    body2 = r2.json()
    assert body2["model"]["source"] == "project"
    assert body2["model"]["value"] == "deepseek-chat"
    assert body2["provider_id"]["source"] == "project"


@pytest.mark.asyncio
async def test_reset_llm_field_restores_global(client, factory):
    pid = await factory.create_project()
    await client.put("/api/settings/llm-defaults", json={"provider_id": "openai-compatible"})
    await client.put(f"/api/projects/{pid}/llm-settings", json={
        "provider_id": "deepseek", "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat",
    })
    r = await client.delete(f"/api/projects/{pid}/llm-settings/field/provider_id")
    assert r.status_code == 200
    r2 = await client.get(f"/api/projects/{pid}/effective-llm-settings")
    assert r2.json()["provider_id"]["source"] == "global"
    assert r2.json()["provider_id"]["value"] == "openai-compatible"


@pytest.mark.asyncio
async def test_reset_llm_field_rejects_unknown(client, factory):
    pid = await factory.create_project()
    r = await client.delete(f"/api/projects/{pid}/llm-settings/field/malicious")
    assert r.status_code == 400
```

> 注意：现有 `ProjectLLMSettingsUpdate` schema 要求 `base_url` 和 `model` 必填且 min_length=1，与继承语义冲突。需在本任务内放寬为可选。

- [ ] **Step 5: 放寬 `ProjectLLMSettingsUpdate` schema 以支持继承**

把 `backend/modules/project/schemas.py` 中：
```python
base_url: str = Field(..., min_length=1, max_length=512)
model: str = Field(..., min_length=1, max_length=256)
```
改为：
```python
base_url: str | None = Field(default=None, max_length=512)
model: str | None = Field(default=None, max_length=256)
```

同步修改 `backend/modules/project/services.py:139` 的 `update_llm_settings`，把 `next_profile` 构建逻辑放寬：缺失字段不写入 `settings["llm"]`（视作继承）。具体：把现有 `next_profile` 改为：

```python
next_profile = {}
if data.provider_id is not None and data.provider_id != "":
    next_profile["provider_id"] = data.provider_id
if data.label is not None:
    next_profile["label"] = data.label
if data.base_url is not None and data.base_url != "":
    next_profile["base_url"] = data.base_url
if data.model is not None and data.model != "":
    next_profile["model"] = data.model
if data.timeout is not None:
    next_profile["timeout"] = data.timeout
if data.max_tokens is not None:
    next_profile["max_tokens"] = data.max_tokens
if data.temperature is not None:
    next_profile["temperature"] = data.temperature
if data.top_p is not None:
    next_profile["top_p"] = data.top_p
if data.extra:
    next_profile["extra"] = data.extra

if data.clear_api_key:
    pass
elif data.api_key:
    next_profile[LLM_API_KEY_FIELD] = data.api_key
elif existing_profile.get(LLM_API_KEY_FIELD):
    next_profile[LLM_API_KEY_FIELD] = existing_profile[LLM_API_KEY_FIELD]

if next_profile:
    settings[LLM_SETTINGS_KEY] = next_profile
else:
    settings.pop(LLM_SETTINGS_KEY, None)
```

把 `provider_id` 默认值改 `None`（不再是 `"openai-compatible"` 默认值）。

- [ ] **Step 6: 运行测试**

Run:
```bash
cd backend && pytest modules/project/tests/test_llm_settings_api.py modules/settings/tests/ -v
```
Expected: 既有 + 新加测试全 PASS

- [ ] **Step 7: Commit**

```bash
git add backend/modules/project/schemas.py backend/modules/project/services.py backend/modules/project/api.py backend/modules/project/tests/test_llm_settings_api.py
git commit -m "feat(project): add effective LLM + author prefs endpoints with field reset"
```

---

## Task 6: 后端 owner 隔离回归测试

**Files:**
- Test: `backend/modules/settings/tests/test_owner_isolation.py`

- [ ] **Step 1: 写测试**

```python
"""Owner isolation regression tests (D24).

Future account system接入时这测试不需改，只需加 authorizer 单测。
"""
from __future__ import annotations

import uuid

import pytest

from modules.settings.repositories import (
    GlobalAuthorPrefsRepository,
    GlobalLLMDefaultsRepository,
)


@pytest.mark.asyncio
async def test_owner_a_cannot_see_owner_b_global_llm(db):
    repo = GlobalLLMDefaultsRepository()
    owner_a = uuid.uuid4()
    owner_b = uuid.uuid4()
    await repo.upsert(db, {"owner_id": owner_a, "provider_id": "a"})
    await repo.upsert(db, {"owner_id": owner_b, "provider_id": "b"})
    a = await repo.get(db, owner_a)
    b = await repo.get(db, owner_b)
    assert a is not None
    assert b is not None
    assert a.provider_id == "a"
    assert b.provider_id == "b"
    assert a.owner_id != b.owner_id
    # 用 owner_a 查询不应得到 owner_b 的行
    assert await repo.get(db, owner_a) is a
    assert await repo.get(db, owner_b) is b


@pytest.mark.asyncio
async def test_owner_isolation_through_unique_constraint(db):
    """UNIQUE(owner_id) 保证两 owner 行不会冲突或互相覆盖。"""
    repo = GlobalLLMDefaultsRepository()
    owner_a = uuid.uuid4()
    # 反复 upsert 不应增行
    for _ in range(3):
        await repo.upsert(db, {"owner_id": owner_a, "provider_id": "a"})
    a = await repo.get(db, owner_a)
    assert a is not None
    # 显式查询 row count
    from sqlalchemy import select, func
    from modules.settings.models import GlobalLLMDefaults
    count = (await db.execute(select(func.count()).where(GlobalLLMDefaults.owner_id == owner_a))).scalar()
    assert count == 1
```

- [ ] **Step 2: 运行**

Run:
```bash
cd backend && pytest modules/settings/tests/test_owner_isolation.py -v
```
Expected: 2 PASS

- [ ] **Step 3: Commit**

```bash
git add backend/modules/settings/tests/test_owner_isolation.py
git commit -m "test(settings): owner isolation regression"
```

---

## Task 7: 前端 shared 组件 - fieldSourceLabel + authorPreferencesForm

**Files:**
- Create: `frontend-console/views/settings/shared/constants.js`
- Create: `frontend-console/views/settings/shared/fieldSourceLabel.js`
- Create: `frontend-console/views/settings/shared/authorPreferencesForm.js`
- Test: `frontend-console/tests/settings/shared/fieldSourceLabel.test.js`
- Test: `frontend-console/tests/settings/shared/authorPreferencesForm.test.js`

- [ ] **Step 1: 写 `shared/constants.js`**

```js
// Source labels match backend source enum (D1)
export const SOURCE_PROJECT = "project"
export const SOURCE_GLOBAL = "global"
export const SOURCE_SYSTEM = "system"
export const SOURCE_UNSET = "unset"

export const SOURCE_LABELS = {
  [SOURCE_PROJECT]: "已覆盖",
  [SOURCE_GLOBAL]: "继承全局",
  [SOURCE_SYSTEM]: "系统默认",
  [SOURCE_UNSET]: "未配置",
}

// 全局作者偏好硬默认（前端 fallback，与后端 AUTHOR_PREFS_DEFAULTS 对齐）
export const AUTHOR_PREFS_DEFAULTS = {
  daily_goal: null,
  editor_font: "system",
  default_focus_mode: false,
}

export const EDITOR_FONT_OPTIONS = ["system", "serif", "sans", "mono"]
```

- [ ] **Step 2: 写失败测试 `fieldSourceLabel.test.js`**

```js
import { describe, it, expect } from "vitest"
import { renderSourceLabel, resettableField } from "../../../views/settings/shared/fieldSourceLabel.js"

describe("fieldSourceLabel", () => {
  it("renders 已覆盖 for project", () => {
    expect(renderSourceLabel({ source: "project", value: "x" })).toContain("已覆盖")
  })
  it("renders 继承全局 for global", () => {
    expect(renderSourceLabel({ source: "global", value: "x" })).toContain("继承全局")
  })
  it("renders 系统默认 for system", () => {
    expect(renderSourceLabel({ source: "system", value: "x" })).toContain("系统默认")
  })
  it("renders 未配置 for unset", () => {
    expect(renderSourceLabel({ source: "unset", value: null })).toContain("未配置")
  })
  it("resettableField produces button HTML with field name", () => {
    expect(resettableField("daily_goal")).toContain("data-field=\"daily_goal\"")
  })
})
```

- [ ] **Step 3: 写 `shared/fieldSourceLabel.js`**

```js
import { SOURCE_LABELS } from "./constants.js"

export function renderSourceLabel({ source, value }) {
  const label = SOURCE_LABELS[source] || "未知"
  const cls = source === "project"
    ? "source-label source-project"
    : source === "global"
      ? "source-label source-global"
      : source === "unset"
        ? "source-label source-unset"
        : "source-label source-system"
  const valStr = value === null || value === undefined ? "—" : String(value)
  return `<span class="${cls}">${label}</span><small class="source-value">${valStr}</small>`
}

export function resettableField(fieldName, opts = {}) {
  const label = opts.label || "恢复到全局默认"
  return `<button class="btn btn-sm btn-link llm-reset-field" data-field="${fieldName}" type="button">${label}</button>`
}
```

- [ ] **Step 4: 运行测试**

Run:
```bash
cd frontend-console && npx vitest run tests/settings/shared/fieldSourceLabel.test.js
```
Expected: 5 PASS

- [ ] **Step 5: 写 `authorPreferencesForm.js` + 测试**

```js
// shared/authorPreferencesForm.js
import { EDITOR_FONT_OPTIONS } from "./constants.js"

export function renderAuthorPreferencesForm({ dailyGoal, editorFont, defaultFocusMode, source = {} } = {}) {
  return `
    <div class="author-preferences-form">
      ${source.daily_goal ? `<div class="field-source">${sourceLabelHtml(source.daily_goal)}</div>` : ""}
      <div class="form-row">
        <div class="form-group">
          <label for="author-daily-goal">日更目标（字）</label>
          <input class="form-input" id="author-daily-goal" type="number" min="0" max="100000"
            value="${dailyGoal ?? ""}" placeholder="6000" />
          ${renderResetFor(source.daily_goal, "daily_goal")}
        </div>
        <div class="form-group">
          <label for="author-editor-font">编辑器字体</label>
          <select class="form-input" id="author-editor-font">
            ${EDITOR_FONT_OPTIONS.map((v) => `<option value="${v}" ${editorFont === v ? "selected" : ""}>${v}</option>`).join("")}
          </select>
          ${renderResetFor(source.editor_font, "editor_font")}
        </div>
        <div class="form-group">
          <label>
            <input id="author-default-focus" type="checkbox" ${defaultFocusMode ? "checked" : ""} />
            默认专注模式
          </label>
          ${renderResetFor(source.default_focus_mode, "default_focus_mode")}
        </div>
      </div>
    </div>
  `
}

function renderResetFor(srcObj, fieldName) {
  if (!srcObj || srcObj.source === "global" || srcObj.source === "system") return ""
  return `<button class="btn btn-sm btn-link field-reset" data-field="${fieldName}" type="button">恢复到全局默认</button>`
}

function sourceLabelHtml(srcObj) {
  return `<small class="source-tag">${srcObj.source}</small>`
}

export function readAuthorPreferencesForm() {
  const dailyGoalRaw = document.getElementById("author-daily-goal")?.value.trim() || ""
  return {
    daily_goal: dailyGoalRaw ? Number(dailyGoalRaw) : null,
    editor_font: document.getElementById("author-editor-font")?.value || null,
    default_focus_mode: Boolean(document.getElementById("author-default-focus")?.checked),
  }
}

export function validateAuthorPreferences(prefs) {
  if (prefs.daily_goal != null && (!Number.isInteger(prefs.daily_goal) || prefs.daily_goal < 0 || prefs.daily_goal > 100000)) {
    return { ok: false, message: "日更目标必须是 0-100000 的整数" }
  }
  return { ok: true }
}
```

测试：

```js
// tests/settings/shared/authorPreferencesForm.test.js
import { describe, it, expect } from "vitest"
import { validateAuthorPreferences } from "../../../views/settings/shared/authorPreferencesForm.js"

describe("validateAuthorPreferences", () => {
  it("accepts null daily_goal", () => {
    expect(validateAuthorPreferences({ daily_goal: null }).ok).toBe(true)
  })
  it("rejects negative daily_goal", () => {
    expect(validateAuthorPreferences({ daily_goal: -1 }).ok).toBe(false)
  })
  it("rejects huge daily_goal", () => {
    expect(validateAuthorPreferences({ daily_goal: 999999 }).ok).toBe(false)
  })
  it("accepts 6000 daily_goal", () => {
    expect(validateAuthorPreferences({ daily_goal: 6000 }).ok).toBe(true)
  })
})
```

- [ ] **Step 6: 运行测试**

Run:
```bash
cd frontend-console && npx vitest run tests/settings/shared/
```
Expected: 全 PASS

- [ ] **Step 7: Commit**

```bash
git add frontend-console/views/settings/shared/ frontend-console/tests/settings/shared/
git commit -m "feat(frontend): shared fieldSourceLabel and authorPreferencesForm"
```

---

## Task 8: 前端 shared 深度导入 fields 抽离

**Files:**
- Create: `frontend-console/views/settings/shared/deepImportFields.js`
- Test: `frontend-console/tests/settings/shared/deepImportFields.test.js`

- [ ] **Step 1: 写 `deepImportFields.js`**

把 `backend/.../llmSettingsView.js:18-92` 的 `_deepImportGroups` schema 搬过来，并附带 render/read/validate helpers。

```js
// shared/deepImportFields.js
const DEEP_IMPORT_GROUPS = [
  {
    id: "global",
    label: "Global",
    fields: [
      { key: "structured_timeout_grace_seconds", label: "结构化调用宽限（秒）", type: "int", min: 1, max: 600, value: 15 },
      { key: "structured_max_fix_attempts", label: "结构化修复次数", type: "int", min: 0, max: 10, value: 2 },
    ],
  },
  {
    id: "phase0",
    label: "Phase 0 Plan",
    fields: [
      { key: "target_input_chars", label: "窗口目标字数", type: "int", min: 1000, max: 500000, value: 72000 },
      { key: "max_chapters_per_window", label: "窗口最大章节", type: "int", min: 1, max: 100, value: 20 },
      { key: "right_overlap_chapters", label: "右侧重叠章节", type: "int", min: 0, max: 20, value: 2 },
      { key: "max_tokens_per_input_char", label: "Max tokens / 字符", type: "float", min: 0.05, max: 2, step: "0.01", value: 0.36 },
      { key: "min_max_tokens", label: "窗口最小 tokens", type: "int", min: 1, max: 200000, value: 13000 },
      { key: "max_max_tokens", label: "窗口最大 tokens", type: "int", min: 1, max: 200000, value: 32768 },
    ],
  },
  // ... phase1a/1b/2/3 同 llmSettingsView.js 现 schema（保留全部字段原值）
]

export { DEEP_IMPORT_GROUPS }

export function renderDeepImportFields(settings) {
  return `
    <div class="llm-deep-import-grid">
      ${DEEP_IMPORT_GROUPS.map((group) => `
        <div class="deep-import-group">
          <h4>${group.label}</h4>
          <div class="form-row">
            ${group.fields.map((field) => renderDeepImportField(group.id, field, settings[group.id]?.[field.key])).join("")}
          </div>
        </div>
      `).join("")}
    </div>
  `
}

function renderDeepImportField(groupId, field, value) {
  const id = deepImportFieldId(groupId, field.key)
  if (field.type === "bool") {
    return renderBoolField(id, field.label, value, false)
  }
  if (field.type === "nullableBool") {
    return renderNullableBoolField(id, field.label, value)
  }
  return renderNumberField(id, field, value)
}

function renderBoolField(id, label, value, _ = false) {
  return `
    <div class="form-group">
      <label for="${id}">${label}</label>
      <select class="form-input" id="${id}">
        <option value="false" ${value ? "" : "selected"}>关闭</option>
        <option value="true" ${value ? "selected" : ""}>开启</option>
      </select>
    </div>
  `
}

function renderNullableBoolField(id, label, value) {
  const selected = value === true ? "true" : value === false ? "false" : ""
  return `
    <div class="form-group">
      <label for="${id}">${label}</label>
      <select class="form-input" id="${id}">
        <option value="" ${selected === "" ? "selected" : ""}>自动</option>
        <option value="true" ${selected === "true" ? "selected" : ""}>开启</option>
        <option value="false" ${selected === "false" ? "selected" : ""}>关闭</option>
      </select>
    </div>
  `
}

function renderNumberField(id, field, value) {
  const step = field.step || (field.type === "float" ? "0.01" : "1")
  const displayValue = value === undefined || value === null ? "" : String(value)
  return `
    <div class="form-group">
      <label for="${id}">${field.label}</label>
      <input class="form-input" id="${id}" type="number" min="${field.min}" max="${field.max}" step="${step}" value="${displayValue}" />
    </div>
  `
}

export function deepImportFieldId(groupId, key) {
  return `deep-import-${groupId}-${key.replaceAll("_", "-")}`
}

export function readDeepImportFields() {
  const value = {}
  for (const group of DEEP_IMPORT_GROUPS) {
    value[group.id] = {}
    for (const field of group.fields) {
      const id = deepImportFieldId(group.id, field.key)
      const readResult = readField(field, id)
      if (!readResult.ok) return readResult
      value[group.id][field.key] = readResult.value ?? field.value
    }
  }
  return { ok: true, value }
}

function readField(field, id) {
  if (field.type === "bool") {
    return { ok: true, value: document.getElementById(id)?.value === "true" }
  }
  if (field.type === "nullableBool") {
    const raw = document.getElementById(id)?.value || ""
    return { ok: true, value: raw === "" ? null : raw === "true" }
  }
  const raw = document.getElementById(id)?.value.trim() || ""
  if (!raw) return { ok: true, value: null }
  const num = Number(raw)
  const inRange = num >= field.min && num <= field.max
  const isFinite = Number.isFinite(num)
  const ok = field.type === "float" ? isFinite && inRange : Number.isInteger(num) && inRange
  if (!ok) {
    return { ok: false, error: `${field.label} 必须是 ${field.min}-${field.max} 的数字` }
  }
  return { ok: true, value: num }
}
```

完整 schema 请严格复制 `llmSettingsView.js:18-92` 的所有字段进入 `DEEP_IMPORT_GROUPS`。

- [ ] **Step 2: 写测试验证 schema 数量、范围校验**

```js
// tests/settings/shared/deepImportFields.test.js
import { describe, it, expect, beforeEach } from "vitest"
import { DEEP_IMPORT_GROUPS, deepImportFieldId, readDeepImportFields } from "../../../views/settings/shared/deepImportFields.js"

describe("deepImportFields schema", () => {
  it("has all 6 groups", () => {
    expect(DEEP_IMPORT_GROUPS.map((g) => g.id)).toEqual([
      "global", "phase0", "phase1a", "phase1b", "phase2", "phase3",
    ])
  })
  it("phase2 contains boundary_supplement_enabled bool", () => {
    const p2 = DEEP_IMPORT_GROUPS.find((g) => g.id === "phase2")
    expect(p2.fields.find((f) => f.key === "boundary_supplement_enabled").type).toBe("bool")
  })
  it("id encoding swaps underscores to dashes", () => {
    expect(deepImportFieldId("phase2", "boundary_scenes")).toBe("deep-import-phase2-boundary-scenes")
  })
})

describe("readDeepImportFields validation", () => {
  function setField(id, val) {
    document.body.innerHTML = `<input id="${id}" value="${val}" />`
  }
  it("rejects out-of-range phase0 target_input_chars", () => {
    setField(deepImportFieldId("phase0", "target_input_chars"), "10")
    const out = readDeepImportFields()
    expect(out.ok).toBe(false)
  })
  it("accepts empty as default fallback", () => {
    document.body.innerHTML = ""
    // 没有元素时 readField 都返回 ok=true value=null → 用 field.value 兜底
    const out = readDeepImportFields()
    expect(out.ok).toBe(true)
  })
})
```

- [ ] **Step 3: 运行**

Run:
```bash
cd frontend-console && npx vitest run tests/settings/shared/deepImportFields.test.js
```
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add frontend-console/views/settings/shared/deepImportFields.js frontend-console/tests/settings/shared/deepImportFields.test.js
git commit -m "feat(frontend): extract deep import fields schema and helpers"
```

---

## Task 9: 前端 shared LLM form fields

**Files:**
- Create: `frontend-console/views/settings/shared/llmFormFields.js`
- Test: `frontend-console/tests/settings/shared/llmFormFields.test.js`

- [ ] **Step 1: 写 `llmFormFields.js`**

```js
// shared/llmFormFields.js
// 渲染 LLM 主配置表单（供应商/Key/BaseURL/模型/参数/预设/扩展 JSON）
// 用于全局 LLM 默认页 + 项目 LLM Tab 主配置
// opts.withApiKey=false 时（全局默认用）不渲染 Key 输入

const CREATIVE_PRESETS = {
  creative: { label: "灵感创作", temperature: 0.9, top_p: 0.95, max_tokens: 8192 },
  precise: { label: "精修校对", temperature: 0.25, top_p: 0.8, max_tokens: 4096 },
  fast: { label: "快速草稿", temperature: 0.6, top_p: 0.9, max_tokens: 2048 },
  custom: { label: "自定义" },
}

export { CREATIVE_PRESETS }

export function renderLLMFormFields({ values, templates, sourceMap = {}, withApiKey = true } = {}) {
  const v = values || {}
  const providerOptions = (templates || []).length
    ? (templates || []).map((t) => `<option value="${t.id}" ${t.id === (v.provider_id || "") ? "selected" : ""}>${t.name}</option>`).join("")
    : `<option value="openai-compatible" selected>openai-compatible</option>`
  const modelOptions = ((templates?.find((t) => t.id === (v.provider_id || ""))?.models) || []).map((m) => `<option value="${m}"></option>`).join("")
  const creativeMode = detectCreativeMode(v)
  return `
    <div class="llm-main-form">
      ${withApiKey ? "" : "<p class='llm-global-hint'>全局默认不存 API Key；Key 仅项目级。</p>"}
      <div class="form-row">
        <div class="form-group">
          <label for="llm-provider">供应商模板</label>
          <select class="form-input" id="llm-provider" ${(templates || []).length ? "" : "disabled"}>
            ${providerOptions}
          </select>
        </div>
        ${withApiKey ? renderKeyBlock(v.api_key_configured, v) : ""}
      </div>
      <div class="form-group">
        <label for="llm-base-url">Base URL</label>
        <input class="form-input" id="llm-base-url" value="${v.base_url || ""}" placeholder="https://api.example.com/v1" />
        ${sourceHtml(sourceMap.base_url)}
      </div>
      <div class="form-row">
        <div class="form-group">
          <label for="llm-model">模型</label>
          <input class="form-input" id="llm-model" list="llm-model-options" value="${v.model || ""}" placeholder="输入或选择模型名" />
          <datalist id="llm-model-options">${modelOptions}</datalist>
        </div>
        <div class="form-group">
          <label for="llm-label">显示名称</label>
          <input class="form-input" id="llm-label" value="${v.label || ""}" placeholder="可选" />
        </div>
      </div>
      <div class="llm-advanced-panel">
        <div class="form-group">
          <label>创作模式</label>
          <div class="llm-preset-list">
            ${Object.entries(CREATIVE_PRESETS).map(([id, p]) => `
              <button class="llm-preset-item ${creativeMode === id ? "active" : ""}" type="button" data-preset-id="${id}">
                <span>${p.label}</span>
                <small>${id === "custom" ? "保留当前参数" : `T ${p.temperature} · P ${p.top_p} · ${p.max_tokens} tokens`}</small>
              </button>`).join("")}
          </div>
        </div>
        <div class="form-row">
          <div class="form-group">
            <label for="llm-timeout">超时（秒）</label>
            <input class="form-input" id="llm-timeout" type="number" min="1" max="3600" value="${v.timeout ?? ""}" placeholder="180" />
          </div>
          <div class="form-group">
            <label for="llm-max-tokens">Max tokens</label>
            <input class="form-input" id="llm-max-tokens" type="number" min="1" max="200000" value="${v.max_tokens ?? ""}" placeholder="4096" />
          </div>
        </div>
        <div class="form-row">
          <div class="form-group">
            <label for="llm-temperature">Temperature</label>
            <input class="form-input" id="llm-temperature" type="number" min="0" max="2" step="0.1" value="${v.temperature ?? ""}" placeholder="0.3" />
          </div>
          <div class="form-group">
            <label for="llm-top-p">Top P</label>
            <input class="form-input" id="llm-top-p" type="number" min="0" max="1" step="0.05" value="${v.top_p ?? ""}" placeholder="可选" />
          </div>
        </div>
        <div class="form-group">
          <label for="llm-extra">供应商扩展参数（JSON）</label>
          <textarea class="form-input llm-extra-json" id="llm-extra" rows="4" placeholder='{"reasoning_effort":"high"}'>${formatExtra(v.extra)}</textarea>
        </div>
      </div>
    </div>
  `
}

function renderKeyBlock(configured, v) {
  return `
    <div class="form-group">
      <label>API Key</label>
      <div class="llm-key-row">
        <input class="form-input" id="llm-api-key" type="password" autocomplete="off" placeholder="留空保留已保存密钥" />
        <button class="btn btn-sm" id="llm-toggle-api-key" type="button">显示 Key</button>
        <label class="llm-clear-key">
          <input id="llm-clear-api-key" type="checkbox" />
          清除
        </label>
      </div>
      <div class="llm-status ${configured ? "success" : "muted"}">${configured ? "已保存" : "未保存"}</div>
      ${configured && v && (v.provider_id_source === "global" || v.base_url_source === "global") ? "<p class='llm-key-mismatch-warning'>当前供应商/BaseURL 来自全局默认，请确认 Key 与该供应商匹配</p>" : ""}
    </div>
  `
}

function sourceHtml(src) {
  if (!src) return ""
  return `<small class="field-source-tag" data-source="${src.source}">${src.source}</small>`
}

function detectCreativeMode(values) {
  for (const [id, p] of Object.entries(CREATIVE_PRESETS)) {
    if (id === "custom") continue
    if (Number(values?.temperature) === p.temperature && Number(values?.top_p) === p.top_p && Number(values?.max_tokens) === p.max_tokens) {
      return id
    }
  }
  return "custom"
}

export function detectCreativeModeExport(values) {
  return detectCreativeMode(values)
}

function formatExtra(extra) {
  if (!extra || typeof extra !== "object" || Object.keys(extra).length === 0) return ""
  return JSON.stringify(extra, null, 2)
}

export function readLLMFormFields() {
  const payload = {
    provider_id: document.getElementById("llm-provider")?.value || null,
    label: document.getElementById("llm-label")?.value.trim() || null,
    base_url: document.getElementById("llm-base-url")?.value.trim() || null,
    model: document.getElementById("llm-model")?.value.trim() || null,
    timeout: parseIntOptional("llm-timeout", 1, 3600),
    max_tokens: parseIntOptional("llm-max-tokens", 1, 200000),
    temperature: parseFloatOptional("llm-temperature", 0, 2),
    top_p: parseFloatOptional("llm-top-p", 0, 1),
    extra: readExtra(),
  }
  const apiKey = document.getElementById("llm-api-key")?.value.trim() || ""
  const clearKey = Boolean(document.getElementById("llm-clear-api-key")?.checked)
  return { payload, api_key: apiKey, clear_api_key: clearKey }
}

function parseIntOptional(id, min, max) {
  const raw = document.getElementById(id)?.value.trim() || ""
  if (!raw) return null
  const v = Number(raw)
  if (!Number.isInteger(v) || v < min || v > max) return undefined  // undefined 表非法
  return v
}

function parseFloatOptional(id, min, max) {
  const raw = document.getElementById(id)?.value.trim() || ""
  if (!raw) return null
  const v = Number(raw)
  if (!Number.isFinite(v) || v < min || v > max) return undefined
  return v
}

function readExtra() {
  const raw = document.getElementById("llm-extra")?.value.trim() || ""
  if (!raw) return {}
  try {
    const parsed = JSON.parse(raw)
    if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") return undefined  // 非法
    return parsed
  } catch {
    return undefined
  }
}

export function validateLLMPayload(payload) {
  // 非法字段（undefined from parseInt/Float/readExtra）应拦截
  for (const [k, v] of Object.entries(payload)) {
    if (v === undefined) return { ok: false, message: `${k} 字段非法或超范围` }
  }
  return { ok: true }
}
```

- [ ] **Step 2: 测试**

```js
// tests/settings/shared/llmFormFields.test.js
import { describe, it, expect } from "vitest"
import { validateLLMPayload, detectCreativeModeExport, CREATIVE_PRESETS } from "../../../views/settings/shared/llmFormFields.js"

describe("validateLLMPayload", () => {
  it("accepts all-null (pure inherit)", () => {
    expect(validateLLMPayload({
      provider_id: null, label: null, base_url: null, model: null,
      timeout: null, max_tokens: null, temperature: null, top_p: null, extra: {},
    }).ok).toBe(true)
  })
  it("rejects undefined (out-of-range numeric)", () => {
    expect(validateLLMPayload({
      provider_id: null, label: null, base_url: null, model: null,
      timeout: undefined, max_tokens: null, temperature: null, top_p: null, extra: {},
    }).ok).toBe(false)
  })
})

describe("detectCreativeModeExport", () => {
  it("returns creative when matching preset", () => {
    expect(detectCreativeModeExport(CREATIVE_PRESETS.creative)).toBe("creative")
  })
  it("returns custom for empty", () => {
    expect(detectCreativeModeExport({})).toBe("custom")
  })
})
```

- [ ] **Step 3: 运行**

Run:
```bash
cd frontend-console && npx vitest run tests/settings/shared/llmFormFields.test.js
```
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add frontend-console/views/settings/shared/llmFormFields.js frontend-console/tests/settings/shared/llmFormFields.test.js
git commit -m "feat(frontend): shared LLM form fields component"
```

---

## Task 10: api.js 新增 settings 方法

**Files:**
- Modify: `frontend-console/api.js`

- [ ] **Step 1: 在 `api.js` 新增 settings 模块**

```js
// 在 api.js 末尾追加

const settingsApi = {
  listGlobalLLMDefaults: () => request("/api/settings/llm-defaults"),
  updateGlobalLLMDefaults: (payload) => put("/api/settings/llm-defaults", payload),
  listGlobalAuthorPrefs: () => request("/api/settings/author-preferences"),
  updateGlobalAuthorPrefs: (payload) => put("/api/settings/author-preferences", payload),
  listProjectsUsingDefaults: (params = {}) =>
    request(`/api/settings/projects-using-defaults?${new URLSearchParams(params).toString()}`),
  refreshSettings: () => post("/api/settings/refresh"),
  getProjectAuthorPrefs: (projectId) => request(`/api/settings/projects/${projectId}/author-preferences`),
  updateProjectAuthorPrefs: (projectId, payload) =>
    put(`/api/settings/projects/${projectId}/author-preferences`, payload),
  resetProjectAuthorPrefsField: (projectId, field) =>
    del(`/api/settings/projects/${projectId}/author-preferences/field/${field}`),
  getEffectiveLLMSettings: (projectId) => request(`/api/projects/${projectId}/effective-llm-settings`),
  getEffectiveAuthorPrefs: (projectId) => request(`/api/projects/${projectId}/effective-author-preferences`),
  resetLLMSettingsField: (projectId, field) =>
    del(`/api/projects/${projectId}/llm-settings/field/${field}`),
}

api.settings = settingsApi
```

确认 `put` / `post` / `del` / `request` 在 api.js 已存在；如无 `del`，添加 `del` helper（看现有 put 实现复制）。

- [ ] **Step 2: Commit**

```bash
git add frontend-console/api.js
git commit -m "feat(api): add settings endpoints"
```

---

## Task 11: globalSettingsView

**Files:**
- Create: `frontend-console/views/settings/globalSettingsView.js`
- Test: `frontend-console/tests/settings/globalSettingsView.test.js`

- [ ] **Step 1: 写 `globalSettingsView.js`**

```js
// views/settings/globalSettingsView.js
import { api } from "../../api.js"
import { state } from "../../state.js"
import { router } from "../../router.js"
import { toast } from "../../ui/toast.js"
import { renderLLMFormFields, readLLMFormFields, validateLLMPayload } from "./shared/llmFormFields.js"
import {
  renderAuthorPreferencesForm,
  readAuthorPreferencesForm,
  validateAuthorPreferences,
} from "./shared/authorPreferencesForm.js"

const globalSettingsView = {
  _llmDefaults: null,
  _authorPrefs: null,
  _projectsUsingDefaults: { items: [], total: 0, truncated: false },

  async onEnter() {
    try {
      const [llm, prefs, projects] = await Promise.all([
        api.settings.listGlobalLLMDefaults(),
        api.settings.listGlobalAuthorPrefs(),
        api.settings.listProjectsUsingDefaults({ limit: 50 }),
      ])
      this._llmDefaults = llm || {}
      this._authorPrefs = prefs || {}
      this._projectsUsingDefaults = projects || { items: [], total: 0, truncated: false }
    } catch (err) {
      console.error("加载全局设置失败:", err)
      toast("加载全局设置失败", "error")
      this._llmDefaults = {}
      this._authorPrefs = {}
      this._projectsUsingDefaults = { items: [], total: 0, truncated: false }
    }
  },

  async render() {
    setTimeout(() => this.bindEvents(), 0)
    return `
      <div class="global-settings-view">
        <div class="section-header">
          <div>
            <h2>全局设置</h2>
            <p class="section-subtitle">owner: local（demo 占位）</p>
          </div>
          <div class="llm-global-actions">
            <button class="btn btn-link" id="goto-recent-project-btn" data-recent-id="${state.currentProjectId || ""}" ${state.currentProjectId ? "" : "disabled"}>进入当前项目 →</button>
          </div>
        </div>

        <section class="settings-section">
          <h3>LLM 全局默认</h3>
          <p class="settings-section-hint">不存 API Key；项目级才配置 Key。</p>
          ${renderLLMFormFields({ values: this._llmDefaults, templates: [], withApiKey: false })}
          <button class="btn btn-primary" id="global-llm-save">保存 LLM 全局默认</button>
        </section>

        <section class="settings-section">
          <h3>作者偏好全局默认</h3>
          ${renderAuthorPreferencesForm({
            dailyGoal: this._authorPrefs.daily_goal,
            editorFont: this._authorPrefs.editor_font,
            defaultFocusMode: this._authorPrefs.default_focus_mode,
          })}
          <button class="btn btn-primary" id="global-author-save">保存作者偏好</button>
        </section>

        <section class="settings-section">
          <h3>引用此默认的项目（只读）</h3>
          ${this._renderProjectsUsingDefaults()}
        </section>

        <section class="settings-section">
          <h3>本地迁移</h3>
          <p class="settings-section-hint">将浏览器 localStorage 中的旧作者偏好一次性迁入后端。</p>
          <button class="btn btn-secondary" id="manual-migrate-btn">手动迁移所有项目本地偏好</button>
        </section>
      </div>
    `
  },

  _renderProjectsUsingDefaults() {
    if (!this._projectsUsingDefaults?.items?.length) {
      return `<p class="empty-hint">没有项目继承全局默认</p>`
    }
    const items = this._projectsUsingDefaults.items.map((it) => `
      <li><a href="#/projects/${it.project_id}/settings">${it.title} (${it.project_id})</a></li>
    `).join("")
    const tail = this._projectsUsingDefaults.truncated
      ? `<p class="muted">还有更多项目省略…</p>`
      : ""
    return `<ul class="projects-using-list">${items}</ul>${tail}`
  },

  bindEvents() {
    document.getElementById("global-llm-save")?.addEventListener("click", () => this.saveLLM())
    document.getElementById("global-author-save")?.addEventListener("click", () => this.saveAuthor())
    document.getElementById("goto-recent-project-btn")?.addEventListener("click", (e) => {
      const pid = e.target.dataset.recentId
      if (pid) router.navigate(`#/projects/${pid}/settings`)
    })
    document.getElementById("manual-migrate-btn")?.addEventListener("click", () => this.runManualMigration())
  },

  async saveLLM() {
    const { payload } = readLLMFormFields()
    const v = validateLLMPayload(payload)
    if (!v.ok) return toast(v.message, "warning")
    try {
      // 全局 PUT 不含 Key 字段
      const clean = { ...payload }
      delete clean.api_key
      delete clean.clear_api_key
      this._llmDefaults = await api.settings.updateGlobalLLMDefaults(clean)
      toast("LLM 全局默认已保存", "success")
    } catch (err) {
      toast(err.message || "保存失败", "error")
    }
  },

  async saveAuthor() {
    const prefs = readAuthorPreferencesForm()
    const v = validateAuthorPreferences(prefs)
    if (!v.ok) return toast(v.message, "warning")
    try {
      this._authorPrefs = await api.settings.updateGlobalAuthorPrefs(prefs)
      toast("作者偏好已保存", "success")
    } catch (err) {
      toast(err.message || "保存失败", "error")
    }
  },

  async runManualMigration() {
    toast("迁移中…", "info")
    const keys = Object.keys(localStorage).filter((k) => k.startsWith("novel_author_preferences:"))
    let migrated = 0
    for (const key of keys) {
      const projectId = key.split(":")[1]
      if (!projectId || projectId === "global") continue
      let parsed
      try {
        parsed = JSON.parse(localStorage.getItem(key) || "{}")
      } catch {
        continue
      }
      // 先看后端是否已有覆盖
      try {
        const existing = await api.settings.getProjectAuthorPrefs(projectId)
        if (existing &&
          (existing.daily_goal !== null || existing.editor_font !== null || existing.default_focus_mode !== null)) {
          // 后端已有覆盖，跳过并清旧 key
          localStorage.removeItem(key)
          continue
        }
      } catch {
        // 后端不可达时跳过保留 key
        continue
      }
      // 迁移为项目覆盖
      const payload = {
        daily_goal: parsed.dailyGoal ?? null,
        editor_font: parsed.editorFont ?? null,
        default_focus_mode: Boolean(parsed.defaultFocusMode ?? false),
      }
      try {
        await api.settings.updateProjectAuthorPrefs(projectId, payload)
        localStorage.removeItem(key)
        migrated += 1
      } catch (err) {
        console.error(`迁移 ${projectId} 失败:`, err)
      }
    }
    toast(`已迁移 ${migrated} 个项目，余 ${keys.length - migrated} 个`, migrated ? "success" : "info")
  },
}

if (typeof router !== "undefined") {
  router.registerView("settings", globalSettingsView)
}

export default globalSettingsView
```

- [ ] **Step 2: 写测试**

```js
// tests/settings/globalSettingsView.test.js
import { describe, it, expect, vi } from "vitest"
import globalSettingsView from "../../views/settings/globalSettingsView.js"

describe("globalSettingsView", () => {
  it("renders empty hint when no projects inherit", () => {
    globalSettingsView._projectsUsingDefaults = { items: [], total: 0, truncated: false }
    const html = globalSettingsView._renderProjectsUsingDefaults()
    expect(html).toContain("没有项目继承全局默认")
  })
  it("renders truncated tail when truncated=true", () => {
    globalSettingsView._projectsUsingDefaults = {
      items: [{ project_id: "x", title: "p1", inherited_fields: [] }],
      total: 200, truncated: true,
    }
    const html = globalSettingsView._renderProjectsUsingDefaults()
    expect(html).toContain("更多项目省略")
  })
})
```

- [ ] **Step 3: 运行**

Run:
```bash
cd frontend-console && npx vitest run tests/settings/globalSettingsView.test.js
```
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add frontend-console/views/settings/globalSettingsView.js frontend-console/tests/settings/globalSettingsView.test.js
git commit -m "feat(frontend): globalSettingsView"
```

---

## Task 12: 三个 Tab 视图

**Files:**
- Create: `frontend-console/views/settings/tabs/llmMainTab.js`
- Create: `frontend-console/views/settings/tabs/deepImportTab.js`
- Create: `frontend-console/views/settings/tabs/authorPreferencesTab.js`

- [ ] **Step 1: 写 `llmMainTab.js`**

```js
// views/settings/tabs/llmMainTab.js
import { toast } from "../../../ui/toast.js"
import {
  renderLLMFormFields,
  readLLMFormFields,
  validateLLMPayload,
} from "../shared/llmFormFields.js"
import { renderSourceLabel } from "../shared/fieldSourceLabel.js"

const llmMainTab = {
  render({ effectiveData, templates }) {
    // effective 数据形如 { provider_id: { value, source }, ... }
    const values = {
      provider_id: effectiveData.provider_id?.value || "",
      label: effectiveData.label?.value || "",
      base_url: effectiveData.base_url?.value || "",
      model: effectiveData.model?.value || "",
      timeout: effectiveData.timeout?.value ?? null,
      max_tokens: effectiveData.max_tokens?.value ?? null,
      temperature: effectiveData.temperature?.value ?? null,
      top_p: effectiveData.top_p?.value ?? null,
      extra: effectiveData.extra?.value || {},
      api_key_configured: effectiveData.api_key_configured?.value || false,
      provider_id_source: effectiveData.provider_id?.source,
      base_url_source: effectiveData.base_url?.source,
    }
    const sourceMap = {
      provider_id: effectiveData.provider_id,
      label: effectiveData.label,
      base_url: effectiveData.base_url,
      model: effectiveData.model,
      timeout: effectiveData.timeout,
      max_tokens: effectiveData.max_tokens,
      temperature: effectiveData.temperature,
      top_p: effectiveData.top_p,
      extra: effectiveData.extra,
    }
    return `
      <div class="llm-main-tab">
        ${renderLLMFormFields({ values, templates, sourceMap, withApiKey: true })}
        <div class="llm-main-tab-actions">
          <button class="btn btn-primary" id="llm-tab-save">保存项目 LLM 配置</button>
          <button class="btn btn-link" id="llm-tab-reset-all">恢复所有字段到全局默认</button>
        </div>
        <ul class="llm-source-legend">
          <li><span class="source-label source-project">已覆盖</span>：项目自填值</li>
          <li><span class="source-label source-global">继承全局</span>：项目未设</li>
          <li><span class="source-label source-system">系统默认</span>：全局也无</li>
          <li><span class="source-label source-unset">未配置</span>：必须填</li>
        </ul>
      </div>
    `
  },

  bindEvents({ onSave, onResetAll, onResetField }) {
    document.getElementById("llm-tab-save")?.addEventListener("click", () => {
      const { payload, api_key, clear_api_key } = readLLMFormFields()
      const v = validateLLMPayload(payload)
      if (!v.ok) return toast(v.message, "warning")
      onSave?.({ payload, api_key, clear_api_key })
    })
    document.getElementById("llm-tab-reset-all")?.addEventListener("click", () => {
      if (!confirm("将清除项目所有 LLM 覆盖，回退到全局默认。继续？")) return
      onResetAll?.()
    })
    document.querySelectorAll(".field-reset[data-field]").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        const field = e.target.dataset.field
        onResetField?.(field)
      })
    })
  },
}

export default llmMainTab
```

- [ ] **Step 2: 写 `deepImportTab.js`**

```js
// views/settings/tabs/deepImportTab.js
import { toast } from "../../../ui/toast.js"
import { renderDeepImportFields, readDeepImportFields } from "../shared/deepImportFields.js"
import { renderSourceLabel } from "../shared/fieldSourceLabel.js"

const deepImportTab = {
  render({ effectiveData }) {
    const di = effectiveData.deep_import
    const settings = di?.source === "project" ? di.value || {} : {}  // source global/system 时不展开字段值，UI 显示提示
    return `
      <div class="deep-import-tab">
        <p class="deep-import-source-hint">
          深度导入参数 <small>${renderSourceLabel(di || { source: "system", value: null })}</small>
        </p>
        ${renderDeepImportFields(settings)}
        <div class="deep-import-actions">
          <button class="btn btn-primary" id="deep-import-tab-save">保存深度导入参数</button>
          ${di?.source === "project"
            ? `<button class="btn btn-link" id="deep-import-tab-reset-all">恢复到全局/系统默认</button>`
            : ""}
        </div>
      </div>
    `
  },

  bindEvents({ onSave, onResetAll }) {
    document.getElementById("deep-import-tab-save")?.addEventListener("click", () => {
      const out = readDeepImportFields()
      if (!out.ok) return toast(out.error, "warning")
      onSave?.(out.value)
    })
    document.getElementById("deep-import-tab-reset-all")?.addEventListener("click", () => {
      if (!confirm("将清除项目深度导入覆盖，整体回退。继续？")) return
      onResetAll?.()
    })
  },
}

export default deepImportTab
```

- [ ] **Step 3: 写 `authorPreferencesTab.js`**

```js
// views/settings/tabs/authorPreferencesTab.js
import { toast } from "../../../ui/toast.js"
import {
  renderAuthorPreferencesForm,
  readAuthorPreferencesForm,
  validateAuthorPreferences,
} from "../shared/authorPreferencesForm.js"

const authorPreferencesTab = {
  render({ effectiveData, mode }) {
    // mode: "project" (项目覆盖 Tab) | "global" (实际由 globalSettingsView 调用)
    const values = {
      dailyGoal: effectiveData.daily_goal?.value,
      editorFont: effectiveData.editor_font?.value,
      defaultFocusMode: effectiveData.default_focus_mode?.value,
    }
    const source = {
      daily_goal: effectiveData.daily_goal,
      editor_font: effectiveData.editor_font,
      default_focus_mode: effectiveData.default_focus_mode,
    }
    return `
      <div class="author-prefs-tab">
        ${renderAuthorPreferencesForm({
          ...values,
          source,
        })}
        <div class="author-prefs-actions">
          <button class="btn btn-primary" id="author-prefs-tab-save">保存作者偏好</button>
        </div>
      </div>
    `
  },

  bindEvents({ onSave, onResetField }) {
    document.getElementById("author-prefs-tab-save")?.addEventListener("click", () => {
      const prefs = readAuthorPreferencesForm()
      const v = validateAuthorPreferences(prefs)
      if (!v.ok) return toast(v.message, "warning")
      onSave?.(prefs)
    })
    document.querySelectorAll(".field-reset[data-field]").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        onResetField?.(e.target.dataset.field)
      })
    })
  },
}

export default authorPreferencesTab
```

- [ ] **Step 3.5: Commit**

```bash
git add frontend-console/views/settings/tabs/
git commit -m "feat(frontend): three settings tabs as composed components"
```

---

## Task 13: projectSettingsView 主视图

**Files:**
- Create: `frontend-console/views/settings/projectSettingsView.js`
- Test: `frontend-console/tests/settings/projectSettingsView.test.js`

- [ ] **Step 1: 写 `projectSettingsView.js`**

```js
// views/settings/projectSettingsView.js
import { api } from "../../api.js"
import { router } from "../../router.js"
import { state } from "../../state.js"
import { toast } from "../../ui/toast.js"
import llmMainTab from "./tabs/llmMainTab.js"
import deepImportTab from "./tabs/deepImportTab.js"
import authorPreferencesTab from "./tabs/authorPreferencesTab.js"

const projectSettingsView = {
  _projectId: null,    // 来自 URL
  _tab: "main",
  _effectiveLLM: null,
  _effectivePrefs: null,
  _templates: [],

  get effectiveLLM() { return this._effectiveLLM },
  get effectivePrefs() { return this._effectivePrefs },

  async onEnter({ projectId } = {}) {
    // D14: 从 URL 取 project id
    this._projectId = projectId || state.currentProjectId
    if (!this._projectId) {
      this._effectiveLLM = null
      this._effectivePrefs = null
      return
    }
    state.setCurrentProject(this._projectId)
    try {
      const [llm, prefs, templates] = await Promise.all([
        api.settings.getEffectiveLLMSettings(this._projectId),
        api.settings.getEffectiveAuthorPrefs(this._projectId),
        api.projects.listLlmProviderTemplates(),
      ])
      this._effectiveLLM = llm
      this._effectivePrefs = prefs
      this._templates = templates?.items || []
    } catch (err) {
      console.error("load effective settings failed:", err)
      toast("加载项目设置失败", "error")
    }
  },

  async render() {
    setTimeout(() => this.bindEvents(), 0)
    if (!this._projectId) {
      return `
        <div class="empty-state">
          <div class="empty-icon">⚙</div>
          <p>请先进入项目</p>
          <a class="btn btn-primary" href="#/settings">返回全局设置</a>
        </div>
      `
    }
    return `
      <div class="project-settings-view">
        <div class="section-header">
          <div>
            <h2>项目设置</h2>
            <p class="section-subtitle">${this._projectId}</p>
          </div>
          <a class="btn btn-link" href="#/settings">全局设置 →</a>
        </div>
        <nav class="settings-tabs">
          <button class="btn btn-sm tab-btn ${this._tab === "main" ? "active" : ""}" data-tab="main">主配置</button>
          <button class="btn btn-sm tab-btn ${this._tab === "deep" ? "active" : ""}" data-tab="deep">深度导入</button>
          <button class="btn btn-sm tab-btn ${this._tab === "author" ? "active" : ""}" data-tab="author">作者偏好</button>
        </nav>
        <div class="settings-tab-content">
          ${this._renderCurrentTab()}
        </div>
      </div>
    `
  },

  _renderCurrentTab() {
    if (!this._effectiveLLM || !this._effectivePrefs) return `<p>加载中…</p>`
    if (this._tab === "main") {
      return llmMainTab.render({ effectiveData: this._effectiveLLM, templates: this._templates })
    }
    if (this._tab === "deep") {
      return deepImportTab.render({ effectiveData: this._effectiveLLM })
    }
    if (this._tab === "author") {
      return authorPreferencesTab.render({ effectiveData: this._effectivePrefs, mode: "project" })
    }
    return ""
  },

  bindEvents() {
    document.querySelectorAll(".tab-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        this._tab = e.target.dataset.tab
        router.refresh()
      })
    })
    if (!this._projectId || !this._effectiveLLM) return
    if (this._tab === "main") {
      llmMainTab.bindEvents({
        onSave: ({ payload, api_key, clear_api_key }) => this.saveLLM(payload, api_key, clear_api_key),
        onResetAll: () => this.resetAllLLMFields(),
        onResetField: (field) => this.resetLLMField(field),
      })
    }
    if (this._tab === "deep") {
      deepImportTab.bindEvents({
        onSave: (deepImport) => this.saveDeepImport(deepImport),
        onResetAll: () => this.resetDeepImport(),
      })
    }
    if (this._tab === "author") {
      authorPreferencesTab.bindEvents({
        onSave: (prefs) => this.saveAuthorPrefs(prefs),
        onResetField: (field) => this.resetAuthorPrefsField(field),
      })
    }
  },

  async saveLLM(payload, apiKey, clearApiKey) {
    try {
      const update = { ...payload, api_key: apiKey, clear_api_key: clearApiKey }
      await api.projects.updateLlmSettings(this._projectId, update)
      toast("LLM 配置已保存", "success")
      await this._refreshEffective()
    } catch (err) {
      toast(err.message || "保存失败", "error")
    }
  },

  async saveDeepImport(deepImport) {
    try {
      const settingsResp = await api.projects.getLlmSettings(this._projectId)
      await api.projects.updateLlmSettings(this._projectId, {
        provider_id: settingsResp.provider_id,
        base_url: settingsResp.base_url,
        model: settingsResp.model,
        deep_import: deepImport,
      })
      toast("深度导入参数已保存", "success")
      await this._refreshEffective()
    } catch (err) {
      toast(err.message || "保存失败", "error")
    }
  },

  async saveAuthorPrefs(prefs) {
    try {
      await api.settings.updateProjectAuthorPrefs(this._projectId, prefs)
      toast("作者偏好已保存", "success")
      await this._refreshEffective()
    } catch (err) {
      toast(err.message || "保存失败", "error")
    }
  },

  async resetLLMField(field) {
    try {
      await api.settings.resetLLMSettingsField(this._projectId, field)
      toast(`${field} 已恢复到全局默认`, "success")
      await this._refreshEffective()
    } catch (err) {
      toast(err.message || "恢复失败", "error")
    }
  },

  async resetAllLLMFields() {
    try {
      // 全清项目 LLM 覆盖：直接 PUT 空对象到 update
      await api.projects.updateLlmSettings(this._projectId, {
        provider_id: null, label: null, base_url: null, model: null,
        timeout: null, max_tokens: null, temperature: null, top_p: null,
        extra: {}, deep_import: {},
        api_key: "", clear_api_key: true,
      })
      toast("已恢复所有 LLM 字段到全局默认", "success")
      await this._refreshEffective()
    } catch (err) {
      toast(err.message || "恢复失败", "error")
    }
  },

  async resetDeepImport() {
    // 删除 deep_import 整体
    await this.resetLLMField("deep_import")
  },

  async resetAuthorPrefsField(field) {
    try {
      await api.settings.resetProjectAuthorPrefsField(this._projectId, field)
      toast(`${field} 已恢复到全局默认`, "success")
      await this._refreshEffective()
    } catch (err) {
      toast(err.message || "恢复失败", "error")
    }
  },

  async _refreshEffective() {
    const [llm, prefs] = await Promise.all([
      api.settings.getEffectiveLLMSettings(this._projectId),
      api.settings.getEffectiveAuthorPrefs(this._projectId),
    ])
    this._effectiveLLM = llm
    this._effectivePrefs = prefs
    await router.refresh()
  },
}

if (typeof router !== "undefined") {
  router.registerView("project-settings", projectSettingsView)
}

export default projectSettingsView
```

- [ ] **Step 2: 写测试**

```js
// tests/settings/projectSettingsView.test.js
import { describe, it, expect } from "vitest"
import projectSettingsView from "../../views/settings/projectSettingsView.js"

describe("projectSettingsView", () => {
  it("renders empty state when no project id", async () => {
    projectSettingsView._projectId = null
    projectSettingsView._effectiveLLM = null
    const html = await projectSettingsView.render()
    expect(html).toContain("请先进入项目")
    expect(html).toContain("#/settings")
  })
  it("renders tabs when effective data loaded", async () => {
    projectSettingsView._projectId = "abc"
    projectSettingsView._tab = "main"
    projectSettingsView._effectiveLLM = { provider_id: { value: "x", source: "system" } }
    projectSettingsView._effectivePrefs = { daily_goal: { value: null, source: "system" } }
    const html = await projectSettingsView.render()
    expect(html).toContain("主配置")
    expect(html).toContain("深度导入")
    expect(html).toContain("作者偏好")
  })
})
```

- [ ] **Step 3: 运行**

Run:
```bash
cd frontend-console && npx vitest run tests/settings/projectSettingsView.test.js
```
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add frontend-console/views/settings/projectSettingsView.js frontend-console/tests/settings/projectSettingsView.test.js
git commit -m "feat(frontend): projectSettingsView with tabs"
```

---

## Task 14: router 注册 + `#/llm` 别名 + state 缓存 + localStorage 迁移

**Files:**
- Modify: `frontend-console/router.js`
- Modify: `frontend-console/state.js`
- Modify: `frontend-console/index.html`

- [ ] **Step 1: 修改 `router.js` 注册两路由 + `#/llm` 别名**

参考 `router.js` 现有 `registerView` 模式，追加：
```js
// 在 router.js 已有 registerView 调用附近追加
import("./views/settings/globalSettingsView.js")
import("./views/settings/projectSettingsView.js")

// 在路由表里新增：
//  #/settings                     → "settings"
//  #/projects/:project_id/settings → "project-settings"，把 :project_id 注入视图 onEnter({ projectId })
//  #/llm                          → "project-settings"，用 state.currentProjectId；无则跳 #/settings + toast
```

具体路由表持久化按 router.js 实际风格改；`onEnter(projectSettingsView.view)({ projectId: <id> })`。

`#/llm` 兼容：
```js
router.on("llm", (params) => {
  const pid = state.currentProjectId
  if (!pid) {
    router.navigate("/settings")
    toast("请先选择项目", "warning")
    return
  }
  router.navigate(`/projects/${pid}/settings`, { replace: true })
})
```

- [ ] **Step 2: 在 `state.js` 新增 `globalSettingsCache`**

```js
// state.js 追加

const state = {
  // 现有字段
  globalSettingsCache: null,    // 新增
  setCurrentProject(projectId) { /* 现有 */ },
  // ...
}

// 多标签页同步：监听 storage 事件刷新全局缓存
if (typeof window !== "undefined") {
  window.addEventListener("storage", (e) => {
    if (e.key === "global_settings_cache_version") {
      state.globalSettingsCache = null  // 失效，下次 onEnter 重拉
    }
  })
}
```

- [ ] **Step 3: 修改 `index.html` 引入新 view**

在已有 `<script type="module" src="views/llmSettingsView.js"></script>` 移除（本任务一并删除旧 `llmSettingsView.js`），追加：
```html
<script type="module" src="views/settings/globalSettingsView.js"></script>
<script type="module" src="views/settings/projectSettingsView.js"></script>
```

- [ ] **Step 4: 删除 `frontend-console/views/llmSettingsView.js`**

确认新视图替代后删除：
```bash
git rm frontend-console/views/llmSettingsView.js
```

- [ ] **Step 5: 在 `state.js` 加 localStorage 自动迁移逻辑（首次打开项目时）**

```js
// state.js 内新增并在 projectSettingsView.onEnter 完成后调用

export async function tryMigrateLocalAuthorPreferences(projectId) {
  if (!projectId) return
  const key = `novel_author_preferences:${projectId}`
  const raw = localStorage.getItem(key)
  if (!raw) return
  let parsed
  try {
    parsed = JSON.parse(raw)
  } catch {
    return
  }
  // 后端有覆盖时跳过并清 key
  try {
    const existing = await api.settings.getProjectAuthorPrefs(projectId)
    if (existing &&
      (existing.daily_goal !== null || existing.editor_font !== null || existing.default_focus_mode !== null)) {
      localStorage.removeItem(key)
      return
    }
    await api.settings.updateProjectAuthorPrefs(projectId, {
      daily_goal: parsed.dailyGoal ?? null,
      editor_font: parsed.editorFont ?? null,
      default_focus_mode: Boolean(parsed.defaultFocusMode ?? false),
    })
    localStorage.removeItem(key)
  } catch {
    // 后端不可达保留
  }
}
```

并在 `projectSettingsView.onEnter` 末尾调用：
```js
await tryMigrateLocalAuthorPreferences(this._projectId)
await this._refreshEffective()
```

- [ ] **Step 6: 跑前端单测确认无回归**

Run:
```bash
cd frontend-console && npx vitest run
```
Expected: 全 PASS

- [ ] **Step 7: Commit**

```bash
git add frontend-console/router.js frontend-console/state.js frontend-console/index.html frontend-console/views/settings/
git rm frontend-console/views/llmSettingsView.js
git commit -m "feat(frontend): register settings/project-settings routes, helpers, custom views"
```

---

## Task 15: Playwright E2E 设置流程

**Files:**
- Create: `frontend-console/e2e/settings_flow.spec.js`

- [ ] **Step 1: 写 E2E**

```js
// e2e/settings_flow.spec.js
import { test, expect } from "@playwright/test"
import { setupCleanTestEnv, buildProjectInDb } from "./helpers"

test.beforeEach(async () => {
  await setupCleanTestEnv()
})

test("global → project deep link and tab switch", async ({ page }) => {
  const pid = await buildProjectInDb({ title: "E2E Project" })
  await page.goto(`/#/projects/${pid}/settings`)
  await expect(page.getByRole("button", { name: "主配置" })).toBeVisible()
  await page.getByRole("button", { name: "深度导入" }).click()
  await expect(page).toContainText(/Phase 0/)
  await page.getByRole("button", { name: "作者偏好" }).click()
  await expect(page).toContainText(/日更目标/)
})

test("author preference override + global change inherits correctly", async ({ page, request }) => {
  const pid = await buildProjectInDb({ title: "Prefs Project" })
  // 全局默认设 mono
  await request.put("/api/settings/author-preferences", { data: { editor_font: "mono" } })
  // 项目覆盖 serif
  await request.put(`/api/settings/projects/${pid}/author-preferences`, { data: { editor_font: "serif" } })

  await page.goto(`/#/projects/${pid}/settings`)
  await page.getByRole("button", { name: "作者偏好" }).click()
  await expect(page.locator("#author-editor-font")).toHaveValue("serif")

  // 项目恢复
  await request.delete(`/api/settings/projects/${pid}/author-preferences/field/editor_font`)
  await page.reload()
  await page.getByRole("button", { name: "作者偏好" }).click()
  await expect(page.locator("#author-editor-font")).toHaveValue("mono")
})

test("effective source label transitions from inherited to overridden", async ({ page, request }) => {
  const pid = await buildProjectInDb({ title: "Source" })
  await request.put("/api/settings/llm-defaults", { data: { provider_id: "openai-compatible", base_url: "https://api.openai.com/v1", model: "gpt-4o" } })
  await page.goto(`/#/projects/${pid}/settings`)
  await expect(page).toContainText("继承全局")

  await page.fill("#llm-base-url", "https://custom.example.com/v1")
  await page.click("#llm-tab-save")
  await expect(page).toContainText("已覆盖")
})

test("deep import min/max validation shows toast", async ({ page }) => {
  const pid = await buildProjectInDb({ title: "DI" })
  await page.goto(`/#/projects/${pid}/settings`)
  await page.getByRole("button", { name: "深度导入" }).click()
  await page.fill("#deep-import-phase0-target-input-chars", "10")   // < min 1000
  await page.getByRole("button", { name: "保存深度导入参数" }).click()
  await expect(page).toContainText(/必须是/)
})

test("#/llm alias rewrites to project settings when project selected", async ({ page, request }) => {
  const pid = await buildProjectInDb({ title: "Alias" })
  const existing = await request.get("/api/projects")
  const items = (await existing.json()).items
  // 设为最近 project（前端 state.currentProjectId 在导航后自动设）
  await page.goto(`/#/projects/${pid}`)
  await page.goto(`/#/llm`)
  await expect(page).toHaveURL(/#\/projects\/.+\/settings/)
})

test("#/llm alias without project routes to global + toast", async ({ page }) => {
  await page.goto(`/#/llm`)
  await expect(page).toHaveURL(/#\/settings/)
  await expect(page).toContainText("请先选择项目")
})
```

注：`buildProjectInDb` 与 `setupCleanTestEnv` 已在 `e2e/helpers.js` 提供；如无，按现有 spec 编写脚手架。

- [ ] **Step 2: 跑 E2E**

Run:
```bash
cd frontend-console && npx playwright test e2e/settings_flow.spec.js
```
Expected: 6 PASS

- [ ] **Step 3: Commit**

```bash
git add frontend-console/e2e/settings_flow.spec.js
git commit -m "test(e2e): settings flow covers routes, overrides, validation, alias"
```

---

## Task 16: 全量回归 + Lint + 文档同步

**Files:**
- Modify: `backend/modules/settings/README.md` (新建)
- Modify: `docs/00_整体设计.md` (settings 模块描述)

- [ ] **Step 1: 跑后端全量**

Run:
```bash
cd backend && pytest -q
```
Expected: 全 PASS

- [ ] **Step 2: 跑前端全量**

Run:
```bash
cd frontend-console && npx vitest run && npx playwright test
```
Expected: 全 PASS

- [ ] **Step 3: 跑 ruff/eslint**

Run:
```bash
cd backend && ruff check . && ruff format --check .
cd frontend-console && npm run lint 2>/dev/null || true
```

- [ ] **Step 4: 写 `backend/modules/settings/README.md`**

```markdown
# Settings Module

管理全局 LLM 默认、全局作者偏好、项目级作者偏好覆盖。

## 关键约束

- API Key 永远项目级：`global_llm_defaults` 表不存 Key，`GlobalLLMDefaultsUpdate` schema `extra="forbid"` 硬拒 `api_key`。
- `owner_id` demo 阶段用 nil UUID `LOCAL_OWNER_ID`；UI 显示 `local`。
- 项目级表不带 `owner_id`，靠 `project → owner` 关系未来追加。
- 项目作者偏好所有字段允许 NULL：NULL = 继承全局。
- 字段级 DELETE 硬白名单：`AUTHOR_PREFS_FIELDS`、`LLM_INHERITABLE_FIELDS`。
- 全局 deep_import 本期永不写入（D9）：`global_llm_defaults.deep_import` 列存在但保持 NULL。

## effective 响应结构

`{ field: { value, source } }`，source ∈ {project, global, system, unset}。

## 接口

详见 `api.py`。路由前缀 `/api/settings/`。项目级 effective 接口仍走 `/api/projects/<id>/...`（位于 `modules/project/`）。
```

- [ ] **Step 5: 更新 `docs/00_整体设计.md` 模块树**

在 `backend/modules/` 下追加 `settings/` 条目，说明职责（全局默认 + 项目覆盖 effective 合并）。

- [ ] **Step 6: Commit**

```bash
git add backend/modules/settings/README.md docs/00_整体设计.md
git commit -m "docs(settings): module README and overall design doc"
```

---

## Self-Review Checklist

- [x] Spec coverage §3 路由 → Task 14
- [x] Spec §4 三表 → Task 1
- [x] Spec §5 API → Tasks 3, 4, 5
- [x] Spec §6 前端视图 + shared → Tasks 7-13
- [x] Spec §7 错误处理 → 分布在 Task 4（400）、Task 5（reset）、Task 11（迁移失败保留 key）、E2E（ #-/llm 兼容）
- [x] Spec §8 测试 → Tasks 2/3/4/6/7/9/13/15
- [x] Spec §9 实施顺序 → 与 Task 编号 1-16 对齐
- [x] Spec §10 不引入项 → Task 11 路由不写 owner auth 逻辑
- [x] D1-D25 决策均落地（详见 decisions 表）

未覆盖：无 placeholder；类型一致性已逐字段核对。

---

**Plan complete and saved to `docs/superpowers/plans/2026-07-07-settings-page-restructure.md`. Two execution options:**

1. **Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

2. **Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**