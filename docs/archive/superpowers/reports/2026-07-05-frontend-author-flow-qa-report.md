# Frontend Author Flow QA Report - 2026-07-05

## Scope

This report records an end-to-end frontend-only authoring acceptance pass for
`ai-writing-assist`, using the app as a web-novel author from a blank project.

Test project:

- Title: `霭潮观澜录`
- Project id: `a389bffb-b39f-4302-b3a3-7229c2b0742e`
- Main URL: `http://localhost:8080/#workbench/a389bffb-b39f-4302-b3a3-7229c2b0742e/writing`
- Browser-only constraint: all product interactions were performed through the
  frontend. Terminal was used only for browser control and local state checks.

Intended author workflow:

1. Create a new novel project.
2. Start from world bible / worldbuilding settings.
3. Create outline, story thread, chapter arc, characters, places, organizations,
   and rules.
4. Use writing page to draft body text.
5. Use AI reference and generation tools during writing.
6. Create maps after writing chapters.
7. Use AI tools to review/check and publish.

Current result:

- Project creation worked.
- World bible creation and saving mostly worked.
- Manual world object creation worked after avoiding hidden stale form controls.
- Manual story thread and arc creation worked, but list display lost descriptions.
- AI reference confirmation opened and a generation task completed.
- Writing body text, generated outline result visibility, chapter maps, review,
  and publishing were blocked by frontend/product issues below.

## Test Data Created

World bible page:

- `世界基本背景`

World objects:

- Characters: `沈澜`, `柳烨`, `许筠`, `赵洛岚`
- Locations: `琉璃湾`, `归潮塔群`, `雾市`
- Organizations: `潮灯局`, `律霄署`
- Rule: `灵潮与灵镜读取法则`

Outline:

- Story thread: `归一潮失踪案主线`
- Arc: `三章短篇：潮雾、镜局、归潮`, chapter range `1-3`

Map:

- One world map was created through quick create, but it contained no place
  facts or candidates.

## Blocking Issues

### P0 - Writing page cannot create the first chapter

Reproduction:

1. Open
   `http://localhost:8080/#workbench/a389bffb-b39f-4302-b3a3-7229c2b0742e/writing`.
2. Click `+ 新建章节`.
3. Click again using the visible DOM node for the same button.

Expected:

- A new chapter form opens, or a first chapter is created and becomes editable.
- If creation fails, the user sees an actionable error message.

Actual:

- No modal opens.
- No chapter appears.
- No visible toast/error appears.
- Browser console did not show a useful error during the click.

Impact:

- This blocks drafting正文 from a new project.
- It also blocks later review/publish and chapter-linked map creation.

Suggested investigation:

- Check `frontend-console/views/writingView.js` empty-state click handler.
- Verify the action dispatch path for `+ 新建章节`.
- Add a frontend test for empty writing workspace -> create first chapter.
- Confirm whether the backend chapter/draft create API exists and is called.

### P0 - World bible projection refresh always fails

Reproduction:

1. Open world -> `世界书`.
2. Create `世界基本背景`.
3. Paste and save long world bible text.
4. Click `刷新投影`.

Expected:

- A projection refresh task runs and completes.
- The refreshed projection becomes available for AI reference/context.
- If the task cannot run, the user sees a product-level explanation.

Actual:

- The task fails with:

```text
ValueError: No handler registered for task type: world_bible_projection_refresh.
Registered types: ['deep_import', 'scene_auto_extraction', ...]
```

Impact:

- AI reference does not reliably include world bible content.
- The UI exposes internal task registry details to the author.

Suggested investigation:

- Register the `world_bible_projection_refresh` task handler, or change the
  frontend to call the currently supported projection refresh endpoint.
- Replace raw internal exception text with a concise author-facing error.
- Add backend/frontend coverage for world bible save -> refresh projection.

### P0 - AI generation completes but generated chapter/scene results are not visible

Reproduction:

1. Open `生成`.
2. Select `章节与场景结构`.
3. Fill intent for a 3-chapter / 6-scene short story.
4. Change AI reference scope from default `章节 1` to `全部`.
5. Click `重新整理`, then `确认使用`.
6. Wait for task completion.
7. Click `查看大纲`.
8. Check `大纲 -> 剧情线`, `篇章纲`, `场景卡`, and top-level `场景`.

Expected:

- The generated chapter cards and scene cards are visible as candidates or
  drafts.
- `查看大纲` navigates to the result-bearing view.

Actual:

- Task showed `100% · 已完成`.
- `查看大纲` navigated to `大纲 -> 剧情线`.
- Only the manually created story thread and arc were visible.
- No generated chapter/scene output appeared in outline or scene workspace.

Impact:

- The generation center appears successful while giving the author no usable
  artifact.
- This blocks the intended AI-assisted structure workflow.

Suggested investigation:

- Trace `plot_structure_generate` / chapter generation task output persistence.
- Verify frontend result routing after task completion.
- Ensure generated chapter cards and scene cards are written as visible
  candidates/drafts.
- Add E2E coverage for generate center -> AI reference confirmation -> task
  complete -> visible result.

### P0 - Compile/review/publish route caused browser control to hang

Reproduction:

1. From the created project, click top-level `编译`.
2. Browser automation timed out while trying to read the page.
3. A reconnect attempt also timed out before a lightweight DOM read could finish.

Expected:

- Compile/review/publish page loads quickly and shows an empty-project state.
- It should explain that no chapters are available, or provide a next action.

Actual:

- Navigation/read attempts repeatedly timed out in browser control.

Impact:

- The AI review/check/publish end of the workflow could not be verified.

Suggested investigation:

- Test compile route with this project id and with a fresh empty project.
- Check for expensive synchronous rendering, infinite loops, or blocking fetches
  in the compile view.
- Add an empty-project compile page test.

## Major Functional / UX Issues

### P1 - AI reference default scope is invalid for a blank project

Reproduction:

1. Start generation from a blank project with no chapters.
2. AI reference modal opens.

Expected:

- For blank projects, default scope should be `项目` or `全部`.
- Existing world bible and world objects should be included or clearly selectable.

Actual:

- Default scope was `章节`, chapter `1`.
- Reference summary initially showed `暂无已选资料`.
- After changing to `全部` and `工作稿`, summary included project style and hard
  constraints, but did not visibly include saved world bible text or world
  object summaries.

Impact:

- Authors can accidentally generate with almost no project context.
- Existing worldbuilding work is not obviously used by AI.

Suggested investigation:

- For `scope=full`, include saved world bible pages and world objects in the AI
  reference summary when token budget allows.
- If excluded by budget, show why and how to include them.
- Use user-facing names instead of requiring raw IDs.

### P1 - Story thread and arc descriptions are not visible after creation

Reproduction:

1. Create story thread `归一潮失踪案主线` with a detailed description.
2. Create arc `三章短篇：潮雾、镜局、归潮` with a detailed description.
3. Return to the list views.

Expected:

- The description column shows the saved description or a truncated preview.

Actual:

- Description column shows `-` for both manually created items.
- Type/range fields show, so the row is created, but the narrative description is
  not visible.

Impact:

- Authors cannot confirm the structure they just entered from the list.
- It looks like data may have been lost.

Suggested investigation:

- Check create payload field names vs list rendering field names in
  `frontend-console/views/outlineView.js` and backend schemas.
- Add a test for create thread/arc with description -> list preview displays it.

### P1 - Map quick create sees locations but cannot place them

Reproduction:

1. Create 3 location world objects: `琉璃湾`, `归潮塔群`, `雾市`.
2. Open `地图`.
3. Click `快速创建`.

Expected:

- Existing location objects are offered as placeable map items, or the UI
  explains what extra location metadata is needed.

Actual:

- Map overview says `地图 0 张，地点 3 个`.
- Quick-create modal says `暂无可放置地点`.
- It also says `缺少地点方向/距离关系，可在地点详情补充`, but there is no direct
  link or guided path to fill those fields.
- Creating anyway opens an empty map with `候选 0`, `事实 0`, `冲突 0`.

Impact:

- Authors cannot create chapter/world maps from normal location objects.
- The map path is technically available but produces an empty artifact.

Suggested investigation:

- Either allow approximate placement from location objects without direction
  metadata, or provide a guided missing-metadata editor.
- Show a clear pre-create warning if the result will be empty.
- Add E2E coverage for location objects -> quick map -> visible markers.

## Accessibility / Usability Issues

### P2 - Several clickable controls are not semantic buttons/tabs

Observed examples:

- Home `创建新项目` is a clickable `div#btn-create-project`.
- Main nav items are `li.nav-item`, not links/buttons.
- World and outline secondary tabs are `span.subnav-item` with `tabIndex=-1`.
- Generate type cards are clickable `div.generate-card`.

Expected:

- Clickable navigation/actions should be `button`, `a`, or proper ARIA tabs with
  keyboard support.

Actual:

- These controls do not appear in the visible interactive control tree as normal
  buttons/links/tabs.

Impact:

- Keyboard and assistive technology users cannot reliably operate key workflows.
- Browser automation and tests need brittle CSS selectors instead of semantic
  locators.

Suggested investigation:

- Convert action cards and nav/subnav entries to semantic controls.
- Add keyboard activation and visible focus states.
- Add accessibility-oriented frontend tests for core author flow navigation.

### P2 - Hidden modal fields remain in DOM and interfere with interactions

Observed examples:

- After creating world bible/entity/thread/arc items, old modal fields remain in
  the DOM with their original ids while hidden.
- Example hidden ids observed after closing entity modal:
  `create-entity-name`, `create-entity-type`, `create-entity-summary`.

Expected:

- Closed modals should be unmounted or hidden with proper inert/aria-hidden
  behavior.
- Active forms should not share ids with hidden stale forms.

Actual:

- Hidden controls remain queryable and can be selected by id.
- Automation attempted to fill a hidden stale field and timed out.

Impact:

- Assistive technology may encounter stale controls.
- Tests and browser automation become flaky.

Suggested investigation:

- Unmount modal content on close, or apply `inert` and ensure unique active ids.
- Scope modal queries to visible active dialogs.

### P2 - Raw enum values are shown to Chinese authors

Observed examples:

- World object type column shows `character`, `location`, `faction`, `rule`.
- Story thread type shows `main`.

Expected:

- Chinese labels such as `人物`, `地点`, `组织`, `规则`, `主线`.

Actual:

- Internal enum values are displayed in author-facing tables.

Impact:

- Makes the product feel unfinished and harder to scan.

Suggested investigation:

- Centralize frontend enum label mapping and apply it in world/outline tables.
- Add tests for visible labels.

### P2 - Ambiguous create buttons cause strict/assistive-name conflicts

Observed example:

- In map view, searching for `创建` matched `快速创建`, `创建世界地图`, and modal
  `创建`.

Expected:

- Modal submit button should have a scoped/unique accessible name such as
  `创建地图`.

Actual:

- Multiple visible controls share overlapping accessible names.

Impact:

- Ambiguous for tests and potentially for assistive technology users.

Suggested investigation:

- Use specific submit labels: `创建地图`, `创建世界书页面`, `创建剧情线`, etc.

### P2 - Save success feedback is weak

Observed example:

- After saving world bible body text, the page did not show a clear success
  confirmation.
- The visible state remained focused on `投影状态：未刷新`.

Expected:

- Clear saved state: `已保存`, timestamp, or non-intrusive toast.

Actual:

- Save appeared to work because textarea retained content, but there was no
  strong confirmation.

Impact:

- Authors are unsure whether long worldbuilding text was saved.

## Suggested Fix Order

1. Fix writing empty-state `+ 新建章节`; this is the main author-flow blocker.
2. Fix AI generation result persistence/routing so completed tasks yield visible
   chapter/scene artifacts.
3. Fix world bible projection refresh handler or frontend endpoint.
4. Fix compile/review/publish route hang and empty-project state.
5. Improve AI reference defaults for blank projects and include world bible /
   world objects.
6. Make map quick-create produce useful markers from basic locations or guide the
   missing metadata.
7. Clean up semantic controls, hidden modals, enum labels, ambiguous button
   names, and save feedback.

## Handoff Notes For Repair Agent

Repair constraints:

- Preserve the existing vanilla JS frontend stack.
- Do not introduce a new frontend framework.
- Preserve external API/wire contracts unless a backend bug requires a narrow
  contract fix.
- Prefer targeted tests for touched flows before broad refactors.
- Existing dirty worktree contains unrelated changes; do not revert user or
  other-agent changes.

Likely frontend files:

- `frontend-console/views/writingView.js`
- `frontend-console/views/generateView.js`
- `frontend-console/shared/aiReferenceModal.js`
- `frontend-console/views/worldBibleView.js`
- `frontend-console/views/worldView.js`
- `frontend-console/views/outlineView.js`
- `frontend-console/views/mapView.js`
- `frontend-console/router.js`
- `frontend-console/styles.css`

Likely backend/task files:

- `backend/modules/world/tasks.py`
- `backend/infrastructure/tasks/api.py`
- `backend/modules/context/api.py`
- `backend/modules/outline/*`
- `backend/modules/writing/*`

Recommended verification:

- `cd frontend-console && npm test`
- Targeted Vitest tests for writing, generate, world bible, outline, map.
- Targeted backend pytest for any task/API contract touched.
- Browser QA on a new project:
  project -> world bible -> world objects -> outline -> generate -> writing
  first chapter -> map -> compile/review/publish empty and non-empty states.

## Follow-up Verification Addendum - After First Repair Pass

First repair pass completed the empty writing workspace path:

- Opening the project writing page and clicking the empty-state `+ 新建章节`
  now creates `第 1 章`.
- The lightweight editor can accept body text and save it as a draft.
- The full editor opens and shows `暂存`, `发布`, `剧情设定冲突检查`,
  `AI 续写`, `AI 工具`, and `打开地图`.

New blocking issue found during continued author-flow verification:

### P0 - Full editor `+ 新建` still calls browser `prompt()` and cannot create chapter 2

Reproduction:

1. Open the test project writing page.
2. Use empty-state `+ 新建章节` to create chapter 1.
3. Save chapter 1 text.
4. Click `完整编辑器`.
5. Click the editor toolbar `+ 新建`.

Expected:

- A product modal or inline form asks for the next chapter title/index, or a new
  chapter is created directly.
- The flow must work in the in-app browser and normal browser contexts without
  relying on blocking browser dialogs.

Actual:

- No new chapter appears.
- Console error:

```text
Error: prompt() is not supported.
    at Object._newChapter (.../views/writingView.js:1544:9)
```

Impact:

- Main author workflow can create the first chapter but cannot continue to
  chapter 2 from the full editor.
- This blocks the requirement to write a multi-chapter short story and create
  chapter-by-chapter maps.

Suggested investigation:

- Replace `prompt()` in `frontend-console/views/writingView.js` full-editor
  `new-chapter` flow with the same modal or direct create path used by the
  fixed empty-state first-chapter flow.
- Add a frontend test for:
  first chapter exists -> full editor `+ 新建` -> chapter 2 created and selected.
- Browser QA should verify chapter 1, chapter 2, and chapter 3 can be created
  without JavaScript prompt dialogs.

## Follow-up Verification Addendum - After Second Repair Pass

Second repair pass fixed the full editor `+ 新建` path enough for continued
author verification:

- Chapter 2 and chapter 3 can be created from the writing UI.
- Chapter body text can be entered and saved.
- The conflict-check modal opens and can run rule checks.

New blocking issue found at publish time:

### P0 - Publishing a saved chapter fails with aborted transaction and raw SQL error

Reproduction:

1. Open the test project writing page.
2. Create / edit chapter 3.
3. Save the draft.
4. Click `剧情设定冲突检查`, run the check, and close/apply any needed edits.
5. Click `发布`.

Expected:

- Publish task completes and the chapter becomes published/canonical.
- If a backend step fails, the UI shows a concise recoverable product-level
  message without leaking SQL internals.

Actual:

- Draft remains saved, but publish task fails.
- Visible modal says `发布失败`.
- Raw backend error is shown to the author:

```text
DBAPIError: (sqlalchemy.dialects.postgresql.asyncpg.Error)
<class 'asyncpg.exceptions.InFailedSQLTransactionError'>:
current transaction is aborted, commands ignored until end of transaction block
[SQL: UPDATE async_tasks SET progress=$1::FLOAT, heartbeat_at=$2::TIMESTAMP WITH TIME ZONE, updated_at=$3::TIMESTAMP WITH TIME ZONE WHERE async_tasks.id = $4::UUID]
...
```

Impact:

- This blocks the final required workflow step: AI/check and publish.
- It also exposes internal SQL and task implementation details to an author.

Suggested investigation:

- Inspect the `publish_chapter` task handler and transaction boundaries.
- Find the original failed statement before the task progress update; the
  visible error is likely a secondary transaction-aborted symptom.
- Ensure task progress/error updates happen in a clean transaction after rollback
  if the publish body fails.
- Add backend regression coverage for publishing a saved draft from the writing
  UI path.
- Add frontend coverage that publish failure messages are sanitized.

Additional continued-observation notes:

- After creating chapter 3, the new chapter initially appeared to inherit the
  previous chapter text. The author could overwrite and save it, but this is
  confusing and should be checked as part of the writing creation flow.
- The writing left rail is Scene-grouped (`北港旧巷`, `归潮塔事故`, etc.) and
  can show duplicated chapter labels. This is usable but confusing for a normal
  chapter-first author workflow.

## Follow-up Verification Addendum - After Third Repair Pass

Third repair pass fixed the publish task failure enough for continued browser
verification:

- Retrying publish no longer immediately fails with `InFailedSQLTransactionError`.
- The publish progress modal entered the RAG step and then closed without a raw
  DB error.
- The publish success signal remains weak; the UI does not clearly show
  `发布成功`, but the hard SQL failure no longer reproduces in this pass.

Map workflow remains blocked:

### P0 - Map quick create still cannot place existing story locations

Reproduction:

1. Use the same test project with world objects and chapter/scene structure.
2. Open top-level `地图`.
3. Click `快速创建`.

Expected:

- The author can create at least a useful world/chapter map from existing
  location objects or current Scene/chapter context.
- If extra spatial metadata is required, the UI offers a guided editor or a
  direct link to fill it.

Actual:

- The map page opens but shows `候选 0`, `事实 0`, `冲突 0`.
- Quick-create modal still says:

```text
缺少地点方向/距离关系，可在地点详情补充
暂无可放置地点
```

- This happens even though locations such as `琉璃湾`, `归潮塔群`, and `雾市`
  were created earlier and the writing flow now has Scene groups.

Impact:

- The required author workflow still cannot create meaningful maps after
  chapters.
- Conflict check still reports `当前 Scene 暂无地图上下文`.

Suggested investigation:

- Allow quick-create to place known location objects with default positions when
  relation/distance metadata is missing.
- Or add a guided missing-spatial-metadata flow reachable from quick-create.
- Ensure current Scene/chapter map context can be created or linked from the
  writing page and then visible in conflict check.
- Add browser/E2E coverage:
  locations exist -> quick-create -> map has visible placed locations/facts.

## Follow-up Verification Addendum - After Fourth Repair Pass

Timestamp: 2026-07-05 17:10 CST.

Fourth repair pass partially improved map quick-create, but the author workflow
is still blocked at end-to-end map creation.

### P0 - Map quick-create creates inconsistent state: duplicate map exists, but no visible facts

Reproduction from frontend only:

1. Open `http://localhost:8080/#workbench/a389bffb-b39f-4302-b3a3-7229c2b0742e/map`.
2. Click `快速创建`.
3. Observe the modal can now see existing locations:
   `归潮塔群`, `琉璃湾`, `雾市`.
4. Observe the modal warning:
   `缺少地点方向/距离关系，已生成等间距草稿`.
5. Click modal `创建`.
6. Return to the map page.

Expected:

- The map shows at least the three known location objects as placed map items.
- The inspector or counters show nonzero map facts/candidates, or a clear
  confirmation explains where the created map/facts went.
- Repeating quick-create should either open/update the existing quick-created
  map or clearly offer to replace it.

Actual:

- After clicking `创建`, the page still shows:

```text
候选 0
事实 0
冲突 0
暂无可检查的地图事实。
```

- The visible map body no longer shows `归潮塔群`, `琉璃湾`, or `雾市`.
- A subsequent create attempt logs:

```text
请求失败 (409)：同层级已存在名为 '快速创建世界地图' 的地图
```

Interpretation:

- The backend or API layer appears to believe a map named `快速创建世界地图`
  exists, but the current map UI does not show placed locations or facts.
- This is worse than a pure validation failure because the author cannot tell
  whether a map was created, where it is, or how to recover.

Impact:

- The required workflow step `每写一些章节创作对应的地图` remains blocked.
- The writing conflict check can still lack usable map context.

Suggested investigation:

- Verify quick-create persistence end to end: map row, map facts, markers, and
  frontend selected-map state should all update in one user-visible result.
- If a quick-created map already exists, make the UI select it or offer a
  replace/update flow instead of returning a raw 409.
- Add regression coverage for:
  existing locations -> quick-create modal -> create -> selected map shows
  visible location markers/facts and nonzero counters.
- Add an idempotent quick-create test:
  repeat create -> existing map is selected/updated or a recoverable UI choice
  is shown; no console-only raw 409.

## Follow-up Verification Addendum - After Fifth Repair Pass

Timestamp: 2026-07-05 17:26 CST.

Fifth repair pass fixed the map quick-create blocker in the main browser
verification:

- The map page now shows `归潮塔群`, `琉璃湾`, and `雾市`.
- The inspector now shows:

```text
候选 0
事实 3
冲突 0
```

- The writing conflict check for chapter 3 no longer reports
  `当前 Scene 暂无地图上下文`.
- After adding one missing outline detail to the chapter body, rule-based
  conflict check reports:

```text
17:23 · 发现 0 个冲突
问题 0 条
```

### P0 - AI soft review/reference confirmation times out

Reproduction from frontend only:

1. Open chapter 3 in the writing page.
2. Run `剧情设定冲突检查`.
3. Confirm the check and wait for the rule-based result to show 0 conflicts.
4. In the conflict modal, click `补充 AI 软冲突判断`.
5. In the `AI 参考资料` modal, leave default settings:
   project scope, canonical mode, no pending objects.
6. Click `确认使用`.

Expected:

- The AI/reference modal confirms selected context or shows a bounded,
  actionable error.
- The soft AI review starts and eventually shows AI judgment results, or a
  clear task status that can be retried.

Actual:

- The modal stays open and shows:

```text
请求超时，请检查后端服务是否运行
```

- No AI judgment result is created.
- The UI continues to show `参考资料摘要：暂无已选资料`.

Impact:

- This blocks the final author workflow requirement: use an AI tool to review
  before publishing.
- The error tells the author to check backend service availability even though
  the rest of the app is running, which is not actionable for a normal frontend
  user.

Suggested investigation:

- Inspect the AI reference confirmation path used from the conflict-check modal.
- Determine whether the timeout is caused by context compilation, route
  mismatch, missing chapter/scope parameter, or a long backend task without task
  polling.
- Ensure the frontend handles slow reference compilation with progress and a
  retryable task state instead of a generic timeout.
- Add coverage:
  chapter conflict result -> `补充 AI 软冲突判断` -> confirm references -> AI
  soft review task/result or clear recoverable UI.

### P2 - Chapter rows are listed but have zero layout size

Observation:

- In the writing page, the left chapter tree renders Scene rows with normal
  dimensions, but the nested chapter rows have `getBoundingClientRect()`
  width/height of `0`.
- Example rows still appear in page text:

```text
第 1 章 第 1 章 984 字
第 2 章 第 2 章 929 字
第 3 章 第三章 归潮尽头 1,095 字
```

- Direct click on `[data-action="select-chapter"][data-chapter="3"]` times out.
- Clicking the parent Scene row (`回声仓`) indirectly opens chapter 3, so the
  flow has a workaround but the visible chapter row itself is not reliably
  clickable.

Impact:

- A chapter-first author sees chapter rows in the tree but cannot click the row
  itself.
- This also makes automated and accessibility-oriented interaction brittle
  because the visible DOM exposes only surrounding controls, not the chapter row
  as a normal interactive target.

Suggested investigation:

- Fix chapter row layout inside collapsed/expanded Scene nodes so each row has a
  real clickable box.
- Ensure chapter rows are semantic buttons or list items with stable labels and
  accessible names.
- Add a frontend regression:
  render writing tree -> chapter row has nonzero dimensions -> clicking the
  row selects the chapter and enables save/publish/conflict-check controls.

## Follow-up Verification Addendum - After Sixth Repair Pass

Timestamp: 2026-07-05 17:50 CST.

Sixth repair pass fixed the P0 AI reference timeout in the main browser
verification:

- Clicking `补充 AI 软冲突判断` no longer ends with
  `请求超时，请检查后端服务是否运行`.
- `AI 参考资料` now compiles a reference package with summary data, for example:

```text
project: 1
scenes: 1
context_sections: 6
Token 251
```

- Confirming the compiled reference starts the AI soft review and returns an AI
  judgment. In this project the AI result was:

```text
AI 判断 1 条
状态：已生成
高
Scene 目标漂移
置信度 95%
```

- The author marked this AI judgment as `忽略` because it appears to come from a
  stale/incorrect Scene goal mentioning `林深`, while this short story's actual
  protagonist and authored setup use `沈澜`.

Two issues remain after main-thread browser verification.

### P1 - Chapter row accessibility fix is incomplete in the real writing page

After the sixth repair pass, nested chapter rows are now rendered as `button`
elements with `aria-label`, but they still have zero layout size in the actual
project page.

Main-thread evidence from
`http://localhost:8080/#workbench/a389bffb-b39f-4302-b3a3-7229c2b0742e/writing`:

```text
tag: BUTTON
data-action: select-chapter
data-chapter: 3
aria-label: 打开第 3 章：第三章 归潮尽头，1,095 字
display: flex
visibility: visible
rect: width 0, height 0, top 0, left 0
```

Directly clicking `[data-action="select-chapter"][data-chapter="3"]` still
times out in the browser. The workaround remains clicking the parent Scene row
(`回声仓`) to indirectly open the chapter.

Impact:

- The test added in the sixth pass does not reproduce the real layout failure.
- The author still cannot directly click the visible chapter row as a chapter
  row, despite the button/aria improvements.

Suggested investigation:

- Reproduce against the real scene-grouped writing tree with collapsed and
  expanded Scene nodes, not only the isolated component test fixture.
- Check whether chapter row buttons are rendered inside a detached/zero-size
  fragment while the visible text belongs to the parent Scene row.
- Ensure nested chapter rows have a real parent flow box and nonzero dimensions
  in the actual writing view after reload.

### P0 - Publish button appears to create versions but does not show or prove publish

Reproduction from frontend only:

1. Open chapter 3 in the writing page.
2. Ensure content is saved and AI soft review has been reviewed/ignored.
3. Click visible `发布`.
4. Wait 60-70 seconds.

Expected:

- A publish task/progress modal appears, or the chapter clearly transitions to
  `已发布`.
- The UI gives a durable success or failure state.
- If publish writes to RAG/canonical memory, the UI should expose success or a
  retryable task error.

Actual:

- No visible publish progress, success, failure, RAG, or task state appears.
- No raw SQL or request error appears.
- Each click appears to create another draft version:

```text
v4 -> v5 -> v6 (最新)
已保存
```

- The visible button remains `发布`; no `已发布` or `发布成功` signal appears.

Impact:

- The author cannot tell whether the final required publish step happened.
- Repeated clicks create extra versions, which looks like autosave rather than
  publish.
- The previously fixed backend publish failure may be fixed, but the frontend
  workflow still does not provide a verifiable published state.

Suggested investigation:

- Trace `data-action="publish"` in the current writing view: confirm whether it
  only saves a version, whether it starts the publish task, and whether task
  polling/success UI is wired.
- Add frontend regression:
  click publish -> publish task is started/polled -> success state visible and
  repeated clicks do not create redundant draft versions.
- Add backend/API regression if needed:
  publishing selected latest version returns/updates an observable published
  status.

## Final Main-Thread Verification Addendum - After Seventh Repair Pass

Timestamp: 2026-07-05 18:11 CST.

Seventh repair pass was verified in the in-app browser against the same author
project.

### Fixed and verified

#### Chapter row layout / direct selection

After reloading the writing page, nested chapter rows now have real layout boxes
and can be clicked directly:

```text
data-action: select-chapter
data-chapter: 3
tag: BUTTON
text: 第 3 章 第三章 归潮尽头 1,095 字
rect: width 189.85, height 46.99
```

Direct clicking the chapter row opened chapter 3 and showed its body. This
fixes the previous 0x0 click timeout.

#### Publish state

Publishing now gives a verifiable frontend state:

```text
第 3 章
v6
发布成功
```

No raw SQL, request failure, or task failure appeared. Repeated publish no
longer created a new draft-only version in the observed pass.

#### Final chapter publish pass

The short story now has three authored chapters with publish success visible:

```text
第 1 章 / 第一章 潮雾前夜 / 发布成功
第 2 章 / 第二章 镜中人来 / 发布成功
第 3 章 / 第三章 归潮尽头 / 发布成功
```

Chapter 1 and chapter 2 had no conflict-check record, so the UI correctly asked
for confirmation:

```text
当前章节还没有剧情设定冲突检查记录。可以继续发布，也可以先运行检查。
继续发布
```

After clicking `继续发布`, both published successfully.

### Workflow completed

The authoring workflow completed through the frontend:

- Created project `霭潮观澜录`.
- Created world bible content.
- Created world objects: characters, locations, organizations, and rules.
- Created story thread and three-chapter arc.
- Used AI generation/reference tools during drafting.
- Wrote three short-story chapters.
- Created a project map with `归潮塔群`, `琉璃湾`, and `雾市`.
- Verified map facts: `候选 0 / 事实 3 / 冲突 0`.
- Ran rule-based conflict check on chapter 3 and reduced it to 0 rule conflicts.
- Ran AI soft conflict review and handled its result.
- Published all three chapters with visible success states.

### Residual non-blocking observations

These did not block final completion, but remain worth future UX/design review:

- The same chapter appears under multiple Scene groups, which is conceptually
  confusing for a chapter-first author workflow.
- AI soft review surfaced a stale-looking Scene goal involving `林深`, while the
  authored short-story setup uses `沈澜`. The author could ignore it, but it
  suggests Scene blueprint/context cleanup may be needed in long-running
  projects.
- Chapter 1 and chapter 2 publish flow requires a confirmation when no conflict
  check exists. This is reasonable, but the wording could make the tradeoff more
  explicit for authors.
