# Smart Dedup Frontend QA Report

Date: 2026-07-05

Project under test:

- Title: `霭潮观澜录`
- Project id: `a389bffb-b39f-4302-b3a3-7229c2b0742e`
- Entry URL: `http://localhost:8080/#workbench/a389bffb-b39f-4302-b3a3-7229c2b0742e/writing`

Method:

- Use the app as an author from the frontend.
- Trigger `智能去重` from visible UI only.
- Record UI, functional, and usability issues.
- If a frontend blocker prevents continuing the workflow, hand this report to a
  repair subagent, wait for completion, then continue browser verification.

Expected workflow:

1. Author has existing project assets.
2. Author clicks `智能去重`.
3. Scan task starts and exposes progress.
4. Scan completes and shows either:
   - no duplicate suggestions, or
   - actionable suggestions with evidence, action choice, and safe apply flow.
5. Applying suggestions gives a clear success/failure state and updates the
   affected project assets without data loss.

## Initial Scan - Existing Published Project

Timestamp: 2026-07-05 18:35 CST.

Reproduction:

1. Open writing page for project `霭潮观澜录`.
2. Click top-level `智能去重`.

Observed:

- The task submits and completes quickly.
- The global action changes from `智能去重` to `查看去重建议`.
- A visible toast appears:

```text
智能去重扫描完成
```

- The result modal shows:

```text
智能去重
没有发现可处理的重复资产。
```

Result:

- Empty-result path works.
- Next step: create an intentional duplicate world object from frontend and
  verify non-empty suggestion/apply path.

## Issue 1 - Similar-object create interception shows raw object and no force-create path

Timestamp: 2026-07-05 18:43 CST.

Reproduction:

1. Open `世界对象`.
2. Click `新建对象`.
3. Create a character named `沈澜` with a summary closely matching the existing
   `沈澜` object.
4. Click `创建`.

Expected:

- The UI should show the existing similar entity with readable name/type/score.
- The author should be able to cancel or explicitly `强制创建`, as the frontend
  code path suggests.

Actual:

- No confirmation dialog appears.
- A toast shows:

```text
创建失败：请求失败 (409)：requires_confirmation: true；similar_entities: [object Object]
```

Impact:

- The author cannot understand which existing object blocked creation.
- The intended force-create flow is unreachable from this failure shape.
- This also blocks generating a controlled duplicate asset for smart-dedup
  workflow testing through normal frontend use.

Suggested investigation:

- Check `api.world.createEntity` / request error normalization for structured
  409 details.
- Ensure `err.details.similar_entities` or equivalent is preserved in a shape
  that `worldView._showCreateForm()` can render.
- Add frontend coverage:
  duplicate create 409 -> readable confirmation -> `强制创建` sends
  `force_create: true`.

## Issue 2 - Empty smart-dedup result gets stuck and cannot rescan after assets change

Timestamp: 2026-07-05 18:47 CST.

Setup:

- Initial smart-dedup scan returned no suggestions.
- A new semantically duplicate world object was then created from the frontend:

```text
北港镜修师
女，28岁。镜局执业修复师，擅长灵镜校准。调查北港失踪案，寻找八年前失踪父亲与归一潮真相。与柳烨旧识，与许筠有师门情分。
```

This object intentionally overlaps with existing `沈澜`.

Reproduction:

1. After the initial no-suggestion scan, create `北港镜修师`.
2. Observe top-level smart-dedup button remains:

```text
查看去重建议
data-action="show-smart-dedup-progress"
```

3. Click it.

Expected:

- The author can start a fresh scan after project assets change, or the result
  modal offers a clear `重新扫描` action.

Actual:

- It shows the old empty result:

```text
智能去重
没有发现可处理的重复资产。
```

- No rescan action is visible.

Impact:

- The author cannot verify or use smart dedup on newly-created duplicates after
  an empty scan.
- This blocks the non-empty suggestion/apply path in a normal frontend session.

Suggested investigation:

- Reset `_smartDedupProgress` after showing an empty result, or add a
  `重新扫描` action to the no-suggestion modal.
- Ensure the global button returns to `智能去重` when the previous result has no
  suggestions, or when project assets change.
- Add frontend coverage:
  empty scan -> create object -> rescan available -> new task starts.

## Issue 3 - Smart-dedup scan with duplicate present hangs the browser interaction path

Timestamp: 2026-07-05 18:52 CST.

Setup:

- Project contains both:
  - `沈澜`
  - `北港镜修师`
- Both are `character` world objects.
- Their summaries substantially overlap.
- Page reload restored the top-level button from `查看去重建议` to
  `智能去重`.

Reproduction:

1. Open `世界对象`.
2. Confirm both `沈澜` and `北港镜修师` are visible.
3. Click `智能去重`.
4. Wait for scan result.

Expected:

- The scan completes with a non-empty suggestion modal, or a bounded failure
  message.
- The page remains responsive.

Actual:

- The scan did not return usable UI within 40 seconds.
- After that, browser automation could not even read visible DOM or page text
  within 20-30 seconds.
- This suggests the frontend page or browser interaction path is hanging after
  the non-empty smart-dedup scan attempt.

Impact:

- This blocks verification of the core smart-dedup path:
  non-empty suggestions -> choose action -> apply.
- The author cannot continue using the page without recovering/reloading.

Suggested investigation:

- Inspect task polling for `smart_dedup_scan` with duplicate suggestions.
- Check whether rendering the suggestion modal creates excessive DOM, infinite
  loops, or repeated modal/poller updates.
- Check whether result normalization can produce malformed suggestions that
  make `_renderSmartDedupSuggestion()` or `_smartDedupDraftFor()` loop or throw.
- Add an E2E/browser regression with at least one duplicate world object:
  scan -> suggestion modal visible -> page remains interactive.

## Current blocker handoff status

At this point the frontend workflow is blocked before the apply stage. The
repair agent should address at least:

1. Duplicate-create 409 details and force-create confirmation.
2. Empty-result rescan affordance.
3. Non-empty smart-dedup scan hang / suggestion modal rendering path.

## Repair Pass 1 Summary

Timestamp: 2026-07-05 19:08 CST.

Repair worker: `019f31e2-5fdb-7392-a7da-ea6fc319687a`.

Reported fixes:

- Preserved structured API error details for failed requests so duplicate-create
  409 responses no longer collapse to `[object Object]`.
- Rendered duplicate-create confirmation with readable similar entity
  name/type/score and working `强制创建`.
- Empty smart-dedup results reset the global action back to `智能去重` and expose
  `重新扫描`.
- Added same-type summary-overlap recall for world entities, producing a stable
  `summary_overlap` suggestion for `沈澜` + `北港镜修师`.
- Avoided slow RAG/BGE evidence retrieval for `summary_overlap`.

Reported verification:

- `frontend-console && npm test`: 546 passed.
- `frontend-console && npm run test:e2e -- e2e/smart-dedup.spec.js`: 2 passed.
- Backend project/world dedup targeted suite: 67 passed, 47 deselected.
- `backend && python -m pytest modules/world/tests/test_entity_fusion.py -q`:
  7 passed.
- `backend && ruff check .`: passed.
- `git diff --check`: passed.

Repair worker browser result:

- Real UI scan showed `智能去重建议` with one readable suggestion:
  `沈澜 -> 北港镜修师`, action `登记别名`, confidence `0.92`, method
  `summary_overlap`.
- Applied the suggestion successfully.
- API verified `北港镜修师.content_json.aliases` contains
  `{"alias": "沈澜", "type": "alias"}`.

## Main-thread Verification After Repair Pass 1

Timestamp: 2026-07-05 19:20 CST.

Verified from frontend:

- Exact duplicate creation now shows a readable confirmation instead of
  `[object Object]`:

```text
发现相似对象：许筠 / character / 相似度 1。是否仍要创建？
```

- `强制创建` works; the project can contain two visible `许筠` world objects
  for controlled dedup testing.
- Smart-dedup scan then opens a non-empty modal:

```text
智能去重建议
扫描 20 个资产，发现 2 条建议
世界对象 · 合并：许筠 → 许筠
置信度 1 · exact_name
世界对象 · 合并：沈澜 → 北港镜修师
置信度 0.99 · alias_name_match
```

- The risky `沈澜 → 北港镜修师` suggestion was manually unchecked.
- Applying only the exact `许筠 → 许筠` suggestion succeeded at the data/UI
  state level:
  - one `许筠` remains `正史`
  - the duplicate `许筠` becomes `已合并`

Residual observation:

- No persistent success toast was captured after apply. The visible entity
  state did update, so this is a feedback/usability gap rather than a data
  blocker.

## Issue 4 - Applying one suggestion then rescanning can hang the browser

Timestamp: 2026-07-05 19:27 CST.

Setup:

- The exact duplicate `许筠 → 许筠` suggestion had just been applied.
- The page still had a remaining risky suggestion involving:
  - `沈澜`
  - `北港镜修师`

Reproduction:

1. Apply only the exact duplicate suggestion.
2. Close/continue from the result state.
3. Trigger smart-dedup again to verify the post-apply state.

Expected:

- A fresh scan completes, excludes already-merged assets, and shows only the
  remaining valid suggestions.
- The page stays responsive.
- Risky alias-derived suggestions should not be selected by default.

Actual:

- Browser interaction timed out after the rescan.
- Page text and DOM reads also timed out during recovery attempts.

Impact:

- This blocks the final author workflow after one successful apply.
- It prevents safe iterative cleanup of multiple duplicate groups.

Suggested investigation:

- Ensure smart-dedup apply success clears active task/poller/progress state.
- Ensure the next scan does not capture stale modal checkbox state.
- Exclude or down-rank merged/candidate-derived alias suggestions where source
  and target stability make automatic application risky.

## Repair Pass 2 Summary

Timestamp: 2026-07-05 19:48 CST.

Repair worker: `019f31fd-008e-7313-89d5-c713cf112dbc`.

Reported root cause:

- Before rendering a new scan result, the frontend captured checkbox draft state
  from the old modal DOM.
- That polluted the next scan's suggestion index state.
- Apply success also did not consistently clear poller/task/progress and active
  workflow state.

Reported fixes:

- Reset smart-dedup result state before a new scan.
- Stopped stale modal checkbox draft from leaking into a later scan.
- Cleaned up active workflow/poller/progress/localStorage state after apply.
- Marked alias-derived uncertain suggestions as high risk and requiring manual
  confirmation.
- High-risk suggestions are no longer selected by default.

Reported verification:

- `frontend-console && npm test -- appSmartDedup.test.js`: 11 passed.
- `frontend-console && npm run test:e2e -- smart-dedup.spec.js`: 3 passed.
- `frontend-console && npm test`: 549 passed.
- `backend && python -m pytest modules/project/tests/test_smart_dedup.py -q`:
  4 passed.
- `backend && python -m pytest modules/world/tests/test_entity_fusion.py -q`:
  7 passed.
- Backend dedup test set: 51 passed.
- `backend && ruff check .`: passed.
- `git diff --check`: passed.

## Final Browser Verification

Timestamp: 2026-07-05 20:02 CST.

Verified from frontend after Repair Pass 2:

1. Opened the project world page.
2. Clicked `智能去重`.
3. Waited for scan completion.
4. Opened `查看去重建议`.

Observed:

- The page did not hang.
- The smart-dedup action remained clickable and the modal opened normally.
- The modal shows one remaining suggestion:

```text
智能去重建议
扫描 19 个资产， 发现 1 条建议。
世界对象 · 合并：沈澜 → 北港镜修师
置信度 0.99 · alias_name_match
别名命中且来源仍是候选/草稿，建议合并到更稳定对象。
高风险别名命中：默认不选中。确认这确实是同一对象后再手动勾选应用。
```

- The suggestion checkbox exists and is unchecked by default.

Final status:

- Empty-result path: pass.
- Duplicate-create confirmation and force-create path: pass.
- Non-empty suggestion rendering: pass.
- Selective apply of exact duplicate: pass.
- Apply-then-rescan path: pass.
- High-risk alias suggestion default safety: pass.

Remaining non-blocking notes:

- The synthetic QA object `北港镜修师` can still make the remaining
  `沈澜 → 北港镜修师` suggestion look semantically suspicious. The UI now treats
  it as high risk and leaves it unchecked, which is the correct safe behavior.
- Apply success feedback could still be made more explicit if authors need a
  persistent confirmation message after batch operations.
