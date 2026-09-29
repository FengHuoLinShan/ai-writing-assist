# Post Round 4 Acceptance Gap Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining code/spec gaps found after validating the latest agent round against `docs/核心业务场景与预期行为.md`.

**Architecture:** Keep the existing FastAPI modules, PostgreSQL-backed `async_tasks`, and vanilla JS SPA. Fix documented user-path contracts first, then make scenario coverage honest and add missing browser/backend acceptance checks. Do not introduce frontend frameworks, TypeScript, Redis, Celery, new databases, or cross-module imports outside `contracts.py` / `facade.py`.

**Tech Stack:** FastAPI, async SQLAlchemy, SQLite module tests, PostgreSQL E2E runtime, vanilla JS, Vitest, Playwright.

---

## Acceptance Baseline

Validation already run for this round:

```bash
cd backend && pytest modules/project/tests/test_project.py modules/imports/tests/test_imports.py modules/imports/tests/test_workflow.py modules/writing/tests/test_writing.py modules/outline/tests/test_scene.py modules/outline/tests/test_foreshadowing_reveal.py modules/world/tests/test_world.py modules/rag/tests/test_rag.py modules/context/tests/test_context.py tests/integration/test_novel_id_isolation.py -q --tb=short
# 279 passed, 1 warning

cd frontend-console && npm test
# 11 files, 130 tests passed

cd frontend-console && node --check app.js && node --check api.js
# exit 0

cd frontend-console && npx playwright test project-recycle-bin.spec.js import.spec.js import-errors.spec.js deep-import.spec.js writing.spec.js writing-conflict.spec.js world.spec.js world-relations-aliases.spec.js outline-scenes.spec.js outline-threads-arcs.spec.js rag.spec.js context.spec.js --reporter=list
# 52 passed
```

The scenario suite is green, but acceptance is not complete. Current tests were changed to match some implementation drift instead of the core scenario document.

## Current Gaps

1. `frontend-console/views/projectView.js` sends newly created and selected projects to `world/objects`; the core document requires `/workbench/:projectId/writing`.
2. `backend/modules/imports/parsers.py`, `backend/modules/imports/services.py`, backend tests, and `frontend-console/e2e/import-errors.spec.js` treat an empty file as one empty chapter; the core document requires failed import record and no `writing_drafts`.
3. `frontend-console/e2e/scenario-coverage.md` marks all scenarios as covered while also listing partial coverage for async deep import, foreshadow/reveal CRUD, RAG parent-child/degraded retrieval, and Context character perspective.
4. Deep import browser tests do not prove the real async worker path keeps running after browser close; `deep-import-real.spec.js` uses `/api/imports/deep/sync`.
5. Foreshadow/reveal management is only list/status for foreshadowing and read-only for reveals in the frontend; backend routes expose list/update only, despite the data contract saying INSERT/UPDATE/DELETE are supported.
6. RAG and Context E2Es are page/entry tests; backend has deeper unit coverage, but browser acceptance does not prove parent-child retrieval, embedding degradation warning, or character-perspective hidden-truth handling.

## File Structure

- Modify: `frontend-console/views/projectView.js` — route project open/create to writing view.
- Modify: `frontend-console/tests/projectView.test.js` — assert writing route contract.
- Modify: `frontend-console/e2e/project.spec.js` — assert URL/view after creation and list selection.
- Modify: `backend/modules/imports/parsers.py` — return no chapters for empty/whitespace-only parsed text.
- Modify: `backend/modules/imports/services.py` — mark empty/no-effective-chapter imports failed with the documented message.
- Modify: `backend/modules/imports/tests/test_imports.py` — parser/service failure tests.
- Modify: `frontend-console/e2e/import-errors.spec.js` — assert empty file failure in UI.
- Modify: `frontend-console/e2e/scenario-coverage.md` — downgrade overstated rows and record true coverage.
- Modify: `backend/modules/outline/api.py` — add foreshadowing/reveal create/delete routes if implementing full management.
- Modify: `backend/modules/outline/schemas.py` — add create schemas for foreshadowing/reveal if missing.
- Modify: `frontend-console/api.js` — add create/delete clients for foreshadowing/reveal.
- Modify: `frontend-console/views/outlineView.js` — add minimal create/edit/delete/status UI for foreshadowing/reveal.
- Modify: `frontend-console/tests/outlineView.test.js` and `frontend-console/e2e/outline-scenes.spec.js` — cover management behavior.
- Modify or add: `frontend-console/e2e/deep-import-worker.spec.js` — real async worker acceptance.
- Modify: `frontend-console/e2e/rag.spec.js` and `frontend-console/e2e/context.spec.js` — add meaningful backend-backed assertions.

## Task 1: Restore Project Landing Route To Writing

**Files:**
- Modify: `frontend-console/views/projectView.js`
- Modify: `frontend-console/tests/projectView.test.js`
- Modify: `frontend-console/e2e/project.spec.js`

- [ ] **Step 1: Update failing unit expectations**

In `frontend-console/tests/projectView.test.js`, change the route assertions for `openProject()` and create success:

```javascript
expect(router.navigate).toHaveBeenCalledWith("writing")
```

Run:

```bash
cd frontend-console && npm test -- --run projectView.test.js
```

Expected before implementation: tests fail because current code calls `router.navigate("world", "objects")`.

- [ ] **Step 2: Update E2E contract**

In `frontend-console/e2e/project.spec.js`, rename the creation test to `创建项目并自动切换到写作视图` and assert:

```javascript
await expect(page.locator(SEL.viewTitle)).toHaveText("写作台", { timeout: 10000 })
await expect(page).toHaveURL(/\/workbench\/[^/]+\/writing/)
```

For the project-card selection path, add the same writing-view assertion after clicking the card.

- [ ] **Step 3: Fix project navigation**

In `frontend-console/views/projectView.js`, change both `openProject()` and create success:

```javascript
router.navigate("writing")
```

Keep `state.currentProjectId` and `state.currentProject` assignment unchanged.

- [ ] **Step 4: Verify route contract**

Run:

```bash
cd frontend-console && npm test -- --run projectView.test.js
cd frontend-console && npx playwright test project.spec.js project-recycle-bin.spec.js --reporter=list
```

Expected: project creation and project-card selection land on writing view; recycle bin remains green.

## Task 2: Make Empty File Import Fail As Documented

**Files:**
- Modify: `backend/modules/imports/parsers.py`
- Modify: `backend/modules/imports/services.py`
- Modify: `backend/modules/imports/tests/test_imports.py`
- Modify: `frontend-console/e2e/import-errors.spec.js`

- [ ] **Step 1: Write failing parser tests**

In `backend/modules/imports/tests/test_imports.py`, update `TestParseTxt.test_empty_content` and add whitespace coverage:

```python
def test_empty_content(self):
    """空字节内容不产生有效章节"""
    chapters = parse_txt(b"")
    assert chapters == []

def test_whitespace_only_content(self):
    """纯空白内容不产生有效章节"""
    chapters = parse_txt(" \n\t \n".encode())
    assert chapters == []
```

Run:

```bash
cd backend && pytest modules/imports/tests/test_imports.py::TestParseTxt -q
```

Expected before implementation: the empty test fails because current parser returns `全文`.

- [ ] **Step 2: Write failing service test**

Replace `TestImportService.test_upload_empty_file` with:

```python
@pytest.mark.asyncio
async def test_upload_empty_file_records_failed_status(
    self,
    service,
    db_session: AsyncSession,
    test_project_id: str,
):
    """空文件应记录 failed，不创建正文草稿"""
    with pytest.raises(HTTPException) as exc:
        await service.upload_and_import(
            db_session,
            test_project_id,
            "empty.txt",
            b"",
        )

    assert exc.value.status_code == 400
    assert "文件中未检测到有效章节" in str(exc.value.detail)

    records = await service.list_import_records(db_session, test_project_id)
    assert records.total == 1
    assert records.items[0].status == "failed"
    assert records.items[0].error_message == "文件中未检测到有效章节"

    from modules.writing.models import WritingDraft

    result = await db_session.execute(
        select(WritingDraft).where(WritingDraft.novel_id == uuid.UUID(test_project_id))
    )
    assert list(result.scalars().all()) == []
```

Run:

```bash
cd backend && pytest modules/imports/tests/test_imports.py::TestImportService::test_upload_empty_file_records_failed_status -q
```

Expected before implementation: fails because current service returns `done`.

- [ ] **Step 3: Implement parser empty-content behavior**

In `backend/modules/imports/parsers.py`, update `split_chapters()`:

```python
def split_chapters(text: str) -> list[dict[str, str]]:
    """按章节模式分割文本，返回 [{title, content}]"""
    if not text or not text.strip():
        return []
    ...
```

Keep normal no-heading prose as one `全文` chapter.

- [ ] **Step 4: Implement service failure message**

In `backend/modules/imports/services.py`, change the `total == 0` branch:

```python
if total == 0:
    await self._repo.update_status(
        db,
        record.id,
        status="failed",
        error_message="文件中未检测到有效章节",
    )
    raise HTTPException(
        status_code=http_status.HTTP_400_BAD_REQUEST,
        detail="文件中未检测到有效章节",
    )
```

Do not create `WritingDraft` rows or enqueue `publish_chapter` / `rag_index_chapter`.

- [ ] **Step 5: Update empty-file E2E**

In `frontend-console/e2e/import-errors.spec.js`, rename the test to `上传空文件标记导入失败且不创建章节` and assert:

```javascript
await expect(page.locator(SEL.toastContainer)).toContainText("文件中未检测到有效章节", { timeout: 15000 })
await expect(page.locator("#import-list-body")).toContainText("失败", { timeout: 15000 })
```

- [ ] **Step 6: Verify imports**

Run:

```bash
cd backend && pytest modules/imports/tests/test_imports.py -q
cd frontend-console && npx playwright test import.spec.js import-errors.spec.js --reporter=list
```

Expected: legal imports still succeed; unsupported format, oversized file, and empty file match the core document.

## Task 3: Correct Scenario Coverage Matrix

**Files:**
- Modify: `frontend-console/e2e/scenario-coverage.md`

- [ ] **Step 1: Reclassify status labels**

Change the legend to distinguish full scenario coverage from partial route coverage:

```markdown
- `✅ 场景闭环`：文档中该场景的主要正常流、异常流、边界流均有自动化断言。
- `🟡 部分覆盖`：已有页面/API/基础 E2E，但至少一个文档化操作路径未断言或未实现。
- `⏳ 待实现`：功能或测试缺失，不能作为验收依据。
```

- [ ] **Step 2: Downgrade overstated rows**

Set these rows to `🟡 部分覆盖` until later tasks pass:

```markdown
| 场景 3 深度导入流水线 | R2 | `imports`, `outline`, `world`, `memory` | `writingView` | workflow 集成 + deep-import E2E | 🟡 部分覆盖 |
| 场景 6 大纲与结构管理 | R4 | `outline`, `context` | `outlineView` | outline 单测 + outline E2E | 🟡 部分覆盖 |
| A1 RAG 混合检索 | R6 | `rag` | `ragView` | rag 单测 + rag E2E | 🟡 部分覆盖 |
| A2 上下文编译 | R6 | `context`, `world`, `outline`, `rag` | `contextView` | context 单测 + context E2E | 🟡 部分覆盖 |
```

After Task 1 and Task 2 pass, keep 场景 1 and 场景 2 as `✅ 场景闭环`.

- [ ] **Step 3: Fix false detailed statements**

Replace:

```markdown
空文件解析为空章节
```

with:

```markdown
空文件导入失败，不创建章节
```

Replace any statement that says async deep import is fully covered with:

```markdown
当前覆盖异步任务提交、轮询 UI 和同步真实流水线；浏览器关闭后 worker 继续执行仍待 `deep-import-worker.spec.js` 验证。
```

- [ ] **Step 4: Verify markdown references**

Run:

```bash
rg -n "空文件解析为空章节|✅ 已覆盖|全部通过" frontend-console/e2e/scenario-coverage.md
```

Expected: no row claims full coverage for known partial scenarios; no stale empty-file wording remains.

## Task 4: Add Real Async Deep Import Worker Acceptance

**Files:**
- Add: `frontend-console/e2e/deep-import-worker.spec.js`
- Modify if needed: `frontend-console/e2e/helpers/api-client.js`
- Verify: `backend/modules/imports/tasks.py`
- Verify: `backend/modules/imports/tests/test_workflow.py`

- [ ] **Step 1: Add task polling helper**

In `frontend-console/e2e/helpers/api-client.js`, add:

```javascript
export async function getTask(taskId) {
  const resp = await fetch(`${API_BASE}/tasks/${taskId}`)
  if (!resp.ok) {
    const text = await resp.text()
    throw new Error(`Task ${taskId} failed (${resp.status}): ${text}`)
  }
  return resp.json()
}
```

- [ ] **Step 2: Add worker-backed E2E**

Create `frontend-console/e2e/deep-import-worker.spec.js`:

```javascript
import { test, expect } from "@playwright/test"
import { createProject, cleanupProject, waitForBackend, getTask } from "./helpers/api-client.js"

const API_BASE = "http://localhost:8000/api"

test.describe("深度导入异步 Worker", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await cleanupProject(testProjectId) } catch {}
      testProjectId = null
    }
  })

  test("提交异步深度导入后关闭页面，worker 继续推进任务状态", async ({ page }) => {
    const project = await createProject({ title: "异步深度导入验收", genre: "fantasy", language: "zh" })
    testProjectId = project.id

    const upload = await page.evaluate(async ({ apiBase, projectId }) => {
      const file = new File([
        "第一章\n主角进入古城。\n\n第二章\n他发现密室。\n\n第三章\n线索指向旧王。",
      ], "worker-import.txt", { type: "text/plain" })
      const form = new FormData()
      form.append("novel_id", projectId)
      form.append("file", file)
      const resp = await fetch(`${apiBase}/imports/upload`, { method: "POST", body: form })
      if (!resp.ok) throw new Error(await resp.text())
      return resp.json()
    }, { apiBase: API_BASE, projectId: testProjectId })
    expect(upload.imported_chapters).toBe(3)

    const submitted = await page.evaluate(async ({ apiBase, projectId }) => {
      const resp = await fetch(`${apiBase}/imports/deep`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ novel_id: projectId, start_chapter: 1, end_chapter: 3 }),
      })
      if (!resp.ok) throw new Error(await resp.text())
      return resp.json()
    }, { apiBase: API_BASE, projectId: testProjectId })

    expect(submitted.task_id).toBeTruthy()
    await page.close()

    let finalTask = null
    for (let i = 0; i < 80; i += 1) {
      finalTask = await getTask(submitted.task_id)
      if (["done", "failed"].includes(finalTask.status)) break
      await new Promise((resolve) => setTimeout(resolve, 1500))
    }

    expect(finalTask.status).toBe("done")
    expect(finalTask.result.phase).toBe("done")
    expect(finalTask.result.completed_steps).toContain("scene_segmentation")
    expect(finalTask.result.completed_steps).toContain("entity_extraction")
    expect(finalTask.result.completed_steps).toContain("structure_analysis")
  })
})
```

This test requires backend, frontend test server, database, and worker to be running. If the standard Playwright setup does not start the worker, document that in the test file header and run it in the worker-enabled E2E target.

- [ ] **Step 3: Verify backend task progress still passes**

Run:

```bash
cd backend && pytest modules/imports/tests/test_workflow.py modules/imports/tests/test_imports_integration.py -q
```

Expected: workflow phase progress and task result updates pass.

- [ ] **Step 4: Run worker E2E in worker-enabled environment**

Run:

```bash
cd frontend-console && npx playwright test deep-import-worker.spec.js --reporter=list
```

Expected: task reaches `done` after the page is closed. If it fails because no worker is running, start the project with `make dev` and rerun.

## Task 5: Complete Foreshadowing And Reveal Management Or Mark It Deferred Consistently

**Files:**
- Modify: `backend/modules/outline/schemas.py`
- Modify: `backend/modules/outline/api.py`
- Modify: `backend/modules/outline/tests/test_foreshadowing_reveal.py`
- Modify: `frontend-console/api.js`
- Modify: `frontend-console/views/outlineView.js`
- Modify: `frontend-console/tests/outlineView.test.js`
- Modify: `frontend-console/e2e/outline-scenes.spec.js`

- [ ] **Step 1: Add backend create/delete tests**

In `backend/modules/outline/tests/test_foreshadowing_reveal.py`, add API tests for:

```python
POST /api/outline/foreshadowing?novel_id=<id>
DELETE /api/outline/foreshadowing/{plan_id}?novel_id=<id>
POST /api/outline/reveals?novel_id=<id>
DELETE /api/outline/reveals/{plan_id}?novel_id=<id>
```

For foreshadowing create body:

```python
{
    "name": "铜铃伏笔",
    "summary": "铜铃只在危险靠近时响",
    "planned_seed_chapter": 1,
    "planned_payoff_chapter": 8,
    "status": "draft",
}
```

For reveal create body:

```python
{
    "target_type": "entity",
    "target_id": str(uuid.uuid4()),
    "secret_summary": "铜铃属于旧王密探",
    "reveal_stages": [
        {"stage_index": 0, "chapter_index": 3, "reveal_content": "铜铃第一次自鸣"}
    ],
    "status": "draft",
}
```

Run:

```bash
cd backend && pytest modules/outline/tests/test_foreshadowing_reveal.py -q
```

Expected before implementation: create/delete route tests fail with 405/404.

- [ ] **Step 2: Add create schemas and routes**

In `backend/modules/outline/schemas.py`, add:

```python
class ForeshadowingPlanCreate(ForeshadowingPlanUpdate):
    name: Annotated[str, Field(min_length=1, max_length=255)]

class RevealPlanCreate(RevealPlanUpdate):
    target_type: Annotated[str, Field(max_length=32)]
    target_id: str
    secret_summary: str
```

In `backend/modules/outline/api.py`, add thin routes that delegate to existing services:

```python
@router.post("/foreshadowing", response_model=ForeshadowingPlanResponse, status_code=201)
async def api_create_foreshadowing(db: DbSession, data: ForeshadowingPlanCreate, novel_id: str = Query(...)):
    return await _foreshadowing_service.create(db, data, novel_id=novel_id)

@router.delete("/foreshadowing/{plan_id}", status_code=204)
async def api_delete_foreshadowing(db: DbSession, plan_id: str, novel_id: str = Query(...)):
    await _foreshadowing_service.delete(db, plan_id, novel_id=novel_id)

@router.post("/reveals", response_model=RevealPlanResponse, status_code=201)
async def api_create_reveal(db: DbSession, data: RevealPlanCreate, novel_id: str = Query(...)):
    return await _reveal_service.create(db, data, novel_id=novel_id)

@router.delete("/reveals/{plan_id}", status_code=204)
async def api_delete_reveal(db: DbSession, plan_id: str, novel_id: str = Query(...)):
    await _reveal_service.delete(db, plan_id, novel_id=novel_id)
```

If `CrudService.create/delete` signatures differ, use the existing `SceneService` or `PlotThreadService` route pattern in the same module.

- [ ] **Step 3: Add frontend API clients**

In `frontend-console/api.js`, add:

```javascript
async createForeshadowing(novelId, payload) {
  return request(`/outline/foreshadowing${buildQueryString({ novel_id: novelId })}`, {
    method: "POST",
    body: JSON.stringify(payload),
  })
},
async deleteForeshadowing(id, novelId) {
  return request(`/outline/foreshadowing/${id}${buildQueryString({ novel_id: novelId })}`, {
    method: "DELETE",
  })
},
async createReveal(novelId, payload) {
  return request(`/outline/reveals${buildQueryString({ novel_id: novelId })}`, {
    method: "POST",
    body: JSON.stringify(payload),
  })
},
async deleteReveal(id, novelId) {
  return request(`/outline/reveals/${id}${buildQueryString({ novel_id: novelId })}`, {
    method: "DELETE",
  })
},
```

- [ ] **Step 4: Add minimal management UI**

In `frontend-console/views/outlineView.js`:

Add a `data-action="create-foreshadowing"` button above the foreshadowing table and empty state. Its handler opens a modal with `name`, `summary`, `planned_seed_chapter`, `planned_payoff_chapter`, and `status`.

Add a `data-action="delete-foreshadowing"` button per row and delete through `api.outline.deleteForeshadowing(id, state.currentProjectId)` after `confirmAction`.

Add a `data-action="create-reveal"` button above reveals and a `data-action="delete-reveal"` button per row. The reveal modal should collect `target_type`, `target_id`, `secret_summary`, first-stage `chapter_index`, and `reveal_content`.

Keep all user/AI text escaped with `esc()`.

- [ ] **Step 5: Add frontend tests**

In `frontend-console/tests/outlineView.test.js`, add tests that:

```javascript
expect(html).toContain('data-action="create-foreshadowing"')
expect(html).toContain('data-action="create-reveal"')
```

and mock successful `api.outline.createForeshadowing`, `deleteForeshadowing`, `createReveal`, and `deleteReveal`.

- [ ] **Step 6: Add E2E coverage**

In `frontend-console/e2e/outline-scenes.spec.js`, extend `管理伏笔与揭示计划`:

```javascript
await page.locator('[data-action="nav-foreshadowing"]').click()
await page.locator('[data-action="create-foreshadowing"]').click()
await page.locator("#foreshadowing-name").fill("铜铃伏笔")
await page.locator("#foreshadowing-summary").fill("铜铃只在危险靠近时响")
await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
await expect(page.locator("table")).toContainText("铜铃伏笔")

await page.locator(".foreshadowing-status-select").first().selectOption("active")
await expect(page.locator(SEL.toastContainer)).toContainText("伏笔状态已更新")

await page.locator('[data-action="nav-reveals"]').click()
await page.locator('[data-action="create-reveal"]').click()
await page.locator("#reveal-secret").fill("铜铃属于旧王密探")
await page.locator("#reveal-target-id").fill("00000000-0000-0000-0000-000000000001")
await page.locator("#reveal-stage-chapter").fill("3")
await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
await expect(page.locator("table")).toContainText("铜铃属于旧王密探")
```

- [ ] **Step 7: Verify outline**

Run:

```bash
cd backend && pytest modules/outline/tests/test_foreshadowing_reveal.py -q
cd frontend-console && npm test -- --run outlineView.test.js
cd frontend-console && npx playwright test outline-scenes.spec.js outline-threads-arcs.spec.js --reporter=list
```

Expected: foreshadowing and reveal management has real create/list/update/delete coverage.

If product decision is to keep this deferred instead, do not implement this task. Instead update `docs/核心业务场景与预期行为.md` and `scenario-coverage.md` to mark front-end management as deferred consistently.

## Task 6: Add Meaningful RAG And Context Browser Acceptance

**Files:**
- Modify: `frontend-console/e2e/rag.spec.js`
- Modify: `frontend-console/e2e/context.spec.js`
- Modify helpers if needed: `frontend-console/e2e/helpers/api-client.js`

- [ ] **Step 1: Add RAG API-backed retrieval test**

In `frontend-console/e2e/rag.spec.js`, add a test that creates a chunk through `/api/rag/chunks`, searches it from the UI, and asserts the text appears:

```javascript
await page.evaluate(async ({ projectId }) => {
  const resp = await fetch(`http://localhost:8000/api/rag/chunks?novel_id=${projectId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      source_type: "chapter",
      source_id: "chapter-1",
      chapter_index: 1,
      chunk_index: 0,
      start_offset: 0,
      end_offset: 12,
      text: "铜铃在雨夜响起",
      summary: "铜铃异常",
      entity_ids: [],
      character_ids: [],
      thread_ids: [],
      visibility: "author_only",
      importance: 0.8,
      embedding_status: "failed",
      embedding_error: "test embedding unavailable",
      index_warnings: ["embedding 降级为关键词检索"],
    }),
  })
  if (!resp.ok) throw new Error(await resp.text())
}, { projectId: testProjectId })

await page.locator('.subnav-item[data-action="nav-search"]').click()
await page.locator("#rag-search-input").fill("铜铃")
await page.locator('[data-action="do-search"]').click()
await expect(page.locator("#rag-results")).toContainText("铜铃在雨夜响起", { timeout: 10000 })
```

If the current UI does not display result warnings, add display of `data.warnings` and assert it contains `embedding`.

- [ ] **Step 2: Add direct API degraded retrieval assertion**

Still in `rag.spec.js`, call `/api/rag/retrieve` directly after creating the failed-embedding chunk:

```javascript
const result = await page.evaluate(async ({ projectId }) => {
  const resp = await fetch(`http://localhost:8000/api/rag/retrieve?novel_id=${projectId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query: "铜铃", mode: "search", top_k: 5 }),
  })
  if (!resp.ok) throw new Error(await resp.text())
  return resp.json()
}, { projectId: testProjectId })

expect(result.chunks.some((chunk) => chunk.text.includes("铜铃"))).toBeTruthy()
expect(Array.isArray(result.warnings)).toBeTruthy()
```

- [ ] **Step 3: Add Context hidden-truth browser assertion**

In `frontend-console/e2e/context.spec.js`, create a character/entity/knowledge fixture through backend APIs or, if a compact backend API fixture is not available, route `/api/context/render` twice with deterministic responses and verify the UI sends different `reveal_mode` values:

```javascript
const requests = []
await page.route("**/api/context/render", async (route) => {
  const body = route.request().postDataJSON()
  requests.push(body)
  const markdown = body.reveal_mode === "character"
    ? "POV Knowledge\n角色误以为铜铃只是普通遗物"
    : "Author Notes\n隐藏真相：铜铃属于旧王密探"
  await route.fulfill({
    status: 200,
    body: JSON.stringify({
      markdown,
      compile_info: {
        novel_id: body.novel_id,
        task: body.task,
        scope: body.scope,
        reveal_mode: body.reveal_mode,
        budgets: [],
        warnings: [],
        section_count: 1,
        sections_present: ["POV Knowledge"],
      },
    }),
  })
})
```

Then:

```javascript
await page.locator("#ctx-reveal").selectOption("character")
await page.locator("#ctx-task").fill("写角色视角场景")
await page.locator('[data-action="compile"]').click()
await expect(page.locator("#ctx-output")).toContainText("误以为")
await expect(page.locator("#ctx-output")).not.toContainText("隐藏真相")
expect(requests.at(-1).reveal_mode).toBe("character")
```

This browser test validates frontend contract. Keep backend hidden-truth behavior covered by `backend/modules/context/tests/test_context.py`.

- [ ] **Step 4: Run focused tests**

```bash
cd backend && pytest modules/rag/tests/test_rag.py modules/context/tests/test_context.py -q
cd frontend-console && npx playwright test rag.spec.js context.spec.js --reporter=list
```

Expected: browser tests prove actual RAG result rendering and Context reveal-mode contract, not only page loading.

## Task 7: Final Scenario Verification And Documentation Sync

**Files:**
- Modify: `frontend-console/e2e/scenario-coverage.md`
- Modify if needed: `docs/核心业务场景与预期行为.md`

- [ ] **Step 1: Run full focused backend suite**

```bash
cd backend && pytest modules/project/tests/test_project.py modules/imports/tests/test_imports.py modules/imports/tests/test_workflow.py modules/writing/tests/test_writing.py modules/outline/tests/test_scene.py modules/outline/tests/test_foreshadowing_reveal.py modules/world/tests/test_world.py modules/rag/tests/test_rag.py modules/context/tests/test_context.py tests/integration/test_novel_id_isolation.py -q --tb=short
```

Expected: all tests pass. The existing async mock warning in imports workflow should either be fixed or recorded in final notes if still present.

- [ ] **Step 2: Run frontend unit and syntax checks**

```bash
cd frontend-console && npm test
cd frontend-console && node --check app.js && node --check api.js
```

Expected: all Vitest files pass; syntax checks exit 0.

- [ ] **Step 3: Run scenario E2E bundle**

```bash
cd frontend-console && npx playwright test project.spec.js project-recycle-bin.spec.js import.spec.js import-errors.spec.js deep-import.spec.js writing.spec.js writing-conflict.spec.js world.spec.js world-relations-aliases.spec.js outline-scenes.spec.js outline-threads-arcs.spec.js rag.spec.js context.spec.js --reporter=list
```

Expected: scenario bundle passes.

- [ ] **Step 4: Run worker-only deep import E2E where supported**

With backend worker running:

```bash
cd frontend-console && npx playwright test deep-import-worker.spec.js --reporter=list
```

Expected: async deep import reaches `done` after page close.

- [ ] **Step 5: Update coverage matrix honestly**

Update `frontend-console/e2e/scenario-coverage.md` with the exact date, commands, and pass counts. Only mark a row `✅ 场景闭环` when its documented normal, abnormal, and boundary paths are either implemented and tested or explicitly deferred in `docs/核心业务场景与预期行为.md`.

- [ ] **Step 6: Sync core scenario document only if product scope changes**

If Task 5 is not implemented and foreshadow/reveal UI remains deferred, update `docs/核心业务场景与预期行为.md` to keep this statement explicit in both the scenario text and coverage matrix. If Task 5 is implemented, remove the stale deferred wording and describe the actual UI operations.

## Self-Review Checklist

- [ ] Task 1 maps to 场景 1 normal create/list selection route.
- [ ] Task 2 maps to 场景 2 empty-file boundary flow.
- [ ] Task 3 prevents coverage reporting from hiding partial acceptance.
- [ ] Task 4 maps to 场景 3 browser-close async workflow.
- [ ] Task 5 maps to 场景 6 foreshadowing/reveal data contract.
- [ ] Task 6 maps to Appendix A1/A2 browser acceptance.
- [ ] Task 7 provides final verification commands and doc sync rules.
