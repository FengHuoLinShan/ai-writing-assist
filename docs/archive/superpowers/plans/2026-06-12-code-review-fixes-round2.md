# Code Review Fixes — Round 2 Scenario Gap Closure

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 3 Important issues and 1 Minor issue identified in the round 2 code review.

**Architecture:** All fixes are localized to single files — no cross-module changes needed.

**Tech Stack:** Vanilla JS (frontend), Python/FastAPI (backend), Vitest (frontend tests), pytest (backend tests).

---

### Task 1: Fix onselect → selectionchange for textarea cursor tracking

**Files:**
- Modify: `frontend-console/views/writingView.js:1450-1461`
- Modify: `frontend-console/tests/writingView.test.js:195-201`

**Why:** The HTML `select` event does not fire on `<textarea>` elements in real browsers (only on `<input type="text">` and `<input type="file">`). The current `onselect` handler is dead code in production. The test passes only because happy-dom doesn't enforce this browser limitation.

- [ ] **Step 1: Update _bindEvents to use selectionchange**

In `frontend-console/views/writingView.js`, replace the cursor event binding block (lines 1450-1461):

```javascript
      editorEl.onclick = null
      editorEl.onselect = null
      editorEl.onkeyup = null
      const updateCursorScene = () => {
        this._cursorOffset = editorEl.selectionStart || 0
        this._updateCurrentScene()
        this._clearCursorDebounceTimer()
        const panelEl = document.getElementById("writing-panel-container")
        if (panelEl) panelEl.innerHTML = this._renderScenePanel()
      }
      editorEl.onclick = updateCursorScene
      editorEl.onselect = updateCursorScene
      editorEl.onkeyup = () => {
        this._clearCursorDebounceTimer()
        this._cursorDebounceTimer = setTimeout(updateCursorScene, 150)
      }
```

Replace with:

```javascript
      editorEl.onclick = null
      editorEl.onkeyup = null
      document.removeEventListener("selectionchange", this._boundSelectionChange)
      const updateCursorScene = () => {
        if (document.activeElement !== editorEl) return
        this._cursorOffset = editorEl.selectionStart || 0
        this._updateCurrentScene()
        this._clearCursorDebounceTimer()
        const panelEl = document.getElementById("writing-panel-container")
        if (panelEl) panelEl.innerHTML = this._renderScenePanel()
      }
      this._boundSelectionChange = updateCursorScene
      editorEl.onclick = updateCursorScene
      document.addEventListener("selectionchange", updateCursorScene)
      editorEl.onkeyup = () => {
        this._clearCursorDebounceTimer()
        this._cursorDebounceTimer = setTimeout(updateCursorScene, 150)
      }
```

- [ ] **Step 2: Add _boundSelectionChange cleanup in state init**

In `writingView.js`, add `_boundSelectionChange: null` to the state object (around line 32 where `_cursorOffset: 0` is defined):

```javascript
  _cursorOffset: 0,
  _boundSelectionChange: null,
```

- [ ] **Step 3: Update the "select" cursor test to use selectionchange**

In `frontend-console/tests/writingView.test.js`, replace the test at lines 195-201:

```javascript
  it("select updates _cursorOffset and re-renders the panel", () => {
    const editor = document.getElementById("writing-editor")
    editor.selectionStart = 3
    editor.dispatchEvent(new Event("select"))
    expect(writingView._cursorOffset).toBe(3)
    expect(document.getElementById("writing-panel-container").innerHTML).toContain("Scene A")
  })
```

Replace with:

```javascript
  it("selectionchange updates _cursorOffset and re-renders the panel", () => {
    const editor = document.getElementById("writing-editor")
    editor.selectionStart = 3
    editor.focus()
    document.dispatchEvent(new Event("selectionchange"))
    expect(writingView._cursorOffset).toBe(3)
    expect(document.getElementById("writing-panel-container").innerHTML).toContain("Scene A")
  })
```

- [ ] **Step 4: Run writing view tests to verify**

Run:

```bash
cd frontend-console && npm test -- --run writingView.test.js
```

Expected: all writing view tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend-console/views/writingView.js frontend-console/tests/writingView.test.js
git commit -m "fix(writing): use selectionchange event for textarea cursor tracking

onselect does not fire on textarea in real browsers. Switch to
document-level selectionchange with activeElement guard."
```

---

### Task 2: Move inline fastapi imports to module level in dedup_service.py

**Files:**
- Modify: `backend/modules/world/services/dedup_service.py:1-38, 427-428, 437-438, 448-449, 458-459, 468-469, 476-477, 571-572`

**Why:** `from fastapi import HTTPException` and `from fastapi import status as http_status` are imported 7 times inside method bodies. These are standard library imports with no circular-import risk and belong at module level.

- [ ] **Step 1: Add module-level imports**

In `backend/modules/world/services/dedup_service.py`, add after line 12 (`from typing import Any`):

```python
from fastapi import HTTPException
from fastapi import status as http_status
```

- [ ] **Step 2: Remove all inline fastapi imports**

Remove the following 7 pairs of inline imports (they are identical at each location):

- Lines 427-428: inside `merge_candidate_into_entity` — target entity not found check
- Lines 437-438: inside `merge_candidate_into_entity` — candidate entity not found check
- Lines 448-449: inside `merge_candidate_into_entity` — target not canonical check
- Lines 458-459: inside `merge_candidate_into_entity` — candidate not draft check
- Lines 468-469: inside `merge_candidate_into_entity` — self-merge check
- Lines 476-477: inside `merge_candidate_into_entity` — cross-novel check
- Lines 571-572: inside `_build_merge_response`

Each pair to remove is:

```python
            from fastapi import HTTPException
            from fastapi import status as http_status
```

- [ ] **Step 3: Run world tests to verify**

Run:

```bash
cd backend && pytest modules/world/tests/test_world.py -q --tb=short
```

Expected: all world tests pass.

- [ ] **Step 4: Commit**

```bash
git add backend/modules/world/services/dedup_service.py
git commit -m "refactor(world): move fastapi imports to module level in dedup_service"
```

---

### Task 3: Add frontend split_pos upper-bound validation

**Files:**
- Modify: `frontend-console/views/writingView.js:1166`

**Why:** `_showSplitSceneForm` only validates `splitPos >= 1` on the frontend. If the user enters `splitPos >= contentLength`, the backend returns a 422 with no user-friendly toast since only `err.message` is shown. Adding a frontend check gives a clear warning before the request is made.

- [ ] **Step 1: Add contentLength upper-bound validation**

In `frontend-console/views/writingView.js`, change line 1166:

```javascript
        if (!splitPos || splitPos < 1) { toast("请输入有效的断章位置", "warning"); return }
```

Replace with:

```javascript
        if (!splitPos || splitPos < 1) { toast("请输入有效的断章位置", "warning"); return }
        if (splitPos >= contentLength) { toast("断章位置必须小于正文长度", "warning"); return }
```

- [ ] **Step 2: Run frontend tests to verify no regression**

Run:

```bash
cd frontend-console && npm test -- --run writingView.test.js
```

Expected: all writing view tests pass.

- [ ] **Step 3: Commit**

```bash
git add frontend-console/views/writingView.js
git commit -m "fix(writing): validate splitPos upper bound on frontend before API call"
```

---

### Task 4: Extract allowlist constants to module level in outlineView.js

**Files:**
- Modify: `frontend-console/views/outlineView.js:133-134, 220, 279`

**Why:** `allowedTags` and `allowedStatuses` Set objects are created identically inside `_renderSceneCards()`, `_renderThreads()`, and `_renderArcs()`. Extracting them to module-level constants avoids redundant allocations.

- [ ] **Step 1: Define module-level constants**

In `frontend-console/views/outlineView.js`, add near the top of the file (before the `outlineView` object literal, after any imports):

```javascript
const SCENE_ALLOWED_TAGS = new Set(["draft", "hook", "inciting_incident", "rising_action", "climax", "valley", "transition", "payoff"])
const ENTITY_ALLOWED_STATUSES = new Set(["canonical", "draft", "candidate", "deprecated"])
```

- [ ] **Step 2: Replace inline Sets with module constants**

In `_renderSceneCards()` (line 133-134), replace:

```javascript
    const allowedTags = new Set(["draft", "hook", "inciting_incident", "rising_action", "climax", "valley", "transition", "payoff"])
    const allowedStatuses = new Set(["canonical", "draft", "candidate", "deprecated"])
```

with:

```javascript
    const allowedTags = SCENE_ALLOWED_TAGS
    const allowedStatuses = ENTITY_ALLOWED_STATUSES
```

In `_renderThreads()` (line 220), replace:

```javascript
    const allowedStatuses = new Set(["canonical", "draft", "candidate", "deprecated"])
```

with:

```javascript
    const allowedStatuses = ENTITY_ALLOWED_STATUSES
```

In `_renderArcs()` (line 279), replace:

```javascript
    const allowedStatuses = new Set(["canonical", "draft", "candidate", "deprecated"])
```

with:

```javascript
    const allowedStatuses = ENTITY_ALLOWED_STATUSES
```

- [ ] **Step 3: Run outline tests to verify**

Run:

```bash
cd frontend-console && npm test -- --run outlineView.test.js
```

Expected: all outline view tests pass.

- [ ] **Step 4: Commit**

```bash
git add frontend-console/views/outlineView.js
git commit -m "refactor(outline): extract allowlist Sets to module-level constants"
```

---

## Final Verification

Run these commands to confirm nothing is broken:

```bash
cd backend && pytest modules/world/tests/test_world.py -q --tb=short
cd frontend-console && npm test -- --run writingView.test.js outlineView.test.js
node --check frontend-console/api.js
```

Expected: all selected tests pass, syntax check exit 0.
