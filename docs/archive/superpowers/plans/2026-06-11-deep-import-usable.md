# Deep Import Usable Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make deep import usable from the writing workspace with safe duplicate confirmation and visible task progress.

**Architecture:** Reuse the existing `async_tasks` table as the workflow carrier instead of introducing a new workflow table. `POST /api/imports/deep` performs duplicate detection before enqueueing and requires `force=true` for confirmed overwrite. The deep-import task updates its own task progress/result between phases so the frontend can poll `/api/tasks/{task_id}` for live status.

**Tech Stack:** FastAPI, async SQLAlchemy, existing PostgreSQL-backed task queue, vanilla JS frontend, pytest, Vitest.

---

### Task 1: Duplicate Confirmation Contract

**Files:**
- Modify: `backend/modules/imports/facade.py`
- Test: `backend/tests/unit/test_imports_facade.py`

- [ ] **Step 1: Write failing tests**

Add tests that prove duplicate deep import returns `requires_confirmation` without enqueueing, and `force=True` enqueues.

- [ ] **Step 2: Run tests to verify failure**

Run: `cd backend && pytest tests/unit/test_imports_facade.py -q`

- [ ] **Step 3: Implement minimal backend contract**

Add `force: bool = False` to `start_deep_import`; if duplicate warning exists and `force` is false, return `{"requires_confirmation": True, "warning": ...}` without calling `enqueue_task`.

- [ ] **Step 4: Verify tests pass**

Run: `cd backend && pytest tests/unit/test_imports_facade.py -q`

### Task 2: API and Frontend Confirmation Flow

**Files:**
- Modify: `backend/modules/imports/api.py`
- Modify: `frontend-console/api.js`
- Modify: `frontend-console/views/writingView.js`
- Test: `frontend-console/tests/writingView.test.js`

- [ ] **Step 1: Write failing frontend test**

Add a Vitest case that mocks the first `api.imports.deepImport` call returning `requires_confirmation`, confirms the modal action, and asserts a second call is made with `force=true`.

- [ ] **Step 2: Run test to verify failure**

Run: `cd frontend-console && npm test -- writingView.test.js`

- [ ] **Step 3: Implement API and UI changes**

Pass `force` from API body to backend facade. Let `api.imports.deepImport` accept a fourth boolean argument. In `writingView._submitDeepImport`, when `requires_confirmation` is returned, prompt the user and resubmit with `force=true`.

- [ ] **Step 4: Verify frontend test passes**

Run: `cd frontend-console && npm test -- writingView.test.js`

### Task 3: Live Task Progress

**Files:**
- Modify: `backend/modules/imports/tasks.py`
- Modify: `backend/modules/imports/workflow.py`
- Test: `backend/modules/imports/tests/test_workflow.py`

- [ ] **Step 1: Write failing workflow test**

Add a fake task object and assert deep import records phase progress after each phase.

- [ ] **Step 2: Run test to verify failure**

Run: `cd backend && pytest modules/imports/tests/test_workflow.py -q`

- [ ] **Step 3: Implement progress callback**

Let `DeepImportWorkflow.run_step` accept an optional `on_progress` async callback. Call it after phase start and phase completion with the serialized progress object and numeric progress `0.0`, `0.4`, `0.8`, `1.0`. `handle_deep_import` passes a callback that updates `task.result`, `task.progress`, and flushes.

- [ ] **Step 4: Verify tests pass**

Run: `cd backend && pytest modules/imports/tests/test_workflow.py -q`

### Task 4: Documentation and Focused Verification

**Files:**
- Modify: `backend/modules/imports/README.md`
- Modify: `docs/modules/13_imports.md`

- [ ] **Step 1: Update docs**

Align imports module documentation with the accepted task-based deep import workflow and duplicate confirmation behavior.

- [ ] **Step 2: Run focused verification**

Run: `cd backend && pytest tests/unit/test_imports_facade.py modules/imports/tests/test_workflow.py -q`

Run: `cd frontend-console && npm test -- writingView.test.js`

- [ ] **Step 3: Run lint if feasible**

Run: `make lint`
