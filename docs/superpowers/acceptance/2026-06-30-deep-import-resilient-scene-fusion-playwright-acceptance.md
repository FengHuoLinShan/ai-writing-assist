# 深度导入韧性 Scene 提取 — Playwright 用户场景与验收标准

## 1. 目标

基于 `docs/superpowers/specs/2026-06-30-deep-import-resilient-scene-fusion-design.md`，定义 Playwright 级别的端到端用户场景。本文关注用户能看到、能点击、能恢复、能整理的行为，不替代后端单元 / 集成测试。

Playwright 验收需要证明：

- 用户能启动新版深度导入，并看到 Phase 0 / Phase 1a / Phase 1b 的实时进度和质量统计。
- API 不稳定时，前端能正确显示阻断或降级，而不是只显示“完成”。
- 浏览器刷新、路由切换、页面关闭后能恢复进度展示。
- worker / backend 中断后，用户必须手动点击继续，且继续复用原 task。
- 用户放弃恢复前会看到破坏性清理警告。
- 导入后的 Scene / 世界对象管理界面能筛选 deprecated、needs_review、fallback、fusion 等结果。
- 用户可手动选择多个 Scene 做 LLM 融合，并在融合结果出来后选择保存策略。

## 2. 测试分层

| 层级 | 用途 | 是否真实 LLM |
|---|---|---|
| Playwright mock E2E | 验证 UI 路径、轮询、恢复、降级文案、筛选和手动融合交互 | 否 |
| Playwright worker E2E | 验证真实 async task 被 worker 领取，浏览器关闭后任务继续 | 默认否，可接 mock LLM |
| 手动 / nightly real LLM | 验证前 60 章真实导入质量、422 率、Scene 数和世界对象数 | 是 |

Playwright 主验收应以 mock 为主，避免把真实 LLM 质量波动误判为前端回归。真实 LLM 只作为单独、显式开启的验收路径。

## 3. 通用准备

### 3.1 推荐测试文件

新增：

- `frontend-console/e2e/deep-import-resilient.spec.js`
- 可选：`frontend-console/e2e/deep-import-resilient-worker.spec.js`

已有可复用文件：

- `frontend-console/e2e/deep-import.spec.js`
- `frontend-console/e2e/deep-import-worker.spec.js`
- `frontend-console/e2e/import-workflow-chaos.spec.js`
- `frontend-console/e2e/helpers/api-client.js`
- `frontend-console/e2e/helpers/workbench.js`

### 3.2 测试数据

默认使用 12-15 章轻量 fixture，不需要真实前 60 章：

- 章节 1-5：覆盖 Round A 第一个 batch。
- 章节 3-7：覆盖 Round B 第一个 batch。
- 章节 8-12：覆盖后续 batch。
- 至少构造一个跨 5/6 或 7/8 边界的 Scene，用于验证 Phase 1b fusion / split 提示。

真实 LLM 验收才使用：

- `/Users/tywww/Desktop/项目/wirting skill/诡秘之主_第一部 小丑_前60章.txt`
- 前 60 章。

### 3.3 Mock 策略

Playwright mock 用 `page.route()` 或 `context.route()` 控制：

- `POST /api/imports/deep`
- `GET /api/tasks/{task_id}`
- 恢复相关 API
- Scene / 世界对象列表 API
- 手动 Scene 融合 API

任务结果 mock 必须覆盖 `async_tasks.result` 中的新字段：

- `current_phase`
- `current_round`
- `current_chapter_range`
- `current_chapter`
- `current_scene_candidate_id`
- `current_window`
- `current_operation`
- `quality_stats`
- `interrupted`
- `recoverable`
- `recovery_required`
- `degraded`
- `degraded_reason`

## 4. Playwright 用户场景

### DI-PW-001 启动新版深度导入并显示 Phase 0 进度

**用户目标**：作者导入正文后启动深度导入，看到任务已经进入双轮预取，而不是无反馈等待。

**步骤**：

1. 创建测试项目并导入 12-15 章正文。
2. 进入写作台。
3. 点击“深度导入”。
4. 确认启动。
5. Mock `POST /api/imports/deep` 返回 `task_id` 和 `workflow_id`。
6. Mock `GET /api/tasks/{task_id}` 返回 running：
   - `current_phase=phase0_prefetch`
   - `current_round=A`
   - `current_chapter_range=1-5`
   - `current_operation=scene_prefetch`
   - `quality_stats.phase0.total_batches=6`
   - `quality_stats.phase0.completed_batches=2`
   - `quality_stats.phase0.success=2`
   - `quality_stats.phase0.final_422_rate=0`

**验收标准**：

- 页面显示主进度条。
- 进度条周围显示“Phase 0 / 预取 / Round A”语义。
- 页面显示当前章节范围 `1-5`。
- 页面显示请求数、成功数、422 率、timeout 数、schema 失败数。
- 进度提示有 alive 状态视觉效果，但不遮挡正文和按钮。
- `localStorage` 保存当前 `task_id`。

### DI-PW-002 Phase 0 final 422 超过 40% 时阻断

**用户目标**：API 通道不稳定时，系统明确阻断并给出可执行建议。

**步骤**：

1. 启动深度导入。
2. Mock task 返回 terminal failed 或 done-with-blocked 状态：
   - `current_phase=phase0_prefetch`
   - `quality_status=failed`
   - `blocked=true`
   - `block_reason=phase0_422_rate_exceeded`
   - `quality_stats.phase0.final_422_rate=0.5`
   - `quality_stats.phase0.total_batches=10`
   - `quality_stats.phase0.final_422_batches=5`
3. 等待前端轮询更新。

**验收标准**：

- UI 不显示“深度导入完成”。
- UI 明确显示 Phase 0 被阻断。
- UI 显示 `422` 率超过 `40%`。
- UI 显示推荐文案：“推荐使用官方 API 以保障稳定性与质量（强推 DeepSeek-v4-flash，质量高价格低并发超快！）”。
- 不出现 Scene 已导入成功、世界对象已生成等误导性文案。
- 用户可以关闭提示或重新发起导入，但不会自动继续 Phase 1a。

### DI-PW-003 Phase 1a final 422 超过 40% 时阻断

**用户目标**：补强阶段 API 不稳定时，系统阻断，避免污染正式 Scene。

**步骤**：

1. Mock Phase 0 已完成且未超阈值。
2. Mock task 更新到 Phase 1a：
   - `current_phase=phase1a_reinforce`
   - `current_round=B`
   - `current_chapter_range=8-12`
   - `quality_stats.phase1a.final_422_rate=0.45`
   - `blocked=true`
   - `block_reason=phase1a_422_rate_exceeded`

**验收标准**：

- UI 显示阻断发生在 Phase 1a，而不是 Phase 0。
- UI 显示当前 round、章节范围和失败统计。
- UI 显示 API 通道不稳定提示。
- 不显示 Phase 1b 自动整理或 Scene commit 已开始。

### DI-PW-004 Phase 1b 422 超过 40% 时降级继续

**用户目标**：自动整理失败时，系统继续使用 Phase 1a 质量补强结果，不让任务整体失败。

**步骤**：

1. Mock Phase 0 / Phase 1a 成功。
2. Mock Phase 1b task result：
   - `current_phase=phase1b_fusion`
   - `quality_stats.phase1b.final_422_rate=0.5`
   - `degraded=true`
   - `degraded_reason=phase1b_422_rate_exceeded`
   - `phase1a_fallback=true`
3. Mock 后续 result 进入 Scene commit / Phase 2。

**验收标准**：

- UI 显示“自动整理失败，已使用质量补强结果继续导入”。
- UI 显示 `phase1a_fallback` 或等价用户文案。
- 主进度继续推进到 Scene commit / Phase 2。
- 最终完成时质量状态显示为“部分降级完成”或等价文案，而不是纯成功。

### DI-PW-005 Phase 1b 局部失败只回退失败 Scene

**用户目标**：少数 Scene 整理失败时，不整批回退。

**步骤**：

1. Mock Phase 1b window 结果：
   - `total_windows=2`
   - `successful_windows=2`
   - `degraded_windows=1`
   - `fallback_scene_count=2`
   - `fused_scene_count=18`
   - `needs_review_scene_count=3`
2. Mock final Scene 列表 API 返回：
   - 多个 `phase=phase1b_fusion` Scene。
   - 两个 `phase=phase1a_fallback` Scene。
   - 三个 `needs_review=true` Scene。

**验收标准**：

- 进度区显示局部 fallback 数量。
- Scene 管理界面能同时看到 fusion Scene 和 fallback Scene。
- fallback Scene 不被隐藏，也不被标记为失败。
- `needs_review` 数量与进度区统计一致。

### DI-PW-006 刷新 / 路由切走后恢复进度展示

**用户目标**：浏览器刷新、切走页面、再回来时仍能看到正在跑的深度导入。

**步骤**：

1. Mock 一个 running task。
2. 在 `localStorage` 写入 `novel_deepImportTaskId`。
3. 进入写作台，断言进度条恢复。
4. 切到项目页或世界对象页。
5. 再切回写作台。
6. 刷新页面。

**验收标准**：

- 每次回到写作台都调用 `GET /api/tasks/{task_id}`。
- 进度条恢复 current phase、章节范围、质量统计。
- 不重复提交 `POST /api/imports/deep`。
- localStorage task_id 未被错误清除。

### DI-PW-007 worker / backend 中断后提示用户手动继续

**用户目标**：后台中断后，系统提示可恢复，但不擅自继续。

**步骤**：

1. Mock task 查询返回：
   - `status=running`
   - `result.interrupted=true`
   - `result.recoverable=true`
   - `result.recovery_required=true`
   - `result.interrupted_at`
   - `result.last_heartbeat_at`
   - checkpoint 摘要。
2. 打开写作台。

**验收标准**：

- UI 显示“检测到上次深度导入中断，可从当前阶段继续”。
- UI 展示 checkpoint 摘要：
  - 中断阶段。
  - 已完成章节 / 窗口 / Scene。
  - 已写入 Scene 数。
  - 已抽取世界对象数。
  - 将重跑的最小范围。
  - deprecated / conflict / needs_review 资产提示。
- UI 提供“继续”和“放弃恢复”两个明确操作。
- 在用户点击“继续”前，不调用恢复 API，不把 task 改回 pending。

### DI-PW-008 用户点击继续后复用原 task

**用户目标**：继续恢复不会创建新 task，进度与 provenance 稳定。

**步骤**：

1. 从 DI-PW-007 的恢复提示开始。
2. 点击“继续”。
3. Mock 恢复 API 返回：
   - same `task_id`
   - same `workflow_id`
   - `status=pending` 或 running。
4. 后续 `GET /api/tasks/{task_id}` 返回继续后的进度。

**验收标准**：

- 请求体或 URL 指向原 task。
- UI 没有生成或保存新的 task_id。
- localStorage 中的 task_id 保持不变。
- 进度条继续显示原 checkpoint 后的最小重跑范围。
- 不显示重复导入确认弹窗。

### DI-PW-009 用户放弃恢复前必须二次确认

**用户目标**：放弃恢复会清理派生资产，必须被明确警告。

**步骤**：

1. 进入可恢复任务提示。
2. 点击“放弃恢复”。
3. Mock 弹出确认对话框。
4. 先点击取消。
5. 再次点击“放弃恢复”，确认。
6. Mock 放弃 API 返回：
   - `task.status=cancelled`
   - `deprecated_scene_count`
   - `deprecated_entity_count`
   - `hard_deleted_intermediate_count`

**验收标准**：

- 第一次点击只打开警告，不立即调用清理 API。
- 警告文案明确说明会清理本次 workflow 已写入的派生 Scene / 自动实体 / 关系 / delta / 结构结果。
- 点击取消后，任务仍显示可恢复。
- 确认后才调用放弃 API。
- UI 显示原 task 已取消。
- UI 显示清理结果摘要。

### DI-PW-010 Scene 管理界面按导入标记筛选

**用户目标**：作者能快速整理导入后的 Scene，尤其是 fallback、needs_review、deprecated。

**步骤**：

1. Mock Scene 列表 API 返回多类 Scene：
   - `phase=phase1b_fusion`
   - `phase=phase1a_fallback`
   - `needs_review=true`
   - `boundary_status=uncertain`
   - `status=deprecated`
   - `recovery_conflict=true`
2. 打开 Scene 管理 / Scene 工作台。
3. 依次选择筛选：
   - needs_review
   - boundary uncertain
   - phase1a_fallback
   - phase1b_fusion
   - deprecated
   - recovery_conflict

**验收标准**：

- 每次筛选都会向后端 API 发送对应查询参数。
- 列表只显示匹配项。
- 筛选状态在 UI 中可见。
- 筛选只改变视图，不自动修改 Scene status。
- 大数据量模式下使用分页参数，不依赖全量拉取后本地筛选。

### DI-PW-011 世界对象管理界面按导入标记筛选

**用户目标**：作者能快速整理深度导入产生的世界对象和关系。

**步骤**：

1. Mock 世界对象列表 API 返回：
   - `source=deep_import`
   - `workflow_id`
   - `auto_ingested=true`
   - `needs_review=true`
   - `status=deprecated`
   - 多种 `entity_type`
2. 打开世界对象管理界面。
3. 选择筛选：
   - source=deep_import
   - auto_ingested
   - workflow_id
   - needs_review
   - entity_type
   - deprecated

**验收标准**：

- 世界对象页停留在世界对象管理视图，不被强制跳转到地图。
- 请求参数包含筛选条件和分页。
- 列表显示对象名称、类型、状态、来源、复核标记。
- deprecated 对象可被定位，但不会被自动恢复或删除。

### DI-PW-012 手动 Scene 融合：保留原 Scene 并保存融合 Scene

**用户目标**：作者选择多个 Scene，让 LLM 生成融合 Scene，同时保留原 Scene。

**步骤**：

1. 打开 Scene 管理界面。
2. 选择两个或多个 Scene。
3. 点击“融合”。
4. Mock LLM 融合 API 返回融合草稿：
   - title
   - source_scene_ids
   - chapter_ids
   - scene_chunks
   - editable fields
5. 选择“保留原 Scene + 保存融合 Scene”。

**验收标准**：

- 融合按钮只在选择多个 Scene 后可用。
- 融合结果展示可编辑字段，不只是摘要。
- 保存请求创建新的 `draft Scene`。
- 原 Scene status 不变。
- 新 Scene 记录 source Scene 依赖。

### DI-PW-013 手动 Scene 融合：保存融合 Scene 并 deprecated 原 Scene

**用户目标**：作者确认融合结果后，可以显式废弃原 Scene。

**步骤**：

1. 从融合结果预览开始。
2. 选择“保存融合 Scene，并将原 Scene 标记为 deprecated”。
3. Mock 保存 API 返回新 Scene 和原 Scene 状态更新。

**验收标准**：

- 操作前有明确文案说明原 Scene 会被标记 deprecated。
- 用户确认后才更新原 Scene。
- 新 Scene 为 draft。
- 原 Scene 变为 deprecated。
- deprecated Scene 可通过筛选找回。

### DI-PW-014 手动 Scene 融合：放弃或继续编辑

**用户目标**：作者可以放弃不满意的融合结果，或编辑后再保存。

**步骤**：

1. 打开融合结果预览。
2. 点击“放弃融合结果”。
3. 再次执行融合，修改标题 / 目标 / 冲突等字段。
4. 点击“继续编辑结果后保存”或等价保存操作。

**验收标准**：

- 放弃融合结果不会创建新 Scene。
- 放弃不会修改原 Scene。
- 编辑后保存使用用户修改后的字段。
- scene_chunks 和章节来源仍被保留。

### DI-PW-015 移动端进度和筛选不重叠

**用户目标**：小屏下仍能看清深度导入进度和整理筛选。

**步骤**：

1. 设置 viewport 宽度 `390px`。
2. 打开写作台并 mock running task。
3. 检查进度条、当前章节、当前 Scene / window、质量统计。
4. 打开 Scene 管理筛选区。

**验收标准**：

- 文本不溢出按钮或容器。
- 进度条、光效、提示文字不互相遮挡。
- 当前章节范围和质量统计可读。
- 筛选控件可滚动或折叠，不遮挡列表主内容。

### DI-PW-016 深度导入完成后生成剧情线 / 篇章纲 / 伏笔 / 揭示

**用户目标**：作者完成深度导入后，能在大纲模块看到 Phase 3 生成的结构资产，而不是只得到 Scene 和世界对象。

**步骤**：

1. Mock 深度导入 task 最终完成：
   - `status=done`
   - `result.phase=done`
   - `completed_steps` 包含 `scene_segmentation`、`entity_extraction`、`structure_analysis`
   - `result.phase3.total_threads=2`
   - `result.phase3.total_arcs=1`
   - `result.phase3.total_foreshadowing_plans=2`
   - `result.phase3.total_reveal_plans=1`
   - `result.phase3.quality_status=complete`
2. Mock outline 相关 API 返回同 workflow 生成的结构资产：
   - `plot_threads` 包含主线 / 隐藏线。
   - `outline_arcs` 包含章节范围。
   - `foreshadowing_plans` 包含目标章节和状态。
   - `reveal_plans` 包含揭示章节和关联伏笔。
   - 每个对象带 `source=deep_import`、`workflow_id`、`auto_ingested=true` 或等价 meta。
3. 从写作台深度导入完成提示进入大纲模块。
4. 依次打开剧情线、篇章纲、伏笔、揭示子标签。

**验收标准**：

- 深度导入完成提示显示 Phase 3 结构分析已完成。
- 剧情线列表显示生成的主线 / 隐藏线名称、类型、状态和来源。
- 篇章纲列表显示标题、起止章节、状态和来源。
- 伏笔列表显示描述、目标章节、状态和来源。
- 揭示列表显示目标 / 描述、揭示章节、状态和来源。
- 四类结构资产均属于当前 novel_id；切换到另一个项目后不可见。
- 刷新页面后四类结构资产仍可见。
- 若 Phase 1b 降级但 Phase 3 完成，结构资产仍显示，同时保留“基于降级 Scene 分析，需复核”或等价提示。

### DI-PW-017 Phase 3 失败或降级时，大纲模块显示部分完成

**用户目标**：结构分析失败或部分失败时，用户能知道 Scene / 世界对象已导入，但剧情线等结构资产不完整。

**步骤**：

1. Mock 深度导入 task 完成但结构分析部分失败：
   - `status=done`
   - `result.quality_status=partial`
   - `result.degraded=true`
   - `result.phase_errors.structure_analysis` 包含错误原因。
   - `result.phase3.total_threads=0`
   - `result.phase3.total_arcs=0`
   - `result.phase3.total_foreshadowing_plans=1`
   - `result.phase3.total_reveal_plans=0`
2. 进入写作台查看完成提示。
3. 进入大纲模块查看四个子标签。

**验收标准**：

- 写作台不显示纯成功，而显示“部分完成”或等价质量提示。
- 大纲模块显示结构分析不完整提示。
- 已生成的伏笔可见。
- 未生成的剧情线 / 篇章纲 / 揭示显示空态和“可重新分析 / 重新生成”入口。
- 不阻塞用户查看已生成 Scene 和世界对象。

### DI-PW-018 结构资产按 deep_import 来源和 workflow 筛选

**用户目标**：作者能在大纲模块快速定位本次深度导入生成的剧情线、篇章纲、伏笔和揭示。

**步骤**：

1. Mock 大纲模块中存在两组资产：
   - 本次 deep_import workflow 生成的 draft / candidate 结构资产。
   - 用户手动创建或其他 workflow 生成的结构资产。
2. 打开大纲模块任一结构子标签。
3. 使用筛选：
   - source=deep_import
   - workflow_id
   - needs_review
   - deprecated
   - candidate / draft
4. 切换剧情线、篇章纲、伏笔、揭示子标签，保持或重新应用筛选。

**验收标准**：

- 请求后端 API 时带 source / workflow_id / status / needs_review 等查询参数。
- 列表只展示匹配当前 workflow 的结构资产。
- 用户手动资产不会被混入本次 deep_import 筛选结果。
- 筛选只改变视图，不自动 promote、deprecated 或删除结构资产。
- 若用户选择批量 deprecated，必须出现二次确认。

### DI-PW-019 放弃恢复时结构资产清理语义正确

**用户目标**：中断任务被放弃时，同 workflow 的自动结构资产被 deprecated，但用户编辑或 canonical 资产不被误伤。

**步骤**：

1. Mock 可恢复深度导入任务。
2. Mock 该 workflow 已写入：
   - 自动 `plot_threads`。
   - 自动 `outline_arcs`。
   - 自动 `foreshadowing_plans`。
   - 自动 `reveal_plans`。
   - 一个用户手动编辑过的剧情线。
   - 一个 canonical 篇章纲。
3. 用户点击“放弃恢复”并确认。
4. Mock 清理 API 返回：
   - `deprecated_plot_threads`
   - `deprecated_outline_arcs`
   - `deprecated_foreshadowing_plans`
   - `deprecated_reveal_plans`
   - `skipped_user_edited_count`
   - `skipped_canonical_count`

**验收标准**：

- 清理结果摘要明确列出四类结构资产 deprecated 数量。
- 用户编辑过的剧情线仍保持原状态。
- canonical 篇章纲仍保持原状态。
- 大纲模块 deprecated 筛选能看到被清理的自动结构资产。
- 默认列表不再混入这些 deprecated 资产，除非用户主动筛选 deprecated。

## 5. 真实 LLM 验收场景

### DI-REAL-001 前 60 章深度导入质量验收

**运行条件**：

- 显式开启真实 LLM，例如 `RUN_DEEP_IMPORT_60_REAL_LLM=1`。
- 使用官方 API 或稳定等价 API。
- 使用 `/Users/tywww/Desktop/项目/wirting skill/诡秘之主_第一部 小丑_前60章.txt`。
- 超时时间按长任务设置，不纳入普通 CI。

**验收标准**：

- 成功解析 60 章。
- Phase 0 生成两轮错位 batch。
- Phase 0 / Phase 1a / Phase 1b 分别记录 422、timeout、schema 失败统计。
- 若 Phase 0 或 Phase 1a final 422 率超过 40%，任务阻断并展示官方 API 推荐文案。
- 若 Phase 1b final 422 率超过 40%，任务降级但继续写 Scene。
- 最终 Scene 数大于 0。
- 世界对象数大于 0。
- 剧情线、篇章纲、伏笔、揭示中至少一类结构资产大于 0；理想情况下四类均有输出。
- 若任一结构资产类型为 0，任务必须在 result 中记录 Phase 3 质量状态、原因和可重新分析入口所需信息。
- needs_review Scene 可在管理界面筛选出来。
- 任务 result 保留 workflow_id、quality_stats 和 provenance 诊断。

真实 LLM 验收不要求固定 Scene 数或固定实体数；它要求质量统计、降级语义、可追溯性和可整理性正确。

## 6. 全局验收标准

- 所有用户可见失败状态都有明确中文文案，不只显示 raw JSON 或 `failed`。
- `422` 阈值语义正确：
  - Phase 0 > 40%：阻断。
  - Phase 1a > 40%：阻断。
  - Phase 1b > 40%：降级继续。
- 刷新 / 路由切换恢复只依赖原 task_id，不重复创建任务。
- worker 中断恢复必须用户确认，不自动继续。
- 放弃恢复必须二次确认，且默认 deprecated 已暴露资产。
- Scene commit 幂等结果能在 UI 层体现为“不重复写入 / 不重复显示”。
- 手动融合不静默覆盖原 Scene。
- 筛选只改变视图，不隐式修改资产状态。
- 深度导入 Phase 3 生成的剧情线、篇章纲、伏笔、揭示能在大纲模块看到，并能按 source / workflow / status / needs_review 筛选。
- 小屏宽度下关键文案和操作不重叠。

## 7. 建议执行命令

Mock E2E：

```bash
cd frontend-console && npx playwright test deep-import-resilient.spec.js --reporter=list
```

Worker E2E：

```bash
cd frontend-console && RUN_WORKER_E2E=1 npx playwright test deep-import-resilient-worker.spec.js --reporter=list
```

真实 LLM 验收：

```bash
cd backend && RUN_DEEP_IMPORT_60_REAL_LLM=1 pytest modules/imports/tests/test_deep_import_real_llm.py -q
```
