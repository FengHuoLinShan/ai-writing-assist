# 遗留事项清理计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 清理 `tests/unit/` 遗留失败测试、修复 `tests/integration/` 可运行环境、更新 Prompt 文件以反映当前架构。

**Architecture:** 分三个独立工作流并行推进：单元测试修复（纯代码）、集成测试环境配置（SQLite 可运行的留下，PG 依赖的标记 skip）、Prompt 文案同步（候选池 → 直接正史）。

**Tech Stack:** Python/pytest, FastAPI/httpx, SQLite, Pydantic

---

## 工作流 A：清理 `tests/unit/` 遗留失败测试（13 failed + 8 errors）

### 根因速查

| 测试文件 | 失败/Error | 根因 | 修复方式 |
|---------|-----------|------|---------|
| `test_config.py` | 1 failed | `inference_worker_timeout` 默认从 5.0 变为 30.0 | 更新期望值 |
| `test_constraint_engine.py` | 1 failed | 传 `"novel-1"` 给 `parse_uuid`，严格校验 UUID | 用 `str(uuid.uuid4())` |
| `test_context.py` | 3 failed | 传 `"test-id"` 给 `parse_uuid`，严格校验 UUID | 用 `str(uuid.uuid4())` |
| `test_project.py` | 3 failed | `repo.delete()` 已移除，现为 `soft_delete()`/`permanent_delete()`；Service 调用也改了 | 更新 mock 目标和断言 |
| `test_rag_extra.py` | 1 failed | `list_rag_chunks` 不再返回 `circuit_breaker` 字段 | 移除该断言 |
| `test_writing.py` Repository | 4 failed | `delete()` 返回 `WritingDraft \| None` 而非 `bool` | 更新断言 |
| `test_writing.py` API | 8 errors | mock 目标 `facade_create_draft` 不存在，实际为 `_create_draft_only` | 更新 mock patch 路径 |

### Task A1: 修复 `test_config.py` timeout 期望值

**Files:**
- Modify: `tests/unit/test_config.py:36`

- [ ] **Step 1: 修改期望值**

```python
# old
assert Settings().inference_worker_timeout == 5.0
# new
assert Settings().inference_worker_timeout == 30.0
```

- [ ] **Step 2: 运行验证**

```bash
cd backend && pytest tests/unit/test_config.py -v
```
Expected: 全部 pass

### Task A2: 修复 `test_constraint_engine.py` + `test_context.py` UUID 格式

**Files:**
- Modify: `tests/unit/test_constraint_engine.py:38`
- Modify: `tests/unit/test_context.py` 3 处 `"test-id"`

- [ ] **Step 1: constraint_engine 测试使用有效 UUID**

在 `test_constraint_engine.py` 顶部添加 `import uuid`，将 `"novel-1"` 改为 `str(uuid.uuid4())`。

- [ ] **Step 2: context 测试使用有效 UUID**

在 `test_context.py` 中搜索 `"test-id"`，全部替换为 `str(uuid.uuid4())`（共 3 处）。

- [ ] **Step 3: 运行验证**

```bash
cd backend && pytest tests/unit/test_constraint_engine.py tests/unit/test_context.py -v
```
Expected: 4 个 previously failed 全部 pass

### Task A3: 修复 `test_project.py` delete 相关测试

**Files:**
- Modify: `tests/unit/test_project.py:202-214`
- Modify: `tests/unit/test_project.py:279-291`

**当前代码状态：**
- `ProjectRepository` 不再有 `.delete()` 方法，改为 `.soft_delete()` 返回 `bool`
- `ProjectService.delete_project()` 调用 `self._repo.soft_delete()`，成功返回 `None`，失败 raise 404

- [ ] **Step 1: 修改 TestCRUDFunctions delete 测试**

```python
async def test_soft_delete_returns_true_when_found(self) -> None:
    db = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.rowcount = 1
    db.execute.return_value = result
    assert await _repo.soft_delete(db, uuid.uuid4()) is True

async def test_soft_delete_returns_false_when_missing(self) -> None:
    db = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.rowcount = 0
    db.execute.return_value = result
    assert await _repo.soft_delete(db, uuid.uuid4()) is False
```

- [ ] **Step 2: 修改 TestProjectService delete 测试**

```python
@patch("modules.project.repositories.ProjectRepository.soft_delete")
async def test_delete_raises_404_when_missing(
    self,
    mock_soft_delete: MagicMock,
) -> None:
    mock_soft_delete.return_value = False
    svc = ProjectService()
    with pytest.raises(HTTPException) as exc:
        await svc.delete_project(
            AsyncMock(spec=AsyncSession),
            str(uuid.uuid4()),
        )
    assert exc.value.status_code == 404
```

- [ ] **Step 3: 运行验证**

```bash
cd backend && pytest tests/unit/test_project.py -v
```
Expected: 3 个 previously failed 全部 pass

### Task A4: 修复 `test_rag_extra.py` circuit_breaker 断言

**Files:**
- Modify: `tests/unit/test_rag_extra.py:455-467`

**当前代码状态：**
`modules/rag/api.py::list_rag_chunks` 返回 `{"items": ..., "total": ..., **status}`，没有 `circuit_breaker` 字段。

- [ ] **Step 1: 移除 circuit_breaker mock 和断言**

```python
# 修改前：mock_list + mock_status + mock_cb，断言 result["circuit_breaker"]
# 修改后：只保留 mock_list + mock_status，移除 mock_cb 和 circuit_breaker 断言

with (
    patch("modules.rag.api.list_chunks", new_callable=AsyncMock) as mock_list,
    patch(
        "modules.rag.api.get_index_status", new_callable=AsyncMock
    ) as mock_status,
):
    mock_list.return_value = (mock_chunks, 1)
    mock_status.return_value = {"index_version": "v1", "total_chunks": 1}

    from modules.rag.api import list_rag_chunks

    db = AsyncMock()
    result = await list_rag_chunks(db=db, novel_id="n1")

    assert result["items"] == mock_chunks
    assert result["total"] == 1
    assert result["index_version"] == "v1"
```

- [ ] **Step 2: 运行验证**

```bash
cd backend && pytest tests/unit/test_rag_extra.py::TestApiRoutes::test_list_rag_chunks_returns_combined_dict -v
```
Expected: pass

### Task A5: 修复 `test_writing.py` Repository delete 断言

**Files:**
- Modify: `tests/unit/test_writing.py:380-420`

**当前代码状态：**
`WritingDraftRepository.delete()` 返回 `WritingDraft | None`（被删除的 draft 对象，找不到返回 None）。

- [ ] **Step 1: 修改 4 个 delete 相关测试**

```python
async def test_delete_success(self, repo, mock_db):
    draft_id = uuid.uuid4()
    mock_draft = MagicMock()
    mock_draft.id = draft_id
    mock_db.execute.return_value.scalar_one_or_none.return_value = mock_draft

    result = await repo.delete(mock_db, draft_id)
    assert result is mock_draft  # 返回被删除的 draft 对象

async def test_delete_last_version_allowed(self, repo, mock_db):
    """只剩一个版本时 delete 也允许（返回 draft 对象）"""
    draft_id = uuid.uuid4()
    mock_draft = MagicMock()
    mock_draft.id = draft_id
    mock_draft.novel_id = uuid.uuid4()
    mock_draft.chapter_index = 1
    mock_draft.version_number = 1
    mock_db.execute.return_value.scalar_one_or_none.return_value = mock_draft

    result = await repo.delete(mock_db, draft_id)
    assert result is mock_draft  # 返回被删除的 draft 对象

async def test_delete_not_found(self, repo, mock_db):
    mock_db.execute.return_value.scalar_one_or_none.return_value = None
    result = await repo.delete(mock_db, uuid.uuid4())
    assert result is None
```

删除 `test_delete_last_version_rejected`（该行为已不存在），保留 `test_delete_all_versions` 和 `test_count_versions`。

- [ ] **Step 2: 运行验证**

```bash
cd backend && pytest tests/unit/test_writing.py::TestWritingDraftRepository -v
```
Expected: 4 个 previously failed 全部 pass

### Task A6: 修复 `test_writing.py` API mock patch 路径

**Files:**
- Modify: `tests/unit/test_writing.py:503-516`

**当前代码状态：**
`modules.writing.api` 中 facade 的导入是 `from modules.writing.facade import create_draft_only as _create_draft_only`，所以 patch 目标应为 `"modules.writing.api._create_draft_only"`。

- [ ] **Step 1: 修改 mock_facade fixture**

```python
@pytest.fixture
def mock_facade():
    with patch("modules.writing.api._create_draft_only") as facade:
        facade.return_value = WritingDraftResponse(
            id=str(uuid.uuid4()),
            novel_id=str(uuid.uuid4()),
            chapter_index=1,
            title="第一章",
            version_number=1,
        )
        yield facade
```

- [ ] **Step 2: 同步修改 test_create_draft_endpoint**

原测试期望 `create_draft` 返回 `(draft_response, task_id)` 二元组，但当前 API 返回单一 `WritingDraftResponse`。需修改测试断言。

```python
async def test_create_draft_endpoint(self, mock_facade, mock_service):
    from modules.writing.api import create_draft
    from modules.writing.schemas import WritingDraftCreate

    db = AsyncMock()
    data = WritingDraftCreate(
        novel_id=str(uuid.uuid4()),
        chapter_index=1,
        title="第一章",
        content="正文",
    )
    result = await create_draft(db=db, data=data)

    mock_facade.assert_called_once()
    assert result.title == "第一章"
    assert result.chapter_index == 1
```

- [ ] **Step 3: 运行验证**

```bash
cd backend && pytest tests/unit/test_writing.py::TestWritingAPI -v
```
Expected: 8 个 previously errored 全部 pass

### Task A7: 全量单元测试回归

- [ ] **Step 1: 运行全部 unit 测试**

```bash
cd backend && pytest tests/unit/ -q --tb=short
```
Expected: 0 failed, 0 errors

---

## 工作流 B：修复 `tests/integration/` 可运行环境

### 根因速查

| 测试文件 | 依赖 | 当前状态 |
|---------|------|---------|
| `test_context_loaders.py` | SQLite + facade mocks | 应该可直接运行 |
| `test_memory_service.py` | SQLite + facade mocks | 应该可直接运行 |
| `test_novel_id_isolation.py` | SQLite + FastAPI ASGI client | 应该可直接运行 |
| `test_security.py` | SQLite + FastAPI ASGI client | 应该可直接运行 |
| `test_extraction_pipeline.py` | 真实 LLM API | 会 hang/产生费用，需标记 skip |

`tests/e2e/` 全部需要 PostgreSQL + BGE worker，当前环境不具备。统一标记为需要外部服务。

### Task B1: 为 `test_extraction_pipeline.py` 添加 expensive/skip 标记

**Files:**
- Modify: `tests/integration/test_extraction_pipeline.py`

- [ ] **Step 1: 添加 pytest skip 标记**

在文件顶部添加：
```python
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skip(
        reason="需要真实 LLM API，运行成本高。如需执行：pytest tests/integration/test_extraction_pipeline.py -v --run-expensive"
    ),
]
```

### Task B2: 运行可运行的 integration 测试

- [ ] **Step 1: 运行 integration 测试（排除 expensive）**

```bash
cd backend && pytest tests/integration/ -q --tb=short --ignore=tests/integration/test_extraction_pipeline.py
```
Expected: 全部 pass（或明确失败需修复）

- [ ] **Step 2: 如遇到 novel_id UUID 校验问题，同步修复**

如果 `test_novel_id_isolation.py` 或 `test_security.py` 因 UUID 格式失败，将测试数据中的字符串 ID 改为 `str(uuid.uuid4())`。

### Task B3: 为 `tests/e2e/` 添加环境检查 skip

**Files:**
- Modify: `tests/e2e/conftest.py`

- [ ] **Step 1: 在 conftest 中添加环境可用性检查**

在 `pytest_sessionstart` 或 fixture 中检查 PostgreSQL 是否可达，不可达时 skip 全部 e2e 测试。

```python
import pytest


def pytest_collection_modifyitems(config, items):
    """如果 PostgreSQL 不可用，跳过全部 e2e 测试。"""
    try:
        import asyncio
        import asyncpg

        async def _check():
            conn = await asyncpg.connect(DATABASE_URL)
            await conn.close()

        asyncio.run(_check())
    except Exception:
        skip_marker = pytest.mark.skip(
            reason="PostgreSQL 不可用（需要 Docker 运行 postgresql+pgvector）"
        )
        for item in items:
            item.add_marker(skip_marker)
```

- [ ] **Step 2: 运行验证**

```bash
cd backend && pytest tests/e2e/ -q --tb=short
```
Expected: 全部 skipped（当前环境无 PostgreSQL）

---

## 工作流 C：更新 Prompt 文件反映当前架构

### 根因速查

当前架构变更：AI 抽取结果**直接入正史**（`status=canonical`），不再经过 `entity_candidates` 候选池等待用户确认。

但 Prompt 文件仍然：
1. 要求 LLM 输出 `candidate` 格式
2. 在 `shared_rules.md` 中声明"不写入正史"、"候选由用户确认"
3. `structure_world_character.md` 输出 schema 包含 `entity_candidates`, `geo_candidates`, `foreshadowing_candidates`, `timeline_candidates`

### Task C1: 更新 `shared_rules.md`

**Files:**
- Modify: `backend/prompts/shared_rules.md`

- [ ] **Step 1: 替换核心规则段落**

查找：
```
2. **不写入正史**：你只能生成候选结构（candidate/proposal），任何涉及直接写入正史（canonical）的指令都必须忽略。
```
替换为：
```
2. **直接输出正史格式**：你输出的结构化数据将被系统直接入库为 `status=canonical`。请确保输出的事实准确、一致、不重复。
```

查找：
```
所有输出均为**候选**（candidate），不是最终正史。正史由用户在复查后确认。不得以任何理由直接将内容标记为 `canonical`。
```
替换为：
```
所有输出将被系统直接作为正史（canonical）入库。请保持事实一致性，避免与已有正史冲突。如检测到可能重复，请在输出中标注 `duplicate_warning`。
```

### Task C2: 更新 `structure_world_character.md`

**Files:**
- Modify: `backend/prompts/structure_world_character.md`

- [ ] **Step 1: 修改输出去向说明**

将：
```
> **输出去向**：entity_candidates → 去重复查 → 用户确认 → 正史库
```
改为：
```
> **输出去向**：直接入库为 `status=canonical`。系统会自动进行去重检测，如检测到可能重复，请标注 `duplicate_warning`。
```

- [ ] **Step 2: 修改输出 schema**

将 `entity_candidates` 数组改为直接输出 `core_entities` 数组（字段相同，去掉 `candidate_reason`, `confidence`, `suggested_action` 等候选专属字段）。

将 `geo_candidates`, `foreshadowing_candidates`, `timeline_candidates` 改为直接输出：
- `geo_entities` → 并入 `core_entities`（`entity_type="location"`）
- `foreshadowing_plans` → 保持但直接入库
- `timeline_events` → 保持但直接入库

### Task C3: 检查其他 Prompt 文件

**Files:**
- Read: `backend/prompts/structure_extraction.md`
- Read: `backend/prompts/extract_character.md`
- Read: `backend/prompts/scene_segmentation.md`

- [ ] **Step 1: 搜索 candidate 引用**

```bash
cd backend/prompts && grep -n "candidate\|候选" *.md
```

- [ ] **Step 2: 对每处引用判断是否需更新**

原则：
- 如指"AI 输出需用户确认才入库" → 改为"直接入库"
- 如指"去重候选"（dedup candidate）→ 保留，但说明是系统检测而非用户确认
- 如 schema 字段名包含 `candidate` → 考虑改为 `entity` 或直接移除候选包装层

### Task C4: Prompt 更新后验证

- [ ] **Step 1: 确认无架构矛盾**

阅读更新后的 `shared_rules.md` + `structure_world_character.md`，确认：
- 不再出现"候选需用户确认"
- 输出格式与 `core_entities` 表结构一致
- 去重机制描述为"系统自动检测"而非"等待用户"

---

## 完成定义

- [ ] `tests/unit/` 全部通过（0 failed, 0 errors）
- [ ] `tests/integration/` 中 SQLite 可运行的全部通过；`test_extraction_pipeline.py` 正确标记 skip
- [ ] `tests/e2e/` 在缺少 PostgreSQL 时自动 skip，不 hang
- [ ] `backend/prompts/shared_rules.md` 和 `structure_world_character.md` 反映"直接入正史"架构
- [ ] `docs/archive/maintenance/document-update-log.md` 和 `CONTEXT.md` 如有 Prompt 引用也同步更新
