# Round 2 Acceptance Validation — 2026-06-12

## Scope

验收对象是当前 `minimal-core` HEAD：

- `b47f01b feat: scenario gap closure round 2`
- `02ac034` ~ `c4fd10a` 的 round2 review fixes
- 当前工作树另有未跟踪文件 `docs/superpowers/plans/2026-06-12-code-review-fixes-round2.md`，本次未修改业务代码，也未回滚其他 agent 改动。

对照文档：

- `docs/核心业务场景与预期行为.md`
- `frontend-console/e2e/scenario-coverage.md`
- `docs/superpowers/plans/2026-06-12-scenario-gap-closure-round2.md`

## Fresh Verification

```bash
cd backend && pytest modules/project/tests/test_project.py modules/imports/tests/test_imports.py modules/writing/tests/test_writing.py modules/outline/tests/test_scene.py modules/outline/tests/test_foreshadowing_reveal.py modules/world/tests/test_world.py modules/rag/tests/test_indexing.py modules/context/tests/test_context.py tests/unit/test_context.py tests/unit/test_world_services_revision_event_helpers.py -q --tb=short
```

Result: `318 passed in 9.48s`

```bash
cd frontend-console && npm test -- --run projectView.test.js writingView.test.js worldView.test.js outlineView.test.js xss-rendering.test.js
```

Result: `5 files, 91 tests passed`

```bash
cd frontend-console && node --check api.js
```

Result: exit code `0`

```bash
cd frontend-console && npx playwright test project-recycle-bin.spec.js import-errors.spec.js writing-conflict.spec.js world.spec.js outline-scenes.spec.js --reporter=list
```

Sandbox run failed because `uvicorn` could not bind `0.0.0.0:8000`. Re-run with approved local-server permission:

Result: `21 tests`, `19 failed`, `2 skipped`.

## Acceptance Result

Round 2 substantially improved backend and frontend unit coverage. The earlier major gaps are no longer accurate as stated:

- Writing split now has `POST /api/writing/chapters/{chapter_index}/split`, backend service orchestration, outline chunk remapping, and frontend call path.
- Writing Scene panel now has cursor-offset awareness and uses `selectionchange` for textarea cursor tracking.
- World frontend/API now exposes merge, rollback, and CharacterKnowledge entry points.
- Outline backend has foreshadowing/reveal API coverage and frontend has basic reorder / AI generate entry points.
- RAG and Context have backend regression coverage for repeated indexing, embedding degradation, and knowledge-boundary handling.
- World rollback docs were updated to describe active `/rollback` and legacy `/rollback-by-revision`.

However, scenario-level acceptance is **not ready** because the new/updated Playwright suite is not executable in its current form.

## Findings

### 1. Scenario E2E Navigation Is Broken

Most failing E2E tests create a project by API, write `novel_currentProjectId` into localStorage, reload `/`, then click a sidebar nav item. The page remains on `#view-title = 项目`.

Affected files include:

- `frontend-console/e2e/world.spec.js`
- `frontend-console/e2e/outline-scenes.spec.js`
- `frontend-console/e2e/writing-conflict.spec.js`
- likely the same pattern in `writing.spec.js`, `rag.spec.js`, `context.spec.js`, `outline-threads-arcs.spec.js`, `world-relations-aliases.spec.js`, `deep-import*.spec.js`

This makes the E2E coverage matrix unreliable: tests exist, but the user paths are not actually being verified.

### 2. Import Error E2E Is Not Runnable

`frontend-console/e2e/import-errors.spec.js` waits for `[data-action="toggle-import"]`, but the project view remains at the initial loading state during the test. It also references fixtures that are absent from `frontend-console/e2e/helpers/fixtures/`:

- `test.pdf`
- `oversized.bin`

Current fixture directory only contains:

- `sample-novel.txt`
- `six-chapter-novel.txt`

### 3. Coverage Matrix Is Stale

`frontend-console/e2e/scenario-coverage.md` says “回收站恢复与永久删除 E2E 待实现”, but `project-recycle-bin.spec.js` now exists. Because that test currently fails, the correct status is not “已覆盖”; it should be “已编写但未通过验收”.

### 4. Remaining Explicit Scenario Gaps

These are still legitimate gaps after round2:

- World entity rollback E2E is still `test.fixme` because there is no stable TextArchive / EntityRevision seed helper.
- Outline foreshadowing/reveal management UI is still `test.fixme`; backend API exists, UI does not.
- Deep import “real” E2E uses `/api/imports/deep/sync`, so it validates the synchronous shortcut, not the documented background `async_tasks` path, browser-close recovery, or task polling.
- Import error E2E lacks empty-file / encoding-failure coverage.
- Full Playwright suite was not proven green.

## Follow-up Plan

补做计划写入：

`docs/superpowers/plans/2026-06-12-scenario-e2e-stabilization-round3.md`
