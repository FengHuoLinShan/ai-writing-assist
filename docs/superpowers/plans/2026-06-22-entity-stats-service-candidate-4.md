# EntityStatsService 提取 — 候选 4 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `backend/modules/world/entity_facade.py` 中剩余的 `count_entities` 与 `list_auto_ingested_entities` 提取到 `EntityStatsService`，使 facade 不再直接写 SQL/ORM 查询。

**Architecture:** 新建 `EntityStatsService` 统一负责实体统计与自动入库实体查询；`CoreEntityRepository` 新增聚合计数方法；`entity_facade.py` 改为委托；新增独立单元测试；同步更新模块导出与 README。

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2.0 async, Pydantic v2, pytest-asyncio.

---

## File Structure

| 文件 | 动作 | 说明 |
|------|------|------|
| `backend/modules/world/services/entity_stats_service.py` | 新建 | 实体统计与自动入库查询服务 |
| `backend/modules/world/repositories.py` | 修改 | `CoreEntityRepository` 新增 `count_entities` |
| `backend/modules/world/entity_facade.py` | 修改 | `count_entities` / `list_auto_ingested_entities` 委托给新服务 |
| `backend/modules/world/services/__init__.py` | 修改 | 导出 `EntityStatsService` |
| `backend/modules/world/tests/test_entity_stats_service.py` | 新建 | 服务单元测试 |
| `backend/modules/world/tests/test_repository.py` 或现有测试 | 修改 | `count_entities` repository 集成测试 |
| `backend/modules/world/README.md` | 修改 | 职责列表加入新服务 |

---

### Task 1: Add `CoreEntityRepository.count_entities`

**Files:**
- Modify: `backend/modules/world/repositories.py`
- Test: `backend/modules/world/tests/test_entity_stats_service.py`（repository 部分）

- [ ] **Step 1: Write the failing test for repository count**

```python
"""EntityStatsService / CoreEntityRepository 测试。"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.project.models import Project
from modules.world.repositories import CoreEntityRepository


@pytest.fixture
def repo() -> CoreEntityRepository:
    return CoreEntityRepository()


@pytest.mark.asyncio
async def test_repo_count_entities(db_session: AsyncSession, repo: CoreEntityRepository) -> None:
    novel_id = str(uuid.uuid4())
    db_session.add(
        Project(
            id=uuid.UUID(novel_id),
            title="t",
            genre="fantasy",
            language="zh",
            target_length="novel",
            current_stage="worldbuilding",
        )
    )

    await repo.create_raw(
        db_session,
        novel_id=uuid.UUID(novel_id),
        entity_type="character",
        name="A",
        status="canonical",
    )
    await repo.create_raw(
        db_session,
        novel_id=uuid.UUID(novel_id),
        entity_type="location",
        name="B",
        status="draft",
    )
    await repo.create_raw(
        db_session,
        novel_id=uuid.UUID(novel_id),
        entity_type="item",
        name="C",
        status="deprecated",
    )

    total = await repo.count_entities(db_session, uuid.UUID(novel_id))
    assert total == 3

    canonical_only = await repo.count_entities(
        db_session,
        uuid.UUID(novel_id),
        status_filter=["canonical"],
    )
    assert canonical_only == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest modules/world/tests/test_entity_stats_service.py::test_repo_count_entities -v
```

Expected: `FAIL` with `AttributeError: 'CoreEntityRepository' object has no attribute 'count_entities'`

- [ ] **Step 3: Add `count_entities` to `CoreEntityRepository`**

在 `backend/modules/world/repositories.py` 的 `CoreEntityRepository` 中，紧随 `delete` 方法之后添加：

```python
    async def count_entities(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        status_filter: list[str] | None = None,
    ) -> int:
        """统计指定 novel 的 CoreEntity 数量。"""
        conditions = [CoreEntity.novel_id == novel_id]
        if status_filter:
            conditions.append(CoreEntity.status.in_(status_filter))
        stmt = select(func.count(CoreEntity.id)).where(*conditions)
        result = await db.execute(stmt)
        return result.scalar() or 0
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && python -m pytest modules/world/tests/test_entity_stats_service.py::test_repo_count_entities -v
```

Expected: `PASS`

- [ ] **Step 5: Commit**

```bash
git add backend/modules/world/repositories.py \
        backend/modules/world/tests/test_entity_stats_service.py
git commit -m "feat(world): add CoreEntityRepository.count_entities"
```

---

### Task 2: Create `EntityStatsService`

**Files:**
- Create: `backend/modules/world/services/entity_stats_service.py`
- Test: `backend/modules/world/tests/test_entity_stats_service.py`

- [ ] **Step 1: Write the failing test for `count_entities` delegation**

在 `backend/modules/world/tests/test_entity_stats_service.py` 中追加：

```python
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.world.services.entity_stats_service import EntityStatsService


@pytest.fixture
def stats_service() -> EntityStatsService:
    return EntityStatsService()


@pytest.mark.asyncio
async def test_stats_count_entities_delegates_to_repo(
    stats_service: EntityStatsService,
) -> None:
    db = MagicMock()
    novel_id = str(uuid.uuid4())
    with patch.object(stats_service, "_repo", new_callable=MagicMock) as mock_repo:
        mock_repo.count_entities = AsyncMock(return_value=7)

        result = await stats_service.count_entities(
            db, novel_id, status_filter=["canonical"]
        )

        assert result == 7
        mock_repo.count_entities.assert_awaited_once_with(
            db,
            uuid.UUID(novel_id),
            status_filter=["canonical"],
        )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest modules/world/tests/test_entity_stats_service.py::test_stats_count_entities_delegates_to_repo -v
```

Expected: `FAIL` with `ModuleNotFoundError: No module named 'modules.world.services.entity_stats_service'`

- [ ] **Step 3: Create `EntityStatsService`**

创建 `backend/modules/world/services/entity_stats_service.py`：

```python
"""EntityStatsService — 实体统计与自动入库查询服务。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.repositories import CoreEntityRepository
from modules.world.services.helpers import parse_uuid


class EntityStatsService:
    """提供实体数量统计与自动入库实体查询。

    从 entity_facade.py 提取，避免 facade 直接写 SQL/ORM。
    """

    def __init__(self, repo: CoreEntityRepository | None = None) -> None:
        self._repo = repo or CoreEntityRepository()

    async def count_entities(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        status_filter: list[str] | None = None,
    ) -> int:
        """统计 novel 的 CoreEntity 数量。"""
        nid = parse_uuid(novel_id, "novel_id")
        return await self._repo.count_entities(
            db,
            nid,
            status_filter=status_filter,
        )

    async def list_auto_ingested_entities(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        start_chapter: int | None = None,
        end_chapter: int | None = None,
        limit: int = 10000,
    ) -> list[dict[str, Any]]:
        """列出自动入库生成的实体，可选按来源章节范围过滤。"""
        nid = parse_uuid(novel_id, "novel_id")
        entities, _ = await self._repo.get_by_novel(db, nid, limit=limit)

        items: list[dict[str, Any]] = []
        for entity in entities:
            if entity.status not in ("canonical", "draft"):
                continue
            content_json = entity.content_json or {}
            meta = content_json.get("_meta") or {}
            if not meta.get("auto_ingested"):
                continue
            source = meta.get("source_chapter_index")
            if start_chapter is not None and end_chapter is not None:
                if source is None or not (start_chapter <= int(source) <= end_chapter):
                    continue
            items.append(
                {
                    "id": str(entity.id),
                    "name": entity.name,
                    "status": entity.status,
                    "content_json": content_json,
                }
            )
        return items
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && python -m pytest modules/world/tests/test_entity_stats_service.py::test_stats_count_entities_delegates_to_repo -v
```

Expected: `PASS`

- [ ] **Step 5: Add tests for `list_auto_ingested_entities`**

在 `backend/modules/world/tests/test_entity_stats_service.py` 中追加：

```python
def _mock_entity(**overrides: Any) -> MagicMock:
    defaults = {
        "id": uuid.uuid4(),
        "novel_id": uuid.uuid4(),
        "name": "Entity",
        "status": "canonical",
        "content_json": {},
    }
    defaults.update(overrides)
    entity = MagicMock()
    for key, value in defaults.items():
        setattr(entity, key, value)
    return entity


@pytest.mark.asyncio
async def test_list_auto_ingested_filters_by_meta_and_status(
    stats_service: EntityStatsService,
) -> None:
    db = MagicMock()
    novel_id = str(uuid.uuid4())
    auto = _mock_entity(
        name="Auto",
        content_json={"_meta": {"auto_ingested": True, "source_chapter_index": 5}},
    )
    manual = _mock_entity(
        name="Manual",
        content_json={"_meta": {"auto_ingested": False}},
    )
    deprecated = _mock_entity(
        name="Deprecated",
        status="deprecated",
        content_json={"_meta": {"auto_ingested": True}},
    )

    with patch.object(stats_service, "_repo", new_callable=MagicMock) as mock_repo:
        mock_repo.get_by_novel = AsyncMock(
            return_value=([auto, manual, deprecated], 3)
        )

        result = await stats_service.list_auto_ingested_entities(db, novel_id)

        assert len(result) == 1
        assert result[0]["name"] == "Auto"
        assert result[0]["status"] == "canonical"


@pytest.mark.asyncio
async def test_list_auto_ingested_filters_by_chapter_range(
    stats_service: EntityStatsService,
) -> None:
    db = MagicMock()
    novel_id = str(uuid.uuid4())
    inside = _mock_entity(
        name="Inside",
        content_json={"_meta": {"auto_ingested": True, "source_chapter_index": 3}},
    )
    outside = _mock_entity(
        name="Outside",
        content_json={"_meta": {"auto_ingested": True, "source_chapter_index": 10}},
    )

    with patch.object(stats_service, "_repo", new_callable=MagicMock) as mock_repo:
        mock_repo.get_by_novel = AsyncMock(return_value=([inside, outside], 2))

        result = await stats_service.list_auto_ingested_entities(
            db, novel_id, start_chapter=1, end_chapter=5
        )

        assert len(result) == 1
        assert result[0]["name"] == "Inside"


@pytest.mark.asyncio
async def test_list_auto_ingested_returns_empty_when_none(
    stats_service: EntityStatsService,
) -> None:
    db = MagicMock()
    novel_id = str(uuid.uuid4())
    manual = _mock_entity(
        name="Manual",
        content_json={"_meta": {"auto_ingested": False}},
    )

    with patch.object(stats_service, "_repo", new_callable=MagicMock) as mock_repo:
        mock_repo.get_by_novel = AsyncMock(return_value=([manual], 1))

        result = await stats_service.list_auto_ingested_entities(db, novel_id)

        assert result == []
```

- [ ] **Step 6: Run all `EntityStatsService` tests**

```bash
cd backend && python -m pytest modules/world/tests/test_entity_stats_service.py -v
```

Expected: 6 passed

- [ ] **Step 7: Commit**

```bash
git add backend/modules/world/services/entity_stats_service.py \
        backend/modules/world/tests/test_entity_stats_service.py
git commit -m "feat(world): add EntityStatsService for count and auto-ingested queries"
```

---

### Task 3: Update `entity_facade.py` Callers

**Files:**
- Modify: `backend/modules/world/entity_facade.py`

- [ ] **Step 1: Import `EntityStatsService` and add module-level instance**

修改 `backend/modules/world/entity_facade.py` 顶部：

```python
from modules.world.services import (
    EntityAliasService,
    EntityContextService,
    EntityEmbeddingService,
    EntityRelationService,
    EntityStatsService,
    WorldEntityService,
)
```

在实例化区添加：

```python
_entity_service = WorldEntityService()
_context_service = EntityContextService()
_alias_service = EntityAliasService()
_embedding_service = EntityEmbeddingService()
_stats_service = EntityStatsService()
_relation_service = EntityRelationService()
_dedup_service = EntityDedupService()
```

- [ ] **Step 2: Replace `count_entities` body with delegation**

```python
async def count_entities(
    db: AsyncSession,
    novel_id: str,
    *,
    status_filter: list[str] | None = None,
) -> int:
    """统计 novel 的 CoreEntity 数量。"""
    return await _stats_service.count_entities(
        db,
        novel_id,
        status_filter=status_filter,
    )
```

- [ ] **Step 3: Replace `list_auto_ingested_entities` body with delegation**

```python
async def list_auto_ingested_entities(
    db: AsyncSession,
    novel_id: str,
    *,
    start_chapter: int | None = None,
    end_chapter: int | None = None,
    limit: int = 10000,
) -> list[dict[str, Any]]:
    """列出 novel 中由深度导入自动生成的实体。"""
    return await _stats_service.list_auto_ingested_entities(
        db,
        novel_id,
        start_chapter=start_chapter,
        end_chapter=end_chapter,
        limit=limit,
    )
```

- [ ] **Step 4: Remove unused inline imports from facade**

确认 `count_entities` 与 `list_auto_ingested_entities` 内部不再有需要保留的局部 `select` / `func` / `CoreEntity` 导入，删除这些局部导入。

- [ ] **Step 5: Run facade tests**

```bash
cd backend && python -m pytest modules/world/tests/test_world.py -v
```

Expected: tests pass

- [ ] **Step 6: Commit**

```bash
git add backend/modules/world/entity_facade.py
git commit -m "refactor(world): delegate count and auto-ingested queries to EntityStatsService"
```

---

### Task 4: Export `EntityStatsService`

**Files:**
- Modify: `backend/modules/world/services/__init__.py`

- [ ] **Step 1: Add import and `__all__` entry**

```python
from modules.world.services.entity_stats_service import EntityStatsService
```

```python
__all__ = [
    "WorldEntityService",
    "EntityAliasService",
    "EntityContextService",
    "EntityEmbeddingService",
    "EntityStatsService",
    "EntityRelationService",
    "EntityRevisionService",
    "EventService",
    "CharacterService",
    "CharacterKnowledgeService",
    # ... existing map services and helpers
]
```

- [ ] **Step 2: Run import smoke test**

```bash
cd backend && python -c "from modules.world.services import EntityStatsService; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add backend/modules/world/services/__init__.py
git commit -m "chore(world): export EntityStatsService"
```

---

### Task 5: Update Module Documentation

**Files:**
- Modify: `backend/modules/world/README.md`

- [ ] **Step 1: Add service to "职责" section**

在 `backend/modules/world/README.md` 的 "职责" 列表中新增：

```markdown
- 实体统计与自动入库查询（`EntityStatsService`）
```

位置建议在 `EntityContextService` 之后、`向其他模块提供世界上下文` 之前。

- [ ] **Step 2: Commit**

```bash
git add backend/modules/world/README.md
git commit -m "docs(world): document EntityStatsService in module README"
```

---

### Task 6: Full Verification

**Files:**
- All modified files

- [ ] **Step 1: Run world module tests**

```bash
cd backend && python -m pytest modules/world/tests/ tests/unit/test_world_extra.py -q
```

Expected: all pass

- [ ] **Step 2: Run imports module tests that depend on `list_auto_ingested_entities`**

```bash
cd backend && python -m pytest modules/imports/tests/ -q
```

Expected: all pass

- [ ] **Step 3: Run lint and format checks**

```bash
cd backend && ruff check modules/world/services/entity_stats_service.py \
    modules/world/repositories.py \
    modules/world/entity_facade.py \
    modules/world/services/__init__.py \
    modules/world/tests/test_entity_stats_service.py
```

Expected: no errors

```bash
cd backend && ruff format --check modules/world/services/entity_stats_service.py \
    modules/world/repositories.py \
    modules/world/entity_facade.py \
    modules/world/services/__init__.py \
    modules/world/tests/test_entity_stats_service.py
```

Expected: no changes needed (or run `ruff format` to fix)

- [ ] **Step 4: Commit if lint/format changes were applied**

```bash
git add -u
git commit -m "style(world): apply ruff format after EntityStatsService extraction"
```

---

## Self-Review

**1. Spec coverage:**
- 拆出 `count_entities` → Task 1 + Task 2 + Task 3 ✓
- 拆出 `list_auto_ingested_entities` → Task 2 + Task 3 ✓
- facade 不再直接写 SQL/ORM 查询 → Task 3 删除局部 SQL 导入 ✓
- 新增服务测试 → Task 1 + Task 2 ✓

**2. Placeholder scan:** No TBD/TODO; every step includes exact file paths, code, commands.

**3. Type consistency:**
- `CoreEntityRepository.count_entities` signature: `(db, novel_id: uuid.UUID, *, status_filter)` — matches service call.
- `EntityStatsService.count_entities` signature: `(db, novel_id: str, *, status_filter)` — matches facade.
- `list_auto_ingested_entities` 保持原有参数名与返回结构。

**4. Gap check:** `api.py` 中无 `count_entities` / `list_auto_ingested_entities` 路由，因此无需更新 API 层；外部调用方（`modules/imports/facade.py`）通过 `modules.world.facade` 导入，签名不变。

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-06-22-entity-stats-service-candidate-4.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - Dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
