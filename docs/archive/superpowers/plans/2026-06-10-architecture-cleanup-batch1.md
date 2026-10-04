# Architecture Cleanup Batch 1 — 删除浅层 Facade + 提取 ListResponse Helper

> **For agentic workers:** Use superpowers:subagent-driven-development or inline execution. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 删除 `outline/facade.py` 和 `memory/facade.py` 两个纯仪式层，让 API 直接调用 Service；提取通用的 `ListResponse` 包装 helper 消除重复代码。

**Architecture:** 对于纯 CRUD、无跨模块编排的模块， facade 的 interface 复杂度几乎等于 implementation 复杂度，是多余的 indirection。删除后 API → Service 直接调用，代码路径缩短一层。`ListResponse` 包装在 service 层统一处理（CrudService 子类添加 `list_response` ClassVar）。

**Tech Stack:** Python 3.13, FastAPI, async SQLAlchemy, pytest

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `backend/core/crud.py` | Modify | Add `list_response` ClassVar + `list_with_response()` method to `CrudService` |
| `backend/modules/outline/facade.py` | **Delete** | Pure pass-through layer (135 lines) |
| `backend/modules/outline/api.py` | Modify | Import from `services` directly; use `list_with_response()` |
| `backend/modules/outline/tasks.py` | Modify | Import `PlotStructureGenerator` from `services` directly |
| `backend/modules/outline/services.py` | Modify | Add `list_response` ClassVar to both services |
| `backend/modules/memory/facade.py` | **Delete** | Pure pass-through layer (107 lines) |
| `backend/modules/memory/api.py` | Modify | Uniformly use `_service` for all endpoints; add list-response wrapper in API or service |
| `backend/modules/memory/services.py` | Modify | Return `EventListResponse` / `SnapshotListResponse` directly from list methods |
| `backend/modules/imports/workflow.py` | Modify | Local import from `outline.services.PlotStructureGenerator` instead of facade |
| `backend/modules/writing/tasks.py` | Modify | Local import from `memory.services.MemoryService` instead of facade |
| `backend/modules/context/services/loaders/outline_arc_loader.py` | Modify | Local import from `outline.services.OutlineArcService` |
| `backend/modules/context/services/loaders/plot_threads_loader.py` | Modify | Local import from `outline.services.PlotThreadService` |
| `backend/modules/context/services/loaders/memory_records_loader.py` | Modify | Local import from `memory.services.MemoryService` |
| `backend/tests/e2e/test_outline_generation.py` | Modify | Import from `outline.services` / `outline.schemas` |
| `backend/tests/integration/test_memory_facade.py` | Rename + Modify | Rename to `test_memory_service.py`, import from `memory.services` |

---

## Phase 1: Extract ListResponse helper in CrudService

### Task 1.1: Add `list_response` ClassVar to CrudService

**Files:**
- Modify: `backend/core/crud.py`

**Context:** `CrudService.list()` currently returns `tuple[list[ResponseT], int]`. Every consumer wraps this into a `*ListResponse` Pydantic model. We add an optional `list_response` ClassVar so subclasses can opt into returning the ListResponse directly.

- [ ] **Step 1: Modify `CrudService` in `core/crud.py`**

```python
class CrudService[ModelT, CreateT, UpdateT, ResponseT]:
    repo: _CrudRepo
    response: ClassVar[type[BaseModel]]
    list_response: ClassVar[type[BaseModel] | None] = None  # NEW
    label: ClassVar[str]
    id_param: ClassVar[str] = "id"

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for attr in ("repo", "response", "label"):
            ...  # existing guard unchanged
        # list_response is optional — no guard needed
```

Add method after existing `list()`:

```python
    async def list_with_response(
        self, db: AsyncSession, novel_id: str, *,
        skip: int = 0, limit: int = DEFAULT_PAGE_SIZE,
    ) -> BaseModel:
        """Like `list()`, but wraps result in `list_response` if configured."""
        items, total = await self.list(db, novel_id, skip=skip, limit=limit)
        if self.list_response is None:
            raise TypeError(
                f"{self.__class__.__name__}.list_response is not set"
            )
        return self.list_response(items=items, total=total)  # type: ignore[return-value]
```

- [ ] **Step 2: Verify no test regressions in core**

Run: `pytest backend/tests/unit/test_crud.py -v` (or `pytest backend/tests -k crud -v`)
Expected: PASS

---

## Phase 2: Remove Outline Facade

### Task 2.1: Update Outline Services to set `list_response`

**Files:**
- Modify: `backend/modules/outline/services.py`

- [ ] **Step 1: Add imports and ClassVar**

At the top of `services.py`, add to existing imports:

```python
from modules.outline.schemas import (
    OutlineArcCreate,
    OutlineArcResponse,
    OutlineArcUpdate,
    OutlineArcListResponse,      # ADD
    PlotThreadCreate,
    PlotThreadResponse,
    PlotThreadUpdate,
    PlotThreadListResponse,      # ADD
)
```

Add `list_response` to `PlotThreadService`:

```python
class PlotThreadService(CrudService[PlotThread, PlotThreadCreate, PlotThreadUpdate, PlotThreadResponse]):
    repo = PlotThreadRepository()
    response = PlotThreadResponse
    list_response = PlotThreadListResponse   # ADD
    label = "PlotThread"
    id_param = "thread_id"
```

Add `list_response` to `OutlineArcService`:

```python
class OutlineArcService(CrudService[OutlineArc, OutlineArcCreate, OutlineArcUpdate, OutlineArcResponse]):
    repo = OutlineArcRepository()
    response = OutlineArcResponse
    list_response = OutlineArcListResponse   # ADD
    label = "OutlineArc"
    id_param = "arc_id"
```

- [ ] **Step 2: Run outline service tests**

Run: `pytest backend/tests -k outline -v`
Expected: PASS

---

### Task 2.2: Update Outline API to call Services directly

**Files:**
- Modify: `backend/modules/outline/api.py`

- [ ] **Step 1: Replace imports and facade calls with service calls**

Replace the entire file content:

```python
from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi import status as http_status

from core.dependencies import DbSession
from modules.outline.schemas import (
    OutlineArcCreate,
    OutlineArcListResponse,
    OutlineArcResponse,
    OutlineArcUpdate,
    PlotThreadCreate,
    PlotThreadListResponse,
    PlotThreadResponse,
    PlotThreadUpdate,
)
from modules.outline.services import (
    OutlineArcService,
    PlotStructureGenerator,
    PlotThreadService,
)
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

router = APIRouter(prefix="/api/outline", tags=["outline"])

_thread_service = PlotThreadService()
_arc_service = OutlineArcService()
_generator = PlotStructureGenerator()


# ============================================================
# PlotThreads
# ============================================================

@router.post("/threads", response_model=PlotThreadResponse, status_code=http_status.HTTP_201_CREATED)
async def api_create_thread(
    data: PlotThreadCreate,
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
):
    return await _thread_service.create(db, novel_id, data)


@router.get("/threads", response_model=PlotThreadListResponse)
async def api_list_threads(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
):
    return await _thread_service.list_with_response(db, novel_id, skip=skip, limit=limit)


@router.get("/threads/{thread_id}", response_model=PlotThreadResponse)
async def api_get_thread(
    thread_id: str,
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
):
    return await _thread_service.get(db, thread_id, novel_id=novel_id)


@router.patch("/threads/{thread_id}", response_model=PlotThreadResponse)
async def api_update_thread(
    thread_id: str,
    data: PlotThreadUpdate,
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
):
    return await _thread_service.update(db, thread_id, data, novel_id=novel_id)


@router.delete("/threads/{thread_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def api_delete_thread(
    thread_id: str,
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
):
    await _thread_service.delete(db, thread_id, novel_id=novel_id)


# ============================================================
# OutlineArcs
# ============================================================

@router.post("/arcs", response_model=OutlineArcResponse, status_code=http_status.HTTP_201_CREATED)
async def api_create_arc(
    data: OutlineArcCreate,
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
):
    return await _arc_service.create(db, novel_id, data)


@router.get("/arcs", response_model=OutlineArcListResponse)
async def api_list_arcs(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
):
    return await _arc_service.list_with_response(db, novel_id, skip=skip, limit=limit)


@router.get("/arcs/{arc_id}", response_model=OutlineArcResponse)
async def api_get_arc(
    arc_id: str,
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
):
    return await _arc_service.get(db, arc_id, novel_id=novel_id)


@router.patch("/arcs/{arc_id}", response_model=OutlineArcResponse)
async def api_update_arc(
    arc_id: str,
    data: OutlineArcUpdate,
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
):
    return await _arc_service.update(db, arc_id, data, novel_id=novel_id)


@router.delete("/arcs/{arc_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def api_delete_arc(
    arc_id: str,
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
):
    await _arc_service.delete(db, arc_id, novel_id=novel_id)


# ============================================================
# AI Generation
# ============================================================

@router.post("/generate", status_code=http_status.HTTP_201_CREATED)
async def api_generate_plot_structure(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    start_chapter: int = Query(1, ge=1, description="起始章节"),
    end_chapter: int = Query(10, ge=1, description="结束章节"),
):
    result = await _generator.generate(db, novel_id, start_chapter, end_chapter)
    return result
```

- [ ] **Step 2: Run outline API tests**

Run: `pytest backend/tests -k outline -v`
Expected: PASS

---

### Task 2.3: Update Outline Tasks to call Service directly

**Files:**
- Modify: `backend/modules/outline/tasks.py`

- [ ] **Step 1: Replace facade import with service import**

```python
from __future__ import annotations

import logging

from infrastructure.tasks.registry import task_handler
from modules.outline.services import PlotStructureGenerator

logger = logging.getLogger(__name__)

_generator = PlotStructureGenerator()


@task_handler("plot_structure_generate")
async def handle_plot_structure_generate(db, task):
    meta = task.meta or {}
    novel_id = meta.get("novel_id", "")
    start_chapter = int(meta.get("start_chapter", 1))
    end_chapter = int(meta.get("end_chapter", 10))

    if not novel_id:
        raise ValueError("novel_id is required for plot_structure_generate")

    result = await _generator.generate(
        db,
        novel_id=novel_id,
        start_chapter=start_chapter,
        end_chapter=end_chapter,
    )

    logger.info(
        "Plot structure generation complete: %d threads, %d arcs",
        result["total_threads"],
        result["total_arcs"],
    )

    return result
```

---

### Task 2.4: Update Cross-Module Callers (Context Loaders + Imports Workflow)

**Files:**
- Modify: `backend/modules/context/services/loaders/outline_arc_loader.py`
- Modify: `backend/modules/context/services/loaders/plot_threads_loader.py`
- Modify: `backend/modules/imports/workflow.py`

- [ ] **Step 1: Update `outline_arc_loader.py`**

```python
    async def load(...):
        from modules.outline.services import OutlineArcService

        chapter = options.chapter_index
        if chapter is None:
            return

        arc = await OutlineArcService().get_by_chapter(db, options.novel_id, chapter)
        ...  # rest unchanged
```

- [ ] **Step 2: Update `plot_threads_loader.py`**

```python
    async def load(...):
        from modules.outline.services import PlotThreadService

        chapter = options.chapter_index or 1
        threads = await PlotThreadService().get_active(db, options.novel_id, chapter)
        ...  # rest unchanged
```

- [ ] **Step 3: Update `imports/workflow.py`**

Change line 150 from:
```python
        from modules.outline.facade import generate_plot_structure
```
to:
```python
        from modules.outline.services import PlotStructureGenerator
        _generator = PlotStructureGenerator()
```

And change the call from:
```python
        result = await generate_plot_structure(...)
```
to:
```python
        result = await _generator.generate(...)
```

- [ ] **Step 4: Run context loader and imports tests**

Run: `pytest backend/tests -k "context or imports" -v`
Expected: PASS

---

### Task 2.5: Update Tests and Delete Outline Facade

**Files:**
- Modify: `backend/tests/e2e/test_outline_generation.py`
- **Delete**: `backend/modules/outline/facade.py`

- [ ] **Step 1: Update test imports**

In `test_outline_generation.py`, replace facade imports with service imports. For `list_threads`, `list_arcs` — these were facade functions that did `items, total = service.list(); return ListResponse(...)`. Now they need to call `service.list()` directly or `list_with_response()`.

Look at each usage and adapt:
- If the test needs `items, total`, call `service.list()` directly
- If the test needs the response object, call `list_with_response()`

- [ ] **Step 2: Delete `backend/modules/outline/facade.py`**

- [ ] **Step 3: Run full outline test suite**

Run: `pytest backend/tests -k outline -v`
Expected: PASS

---

## Phase 3: Remove Memory Facade

### Task 3.1: Update Memory Service to return ListResponses directly

**Files:**
- Modify: `backend/modules/memory/services.py`

- [ ] **Step 1: Modify `list_events` to return `EventListResponse` directly**

Find the `list_events` method (around line 200+). Current signature returns `tuple[list[MemoryEventResponse], int]`. Change to return `EventListResponse`.

Also modify `get_entity_timeline` and `list_snapshots` similarly.

The exact line numbers will be confirmed during editing. The pattern is:

```python
    async def list_events(
        self, db: AsyncSession, novel_id: str,
        from_chapter: int, to_chapter: int,
    ) -> EventListResponse:
        nid = parse_uuid(novel_id)
        events, total = await self._event_repo.get_by_chapter_range(
            db, nid, from_chapter, to_chapter,
        )
        return EventListResponse(
            items=[MemoryEventResponse.model_validate(e) for e in events],
            total=total,
        )
```

Same for `get_entity_timeline` → `EventListResponse` and `list_snapshots` → `SnapshotListResponse`.

- [ ] **Step 2: Run memory service tests**

Run: `pytest backend/tests/integration/test_memory_facade.py -v`
Expected: PASS (with updated imports)

---

### Task 3.2: Update Memory API to uniformly use Service

**Files:**
- Modify: `backend/modules/memory/api.py`

- [ ] **Step 1: Replace all `_memory_facade` usage with `_service`**

The current `memory/api.py` already uses `_service` for some endpoints and `_memory_facade` for others. Uniformly use `_service`:

```python
@router.get("/events", response_model=EventListResponse)
async def list_events(...):
    return await _service.list_events(db, novel_id, from_chapter, to_chapter)

@router.get("/events/{entity_id}/timeline", response_model=EventListResponse)
async def get_entity_timeline(...):
    return await _service.get_entity_timeline(db, novel_id, entity_id, skip, limit)

@router.get("/snapshots", response_model=SnapshotListResponse)
async def list_snapshots(...):
    return await _service.list_snapshots(db, novel_id)
```

Remove the `import modules.memory.facade as _memory_facade` line entirely.

- [ ] **Step 2: Run memory API tests**

Run: `pytest backend/tests -k memory -v`
Expected: PASS

---

### Task 3.3: Update Cross-Module Callers

**Files:**
- Modify: `backend/modules/writing/tasks.py`
- Modify: `backend/modules/context/services/loaders/memory_records_loader.py`

- [ ] **Step 1: Update `writing/tasks.py`**

Change the local import from:
```python
            from modules.memory.facade import capture_snapshot
            snap = await capture_snapshot(db, novel_id, chapter_index)
```
to:
```python
            from modules.memory.services import MemoryService
            _memory = MemoryService()
            snap = await _memory.capture_snapshot(db, novel_id, chapter_index)
```

- [ ] **Step 2: Update `memory_records_loader.py`**

Change:
```python
        from modules.memory.facade import get_chapter_panorama
        panorama = await get_chapter_panorama(...)
```
to:
```python
        from modules.memory.services import MemoryService
        _memory = MemoryService()
        panorama = await _memory.get_panorama(...)
```

- [ ] **Step 3: Run writing and context loader tests**

Run: `pytest backend/tests -k "writing or context" -v`
Expected: PASS

---

### Task 3.4: Update Tests and Delete Memory Facade

**Files:**
- Rename + Modify: `backend/tests/integration/test_memory_facade.py` → `test_memory_service.py`
- **Delete**: `backend/modules/memory/facade.py`

- [ ] **Step 1: Rename test file and update imports**

Replace all facade imports with service imports:
```python
from modules.memory.services import MemoryService
```

Replace function calls like `record_events(db, ...)` with `_service = MemoryService(); await _service.record_events(db, ...)`.

- [ ] **Step 2: Delete `backend/modules/memory/facade.py`**

- [ ] **Step 3: Run full memory test suite**

Run: `pytest backend/tests -k memory -v`
Expected: PASS

---

## Phase 4: Verify Batch 1

### Task 4.1: Run all backend tests

- [ ] **Step 1: Run full test suite**

Run: `cd backend && pytest tests/ -x --tb=short`
Expected: All PASS

- [ ] **Step 2: Run lint**

Run: `cd backend && ruff check .`
Expected: Clean (or only pre-existing issues)

---

## Spec Coverage Check

| Review Issue | Covered in Plan | Task |
|-------------|-----------------|------|
| #2 Outline Facade 浅层 | ✅ Yes | Task 2.1–2.5 |
| #3 Memory Facade 100% 透传 | ✅ Yes | Task 3.1–3.4 |
| #6 ListResponse 包装重复 | ✅ Yes | Task 1.1, 2.1, 3.1 |
| #1 Project 单体化 | ❌ No | Deferred to Batch 2 |
| #4 Context Compiler 隐藏依赖 | ❌ No | Deferred to Batch 2 |
| #5 循环依赖群 | ❌ No | Deferred to Batch 2 |

## Placeholder Scan

- No "TBD", "TODO", "implement later" in plan.
- All code blocks show actual content.
- All file paths are exact.
- Type names consistent across tasks.
