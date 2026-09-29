# 后端 Ruff Lint 错误修复计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将后端 `backend/` 目录下的 104 个 Ruff lint 错误清零，同时不引入行为变更、不破坏现有测试。

**Architecture:** 按规则类型分组修复：
- `UP040`：用 Python 3.12+ `type` 关键字替换 `TypeAlias` 注解。
- `E402`：模块级副作用注册型 import 保持原位并加 `# noqa: E402`；其余可上移的 import 移到顶部。
- `E501`：通过括号换行、字符串拼接、提取局部变量将行宽压缩到 ≤90。
- `N801/N806/N814`：重命名为符合 PEP 8 的大小写。
- `F841`：删除未使用变量或改为 `_` / 加 `# noqa: F841`。
- `I001`：使用 `ruff check --fix` 自动排序 import。

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy, Ruff, pytest

---

## File Structure

| 文件 | 主要问题 | 修复策略 |
|------|----------|----------|
| `backend/shared/types.py` | UP040 × 11 | `type X = ...` |
| `backend/alembic/env.py` | E402 × 9 | 加 `# noqa: E402` |
| `backend/app/main.py` | E402 × 13 | 加 `# noqa: E402` |
| `backend/infrastructure/tasks/worker.py` | E402 × 7, N814 × 3, E501 × 2 | noqa + 重命名 + 换行 |
| `backend/modules/world/repositories.py` | E402 × 4 | 加 `# noqa: E402` |
| `backend/modules/imports/api.py` | I001 × 1 | ruff --fix |
| `backend/alembic/versions/*.py` | E501 × 4 | 字符串/列表换行 |
| `backend/infrastructure/llm/*.py` | E501 × 2 | 字符串换行 |
| `backend/modules/imports/models.py` | E501 × 1 | f-string 换行 |
| `backend/modules/imports/tests/test_real_extraction.py` | E501 × 3 | print/f-string 换行 |
| `backend/modules/rag/*.py` | E501 × 8, N806 × 2, F841 × 1 | 换行 + 小写 + 删除未用变量 |
| `backend/modules/world/services/extraction_service.py` | E501 × 4, N806 × 1 | 换行 + 小写 |
| `backend/modules/world/contracts.py` | E501 × 1 | docstring 换行 |
| `backend/modules/context/services/loaders/events_loader.py` | F841 × 1 | 删除未用变量 |
| `backend/tests/unit/test_crud.py` | N801 × 3 | 匿名类改名 |
| `backend/tests/unit/test_infra_tasks.py` | N806 × 3, F841 × 2 | 小写 + 删除/忽略 |
| `backend/tests/unit/test_rag_services.py` | N806 × 6 | with-as 别名小写 |
| `backend/tests/e2e/test_11_writing.py` | F841 × 1 | 删除未用变量 |
| `backend/tests/unit/test_character_facade.py` | F841 × 1 | 删除未用变量 |
| `backend/tests/unit/test_world_services_character_and_relation.py` | F841 × 2 | 删除未用变量 |
| `backend/tests/unit/test_extraction_service.py` | E501 × 4 | 参数列表/字符串换行 |
| `backend/tests/unit/test_world_extra.py` | E501 × 1 | 注释换行 |
| `backend/tests/unit/test_world_services_revision_event_helpers.py` | E501 × 1 | 函数签名换行 |
| `backend/tests/e2e/test_extraction_real_file.py` | E501 × 1 | f-string 换行 |
| `backend/tests/integration/test_novel_id_isolation.py` | E501 × 1 | 字符串换行 |

---

### Task 1: `shared/types.py` — 迁移类型别名为 `type` 语法

**Files:**
- Modify: `backend/shared/types.py`

- [ ] **Step 1: 修改文件内容**

将 `TypeAlias` 全部替换为 `type` 关键字，并删除 `typing.TypeAlias` import。

```python
"""
全局类型别名

为所有模块提供一致的 UUID 字符串类型别名。
所有 ID 在 API/contract 层以 str 传递，在 ORM 层为 uuid.UUID。
"""

from __future__ import annotations

# ---- 核心 ID 类型别名 ----

type NovelID = str
"""小说项目 ID (UUID hex string)"""

type EntityID = str
"""世界对象 ID (UUID hex string)"""

type CharacterID = str
"""人物 ID (UUID hex string)"""

type RelationshipID = str
"""关系 ID (UUID hex string)"""

type SnapshotID = str
"""记忆快照 ID (UUID hex string)"""

type DraftID = str
"""正文草稿 ID (UUID hex string)"""

type TaskID = str
"""异步任务 ID (UUID hex string)"""

# ---- 通用类型别名 ----

type JSON = dict[str, object]
"""通用 JSON 对象"""

type JSONList = list[object]
"""通用 JSON 数组"""

type ChapterIndex = int
"""章节索引（从 1 开始）"""

type EmbeddingVector = list[float]
"""Embedding 向量"""
```

- [ ] **Step 2: 单文件 lint 验证**

Run: `cd /Users/tywww/Desktop/项目/ai-writing-assist/backend && python -m ruff check shared/types.py`
Expected: `All checks passed`

- [ ] **Step 3: 提交**

```bash
git add backend/shared/types.py
git commit -m "style: migrate TypeAlias annotations to type keyword (UP040)"
```

---

### Task 2: `alembic/env.py` — 标记 Alembic 副作用 import 的 E402

**Files:**
- Modify: `backend/alembic/env.py`

- [ ] **Step 1: 修改文件内容**

将第 21-33 行的所有模块级模型 import 标记为 `# noqa: E402`，保留它们在 config 设置之后的注册位置。

```python
# 导入所有 ORM 模型以注册到 Base.metadata
import infrastructure.tasks.models  # noqa: E402  # noqa: F401

# character 模块已删除，模型在 modules.world.models
import modules.imports.models  # noqa: E402  # noqa: F401
import modules.memory.models  # noqa: E402  # noqa: F401
import modules.outline.models  # noqa: E402  # noqa: F401

# 显式导入所有模块的模型，确保 alembic autogenerate 能检测到所有表
import modules.project.models  # noqa: E402  # noqa: F401
import modules.rag.models  # noqa: E402  # noqa: F401
import modules.world.models  # noqa: E402  # noqa: F401
import modules.writing.models  # noqa: E402  # noqa: F401
from core.base import Base  # noqa: E402
```

- [ ] **Step 2: 单文件 lint 验证**

Run: `python -m ruff check alembic/env.py`
Expected: `All checks passed`

- [ ] **Step 3: 提交**

```bash
git add backend/alembic/env.py
git commit -m "style: noqa E402 for alembic model-registration imports"
```

---

### Task 3: `app/main.py` — 标记路由注册 import 的 E402

**Files:**
- Modify: `backend/app/main.py:337-353`

- [ ] **Step 1: 修改文件内容**

将路由注册段的所有 import 标记为 `# noqa: E402`。

```python
import modules.imports.tasks  # noqa: F401  # noqa: E402 — 注册深度导入任务处理器
import modules.outline.tasks  # noqa: F401  # noqa: E402 — 注册剧情结构生成任务处理器
import modules.rag.tasks  # noqa: F401  # noqa: E402 — 注册 RAG 索引/重建任务处理器
import modules.world.tasks  # noqa: F401  # noqa: E402 — 注册世界模块任务处理器
import modules.writing.tasks  # noqa: F401  # noqa: E402 — 注册章节发布任务处理器
from infrastructure.tasks import api as tasks_api  # noqa: E402
from modules.context import api as context_api  # noqa: E402

# geo/review — 已从 minimal-core 移除
# character API 已迁入 modules.world.api；模块已删除
from modules.imports import api as imports_api  # noqa: E402
from modules.memory import api as memory_api  # noqa: E402
from modules.outline import api as outline_api  # noqa: E402
from modules.project.api import router as project_router  # noqa: E402
from modules.rag import api as rag_api  # noqa: E402
from modules.world import api as world_api  # noqa: E402
from modules.writing import api as writing_api  # noqa: E402
```

- [ ] **Step 2: 单文件 lint 验证**

Run: `python -m ruff check app/main.py`
Expected: `All checks passed`

- [ ] **Step 3: 提交**

```bash
git add backend/app/main.py
git commit -m "style: noqa E402 for app route-registration imports"
```

---

### Task 4: `infrastructure/tasks/worker.py` — E402、N814、E501

**Files:**
- Modify: `backend/infrastructure/tasks/worker.py`

- [ ] **Step 1: 修改模块级注册 import**

第 39-46 行的 import 标记 `# noqa: E402`。

```python
# 注册 projects 表（NovelMixin FK 依赖）
import modules.imports.tasks  # noqa: E402  # noqa: F401
import modules.outline.tasks  # noqa: E402  # noqa: F401
import modules.project.models  # noqa: E402  # noqa: F401
import modules.rag.tasks  # noqa: E402  # noqa: F401

# 注册所有任务处理器（与 app/main.py 同步）
import modules.world.tasks  # noqa: E402  # noqa: F401
import modules.writing.tasks  # noqa: E402  # noqa: F401
```

- [ ] **Step 2: 重命名 N814 常量风格别名**

在 `_register_container_services` 中，把 `_OAS`、`_PSG`、`_PTS` 改为小写 snake_case。

```python
    from modules.outline.services import (
        OutlineArcService as _outline_arc_service,
    )
    from modules.outline.services import (
        PlotStructureGenerator as _plot_structure_generator,
    )
    from modules.outline.services import (
        PlotThreadService as _plot_thread_service,
    )
```

同时更新后续使用这些别名的地方（搜索 `_OAS`、`_PSG`、`_PTS` 并替换）。

- [ ] **Step 3: 修复 E501 长行**

第 216 行：
```python
            logger.info(
                "TaskWorker stopped — processed=%d, succeeded=%d, "
                "failed=%d, cancelled=%d",
                self._stats["processed"],
                self._stats["succeeded"],
                self._stats["failed"],
                self._stats["cancelled"],
            )
```

第 341 行：
```python
                "UPDATE async_tasks "
                "SET status = 'pending', "
                "error_message = 'Task recovered: heartbeat timeout' "
                "WHERE status = 'running' "
                "AND heartbeat_at < NOW() - make_interval(secs => :gap)"
```

- [ ] **Step 4: 单文件 lint 验证**

Run: `python -m ruff check infrastructure/tasks/worker.py`
Expected: `All checks passed`

- [ ] **Step 5: 提交**

```bash
git add backend/infrastructure/tasks/worker.py
git commit -m "style: fix E402/E501/N814 in infrastructure tasks worker"
```

---

### Task 5: `modules/world/repositories.py` — E402

**Files:**
- Modify: `backend/modules/world/repositories.py:21-42`

- [ ] **Step 1: 为模型/schema import 加 noqa**

```python
from modules.world.models import (  # noqa: E402
    Character,
    CharacterKnowledge,
    CoreEntity,
    EntityRelation,
    EntityRevision,
    Event,
)
from modules.world.schemas import (  # noqa: E402
    CharacterCreate,
    CharacterKnowledgeCreate,
    CharacterKnowledgeUpdate,
    CharacterUpdate,
    CoreEntityCreate,
    CoreEntityUpdate,
    EntityRelationCreate,
    EntityRelationUpdate,
    EventCreate,
    EventUpdate,
)
from shared.constants import DEFAULT_PAGE_SIZE  # noqa: E402
from shared.utils import parse_uuid  # noqa: E402
```

- [ ] **Step 2: 单文件 lint 验证**

Run: `python -m ruff check modules/world/repositories.py`
Expected: `All checks passed`

- [ ] **Step 3: 提交**

```bash
git add backend/modules/world/repositories.py
git commit -m "style: noqa E402 for world repositories model imports"
```

---

### Task 6: `modules/imports/api.py` — I001 import 排序

**Files:**
- Modify: `backend/modules/imports/api.py`

- [ ] **Step 1: 自动修复 import 排序**

Run: `python -m ruff check modules/imports/api.py --fix`
Expected: 文件被修改，`I001` 消失。

- [ ] **Step 2: 验证**

Run: `python -m ruff check modules/imports/api.py`
Expected: `All checks passed`

- [ ] **Step 3: 提交**

```bash
git add backend/modules/imports/api.py
git commit -m "style: sort imports in imports api (I001)"
```

---

### Task 7: Alembic migration 文件 E501

**Files:**
- Modify: `backend/alembic/versions/aed774d96500_v3_causal_spacetime_web.py:52-53`
- Modify: `backend/alembic/versions/d967c0547255_add_search_text_generated_col.py:24`
- Modify: `backend/alembic/versions/d967c0547257_memory_events_snapshots.py:47`

- [ ] **Step 1: 修复 aed774d96500 的 SQL 长行**

```python
    op.execute("""
        INSERT INTO core_entities (
            id, novel_id, entity_type, name, status, created_at, updated_at
        )
        SELECT gen_random_uuid(), c.novel_id, 'character_ref', c.name,
               c.status, c.created_at, c.updated_at
        FROM characters c
        WHERE c.world_entity_id IS NULL
    """)
    op.execute("""
        UPDATE characters c
        SET world_entity_id = ce.id,
            updated_at = NOW()
        FROM core_entities ce
        WHERE ce.novel_id = c.novel_id
          AND ce.name = c.name
          AND c.world_entity_id IS NULL
    """)
```

> 注意：如果实际 migration 的 `UPDATE` 原文与上面不同，请按原文语义换行，不要改变 SQL 逻辑。

- [ ] **Step 2: 修复 d967c0547255 的 pg_trgm 长行**

```python
    # Ensure pg_trgm extension is available
    # (it was created in 0001 but may not exist in test DBs)
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
```

- [ ] **Step 3: 修复 d967c0547257 的 comment 长行**

```python
            "event_type",
            sa.String(64),
            nullable=False,
            comment=(
                "entity_created | entity_updated | entity_removed | "
                "entity_moved | relation_established | relation_ended | "
                "knowledge_changed | manual_correction"
            ),
```

- [ ] **Step 4: 批量 lint 验证**

Run: `python -m ruff check alembic/versions/aed774d96500_v3_causal_spacetime_web.py alembic/versions/d967c0547255_add_search_text_generated_col.py alembic/versions/d967c0547257_memory_events_snapshots.py`
Expected: `All checks passed`

- [ ] **Step 5: 提交**

```bash
git add backend/alembic/versions/aed774d96500_v3_causal_spacetime_web.py backend/alembic/versions/d967c0547255_add_search_text_generated_col.py backend/alembic/versions/d967c0547257_memory_events_snapshots.py
git commit -m "style: wrap long lines in alembic migrations (E501)"
```

---

### Task 8: `infrastructure/llm/client.py` & `providers.py` — E501

**Files:**
- Modify: `backend/infrastructure/llm/client.py:211`
- Modify: `backend/infrastructure/llm/providers.py:47`

- [ ] **Step 1: 修复 client.py 长 f-string**

```python
                fix_msg = fix_prompt or (
                    "Your previous response failed validation. "
                    f"Error: {last_error}\n"
                    "Please output valid JSON matching this schema: "
                    f"{schema.model_json_schema()}"
                )
```

- [ ] **Step 2: 修复 providers.py docstring 长行**

```python
class OpenAIProvider:
    """OpenAI-compatible API Provider

    支持 OpenAI、Azure OpenAI、以及任何 OpenAI-compatible 的 API
    （如 Ollama、vLLM、DeepSeek 等）。
    """
```

- [ ] **Step 3: 验证**

Run: `python -m ruff check infrastructure/llm/client.py infrastructure/llm/providers.py`
Expected: `All checks passed`

- [ ] **Step 4: 提交**

```bash
git add backend/infrastructure/llm/client.py backend/infrastructure/llm/providers.py
git commit -m "style: wrap long lines in llm client/providers (E501)"
```

---

### Task 9: `modules/imports/models.py` — E501

**Files:**
- Modify: `backend/modules/imports/models.py:111`

- [ ] **Step 1: 修复 __repr__ 长行**

```python
    def __repr__(self) -> str:
        return (
            f"<ImportedChapter id={self.id} "
            f"index={self.chapter_index} title={self.title!r}>"
        )
```

- [ ] **Step 2: 验证并提交**

Run: `python -m ruff check modules/imports/models.py`
Expected: `All checks passed`

```bash
git add backend/modules/imports/models.py
git commit -m "style: wrap __repr__ line in imports models (E501)"
```

---

### Task 10: `modules/imports/tests/test_real_extraction.py` — E501

**Files:**
- Modify: `backend/modules/imports/tests/test_real_extraction.py:216,480,505`

- [ ] **Step 1: 修复三处长行**

第 216 行：
```python
        print(
            f"生成率: {result.total_created}/"
            f"{result.total_created + result.total_skipped}"
        )
```

第 480 行：
```python
        print(
            f"首次创建: {ctx['first_created']}, "
            f"第二次创建: {second_result.total_created}, "
            f"跳过: {second_result.total_skipped}"
        )
```

第 505 行：
```python
        print(
            f"批次 {batch['batch_id']}: {batch['entity_count']} 个实体, "
            f"导入时间 {batch['ingested_at']}"
        )
```

- [ ] **Step 2: 验证并提交**

Run: `python -m ruff check modules/imports/tests/test_real_extraction.py`
Expected: `All checks passed`

```bash
git add backend/modules/imports/tests/test_real_extraction.py
git commit -m "style: wrap long print lines in real extraction tests (E501)"
```

---

### Task 11: `modules/rag/*.py` — E501、N806、F841

**Files:**
- Modify: `backend/modules/rag/facade.py:81`
- Modify: `backend/modules/rag/models.py:49`
- Modify: `backend/modules/rag/services.py:688-689,1165,1244`
- Modify: `backend/modules/rag/tuning.py:293,321,328,334,337`

- [ ] **Step 1: 修复 facade.py 长行**

```python
        warnings.append(
            f"有 {pending_vectorization} 个片段待重新向量化（维度迁移后），"
            "检索可能暂时不准确",
        )
```

- [ ] **Step 2: 修复 models.py comment 长行**

```python
        comment=(
            "来源类型（chapter_text / world_entity / character / "
            "memory / outline 等）"
        ),
```

- [ ] **Step 3: 修复 services.py N806 与 F841**

第 688-689 行：
```python
        max_window = 10
        min_weight = 0.5
        distance = abs(chunk_chapter_index - reference_chapter_index)

        if distance >= max_window:
            return min_weight
        return 1.0 - (distance / max_window) * (1.0 - min_weight)
```

第 1163-1165 行：删除未使用的 `logger`：
```python
        # 构建 embedding 文本：BGE 模型直接使用原始 chunk 文本，不需要上下文前缀
        # OpenAI embedding 模式下前缀在 facade 层拼接（见 facade.retrieve）
        created_chunks: list[RagChunk] = []
```

第 1244 行：
```python
                warnings.append(
                    f"本章 {embedding_failed_count}/{len(created_chunks)} "
                    "个片段 embedding 失败，检索将降级为关键词匹配",
                )
```

- [ ] **Step 4: 修复 tuning.py 长行**

第 293 行：
```python
            print(
                f"  [{i + 1}/{len(combos)}] "
                f"v={w[0]:.2f} k={w[1]:.2f} r={w[2]:.2f} i={w[3]:.2f}  "
                f"MRR={result.mrr:.4f}"
            )
```

第 321 行：
```python
        print(
            f"{'排名':<4} {'vector':<8} {'keyword':<8} {'relation':<8} "
            f"{'importance':<10} {'MRR':<8} {'NDCG@5':<8} "
            f"{'NDCG@10':<8} {'P@5':<8}"
        )
```

第 328 行：
```python
            print(
                f"{rank:<4} {r.weights[0]:<8.2f} {r.weights[1]:<8.2f} "
                f"{r.weights[2]:<8.2f} {r.weights[3]:<10.2f} "
                f"{r.mrr:<8.4f} {r.ndcg_at_5:<8.4f} "
                f"{r.ndcg_at_10:<8.4f} {r.precision_at_5:<8.4f}"
            )
```

第 334 行：
```python
    print(
        f"推荐权重: vector={best.weights[0]:.2f} "
        f"keyword={best.weights[1]:.2f} relation={best.weights[2]:.2f} "
        f"importance={best.weights[3]:.2f}"
    )
```

第 337 行：
```python
    print(
        f"指标: MRR={best.mrr:.4f} NDCG@5={best.ndcg_at_5:.4f} "
        f"P@5={best.precision_at_5:.4f} "
        f"avg_latency={best.avg_latency_ms:.1f}ms"
    )
```

- [ ] **Step 5: 验证并提交**

Run: `python -m ruff check modules/rag/facade.py modules/rag/models.py modules/rag/services.py modules/rag/tuning.py`
Expected: `All checks passed`

```bash
git add backend/modules/rag/facade.py backend/modules/rag/models.py backend/modules/rag/services.py backend/modules/rag/tuning.py
git commit -m "style: fix E501/N806/F841 in rag module"
```

---

### Task 12: `modules/world/services/extraction_service.py` — E501、N806

**Files:**
- Modify: `backend/modules/world/services/extraction_service.py:123,226,259,300,307`

- [ ] **Step 1: 修复 N806 `_Action`**

第 123 行：
```python
        _action = Literal["create_new", "link_to_existing", "ignore", "temporary_only"]
```

同时把第 132 行的 `suggested_action: _Action` 改为 `suggested_action: _action`。

- [ ] **Step 2: 修复 E501 长 f-string**

第 226 行：
```python
                        new_entity_descriptions.append(
                            f"- {extracted.name} ({extracted.entity_type}) "
                            "[linked to existing]"
                        )
```

第 259 行：
```python
                        new_entity_descriptions.append(
                            f"- {extracted.name} ({extracted.entity_type}) "
                            "[matched via name embedding]"
                        )
```

第 300 行：
```python
                        new_entity_descriptions.append(
                            f"- {extracted.name} ({extracted.entity_type}) "
                            "[matched via content embedding]"
                        )
```

第 307 行（message 参数）：
```python
                    logger.warning(
                        "link_to_existing for '%s' (chapter %d) "
                        "could not resolve; skipping",
                        extracted.name,
                        ch_idx,
                    )
```

- [ ] **Step 3: 验证并提交**

Run: `python -m ruff check modules/world/services/extraction_service.py`
Expected: `All checks passed`

```bash
git add backend/modules/world/services/extraction_service.py
git commit -m "style: fix E501/N806 in world extraction service"
```

---

### Task 13: `modules/world/contracts.py` — E501

**Files:**
- Modify: `backend/modules/world/contracts.py:63`

- [ ] **Step 1: 修复 docstring 长行**

```python
@dataclass(frozen=True)
class EntityRevisionContract:
    """版本快照契约

    `entity_revisions` 在回滚时作为兜底使用，并继续承担显式
    `rollback-by-revision` 快照的存储。
    当 `TextArchive` 可用时，优先使用 TextArchive 作为回滚数据源。
    """
```

- [ ] **Step 2: 验证并提交**

Run: `python -m ruff check modules/world/contracts.py`
Expected: `All checks passed`

```bash
git add backend/modules/world/contracts.py
git commit -m "style: wrap long docstring in world contracts (E501)"
```

---

### Task 14: `modules/context/services/loaders/events_loader.py` — F841

**Files:**
- Modify: `backend/modules/context/services/loaders/events_loader.py:33-37`

- [ ] **Step 1: 删除未使用变量**

```python
        from modules.world.facade import get_events_context

        ctx = await get_events_context(
            db,
            options.novel_id,
            limit=tl_limit,
        )
```

- [ ] **Step 2: 验证并提交**

Run: `python -m ruff check modules/context/services/loaders/events_loader.py`
Expected: `All checks passed`

```bash
git add backend/modules/context/services/loaders/events_loader.py
git commit -m "style: remove unused variable in events loader (F841)"
```

---

### Task 15: `tests/unit/test_crud.py` — N801

**Files:**
- Modify: `backend/tests/unit/test_crud.py:91,98,105`

- [ ] **Step 1: 匿名类改名**

```python
    def test_missing_repo_raises_type_error(self):
        with pytest.raises(TypeError, match="'repo'"):

            class _MissingRepoService(CrudService):
                response = ResponseModel
                label = "X"

    def test_missing_response_raises_type_error(self):
        with pytest.raises(TypeError, match="'response'"):

            class _MissingResponseService(CrudService):
                repo = MagicMock()
                label = "X"

    def test_missing_label_raises_type_error(self):
        with pytest.raises(TypeError, match="'label'"):

            class _MissingLabelService(CrudService):
                repo = MagicMock()
                response = ResponseModel
```

- [ ] **Step 2: 验证并提交**

Run: `python -m ruff check tests/unit/test_crud.py`
Expected: `All checks passed`

```bash
git add backend/tests/unit/test_crud.py
git commit -m "style: name anonymous test classes (N801)"
```

---

### Task 16: `tests/unit/test_infra_tasks.py` — N806、F841

**Files:**
- Modify: `backend/tests/unit/test_infra_tasks.py:107,114,130,155,159`

- [ ] **Step 1: 修复 N806 别名**

把 `with patch(...) as MockRegistry:` 改为 `as mock_registry:`，并把 `registry_instance = MockRegistry.return_value` 改为 `registry_instance = mock_registry.return_value`。

第 106-109 行示例：
```python
        with patch(
            "infrastructure.tasks.api.TaskRegistry",
        ) as mock_registry:
            registry_instance = mock_registry.return_value
            registry_instance.__contains__ = MagicMock(return_value=True)
```

对第 128-132、153-157 处做同样处理。

- [ ] **Step 2: 修复 F841 未使用变量**

第 114 行：
```python
        _ = uuid.UUID(hex=response.task_id)  # valid UUID
```

第 159 行：
```python
        _ = await submit_task(request, db=db)
```

- [ ] **Step 3: 验证并提交**

Run: `python -m ruff check tests/unit/test_infra_tasks.py`
Expected: `All checks passed`

```bash
git add backend/tests/unit/test_infra_tasks.py
git commit -m "style: fix N806/F841 in infra tasks unit tests"
```

---

### Task 17: `tests/unit/test_rag_services.py` — N806

**Files:**
- Modify: `backend/tests/unit/test_rag_services.py:197,223,242,261,276,309`

- [ ] **Step 1: 所有 `MockClient` 别名改为小写**

把每个 `with patch("modules.rag.reranker.LLMClient") as MockClient:` 改为 `as mock_client:`。

例如第 223 行：
```python
        with patch("modules.rag.reranker.LLMClient") as mock_client:
            instance = mock_client.return_value
```

- [ ] **Step 2: 验证并提交**

Run: `python -m ruff check tests/unit/test_rag_services.py`
Expected: `All checks passed`

```bash
git add backend/tests/unit/test_rag_services.py
git commit -m "style: lowercase mock aliases in rag services tests (N806)"
```

---

### Task 18: `tests/e2e/test_11_writing.py` — F841

**Files:**
- Modify: `backend/tests/e2e/test_11_writing.py:60`

- [ ] **Step 1: 删除未使用的 `v1_id`**

```python
        assert resp.status_code == 201

        # Act
```

- [ ] **Step 2: 验证并提交**

Run: `python -m ruff check tests/e2e/test_11_writing.py`
Expected: `All checks passed`

```bash
git add backend/tests/e2e/test_11_writing.py
git commit -m "style: remove unused v1_id in writing e2e test (F841)"
```

---

### Task 19: `tests/unit/test_character_facade.py` — F841

**Files:**
- Modify: `backend/tests/unit/test_character_facade.py:108`

- [ ] **Step 1: 删除未使用的 `novel_id`**

```python
    # Arrange
    name = ""
```

- [ ] **Step 2: 验证并提交**

Run: `python -m ruff check tests/unit/test_character_facade.py`
Expected: `All checks passed`

```bash
git add backend/tests/unit/test_character_facade.py
git commit -m "style: remove unused novel_id in character facade test (F841)"
```

---

### Task 20: `tests/unit/test_world_services_character_and_relation.py` — F841

**Files:**
- Modify: `backend/tests/unit/test_world_services_character_and_relation.py:213,677`

- [ ] **Step 1: 删除/忽略未使用变量**

第 213 行：
```python
        # Act
        _ = await svc.update_character_state(
            db_session,
            cid,
            current_state="tired",
            novel_id=nid,
        )
```

第 677 行附近（`char = _make_character(...)` 后未使用）：
```python
        _ = _make_character(
            entity_id=uuid.UUID(cid),
            meta={"location_id": loc_id},
        )
```

- [ ] **Step 2: 验证并提交**

Run: `python -m ruff check tests/unit/test_world_services_character_and_relation.py`
Expected: `All checks passed`

```bash
git add backend/tests/unit/test_world_services_character_and_relation.py
git commit -m "style: remove unused variables in world services tests (F841)"
```

---

### Task 21: `tests/unit/test_extraction_service.py` — E501

**Files:**
- Modify: `backend/tests/unit/test_extraction_service.py:351,405,469,543`

- [ ] **Step 1: 修复四个装饰器/函数签名长行**

 decorators 行过长通常是因为参数列表。把每个 `@mock.patch(...)` 调用换行到多行。

例如第 351 行：
```python
    @mock.patch("modules.world.facade.find_entity_id_by_name")
    @mock.patch("modules.world.facade.get_world_context")
    @mock.patch("infrastructure.llm.prompt_loader.load_prompt")
    @mock.patch("infrastructure.llm.client.LLMClient")
    async def test_extract_entities_from_chapters_with_content_embedding_match_skips_entity(
        self,
        mock_llm_client,
        mock_load_prompt,
        mock_get_context,
        mock_find_entity,
        service,
    ):
```

对第 405、469、543 行做同样处理。

- [ ] **Step 2: 验证并提交**

Run: `python -m ruff check tests/unit/test_extraction_service.py`
Expected: `All checks passed`

```bash
git add backend/tests/unit/test_extraction_service.py
git commit -m "style: wrap long decorator lines in extraction service tests (E501)"
```

---

### Task 22: `tests/unit/test_world_extra.py` — E501

**Files:**
- Modify: `backend/tests/unit/test_world_extra.py:571`

- [ ] **Step 1: 修复注释长行**

```python
        # sim = round(0.50 + 0.95 * 0.35, 4) = 0.8325
        # 0.8325 > 0.88? No -> falls through
        # Wait: if semantic_cosine >= 0.85 -> already handled.
        # 0.95 >= 0.85 -> returns (0.90, "semantic", merge)
```

- [ ] **Step 2: 验证并提交**

Run: `python -m ruff check tests/unit/test_world_extra.py`
Expected: `All checks passed`

```bash
git add backend/tests/unit/test_world_extra.py
git commit -m "style: wrap long comment in world extra tests (E501)"
```

---

### Task 23: `tests/unit/test_world_services_revision_event_helpers.py` — E501

**Files:**
- Modify: `backend/tests/unit/test_world_services_revision_event_helpers.py:613`

- [ ] **Step 1: 修复测试函数签名长行**

```python
    async def test_writing_draft_provider_load_chapters_with_draft_and_rag_returns_chapters(
        self,
    ):
```

- [ ] **Step 2: 验证并提交**

Run: `python -m ruff check tests/unit/test_world_services_revision_event_helpers.py`
Expected: `All checks passed`

```bash
git add backend/tests/unit/test_world_services_revision_event_helpers.py
git commit -m "style: wrap long test method name (E501)"
```

---

### Task 24: `tests/e2e/test_extraction_real_file.py` — E501

**Files:**
- Modify: `backend/tests/e2e/test_extraction_real_file.py:217`

- [ ] **Step 1: 修复 f-string 长行**

```python
        assert result.total_created > 0, (
            f"应抽取到世界对象候选。创建 {result.total_created}，"
            f"跳过: {result.total_skipped}"
        )
```

- [ ] **Step 2: 验证并提交**

Run: `python -m ruff check tests/e2e/test_extraction_real_file.py`
Expected: `All checks passed`

```bash
git add backend/tests/e2e/test_extraction_real_file.py
git commit -m "style: wrap long assert message in real file e2e test (E501)"
```

---

### Task 25: `tests/integration/test_novel_id_isolation.py` — E501

**Files:**
- Modify: `backend/tests/integration/test_novel_id_isolation.py:173`

- [ ] **Step 1: 修复测试方法名/字符串长行**

如果是方法名过长：
```python
    async def test_novel_id_isolation_cross_project_rag_retrieve_returns_no_foreign_chunks(
        self,
        async_client: AsyncClient,
    ):
```

如果是字符串注释：按空格换行到多行。

- [ ] **Step 2: 验证并提交**

Run: `python -m ruff check tests/integration/test_novel_id_isolation.py`
Expected: `All checks passed`

```bash
git add backend/tests/integration/test_novel_id_isolation.py
git commit -m "style: wrap long line in novel id isolation integration test (E501)"
```

---

### Task 26: 全量验证

**Files:**
- All files listed above

- [ ] **Step 1: 运行全量 Ruff**

Run: `cd /Users/tywww/Desktop/项目/ai-writing-assist/backend && python -m ruff check .`
Expected: `All checks passed`

- [ ] **Step 2: 运行受影响模块测试**

Run:
```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist/backend
python -m pytest tests/unit tests/integration -q
```
Expected: 所有非真实 LLM/真实文件测试通过（`test_real_extraction.py` 与 `test_real_file_import.py` 可能因环境跳过或失败，属已知）。

- [ ] **Step 3: 最终提交（如需要）**

如果前面已逐任务提交，此步骤可跳过。否则：

```bash
git commit -m "style: fix all backend ruff lint errors"
```

---

## Self-Review

**1. Spec coverage:** 本计划覆盖统计中全部 104 个错误：
- UP040 × 11 → Task 1
- E402 × 33 → Task 2-5
- E501 × 33 → Task 7-13, 21-25 等
- N806 × 12 → Task 4, 11, 12, 16, 17
- F841 × 8 → Task 11, 14, 16, 18-20
- N801 × 3 → Task 15
- N814 × 3 → Task 4
- I001 × 1 → Task 6

**2. Placeholder scan:** 所有步骤均给出具体文件路径、行号、修复后代码或命令，无 "TBD"/"TODO"。

**3. Type consistency:** Task 12 中 `_Action` 改为 `_action` 后，同步更新了 `suggested_action` 的类型注解；Task 4 中别名重命名后需全文替换；其余改动均为局部格式化，无跨任务类型变化。

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-06-12-fix-backend-lint-errors.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
