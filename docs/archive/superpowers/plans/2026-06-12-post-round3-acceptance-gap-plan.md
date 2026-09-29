# Post Round 3 Acceptance Gap Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining gaps found by acceptance validation against `docs/核心业务场景与预期行为.md`, so the documented user paths pass real browser-level verification.

**Architecture:** Fix real product entry points before stabilizing tests. Keep the existing vanilla JS SPA and FastAPI module boundaries. Frontend uses `api.js`; backend cross-module calls stay behind module APIs/facades. Do not introduce new framework, queue, database, or agent runtime.

**Tech Stack:** FastAPI, async SQLAlchemy, PostgreSQL-backed `async_tasks`, vanilla JS SPA, Vitest, Playwright.

---

## Verified Baseline

Validation run on 2026-06-12:

```bash
cd backend && pytest modules/project/tests/test_project.py modules/imports/tests/test_imports.py modules/imports/tests/test_workflow.py modules/writing/tests/test_writing.py modules/outline/tests/test_scene.py modules/outline/tests/test_foreshadowing_reveal.py modules/world/tests/test_world.py modules/rag/tests/test_rag.py modules/context/tests/test_context.py tests/integration/test_novel_id_isolation.py -q --tb=short
# 279 passed, 1 warning

cd frontend-console && npm test -- --run projectView.test.js writingView.test.js worldView.test.js outlineView.test.js xss-rendering.test.js
# 5 files, 102 tests passed

cd frontend-console && node --check api.js
# exit 0

cd frontend-console && npx playwright test project-recycle-bin.spec.js import.spec.js import-errors.spec.js deep-import.spec.js writing.spec.js writing-conflict.spec.js world.spec.js world-relations-aliases.spec.js outline-scenes.spec.js outline-threads-arcs.spec.js rag.spec.js context.spec.js --reporter=list
# 42 passed, 10 failed
```

Current failed Playwright paths:

- `deep-import.spec.js`: import from project view does not result in writing view with deep-import button.
- `outline-scenes.spec.js`: scene reorder assertion is unstable; AI generate modal close remains visible.
- `project-recycle-bin.spec.js`: page reload leaves project page stuck at loading, `.project-grid` absent.
- `world-relations-aliases.spec.js`: alias creation returns `数据格式校验失败：[object Object]`.
- `writing-conflict.spec.js`: expected 409 conflict toast is not shown; save succeeds as `已暂存`.
- `writing.spec.js`: split chapter returns backend connection error; cursor-linked scene panel and AI extraction dialog tests time out after reload.

## Acceptance Assessment

Round 3 made useful progress:

- Backend focused scenario tests pass.
- Frontend unit coverage for writing/outline/world/project passes.
- Deep-import progress recovery exists in `writingView`.
- Outline now exposes `foreshadowing` and `reveals` sub-tabs, and the empty-state E2E passes.
- `world.spec.js` now passes merge, rollback, and CharacterKnowledge paths.

Not accepted yet:

- The app entry script is still loaded as a classic script in `frontend-console/index.html`, while `frontend-console/app.js` contains `export default App`. The E2E helper explicitly bypasses this broken initialization. This is a product entry bug, not just a test issue.
- Several documented paths only pass via injected state or helper navigation; full user reload/navigation behavior is not trustworthy.
- `frontend-console/e2e/scenario-coverage.md` currently overstates some coverage because the scenario bundle still has 10 failures.

## File Structure

- Modify: `frontend-console/index.html` — load `app.js` as a module, or remove module syntax from `app.js`.
- Modify: `frontend-console/app.js` — keep browser startup and Vitest import compatible.
- Modify: `frontend-console/e2e/helpers/workbench.js` — stop compensating for broken App startup after it is fixed.
- Modify: `frontend-console/views/projectView.js` — ensure list refresh/reload and recycle-bin paths are robust.
- Modify: `frontend-console/api.js` — fix alias creation signature and error detail rendering.
- Modify: `frontend-console/views/worldView.js` — send alias payload/query matching backend schema.
- Modify: `frontend-console/views/writingView.js` — remove stale draft-id assumptions in split flow; ensure reload paths hydrate chapters/scenes.
- Modify: `frontend-console/e2e/*.spec.js` — replace direct state injection with stable user/API setup only where needed.
- Modify: `frontend-console/e2e/scenario-coverage.md` — update after final Playwright run.

## Task 1: Fix SPA Startup and Route Restoration

**Files:**
- Modify: `frontend-console/index.html`
- Modify: `frontend-console/app.js`
- Modify: `frontend-console/tests/xss-rendering.test.js`
- Modify: `frontend-console/e2e/helpers/workbench.js`

- [ ] **Step 1: Write a failing smoke test for app startup**

Add or update a Vitest smoke test that imports `app.js` in the same mode used by the browser and asserts `window.App` exists and can initialize without syntax errors.

Run:

```bash
cd frontend-console && npm test -- --run smoke.test.js xss-rendering.test.js
```

Expected before fix: fail or require the current workaround.

- [ ] **Step 2: Make script loading consistent**

Use one of these two approaches:

```html
<script type="module" src="app.js"></script>
```

or remove `export default App` from `app.js` and expose `window.App = App` only. Prefer the lower-impact option that keeps existing Vitest imports passing.

- [ ] **Step 3: Verify real page startup**

Run:

```bash
cd frontend-console && npx playwright test home.spec.js project.spec.js --reporter=list
```

Expected: sidebar navigation and reload work without helper-only state injection.

- [ ] **Step 4: Update helper comments**

Remove the comment in `frontend-console/e2e/helpers/workbench.js` that says `app.js` is broken. Keep helpers for deterministic setup, not for bypassing production startup.

## Task 2: Repair Project List and Recycle Bin User Path

**Files:**
- Modify: `frontend-console/e2e/project-recycle-bin.spec.js`
- Modify: `frontend-console/views/projectView.js`
- Test: `frontend-console/tests/projectView.test.js`

- [ ] **Step 1: Reproduce focused failure**

Run:

```bash
cd frontend-console && npx playwright test project-recycle-bin.spec.js --reporter=list
```

Expected baseline: 2 failures with `.project-grid` missing after `page.reload()`.

- [ ] **Step 2: Replace raw reload with project-list helper after startup fix**

Use `openProjectList(page)` or a new `reloadProjectList(page)` helper that waits for `state.loading === false` and for either `.project-grid` or `.empty-state`.

- [ ] **Step 3: Ensure projectView refreshes after API-created project**

If helper-only change is insufficient, update `projectView.onEnter()` / `render()` so a fresh project created outside the UI appears after reload. Do not rely on stale `state.projects`.

- [ ] **Step 4: Run tests**

```bash
cd frontend-console && npm test -- --run projectView.test.js
cd frontend-console && npx playwright test project-recycle-bin.spec.js --reporter=list
```

Expected: recycle-bin restore and permanent-delete paths pass.

## Task 3: Fix World Alias Creation Contract

**Files:**
- Modify: `frontend-console/api.js`
- Modify: `frontend-console/views/worldView.js`
- Test: `frontend-console/tests/worldView.test.js`
- Test: `frontend-console/e2e/world-relations-aliases.spec.js`

- [ ] **Step 1: Add unit test for alias payload**

In `worldView.test.js`, mock `api.world.createAlias` and assert the UI sends:

```javascript
{
  entity_id: "entity-id",
  alias: "小名",
  alias_type: "nickname"
}
```

and passes `state.currentProjectId` as the `novel_id` query source.

- [ ] **Step 2: Fix `api.world.createAlias` signature**

Change it from:

```javascript
async createAlias(payload) {
  return request("/world/aliases", {
    method: "POST",
    body: JSON.stringify(payload),
  })
}
```

to:

```javascript
async createAlias(payload, novelId) {
  return request(`/world/aliases${buildQueryString({ novel_id: novelId })}`, {
    method: "POST",
    body: JSON.stringify(payload),
  })
}
```

- [ ] **Step 3: Remove `novel_id` from alias JSON body**

In `worldView.showAliasCreateForm()`, call:

```javascript
await api.world.createAlias({
  entity_id: eid,
  alias: text,
  alias_type: document.getElementById("alias-type")?.value || "name",
}, state.currentProjectId)
```

- [ ] **Step 4: Improve validation error rendering**

In `request()`, if FastAPI returns `detail` as an array/object, stringify meaningful messages instead of showing `[object Object]`.

- [ ] **Step 5: Run tests**

```bash
cd frontend-console && npm test -- --run worldView.test.js
cd frontend-console && npx playwright test world-relations-aliases.spec.js world.spec.js --reporter=list
```

Expected: relation and alias paths pass.

## Task 4: Fix Writing Split Chapter Path

**Files:**
- Modify: `frontend-console/e2e/writing.spec.js`
- Modify: `frontend-console/views/writingView.js`
- Test: `frontend-console/tests/writingView.test.js`
- Verify backend: `backend/modules/writing/tests/test_writing.py`

- [ ] **Step 1: Reproduce focused split failure**

Run:

```bash
cd frontend-console && npx playwright test writing.spec.js -g "新 Scene 创建和断章更新左侧树" --reporter=list
```

Expected baseline: toast shows backend connection error, not `断章完成`.

- [ ] **Step 2: Stop injecting mismatched draft state in E2E**

The failed test sets `_currentChapter = 2` but `_currentDraftId` from chapter 1. Replace injected state with real navigation:

```javascript
await reloadWorkbench(page, "writing")
await page.locator('[data-action="select-chapter"][data-chapter="2"]').click()
```

- [ ] **Step 3: Harden `_doSplitScene()`**

Before calling `api.writing.splitChapter`, ensure the current chapter and current draft id are consistent. If current chapter has no latest draft loaded, call `_selectChapter(this._currentChapter)` and retry once.

- [ ] **Step 4: Add frontend unit test**

Cover that `_doSplitScene()` calls:

```javascript
api.writing.splitChapter(currentChapter, { split_pos, source_scene_id }, currentProjectId)
```

and updates `_chapterList`, `_currentChapter`, `_currentDraftId`, `_currentContent`, and `_scenes` from the response.

- [ ] **Step 5: Run tests**

```bash
cd backend && pytest modules/writing/tests/test_writing.py::test_split_chapter_at_offset_creates_new_chapter_without_publish_task modules/writing/tests/test_writing.py::test_split_chapter_at_offset_syncs_scene_chunks -q --tb=short
cd frontend-console && npm test -- --run writingView.test.js
cd frontend-console && npx playwright test writing.spec.js -g "新 Scene 创建和断章更新左侧树" --reporter=list
```

Expected: split creates a new chapter, updates tree, and does not trigger RAG publish.

## Task 5: Fix Writing Reload-Based Paths and 409 Conflict

**Files:**
- Modify: `frontend-console/e2e/writing.spec.js`
- Modify: `frontend-console/e2e/writing-conflict.spec.js`
- Modify: `frontend-console/views/writingView.js`
- Test: `frontend-console/tests/writingView.test.js`

- [ ] **Step 1: Replace raw reloads in writing E2E**

Raw `page.reload()` currently leaves tests waiting for `writingView._loading === false`. Use `reloadWorkbench(page, "writing")` after Task 1.

- [ ] **Step 2: Add a real cursor-link E2E path**

Do not mutate private `_cursorOffset` directly. Focus the textarea and set selection:

```javascript
await page.locator("#writing-editor").focus()
await page.evaluate(() => {
  const editor = document.getElementById("writing-editor")
  editor.setSelectionRange(7, 7)
  document.dispatchEvent(new Event("selectionchange"))
})
await expect(page.locator("#writing-panel-container")).toContainText("Scene B")
```

- [ ] **Step 3: Fix 409 conflict test setup**

Ensure Tab B / current page is saving with stale `expected_version`. The backend already has focused tests for `expected_version`; the E2E must seed v1, load v1 into the editor, update the same chapter externally to v2, then click `暂存` without refreshing local `_currentVersionNumber`.

- [ ] **Step 4: Ensure API error surfaces conflict text**

If the backend returns 409 but frontend only shows generic text, update `api.js` error parsing and `writingView` save catch so the toast contains:

```text
该章节已被其他会话更新，请刷新后重新编辑
```

- [ ] **Step 5: Run writing scenario bundle**

```bash
cd frontend-console && npx playwright test writing.spec.js writing-conflict.spec.js --reporter=list
```

Expected: all writing scenarios pass, including cursor-linked Scene panel, AI extraction dialog, split, and 409 conflict.

## Task 6: Fix Deep Import Main User Path

**Files:**
- Modify: `frontend-console/e2e/deep-import.spec.js`
- Modify: `frontend-console/views/projectView.js`
- Modify: `frontend-console/views/writingView.js`
- Test: `frontend-console/tests/projectView.test.js`
- Test: `frontend-console/tests/writingView.test.js`

- [ ] **Step 1: Reproduce focused failure**

```bash
cd frontend-console && npx playwright test deep-import.spec.js -g "从项目视图导入小说后启动深度导入" --reporter=list
```

Expected baseline: writing view remains empty after import; no `[data-action="deep-import"]`.

- [ ] **Step 2: Verify imported chapters are written**

After upload, assert via API helper that `/api/writing/chapters?novel_id=...` returns chapters. If backend has data but UI is empty, fix frontend reload/hydration. If backend lacks data, fix import service.

- [ ] **Step 3: Fix project import to writing handoff**

After `api.imports.upload(project.id, file)`, ensure `state.currentProjectId`, `state.currentProject`, and route hash are set to `/workbench/:projectId/writing`, then force writing view `onEnter()` to fetch chapters.

- [ ] **Step 4: Start deep import from the post-import prompt**

The current confirmation handler is empty. Make the “启动深度导入” confirmation either navigate to writing and open the deep-import modal, or directly call the same `_submitDeepImport(start, end)` path with the imported chapter range.

- [ ] **Step 5: Run tests**

```bash
cd frontend-console && npm test -- --run projectView.test.js writingView.test.js
cd frontend-console && npx playwright test deep-import.spec.js import.spec.js --reporter=list
```

Expected: import success flow exposes and starts deep import.

## Task 7: Stabilize Outline Scene Reorder and AI Modal Paths

**Files:**
- Modify: `frontend-console/e2e/outline-scenes.spec.js`
- Modify: `frontend-console/views/outlineView.js`
- Test: `frontend-console/tests/outlineView.test.js`

- [ ] **Step 1: Fix strict locator in reorder test**

Replace strict multi-element assertion:

```javascript
await expect(page.locator(".scene-card")).toContainText("Scene A")
```

with:

```javascript
await expect(page.locator(".scene-card").filter({ hasText: "Scene A" })).toHaveCount(1)
await expect(page.locator(".scene-card").filter({ hasText: "Scene B" })).toHaveCount(1)
```

- [ ] **Step 2: Assert reorder by ordered card titles**

After clicking move-up, collect card titles and assert order, instead of relying on a single locator.

- [ ] **Step 3: Fix modal close behavior**

If `#modal-close` does not hide the overlay after `AI 生成结构`, repair modal event binding or outline form code so close works consistently.

- [ ] **Step 4: Expand foreshadow/reveal path only after CRUD exists**

The current test only verifies empty tabs. Do not mark full “管理伏笔与揭示计划” complete until create/edit/status-change paths are executable. If only empty tabs exist, update scenario coverage as partial.

- [ ] **Step 5: Run tests**

```bash
cd frontend-console && npm test -- --run outlineView.test.js
cd frontend-console && npx playwright test outline-scenes.spec.js outline-threads-arcs.spec.js --reporter=list
```

Expected: scene CRUD, reorder, AI modal, empty foreshadow/reveal tabs, and threads/arcs pass.

## Task 8: Update Scenario Coverage and Final Verification

**Files:**
- Modify: `frontend-console/e2e/scenario-coverage.md`
- Optionally create: `docs/superpowers/reports/2026-06-12-post-round3-gap-validation.md`

- [ ] **Step 1: Run full frontend unit suite**

```bash
cd frontend-console && npm test
```

Expected: all Vitest tests pass.

- [ ] **Step 2: Run focused backend suite**

```bash
cd backend && pytest modules/project/tests/test_project.py modules/imports/tests/test_imports.py modules/imports/tests/test_workflow.py modules/writing/tests/test_writing.py modules/outline/tests/test_scene.py modules/outline/tests/test_foreshadowing_reveal.py modules/world/tests/test_world.py modules/rag/tests/test_rag.py modules/context/tests/test_context.py tests/integration/test_novel_id_isolation.py -q --tb=short
```

Expected: pass.

- [ ] **Step 3: Run full scenario Playwright suite**

```bash
cd frontend-console && npx playwright test project-recycle-bin.spec.js import.spec.js import-errors.spec.js deep-import.spec.js writing.spec.js writing-conflict.spec.js world.spec.js world-relations-aliases.spec.js outline-scenes.spec.js outline-threads-arcs.spec.js rag.spec.js context.spec.js --reporter=list
```

Expected: 52 passed, 0 failed.

- [ ] **Step 4: Update coverage matrix honestly**

Set a scenario to `✅ 已覆盖` only when its relevant Playwright file passes. Keep these partial unless implemented:

- Real async deep-import three-stage worker path and failure degradation.
- Full foreshadow/reveal CRUD if only empty tabs exist.
- RAG parent-child retrieval and embedding warning E2E if only basic page/search tests exist.
- Context character-perspective hidden-truth transformation if only basic compile page tests exist.

- [ ] **Step 5: Run lint/checks**

```bash
cd frontend-console && node --check app.js && node --check api.js
make lint
```

Expected: pass, or document any existing unrelated lint failures.

## Definition of Done

- No E2E helper is compensating for broken production startup.
- Project create/list/edit/delete/recycle-bin works after reload.
- Import success leads to writing view with imported chapters and a real deep-import entry.
- Writing split, cursor-linked Scene panel, version conflict, version history, and AI card extraction dialog all pass in browser.
- World alias creation writes to `core_entities.content_json.aliases` and does not create a new entity.
- Outline scene reorder and AI modal are stable; foreshadow/reveal coverage status is not overstated.
- `frontend-console/e2e/scenario-coverage.md` matches the latest test results.
