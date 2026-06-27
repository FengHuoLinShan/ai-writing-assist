# Scenario E2E Stabilization Round 3 — 修复计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 Round 3 实现中遗留的安全、功能与测试缺口，使 Scenario E2E 全部通过且文档状态真实可信。

**Architecture:** 保持现有模块边界：backend 测试专用路由必须被 `APP_ENV == "test"` 守卫并校验 novel_id 所有权；frontend 在 `onEnter` 与 `onActivate` 中统一恢复深度导入任务；补齐 foreshadow/reveal 的状态刷新与 E2E 覆盖；补充 backend task-progress 单元测试；最终统一跑通验证命令并修正 `scenario-coverage.md`。

**Tech Stack:** FastAPI, async SQLAlchemy, PostgreSQL, vanilla JS SPA, Vitest, Playwright.

---

## Verified Baseline

修复前预期状态（当前工作目录）：

```bash
cd backend && pytest modules/world/tests/test_world.py modules/outline/tests/test_foreshadowing_reveal.py -q --tb=short
# 44 passed

cd backend && pytest modules/imports/tests/test_workflow.py -q --tb=short
# 1 failed（既有问题，本次修复需解决）

cd frontend-console && npm test -- --run outlineView.test.js writingView.test.js
# 53 passed

cd frontend-console && npx playwright test outline-scenes.spec.js deep-import.spec.js --reporter=list
# 4 failed / 6 passed
```

---

## File Structure

- **Create:** `backend/tests/test_world_testonly_route.py` — 种子路由环境隔离与所有权测试。
- **Modify:** `backend/core/config.py` — 新增 `app_env` 配置字段。
- **Modify:** `backend/modules/world/api.py:326-353` — 为 `/_test/entities/{entity_id}/text-archive` 增加环境守卫、entity 所有权校验、Pydantic response、顶层 import。
- **Modify:** `backend/modules/imports/tests/test_workflow.py` — 补充 `handle_deep_import` 在 phase boundary 更新 `task.result` 的测试，并修复既有失败测试。
- **Modify:** `frontend-console/router.js:18` — 更新 `outline` 子视图列表，加入 `foreshadowing` 与 `reveals`。
- **Modify:** `frontend-console/views/writingView.js:115-225` — 统一恢复深度导入任务，覆盖 `onEnter` 与 `onActivate`。
- **Modify:** `frontend-console/views/outlineView.js:785-815` — 伏笔状态变更后刷新列表。
- **Modify:** `frontend-console/e2e/outline-scenes.spec.js:161-169` — 扩展 foreshadow/reveal E2E，覆盖 API seed、状态变更、刷新断言。
- **Modify:** `frontend-console/e2e/helpers/api-client.js` — 补充 `createForeshadowing` / `createReveal` seed helper。
- **Modify:** `frontend-console/e2e/scenario-coverage.md` — 根据最终实际测试结果修正状态。

---

## Task 1: 为 Backend 测试路由增加环境隔离与所有权校验

**Files:**
- Modify: `backend/core/config.py`
- Modify: `backend/modules/world/api.py`
- Create: `backend/tests/test_world_testonly_route.py`

### Step 1: 在 Settings 中增加 `app_env`

在 `backend/core/config.py` 的 `Settings` dataclass 中新增字段：

```python
# --- 运行环境 ---
app_env: str = field(default_factory=lambda: _env("APP_ENV", "development"))
```

位置建议放在 LLM 配置之前，与数据库配置相邻。

### Step 2: 运行现有 backend 测试确认基线

```bash
cd backend && pytest modules/world/tests/test_world.py -q --tb=short
```

Expected: 36 passed（基线不变）。

### Step 3: 重构 `seed_entity_text_archive` 路由

修改 `backend/modules/world/api.py`：

1. 在文件顶部 import 区加入：

```python
import uuid

from fastapi import HTTPException

from core.config import get_settings
```

注意 `modules.world.models.TextArchive` 可能已在文件顶部 import；若未 import，一并加入：

```python
from modules.world.models import TextArchive
```

2. 替换现有路由实现：

```python
@router.post(
    "/_test/entities/{entity_id}/text-archive",
    response_model=dict,
    summary="E2E 测试专用：为实体写入 TextArchive 归档",
)
async def seed_entity_text_archive(
    db: DbSession,
    entity_id: str,
    novel_id: str = Query(..., description="项目 ID"),
    field_name: str = Query("summary", description="归档字段名"),
    text_content: str = Query(..., description="归档文本内容"),
    scene_index: int = Query(0, ge=0, description="场景索引"),
) -> dict:
    settings = get_settings()
    if settings.app_env != "test":
        raise HTTPException(status_code=404, detail="Not found")

    try:
        eid = uuid.UUID(hex=entity_id)
        nid = uuid.UUID(hex=novel_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid id: {exc}") from exc

    # 校验 entity 存在且属于该 novel_id
    entity = await db.get(CoreEntity, eid)
    if entity is None or entity.novel_id != nid:
        raise HTTPException(status_code=404, detail="Entity not found")

    archive = TextArchive(
        novel_id=nid,
        entity_id=eid,
        field_name=field_name,
        text_content=text_content,
        scene_index=scene_index,
        source="manual_edit",
    )
    db.add(archive)
    await db.flush()
    return {"status": "ok", "entity_id": entity_id, "field_name": field_name}
```

### Step 4: 编写路由隔离与所有权测试

创建 `backend/tests/test_world_testonly_route.py`：

```python
import os
from uuid import uuid4

import pytest
from httpx import AsyncClient

from modules.world.models import CoreEntity, TextArchive

pytestmark = pytest.mark.asyncio


async def _create_entity(db, novel_id: str, name: str = "seed-target") -> CoreEntity:
    entity = CoreEntity(
        novel_id=uuid4(),
        name=name,
        entity_type="item",
        status="canonical",
        summary="original",
    )
    db.add(entity)
    await db.flush()
    return entity


async def test_seed_text_archive_available_only_in_test_env(
    client: AsyncClient,
    db,
    monkeypatch,
):
    monkeypatch.setenv("APP_ENV", "development")
    entity = await _create_entity(db, str(uuid4()))
    resp = await client.post(
        f"/api/world/_test/entities/{entity.id.hex}/text-archive",
        params={
            "novel_id": entity.novel_id.hex,
            "text_content": "archived",
            "scene_index": 5,
        },
    )
    assert resp.status_code == 404


async def test_seed_text_archive_requires_matching_novel_id(
    client: AsyncClient,
    db,
    monkeypatch,
):
    monkeypatch.setenv("APP_ENV", "test")
    entity = await _create_entity(db, str(uuid4()))
    wrong_novel_id = uuid4().hex
    resp = await client.post(
        f"/api/world/_test/entities/{entity.id.hex}/text-archive",
        params={
            "novel_id": wrong_novel_id,
            "text_content": "archived",
        },
    )
    assert resp.status_code == 404


async def test_seed_text_archive_creates_row(
    client: AsyncClient,
    db,
    monkeypatch,
):
    monkeypatch.setenv("APP_ENV", "test")
    entity = await _create_entity(db, str(uuid4()))
    resp = await client.post(
        f"/api/world/_test/entities/{entity.id.hex}/text-archive",
        params={
            "novel_id": entity.novel_id.hex,
            "text_content": "archived summary",
            "field_name": "summary",
            "scene_index": 3,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["entity_id"] == entity.id.hex
    assert data["field_name"] == "summary"

    from sqlalchemy import select
    result = await db.execute(
        select(TextArchive).where(TextArchive.entity_id == entity.id)
    )
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].text_content == "archived summary"
    assert rows[0].scene_index == 3
```

注意：若项目没有全局 `client` fixture，请改用已有的 async client fixture 名称或按现有测试模式构造请求。

### Step 5: 运行新增测试

```bash
cd backend && pytest tests/test_world_testonly_route.py -q --tb=short
```

Expected: 3 passed。

### Step 6: 提交

```bash
git add backend/core/config.py backend/modules/world/api.py backend/tests/test_world_testonly_route.py
git commit -m "fix(world): guard _test text-archive route by APP_ENV and validate ownership"
```

---

## Task 2: 修复 writingView 深度导入任务在 KeepAlive 下的恢复

**Files:**
- Modify: `frontend-console/views/writingView.js`
- Modify: `frontend-console/tests/writingView.test.js`

### Step 1: 提取恢复方法并统一调用

修改 `frontend-console/views/writingView.js`：

1. 将 `onEnter` 末尾的：

```javascript
// 恢复持久化的深度导入任务进度
this._recoverDeepImportTask()
```

替换为：

```javascript
// 恢复持久化的深度导入任务进度
await this._recoverDeepImportTask()
```

2. 在 `onActivate()` 中也调用恢复：

```javascript
onActivate() {
  // KeepAlive 恢复后重新绑定事件
  this._bindEvents()
  // 恢复编辑器焦点
  const editor = document.getElementById("writing-editor")
  if (editor) editor.focus()
  // KeepAlive 切回时同样需要恢复深度导入进度
  this._recoverDeepImportTask()
},
```

### Step 2: 保证恢复后再刷新进度条

当前 `_recoverDeepImportTask` 在运行中分支已调用 `_rerender()`。确保 `onEnter` 中的 `await` 使得首次渲染前或渲染后进度条已存在。为增强确定性，在 `_recoverDeepImportTask` 末尾统一调用一次 `_rerender`：

```javascript
async _recoverDeepImportTask() {
  let taskId
  try { taskId = localStorage.getItem("novel_deepImportTaskId") } catch {}
  if (!taskId) return
  try {
    const task = await api.tasks.get(taskId)
    if (!task || task.status === "done" || task.status === "failed") {
      if (task && task.result) {
        this._deepImportTaskId = taskId
        this._deepImportProgress = {
          phase: "done",
          step: "",
          message: task.result.message || (task.status === "failed" ? "导入失败" : "导入完成"),
          percent: 100,
          stepLabel: (task.status === "failed" ? "失败" : "完成"),
          degraded: task.result.degraded || false,
        }
      }
      try { localStorage.removeItem("novel_deepImportTaskId") } catch {}
      await this._rerender()
      return
    }
    this._deepImportTaskId = taskId
    const result = task.result || {}
    this._deepImportProgress = {
      phase: result.phase || "running",
      step: result.current_step || "",
      message: result.message || "深度导入中...",
      percent: result.phase === "running" ? 50 : 0,
      stepLabel: result.current_step ? `Phase: ${result.current_step}` : "恢复进度中...",
      degraded: result.degraded || false,
    }
    await this._rerender()
    this._startDeepImportPolling()
  } catch {
    try { localStorage.removeItem("novel_deepImportTaskId") } catch {}
  }
}
```

注意：失败分支也加了 `_rerender()`，但异常时未调用；可选在 catch 中调用 `_rerender()` 以清空可能的旧状态。

### Step 3: 更新单元测试验证 `onActivate` 恢复

在 `frontend-console/tests/writingView.test.js` 的 `_recoverDeepImportTask` describe 下新增：

```javascript
it("onActivate 也会触发恢复", async () => {
  localStorage.setItem("novel_deepImportTaskId", "task-reactivate")
  api.tasks.get.mockResolvedValue({
    status: "running",
    result: { phase: "running", current_step: "entity_extraction", message: "Phase 2/3" },
  })
  vi.spyOn(writingView, "_bindEvents").mockImplementation(() => {})
  vi.spyOn(writingView, "_rerender").mockImplementation(() => {})

  await writingView.onActivate()

  expect(api.tasks.get).toHaveBeenCalledWith("task-reactivate")
  expect(writingView._deepImportProgress.phase).toBe("running")
})
```

### Step 4: 运行单元测试

```bash
cd frontend-console && npm test -- --run writingView.test.js
```

Expected: 所有 writingView 测试通过（含新增 1 个）。

### Step 5: 运行恢复 E2E

```bash
cd frontend-console && npx playwright test deep-import.spec.js --reporter=list
```

Expected: 「深度导入进度条在路由切换后恢复」通过。

### Step 6: 提交

```bash
git add frontend-console/views/writingView.js frontend-console/tests/writingView.test.js
git commit -m "fix(writing): recover deep import task on both onEnter and onActivate"
```

---

## Task 3: 更新 Router 的 Outline 子视图列表

**Files:**
- Modify: `frontend-console/router.js`

### Step 1: 修改 routes 配置

```javascript
outline: { title: "大纲", subViews: ["scenes", "threads", "arcs", "foreshadowing", "reveals"] },
```

### Step 2: 运行 outline 相关单元测试

```bash
cd frontend-console && npm test -- --run outlineView.test.js
```

Expected: 22 tests passed。

### Step 3: 提交

```bash
git add frontend-console/router.js
git commit -m "fix(router): register foreshadowing and reveals as outline subviews"
```

---

## Task 4: 完善 Foreshadow/Reveal UI 刷新与 E2E 覆盖

**Files:**
- Modify: `frontend-console/e2e/helpers/api-client.js`
- Modify: `frontend-console/views/outlineView.js`
- Modify: `frontend-console/e2e/outline-scenes.spec.js`

### Step 1: 在 api-client.js 中新增 seed helper

在 `frontend-console/e2e/helpers/api-client.js` 末尾追加：

```javascript
// ---- Outline helpers ----

export async function createForeshadowing(novelId, data) {
  return request(`/outline/foreshadowing?novel_id=${encodeURIComponent(novelId)}`, {
    method: "POST",
    body: JSON.stringify(data),
  })
}

export async function createReveal(novelId, data) {
  return request(`/outline/reveals?novel_id=${encodeURIComponent(novelId)}`, {
    method: "POST",
    body: JSON.stringify(data),
  })
}
```

### Step 2: 伏笔状态变更后刷新列表

修改 `frontend-console/views/outlineView.js` 中 `sel.onchange`：

```javascript
sel.onchange = async () => {
  const id = sel.dataset.id
  if (!id) return
  try {
    await api.outline.updateForeshadowing(id, state.currentProjectId, { status: sel.value })
    toast("伏笔状态已更新", "success")
    await this.onEnter()
  } catch (err) {
    toast(err.message || "更新失败", "error")
  }
}
```

### Step 3: 扩展 E2E 覆盖

替换 `frontend-console/e2e/outline-scenes.spec.js` 中的测试：

```javascript
test("管理伏笔与揭示计划", async ({ page }) => {
  // Given: 通过 API 创建 seed 数据
  const foreshadowing = await createForeshadowing(testProjectId, {
    name: "隐藏神器",
    summary: "主角在古遗迹中获得神秘吊坠",
    status: "draft",
    planned_seed_chapter: 2,
    planned_payoff_chapter: 10,
  })
  await createReveal(testProjectId, {
    target_type: "entity",
    secret_summary: "吊坠的真实力量",
    reveal_stages: [{ stage_index: 0, summary: "初次发光" }],
    status: "draft",
  })

  // 伏笔子标签
  await page.locator('[data-action="nav-foreshadowing"]').click()
  await expect(page.locator(SEL.dataTable)).toContainText("隐藏神器", { timeout: 10000 })

  // 修改状态并验证刷新
  await page.locator('tr:has-text("隐藏神器") .foreshadowing-status-select').selectOption("active")
  await expect(page.locator(SEL.toastContainer)).toContainText("已更新", { timeout: 10000 })
  await expect(page.locator('tr:has-text("隐藏神器") .badge-active')).toBeVisible({ timeout: 10000 })

  // 揭示子标签
  await page.locator('[data-action="nav-reveals"]').click()
  await expect(page.locator(SEL.dataTable)).toContainText("吊坠的真实力量", { timeout: 10000 })
})
```

注意：需要在该 spec 顶部 import `createForeshadowing` 和 `createReveal`：

```javascript
import { createProject, cleanupProject, waitForBackend, createForeshadowing, createReveal } from "./helpers/api-client.js"
```

### Step 4: 运行单元测试与 E2E

```bash
cd frontend-console && npm test -- --run outlineView.test.js
cd frontend-console && npx playwright test outline-scenes.spec.js --reporter=list
```

Expected: 单元测试通过；outline-scenes E2E 中「管理伏笔与揭示计划」通过。

### Step 5: 提交

```bash
git add frontend-console/e2e/helpers/api-client.js frontend-console/views/outlineView.js frontend-console/e2e/outline-scenes.spec.js
git commit -m "feat(outline): refresh foreshadow list after status change and extend E2E"
```

---

## Task 5: 补充 Backend Deep Import Task-Progress 测试

**Files:**
- Modify: `backend/modules/imports/tests/test_workflow.py`

### Step 1: 修复既有失败测试

既有失败：

```
modules/outline/facade.py:124: in get_next_scene_index
    return (result.scalar() or -1) + 1
E   TypeError: unsupported operand type(s) for +: 'coroutine' and 'int'
```

检查 `backend/modules/outline/facade.py:124`：

```python
async def get_next_scene_index(db, novel_id):
    result = await db.execute(select(func.max(OutlineScene.scene_index)).filter(...))
    return (result.scalar() or -1) + 1
```

失败原因是 `result.scalar()` 在测试中被 mock 为 coroutine。检查 `test_workflow.py` 中相关 mock，将 `scalar` 改为返回同步值：

```python
mock_result.scalar.return_value = 2  # 或任意整数
```

### Step 2: 编写 task.result 阶段更新测试

在 `backend/modules/imports/tests/test_workflow.py` 新增测试类：

```python
class TestHandleDeepImportReportsProgress:
    async def test_updates_task_result_at_phase_boundaries(self, db, monkeypatch):
        from modules.imports.workflow import handle_deep_import
        from modules.imports.models import ImportTask

        novel_id = uuid4()
        task = ImportTask(
            novel_id=novel_id,
            task_type="deep_import",
            status="running",
            result={},
        )
        db.add(task)
        await db.flush()

        # 模拟三个阶段，每个阶段向 task.result 写入进度
        call_order = []

        async def fake_segment_chapters(db, novel_id, chapters, task):
            task.result = {"phase": "segmentation", "current_step": "scene_segmentation", "completed_steps": []}
            call_order.append("segment")
            return [{"index": 0, "title": "Scene 1"}]

        async def fake_extract_entities(db, novel_id, scenes, task):
            task.result = {"phase": "extraction", "current_step": "entity_extraction", "completed_steps": ["scene_segmentation"]}
            call_order.append("extract")
            return []

        async def fake_integrate_assets(db, novel_id, scenes, entities, task):
            task.result = {"phase": "integration", "current_step": "asset_integration", "completed_steps": ["scene_segmentation", "entity_extraction"]}
            call_order.append("integrate")

        monkeypatch.setattr(
            "modules.imports.workflow.segment_chapters",
            fake_segment_chapters,
        )
        monkeypatch.setattr(
            "modules.imports.workflow.extract_entities_from_scenes",
            fake_extract_entities,
        )
        monkeypatch.setattr(
            "modules.imports.workflow.integrate_extracted_assets",
            fake_integrate_assets,
        )

        await handle_deep_import(db, novel_id, task)

        await db.refresh(task)
        assert task.status == "done"
        assert call_order == ["segment", "extract", "integrate"]
        assert task.result["phase"] == "integration"
        assert "asset_integration" in task.result["completed_steps"]
```

实际函数名与模块路径以 `backend/modules/imports/workflow.py` 为准，请按真实签名调整。

### Step 3: 运行 workflow 测试

```bash
cd backend && pytest modules/imports/tests/test_workflow.py -q --tb=short
```

Expected: 全部通过。

### Step 4: 提交

```bash
git add backend/modules/imports/tests/test_workflow.py
git commit -m "test(imports): fix existing mock and assert task.result progress in deep import"
```

---

## Task 6: 统一跑通验证命令并修正场景覆盖文档

**Files:**
- Modify: `frontend-console/e2e/scenario-coverage.md`

### Step 1: 运行后端完整验证

```bash
cd backend && pytest modules/project/tests/test_project.py modules/imports/tests/test_imports.py modules/imports/tests/test_workflow.py modules/writing/tests/test_writing.py modules/outline/tests/test_scene.py modules/outline/tests/test_foreshadowing_reveal.py modules/world/tests/test_world.py modules/rag/tests/test_indexing.py modules/context/tests/test_context.py tests/unit/test_context.py tests/unit/test_world_services_revision_event_helpers.py -q --tb=short
```

Expected: 全部通过。

### Step 2: 运行前端单元测试

```bash
cd frontend-console && npm test
```

Expected: 全部通过。

### Step 3: 运行 API 语法检查

```bash
cd frontend-console && node --check api.js
```

Expected: exit 0。

### Step 4: 运行全部 Scenario E2E

```bash
cd frontend-console && npx playwright test project-recycle-bin.spec.js import.spec.js import-errors.spec.js deep-import.spec.js writing.spec.js writing-conflict.spec.js world.spec.js world-relations-aliases.spec.js outline-scenes.spec.js outline-threads-arcs.spec.js rag.spec.js context.spec.js --reporter=list
```

Expected: 全部通过；如有仍未通过的，保留 `test.fixme` 或明确标注原因，不标记为 ✅。

### Step 5: 根据实际结果修正 `scenario-coverage.md`

修改 `frontend-console/e2e/scenario-coverage.md`：

- 若所有 E2E 通过：
  - `project-recycle-bin.spec.js` 状态改为 ✅（需确认 app.js 问题已修复或该 spec 确实通过）。
  - `import-errors.spec.js` 状态改为 ✅。
  - `deep-import.spec.js` 状态改为 ✅。
  - `world.spec.js` / `world-relations-aliases.spec.js` 状态改为 ✅。
  - `outline-scenes.spec.js` 状态改为 ✅。
- 若仍有失败：
  - 使用 `🚧 已实现，E2E 待稳定`。
  - 在「部分覆盖」区用一句话说明失败原因和跟踪 issue（如有）。
  - 绝不将未通过的测试标记为 ✅。

### Step 6: 提交

```bash
git add frontend-console/e2e/scenario-coverage.md
git commit -m "docs(e2e): sync scenario coverage after round 3 stabilization fixes"
```

---

## Self-Review Checklist

1. **Spec coverage:**
   - Task 1 覆盖 review 中 Critical 安全问题 ✅
   - Task 2 覆盖 deep import KeepAlive 恢复失败 ✅
   - Task 3 覆盖 router 子视图缺失 ✅
   - Task 4 覆盖 foreshadow/reveal 刷新与 E2E ✅
   - Task 5 覆盖 backend task-progress 测试缺失 ✅
   - Task 6 覆盖 scenario-coverage.md 同步 ✅

2. **Placeholder scan:** 无 TBD/TODO/"implement later"/"similar to" 等占位符。

3. **Type consistency：**
   - `app_env` 字符串与 `"test"` 比较一致。
   - `api.outline.updateForeshadowing(id, novelId, payload)` 签名一致。
   - `handle_deep_import(db, novel_id, task)` 以实际模块为准。

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-06-12-scenario-e2e-stabilization-round3-fixes.md`.**

Two execution options:

1. **Subagent-Driven (recommended)** — Dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
