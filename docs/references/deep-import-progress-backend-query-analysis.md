# 深度导入进度条 — 后端查询逻辑分析（代码核实版）

> 基于 4 个并行 agent 对全量源代码的逐行读取与分析，后经人工对照源文件逐条核实。
> 核实时间: 2026-07-12

---

## 1. 整体数据流

```
用户点击"场景（scene）自动提取"
  ↓ autoExtraction.js: POST /api/imports/stages/scenes { novel_id, start_chapter, end_chapter, ... }
  ↓ Backend orchestrator 创建 scene_auto_extraction AsyncTask (progress=0.0)
  ↓ deepImportRecovery.js: startPolling()
  ↓ 每 3s GET /api/tasks/{task_id}?novel_id=...&_ts=...
  ↓ normalizeTaskProgress() 标准化
  ↓ progressRenderer.js 渲染 HTML → innerHTML 注入容器
  ↓ 直到 status==done/failed/cancelled 停止轮询
```

**代码路径**:
- `backend/infrastructure/tasks/api.py:151-198` — GET 端点
- `backend/modules/imports/orchestrator.py:217-226` — `_record_progress` 回调
- `frontend-console/views/writing/deepImportRecovery.js:418-525` — 自建轮询
- `frontend-console/shared/workflowProgress.js:375-473` — 通用轮询工具

---

## 2. 后端 API 响应形状

### `GET /api/tasks/{task_id}?novel_id=...&_ts=...`

**源文件**: `backend/infrastructure/tasks/api.py:65-83` (`TaskStatusResponse`)

```python
{
  "task_id": str,                    # UUID
  "task_type": str,                  # "deep_import"
  "status": str,                     # "pending"|"running"|"done"|"failed"|"cancelled"
  "progress": float|null,            # ← 直接读 AsyncTask.progress ORM 列
  "meta": dict,                      # 输入参数
  "result": dict,                    # ← 含 DeepImportProgress 全部 40+ 字段
  "error_message": str|null,
  "created_at"/"started_at"/"finished_at"/"heartbeat_at": str|null,
  "attempt": int, "max_attempts": int,
  "stale": bool,                     # running + 心跳过期=true
  "lifecycle": {                     # 由 lifecycle_contract() 实时计算
    "reason": str|null,
    "recovery_policy": str,
    "recovery_required": bool,
    "stale_detected_at": str|null
  },
  "available_actions": [str]         # 按状态+恢复策略
}
```

**核实要点**:

| 断言 | 代码证据 | 结论 |
|------|---------|------|
| `progress` 直接从 ORM 列读取，非计算值 | `api.py:180` → `progress=task.progress`; `models.py:40-44` → `progress: mapped_column(Float, default=0.0)` | ✅ 正确 |
| `result` 是整个 DeepImportProgress 的 JSON dump | `orchestrator.py:222` → `task.result = updated.model_dump(mode="json")` | ✅ 正确 |
| novle_id 隔离 | `api.py:162-164` → WHERE + `meta["novel_id"]` 过滤 | ✅ 正确 |
| heartbeat 在 `lifecycle_contract()` 中实时计算 | `api.py:172-175` → 每次 GET 调用 `lifecycle_contract()` | ✅ 正确 |
| 404 时返回 `{detail: "Task not found"}` | `api.py:169-170` | ✅ 正确 |

---

## 3. progress 字段来源与更新途径

### 3.1 初始值

**源文件**: `backend/infrastructure/tasks/api.py:137`

```python
task = AsyncTask(..., progress=0.0, ...)
```

创建时设为 0.0。

### 3.2 运行中更新

**源文件**: `backend/infrastructure/tasks/models.py:150-153`

```python
def update_progress(self, progress: float) -> None:
    self.progress = progress
    self.heartbeat_at = datetime.now(UTC)
```

由任务处理器在 `emit_progress()` 时调用，每次赋一个 0.0-1.0 的值。**每次都完整替换，不是增量累加**。

**调用点**: `orchestrator.py:223` — `task.update_progress(progress_value)`

### 3.3 完成时强制设为 1.0

**源文件**: `backend/infrastructure/tasks/models.py:124-131`

```python
def mark_done(self, result_data=None):
    self.progress = 1.0  # 强制
```

### 3.4 Backend 实际使用的 progress 值

从 `workflow_scene_phase.py` 和 `workflow_entity_phase.py` 中提取的 `on_progress` 实参：

| 阶段 | 起始值 | 结束值 | 步进方式 | 代码位置 |
|------|--------|--------|---------|---------|
| Phase 0: 规划 | 0.0 | 0.0（失败保留） | 固定步进 | `workflow_scene_phase.py` |
| Phase 1a: Scene 切分 | 0.1 | 0.2 | 按 batch 百分比 | `0.1 + 0.1 * completed/total` |
| Phase 1b: Scene 补全 | 0.2 | 0.3 | 按 batch 百分比 | `0.2 + 0.1 * completed/total` |
| Scene commit | 0.3 | 0.3（失败保留） | 固定步进 | `workflow_scene_phase.py` |
| Phase 2: 实体抽取 | 0.4 | 0.8 | 按 scene 百分比 | `workflow_entity_phase.py` |
| Phase 3: 结构分析 | 0.8 | 1.0（仅成功终态） | 不确定条 | `workflow_structure_phase.py` |

> **注意**: 每次 `emit_progress` 都会写入任务并提交，因此中间值会被前端查询到。运行中持久化边界会保证进度单调；失败不再写入 `1.0`。

`scene_auto_extraction` 是例外：orchestrator 在持久化前将上述 Scene
内部区间转换为独立 stage 的耗时预测进度。Phase 0 保持 `0`
且前端显示不确定条；Phase 1a 映射到 `0–59%`，Phase 1b 映射到
`59–99%`，Scene commit 为 `99%`，成功终态为 `100%`。权重来自
当前 pipeline 最近两次 1–60 章运行的约 `58.3% / 41.5% / 0.25%`
耗时比例，取便于展示的 `59% / 40% / 1%`。

---

## 4. DeepImportProgress Schema（40+ 字段）

**源文件**: `backend/modules/imports/workflow_schemas.py:25-189`

### 4.1 生命周期字段

| 字段 | 类型 | 默认值 | 用途 |
|------|------|--------|------|
| `workflow_id` | str\|None | None | 与 task.id 一致 |
| `workflow_type` | str | "deep_import" | 流水线类型 |
| `stage` | str\|None | None | 分阶段标识 |
| `phase` | str | "pending" | 顶层状态 |
| `quality_status` | str | "pending" | pending/complete/partial/failed |
| `current_step` | DeepImportStep\|None | None | 当前步骤枚举 |
| `completed_steps` | list[str] | [] | 已完成步骤列表 |

### 4.2 进度定位字段（用于前端实时展示）

| 字段 | 类型 | 默认值 | 用途 |
|------|------|--------|------|
| `current_phase` | str\|None | None | Phase 0/1a/1b/entity_extraction 等 |
| `current_round` | str\|None | None | 当前处理轮次 |
| `current_chapter_range` | str\|None | None | "1-5" |
| `current_chapter` | int\|None | None | 当前章节编号 |
| `current_scene_candidate_id` | str\|None | None | 最近完成的 scene |
| `current_window` | str\|None | None | 处理窗口 ID |
| `current_operation` | str\|None | None | 具体操作名称 |
| `current_item` | dict | {} | 当前对象摘要 |
| `phase1_total_batches` / `phase1_completed_batches` | int | 0 | Phase 1 批次进度 |
| `phase2_total_scenes` / `phase2_completed_scenes` | int | 0 | Phase 2 scene 进度 |

### 4.3 诊断字段（用于进度条详细视图）

| 字段 | 上限 | 用途 |
|------|------|------|
| `phase_timeline` | 120 条 | 阶段开始/结束/耗时/状态 |
| `progress_events` | 200 条 | 服务级事件流 |
| `acceptance_checks` | 200 条 | 门禁检查结果 |
| `phase_errors` | 120 条 | 可机器读取的失败/降级原因 |
| `diagnostic_counts` | — | 累计计数摘要 |
| `quality_stats` | — | 各阶段质量统计 |
| `phase_artifacts` | — | 阶段产物摘要 |
| `checkpoints` | — | 可恢复检查点 |

**上限控制**: `service_progress_limits.py:14-31` → `trim_progress_diagnostics()`，在每次 `emit_progress()` 和 `_result_from_progress()` 时调用。

### 4.4 恢复与降级字段

| 字段 | 类型 | 用途 |
|------|------|------|
| `interrupted` / `recoverable` / `recovery_required` | bool | 恢复状态标志 |
| `recovery_summary` | dict | 中断恢复提示 |
| `degraded` / `degraded_reason` | bool/str | 降级信息 |
| `phase1a_fallback` | bool | 是否使用 fallback |
| `degraded_batches` | list[int] | 降级批次索引 |

---

## 5. 前端标准化层

**源文件**: `frontend-console/shared/workflowProgress.js:238-310`

### 5.1 `normalizeTaskProgress(task, workflowType)` 输入消费

`task` 参数 → 通过 3 个安全包装器: `safeObject(task)`, `safeObject(task.result)`, `safeObject(task.meta)`

**消费的字段**（含回退链）:

```
task.status                     → statusLabel (中文映射)
task.progress                   → clampPercent()
                                  → 0-1 缩放为 0-100, done 强制 100
                                  → 非数字/NaN 返回 null → 触发不确定条
result.current_phase            → currentPhase (透传)
result.current_operation        → currentOperation (透传)
result.phase_timeline           → phaseTimeline (透传)
result.progress_events          → progressEvents (透传)
result.acceptance_checks        → acceptanceChecks (透传)
result.phase_errors             → phaseErrors (透传)
result.phase_artifacts          → phaseArtifacts (透传)
result.asset_summary|assetSummary → assetSummary (透传)
result.diagnostic_counts        → diagnosticCounts (透传)
task.error_message|result.error_message|result.error → sanitizeTaskErrorMessage()
                                                      → 过滤 DBAPIError/SQLAlchemy/asyncpg 等技术细节
                                                      → 替换为 "后台任务失败，请稍后重试。"
result.warnings|meta.warnings   → + phase_artifact coverage/repair/degraded 检查
                                 → + acceptance_checks 中 failed 项
                                 → → warnings[]
result.summary|completed_steps  → buildResultSummary() (按 workflowType 分支)
task.available_actions          → 或根据状态推断
```

**安全默认值**:

- `status`: `"pending"`
- `percent`: `null`（缺失/非数字时）
- `label`: `"后台任务"`
- `message`: `"任务状态未知"`
- `warnings`: `[]`
- `resultSummary`: `null`
- 所有诊断数组: `[]`
- 所有诊断对象: `{}`
- `createdAt/startedAt/updatedAt/heartbeatAt`: `null`
- `recoveryRequired`: `false`
- `availableActions`: 按状态推断

### 5.2 `pollTaskProgress()` 轮询生命周期

**源文件**: `workflowProgress.js:375-473`

- 默认间隔: **1500ms**
- 使用 `setTimeout` 递归调度（不是 `setInterval`）
- 通过 `inFlight` 布尔值确保同一时间只有一次请求飞行
- `pauseWhenHidden=true` 时监听 `visibilitychange` 事件
- **错误时不停轮询**: catch 分支构造 `stateUnknown` progress 对象，继续调度下一个 tick
- **自动停止条件**: `done`/`failed`/`cancelled`
- **stale 不停轮询**: `stale` 字段透传但不会自动停止
- 返回值 `{ stop }` 供外部手动停止

---

## 6. 进度条渲染器

**源文件**: `frontend-console/shared/progressRenderer.js`

### 6.1 `renderInlineProgress(progress, options)` 消费的全部字段

| 字段 | 类型 | 渲染位置 |
|------|------|---------|
| `progress.label` | string | 标题 (`options.title` 可覆盖) |
| `progress.statusLabel` | string | 状态徽章 |
| `progress.message` | string | 消息体 (`options.message` 可覆盖) |
| `progress.failed/done/cancelled` | boolean | CSS 类 |
| `progress.indeterminate` | boolean | 进度条模式 |
| `progress.percent` | number\|null | 进度条宽度 + aria-valuenow |
| `progress.hasPercent` | boolean | 是否显示 "X%" |
| `progress.taskId` | string\|null | "任务 {id}" |
| `progress.resultSummary` | string\|null | `.summary` div |
| `progress.errorMessage` | string\|null | `.error` div |
| `progress.warnings` | string[] | 警告列表（最多 3 条） |
| `progress.assetSummary.adopted/review/not_adopted` | number | 资产统计表 |
| `progress.phaseArtifacts` | object | 阶段产物摘要（各 4 个字段） |
| `progress.phaseTimeline[].phase/status/duration_s/error_kind` | 最近 8 条 | 时间线 |
| `progress.progressEvents[].phase/event/status/level/message/details` | 最近 10 条 | 事件流 |
| `progress.acceptanceChecks[].phase/name/ok/message/details` | 最近 10 条 | 门禁检查 |
| `progress.phaseErrors[].phase/error_kind/message` | 最近 6 条 | 错误列表 |
| `progress.diagnosticCounts` | object | 键值对诊断 |

### 6.2 三种渲染包装

- **`renderFixedProgress`** → `renderInlineProgress` + `.workflow-progress-fixed` 容器 + 可选 `bottom: Npx`
- **`renderWorkflowCard`** → `renderInlineProgress` + `.workflow-progress--card` 类 + `destinationLabel`
- **`renderProgressBar`** → 不确定 (`indeterminate`) 或确定 (`percent`) 模式

### 6.3 安全处理

- 所有输出统一经 `escapeHtml()` 转义
- `<details>` 使用 `sessionStorage` 持久化展开/折叠状态
- `renderDetailedProgress` 在所有子渲染器返回空时不渲染

---

## 7. 各视图轮询差异

| 视图 | 工作流类型 | 轮询机制 | 间隔 | 渲染方式 | 错误行为 |
|------|-----------|---------|------|---------|---------|
| `deepImportRecovery.js` | `deep_import` / `scene_auto_extraction` / `world_object_auto_extraction` / `plot_structure_auto_extraction` / `chapter_card_generation` / `outline_chapter_scenes_extract` | **单请求递归 `setTimeout`** | **3000ms + 退避** | `renderFixedProgress` | 仅 404 清理，瞬时错误重试 |
| `sceneWorkbenchView` | `scene_auto_extraction` | `pollTaskProgress` | 1500ms | `renderWorkflowCard` | 错误后继续 |
| `outlineView` | `outline_generate` / `plot_structure_auto_extraction` | `pollTaskProgress` | 1500ms | `renderWorkflowCard` | 错误后继续 |
| `worldView` | `world_object_auto_extraction` / `world_entity_fusion_suggestions` | `pollTaskProgress` | 1500ms | `renderWorkflowCard` | 错误后继续 |
| `ragView` | `rag_reindex_novel` / `rag_retry_embeddings` | `pollTaskProgress` | 1500ms | `renderWorkflowCard` | 错误后继续 |
| `worldBibleView` (**source**: `worldBibleView.js:736`) | `world_bible_projection_refresh` | `pollTaskProgress` | **800ms** | 手动渲染 `状态: X · 进度 Y%` | 错误后继续 |
| `projectView` | 文件上传（非任务） | 无轮询 (XHR `onprogress`) | — | `renderInlineProgress` | XHR 错误 |

**轮询间隔代码证实**:
- `deepImportRecovery.js`: 立即查询后用 `setTimeout` 调度下一次，并防止请求重叠 ✅
- `workflowProgress.js:378`: `intervalMs = 1500` ✅
- `worldBibleView.js:736`: `intervalMs: 800` ✅

Scene 工作台的两个任务轮询只替换各自的稳定进度挂载节点，
不再调用 `router.renderCurrentView()` 重建整个 Scene 列表。终态数据通过
workbench 局部刷新加载，并恢复列表 `scrollTop`。

---

## 8. 深度导入专用进度计算

### 8.1 百分比计算

**源文件**: `deepImportRecovery.js:41-68` — `computeDeepImportPercent(task, result)`

**优先使用后端值**:

```javascript
if (typeof task.progress === "number") {
    return task.progress <= 1 ? Math.round(task.progress * 100) : Math.round(task.progress)
}
// fallback to phase-based calculation
```

> **关键发现**: 不是"前端自己算"，而是优先用后端 `task.progress`。仅当后端值为 null/undefined 时才 fallback 到 phase-based 算法。

**Fallback 阶段范围**:

| 阶段 | 区间 | 公式 |
|------|------|------|
| `phase0_plan` | 0-10% | `round(p1Completed/p1Total * 10)` |
| `phase1a_scene_slicing` | 10-20% | `10 + round(p1Completed/p1Total * 10)` |
| `phase1b_enrichment` | 20-30% | `20 + round(p1Completed/p1Total * 10)` |
| `scene_commit` | 30%（固定） | — |
| `entity_extraction` | 40-80% | `40 + round(p2Completed/p2Total * 40)` |
| `structure_analysis` | 80%（固定） | — 但前端覆盖为 null → 不确定条 |
| `done` | 100% | — |

### 8.2 `structure_analysis` 阶段的不确定条

**源文件**: `deepImportRecovery.js:219-224`

```javascript
const isStructureRunning = (
  p.currentPhase === "structure_analysis" && status === "running"
)
const progressValue = isStructureRunning
  ? null      // ← 触发不确定进度条
  : (typeof p.percent === "number" ? p.percent : null)
```

### 8.3 恢复提示检测

**源文件**: `deepImportRecovery.js:124-132`

```javascript
function hasRecoveryPrompt(p = progress) {
  const actions = Array.isArray(p?.availableActions) ? p.availableActions : []
  return Boolean(
    (actions.includes("resume") && actions.includes("abandon"))
    || p?.recoveryRequired || p?.interrupted || p?.recoverable,
  )
}
```

触发恢复提示后轮询暂停，等待用户交互。

---

## 9. 存储与恢复

**源文件**: `workflowProgress.js:312-373`

### 9.1 持久化到 localStorage

- Key: `"novel_active_workflows_v1"`
- 数据结构: 每个元素包含 `id`, `taskId`, `workflowType`, `projectId`, `view`, `meta`, `createdAt`, `updatedAt`
- 复合 key: `{projectId}:{workflowType}:{taskId}`

### 9.2 恢复

- `recoverActiveWorkflows(projectId)` → 读取 → 迁移旧格式 → 去重 → 按 projectId 过滤
- `deepImportRecovery.recover()` → 调用 `api.tasks.get(taskId, projectId)` → 根据状态分支:
  - 已完成/失败/取消: 显示结果或恢复提示
  - 运行中: 调用 `startPolling()` 恢复轮询
  - 明确 404: 清理本地恢复记录
  - 网络/5xx/超时: 保留记录并退避重试

---

## 10. 错误处理全景

| 层 | 错误类型 | 行为 |
|----|---------|------|
| API | 任务不存在 | 返回 404 `{detail: "Task not found"}` |
| API | 无效 UUID | FastAPI 自动 422 校验错误 |
| API | 取消已完成任务 | 返回 400 |
| API | 重试不允许 | 返回 409 Conflict |
| 后端 | 心跳过期 | `lifecycle_contract()` 设置 `stale=true`, `worker.py` 恢复停滞任务 |
| `pollTaskProgress` | 网络错误/404 | 构造 `stateUnknown` progress → `onUpdate` → 继续轮询 |
| `deepImportRecovery` | 瞬时查询失败 | 保留任务，按 3/6/12/24/30 秒退避重试 |
| `normalizeTaskProgress` | 缺失/损坏字段 | `safeObject()`/`safeArray()` 返回安全默认值 |
| `sanitizeTaskErrorMessage` | 技术关键词 | 替换为用户友好文本 |

---

## 11. 核心结论（代码核实后修正）

| # | Agent 原始断言 | 核实结果 | 代码证据 |
|---|--------------|---------|---------|
| 1 | progress 是 ORM 列，非计算值 | ✅ 正确 | `api.py:180`, `models.py:40-44` |
| 2 | 所有诊断字段嵌套在 result 内 | ✅ 正确 | `orchestrator.py:222` |
| 3 | 每次 progress 回调完整替换 result | ✅ 正确 | `orchestrator.py:222` |
| 4 | 前端优先用后端 progress 值 | ⚠️ **修正**: 原报告说"前端自己算百分比"。**实际**: 优先用 `task.progress`（`computeDeepImportPercent` 第 42-46 行），fallback 才用 phase 计算 | `deepImportRecovery.js:41-46` |
| 5 | scene_commit 后端值为 30% | ✅ 前后端已统一为 30% | `workflow_scene_phase.py` / `deepImportRecovery.js` |
| 6 | phase 百分比权重 40%/40%/20% | ✅ 偏差不大 | 从各 `emit_progress` 调用点看场景→实体→结构权重 |
| 7 | deepImportRecovery 轮询间隔 3000ms | ✅ 正确 | `deepImportRecovery.js:524` |
| 8 | worldBibleView 轮询间隔 800ms | ✅ 正确 | `worldBibleView.js:736` |
| 9 | 阶段时间线上限 120 | ✅ 正确 | `service_progress_limits.py:9` |
| 10 | 门禁检查上限 200 | ✅ 正确 | `service_progress_limits.py:10` |
| 11 | 阶段错误上限 120 | ✅ 正确 | `service_progress_limits.py:11` |
| 12 | structure_analysis 阶段 percent=null → 不确定条 | ✅ 正确 | `deepImportRecovery.js:219-224` |
| 13 | 错误后 `pollTaskProgress` 继续轮询 | ✅ 正确 | `workflowProgress.js:452-461` |
| 14 | 错误后 `deepImportRecovery` 5 次后停止 | ❌ 已修正为有上限退避的持续恢复，不清除 localStorage | `deepImportRecovery.js` |
| 15 | lifecycle_contract 每次 GET 实时计算 | ✅ 正确 | `api.py:172-175` |

---

## 附录: 关键源文件索引

| 文件 | 路径 | 行数 |
|------|------|------|
| Task API 端点 | `backend/infrastructure/tasks/api.py` | 261 |
| Task ORM 模型 | `backend/infrastructure/tasks/models.py` | 153 |
| 生命周期合约 | `backend/infrastructure/tasks/lifecycle.py` | 329 |
| DeepImportProgress schema | `backend/modules/imports/workflow_schemas.py` | 189 |
| 进度追踪器 | `backend/modules/imports/workflow_progress.py` | 344 |
| 进度日志 | `backend/modules/imports/service_progress_logs.py` | (非关键) |
| 进度限制 | `backend/modules/imports/service_progress_limits.py` | 58 |
| 编排器 | `backend/modules/imports/orchestrator.py` | 927 |
| Scene Phase Runner | `backend/modules/imports/workflow_scene_phase.py` | — |
| Entity Phase Runner | `backend/modules/imports/workflow_entity_phase.py` | — |
| 前端标准化+轮询 | `frontend-console/shared/workflowProgress.js` | 475 |
| 前端渲染器 | `frontend-console/shared/progressRenderer.js` | 277 |
| 深度导入恢复 UI | `frontend-console/views/writing/deepImportRecovery.js` | 1031 |
| 自动提取表单 | `frontend-console/views/writing/autoExtraction.js` | — |
| 场景工作台 (poll) | `frontend-console/views/sceneWorkbenchView.js` | — |
| 大纲视图 (poll) | `frontend-console/views/outlineView.js` | — |
| 世界视图 (poll) | `frontend-console/views/worldView.js` | — |
| RAG 视图 (poll) | `frontend-console/views/ragView.js` | — |
| 世界圣经 (poll) | `frontend-console/views/worldBibleView.js` | — |
