# WorldEntityService 职责拆分 — 候选 3 修复计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `backend/modules/world/services/entity_service.py` 中别名、embedding、上下文/查询三类职责拆出为独立服务，`WorldEntityService` 仅保留 core CRUD + 创建去重校验。

**Architecture:** 按领域概念拆分服务层：`EntityAliasService` 管理 `content_json.aliases`；`EntityEmbeddingService` 负责向量回填；`EntityContextService` 负责世界上下文、检索词典、批次、名称查找。`WorldEntityService` 退化为薄 CRUD 协调层。Facade 与 API 层只改委托对象，不改外部接口。

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 async, Pydantic v2, pytest-asyncio.

---

## File Structure

| 文件 | 状态 | 职责 |
|------|------|------|
| `backend/modules/world/services/entity_alias_service.py` | 新建 | 别名列表/创建/删除；操作 `core_entities.content_json.aliases` |
| `backend/modules/world/services/entity_embedding_service.py` | 新建 | 批量回填缺失的实体 embedding |
| `backend/modules/world/services/entity_context_service.py` | 新建 | 世界上下文、检索词典、批次、按名称查 ID |
| `backend/modules/world/services/entity_service.py` | 修改 | 仅保留 core CRUD + create 去重 + list filter |
| `backend/modules/world/services/__init__.py` | 修改 | 导出新服务 |
| `backend/modules/world/entity_facade.py` | 修改 | 上下文/术语/embedding/批次委托给新服务 |
| `backend/modules/world/api.py` | 修改 | 别名路由委托给 `EntityAliasService` |
| `backend/modules/world/tests/test_entity_alias_service.py` | 新建 | 别名服务单元测试 |
| `backend/modules/world/tests/test_entity_embedding_service.py` | 新建 | embedding 服务单元测试 |
| `backend/modules/world/tests/test_entity_context_service.py` | 新建 | 上下文服务单元测试 |
| `backend/tests/unit/test_world_extra.py` | 修改 | 将原 `WorldEntityService.*` 非 CRUD 测试迁移到对应新服务 |
| `backend/modules/world/tests/test_world.py` | 修改 | facade 测试仍走 facade，必要时调整 fixture/导入 |
| `backend/modules/world/tests/test_world_object_management.py` | 修改 | 仍使用 `WorldEntityService` 做 CRUD，无需大改 |

---

### Task 1: Create `EntityAliasService`

**Files:**
- Create: `backend/modules/world/services/entity_alias_service.py`
- Test: `backend/modules/world/tests/test_entity_alias_service.py`

- [ ] **Step 1: Write the failing test for list aliases**

```python
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.schemas import WorldEntityCreate
from modules.world.services import WorldEntityService
from modules.world.services.entity_alias_service import EntityAliasService


@pytest.fixture
def alias_service() -> EntityAliasService:
    return EntityAliasService()


@pytest.fixture
def entity_service() -> WorldEntityService:
    return WorldEntityService()


@pytest.mark.asyncio
async def test_list_aliases_returns_all_aliases(
    db_session: AsyncSession,
    entity_service: WorldEntityService,
    alias_service: EntityAliasService,
) -> None:
    from modules.project.models import Project

    novel_id = str(uuid.uuid4())
    db_session.add(
        Project(
            id=uuid.UUID(hex=novel_id),
            title="t",
            genre="fantasy",
            language="zh",
            target_length="novel",
            current_stage="worldbuilding",
        )
    )
    entity = await entity_service.create(
        db_session,
        novel_id,
        WorldEntityCreate(
            entity_type="character",
            name="亚瑟",
            content_json={"aliases": [{"alias": "Art", "type": "nickname"}]},
        ),
    )

    result = await alias_service.list_aliases(db_session, novel_id)

    assert len(result) == 1
    assert result[0]["alias"] == "Art"
    assert result[0]["entity_id"] == entity.id
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd backend && python -m pytest modules/world/tests/test_entity_alias_service.py::test_list_aliases_returns_all_aliases -v
```
Expected: `FAIL` with `ModuleNotFoundError: No module named 'modules.world.services.entity_alias_service'`

- [ ] **Step 3: Create `EntityAliasService` with list/create/delete**

```python
"""EntityAliasService — 管理 core_entities.content_json.aliases。"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.models import CoreEntity
from modules.world.repositories import CoreEntityRepository
from modules.world.services.helpers import parse_uuid


class EntityAliasService:
    """别名 CRUD（内联于 CoreEntity.content_json.aliases JSONB）。"""

    def __init__(self, repo: CoreEntityRepository | None = None) -> None:
        self._repo = repo or CoreEntityRepository()

    async def list_aliases(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> list[dict]:
        """列出项目下所有实体的别名。"""
        nid = parse_uuid(novel_id, "novel_id")
        entities, _ = await self._repo.get_by_novel(db, nid, limit=limit)
        result = []
        for entity in entities:
            aliases = (entity.content_json or {}).get("aliases", [])
            for a in aliases:
                alias_text = a if isinstance(a, str) else a.get("alias", "")
                alias_type = a.get("type", "name") if isinstance(a, dict) else "name"
                result.append(
                    {
                        "entity_id": str(entity.id),
                        "entity_name": entity.name,
                        "alias": alias_text,
                        "alias_type": alias_type,
                    }
                )
        return result[skip : skip + limit]

    async def create_alias(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_id: str,
        alias: str,
        alias_type: str = "name",
    ) -> dict:
        """为实体添加别名。"""
        nid = parse_uuid(novel_id, "novel_id")
        eid = parse_uuid(entity_id, "entity_id")
        entity = await self._repo.get(db, eid)
        if entity is None or entity.novel_id != nid:
            raise HTTPException(status_code=404, detail="Entity not found")
        content = entity.content_json or {}
        aliases = content.get("aliases", [])
        for a in aliases:
            existing = a if isinstance(a, str) else a.get("alias", "")
            if existing == alias:
                raise HTTPException(
                    status_code=409, detail=f"Alias already exists: {alias}"
                )
        aliases.append({"alias": alias, "type": alias_type})
        content["aliases"] = aliases
        entity.content_json = content
        await db.flush()
        return {"entity_id": str(entity.id), "alias": alias, "alias_type": alias_type}

    async def delete_alias(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_id: str,
        alias: str,
    ) -> dict:
        """删除实体的指定别名。"""
        nid = parse_uuid(novel_id, "novel_id")
        eid = parse_uuid(entity_id, "entity_id")
        entity = await self._repo.get(db, eid)
        if entity is None or entity.novel_id != nid:
            raise HTTPException(status_code=404, detail="Entity not found")
        content = entity.content_json or {}
        aliases = content.get("aliases", [])
        new_aliases = []
        found = False
        for a in aliases:
            existing = a if isinstance(a, str) else a.get("alias", "")
            if existing == alias:
                found = True
                continue
            new_aliases.append(a)
        if not found:
            raise HTTPException(status_code=404, detail=f"Alias not found: {alias}")
        content["aliases"] = new_aliases
        entity.content_json = content
        await db.flush()
        return {"entity_id": str(entity.id), "alias": alias, "deleted": True}
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
cd backend && python -m pytest modules/world/tests/test_entity_alias_service.py::test_list_aliases_returns_all_aliases -v
```
Expected: `PASS`

- [ ] **Step 5: Add create/delete alias tests**

```python
@pytest.mark.asyncio
async def test_create_alias_adds_to_content_json(
    db_session: AsyncSession,
    entity_service: WorldEntityService,
    alias_service: EntityAliasService,
) -> None:
    from modules.project.models import Project

    novel_id = str(uuid.uuid4())
    db_session.add(
        Project(
            id=uuid.UUID(hex=novel_id),
            title="t",
            genre="fantasy",
            language="zh",
            target_length="novel",
            current_stage="worldbuilding",
        )
    )
    entity = await entity_service.create(
        db_session,
        novel_id,
        WorldEntityCreate(entity_type="character", name="亚瑟"),
    )

    result = await alias_service.create_alias(
        db_session, novel_id, entity.id, "Art", "nickname"
    )

    assert result["alias"] == "Art"
    refreshed = await entity_service.get(db_session, entity.id, novel_id=novel_id)
    assert refreshed.content_json["aliases"] == [{"alias": "Art", "type": "nickname"}]


@pytest.mark.asyncio
async def test_delete_alias_removes_from_content_json(
    db_session: AsyncSession,
    entity_service: WorldEntityService,
    alias_service: EntityAliasService,
) -> None:
    from modules.project.models import Project

    novel_id = str(uuid.uuid4())
    db_session.add(
        Project(
            id=uuid.UUID(hex=novel_id),
            title="t",
            genre="fantasy",
            language="zh",
            target_length="novel",
            current_stage="worldbuilding",
        )
    )
    entity = await entity_service.create(
        db_session,
        novel_id,
        WorldEntityCreate(
            entity_type="character",
            name="亚瑟",
            content_json={"aliases": [{"alias": "Art", "type": "nickname"}]},
        ),
    )

    result = await alias_service.delete_alias(db_session, novel_id, entity.id, "Art")

    assert result["deleted"] is True
    refreshed = await entity_service.get(db_session, entity.id, novel_id=novel_id)
    assert refreshed.content_json["aliases"] == []
```

- [ ] **Step 6: Run all alias service tests**

Run:
```bash
cd backend && python -m pytest modules/world/tests/test_entity_alias_service.py -v
```
Expected: 3 passed

- [ ] **Step 7: Commit**

```bash
git add backend/modules/world/services/entity_alias_service.py \
        backend/modules/world/tests/test_entity_alias_service.py
git commit -m "feat(world): add EntityAliasService for core_entities.content_json.aliases"
```

---

### Task 2: Create `EntityEmbeddingService`

**Files:**
- Create: `backend/modules/world/services/entity_embedding_service.py`
- Test: `backend/modules/world/tests/test_entity_embedding_service.py`

- [ ] **Step 1: Write the failing test for backfill when no entities need embedding**

```python
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.world.services.entity_embedding_service import EntityEmbeddingService


@pytest.fixture
def embedding_service() -> EntityEmbeddingService:
    return EntityEmbeddingService()


@pytest.mark.asyncio
async def test_no_entities_returns_zero(embedding_service: EntityEmbeddingService) -> None:
    db = MagicMock()
    query_result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = []
    query_result.scalars.return_value = scalars
    db.execute = AsyncMock(return_value=query_result)

    result = await embedding_service.backfill_embeddings(db, str(uuid.uuid4()))

    assert result == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd backend && python -m pytest modules/world/tests/test_entity_embedding_service.py::test_no_entities_returns_zero -v
```
Expected: `FAIL` with module not found

- [ ] **Step 3: Create `EntityEmbeddingService` with backfill logic**

```python
"""EntityEmbeddingService — 实体 embedding 批量回填。"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.embedding.client import BgeEmbeddingClient
from modules.world.models import CoreEntity
from modules.world.services.helpers import parse_uuid

_logger = logging.getLogger(__name__)


class EntityEmbeddingService:
    """为缺少 embedding 的实体生成向量。"""

    async def backfill_embeddings(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        batch_size: int = 64,
    ) -> int:
        """为 novel 中缺少 embedding 的实体生成向量。返回回填数量。"""
        nid = parse_uuid(novel_id, "novel_id")

        stmt = select(CoreEntity).where(
            CoreEntity.novel_id == nid,
            CoreEntity.embedding.is_(None),
            CoreEntity.status.in_(["canonical", "draft"]),
        )
        result = await db.execute(stmt)
        entities = list(result.scalars().all())

        if not entities:
            return 0

        try:
            bge = await BgeEmbeddingClient.get_instance()
        except Exception:
            _logger.warning("BGE client unavailable, backfill skipped")
            return 0

        total = 0
        named = [(e, e.name.strip()) for e in entities if e.name and e.name.strip()]

        for i in range(0, len(named), batch_size):
            batch = named[i : i + batch_size]
            batch_entities = [e for e, _ in batch]
            batch_texts = [n for _, n in batch]
            try:
                embeddings = await bge.generate_embedding(batch_texts, is_query=False)
            except Exception:
                _logger.exception("Backfill embedding batch failed at offset %d", i)
                continue

            for entity, emb in zip(batch_entities, embeddings):
                entity.embedding = [float(v) for v in emb]
                entity.embedding_text = entity.name
                total += 1

            await db.flush()

        _logger.info("Backfilled embeddings for %d entities in novel %s", total, novel_id)
        return total
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
cd backend && python -m pytest modules/world/tests/test_entity_embedding_service.py::test_no_entities_returns_zero -v
```
Expected: `PASS`

- [ ] **Step 5: Add happy path and failure tests**

```python
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _mock_entity(name: str) -> MagicMock:
    e = MagicMock()
    e.name = name
    e.embedding = None
    e.embedding_text = None
    return e


class TestEntityEmbeddingServiceBackfill:
    @pytest.fixture
    def service(self) -> EntityEmbeddingService:
        return EntityEmbeddingService()

    def _make_db(self, entities: list) -> MagicMock:
        db = MagicMock()
        query_result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = entities
        query_result.scalars.return_value = scalars_mock
        db.execute = AsyncMock(return_value=query_result)
        db.flush = AsyncMock()
        return db

    @patch("modules.world.services.entity_embedding_service.BgeEmbeddingClient.get_instance")
    async def test_happy_path_backfills_in_batches(self, mock_get_instance, service) -> None:
        bge = AsyncMock()
        bge.generate_embedding = AsyncMock(return_value=[[0.1], [0.2], [0.3], [0.4]])
        mock_get_instance.return_value = bge
        ents = [_mock_entity(f"E{i}") for i in range(4)]
        db = self._make_db(ents)

        result = await service.backfill_embeddings(db, str(uuid.uuid4()), batch_size=4)

        assert result == 4
        for e, expected_val in zip(ents, [0.1, 0.2, 0.3, 0.4]):
            assert e.embedding == [expected_val]
            assert e.embedding_text == e.name

    @patch("modules.world.services.entity_embedding_service.BgeEmbeddingClient.get_instance")
    async def test_bge_unavailable_returns_zero(self, mock_get_instance, service) -> None:
        mock_get_instance.side_effect = RuntimeError("BGE not available")
        db = self._make_db([_mock_entity("Arthur")])
        result = await service.backfill_embeddings(db, str(uuid.uuid4()))
        assert result == 0

    @patch("modules.world.services.entity_embedding_service.BgeEmbeddingClient.get_instance")
    async def test_batch_failure_continues_to_next_batch(self, mock_get_instance, service) -> None:
        bge = AsyncMock()
        bge.generate_embedding = AsyncMock(
            side_effect=[
                RuntimeError("API error"),
                [[0.9], [1.0]],
            ]
        )
        mock_get_instance.return_value = bge
        ents = [_mock_entity(f"E{i}") for i in range(4)]
        db = self._make_db(ents)

        result = await service.backfill_embeddings(db, str(uuid.uuid4()), batch_size=2)

        assert result == 2
```

- [ ] **Step 6: Run all embedding service tests**

Run:
```bash
cd backend && python -m pytest modules/world/tests/test_entity_embedding_service.py -v
```
Expected: 4 passed

- [ ] **Step 7: Commit**

```bash
git add backend/modules/world/services/entity_embedding_service.py \
        backend/modules/world/tests/test_entity_embedding_service.py
git commit -m "feat(world): add EntityEmbeddingService for backfilling entity embeddings"
```

---

### Task 3: Create `EntityContextService`

**Files:**
- Create: `backend/modules/world/services/entity_context_service.py`
- Test: `backend/modules/world/tests/test_entity_context_service.py`

- [ ] **Step 1: Write the failing test for get_entity_context**

```python
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.world.services.entity_context_service import EntityContextService


@pytest.fixture
def context_service() -> EntityContextService:
    return EntityContextService()


@pytest.mark.asyncio
async def test_get_entity_context_with_entity_ids(context_service: EntityContextService) -> None:
    db = MagicMock()
    nid = str(uuid.uuid4())
    eid = str(uuid.uuid4())

    entity = MagicMock()
    entity.id = uuid.UUID(hex=eid)
    entity.entity_type = "location"
    entity.name = "Middle-earth"
    entity.summary = "A continent"
    entity.public_info = "Known"
    entity.hidden_truth = "Secret"
    entity.importance = 0.9
    entity.importance_level = "core"
    entity.reveal_level = "hinted"
    entity.status = "canonical"

    with patch.object(context_service, "_repo", new_callable=MagicMock) as mock_repo:
        mock_repo.get_by_ids = AsyncMock(return_value=[entity])
        result = await context_service.get_entity_context(db, nid, entity_ids=[eid])

    assert result.total_count == 1
    assert result.entities[0].name == "Middle-earth"
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd backend && python -m pytest modules/world/tests/test_entity_context_service.py::test_get_entity_context_with_entity_ids -v
```
Expected: `FAIL` with module not found

- [ ] **Step 3: Create `EntityContextService` with all context/query methods**

```python
"""EntityContextService — 实体上下文、检索词典、批次、名称查找。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.models import CoreEntity
from modules.world.repositories import CoreEntityRepository
from modules.world.schemas import WorldContextBundle, WorldEntityContext
from modules.world.services.helpers import parse_uuid


class EntityContextService:
    """提供世界对象上下文、检索词典、批次分组、按名称查找等查询能力。"""

    def __init__(self, repo: CoreEntityRepository | None = None) -> None:
        self._repo = repo or CoreEntityRepository()

    async def get_entity_context(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_ids: list[str] | None = None,
        reveal_mode: str = "author_safe",
        limit: int = 20,
        current_chapter: int | None = None,
    ) -> WorldContextBundle:
        """获取世界上下文，支持临时实体过期过滤。"""
        nid = parse_uuid(novel_id, "novel_id")

        if entity_ids:
            eids = [parse_uuid(eid, "entity_id") for eid in entity_ids]
            entities = await self._repo.get_by_ids(db, nid, eids)
        else:
            entities, _ = await self._repo.get_by_novel(db, nid, limit=limit)

        if current_chapter is not None:
            from modules.project.facade import get_project_context

            project_ctx = await get_project_context(db, novel_id)
            expiry = 30
            if project_ctx is not None and project_ctx.settings:
                expiry = project_ctx.settings.get(
                    "temporary_entity_expiry_chapters", 30
                )

            filtered: list[CoreEntity] = []
            for entity in entities:
                content = entity.content_json or {}
                meta = content.get("_meta", {})
                if (
                    meta.get("temporary") is True
                    and meta.get("source_chapter_index") is not None
                ):
                    src_ch = int(meta["source_chapter_index"])
                    if current_chapter - src_ch > expiry:
                        continue
                filtered.append(entity)
            entities = filtered

        contexts = [_entity_to_context(entity, reveal_mode) for entity in entities]

        return WorldContextBundle(
            novel_id=novel_id,
            entities=contexts,
            total_count=len(contexts),
            reveal_mode=reveal_mode,
        )

    async def list_entity_summaries(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        entity_type: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """获取世界对象摘要列表。"""
        nid = parse_uuid(novel_id, "novel_id")
        result = await self._repo.get_by_type_and_status(
            db,
            nid,
            entity_type=entity_type,
            limit=limit,
        )
        return [
            {"id": item.id, "name": item.name, "entity_type": item.entity_type}
            for item in result
        ]

    async def list_entity_terms(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        limit: int = 500,
    ) -> list[dict]:
        """获取正史 + 草稿实体的检索词典项（name + content_json.aliases）。"""
        nid = parse_uuid(novel_id, "novel_id")
        entities, _ = await self._repo.get_by_novel(db, nid, limit=limit)
        terms: list[dict] = []
        for item in entities:
            if item.status not in ("canonical", "draft"):
                continue
            item_terms = [item.name]
            aliases = (item.content_json or {}).get("aliases", [])
            item_terms.extend(
                a if isinstance(a, str) else a.get("alias", "") for a in aliases
            )
            terms.append(
                {
                    "id": str(item.id),
                    "name": item.name,
                    "entity_type": item.entity_type,
                    "terms": [t for t in item_terms if t],
                }
            )
        return terms

    async def find_by_name(
        self,
        db: AsyncSession,
        novel_id: str,
        name: str,
        entity_type: str | None = None,
    ) -> str | None:
        """按名称查正史实体 ID，返回 str 或 None。"""
        nid = parse_uuid(novel_id, "novel_id")
        return await self._repo.find_entity_by_name(
            db,
            nid,
            name,
            entity_type=entity_type,
        )

    async def list_entity_batches(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        limit: int = 10,
    ) -> list[dict]:
        """获取自动入库实体的批次分组列表。"""
        nid = parse_uuid(novel_id, "novel_id")
        return await self._repo.get_entity_batches(db, nid, limit=limit)


def _entity_to_context(
    entity: CoreEntity,
    reveal_mode: str,
) -> WorldEntityContext:
    hidden = None
    if reveal_mode == "author_only":
        hidden = entity.hidden_truth

    return WorldEntityContext(
        entity_id=str(entity.id),
        entity_type=entity.entity_type,
        name=entity.name,
        summary=entity.summary,
        public_info=entity.public_info,
        hidden_truth=hidden,
        importance=entity.importance,
        importance_level=entity.importance_level,
        reveal_level=entity.reveal_level,
        status=entity.status,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
cd backend && python -m pytest modules/world/tests/test_entity_context_service.py::test_get_entity_context_with_entity_ids -v
```
Expected: `PASS`

- [ ] **Step 5: Add tests for terms, summaries, find_by_name, batches**

```python
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.world.services.entity_context_service import EntityContextService


def _mock_entity(**overrides) -> MagicMock:
    defaults = {
        "id": uuid.uuid4(),
        "novel_id": uuid.uuid4(),
        "entity_type": "character",
        "name": "Test",
        "summary": None,
        "public_info": None,
        "hidden_truth": None,
        "content_json": {},
        "importance": 0.5,
        "importance_level": "normal",
        "reveal_level": "author_only",
        "status": "draft",
        "embedding_text": None,
        "created_by": None,
        "approved_by": None,
        "created_at": None,
        "updated_at": None,
    }
    defaults.update(overrides)
    e = MagicMock()
    for k, v in defaults.items():
        setattr(e, k, v)
    return e


@pytest.fixture
def context_service() -> EntityContextService:
    return EntityContextService()


class TestEntityContextServiceSummaries:
    async def test_list_entity_summaries_returns_id_name_type(self, context_service) -> None:
        db = MagicMock()
        nid = str(uuid.uuid4())
        ent = _mock_entity(name="Sword", entity_type="item")
        with patch.object(context_service, "_repo", new_callable=MagicMock) as mock_repo:
            mock_repo.get_by_type_and_status = AsyncMock(return_value=[ent])
            result = await context_service.list_entity_summaries(
                db, nid, entity_type="item", limit=50
            )

        assert len(result) == 1
        assert result[0]["name"] == "Sword"
        assert result[0]["entity_type"] == "item"


class TestEntityContextServiceTerms:
    async def test_only_canonical_and_draft_included(self, context_service) -> None:
        db = MagicMock()
        canonical = _mock_entity(name="Hero", status="canonical")
        draft = _mock_entity(name="Sidekick", status="draft")
        merged = _mock_entity(name="Gone", status="merged")
        with patch.object(context_service, "_repo", new_callable=MagicMock) as mock_repo:
            mock_repo.get_by_novel = AsyncMock(
                return_value=([canonical, draft, merged], 3)
            )
            result = await context_service.list_entity_terms(db, str(uuid.uuid4()))
            assert len(result) == 2

    async def test_extracts_aliases_from_content_json(self, context_service) -> None:
        db = MagicMock()
        ent1 = _mock_entity(
            name="Arthur",
            status="canonical",
            content_json={"aliases": ["King", {"alias": "Once and Future King"}]},
        )
        ent2 = _mock_entity(name="Merlin", status="canonical", content_json={"aliases": []})
        with patch.object(context_service, "_repo", new_callable=MagicMock) as mock_repo:
            mock_repo.get_by_novel = AsyncMock(return_value=([ent1, ent2], 2))
            result = await context_service.list_entity_terms(db, str(uuid.uuid4()))

            assert len(result) == 2
            arthur_terms = [t for t in result if t["name"] == "Arthur"][0]
            assert "Arthur" in arthur_terms["terms"]
            assert "King" in arthur_terms["terms"]
            assert "Once and Future King" in arthur_terms["terms"]


class TestEntityContextServiceFindByName:
    async def test_found_returns_entity_id_str(self, context_service) -> None:
        db = MagicMock()
        eid = str(uuid.uuid4())
        with patch.object(context_service, "_repo", new_callable=MagicMock) as mock_repo:
            mock_repo.find_entity_by_name = AsyncMock(return_value=eid)
            result = await context_service.find_by_name(db, str(uuid.uuid4()), "Arthur")
            assert result == eid

    async def test_not_found_returns_none(self, context_service) -> None:
        db = MagicMock()
        with patch.object(context_service, "_repo", new_callable=MagicMock) as mock_repo:
            mock_repo.find_entity_by_name = AsyncMock(return_value=None)
            result = await context_service.find_by_name(db, str(uuid.uuid4()), "Nobody")
            assert result is None


class TestEntityContextServiceTempEntityFiltering:
    async def test_expired_temp_entity_filtered_out(self, context_service) -> None:
        db = MagicMock()
        db.execute = AsyncMock()
        db.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)
        old_temp = _mock_entity(
            content_json={"_meta": {"temporary": True, "source_chapter_index": 1}},
        )
        with patch.object(context_service, "_repo", new_callable=MagicMock) as mock_repo:
            mock_repo.get_by_novel = AsyncMock(return_value=([old_temp], 1))
            result = await context_service.get_entity_context(
                db,
                str(uuid.uuid4()),
                current_chapter=100,
            )
            assert result.total_count == 0
```

- [ ] **Step 6: Run all context service tests**

Run:
```bash
cd backend && python -m pytest modules/world/tests/test_entity_context_service.py -v
```
Expected: 7 passed

- [ ] **Step 7: Commit**

```bash
git add backend/modules/world/services/entity_context_service.py \
        backend/modules/world/tests/test_entity_context_service.py
git commit -m "feat(world): add EntityContextService for context/terms/batches/name lookup"
```

---

### Task 4: Slim Down `WorldEntityService`

**Files:**
- Modify: `backend/modules/world/services/entity_service.py`

- [ ] **Step 1: Replace `WorldEntityService` body with core CRUD only**

```python
"""WorldEntityService — 核心实体 CRUD。继承 BaseCRUDService (ADR-0002)。

list 加 entity_type / status filter + 返 ListResponse (per design B3,
subclass override)。
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.repositories import CoreEntityRepository
from modules.world.schemas import (
    CoreEntityCreate,
    CoreEntityListResponse,
    CoreEntityResponse,
    CoreEntityUpdate,
)
from modules.world.services.base import CrudService
from modules.world.services.helpers import parse_uuid
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


class WorldEntityService(
    CrudService[
        CoreEntity,
        CoreEntityCreate,
        CoreEntityUpdate,
        CoreEntityResponse,
    ],
):
    """核心实体业务服务：仅保留 CRUD + 创建去重校验。"""

    repo = CoreEntityRepository()
    response = CoreEntityResponse
    label = "CoreEntity"
    id_param = "entity_id"

    async def create(
        self,
        db: AsyncSession,
        novel_id: str,
        data: CoreEntityCreate,
    ) -> CoreEntityResponse:
        nid = parse_uuid(novel_id, "novel_id")

        if not data.created_by:
            data = data.model_copy(update={"created_by": "manual"})

        if not data.force_create:
            similar = await self.repo.find_similar_by_search_text(
                db,
                nid,
                data.name,
                entity_type=data.entity_type,
                status_filter=["canonical", "draft"],
                min_similarity=0.9,
                top_k=5,
            )
            if similar:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "requires_confirmation": True,
                        "similar_entities": [
                            {
                                "id": str(e.id),
                                "name": e.name,
                                "similarity_score": round(score, 2),
                            }
                            for e, score in similar[:5]
                        ],
                    },
                )

        obj = await self.repo.create(db, nid, data)
        return self._to_response(obj)

    async def list(  # type: ignore[override]
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        entity_type: str | None = None,
        status: str | None = None,
        q: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> CoreEntityListResponse:
        """带 filter 的 list, 返 ListResponse 包装 (不是 tuple)。"""
        nid = parse_uuid(novel_id, "novel_id")
        limit = min(limit, MAX_PAGE_SIZE)
        items, total = await self.repo.get_by_novel(
            db,
            nid,
            entity_type=entity_type,
            status=status,
            q=q,
            skip=skip,
            limit=limit,
        )
        return CoreEntityListResponse(
            items=[CoreEntityResponse.model_validate(e) for e in items],
            total=total,
        )
```

- [ ] **Step 2: Run existing CRUD tests**

Run:
```bash
cd backend && python -m pytest modules/world/tests/test_world.py::TestWorldEntityService -v
```
Expected: 5 passed

- [ ] **Step 3: Commit**

```bash
git add backend/modules/world/services/entity_service.py
git commit -m "refactor(world): slim WorldEntityService to core CRUD only"
```

---

### Task 5: Update `services/__init__.py`

**Files:**
- Modify: `backend/modules/world/services/__init__.py`

- [ ] **Step 1: Export the three new services**

```python
"""World 服务层导出"""

from modules.world.services.character_knowledge_service import (
    CharacterKnowledgeService,
)
from modules.world.services.character_service import CharacterService
from modules.world.services.entity_alias_service import EntityAliasService
from modules.world.services.entity_context_service import EntityContextService
from modules.world.services.entity_embedding_service import EntityEmbeddingService
from modules.world.services.entity_relation_service import EntityRelationService
from modules.world.services.entity_revision_service import EntityRevisionService
from modules.world.services.entity_service import WorldEntityService
from modules.world.services.event_service import EventService
from modules.world.services.helpers import (
    merge_text_field,
    normalize_name,
    parse_uuid,
    world_entity_types_compatible,
)

# 去重服务: 仍可通过 modules.world.services.dedup_service 直接导入

__all__ = [
    "WorldEntityService",
    "EntityAliasService",
    "EntityContextService",
    "EntityEmbeddingService",
    "EntityRelationService",
    "EntityRevisionService",
    "EventService",
    "CharacterService",
    "CharacterKnowledgeService",
    "parse_uuid",
    "normalize_name",
    "merge_text_field",
    "world_entity_types_compatible",
]
```

- [ ] **Step 2: Run import smoke test**

Run:
```bash
cd backend && python -c "from modules.world.services import EntityAliasService, EntityContextService, EntityEmbeddingService; print('ok')"
```
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add backend/modules/world/services/__init__.py
git commit -m "chore(world): export new entity services"
```

---

### Task 6: Update `entity_facade.py` Callers

**Files:**
- Modify: `backend/modules/world/entity_facade.py`

- [ ] **Step 1: Update imports and module-level service instances**

Modify the top of `entity_facade.py` to:

```python
from modules.world.services import (
    EntityAliasService,
    EntityContextService,
    EntityEmbeddingService,
    EntityRelationService,
    WorldEntityService,
)
from modules.world.services.dedup_service import EntityDedupService

_entity_service = WorldEntityService()
_context_service = EntityContextService()
_alias_service = EntityAliasService()
_embedding_service = EntityEmbeddingService()
_relation_service = EntityRelationService()
_dedup_service = EntityDedupService()
```

- [ ] **Step 2: Redirect context/query methods to `_context_service`**

Replace the bodies of these functions to delegate to `_context_service`:

```python
async def list_entities(
    db: AsyncSession,
    novel_id: str,
    *,
    entity_type: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """获取世界对象摘要列表"""
    return await _context_service.list_entity_summaries(
        db,
        novel_id,
        entity_type=entity_type,
        limit=limit,
    )


async def list_entity_terms(
    db: AsyncSession,
    novel_id: str,
    *,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """获取世界对象检索词典项（名称 + 已确认别名）。"""
    return await _context_service.list_entity_terms(db, novel_id, limit=limit)


async def get_world_context(
    db: AsyncSession,
    novel_id: str,
    entity_ids: list[str] | None = None,
    reveal_mode: str = "author_safe",
    limit: int = 20,
    current_chapter: int | None = None,
) -> WorldContextBundle:
    """获取世界上下文"""
    return await _context_service.get_entity_context(
        db,
        novel_id,
        entity_ids=entity_ids,
        reveal_mode=reveal_mode,
        limit=limit,
        current_chapter=current_chapter,
    )


async def find_entity_id_by_name(
    db: AsyncSession,
    novel_id: str,
    name: str,
    entity_type: str | None = None,
) -> str | None:
    """按名称查正史实体 ID。"""
    return await _context_service.find_by_name(
        db,
        novel_id,
        name,
        entity_type=entity_type,
    )
```

- [ ] **Step 3: Redirect embedding backfill to `_embedding_service`**

```python
async def backfill_entity_embeddings(
    db: AsyncSession,
    novel_id: str,
    *,
    batch_size: int = 64,
) -> int:
    """回填 novel 中缺少 embedding 的实体向量。返回回填数量。"""
    return await _embedding_service.backfill_embeddings(
        db,
        novel_id,
        batch_size=batch_size,
    )
```

- [ ] **Step 4: Run facade tests**

Run:
```bash
cd backend && python -m pytest modules/world/tests/test_world.py::TestFacade -v
```
Expected: tests pass

- [ ] **Step 5: Commit**

```bash
git add backend/modules/world/entity_facade.py
git commit -m "refactor(world): delegate context/alias/embedding to new services in facade"
```

---

### Task 7: Update `api.py` Alias Routes

**Files:**
- Modify: `backend/modules/world/api.py`

- [ ] **Step 1: Import `EntityAliasService` and instantiate it**

Change imports from:
```python
from modules.world.services import (
    CharacterKnowledgeService,
    CharacterService,
    EntityRelationService,
    EntityRevisionService,
    EventService,
    WorldEntityService,
)
```
to:
```python
from modules.world.services import (
    CharacterKnowledgeService,
    CharacterService,
    EntityAliasService,
    EntityContextService,
    EntityRelationService,
    EntityRevisionService,
    EventService,
    WorldEntityService,
)
```

Change instance block from:
```python
_entity_service = WorldEntityService()
_relation_service = EntityRelationService()
_dedup_service = EntityDedupService()
_revision_service = EntityRevisionService()
_event_service = EventService()
_character_service = CharacterService()
_knowledge_service = CharacterKnowledgeService()
```
to:
```python
_entity_service = WorldEntityService()
_alias_service = EntityAliasService()
_context_service = EntityContextService()
_relation_service = EntityRelationService()
_dedup_service = EntityDedupService()
_revision_service = EntityRevisionService()
_event_service = EventService()
_character_service = CharacterService()
_knowledge_service = CharacterKnowledgeService()
```

- [ ] **Step 2: Update alias and batch route handlers**

Change `/aliases` GET handler to:
```python
@router.get("/aliases")
async def list_aliases(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict]:
    """列出项目下所有实体的别名"""
    return await _alias_service.list_aliases(
        db,
        novel_id,
        skip=skip,
        limit=limit,
    )
```

Change `/aliases` POST handler to:
```python
@router.post("/aliases", status_code=201)
async def create_alias(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    data: EntityAliasCreate = ...,
) -> dict:
    """为实体添加别名"""
    return await _alias_service.create_alias(
        db,
        novel_id,
        data.entity_id,
        data.alias,
        data.alias_type,
    )
```

Change `/entities/{entity_id}/aliases` DELETE handler to:
```python
@router.delete("/entities/{entity_id}/aliases")
async def delete_alias(
    db: DbSession,
    entity_id: str,
    novel_id: str = Query(..., description="项目 ID"),
    alias: str = Query(..., description="要删除的别名文本"),
) -> dict:
    """删除实体的指定别名"""
    return await _alias_service.delete_alias(
        db,
        novel_id,
        entity_id,
        alias,
    )
```

Change `/entity-batches` GET handler to:
```python
@router.get("/entity-batches")
async def list_entity_batches(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    limit: int = Query(default=10, ge=1, le=50, description="最多返回的批次数量"),
) -> list[dict]:
    """获取自动入库实体的批次分组列表"""
    return await _context_service.list_entity_batches(
        db,
        novel_id,
        limit=limit,
    )
```

- [ ] **Step 3: Run API tests**

Run:
```bash
cd backend && python -m pytest modules/world/tests/test_world_object_management.py::TestWorldObjectManagementAPI -v
```
Expected: tests pass

- [ ] **Step 4: Commit**

```bash
git add backend/modules/world/api.py
git commit -m "refactor(world): use EntityAliasService/EntityContextService in API routes"
```

---

### Task 8: Update Existing Tests

**Files:**
- Modify: `backend/tests/unit/test_world_extra.py`
- Modify: `backend/modules/world/tests/test_world.py` (if needed)
- Modify: `backend/modules/world/tests/test_world_object_management.py` (if needed)

- [ ] **Step 1: Update `test_world_extra.py` imports and class names**

Change the import:
```python
from modules.world.services.entity_service import WorldEntityService, _entity_to_context
```
to:
```python
from modules.world.services.entity_context_service import (
    EntityContextService,
    _entity_to_context,
)
from modules.world.services.entity_embedding_service import EntityEmbeddingService
from modules.world.services.entity_service import WorldEntityService
```

- [ ] **Step 2: Rename/migrate context tests to use `EntityContextService`**

Replace class `TestEntityServiceGetEntityContext` with `TestEntityContextServiceGetEntityContext`, and patch `EntityContextService` instead of `WorldEntityService`:

```python
class TestEntityContextServiceGetEntityContext:
    """EntityContextService.get_entity_context"""

    async def test_with_entity_ids_filters_by_ids(self) -> None:
        db = MagicMock()
        nid = str(uuid.uuid4())
        eid = str(uuid.uuid4())
        with patch.object(
            EntityContextService, "_repo", new_callable=MagicMock
        ) as mock_repo:
            mock_repo.get_by_ids = AsyncMock(return_value=[_mock_entity()])
            svc = EntityContextService()
            result = await svc.get_entity_context(db, nid, entity_ids=[eid])
            assert result.total_count == 1
            mock_repo.get_by_ids.assert_awaited_once()

    async def test_without_entity_ids_falls_back_to_get_by_novel(self) -> None:
        db = MagicMock()
        with patch.object(
            EntityContextService, "_repo", new_callable=MagicMock
        ) as mock_repo:
            mock_repo.get_by_novel = AsyncMock(return_value=([], 0))
            svc = EntityContextService()
            result = await svc.get_entity_context(db, str(uuid.uuid4()), entity_ids=None)
            assert result.total_count == 0
            mock_repo.get_by_novel.assert_awaited_once()
            mock_repo.get_by_ids.assert_not_called()

    async def test_author_only_reveal_mode_includes_hidden_truth(self) -> None:
        db = MagicMock()
        ent = _mock_entity(hidden_truth="deep secret")
        with patch.object(
            EntityContextService, "_repo", new_callable=MagicMock
        ) as mock_repo:
            mock_repo.get_by_novel = AsyncMock(return_value=([ent], 1))
            svc = EntityContextService()
            result = await svc.get_entity_context(
                db,
                str(uuid.uuid4()),
                reveal_mode="author_only",
            )
            assert result.entities[0].hidden_truth == "deep secret"

    async def test_author_safe_reveal_mode_excludes_hidden_truth(self) -> None:
        db = MagicMock()
        ent = _mock_entity(hidden_truth="secret")
        with patch.object(
            EntityContextService, "_repo", new_callable=MagicMock
        ) as mock_repo:
            mock_repo.get_by_novel = AsyncMock(return_value=([ent], 1))
            svc = EntityContextService()
            result = await svc.get_entity_context(
                db,
                str(uuid.uuid4()),
                reveal_mode="author_safe",
            )
            assert result.entities[0].hidden_truth is None

    async def test_expired_temp_entity_filtered_out(self) -> None:
        db = MagicMock()
        db.execute = AsyncMock()
        db.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)
        old_temp = _mock_entity(
            content_json={"_meta": {"temporary": True, "source_chapter_index": 1}},
        )
        with patch.object(
            EntityContextService, "_repo", new_callable=MagicMock
        ) as mock_repo:
            mock_repo.get_by_novel = AsyncMock(return_value=([old_temp], 1))
            svc = EntityContextService()
            result = await svc.get_entity_context(
                db,
                str(uuid.uuid4()),
                current_chapter=100,
            )
            assert result.total_count == 0

    async def test_non_temp_entity_always_included(self) -> None:
        db = MagicMock()
        db.execute = AsyncMock()
        db.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)
        normal = _mock_entity(content_json={"_meta": {}})
        with patch.object(
            EntityContextService, "_repo", new_callable=MagicMock
        ) as mock_repo:
            mock_repo.get_by_novel = AsyncMock(return_value=([normal], 1))
            svc = EntityContextService()
            result = await svc.get_entity_context(
                db,
                str(uuid.uuid4()),
                current_chapter=100,
            )
            assert result.total_count == 1
```

- [ ] **Step 3: Rename/migrate summaries/terms/find_by_name tests**

```python
class TestEntityContextServiceListEntitySummaries:
    async def test_returns_id_name_type_dicts(self) -> None:
        db = MagicMock()
        nid = str(uuid.uuid4())
        ent = _mock_entity(name="Sword", entity_type="item")
        with patch.object(
            EntityContextService, "_repo", new_callable=MagicMock
        ) as mock_repo:
            mock_repo.get_by_type_and_status = AsyncMock(return_value=[ent])
            svc = EntityContextService()
            result = await svc.list_entity_summaries(
                db, nid, entity_type="item", limit=50
            )
            assert len(result) == 1
            assert result[0]["name"] == "Sword"
            assert result[0]["entity_type"] == "item"


class TestEntityContextServiceListEntityTerms:
    async def test_only_canonical_and_draft_included(self) -> None:
        db = MagicMock()
        canonical = _mock_entity(name="Hero", status="canonical")
        draft = _mock_entity(name="Sidekick", status="draft")
        merged = _mock_entity(name="Gone", status="merged")
        with patch.object(
            EntityContextService, "_repo", new_callable=MagicMock
        ) as mock_repo:
            mock_repo.get_by_novel = AsyncMock(
                return_value=([canonical, draft, merged], 3)
            )
            svc = EntityContextService()
            result = await svc.list_entity_terms(db, str(uuid.uuid4()))
            assert len(result) == 2

    async def test_extracts_aliases_from_content_json(self) -> None:
        db = MagicMock()
        ent1 = _mock_entity(
            name="Arthur",
            status="canonical",
            content_json={"aliases": ["King", {"alias": "Once and Future King"}]},
        )
        ent2 = _mock_entity(
            name="Merlin",
            status="canonical",
            content_json={"aliases": []},
        )
        with patch.object(
            EntityContextService, "_repo", new_callable=MagicMock
        ) as mock_repo:
            mock_repo.get_by_novel = AsyncMock(return_value=([ent1, ent2], 2))
            svc = EntityContextService()
            result = await svc.list_entity_terms(db, str(uuid.uuid4()))

            assert len(result) == 2
            arthur_terms = [t for t in result if t["name"] == "Arthur"][0]
            assert "Arthur" in arthur_terms["terms"]
            assert "King" in arthur_terms["terms"]
            assert "Once and Future King" in arthur_terms["terms"]


class TestEntityContextServiceFindByName:
    async def test_found_returns_entity_id_str(self) -> None:
        db = MagicMock()
        eid = str(uuid.uuid4())
        with patch.object(
            EntityContextService, "_repo", new_callable=MagicMock
        ) as mock_repo:
            mock_repo.find_entity_by_name = AsyncMock(return_value=eid)
            svc = EntityContextService()
            result = await svc.find_by_name(db, str(uuid.uuid4()), "Arthur")
            assert result == eid

    async def test_not_found_returns_none(self) -> None:
        db = MagicMock()
        with patch.object(
            EntityContextService, "_repo", new_callable=MagicMock
        ) as mock_repo:
            mock_repo.find_entity_by_name = AsyncMock(return_value=None)
            svc = EntityContextService()
            result = await svc.find_by_name(db, str(uuid.uuid4()), "Nobody")
            assert result is None
```

- [ ] **Step 4: Migrate embedding backfill tests to `EntityEmbeddingService`**

Replace `TestEntityServiceBackfillEmbeddings` with `TestEntityEmbeddingServiceBackfillEmbeddings`:

```python
class TestEntityEmbeddingServiceBackfillEmbeddings:
    """EntityEmbeddingService.backfill_embeddings — BGE client and batch logic"""

    def _make_db(self, entities: list) -> MagicMock:
        db = MagicMock()
        query_result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = entities
        query_result.scalars.return_value = scalars_mock
        db.execute = AsyncMock(return_value=query_result)
        db.flush = AsyncMock()
        return db

    async def test_no_entities_needing_backfill_returns_zero(self) -> None:
        db = self._make_db([])
        result = await EntityEmbeddingService().backfill_embeddings(db, str(uuid.uuid4()))
        assert result == 0

    @patch("modules.world.services.entity_embedding_service.BgeEmbeddingClient.get_instance")
    async def test_bge_unavailable_returns_zero(self, mock_get_instance) -> None:
        mock_get_instance.side_effect = RuntimeError("BGE not available")
        db = self._make_db([_mock_entity(name="Arthur")])
        result = await EntityEmbeddingService().backfill_embeddings(db, str(uuid.uuid4()))
        assert result == 0

    @patch("modules.world.services.entity_embedding_service.BgeEmbeddingClient.get_instance")
    async def test_happy_path_backfills_in_batches(self, mock_get_instance) -> None:
        bge = AsyncMock()
        bge.generate_embedding = AsyncMock(return_value=[[0.1], [0.2], [0.3], [0.4]])
        mock_get_instance.return_value = bge
        ents = [_mock_entity(name=f"E{i}") for i in range(4)]
        db = self._make_db(ents)

        result = await EntityEmbeddingService().backfill_embeddings(
            db, str(uuid.uuid4()), batch_size=4
        )

        assert result == 4
        for e, expected_val in zip(ents, [0.1, 0.2, 0.3, 0.4]):
            assert e.embedding == [expected_val]
            assert e.embedding_text == e.name

    @patch("modules.world.services.entity_embedding_service.BgeEmbeddingClient.get_instance")
    async def test_skips_empty_name_entities(self, mock_get_instance) -> None:
        bge = AsyncMock()
        bge.generate_embedding = AsyncMock(return_value=[[0.5]])
        mock_get_instance.return_value = bge
        valid = _mock_entity(name="E1")
        empty = _mock_entity(name="")
        db = self._make_db([valid, empty])

        result = await EntityEmbeddingService().backfill_embeddings(
            db, str(uuid.uuid4()), batch_size=8
        )

        assert result == 1
        assert valid.embedding == [0.5]

    @patch("modules.world.services.entity_embedding_service.BgeEmbeddingClient.get_instance")
    async def test_batch_failure_continues_to_next_batch(self, mock_get_instance) -> None:
        bge = AsyncMock()
        bge.generate_embedding = AsyncMock(
            side_effect=[
                RuntimeError("API error"),
                [[0.9], [1.0]],
            ]
        )
        mock_get_instance.return_value = bge
        ents = [_mock_entity(name=f"E{i}") for i in range(4)]
        db = self._make_db(ents)

        result = await EntityEmbeddingService().backfill_embeddings(
            db, str(uuid.uuid4()), batch_size=2
        )

        assert result == 2
```

- [ ] **Step 5: Remove obsolete `TestEntityServiceList` tests from `test_world_extra.py`**

`WorldEntityService.list` is unchanged; keep `TestEntityServiceList` if it still tests `WorldEntityService.list`. The `TestEntityServiceList` class already tests `WorldEntityService.list` correctly; leave it as-is.

- [ ] **Step 6: Run updated unit tests**

Run:
```bash
cd backend && python -m pytest tests/unit/test_world_extra.py -v
```
Expected: all tests pass

- [ ] **Step 7: Commit**

```bash
git add backend/tests/unit/test_world_extra.py
git commit -m "test(world): migrate context/embedding tests to new services"
```

---

### Task 9: Full World Module Test Run

**Files:**
- All modified files

- [ ] **Step 1: Run all world tests**

Run:
```bash
cd backend && python -m pytest modules/world/tests/ tests/unit/test_world_extra.py -v
```
Expected: all pass

- [ ] **Step 2: Run lint and format checks**

Run:
```bash
cd backend && ruff check modules/world/services/entity_*.py modules/world/entity_facade.py modules/world/api.py modules/world/tests/test_entity_*.py tests/unit/test_world_extra.py
```
Expected: no errors

Run:
```bash
cd backend && ruff format --check modules/world/services/entity_*.py modules/world/entity_facade.py modules/world/api.py modules/world/tests/test_entity_*.py tests/unit/test_world_extra.py
```
Expected: no changes needed (or run `ruff format` to fix)

- [ ] **Step 3: Commit if lint/format changes were applied**

```bash
git add -u
git commit -m "style(world): apply ruff format/lint after entity service decomposition"
```

---

### Task 10: Update Module Documentation

**Files:**
- Modify: `backend/modules/world/README.md`
- Modify: `backend/modules/world/CLAUDE.md` (if needed)

- [ ] **Step 1: Update README service list**

In `backend/modules/world/README.md`, locate the "职责" section and update to include new services:

```markdown
## 职责

- 世界对象 CRUD（CoreEntity / `WorldEntityService`）
- 对象关系管理（EntityRelation）
- 别名管理（`EntityAliasService`，内联于 CoreEntity.aliases JSONB）
- 对象去重（EntityDedupService）
- 世界上下文/检索词典/批次（`EntityContextService`）
- 实体 embedding 回填（`EntityEmbeddingService`）
- 向其他模块提供世界上下文（`get_world_context`）
- 人物档案与知识边界（Character / CharacterKnowledge）
```

- [ ] **Step 2: Update README Facade section if necessary**

Facade signatures are unchanged; no update needed.

- [ ] **Step 3: Commit**

```bash
git add backend/modules/world/README.md
git commit -m "docs(world): document new entity services in module README"
```

---

## Self-Review

**1. Spec coverage:** Architecture review candidate 3 required:
- 拆出 `EntityAliasService` → Task 1 ✓
- 拆出 `EntityEmbeddingService` → Task 2 ✓
- 拆出 `EntityContextService` → Task 3 ✓
- `WorldEntityService` 只保留 core CRUD + 去重校验 → Task 4 ✓
- project 配置不再泄露到 entity service 内部 → `get_project_context` 调用 moved to `EntityContextService` ✓

**2. Placeholder scan:** No TBD/TODO; every step contains actual code and exact commands.

**3. Type consistency:**
- `EntityAliasService.__init__` accepts optional `CoreEntityRepository`.
- `EntityContextService.__init__` accepts optional `CoreEntityRepository`.
- `EntityEmbeddingService.backfill_embeddings` signature matches facade/API usage.
- `_entity_to_context` moved from `entity_service.py` to `entity_context_service.py`; imports updated in tests.

**4. Gap check:**
- `api.py` still imports `EntityAliasCreate`, `EntityContextService` unused beyond batches; verify no dead imports remain after Task 7.
- `entity_facade.py` `count_entities` and `list_auto_ingested_entities` are out of scope for candidate 3 (they belong to candidate 4) and are left untouched.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-06-13-world-entity-service-decomposition.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - Dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
