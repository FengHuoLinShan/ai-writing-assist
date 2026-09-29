# Post-Agent Acceptance Validation — 2026-06-12

## Scope

验收对象是当前 `minimal-core` 工作树中的未提交改动，对照：

- `docs/superpowers/plans/2026-06-11-post-agent-acceptance-fixes.md`
- `docs/核心业务场景与预期行为.md`
- `frontend-console/e2e/scenario-coverage.md`

本报告只记录验收结论和剩余差距，不回滚其他 agent 的改动。

## Fresh Verification

```bash
cd backend && pytest modules/project/tests/test_project.py modules/imports/tests/test_imports.py modules/writing/tests/test_writing.py modules/outline/tests/test_scene.py modules/world/tests/test_world.py -q --tb=short
```

Result: `159 passed in 5.95s`

```bash
cd backend && pytest tests/unit/test_world_services_revision_event_helpers.py -q --tb=short
```

Result: `43 passed in 0.09s`

```bash
cd frontend-console && npm test -- --run projectView.test.js writingView.test.js worldView.test.js xss-rendering.test.js
```

Result: `4 passed`, `55 passed`

```bash
node --check frontend-console/api.js
```

Result: exit code 0

## Acceptance Result

上一轮补救计划中的阻断项大多已经完成：

- Project soft-delete contract: `ProjectRepository.get()` 隐藏软删除项目，restore 使用显式恢复路径。
- Import success to deep import: `projectView` 新建导入和导入到当前项目后都会提示并调用 `api.imports.deepImport(...)`。
- Scene chunk split API: `outline` 已提供 `split_scene_chunk()`，并更新 `scene_chunks` offset。
- Entity rollback: `/api/world/entities/{entity_id}/rollback` 已改为 Delta Log + Text Archive；legacy revision rollback 移到 `/rollback-by-revision`。
- Manual duplicate confirmation: `WorldEntityService.create()` 对高相似实体返回 409，前端可确认 `force_create`。
- Focused frontend XSS regressions: command suggestions、context/generate 输出已有单测覆盖。

## Remaining Code/Doc Gaps

### 1. Writing split scene is not the full documented operation path

`writingView._showSplitSceneForm()` now calls `api.outline.splitSceneChunk(...)`, which updates scene chunk mapping. However `docs/核心业务场景与预期行为.md` 场景 4 要求“在此处断章”同时：

- 拆分当前 Chapter 正文；
- 新增一个 `writing_drafts` Chapter 记录；
- 刷新左侧 Chapter 树；
- 更新 `scene_chunks` 物理映射；
- 不触发 RAG 索引，等用户保存时触发。

Current code covers only the outline mapping portion. There is no `writing` API/service that splits a chapter at an offset and coordinates with outline.

### 2. Scene panel is not cursor-position aware

Docs require same Chapter spanning two Scenes to switch the right Scene panel by cursor offset. Current `writingView._findCurrentScene()` returns the first scene matching `chapter_ids` or any `scene_chunks` for the chapter, without considering `start_pos <= cursor < end_pos`.

### 3. World management operation paths still lack executable UI/E2E coverage

Backend has merge, rollback, and CharacterKnowledge services, but current frontend/E2E coverage is still partial:

- No visible entity merge path covering candidate selection, comparison, confirmation, and result refresh.
- No rollback UI/E2E path using `/rollback` target scene index.
- No CharacterKnowledge UI/E2E path, especially `false_belief` requiring `misconception`.
- `api.js` lacks world client methods for revisions/rollback/knowledge/merge.

### 4. Outline management remains partial against scenario 6

Backend supports Scene reorder and AI structure generation, and persists foreshadowing/reveal output internally, but scenario 6 still lacks a complete user path:

- No verified drag reorder UI path.
- No verified AI structure generation UI path from `outlineView`.
- No public CRUD/user workflow for foreshadowing and reveal plans.
- `frontend-console/e2e/scenario-coverage.md` still marks outline gaps as uncovered.

### 5. RAG/Context support paths need scenario-level regression tests

The backend has RAG indexing and context budget/knowledge-boundary logic, but E2E coverage remains basic. Missing scenario-level tests:

- Repeated chapter save replaces old chunks instead of leaving stale chunks.
- Embedding failure still returns keyword results with warning.
- Character perspective context hides or transforms `hidden_truth` according to CharacterKnowledge.

### 6. Module docs are stale after rollback changes

`docs/modules/02_world.md` and `backend/modules/world/README.md` still describe `/rollback` as legacy or “后续替换为 Delta Replay”. Current code makes `/rollback` the active Delta/TextArchive path and `/rollback-by-revision` the legacy route.

## Follow-up Plan

补做计划已写入:

`docs/superpowers/plans/2026-06-12-scenario-gap-closure-round2.md`
