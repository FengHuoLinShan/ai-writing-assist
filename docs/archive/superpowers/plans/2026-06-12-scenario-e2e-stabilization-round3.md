# Scenario E2E Stabilization Round 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the documented scenario paths executable and trustworthy by fixing broken Playwright setup, then closing the remaining explicit user-path gaps.

**Architecture:** Do not rework the backend capabilities that already pass focused tests. First stabilize the E2E harness with shared helpers and real fixtures; then add the smallest vertical slices for rollback, foreshadow/reveal UI, and async deep-import polling. Keep module boundaries intact: frontend uses `api.js`; backend cross-module calls use `contracts.py` / `facade.py`.

**Tech Stack:** FastAPI, async SQLAlchemy, PostgreSQL-backed `async_tasks`, vanilla JS SPA, Vitest, Playwright.

---

## Verified Baseline

Fresh validation on 2026-06-12:

```bash
cd backend && pytest modules/project/tests/test_project.py modules/imports/tests/test_imports.py modules/writing/tests/test_writing.py modules/outline/tests/test_scene.py modules/outline/tests/test_foreshadowing_reveal.py modules/world/tests/test_world.py modules/rag/tests/test_indexing.py modules/context/tests/test_context.py tests/unit/test_context.py tests/unit/test_world_services_revision_event_helpers.py -q --tb=short
# 318 passed

cd frontend-console && npm test -- --run projectView.test.js writingView.test.js worldView.test.js outlineView.test.js xss-rendering.test.js
# 5 files, 91 tests passed

cd frontend-console && node --check api.js
# exit 0

cd frontend-console && npx playwright test project-recycle-bin.spec.js import-errors.spec.js writing-conflict.spec.js world.spec.js outline-scenes.spec.js --reporter=list
# 21 tests: 19 failed, 2 skipped
```

Do not mark any scenario as E2E-covered until the relevant Playwright test passes in the command above or in the full scenario command at the end of this plan.

## File Structure

- Create: `frontend-console/e2e/helpers/workbench.js` — common project setup and reliable route entry helpers.
- Create: `frontend-console/e2e/helpers/fixtures/test.pdf` — tiny invalid-format fixture.
- Create: `frontend-console/e2e/helpers/fixtures/empty.txt` — empty import fixture.
- Modify: `frontend-console/e2e/import-errors.spec.js` — use real helper and fixtures; add empty-file assertion.
- Modify: `frontend-console/e2e/project-recycle-bin.spec.js` — use stable project list/recycle-bin setup.
- Modify: `frontend-console/e2e/writing-conflict.spec.js` — enter `/workbench/:id/writing` directly.
- Modify: `frontend-console/e2e/world.spec.js` — enter `/workbench/:id/world` directly; unskip rollback after seed helper exists.
- Modify: `frontend-console/e2e/world-relations-aliases.spec.js` — use the shared helper.
- Modify: `frontend-console/e2e/outline-scenes.spec.js` — enter `/workbench/:id/outline` directly; add foreshadow/reveal UI tests after UI exists.
- Modify: `frontend-console/e2e/outline-threads-arcs.spec.js`, `writing.spec.js`, `rag.spec.js`, `context.spec.js`, `deep-import.spec.js`, `deep-import-real.spec.js`, `generate.spec.js` — replace repeated localStorage/reload navigation with helper.
- Modify: `frontend-console/e2e/helpers/api-client.js` — add TextArchive/revision seed route helper only if a public/test-safe backend API already exists; otherwise add backend test-only route under explicit E2E guard.
- Modify: `backend/modules/world/api.py`, `backend/modules/world/tests/test_world.py` — only if needed for a safe rollback seed path.
- Modify: `frontend-console/api.js`, `frontend-console/views/outlineView.js`, `frontend-console/tests/outlineView.test.js` — add foreshadow/reveal UI user path.
- Modify: `frontend-console/e2e/scenario-coverage.md` — sync status after tests pass.

## Task 1: Stabilize E2E Workbench Entry

**Files:**
- Create: `frontend-console/e2e/helpers/workbench.js`
- Modify: all scenario E2E specs that currently call `localStorage.setItem("novel_currentProjectId", ...)` followed by sidebar clicks.

- [ ] **Step 1: Add shared helper**

Create `frontend-console/e2e/helpers/workbench.js`:

```javascript
import { expect } from "@playwright/test"
import { SEL } from "./selectors.js"

export async function openWorkbench(page, project, view = "writing", subview = null) {
  const hash = subview
    ? `#/workbench/${project.id}/${view}/${subview}`
    : `#/workbench/${project.id}/${view}`
  await page.goto(`/${hash}`)
  await page.evaluate((projectData) => {
    localStorage.setItem("novel_currentProjectId", projectData.id)
    localStorage.setItem("novel_currentProject", JSON.stringify(projectData))
  }, project)
  await page.reload()
  const expectedTitle = {
    writing: "手动工作台",
    world: "世界对象",
    outline: "大纲",
    rag: "RAG 检索",
    context: "上下文",
    generate: "生成中心",
    project: "项目",
  }[view]
  await expect(page.locator(SEL.viewTitle)).toHaveText(expectedTitle, { timeout: 10000 })
}

export async function openProjectList(page) {
  await page.goto("/#project")
  await expect(page.locator(SEL.viewTitle)).toHaveText("项目", { timeout: 10000 })
  await expect(page.locator(SEL.workspaceContent)).not.toContainText("加载中", { timeout: 10000 })
}
```

- [ ] **Step 2: Convert one failing spec first**

In `frontend-console/e2e/world.spec.js`, replace the localStorage/reload/nav block with:

```javascript
import { openWorkbench } from "./helpers/workbench.js"

// inside beforeEach after createProject(...)
await openWorkbench(page, project, "world", "objects")
```

- [ ] **Step 3: Run the converted spec**

```bash
cd frontend-console && npx playwright test world.spec.js --reporter=list
```

Expected before further business fixes: navigation-related failures disappear. If rollback remains `fixme`, it should be reported as skipped, not failed.

- [ ] **Step 4: Convert the rest**

Apply the same pattern:

```javascript
await openWorkbench(page, project, "outline", "scenes")
await openWorkbench(page, project, "writing")
await openWorkbench(page, project, "rag", "status")
await openWorkbench(page, project, "context")
await openWorkbench(page, project, "generate")
```

Use `openProjectList(page)` for project-list-only specs.

- [ ] **Step 5: Run the previously failing bundle**

```bash
cd frontend-console && npx playwright test project-recycle-bin.spec.js import-errors.spec.js writing-conflict.spec.js world.spec.js outline-scenes.spec.js --reporter=list
```

Expected: no failures caused by staying on `#view-title = 项目`.

## Task 2: Fix Import Error E2E Fixtures and Assertions

**Files:**
- Create: `frontend-console/e2e/helpers/fixtures/test.pdf`
- Create: `frontend-console/e2e/helpers/fixtures/empty.txt`
- Modify: `frontend-console/e2e/import-errors.spec.js`

- [ ] **Step 1: Add tiny invalid-format fixture**

Create `frontend-console/e2e/helpers/fixtures/test.pdf` with plain text bytes:

```text
not a real pdf; used only to verify unsupported extension handling
```

- [ ] **Step 2: Add empty fixture**

Create `frontend-console/e2e/helpers/fixtures/empty.txt` as a zero-byte file.

- [ ] **Step 3: Replace oversized physical fixture with in-browser file**

In `import-errors.spec.js`, replace `oversized.bin` usage with:

```javascript
await page.locator("#pv-import-file").setInputFiles({
  name: "oversized.txt",
  mimeType: "text/plain",
  buffer: Buffer.alloc(50 * 1024 * 1024 + 1),
})
```

- [ ] **Step 4: Add empty-file scenario**

Append:

```javascript
test("上传空文件提示未检测到有效章节", async ({ page }) => {
  await page.locator('[data-action="toggle-import"]').click()
  await expect(page.locator("#pv-import-file")).toBeVisible()

  const filePath = path.join(__dirname, "helpers", "fixtures", "empty.txt")
  await page.locator("#pv-import-file").setInputFiles(filePath)
  await page.locator('[data-action="upload-file"]').click()

  await expect(page.locator(SEL.toastContainer)).toContainText("未检测到有效章节", { timeout: 15000 })
})
```

- [ ] **Step 5: Run import E2E**

```bash
cd frontend-console && npx playwright test import-errors.spec.js import.spec.js --reporter=list
```

Expected: supported import and three error paths pass.

## Task 3: Add Entity Rollback E2E Seed Path

**Files:**
- Modify: `backend/modules/world/api.py`
- Modify: `backend/modules/world/tests/test_world.py`
- Modify: `frontend-console/e2e/helpers/api-client.js`
- Modify: `frontend-console/e2e/world.spec.js`

- [ ] **Step 1: Prefer existing public behavior**

First check whether normal entity update writes `TextArchive`:

```bash
cd backend && pytest modules/world/tests/test_world.py::test_rollback_entity_route_uses_scene_index -q --tb=short
```

If yes, use normal API updates to seed rollback data. If no, add a test-only E2E seed route guarded by environment variable.

- [ ] **Step 2: Add backend test for guarded seed route only if needed**

If needed, add a route available only when `APP_ENV == "test"`:

```python
@router.post("/_test/entities/{entity_id}/text-archive")
async def seed_entity_text_archive(...):
    if settings.app_env != "test":
        raise HTTPException(status_code=404, detail="Not found")
```

The route must require `novel_id`, validate entity ownership, and insert only `TextArchive` rows for the requested entity.

- [ ] **Step 3: Add E2E helper**

In `api-client.js`:

```javascript
export async function seedEntityArchive(novelId, entityId, payload) {
  return request(`/world/_test/entities/${entityId}/text-archive?novel_id=${encodeURIComponent(novelId)}`, {
    method: "POST",
    body: JSON.stringify(payload),
  })
}
```

- [ ] **Step 4: Unskip rollback test**

Replace `test.fixme("回滚实体到指定场景索引"...` with a normal test that seeds archive data, clicks rollback, and verifies the displayed entity summary changed to the earlier archived value.

- [ ] **Step 5: Run backend and E2E**

```bash
cd backend && pytest modules/world/tests/test_world.py -q --tb=short
cd frontend-console && npx playwright test world.spec.js --reporter=list
```

Expected: rollback test passes; no test-only route is available outside test env.

## Task 4: Add Foreshadowing / Reveal User Path

**Files:**
- Modify: `frontend-console/api.js`
- Modify: `frontend-console/views/outlineView.js`
- Modify: `frontend-console/tests/outlineView.test.js`
- Modify: `frontend-console/e2e/outline-scenes.spec.js`

- [ ] **Step 1: Add frontend unit test for new sub-tabs**

In `outlineView.test.js`, add tests that render `foreshadowing` and `reveals` subviews and assert:

```javascript
expect(document.body.textContent).toContain("伏笔")
expect(document.body.textContent).toContain("揭示")
```

- [ ] **Step 2: Add outline subviews**

Extend the route or local subnav so `outlineView` exposes:

```javascript
["scenes", "threads", "arcs", "foreshadowing", "reveals"]
```

If changing router route config, update `router.js` and existing route tests.

- [ ] **Step 3: Implement list/update UI**

Use existing API clients:

```javascript
api.outline.listForeshadowing(state.currentProjectId)
api.outline.updateForeshadowing(id, payload, state.currentProjectId)
api.outline.listReveals(state.currentProjectId)
api.outline.updateReveal(id, payload, state.currentProjectId)
```

Minimum UI:

- list name/summary/status/planned payoff chapter
- status select for foreshadowing
- reveal stage summary display
- refresh after update

- [ ] **Step 4: Unskip E2E**

Replace `test.fixme("管理伏笔与揭示计划"...` with a test that seeds plans by API, opens the new sub-tab, changes status, and verifies refresh.

- [ ] **Step 5: Run tests**

```bash
cd frontend-console && npm test -- --run outlineView.test.js
cd frontend-console && npx playwright test outline-scenes.spec.js --reporter=list
```

Expected: outline user path covers Scene CRUD, reorder, AI generate modal, and foreshadow/reveal management.

## Task 5: Cover Async Deep Import Recovery Path

**Files:**
- Modify: `frontend-console/e2e/deep-import.spec.js`
- Modify: `backend/modules/imports/tests/test_workflow.py`
- Modify: `frontend-console/tests/writingView.test.js`
- Modify: `frontend-console/views/writingView.js` only if polling recovery is missing.

- [ ] **Step 1: Add backend task-progress assertion**

Add a backend test that invokes `handle_deep_import` with mocked workflow steps and asserts `task.result` is updated at phase boundaries.

- [ ] **Step 2: Add frontend recovery test**

In `writingView.test.js`, verify that when localStorage contains a running deep-import task id, entering writing view calls `api.tasks.get(taskId)` and renders the current phase message.

- [ ] **Step 3: Add Playwright async recovery test**

In `deep-import.spec.js`, mock `/api/imports/deep` and `/api/tasks/:id` as running, reload the page, and assert the progress panel is restored.

- [ ] **Step 4: Keep sync real E2E separate**

Keep `deep-import-real.spec.js` as a synchronous smoke test, but rename its scenario text to make clear it verifies `/api/imports/deep/sync`, not the async browser-close workflow.

- [ ] **Step 5: Run tests**

```bash
cd backend && pytest modules/imports/tests/test_workflow.py -q --tb=short
cd frontend-console && npm test -- --run writingView.test.js
cd frontend-console && npx playwright test deep-import.spec.js --reporter=list
```

Expected: async task polling and reload recovery are covered separately from sync deep import.

## Task 6: Sync Scenario Coverage

**Files:**
- Modify: `frontend-console/e2e/scenario-coverage.md`
- Modify: `docs/核心业务场景与预期行为.md` only if actual deferred scope changes.

- [ ] **Step 1: Update statuses only after passing commands**

Use these labels:

- `✅ 已覆盖` only when the referenced E2E passes.
- `🚧 已实现，E2E 待稳定` when unit/backend tests pass but Playwright still fails.
- `⏳ 待实现` for missing UI/API behavior.

- [ ] **Step 2: Correct stale entries**

Specifically update:

- project recycle-bin: from “待实现” to pass/fail status based on `project-recycle-bin.spec.js`
- import errors: include format, oversized, empty-file coverage
- world rollback: remove `test.fixme` only after Task 3
- outline foreshadow/reveal: remove `test.fixme` only after Task 4
- deep import: distinguish async task polling from sync smoke test

- [ ] **Step 3: Run final verification**

```bash
cd backend && pytest modules/project/tests/test_project.py modules/imports/tests/test_imports.py modules/imports/tests/test_workflow.py modules/writing/tests/test_writing.py modules/outline/tests/test_scene.py modules/outline/tests/test_foreshadowing_reveal.py modules/world/tests/test_world.py modules/rag/tests/test_indexing.py modules/context/tests/test_context.py tests/unit/test_context.py tests/unit/test_world_services_revision_event_helpers.py -q --tb=short
cd frontend-console && npm test
cd frontend-console && node --check api.js
cd frontend-console && npx playwright test project-recycle-bin.spec.js import.spec.js import-errors.spec.js deep-import.spec.js writing.spec.js writing-conflict.spec.js world.spec.js world-relations-aliases.spec.js outline-scenes.spec.js outline-threads-arcs.spec.js rag.spec.js context.spec.js --reporter=list
```

Expected: backend and frontend unit tests pass; all listed scenario E2E pass; any remaining deferred item is explicitly documented with a reason and not represented as covered.
