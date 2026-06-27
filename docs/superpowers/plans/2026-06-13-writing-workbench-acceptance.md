# 手工写作工作台验收 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verify and complete acceptance of the "手工写作工作台" user path, including backend coverage, frontend E2E, and real-LLM scene-card extraction on 《诡秘之主 第一部》 chapters 1-3.

**Architecture:** The implementation already exists across `backend/modules/writing`, `backend/modules/outline`, `backend/modules/rag`, and `frontend-console/views/writingView.js`. This plan focuses on running acceptance checks, fixing any gaps, and producing a real-LLM extraction record.

**Tech Stack:** Python/FastAPI + async SQLAlchemy + vanilla JS + Playwright + pytest + DeepSeek LLM (configured via `.env`).

---

## Context for Agents

- Backend module: `backend/modules/writing` already implements draft CRUD, version auto-increment, optimistic conflict (`expected_version` → 409), chapter split, and publish task enqueue to RAG/memory.
- Frontend view: `frontend-console/views/writingView.js` already implements the three-pane workbench (scene tree, editor, scene card panel), autosave, publish, version history, split, cursor linkage, AI extract dialog, localStorage backup, and 409 conflict toast.
- Existing tests:
  - Backend: `backend/modules/writing/tests/test_writing.py` (53 tests passed).
  - Frontend: `frontend-console/e2e/writing.spec.js` (12 tests) and `frontend-console/e2e/writing-conflict.spec.js` (1 test).
- Seed data for real LLM extraction: `backend/tests/e2e/seed_data.py` + `backend/tests/e2e/samples/lotm_chapters_1_2_3.txt`.
- LLM is configured: `llm_model=deepseek-v4-flash`, `llm_base_url=https://api.deepseek.com`, key present.

---

## Task 1: Backend Writing Module Acceptance Verification

**Files:**
- Run tests in: `backend/modules/writing/tests/test_writing.py`
- Inspect: `backend/modules/writing/api.py`, `backend/modules/writing/services.py`, `backend/modules/writing/repositories.py`

- [ ] **Step 1: Run backend writing tests**

Run:
```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist/backend
pytest modules/writing/tests -v
```

Expected: all tests pass (currently 53).

- [ ] **Step 2: Verify coverage of acceptance requirements**

Confirm the test file exercises:
- `test_create_auto_increment_version` → version_number increments on publish.
- `test_update_draft_conflict_detection` / `test_update_draft_no_conflict_when_expected_version_matches` → 409 expected_version behavior.
- `test_split_chapter_at_offset_creates_new_chapter_without_publish_task` → split does not enqueue RAG.
- `test_publish_creates_rag_chunks` → publish enqueues publish_chapter/RAG indexing.
- Draft CRUD, version history, list chapters.

If any requirement lacks a test, add a minimal test in `backend/modules/writing/tests/test_writing.py`.

- [ ] **Step 3: Run lint**

Run:
```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist
make lint
```

Expected: no new lint errors in writing/outline/rag modules.

- [ ] **Step 4: Commit**

```bash
git add backend/modules/writing/tests/test_writing.py
git commit -m "test(writing): verify backend acceptance coverage"
```

---

## Task 2: Frontend Writing E2E Acceptance Verification

**Files:**
- Run tests in: `frontend-console/e2e/writing.spec.js`, `frontend-console/e2e/writing-conflict.spec.js`
- Inspect: `frontend-console/views/writingView.js`, `frontend-console/playwright.config.js`

- [ ] **Step 1: Run both E2E specs together**

Run:
```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist/frontend-console
npx playwright test e2e/writing.spec.js e2e/writing-conflict.spec.js --reporter=list
```

Expected: 13 tests pass (12 + 1).

If Playwright only runs one file, check `playwright.config.js` and ensure both files are included (they are in `testDir: "./e2e"`; the issue may be test isolation or reuseExistingServer). Fix by running them sequentially in one command or ensure webServer reuse does not cause state bleed.

- [ ] **Step 2: Verify acceptance criteria coverage**

Map each requirement to a test in the two spec files:
- 空状态 / 新建章节 → `writing.spec.js` first two tests.
- 暂存 → "编辑章节内容并暂存".
- 发布 → "发布章节".
- Scene 切换不丢内容 → "Scene 切换不丢失内容".
- 版本历史 → "版本历史查看与恢复".
- 断章 → "新 Scene 创建和断章更新左侧树".
- 光标联动 → "光标位置联动右侧 Scene 卡面板".
- AI 提取弹窗 → "AI 提取章节卡按钮和对话框".
- localStorage 备份 → "离线恢复 — localStorage 后备内容".
- 多 Tab 冲突 → "多 Tab 冲突检测 — 草稿被其他会话删除" and `writing-conflict.spec.js` "409 冲突 — 其他会话已更新草稿版本".

If the localStorage backup test is weak (only checks editor visibility), strengthen it to assert that a backup entry is restored into the editor after reload.

- [ ] **Step 3: Strengthen localStorage backup test (optional if weak)**

Modify `frontend-console/e2e/writing.spec.js` test "离线恢复 — localStorage 后备内容" to:
1. Create a draft via API.
2. Load workbench, type content, navigate away (trigger `onDeactivate`).
3. Reload workbench.
4. Assert editor contains the backed-up content.

- [ ] **Step 4: Run lint / format on frontend (if available)**

Run:
```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist/frontend-console
npx eslint e2e/writing.spec.js e2e/writing-conflict.spec.js 2>/dev/null || echo "eslint not configured, skip"
```

- [ ] **Step 5: Commit**

```bash
git add frontend-console/e2e/writing.spec.js frontend-console/e2e/writing-conflict.spec.js
git commit -m "test(writing): verify frontend E2E acceptance coverage"
```

---

## Task 3: Real LLM Scene-Card Extraction on 《诡秘之主 第一部》 Chapters 1-3

**Files:**
- Use seed script: `backend/tests/e2e/seed_data.py`
- Use sample text: `backend/tests/e2e/samples/lotm_chapters_1_2_3.txt`
- Endpoint: `POST /api/outline/generate?novel_id=<id>&start_chapter=1&end_chapter=3`

- [ ] **Step 1: Create a standalone acceptance script**

Create `backend/scripts/acceptance_writing_extraction.py` that:
1. Connects to the development PostgreSQL database (from `.env` `DATABASE_URL`).
2. Loads seed data for project "诡秘之主 第一部" with chapters 1-3 from the sample file.
3. Calls the outline generation service / API for `start_chapter=1`, `end_chapter=3` using real LLM.
4. Queries the resulting `scenes` table for the project.
5. Prints:
   - Project ID.
   - Number of scenes created/updated.
   - Per-scene: scene_index, title, goal, core_conflict, emotional_beat, must_happen, must_not_happen, narrative_tag.

- [ ] **Step 2: Run the acceptance script**

Start the backend and worker:
```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist
make dev
```

In another shell, run:
```bash
cd /Users/tywww/Desktop/项目/ai-writing-assist/backend
python scripts/acceptance_writing_extraction.py
```

Expected: script completes with real LLM output, scene cards persisted, and counts/fields printed.

- [ ] **Step 3: Record the acceptance result**

Save the console output to `docs/acceptance/writing-extraction-lotm-ch1-3-<timestamp>.md`.

- [ ] **Step 4: Commit**

```bash
git add backend/scripts/acceptance_writing_extraction.py docs/acceptance/writing-extraction-lotm-ch1-3-*.md
git commit -m "test(writing): add real LLM extraction acceptance for LOTM ch1-3"
```

---

## Task 4: Compile Acceptance Report and Update Documentation

**Files:**
- Create: `docs/acceptance/2026-06-13-writing-workbench-acceptance-report.md`
- Update: `backend/modules/writing/README.md`, `frontend-console/views/writingView.js` header comments (if needed)

- [ ] **Step 1: Write acceptance report**

Include:
1. Scope summary.
2. Backend test results (command + pass count + key test names).
3. Frontend E2E results (command + pass count + test list).
4. Real LLM extraction results (scene count, key fields, project ID).
5. Gaps found and fixes applied.
6. Sign-off statement.

- [ ] **Step 2: Update module README if public contract changed**

If any API was added or changed during gap fixes, update `backend/modules/writing/README.md` with new endpoints/behaviors. If no API changed, skip.

- [ ] **Step 3: Commit**

```bash
git add docs/acceptance/2026-06-13-writing-workbench-acceptance-report.md
git add backend/modules/writing/README.md  # if changed
git commit -m "docs(writing): acceptance report for manual workbench"
```

---

## Self-Review

1. **Spec coverage:** Each user acceptance requirement maps to a test or real-LLM run in the plan.
2. **Placeholder scan:** No TBD/TODO; all steps have concrete commands.
3. **Type consistency:** Field names match `scenes` table columns and frontend view state.

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-06-13-writing-workbench-acceptance.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - Dispatch fresh subagents per task, review between tasks, fast iteration.

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
