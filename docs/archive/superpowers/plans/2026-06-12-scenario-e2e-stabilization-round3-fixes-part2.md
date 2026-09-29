# Round 3 修复收尾 — 第二部分 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消除第二轮 Code Review 中发现的 Critical 回归与遗留缺口，使 `world.spec.js` 回滚测试通过，并补齐计划要求但尚未实现的测试与文档同步。

**Architecture:** 最小改动原则：让 Playwright 启动的 backend 以 `APP_ENV=test` 运行，使 `_test/` 种子路由在 E2E 中可用；在 `test_workflow.py` 中直接测试 `handle_deep_import` 对 `task.result` 的阶段更新；修正 `scenario-coverage.md` 使其状态与真实测试结果一致；只做必要的代码整理。

**Tech Stack:** FastAPI, async SQLAlchemy, PostgreSQL, Playwright, vanilla JS SPA.

---

## Verified Baseline

修复前当前工作目录的预期测试结果：

```bash
cd backend && pytest modules/world/tests/test_world.py tests/test_world_testonly_route.py modules/imports/tests/test_workflow.py -q --tb=short
# 49 passed

cd frontend-console && npm test
# 11 files, 127 passed

cd frontend-console && npx playwright test world.spec.js --reporter=list
# 11 passed, 1 failed（回滚实体 404）

cd frontend-console && npx playwright test outline-scenes.spec.js deep-import.spec.js --reporter=list
# 7 passed, 3 failed
```

---

## File Structure

- **Modify:** `frontend-console/playwright.config.js` — E2E backend 启动命令注入 `APP_ENV=test`。
- **Modify:** `backend/modules/world/api.py` — 将 `TextArchive` import 从函数内提到模块顶部。
- **Modify:** `backend/modules/imports/tests/test_workflow.py` — 新增 `handle_deep_import` 更新 `task.result` 的测试。
- **Modify:** `frontend-console/e2e/scenario-coverage.md` — 根据真实测试结果修正状态，删除不实声明。

---

## Task 1: 修复 E2E Backend 环境，使测试路由可用

**Files:**
- Modify: `frontend-console/playwright.config.js`

### Step 1: 修改 webServer command

将 `frontend-console/playwright.config.js` 中的 backend 启动命令：

```javascript
{
  command: "cd ../backend && uvicorn app.main:app --host 0.0.0.0 --port 8000",
  url: "http://localhost:8000/api/health",
  timeout: 60000,
  reuseExistingServer: !process.env.CI,
}
```

替换为：

```javascript
{
  command: "cd ../backend && APP_ENV=test uvicorn app.main:app --host 0.0.0.0 --port 8000",
  url: "http://localhost:8000/api/health",
  timeout: 60000,
  reuseExistingServer: !process.env.CI,
}
```

说明：当前 backend 仅在此处使用 `app_env`，设置为 `test` 不会触发其他行为变化，仅开放 `/_test/` 种子路由。

### Step 2: 验证 world 回滚 E2E 通过

```bash
cd frontend-console && npx playwright test world.spec.js --reporter=list
```

Expected: 12 passed, 0 failed。

### Step 3: 提交

```bash
git add frontend-console/playwright.config.js
git commit -m "test(e2e): run backend with APP_ENV=test so seed routes are available"
```

---

## Task 2: 整理 backend 测试路由的 import

**Files:**
- Modify: `backend/modules/world/api.py`

### Step 1: 将 `TextArchive` 提到模块顶部 import

在 `backend/modules/world/api.py` 顶部 import 区，已有：

```python
from modules.world.models import CoreEntity
```

改为：

```python
from modules.world.models import CoreEntity, TextArchive
```

### Step 2: 删除函数内 import

将 `seed_entity_text_archive` 函数内的：

```python
    from modules.world.models import TextArchive
```

删除。

### Step 3: 运行 backend world 相关测试

```bash
cd backend && pytest modules/world/tests/test_world.py tests/test_world_testonly_route.py -q --tb=short
```

Expected: 39 passed。

### Step 4: 提交

```bash
git add backend/modules/world/api.py
git commit -m "style(world): move TextArchive import to module top"
```

---

## Task 3: 补充 handle_deep_import 更新 task.result 的测试

**Files:**
- Modify: `backend/modules/imports/tests/test_workflow.py`

### Step 1: 新增测试类

在 `backend/modules/imports/tests/test_workflow.py` 末尾追加：

```python
class TestHandleDeepImportTaskResult:
    """测试 task handler 在阶段边界更新 task.result"""

    @pytest.mark.asyncio
    async def test_handle_deep_import_updates_task_result_at_phase_boundaries(self):
        from modules.imports.tasks import handle_deep_import

        class FakeTask:
            def __init__(self):
                self.meta = {
                    "novel_id": str(uuid.uuid4()),
                    "start_chapter": 1,
                    "end_chapter": 3,
                }
                self.result = {}
                self.progress_values = []

            def update_progress(self, value):
                self.progress_values.append(value)

        task = FakeTask()

        with patch.object(
            DeepImportWorkflow,
            "_segment_scenes",
            new_callable=AsyncMock,
            return_value={
                "total_scenes": 5,
                "failed_batches": [],
                "degraded": False,
            },
        ), patch.object(
            DeepImportWorkflow,
            "_extract_entities_by_scene",
            new_callable=AsyncMock,
            return_value={"total_created": 3, "total_deltas": 2},
        ), patch.object(
            DeepImportWorkflow,
            "_analyze_structure",
            new_callable=AsyncMock,
            return_value={"total_threads": 2, "total_arcs": 4},
        ):
            result = await handle_deep_import(db=None, task=task)

        assert result["phase"] == "done"
        assert task.result["phase"] == "done"
        assert DeepImportStep.scene_segmentation.value in task.result["completed_steps"]
        assert DeepImportStep.entity_extraction.value in task.result["completed_steps"]
        assert DeepImportStep.structure_analysis.value in task.result["completed_steps"]
        assert len(task.progress_values) >= 4
        assert 1.0 in task.progress_values
```

注意：如果 `handle_deep_import` 内部调用 `await db.commit()` 而测试传入 `db=None` 会报错，则需要传入一个 mock db：

```python
mock_db = AsyncMock()
result = await handle_deep_import(db=mock_db, task=task)
```

按实际错误调整。

### Step 2: 运行测试

```bash
cd backend && pytest modules/imports/tests/test_workflow.py -q --tb=short
```

Expected: 11 passed（新增 1 个）。

### Step 3: 提交

```bash
git add backend/modules/imports/tests/test_workflow.py
git commit -m "test(imports): assert handle_deep_import updates task.result at phase boundaries"
```

---

## Task 4: 根据真实测试结果修正 scenario-coverage.md

**Files:**
- Modify: `frontend-console/e2e/scenario-coverage.md`

### Step 1: 重新跑完全部 Scenario E2E

```bash
cd frontend-console && npx playwright test project-recycle-bin.spec.js import.spec.js import-errors.spec.js deep-import.spec.js writing.spec.js writing-conflict.spec.js world.spec.js world-relations-aliases.spec.js outline-scenes.spec.js outline-threads-arcs.spec.js rag.spec.js context.spec.js --reporter=list
```

记录每个 spec 的通过/失败状态。

### Step 2: 修正状态标签

打开 `frontend-console/e2e/scenario-coverage.md`，按上一步结果更新：

- 全部通过的 spec：标 `✅ 已覆盖`。
- 部分通过或仍有失败：标 `🚧 已实现，E2E 待稳定`，并在描述中列出未通过用例。
- 完全未实现：标 `⏳ 待实现`。

具体需要修正的不实声明（以当前测试结果为例）：

**世界对象合并与回滚**：

原文：
> `world.spec.js` 已新增实体合并 E2E；实体回滚通过 `POST /api/world/_test/entities/:id/text-archive` 种子路由完成，回滚 E2E 已解除 `test.fixme` 并通过验收。

修正示例（假设 Task 1 修复后 world.spec.js 全部通过）：
> `world.spec.js` 已新增实体合并 E2E；实体回滚通过 `POST /api/world/_test/entities/:id/text-archive` 种子路由完成，回滚 E2E 已解除 `test.fixme`。注意：该种子路由仅在 `APP_ENV=test` 时可用，Playwright 已配置以 test 模式启动 backend。

**深度导入**：

原文：
> `deep-import.spec.js` 使用 Mock 加速覆盖了基础路径和浏览器恢复场景（`_recoverDeepImportTask` 单元测试 + E2E 恢复测试）。未覆盖真实三阶段推进与失败降级。

修正示例（假设仍有 2 个失败）：
> `deep-import.spec.js` 中「深度导入进度条在路由切换后恢复」已通过；「从项目视图导入小说后启动深度导入」等用例仍失败。真实三阶段推进、失败降级、浏览器关闭后进度恢复仍待覆盖。

**大纲伏笔/揭示管理**：

原文：
> `outlineView.js` 已新增"伏笔"和"揭示"两个子标签，包含列表渲染和伏笔状态切换功能。E2E 已解除 `test.fixme` 并通过验收。暂不支持编辑揭示计划阶段内容。

修正示例（假设 outline-scenes.spec.js 仍有失败）：
> `outlineView.js` 已新增"伏笔"和"揭示"两个子标签，包含列表渲染和伏笔状态切换功能；「管理伏笔与揭示计划」空态测试通过。但 `outline-scenes.spec.js` 仍有「上移/下移 Scene 卡调整顺序」「AI 生成结构弹窗」等失败，整体标记为待稳定。

### Step 3: 修正「部分覆盖」与「待实现」区

根据实际结果，将「已通过」的条目移到上方「已覆盖」表格，或更新描述。确保：

- 不将仍有失败的 spec 整体标记为 ✅。
- 每个 `⏳ 待实现` 条目对应真实未覆盖的功能。

### Step 4: 提交

```bash
git add frontend-console/e2e/scenario-coverage.md
git commit -m "docs(e2e): sync scenario coverage with actual test results"
```

---

## Task 5: 最终验证

**Files:** 无新增文件。

### Step 1: 后端全量验证

```bash
cd backend && pytest modules/project/tests/test_project.py modules/imports/tests/test_imports.py modules/imports/tests/test_workflow.py modules/writing/tests/test_writing.py modules/outline/tests/test_scene.py modules/outline/tests/test_foreshadowing_reveal.py modules/world/tests/test_world.py modules/rag/tests/test_indexing.py modules/context/tests/test_context.py tests/unit/test_context.py tests/unit/test_world_services_revision_event_helpers.py -q --tb=short
```

Expected: 全部通过。

### Step 2: 前端单元测试

```bash
cd frontend-console && npm test
```

Expected: 127 passed。

### Step 3: API 语法检查

```bash
cd frontend-console && node --check api.js
```

Expected: exit 0。

### Step 4: 全部 Scenario E2E

```bash
cd frontend-console && npx playwright test project-recycle-bin.spec.js import.spec.js import-errors.spec.js deep-import.spec.js writing.spec.js writing-conflict.spec.js world.spec.js world-relations-aliases.spec.js outline-scenes.spec.js outline-threads-arcs.spec.js rag.spec.js context.spec.js --reporter=list
```

Expected: `world.spec.js` 必须通过；其余保持真实状态，`scenario-coverage.md` 已如实记录。

### Step 5: 提交（如仅文档/测试修正无单独提交）

若 Task 4 已提交，此步骤无需新 commit；否则：

```bash
git add frontend-console/e2e/scenario-coverage.md
git commit -m "docs(e2e): final sync of scenario coverage"
```

---

## Self-Review Checklist

1. **Spec coverage:**
   - Critical E2E 回归 ✅（Task 1）
   - 代码整理 ✅（Task 2）
   - Task 5 缺失测试 ✅（Task 3）
   - 文档同步 ✅（Task 4）

2. **Placeholder scan:** 无 TBD/TODO/"implement later" 等占位符。

3. **Type consistency：**
   - `APP_ENV=test` 字符串一致。
   - `handle_deep_import(db, task)` 签名与 `backend/modules/imports/tasks.py` 一致。
   - `DeepImportWorkflow` patch 目标与实际方法名一致。

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-06-12-scenario-e2e-stabilization-round3-fixes-part2.md`.**

Two execution options:

1. **Subagent-Driven (recommended)** — Dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
