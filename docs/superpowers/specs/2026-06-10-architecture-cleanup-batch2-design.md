# Architecture Cleanup Batch 2 — DI 容器解耦 + outlineView 独立 + Context v2 增量改写

> **For agentic workers:** Use superpowers:subagent-driven-development or inline execution. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 消除循环依赖群、删除 Project 单体化 shim、前端 outlineView 独立提取、Context Compiler v2 增量改写（Tier 驱逐 + ConstraintEngine）。

**Architecture:** 两个 Batch 顺序执行。Batch 2A 做依赖图修复（DI 容器 + project.py 清除），Batch 2B 做功能增强（outlineView + Context v2）。Batch 2A 必须先完成，因为 Batch 2B 的 Context v2 依赖干净的模块边界。

**Tech Stack:** Python 3.13, FastAPI, async SQLAlchemy, pytest, vanilla JS SPA

---

## 0. 当前问题诊断

### 0.1 循环依赖图

```
world ←→ rag              # rag/services→world.facade; world/draft_provider→rag.facade
context ←→ outline        # context/loaders→outline.services; outline/services→context.facade
rag → writing → memory → world → rag  # 间接链条
```

### 0.2 Project 单体化

`modules/project/project.py` 是向后兼容重导出文件，20+ 导入站点仍通过它 import `Project` 和 CRUD 函数。

### 0.3 outlineView 内嵌

当前 `writingView.js`（826 行）中内嵌了 outline 面板逻辑。业务场景 6 要求 `/workbench/:pid/outline` 独立路由。

### 0.4 Context Compiler 架构不足

现有 `context_compiler.py` 按	scope 调度 8 个 Loader，但缺少：
- Tier 分级输出（P0-P4 9 段体系）
- Tier 驱逐策略（按 token 预算截断）
- ConstraintEngine（硬约束动态生成）
- IR 中间表示层（CompiledContext → MarkdownRenderer 分离）

---

## 1. Batch 2A：依赖图修复

### 1.1 创建 DI 容器 (`core/container.py`)

**Files:**
- Create: `backend/core/container.py`
- Modify: `backend/app/main.py`

**Design:**

```python
# core/container.py
"""轻量 DI 容器 — 消除模块间 facade 直连的循环依赖。

服务在 main.py 启动时注册，模块间通过 container.get() 获取依赖，
不再直接 import 其他模块的 facade/service。
"""
from __future__ import annotations

from collections.abc import Callable
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

**服务注册契约：** 每个注册到容器的服务必须是 **async callable**（`async def` 函数或实现了 `__call__` 的 async 方法），签名为 `(db: AsyncSession, novel_id: str, **kwargs) -> Any`。

**注册点在 `main.py` 启动时：**

```python
# app/main.py — 在 lifespan 或模块加载后
from core.container import register
from modules.world.facade import (
    list_characters,
    list_entity_terms,
    get_entity_importance_map,
)
from modules.rag.facade import (
    index_chapter_with_report,
    list_chapter_indices,
)
from modules.writing.facade import list_chapter_indices as writing_list_chapter_indices
from modules.outline.services import PlotStructureGenerator
from modules.context.facade import compile_structure_context

# 注册所有跨模块服务
register("world.list_characters", list_characters)
register("world.list_entity_terms", list_entity_terms)
register("world.get_entity_importance_map", get_entity_importance_map)
register("world.run_entity_extraction", run_entity_extraction)
register("rag.index_chapter", index_chapter_with_report)
register("rag.list_chapter_indices", list_chapter_indices)
register("writing.list_chapter_indices", writing_list_chapter_indices)
register("outline.generate_structure", PlotStructureGenerator().generate)
register("context.compile", compile_structure_context)
```

### 1.2 解耦 world ↔ rag 循环

**当前：**
- `rag/services.py` → `from modules.world.facade import list_characters, list_entity_terms, get_entity_importance_map`
- `world/services/draft_provider.py` → `from modules.rag.facade import index_chapter_with_report`

**解耦：**

| File | Action | Change |
|------|--------|--------|
| `rag/services.py` | Modify | 删除 facade import，改用 `container.get("world.list_characters")` 等 |
| `world/services/draft_provider.py` | Modify | 删除 rag facade import，改用 `container.get("rag.index_chapter")` |
| `rag/tasks.py` | Modify | 删除 `from modules.writing.facade`，改用 `container.get("writing.list_chapter_indices")` |
| `world/services/extraction_service.py` | Modify | 删除 `from modules.project.project import Project`，改用 `from modules.project.models import Project` |

### 1.3 解耦 context ↔ outline 循环

**当前：**
- `context/services/loaders/outline_arc_loader.py` → `from modules.outline.services import OutlineArcService`
- `context/services/loaders/plot_threads_loader.py` → `from modules.outline.services import PlotThreadService`
- `outline/services.py:163` → `from modules.context.facade import compile_structure_context`

**解耦：**

Context Loaders 已经通过 DI 注入（`ContextCompiler.__init__` 接收 loader 列表），但 loader 内部仍有 facade/service 直连。

**方案：** Loader 通过容器获取服务，不在文件顶部 import：

```python
# context/services/loaders/outline_arc_loader.py
from core.container import get

class OutlineArcLoader(Loader):
    name = "outline_arc"

    async def load(self, db, options):
        get_arc = get("outline.get_arc_by_chapter")
        arc = await get_arc(db, options.novel_id, options.chapter_index)
        ...
```

`outline/services.py` 中 `compile_structure_context` 调用改为容器注入：

```python
# outline/services.py
from core.container import get

class PlotStructureGenerator:
    async def generate(self, db, novel_id, start_chapter, end_chapter):
        compile_ctx = get("context.compile")
        context = await compile_ctx(db, novel_id, ...)
        ...
```

### 1.4 解耦 rag → writing 循环

**当前：**
- `rag/tasks.py:69` → `from modules.writing.facade import list_chapter_indices`

**解耦：** 写入容器，rag 通过容器获取：

```python
# rag/tasks.py
from core.container import get

async def _get_chapter_indices(db, novel_id):
    fn = get("writing.list_chapter_indices")
    return await fn(db, novel_id)
```

### 1.5 删除 Project 单体化 shim

**Files:**
- Delete: `backend/modules/project/project.py`
- Modify: 20+ files（所有 `from modules.project.project import ...` 的导入站点）

**机械性替换表（全部 import 替换）：**

| 旧导入 | 新导入 |
|--------|--------|
| `from modules.project.project import Project` | `from modules.project.models import Project` |
| `from modules.project.project import create_project` | `from modules.project.services import ProjectService; _svc = ProjectService()` |
| `from modules.project.project import get_project_by_id` | `from modules.project.services import ProjectService; _svc = ProjectService()` |
| `from modules.project.project import list_projects` | 同上 |
| `from modules.project.project import update_project` | 同上 |
| `from modules.project.project import delete_project` | 同上 |
| `from modules.project.project import router` | `from modules.project.api import router` |
| `from modules.project.project import ProjectContext` | `from modules.project.schemas import ProjectContext` |
| `import modules.project.project` (model 注册) | `import modules.project.models` |

**需要修改的文件清单：**

1. `app/main.py` — router import + model registration
2. `conftest.py` — model import
3. `tests/conftest.py` — model import
4. `alembic/env.py` — model import
5. `infrastructure/tasks/worker.py` — model import
6. `modules/world/services/entity_service.py` — Project import
7. `modules/memory/tests/conftest.py` — Project import
8. `modules/memory/tests/test_repositories.py` — Project import
9. `modules/imports/tests/test_real_file_import.py` — Project import
10. `modules/imports/tests/test_real_extraction.py` — Project import
11. `modules/rag/tests/test_real_index.py` — Project import
12. `modules/rag/tests/conftest.py` — Project import
13. `modules/outline/tests/test_context_integration.py` — Project import
14. `modules/project/tests/test_project.py` — service import
15. `modules/project/__init__.py` — 重导出
16. `tests/e2e/seed_data.py` — Project import
17. `tests/unit/test_entity_context_filter.py` — Project import
18. `tests/integration/test_extraction_pipeline.py` — Project import

### 1.6 Batch 2A 验证

- [ ] 全部循环依赖消除：`python -c "from modules.rag.services import RagService; from modules.world.services.draft_provider import DraftProvider"` 不报 CircularImport
- [ ] 项目单体化删除：`python -c "import modules.project.project"` 抛 ImportError
- [ ] 全部后端测试通过：`pytest backend/tests/ -x`
- [ ] Ruff 检查通过：`ruff check backend/`

---

## 2. Batch 2B：功能增强

### 2.1 前端 outlineView 独立提取

**当前状态：** `writingView.js` 826 行，内嵌 outline 面板。路由中无 `/workbench/:pid/outline`。

**目标：** 提取独立 `outlineView.js`，路由到 `/workbench/:pid/outline`，保持 KeepAlive。

**Files:**
- Create: `frontend-console/views/outlineView.js` — 独立大纲视图
- Modify: `frontend-console/router.js` — 添加 outline 路由
- Modify: `frontend-console/views/writingView.js` — 移除内嵌 outline 面板逻辑
- Modify: `frontend-console/app.js` — KeepAlive 配置

**outlineView.js 核心结构：**

```javascript
// outlineView.js — 独立大纲管理视图
const outlineView = {
  // 三个子标签：剧情线 / 篇章纲 / Scene 卡
  // 按 Scene 标签默认展示
  // 拖拽排序 Scene 卡片
  // AI 生成剧情结构
  // 伏笔/揭示管理

  async render(container, { projectId }) { ... },
  async onActivate() { ... },
  async onDeactivate() { ... },
};
```

**从 writingView.js 提取的逻辑：**
- Scene 卡片面板渲染和编辑（移到 outlineView + 保留写作台右侧只读展示）
- 大纲导航逻辑
- 剧情/篇章列表

**KeepAlive 联动：**
- 写作工作台右侧 Scene 卡面板从 outlineView API 获取数据（只读）
- outlineView 中编辑 Scene 卡后，writingView 通过共享状态刷新右侧面板
- 不使用 iframe，而是通过 `state.js` 共享 `outline.scenes` 响应式状态

### 2.2 Context Compiler v2 增量改写

**当前架构：**
- `context_compiler.py` — 139 行，按 scope 调度 Loader
- `markdown_renderer.py` — 590 行，直接渲染 `StructureContextBundle`
- `services/loaders/` — 8 个 Loader
- `services/protocol.py` — Loader 协议定义
- `services/types.py` — CompileOptions

**目标架构（增量改写）：**

```
context/
  contracts.py           — 不变（公共类型）
  schemas.py             — 不变
  api.py                 — 不变
  facade.py              — 不变
  markdown_renderer.py   — 适配为从 CompiledContext IR 渲染
  services/
    context_compiler.py   — 增加 Tier 分组 + 驱逐逻辑
    compiled_context.py   — 新增：IR 数据结构
    constraint_engine.py  — 新增：硬约束动态生成
    types.py              — 不变
    protocol.py           — 不变
    loaders/              — 不变
```

#### 2.2.1 CompiledContext IR (`compiled_context.py`)

```python
from __future__ import annotations
from enum import IntEnum
from pydantic import BaseModel

class Tier(IntEnum):
    P0 = 0   # 永不截断
    P1 = 1   # 最后截断
    P2 = 2   # 按条截断
    P3 = 3   # 优先截断
    P4 = 4   # 最先截断

class ContextSection(BaseModel):
    key: str
    tier: Tier
    content: str
    token_count: int = 0
    truncatable_per_item: bool = False   # P2 按条截断
    max_items: int | None = None          # P2 最大条数

class CompiledContext(BaseModel):
    """IR 中间表示 — Tier 标注的段列表"""
    sections: list[ContextSection]
    total_tokens: int = 0
    budget_tokens: int = 0
    compiled_at: str = ""

    def enforce_budget(self) -> "CompiledContext":
        """按 Tier 驱逐策略裁剪至预算内"""
        ...
```

#### 2.2.2 ConstraintEngine (`constraint_engine.py`)

4 类约束源：

| 约束源 | 类型 | 说明 |
|--------|------|------|
| StaticConstraints | P0 | 代码写死的全局约束（不泄露作者视角信息等） |
| KnowledgeConstraints | P1 | CharacterKnowledge 三态：unknown→禁止/restricted→限制/misunderstood→按误判表现 |
| ForeshadowingConstraints | P2 | status=seeded 且 payoff_scene > 当前 Scene → 禁止提前揭示 |
| SceneConstraints | P0 | Scene 卡 `must_not_happen` 直接列出 |

```python
class ConstraintEngine:
    async def compile_constraints(
        self, db: AsyncSession, novel_id: str,
        scene_id: str | None = None,
        chapter_index: int | None = None,
    ) -> list[ContextSection]:
        """收集全部硬约束段，标记 Tier=P0"""
        ...
```

ConstraintEngine 通过容器注入获取 world（CharacterKnowledge）和 outline（Foreshadowing）数据。

#### 2.2.3 Tier 驱逐策略

```
驱逐顺序：P4 → P3 → P2（按条）→ P1（Delta 20→15→10）→ P0 不截断

预算规则：
- token_budget 由配置决定（默认 4000）
- P0 段永不截断（Writing Objective + Scene Blueprint + Hard Constraints）
- P1 最后截断（截断前先做 Delta 压缩：20→15→10 条目）
- P2 按条截断（丢弃尾部条目直到预算满足）
- P3 优先截断（Style Assets）
- P4 最先截断（Compiler Warnings）
```

#### 2.2.4 双模式输出

```python
class CompileMode(StrEnum):
    writing = "writing"    # Delta 摘要模式（默认）
    debug = "debug"        # 全量 Snapshot 模式
```

- Writing 模式：P1 段使用 Delta Timeline（仅自上一 Scene 后的变更）
- Debug 模式：P1 段使用全量 Snapshot

#### 2.2.5 MarkdownRenderer 适配

现有 `markdown_renderer.py` 从 `StructureContextBundle` 直接渲染。改为：

1. `context_compiler.py` 先构建 `CompiledContext` IR
2. IR 通过 `enforce_budget()` 驱逐
3. `markdown_renderer.py` 从 `CompiledContext` 渲染

保持旧的 `render(StructureContextBundle)` 路由工作，内部桥接到新 IR 路径。

### 2.3 Batch 2B 验证

- [ ] outlineView 独立路由可访问
- [ ] KeepAlive 联动：outlineView 编辑 → writingView 右侧面板刷新
- [ ] Context Compiler v2 输出 9 段 Tier 结构
- [ ] Tier 驱逐：超出预算时按 P4→P3→P2→P1 顺序截断
- [ ] ConstraintEngine 生成硬约束段
- [ ] 双模式（writing/debug）输出不同 P1 内容
- [ ] 全部后端测试通过
- [ ] Ruff 检查通过
- [ ] 前端 E2E 测试通过

---

## 3. 不在本轮范围

| 项目 | 原因 |
|------|------|
| 新增数据模型（scenes/chapter_cards/foreshadowing_plans/reveal_plans/delta_log/text_archive/workflow 表） | 用户明确排除，后续 Batch |
| 深度导入三遍流水线 | 依赖缺失的 workflow 表和 scenes 表 |
| Entity 版本回滚（Delta Log + Text Archive） | 依赖 delta_log 和 text_archive 表 |
| 实体合并 9 步事务 | 前置条件满足，但不属于架构清理 |
| 写作工作台三栏布局重建 | 依赖 scenes 表和前端数据结构 |
| Batch 1 已覆盖项 | outline/memory facade 删除 + ListResponse 提取 |

---

## 4. 文件变更汇总

### Batch 2A（DI 容器 + 依赖解耦 + project.py 清除）

| File | Action | Responsibility |
|------|--------|---------------|
| `core/container.py` | Create | DI 容器（register/get/Injected/reset） |
| `app/main.py` | Modify | 服务注册 + project.py import 替换 |
| `rag/services.py` | Modify | facade import → container.get() |
| `rag/tasks.py` | Modify | writing facade import → container.get() |
| `world/services/draft_provider.py` | Modify | rag facade import → container.get() |
| `world/services/extraction_service.py` | Modify | project.py import → models import |
| `context/services/loaders/outline_arc_loader.py` | Modify | outline service import → container.get() |
| `context/services/loaders/plot_threads_loader.py` | Modify | outline service import → container.get() |
| `outline/services.py` | Modify | context facade import → container.get() |
| `imports/workflow.py` | Modify | world/outline facade → container.get() |
| `writing/tasks.py` | Modify | facade import → container.get() |
| `modules/project/project.py` | **Delete** | 向后兼容 shim |
| `modules/project/__init__.py` | Modify | 重导出改为从子模块 |
| 18+ test/config files | Modify | import 路径替换 |

### Batch 2B（outlineView 独立 + Context v2）

| File | Action | Responsibility |
|------|--------|---------------|
| `frontend-console/views/outlineView.js` | Create | 独立大纲视图 |
| `frontend-console/router.js` | Modify | 添加 outline 路由 |
| `frontend-console/views/writingView.js` | Modify | 移除内嵌 outline 逻辑 |
| `frontend-console/app.js` | Modify | KeepAlive 配置 |
| `context/services/compiled_context.py` | Create | IR 数据结构 |
| `context/services/constraint_engine.py` | Create | 硬约束引擎 |
| `context/services/context_compiler.py` | Modify | 增加 Tier 分组 + 驱逐 |
| `context/markdown_renderer.py` | Modify | 适配 CompiledContext IR |