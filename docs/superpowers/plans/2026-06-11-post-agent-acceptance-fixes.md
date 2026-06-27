# Post-Agent Acceptance Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining gaps found during acceptance review after the previous agent's implementation round.

**Architecture:** Keep changes as vertical slices around failing or mismatched behavior: project recycle-bin contract, import-to-deep-import entry, writing Scene split semantics, world rollback contract, frontend XSS hardening, and scenario coverage tests. Do not introduce new infrastructure or frontend framework; use existing FastAPI services, vanilla JS views, and current test setup.

**Tech Stack:** FastAPI, async SQLAlchemy, pytest, vanilla JS, Vitest, Playwright.

---

## Acceptance Findings

Fresh verification run:

```bash
cd backend && pytest modules/project/tests/test_project.py modules/imports/tests/test_imports.py modules/writing/tests/test_writing.py modules/outline/tests/test_scene.py -q --tb=short
```

Observed: `1 failed, 125 passed`. Failure: `modules/project/tests/test_project.py::TestProjectCrud::test_soft_delete` still expects `ProjectRepository.get()` to return soft-deleted projects, while current repository filters `deleted_at is null`.

Additional code/document mismatches:

- `projectView.importFile()` shows “是否启动深度导入？” but the confirm handler is empty.
- `projectView._uploadFile()` imports into an existing project but does not show the same deep-import prompt.
- Scene split UI says “选中一段文字，右键 → 在此处断章”, but implementation splits whole chapter ranges by chapter index and does not update `scene_chunks` offsets.
- Spec says EntityRevision is废弃 and rollback must use Delta Log + Text Archive, but `EntityRevisionService` remains the active rollback route.
- World entity creation does not yet enforce duplicate-confirmation workflow for manual creation.
- Frontend still has user/AI content rendered through `innerHTML` in command suggestions and output views.
- `frontend-console/e2e/scenario-coverage.md` records many partial coverage gaps; those gaps need executable tests or explicit deferred status.

## File Structure

Modify these files:

- `backend/modules/project/repositories.py` — add explicit deleted-project lookup instead of overloading `get()`.
- `backend/modules/project/services.py` — use deleted lookup in restore flow.
- `backend/modules/project/tests/test_project.py` — align tests with visible vs recycle-bin lookup contract.
- `frontend-console/views/projectView.js` — make post-import deep-import prompt actually start the workflow.
- `frontend-console/tests/projectView.test.js` — cover import prompt and deep-import handoff.
- `backend/modules/outline/services.py` — either implement offset-aware split or rename current range split as a separate behavior.
- `backend/modules/outline/tests/test_scene.py` — cover `scene_chunks` changes for split.
- `frontend-console/views/writingView.js` — align UI copy and action with selected-text split requirements.
- `frontend-console/tests/writingView.test.js` — cover selected-text split and no-save side effect.
- `backend/modules/world/services/entity_revision_service.py` or a new rollback service — replace active rollback with Delta Log + Text Archive.
- `backend/modules/world/api.py` — expose rollback contract that no longer depends on `entity_revisions`.
- `backend/modules/world/tests/test_world.py` and `backend/tests/unit/test_world_services_revision_event_helpers.py` — update rollback tests.
- `frontend-console/views/worldView.js` and `frontend-console/tests/worldView.test.js` — duplicate-confirmation workflow and merge/rollback entry coverage.
- `frontend-console/app.js`, `frontend-console/views/contextView.js`, `frontend-console/views/generateView.js` — remove risky `innerHTML` rendering for user/AI content or ensure all inserted data is built through DOM APIs.
- `frontend-console/tests/api-contract.test.js` or a new `frontend-console/tests/xss-rendering.test.js` — enforce rendering rules.
- `frontend-console/e2e/scenario-coverage.md` — update only after tests exist or deferral is explicitly justified.

## Task 1: Fix Project Soft-Delete Contract

**Files:**
- Modify: `backend/modules/project/repositories.py`
- Modify: `backend/modules/project/services.py`
- Modify: `backend/modules/project/tests/test_project.py`

- [ ] **Step 1: Write the failing contract tests**

In `backend/modules/project/tests/test_project.py`, replace `test_soft_delete` with:

```python
@pytest.mark.asyncio
async def test_soft_delete_hides_from_get_and_list(
    self,
    db_session: AsyncSession,
    sample_create_data: ProjectCreate,
) -> None:
    created = await _repo.create(db_session, sample_create_data)

    deleted = await _repo.soft_delete(db_session, created.id)

    assert deleted is True
    assert await _repo.get(db_session, created.id) is None
    deleted_project = await _repo.get_deleted(db_session, created.id)
    assert deleted_project is not None
    assert deleted_project.deleted_at is not None

    items, _total = await _repo.list(db_session, skip=0, limit=10)
    assert all(item.id != created.id for item in items)
```

Add a restore service test:

```python
@pytest.mark.asyncio
async def test_restore_project_returns_restored_row(
    self,
    db_session: AsyncSession,
    sample_create_data: ProjectCreate,
) -> None:
    service = ProjectService()
    created = await service.create_project(db_session, sample_create_data)
    await service.delete_project(db_session, created.id)

    restored = await service.restore_project(db_session, created.id)

    assert restored.id == created.id
    assert restored.deleted_at is None
```

- [ ] **Step 2: Run the project tests and confirm the current failure**

Run:

```bash
cd backend && pytest modules/project/tests/test_project.py -q --tb=short
```

Expected before implementation: failure because `get_deleted()` does not exist or restore cannot load the restored row through the correct contract.

- [ ] **Step 3: Add explicit deleted lookup**

In `backend/modules/project/repositories.py`, add:

```python
async def get_deleted(
    self,
    db: AsyncSession,
    project_id: uuid.UUID,
) -> Project | None:
    stmt = select(Project).where(
        Project.id == project_id,
        Project.deleted_at.isnot(None),
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()
```

Keep `get()` filtering out deleted projects.

- [ ] **Step 4: Use the explicit lookup in restore**

In `backend/modules/project/services.py`, replace the restore tail with:

```python
project = await self._repo.get(db, pid)
if project is None:
    raise HTTPException(
        status_code=http_status.HTTP_404_NOT_FOUND,
        detail=f"Project {project_id} not found after restore",
    )
return ProjectResponse.model_validate(project)
```

This keeps the normal visible-project lookup after restore and makes failures explicit.

- [ ] **Step 5: Verify**

Run:

```bash
cd backend && pytest modules/project/tests/test_project.py -q --tb=short
```

Expected: all project tests pass.

## Task 2: Wire Import Success to Real Deep Import Start

**Files:**
- Modify: `frontend-console/views/projectView.js`
- Modify: `frontend-console/tests/projectView.test.js`

- [ ] **Step 1: Add failing frontend tests**

In `frontend-console/tests/projectView.test.js`, add tests covering both import paths:

```javascript
it("starts deep import from importFile confirmation", async () => {
  const file = new File(["第1章\n正文"], "novel.txt", { type: "text/plain" })
  mockApi.projects.create.mockResolvedValue({ id: "p1", title: "novel" })
  mockApi.projects.list.mockResolvedValue({ items: [] })
  mockApi.imports.upload.mockResolvedValue({ imported_chapters: 3 })
  mockApi.imports.deepImport.mockResolvedValue({ task_id: "task-1" })
  mockConfirmAction.mockImplementation((_msg, onConfirm) => onConfirm())

  await projectView._handleImportedFile(file)

  expect(mockApi.imports.deepImport).toHaveBeenCalledWith("p1", 1, 3, false)
})

it("prompts deep import after uploading into current project", async () => {
  state.currentProjectId = "p1"
  mockUploadWithProgress({ imported_chapters: 2 })
  mockApi.imports.deepImport.mockResolvedValue({ task_id: "task-2" })
  mockConfirmAction.mockImplementation((_msg, onConfirm) => onConfirm())

  await projectView._uploadFile()

  expect(mockApi.imports.deepImport).toHaveBeenCalledWith("p1", 1, 2, false)
})
```

If current test helpers do not expose `mockConfirmAction` or upload progress, add minimal mocks in the existing setup rather than introducing a new test framework.

- [ ] **Step 2: Run tests to confirm failure**

Run:

```bash
cd frontend-console && npm test -- --run projectView.test.js
```

Expected before implementation: `api.imports.deepImport` is not called.

- [ ] **Step 3: Extract reusable deep-import start helper**

In `frontend-console/views/projectView.js`, add:

```javascript
async _promptDeepImportAfterUpload(projectId, importedChapters) {
  if (!projectId || !importedChapters || importedChapters < 1) return
  confirmAction(
    `已导入 ${importedChapters} 章，是否启动深度导入？`,
    async () => {
      try {
        const result = await api.imports.deepImport(projectId, 1, importedChapters, false)
        if (result.requires_confirmation) {
          confirmAction(result.warning, async () => {
            const forced = await api.imports.deepImport(projectId, 1, importedChapters, true)
            toast(forced.task_id ? "深度导入已启动" : forced.message || "深度导入未启动", forced.task_id ? "success" : "warning")
          }, "确认覆盖")
          return
        }
        toast(result.task_id ? "深度导入已启动" : result.message || "深度导入未启动", result.task_id ? "success" : "warning")
      } catch (err) {
        toast(err.message || "深度导入启动失败", "error")
      }
    },
    "启动深度导入",
  )
}
```

- [ ] **Step 4: Call helper from both upload paths**

In `importFile()` confirm handler, replace the empty handler by calling:

```javascript
await this._promptDeepImportAfterUpload(project.id, result.imported_chapters)
```

For `_uploadFile()`, after `toast(...)` and before/after `router.navigate("writing")`, call:

```javascript
await this._promptDeepImportAfterUpload(state.currentProjectId, result.imported_chapters)
```

If direct unit testing of `input.onchange` is hard, extract `_handleImportedFile(file)` that contains the current importFile body and call it from `input.onchange`.

- [ ] **Step 5: Verify**

Run:

```bash
cd frontend-console && npm test -- --run projectView.test.js
```

Expected: tests pass.

## Task 3: Align Writing Split Scene With Spec

**Files:**
- Modify: `backend/modules/outline/services.py`
- Modify: `backend/modules/outline/schemas.py`
- Modify: `backend/modules/outline/api.py`
- Modify: `backend/modules/outline/tests/test_scene.py`
- Modify: `frontend-console/views/writingView.js`
- Modify: `frontend-console/tests/writingView.test.js`

- [ ] **Step 1: Add backend test for offset-aware split**

In `backend/modules/outline/tests/test_scene.py`, add:

```python
@pytest.mark.asyncio
async def test_split_scene_chunk_at_offset(
    db_session: AsyncSession,
    sample_novel_id: str,
) -> None:
    svc = SceneService()
    created = await svc.create(
        db_session,
        sample_novel_id,
        SceneCreate(
            scene_index=0,
            title="原 Scene",
            chapter_ids=["5"],
            scene_chunks=[
                {"chapter_id": "ch5", "chapter_index": 5, "start_pos": 0, "end_pos": 3000}
            ],
        ),
    )

    result = await svc.split_scene_chunk(
        db_session,
        novel_id=sample_novel_id,
        source_scene_id=created.id,
        chapter_id="ch5",
        chapter_index=5,
        split_pos=1500,
    )

    assert len(result) == 2
    source = result[0]
    target = result[1]
    assert source.scene_chunks == [
        {"chapter_id": "ch5", "chapter_index": 5, "start_pos": 0, "end_pos": 1500}
    ]
    assert target.scene_chunks == [
        {"chapter_id": "ch5", "chapter_index": 5, "start_pos": 1500, "end_pos": 3000}
    ]
    assert target.source == "manual"
    assert target.narrative_tag == "draft"
```

- [ ] **Step 2: Run test to confirm failure**

Run:

```bash
cd backend && pytest modules/outline/tests/test_scene.py::TestSceneService::test_split_scene_chunk_at_offset -q --tb=short
```

Expected before implementation: method/schema missing.

- [ ] **Step 3: Add request schema**

In `backend/modules/outline/schemas.py`, add:

```python
class SplitSceneChunkRequest(BaseModel):
    source_scene_id: str
    chapter_id: str
    chapter_index: int = Field(..., ge=1)
    split_pos: int = Field(..., ge=0)
```

- [ ] **Step 4: Implement service method**

In `SceneService`, add `split_scene_chunk()` that:

1. Loads source scene and verifies `novel_id`.
2. Finds the chunk matching `chapter_id` or `chapter_index`.
3. Validates `start_pos < split_pos < end_pos`.
4. Updates source chunk end to `split_pos`.
5. Creates a new manual Scene with `scene_index = source.scene_index + 1`, `narrative_tag = "draft"`, `chapter_ids = [chapter_id or str(chapter_index)]`, and chunk start at `split_pos`.
6. Reorders later scene indices to avoid duplicates.
7. Flushes and returns ordered scenes.

- [ ] **Step 5: Add API endpoint**

In `backend/modules/outline/api.py`, add:

```python
@router.post("/scenes/split-chunk", response_model=list[SceneResponse])
async def api_split_scene_chunk(
    db: DbSession,
    data: SplitSceneChunkRequest,
    novel_id: str = Query(...),
) -> list[SceneResponse]:
    return await _scene_service.split_scene_chunk(
        db,
        novel_id=novel_id,
        source_scene_id=data.source_scene_id,
        chapter_id=data.chapter_id,
        chapter_index=data.chapter_index,
        split_pos=data.split_pos,
    )
```

- [ ] **Step 6: Update frontend behavior**

In `writingView`, change “断章” to use the textarea selection/cursor:

```javascript
const editor = document.getElementById("writing-editor")
const splitPos = editor ? editor.selectionStart : null
```

Call `api.outline.splitSceneChunk(...)` with current scene id, current chapter id/index, and `splitPos`. Do not call the chapter-range `splitChapters()` endpoint for the right-click/cursor split action. Keep the existing range split only if it is renamed in UI as “按章节迁移到 Scene”.

- [ ] **Step 7: Verify**

Run:

```bash
cd backend && pytest modules/outline/tests/test_scene.py -q --tb=short
cd frontend-console && npm test -- --run writingView.test.js
```

Expected: tests pass.

## Task 4: Replace Active EntityRevision Rollback With Delta/Text Archive Contract

**Files:**
- Modify: `backend/modules/world/services/entity_revision_service.py`
- Modify: `backend/modules/world/api.py`
- Modify: `backend/modules/world/repositories.py`
- Modify: `backend/modules/world/tests/test_world.py`
- Modify: `backend/tests/unit/test_world_services_revision_event_helpers.py`
- Modify: `docs/modules/02_world.md`
- Modify: `backend/modules/world/README.md`

- [ ] **Step 1: Add failing rollback test**

Add a test that creates:

- a `CoreEntity` with current structured fields
- `delta_log` rows for `importance` and `status`
- `text_archive` rows for `summary` and `hidden_truth`

Then call rollback to `target_scene_index=10` and assert:

```python
assert entity.importance == 0.7
assert entity.status == "canonical"
assert entity.summary == "旧摘要"
assert entity.hidden_truth == "旧隐藏真相"
assert latest_delta.category == "MANUAL_ROLLBACK"
```

- [ ] **Step 2: Run test to confirm current EntityRevision dependency**

Run:

```bash
cd backend && pytest backend/tests/unit/test_world_services_revision_event_helpers.py -q --tb=short
```

Expected before implementation: rollback still requires `revision_id` or uses `entity_revisions`.

- [ ] **Step 3: Implement rollback service contract**

Change rollback API to accept:

```python
class EntityRollbackRequest(BaseModel):
    target_scene_index: int = Field(..., ge=0)
```

Implement logic:

1. Load entity by `entity_id` and `novel_id`.
2. Query Delta Log rows for that entity with `scene_index <= target_scene_index`, ordered by `created_at`.
3. Reconstruct structured fields from earliest known old values plus new values up to target.
4. Query Text Archive for each long text field with `scene_index <= target_scene_index`, latest by `created_at`.
5. Update `core_entities`.
6. Insert a `DeltaLog` row with `category="MANUAL_ROLLBACK"` and `source="manual_rollback"`.

If full reconstruction is impossible because no old/new value exists for a field, leave that field unchanged and include a warning in the response.

- [ ] **Step 4: Keep legacy EntityRevision read-only or remove route**

Do not let `/api/world/entities/{entity_id}/rollback` call `EntityRevisionService.rollback_to_revision`. Either:

- keep `/revisions` read-only and mark legacy, or
- remove revision route if no caller uses it.

Update docs to say `entity_revisions` is legacy and not used by active rollback.

- [ ] **Step 5: Verify**

Run:

```bash
cd backend && pytest modules/world/tests/test_world.py tests/unit/test_world_services_revision_event_helpers.py -q --tb=short
```

Expected: tests pass and active rollback no longer depends on `entity_revisions`.

## Task 5: Add Manual Entity Duplicate Confirmation

**Files:**
- Modify: `backend/modules/world/services/entity_service.py`
- Modify: `backend/modules/world/schemas.py`
- Modify: `backend/modules/world/api.py`
- Modify: `backend/modules/world/tests/test_world.py`
- Modify: `frontend-console/views/worldView.js`
- Modify: `frontend-console/tests/worldView.test.js`

- [ ] **Step 1: Add backend test for duplicate warning**

Create an existing canonical entity named `张三`, then call create with `name="张三"` and `force=false`.

Expected response shape:

```python
assert result.requires_confirmation is True
assert result.similar_entities[0]["name"] == "张三"
```

Then call with `force=true` and assert entity is created.

- [ ] **Step 2: Add create request flag**

Add `force_create: bool = False` to `CoreEntityCreate`.

- [ ] **Step 3: Implement duplicate preflight**

In `WorldEntityService.create`, before creating:

1. Run existing name/fuzzy/dedup lookup for same `novel_id`.
2. If score >= `0.90` and `force_create` is false, return a confirmation response or raise `409` with structured detail.
3. If `force_create` is true, create normally.

Prefer `409 Conflict` with detail:

```json
{
  "requires_confirmation": true,
  "similar_entities": [{"id": "...", "name": "...", "similarity_score": 0.95}]
}
```

- [ ] **Step 4: Update frontend**

In `worldView` entity creation:

1. On `409` with `requires_confirmation`, show confirmation modal.
2. On confirm, resubmit with `force_create: true`.
3. On cancel, leave form data intact.

- [ ] **Step 5: Verify**

Run:

```bash
cd backend && pytest modules/world/tests/test_world.py -q --tb=short
cd frontend-console && npm test -- --run worldView.test.js
```

Expected: tests pass.

## Task 6: Harden Frontend Rendering Against User/AI HTML

**Files:**
- Modify: `frontend-console/app.js`
- Modify: `frontend-console/views/contextView.js`
- Modify: `frontend-console/views/generateView.js`
- Modify: `frontend-console/views/writingView.js`
- Create or modify: `frontend-console/tests/xss-rendering.test.js`

- [ ] **Step 1: Add XSS regression tests**

Create `frontend-console/tests/xss-rendering.test.js` with cases:

```javascript
it("renders command suggestions without executing HTML", () => {
  commands.getSuggestions = () => [{ name: "<img src=x onerror=alert(1)>", description: "<script>alert(1)</script>" }]
  app._updateHint(input, hint, suggestionsEl)
  expect(suggestionsEl.querySelector("script")).toBeNull()
  expect(suggestionsEl.textContent).toContain("<script>alert(1)</script>")
})

it("renders context markdown as text", async () => {
  api.context.render.mockResolvedValue({ markdown: "<script>alert(1)</script>" })
  await contextView._renderMarkdown()
  expect(document.querySelector("script")).toBeNull()
  expect(output.textContent).toContain("<script>alert(1)</script>")
})
```

- [ ] **Step 2: Replace command suggestions `innerHTML` with DOM construction**

In `frontend-console/app.js`, replace suggestion rendering with:

```javascript
suggestionsEl.replaceChildren()
for (const s of suggestions.slice(0, 6)) {
  const row = document.createElement("div")
  row.className = "suggestion"
  row.dataset.cmd = s.name
  const label = document.createElement("span")
  label.textContent = s.name
  if (s.description) {
    const desc = document.createElement("span")
    desc.style.color = "var(--text-tertiary)"
    desc.style.marginLeft = "8px"
    desc.style.fontSize = "12px"
    desc.textContent = s.description
    label.appendChild(desc)
  }
  const key = document.createElement("span")
  key.className = "suggestion-key"
  key.textContent = "Enter"
  row.append(label, key)
  suggestionsEl.appendChild(row)
}
```

- [ ] **Step 3: Use textContent for AI/user output**

For `contextView` and `generateView`, build containers with `document.createElement()` and set AI/user text via `textContent`. Keep static layout HTML only if it contains no user/AI data.

- [ ] **Step 4: Verify**

Run:

```bash
cd frontend-console && npm test -- --run xss-rendering.test.js
```

Expected: tests pass and no script nodes are inserted.

## Task 7: Turn Scenario Coverage Gaps Into Executable Tests

**Files:**
- Modify: `frontend-console/e2e/project.spec.js`
- Modify: `frontend-console/e2e/import.spec.js`
- Modify: `frontend-console/e2e/deep-import.spec.js`
- Modify: `frontend-console/e2e/writing.spec.js`
- Modify: `frontend-console/e2e/world-relations-aliases.spec.js`
- Modify: `frontend-console/e2e/outline-scenes.spec.js`
- Modify: `frontend-console/e2e/scenario-coverage.md`

- [ ] **Step 1: Remove `test.fixme` for relation and alias CRUD when backend route exists**

`/api/world/relations` and `/api/world/aliases` now exist. Convert `test.fixme` cases in `world-relations-aliases.spec.js` to normal tests.

- [ ] **Step 2: Add project recycle-bin E2E**

Cover:

1. Create project.
2. Soft delete.
3. Open recycle bin.
4. Restore.
5. Soft delete again.
6. Permanent delete.

- [ ] **Step 3: Add import error E2E**

Cover `.pdf` 400 and oversized client-side guard. Use a synthetic File object; do not commit large binary files.

- [ ] **Step 4: Add deep import resume E2E**

Mock or seed a running task id, reload the page at `/workbench/:pid/writing`, and assert the progress bar resumes via `GET /api/tasks/{task_id}`.

- [ ] **Step 5: Add writing conflict E2E**

Use two browser contexts or API setup:

1. Tab A loads chapter v1.
2. API creates/saves v2.
3. Tab A saves with expected v1.
4. Assert 409 message and editor content remains.

- [ ] **Step 6: Update scenario coverage doc**

Only mark a row as covered after the corresponding test exists and has been run.

- [ ] **Step 7: Verify targeted E2E**

Run:

```bash
cd frontend-console && npx playwright test e2e/project.spec.js e2e/import.spec.js e2e/world-relations-aliases.spec.js --reporter=list
```

Expected: targeted tests pass in an environment with backend/frontend running.

## Task 8: Final Verification

**Files:** no code changes unless failures require fixes.

- [ ] **Step 1: Run backend focused suite**

Run:

```bash
cd backend && pytest modules/project/tests/test_project.py modules/imports/tests/test_imports.py modules/writing/tests/test_writing.py modules/outline/tests/test_scene.py modules/world/tests/test_world.py -q --tb=short
```

Expected: all pass.

- [ ] **Step 2: Run backend unit regression**

Run:

```bash
cd backend && pytest tests/unit/ -q --tb=short
```

Expected: all pass or only documented skips.

- [ ] **Step 3: Run frontend unit tests**

Run:

```bash
cd frontend-console && npm test
```

Expected: all pass.

- [ ] **Step 4: Run lint**

Run:

```bash
make lint
```

Expected: no lint errors.

## Self-Review

Spec coverage:

- Project recycle bin: Task 1 and Task 7.
- Import → deep import prompt: Task 2.
- Writing split selected text / scene chunks: Task 3.
- Entity rollback via Delta/Text Archive: Task 4.
- Manual entity duplicate confirmation: Task 5.
- XSS hardening: Task 6.
- Scenario coverage evidence: Task 7.

Known deliberate deferrals after this plan:

- Relationship graph visualization remains P2 unless the user asks for the visual graph now.
- Full LR dedup model tuning remains P3; this plan only requires duplicate confirmation behavior.
- Real LLM/PG E2E may remain environment-gated, but the skip condition must be explicit and non-hanging.

Placeholder scan: no TBD/TODO/fill-in-later steps remain; each task has files, code shape, commands, and expected outcomes.
