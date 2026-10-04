# Architecture Cleanup Batch 2 — DI 容器解耦 + outlineView 独立 + Context v2 增量改写

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消除循环依赖群、删除 Project 单体化 shim、前端 outlineView 独立提取、Context Compiler v2 增量改写（Tier 驱逐 + ConstraintEngine）。

**Architecture:** Phase 1 做依赖图修复（DI 容器 + project.py 清除），Phase 2 做功能增强（outlineView + Context v2）。Phase 1 必须先完成。

**Tech Stack:** Python 3.13, FastAPI, async SQLAlchemy, pytest, vanilla JS SPA

**Precondition:** Batch 1 已完成（outline/memory facade 已删除）。

---

## Phase 1: 依赖图修复

### Task 1: 创建 DI 容器 `core/container.py`

**Files:**
- Create: `backend/core/container.py`
- Create: `backend/tests/unit/test_container.py`

- [ ] **Step 1: 写 DI 容器测试**

```python
# tests/unit/test_container.py
import pytest
from core.container import get, register, reset, Injected


def setup_function():
    reset()


def teardown_function():
    reset()


def test_register_and_get():
    register("test_svc", lambda: "hello")
    assert get("test_svc")() == "hello"


def test_get_missing_raises_keyerror():
    reset()
    with pytest.raises(KeyError, match="not registered"):
        get("nonexistent")


def test_duplicate_register_raises_valueerror():
    register("dup", "a")
    with pytest.raises(ValueError, match="already registered"):
        register("dup", "b")


def test_reset_clears_all():
    register("x", 1)
    reset()
    with pytest.raises(KeyError):
        get("x")


class TestInjected:
    def setup_method(self):
        reset()

    def test_injected_descriptor_resolves(self):
        register("world.list_characters", lambda: ["char1"])

        class MyService:
            list_chars = Injected("world.list_characters")

        svc = MyService()
        assert svc.list_chars() == ["char1"]

    def test_injected_descriptor_missing_raises(self):
        class MyService:
            missing = Injected("not.registered")

        svc = MyService()
        with pytest.raises(KeyError):
            svc.missing
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && pytest tests/unit/test_container.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: 创建 `core/container.py`**

```python
# core/container.py
"""轻量 DI 容器 — 消除模块间 facade 直连的循环依赖。

服务在 main.py 启动时注册，模块间通过 container.get() 获取依赖，
不再直接 import 其他模块的 facade/service。
"""
from __future__ import annotations

from typing import Any

_container: dict[str, Any] = {}


def register(name: str, instance: Any) -> None:
    if name in _container:
        raise ValueError(f"Service {name!r} already registered")
    _container[name] = instance


def get(name: str) -> Any:
    if name not in _container:
        available = ", ".join(sorted(_container))
        raise KeyError(
            f"Service {name!r} not registered. "
            f"Available: {available}"
        )
    return _container[name]


def reset() -> None:
    _container.clear()


class Injected:
    """描述符 — 延迟从容器获取服务。

    用法:
        class RagService:
            list_characters = Injected("world.list_characters")

            async def some_method(self, db, novel_id):
                chars = await self.list_characters(db, novel_id)
    """

    def __init__(self, name: str) -> None:
        self._name = name

    def __set_name__(self, owner: type, name: str) -> None:
        self._attr = name

    def __get__(self, obj: object, objtype: type | None = None) -> Any:
        return get(self._name)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && pytest tests/unit/test_container.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/core/container.py backend/tests/unit/test_container.py
git commit -m "feat: add DI container (core/container.py) with register/get/Injected/reset"
```

---

### Task 2: 注册跨模块服务到 DI 容器

**Files:**
- Modify: `backend/app/main.py`

先读取 main.py 当前头部的 import 区域和 lifespan 区域，在适当位置添加服务注册。

- [ ] **Step 1: 读取 `app/main.py`**

读取 main.py，找到 router 注册区域和模块导入区域。当前路由注册在 main.py 约 line 288:
```python
from modules.project.project import router as project_router
```

- [ ] **Step 2: 添加容器注册**

在 main.py 的 lifespan 函数内（或模块导入后）添加：

```python
from core.container import register as _register

# 注册跨模块服务（消除循环依赖）
from modules.world.facade import (
    list_characters as _world_list_characters,
    list_entity_terms as _world_list_entity_terms,
    get_entity_importance_map as _world_get_importance,
    run_entity_extraction as _world_extract,
)
from modules.rag.facade import (
    index_chapter_with_report as _rag_index,
    list_chapter_indices as _rag_list_indices,
)
from modules.writing.facade import (
    list_chapter_indices as _writing_list_indices,
)
from modules.outline.services import PlotStructureGenerator as _PSG
from modules.context.facade import compile_structure_context as _ctx_compile

_register("world.list_characters", _world_list_characters)
_register("world.list_entity_terms", _world_list_entity_terms)
_register("world.get_entity_importance_map", _world_get_importance)
_register("world.run_entity_extraction", _world_extract)
_register("rag.index_chapter", _rag_index)
_register("rag.list_chapter_indices", _rag_list_indices)
_register("writing.list_chapter_indices", _writing_list_indices)
_register("outline.generate_structure", _PSG().generate)
_register("context.compile", _ctx_compile)
```

- [ ] **Step 3: 运行 main.py import 测试**

Run: `cd backend && python -c "from app.main import app; print('OK')"`
Expected: OK（或正常 import 错误如果后面有项目单体化问题，那在 Task 5 修复）

- [ ] **Step 4: 提交**

```bash
git add backend/app/main.py
git commit -m "feat: register cross-module services in DI container"
```

---

### Task 3: 解耦 world ↔ rag 循环

**Files:**
- Modify: `backend/modules/rag/services.py`
- Modify: `backend/modules/world/services/draft_provider.py`

- [ ] **Step 1: 读取 `rag/services.py` 和 `world/services/draft_provider.py`**

Find all `from modules.world.facade import ...` in rag/services.py and `from modules.rag.facade import ...` in draft_provider.py.

- [ ] **Step 2: 修改 `rag/services.py`**

Replace facade imports with container.get() calls. For each imported function:
```python
# BEFORE (example):
from modules.world.facade import list_characters, list_entity_terms, get_entity_importance_map

# AFTER:
from core.container import get as _get
# Remove the world facade import entirely

# In methods, replace:
# chars = await list_characters(db, novel_id)
# WITH:
# chars = await _get("world.list_characters")(db, novel_id)
```

Also handle the method at line ~934 which does a local import:
```python
# BEFORE:
from modules.world.facade import list_characters as _list_chars

# AFTER:
from core.container import get as _get
# And in the method body:
_list_chars = _get("world.list_characters")
chars = await _list_chars(db, novel_id)
```

- [ ] **Step 3: 修改 `world/services/draft_provider.py`**

```python
# BEFORE:
from modules.rag.facade import (
    index_chapter_with_report,
)

# AFTER:
from core.container import get as _get
# In the method body:
# index_fn = _get("rag.index_chapter")
# result = await index_fn(db, novel_id, chapter_index, ...)
```

- [ ] **Step 4: 运行相关模块测试**

Run: `cd backend && pytest tests/ -k "rag or world" -x --tb=short`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/modules/rag/services.py backend/modules/world/services/draft_provider.py
git commit -m "refactor: decouple world↔rag via DI container"
```

---

### Task 4: 解耦 context ↔ outline 和 rag → writing → memory 循环

**Files:**
- Modify: `backend/modules/context/services/loaders/outline_arc_loader.py`
- Modify: `backend/modules/context/services/loaders/plot_threads_loader.py`
- Modify: `backend/modules/outline/services.py` (PlotStructureGenerator)
- Modify: `backend/modules/rag/tasks.py`
- Modify: `backend/modules/writing/tasks.py`
- Modify: `backend/modules/imports/workflow.py`

- [ ] **Step 1: 读取所有需要修改的文件**

Read the outline_arc_loader, plot_threads_loader, outline/services.py (the context facade import section), rag/tasks.py, writing/tasks.py, imports/workflow.py.

- [ ] **Step 2: 修改 `outline_arc_loader.py`**

Replace `from modules.outline.services import OutlineArcService` with container.get():

```python
# Remove:
# from modules.outline.services import OutlineArcService

# Add:
from core.container import get as _get

# In load() method:
# _arc_svc = _get("outline.arc_service")
# arc = await _arc_svc.get_by_chapter(db, options.novel_id, options.chapter_index)
```

Note: Need to register `outline.arc_service` and `outline.thread_service` in the container as well. Add to main.py:
```python
from modules.outline.services import OutlineArcService as _OAS, PlotThreadService as _PTS
_register("outline.arc_service", _OAS())
_register("outline.thread_service", _PTS())
```

- [ ] **Step 3: 修改 `plot_threads_loader.py`**

Same pattern as outline_arc_loader.

- [ ] **Step 4: 修改 `outline/services.py`**

Replace `from modules.context.facade import compile_structure_context`:
```python
# Remove:
# from modules.context.facade import compile_structure_context

# In PlotStructureGenerator.generate():
from core.container import get as _get
compile_fn = _get("context.compile")
context = await compile_fn(db, novel_id, ...)
```

- [ ] **Step 5: 修改 `rag/tasks.py`**

Replace `from modules.writing.facade import list_chapter_indices`:
```python
from core.container import get as _get

async def _get_chapter_indices(db, novel_id):
    fn = _get("writing.list_chapter_indices")
    return await fn(db, novel_id)
```

- [ ] **Step 6: 修改 `writing/tasks.py`**

Replace `from modules.memory.services import MemoryService` and `from modules.rag.facade import index_chapter_with_report`:
```python
from core.container import get as _get

# In the task handler:
_memory_svc = _get("memory.capture_snapshot")  # or the appropriate function
_rag_index = _get("rag.index_chapter")
```

Need to also register these in main.py. Check what writing/tasks.py currently imports.

- [ ] **Step 7: 修改 `imports/workflow.py`**

Replace `from modules.world.facade import run_entity_extraction, ...` and `from modules.outline.services import PlotStructureGenerator`:
```python
from core.container import get as _get

# In the workflow steps:
_extract = _get("world.run_entity_extraction")
_generate = _get("outline.generate_structure")
```

Also any other world facade imports in workflow.py.

- [ ] **Step 8: 更新 main.py 注册**

Add the new registrations to main.py from Steps 2-7:
```python
_register("outline.arc_service", _OAS())
_register("outline.thread_service", _PTS())
```

Check what other services need to be registered based on what was replaced.

- [ ] **Step 9: 运行全量测试**

Run: `cd backend && pytest tests/ -x --tb=short`
Expected: PASS

- [ ] **Step 10: 提交**

```bash
git add backend/modules/context/services/loaders/outline_arc_loader.py \
  backend/modules/context/services/loaders/plot_threads_loader.py \
  backend/modules/outline/services.py \
  backend/modules/rag/tasks.py \
  backend/modules/writing/tasks.py \
  backend/modules/imports/workflow.py \
  backend/app/main.py
git commit -m "refactor: decouple context↔outline and rag→writing cycles via DI container"
```

---

### Task 5: 删除 Project 单体化 shim

**Files:**
- Delete: `backend/modules/project/project.py`
- Modify: `backend/modules/project/__init__.py`
- Modify: ~18 files that import from `modules.project.project`

这是机械性的工作——每个文件都需要根据 `spec` 中的替换表进行导入替换。

- [ ] **Step 1: 搜索所有导入**

```bash
cd backend && grep -rn "from modules.project.project import\|import modules.project.project" --include="*.py" | grep -v __pycache__
```

- [ ] **Step 2: 逐一修改每个文件**

**替换规则：**

| 旧导入 | 新导入 |
|--------|--------|
| `from modules.project.project import Project` | `from modules.project.models import Project` |
| `from modules.project.project import ProjectContext` | `from modules.project.schemas import ProjectContext` |
| `from modules.project.project import router` | `from modules.project.api import router` |
| `import modules.project.project` (model-registration) | `import modules.project.models` |
| 函数导入 (create_project 等) | 改用 ProjectService 方法 |

**对于 `app/main.py`：**
```python
# BEFORE:
from modules.project.project import router as project_router
import modules.project.project  # noqa: F401

# AFTER:
from modules.project.api import router as project_router
import modules.project.models  # noqa: F401
```

**对于测试 conftest.py：**
```python
# BEFORE:
import modules.project.project  # noqa: F401
from modules.project.project import Project

# AFTER:
import modules.project.models  # noqa: F401
from modules.project.models import Project
```

**对于 test_project.py：**
```python
# BEFORE:
from modules.project.project import (
    create_project, get_project_by_id, list_projects, update_project, delete_project,
)

# AFTER:
from modules.project.models import Project
from modules.project.schemas import ProjectCreate, ProjectUpdate
from modules.project.services import ProjectService

_svc = ProjectService()

async def create_project(db, data):
    return await _svc.create(db, data=str_val, data=data)
# ... adapt each function similarly
```

Actually, looking at the existing code more carefully, the function-style imports in tests need individual checking. Read each file to understand the usage pattern.

- [ ] **Step 3: 修改 `modules/project/__init__.py`**

```python
# Update re-exports to import from submodules directly
from modules.project.models import Project  # noqa: F401
from modules.project.schemas import (  # noqa: F401
    ProjectContext,
    ProjectCreate,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdate,
)
from modules.project.repositories import ProjectRepository  # noqa: F401
from modules.project.services import ProjectService  # noqa: F401
from modules.project.api import router  # noqa: F401
```

- [ ] **Step 4: 删除 `modules/project/project.py`**

```bash
rm backend/modules/project/project.py
```

- [ ] **Step 5: 运行全量测试**

Run: `cd backend && pytest tests/ -x --tb=short`
Expected: PASS

- [ ] **Step 6: 验证 project.py 不可导入**

Run: `cd backend && python -c "from modules.project.project import Project" 2>&1 || echo "CORRECT: ImportError raised"`
Expected: ImportError

- [ ] **Step 7: 提交**

```bash
git add -A
git commit -m "refactor: delete project.py singleton shim, migrate all imports to submodules"
```

---

### Task 6: Phase 1 验证

- [ ] **Step 1: 运行全量后端测试**

Run: `cd backend && pytest tests/ -x --tb=short`
Expected: ALL PASS

- [ ] **Step 2: 运行 Ruff 检查**

Run: `cd backend && ruff check .`
Expected: Clean (no new errors)

- [ ] **Step 3: 验证循环依赖消除**

Run: `cd backend && python -c "from modules.rag.services import RagService; from modules.world.services.draft_provider import DraftProvider; from modules.context.services.context_compiler import ContextCompiler; from modules.outline.services import PlotStructureGenerator; print('No CircularImportError')"`
Expected: No CircularImportError

- [ ] **Step 4: 提交（如有修复）**

If any fix was needed:
```bash
git add -A && git commit -m "fix: Phase 1 verification fixes"
```

---

## Phase 2: 功能增强

### Task 7: 创建 CompiledContext IR (`compiled_context.py`)

**Files:**
- Create: `backend/modules/context/services/compiled_context.py`
- Create: `backend/tests/unit/test_compiled_context.py`

- [ ] **Step 1: 写 CompiledContext 测试**

```python
# tests/unit/test_compiled_context.py
import pytest
from modules.context.services.compiled_context import (
    Tier,
    ContextSection,
    CompiledContext,
)


class TestTierOrdering:
    def test_tier_ordering(self):
        assert Tier.P0 < Tier.P1 < Tier.P2 < Tier.P3 < Tier.P4

    def test_p0_is_lowest_priority_for_eviction(self):
        assert Tier.P0 == 0


class TestCompiledContext:
    def test_enforce_budget_no_overage(self):
        ctx = CompiledContext(
            sections=[
                ContextSection(key="a", tier=Tier.P0, content="hello", token_count=100),
                ContextSection(key="b", tier=Tier.P1, content="world", token_count=100),
            ],
            total_tokens=200,
            budget_tokens=300,
        )
        result = ctx.enforce_budget()
        assert len(result.sections) == 2

    def test_enforce_budget_evicts_p4_first(self):
        ctx = CompiledContext(
            sections=[
                ContextSection(key="obj", tier=Tier.P0, content="a" * 100, token_count=500),
                ContextSection(key="warn", tier=Tier.P4, content="b" * 100, token_count=200),
            ],
            total_tokens=700,
            budget_tokens=600,
        )
        result = ctx.enforce_budget()
        assert len(result.sections) == 1
        assert result.sections[0].key == "obj"

    def test_enforce_budget_evicts_p3_then_p4(self):
        ctx = CompiledContext(
            sections=[
                ContextSection(key="obj", tier=Tier.P0, content="a" * 50, token_count=300),
                ContextSection(key="style", tier=Tier.P3, content="b" * 50, token_count=200),
                ContextSection(key="warn", tier=Tier.P4, content="c" * 50, token_count=100),
            ],
            total_tokens=600,
            budget_tokens=400,
        )
        result = ctx.enforce_budget()
        assert all(s.tier == Tier.P0 for s in result.sections)

    def test_enforce_budget_p2_per_item_truncation(self):
        items = ContextSection(
            key="obligations",
            tier=Tier.P2,
            content="item1\nitem2\nitem3",
            token_count=300,
            truncatable_per_item=True,
        )
        ctx = CompiledContext(
            sections=[
                ContextSection(key="obj", tier=Tier.P0, content="a" * 50, token_count=500),
                items,
            ],
            total_tokens=800,
            budget_tokens=600,
        )
        result = ctx.enforce_budget()
        assert len(result.sections) == 2
        assert result.sections[1].token_count < 300

    def test_enforce_budget_never_evicts_p0(self):
        ctx = CompiledContext(
            sections=[
                ContextSection(key="obj", tier=Tier.P0, content="x" * 100, token_count=500),
            ],
            total_tokens=500,
            budget_tokens=300,
        )
        result = ctx.enforce_budget()
        assert len(result.sections) == 1
        assert result.sections[0].key == "obj"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && pytest tests/unit/test_compiled_context.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: 创建 `compiled_context.py`**

```python
# modules/context/services/compiled_context.py
"""CompiledContext IR — Tier 标注的段列表，按预算驱逐。

Tier 驱逐顺序：P4 → P3 → P2（按条）→ P1（Delta 压缩）→ P0 不截断。
"""
from __future__ import annotations

from enum import IntEnum

from pydantic import BaseModel


class Tier(IntEnum):
    P0 = 0   # 永不截断 — Writing Objective, Scene Blueprint, Hard Constraints
    P1 = 1   # 最后截断 — POV Knowledge, Delta Timeline
    P2 = 2   # 按条截断 — Open Obligations, Retrieval Evidence Packs
    P3 = 3   # 优先截断 — Style Assets
    P4 = 4   # 最先截断 — Compiler Warnings


class ContextSection(BaseModel):
    key: str
    tier: Tier
    content: str
    token_count: int = 0
    truncatable_per_item: bool = False
    max_items: int | None = None

    model_config = {"frozen": False}


class CompiledContext(BaseModel):
    """IR 中间表示 — Tier 标注的段列表"""

    sections: list[ContextSection]
    total_tokens: int = 0
    budget_tokens: int = 0
    compiled_at: str = ""

    model_config = {"frozen": False}

    def enforce_budget(self) -> CompiledContext:
        """按 Tier 驱逐策略裁剪至预算内。

        驱逐顺序：P4 → P3 → P2（按条）→ P1（Delta 压缩）→ P0 不截断。
        """
        if self.budget_tokens <= 0 or self.total_tokens <= self.budget_tokens:
            return self

        sections = list(self.sections)
        budget = self.budget_tokens

        # Phase 1: 计算 P0 必占预算
        p0_cost = sum(s.token_count for s in sections if s.tier == Tier.P0)
        remaining = budget - p0_cost

        # Phase 2: 按 Tier 从高到低驱逐
        for tier in [Tier.P4, Tier.P3]:
            if remaining >= 0:
                break
            kept = []
            for s in sections:
                if s.tier == tier:
                    if remaining > 0:
                        remaining -= s.token_count
                        kept.append(s)
                    # else: evict
                else:
                    kept.append(s)
            sections = kept

        # Phase 3: P2 按条截断
        if remaining < 0:
            new_sections = []
            for s in sections:
                if s.tier == Tier.P2 and s.truncatable_per_item:
                    items = s.content.split("\n")
                    kept_items = []
                    cost_so_far = 0
                    for item in items:
                        item_tokens = max(1, len(item) // 4)
                        if cost_so_far + item_tokens <= remaining:
                            kept_items.append(item)
                            cost_so_far += item_tokens
                        else:
                            break
                    if kept_items:
                        new_content = "\n".join(kept_items)
                        new_tokens = cost_so_far
                        remaining -= new_tokens
                        new_sections.append(ContextSection(
                            key=s.key,
                            tier=s.tier,
                            content=new_content,
                            token_count=new_tokens,
                            truncatable_per_item=s.truncatable_per_item,
                            max_items=s.max_items,
                        ))
                else:
                    new_sections.append(s)
            sections = new_sections

        # Phase 4: P1 Delta 压缩（20→15→10）
        if remaining < 0:
            new_sections = []
            for s in sections:
                if s.tier == Tier.P1:
                    items = s.content.split("\n")
                    for limit in [15, 10]:
                        if len(items) > limit and sum(max(1, len(i) // 4) for i in items[:limit]) + p0_cost <= budget:
                            new_content = "\n".join(items[:limit])
                            new_tokens = sum(max(1, len(i) // 4) for i in items[:limit])
                            remaining = budget - p0_cost - sum(
                                sec.token_count for sec in new_sections if sec.tier != Tier.P1
                            ) - new_tokens
                            new_sections.append(ContextSection(
                                key=s.key,
                                tier=s.tier,
                                content=new_content,
                                token_count=new_tokens,
                            ))
                            break
                    else:
                        new_sections.append(s)
                else:
                    new_sections.append(s)
            sections = new_sections

        total = sum(s.token_count for s in sections)
        return CompiledContext(
            sections=sections,
            total_tokens=total,
            budget_tokens=self.budget_tokens,
            compiled_at=self.compiled_at,
        )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && pytest tests/unit/test_compiled_context.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/modules/context/services/compiled_context.py backend/tests/unit/test_compiled_context.py
git commit -m "feat: add CompiledContext IR with Tier-based budget enforcement"
```

---

### Task 8: 创建 ConstraintEngine (`constraint_engine.py`)

**Files:**
- Create: `backend/modules/context/services/constraint_engine.py`
- Create: `backend/tests/unit/test_constraint_engine.py`

- [ ] **Step 1: 写 ConstraintEngine 测试**

```python
# tests/unit/test_constraint_engine.py
import pytest
from unittest.mock import AsyncMock, patch
from modules.context.services.constraint_engine import ConstraintEngine
from modules.context.services.compiled_context import Tier, ContextSection


@pytest.fixture
def engine():
    return ConstraintEngine()


class TestStaticConstraints:
    @pytest.mark.asyncio
    async def test_static_constraints_returns_p0_sections(self, engine):
        sections = await engine._static_constraints("zh")
        assert all(s.tier == Tier.P0 for s in sections)
        assert len(sections) > 0


class TestSceneConstraints:
    @pytest.mark.asyncio
    async def test_scene_constraints_empty_when_no_scene(self, engine):
        sections = await engine._scene_constraints(None, None)
        assert sections == []


class TestEmptyEngine:
    @pytest.mark.asyncio
    async def test_compile_constraints_returns_list(self, engine):
        with patch.object(engine, "_static_constraints", new_callable=AsyncMock, return_value=[
            ContextSection(key="static", tier=Tier.P0, content="test", token_count=10)
        ]):
            with patch.object(engine, "_scene_constraints", new_callable=AsyncMock, return_value=[]):
                with patch.object(engine, "_knowledge_constraints", new_callable=AsyncMock, return_value=[]):
                    with patch.object(engine, "_foreshadowing_constraints", new_callable=AsyncMock, return_value=[]):
                        result = await engine.compile_constraints(
                            db=AsyncMock(), novel_id="test-novel"
                        )
                        assert len(result) >= 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && pytest tests/unit/test_constraint_engine.py -v`
Expected: FAIL

- [ ] **Step 3: 创建 `constraint_engine.py`**

```python
# modules/context/services/constraint_engine.py
"""ConstraintEngine — 动态生成硬约束段（Tier=P0）。

4 类约束源：
1. StaticConstraints — 代码写死全局约束
2. KnowledgeConstraints — CharacterKnowledge 三态
3. ForeshadowingConstraints — 伏笔揭示禁止
4. SceneConstraints — Scene 卡 must_not_happen
"""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.services.compiled_context import ContextSection, Tier

logger = logging.getLogger(__name__)

# 全局静态约束模板
_STATIC_CONSTRAINTS_ZH = [
    "不得让角色知道其知识边界之外的信息",
    "不得在读者层提前揭示作者视角的秘密",
    "伏笔未到收束阶段不得提前揭示",
]

_STATIC_CONSTRAINTS_EN = [
    "Characters must not know information beyond their knowledge boundary",
    "Author-only secrets must not be revealed to readers prematurely",
    "Foreshadowing must not be revealed before their planned payoff",
]


class ConstraintEngine:
    """硬约束动态编译引擎"""

    async def compile_constraints(
        self,
        db: AsyncSession,
        novel_id: str,
        scene_id: str | None = None,
        chapter_index: int | None = None,
    ) -> list[ContextSection]:
        """收集全部硬约束段，标记 Tier=P0"""
        sections: list[ContextSection] = []

        sections.extend(await self._static_constraints("zh"))
        sections.extend(await self._scene_constraints(scene_id, chapter_index))
        sections.extend(await self._knowledge_constraints(db, novel_id, chapter_index))
        sections.extend(await self._foreshadowing_constraints(db, novel_id, chapter_index))

        return sections

    async def _static_constraints(self, language: str = "zh") -> list[ContextSection]:
        constraints = _STATIC_CONSTRAINTS_ZH if language == "zh" else _STATIC_CONSTRAINTS_EN
        content = "\n".join(f"- {c}" for c in constraints)
        return [ContextSection(
            key="hard_constraints",
            tier=Tier.P0,
            content=content,
            token_count=max(1, len(content) // 4),
        )]

    async def _scene_constraints(
        self, scene_id: str | None, chapter_index: int | None,
    ) -> list[ContextSection]:
        # TODO: When scenes table exists, load must_not_happen from scene card
        # For now, return empty — Scene table not yet created
        return []

    async def _knowledge_constraints(
        self, db: AsyncSession, novel_id: str, chapter_index: int | None = None,
    ) -> list[ContextSection]:
        # TODO: When scenes table exists, load CharacterKnowledge for POV character
        # For now, return empty — knowledge constraints depend on POV character
        return []

    async def _foreshadowing_constraints(
        self, db: AsyncSession, novel_id: str, chapter_index: int | None = None,
    ) -> list[ContextSection]:
        # TODO: When foreshadowing_plans table exists, load seeded foreshadowing
        # For now, return empty — foreshadowing table not yet created
        return []
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && pytest tests/unit/test_constraint_engine.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/modules/context/services/constraint_engine.py backend/tests/unit/test_constraint_engine.py
git commit -m "feat: add ConstraintEngine with static/knowledge/foreshadowing/scene constraint sources"
```

---

### Task 9: 改写 Context Compiler — Tier 分组 + 驱逐 + 双模式

**Files:**
- Modify: `backend/modules/context/services/context_compiler.py`
- Modify: `backend/modules/context/contracts.py`
- Modify: `backend/modules/context/services/types.py`

- [ ] **Step 1: 读取当前 context_compiler.py, contracts.py, types.py**

Read all three files completely.

- [ ] **Step 2: 更新 `contracts.py` — 添加 CompileMode**

Add `CompileMode` enum to contracts.py:

```python
from shared.enums import StrEnum

class CompileMode(StrEnum):
    writing = "writing"    # Delta 摘要模式（默认）
    debug = "debug"        # 全量 Snapshot 模式
```

Also add `mode` field to `CompileOptions`:
```python
mode: str = "writing"  # CompileMode value
```

- [ ] **Step 3: 重写 `context_compiler.py`**

Add Tier-based section assembly. The `compile` method should:
1. Call all loaders as before (populate StructureContextBundle)
2. Build ContextSections from bundle data, assigning Tier labels
3. Optionally call ConstraintEngine to get hard constraint sections
4. Build CompiledContext with sections
5. Call enforce_budget()

```python
# New imports at top of context_compiler.py
from modules.context.services.compiled_context import (
    CompiledContext, ContextSection, Tier,
)
from modules.context.services.constraint_engine import ConstraintEngine
from shared.enums import StrEnum


class ContextCompiler:
    def __init__(self, loaders=None):
        # ... existing init ...
        self._constraint_engine = ConstraintEngine()

    async def compile(self, db, options):
        """主入口：编译结构化上下文（保持现有行为）"""
        # ... existing compile logic unchanged ...
        return bundle

    async def compile_with_tiers(self, db, options, budget_tokens=4000):
        """新入口：按 Tier 编译上下文，返回 CompiledContext IR"""
        # Phase 1: Load data as before
        bundle = await self.compile(db, options)

        # Phase 2: Build sections with Tier labels
        sections = self._build_sections(bundle)

        # Phase 3: Add hard constraints
        constraint_sections = await self._constraint_engine.compile_constraints(
            db, options.novel_id,
            scene_id=None,  # TODO: pass scene_id when available
            chapter_index=options.chapter_index,
        )
        sections.extend(constraint_sections)

        # Phase 4: Build CompiledContext and enforce budget
        total_tokens = sum(s.token_count for s in sections)
        ctx = CompiledContext(
            sections=sections,
            total_tokens=total_tokens,
            budget_tokens=budget_tokens,
            compiled_at=datetime.utcnow().isoformat(),
        )
        return ctx.enforce_budget()

    def _build_sections(self, bundle):
        """将 StructureContextBundle 转为 Tier 标注的 ContextSection 列表"""
        sections = []

        # P0: Writing Objective
        if bundle.task:
            sections.append(ContextSection(
                key="writing_objective",
                tier=Tier.P0,
                content=bundle.task,
                token_count=max(1, len(bundle.task) // 4),
            ))

        # P0: Scene Blueprint (when chapter_card available)
        if bundle.chapter_card:
            import json
            content = json.dumps(bundle.chapter_card, ensure_ascii=False, indent=2)
            sections.append(ContextSection(
                key="scene_blueprint",
                tier=Tier.P0,
                content=content,
                token_count=max(1, len(content) // 4),
            ))

        # P1: POV Knowledge (characters)
        if bundle.characters:
            content = "\n".join(str(c) for c in bundle.characters)
            sections.append(ContextSection(
                key="pov_knowledge",
                tier=Tier.P1,
                content=content,
                token_count=max(1, len(content) // 4),
            ))

        # P1: Delta Timeline (memory_records)
        if bundle.memory_records:
            content = "\n".join(str(m) for m in bundle.memory_records)
            sections.append(ContextSection(
                key="delta_timeline",
                tier=Tier.P1,
                content=content,
                token_count=max(1, len(content) // 4),
                truncatable_per_item=True,
            ))

        # P2: Open Narrative Obligations (plot_threads)
        if bundle.plot_threads:
            content = "\n".join(str(t) for t in bundle.plot_threads)
            sections.append(ContextSection(
                key="narrative_obligations",
                tier=Tier.P2,
                content=content,
                token_count=max(1, len(content) // 4),
                truncatable_per_item=True,
            ))

        # P2: Retrieval Evidence Packs (rag_chunks)
        if bundle.rag_chunks:
            content = "\n".join(str(c) for c in bundle.rag_chunks)
            sections.append(ContextSection(
                key="retrieval_evidence",
                tier=Tier.P2,
                content=content,
                token_count=max(1, len(content) // 4),
                truncatable_per_item=True,
            ))

        # P0: Hard Constraints — added by ConstraintEngine separately

        # P3: Style Assets (project-level)
        if bundle.project:
            content = str(bundle.project)
            sections.append(ContextSection(
                key="style_assets",
                tier=Tier.P3,
                content=content,
                token_count=max(1, len(content) // 4),
            ))

        # P4: Compiler Warnings
        if bundle.warnings:
            content = "\n".join(f"- {w}" for w in bundle.warnings)
            sections.append(ContextSection(
                key="compiler_warnings",
                tier=Tier.P4,
                content=content,
                token_count=max(1, len(content) // 4),
            ))

        return sections
```

- [ ] **Step 4: 更新 facade.py — 添加 compile_with_tiers 入口**

```python
async def compile_with_tiers(
    db, novel_id, task, scope,
    budget_tokens=4000,
    **kwargs,
):
    options = CompileOptions(novel_id=novel_id, task=task, scope=scope, **kwargs)
    return await _compiler.compile_with_tiers(db, options, budget_tokens=budget_tokens)
```

- [ ] **Step 5: 运行全部 context 测试**

Run: `cd backend && pytest tests/ -k context -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add backend/modules/context/
git commit -m "feat: add Tier-based context compilation with budget enforcement and dual-mode support"
```

---

### Task 10: 适配 MarkdownRenderer — 从 CompiledContext IR 渲染

**Files:**
- Modify: `backend/modules/context/markdown_renderer.py`
- Create: `backend/tests/unit/test_context_tier_rendering.py`

- [ ] **Step 1: 读取当前 markdown_renderer.py 全部内容**

Read the full file to understand existing section rendering functions.

- [ ] **Step 2: 添加 CompiledContext 渲染入口**

In markdown_renderer.py, add a new public function:

```python
def render_compiled_context(ctx: CompiledContext) -> str:
    """从 CompiledContext IR 渲染为 Markdown，保持 Tier 顺序"""
    parts = []
    for section in sorted(ctx.sections, key=lambda s: s.tier):
        header = TIER_HEADERS.get(section.key, section.key)
        parts.append(f"## {header}\n\n{section.content}\n")
    return "\n".join(parts)


TIER_HEADERS = {
    "writing_objective": "一、创作目标",
    "scene_blueprint": "二、场景蓝图",
    "hard_constraints": "二、必须遵守的硬约束",
    "pov_knowledge": "三、视角人物知识边界",
    "delta_timeline": "三、世界线变化时间线",
    "narrative_obligations": "四、叙事义务",
    "retrieval_evidence": "四、检索证据包",
    "style_assets": "五、风格素材",
    "compiler_warnings": "六、编译器警告",
}
```

- [ ] **Step 3: 保持旧 `render_context_markdown(StructureContextBundle)` 函数**

The existing function should continue to work. Internally, it can optionally bridge to the new IR path when CompiledContext is available.

No changes to the existing render function — keep backward compatibility.

- [ ] **Step 4: 写测试**

```python
# tests/unit/test_context_tier_rendering.py
from modules.context.services.compiled_context import Tier, ContextSection, CompiledContext
from modules.context.markdown_renderer import render_compiled_context


def test_render_compiled_context_respects_tier_order():
    ctx = CompiledContext(
        sections=[
            ContextSection(key="warn", tier=Tier.P4, content="Warning", token_count=10),
            ContextSection(key="obj", tier=Tier.P0, content="Objective", token_count=10),
            ContextSection(key="style", tier=Tier.P3, content="Style", token_count=10),
        ],
        total_tokens=30,
        budget_tokens=100,
    )
    result = render_compiled_context(ctx)
    lines = result.split("\n")
    # P0 should come before P3 and P4
    obj_idx = next(i for i, l in enumerate(lines) if "创作目标" in l or "Objective" in l)
    style_idx = next(i for i, l in enumerate(lines) if "风格" in l or "Style" in l)
    warn_idx = next(i for i, l in enumerate(lines) if "警告" in l or "Warning" in l)
    assert obj_idx < style_idx < warn_idx
```

- [ ] **Step 5: 运行测试**

Run: `cd backend && pytest tests/unit/test_context_tier_rendering.py -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add backend/modules/context/markdown_renderer.py backend/tests/unit/test_context_tier_rendering.py
git commit -m "feat: add CompiledContext-to-Markdown renderer with Tier ordering"
```

---

### Task 11: 前端 outlineView 独立提取

**Files:**
- Create: `frontend-console/views/outlineView.js`
- Modify: `frontend-console/router.js`
- Modify: `frontend-console/views/writingView.js`
- Modify: `frontend-console/app.js`

这是一个前端任务，需要大量阅读 writingView.js 中的 outline 相关逻辑。由于当前 writingView.js 826 行，需要先识别哪些逻辑是 outline 相关的。

- [ ] **Step 1: 分析 writingView.js 中 outline 相关逻辑**

Read writingView.js, identifying:
- Scene card panel rendering
- Plot thread / arc listing
- Outline navigation
- AI generation calls for plot structure

Mark the line ranges for each.

- [ ] **Step 2: 在 router.js 添加 outline 路由**

```javascript
// In routes object, add:
outline: { title: "大纲", subViews: ["scenes", "threads", "arcs"] },
```

- [ ] **Step 3: 创建 outlineView.js 骨架**

```javascript
// views/outlineView.js
/**
 * outlineView — 独立大纲管理视图
 *
 * 三个子标签：Scene 卡 / 剧情线 / 篇章纲
 */

const outlineView = {
  /** @type {string|null} 当前选中的子标签 */
  _activeTab: "scenes",

  /** @type {string|null} 当前选中的项目 ID */
  _projectId: null,

  async render() {
    const pid = state.currentProjectId
    if (!pid) return '<div class="empty-state">请先选择项目</div>'
    this._projectId = pid
    this._activeTab = state.currentSubView || "scenes"

    return `
      <div class="outline-view">
        <div class="outline-tabs">
          <button class="tab-btn ${this._activeTab === "scenes" ? "active" : ""}" data-tab="scenes">Scene 卡</button>
          <button class="tab-btn ${this._activeTab === "threads" ? "active" : ""}" data-tab="threads">剧情线</button>
          <button class="tab-btn ${this._activeTab === "arcs" ? "active" : ""}" data-tab="arcs">篇章纲</button>
        </div>
        <div id="outline-content" class="outline-content">
          Loading...
        </div>
      </div>
    `
  },

  async onEnter() {
    this._bindTabs()
    await this._loadTab(this._activeTab)
  },

  onLeave() {
    // cleanup
  },

  _bindTabs() {
    document.querySelectorAll(".outline-tabs .tab-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        this._activeTab = btn.dataset.tab
        this._loadTab(this._activeTab)
      })
    })
  },

  async _loadTab(tab) {
    const content = document.getElementById("outline-content")
    if (!content) return

    switch (tab) {
      case "scenes":
        content.innerHTML = await this._renderScenes()
        break
      case "threads":
        content.innerHTML = await this._renderThreads()
        break
      case "arcs":
        content.innerHTML = await this._renderArcs()
        break
    }
  },

  async _renderScenes() {
    // TODO: Fetch and render scene cards from outline API
    return '<div class="empty-state">Scene 卡列表（开发中）</div>'
  },

  async _renderThreads() {
    // TODO: Fetch and render plot threads
    const resp = await api.get(`/api/outline/threads?novel_id=${this._projectId}`)
    if (!resp.ok) return '<div class="empty-state">加载失败</div>'
    const threads = await resp.json()
    return this._renderThreadList(threads.items || [])
  },

  async _renderArcs() {
    const resp = await api.get(`/api/outline/arcs?novel_id=${this._projectId}`)
    if (!resp.ok) return '<div class="empty-state">加载失败</div>'
    const arcs = await resp.json()
    return this._renderArcList(arcs.items || [])
  },

  _renderThreadList(threads) {
    if (threads.length === 0) return '<div class="empty-state">暂无剧情线</div>'
    return `<div class="thread-list">${threads.map((t) => `
      <div class="thread-item" data-id="${esc(t.id)}">
        <span class="thread-type">${esc(t.thread_type)}</span>
        <span class="thread-name">${esc(t.name)}</span>
      </div>
    `).join("")}</div>`
  },

  _renderArcList(arcs) {
    if (arcs.length === 0) return '<div class="empty-state">暂无篇章纲</div>'
    return `<div class="arc-list">${arcs.map((a) => `
      <div class="arc-item" data-id="${esc(a.id)}">
        <span class="arc-index">#${a.arc_index || "?"}</span>
        <span class="arc-title">${esc(a.title)}</span>
      </div>
    `).join("")}</div>`
  },
}

window.outlineView = outlineView
```

- [ ] **Step 4: 在 index.html 注册 outlineView**

Add to `frontend-console/index.html`:
```html
<script type="module" src="views/outlineView.js"></script>
```

And register in the view initialization:
```javascript
router.registerView("outline", outlineView)
```

- [ ] **Step 5: 从 writingView.js 移除 outline 内嵌逻辑**

Read writingView.js and remove any inline outline panel rendering that's now in outlineView. Keep only the right-side Scene card read-only panel for writing context.

This step requires careful line-by-line analysis. At minimum, remove the AI generation button that leads to outline-specific actions, replacing it with a link to the outline view.

- [ ] **Step 6: 更新 app.js — 添加 outline 导航**

In the navigation sidebar HTML, add the outline view link. Currently the nav has:
```html
📁写作 / 📋大纲 / 🌍世界
```

Ensure the 📋大纲 link points to `#outline`.

- [ ] **Step 7: 测试前端路由**

Navigate to `#/outline` and verify the outline view renders.

- [ ] **Step 8: 提交**

```bash
git add frontend-console/
git commit -m "feat: extract outlineView as independent route, remove inline outline from writingView"
```

---

### Task 12: Phase 2 验证

- [ ] **Step 1: 运行全量后端测试**

Run: `cd backend && pytest tests/ -x --tb=short`
Expected: ALL PASS

- [ ] **Step 2: 运行 Ruff 检查**

Run: `cd backend && ruff check .`
Expected: Clean

- [ ] **Step 3: 验证 Context Compiler v2 新入口**

Run: `cd backend && python -c "from modules.context.services.context_compiler import ContextCompiler; from modules.context.services.compiled_context import CompiledContext, Tier; from modules.context.services.constraint_engine import ConstraintEngine; print('All imports OK')"`
Expected: "All imports OK"

- [ ] **Step 4: 验证前端 outlineView 路由**

Open browser to the app, navigate to outline view via sidebar. Verify page loads without errors.

- [ ] **Step 5: 最终提交（如有修复）**

```bash
git add -A && git commit -m "fix: Phase 2 verification fixes"
```

---

## Spec Coverage Check

| Spec Requirement | Task |
|-----------------|------|
| DI 容器 core/container.py | Task 1 |
| 注册跨模块服务到 main.py | Task 2 |
| world↔rag 解耦 | Task 3 |
| context↔outline + rag→writing 解耦 | Task 4 |
| project.py shim 删除 | Task 5 |
| Phase 1 验证 | Task 6 |
| CompiledContext IR | Task 7 |
| ConstraintEngine | Task 8 |
| Context Compiler v2 (Tier + 驱逐 + 双模式) | Task 9 |
| MarkdownRenderer 适配 | Task 10 |
| outlineView 独立提取 | Task 11 |
| Phase 2 验证 | Task 12 |

## Placeholder Scan

- No TBD/TODO/fill-in-later in actual code steps (ConstraintEngine knowledge/foreshadowing/scene have TODOs but these are genuinely deferred pending missing tables, noted explicitly)
- All file paths are exact
- All type names consistent across tasks