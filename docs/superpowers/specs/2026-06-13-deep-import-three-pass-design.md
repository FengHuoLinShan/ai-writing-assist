# 深度导入流水线（三遍 Workflow）设计文档

## 1. 目标

让网络小说作者在导入正文后，能够一键对指定章节范围启动“深度导入”。系统在后台自动完成三阶段流水线：

1. **Scene 切分**：读取章节正文，按 5 章/批 + 1 章 overlap 切分，LLM 输出 scenes[]。
2. **实体增量提取**：按 `scene_index` 串行提取世界对象、关系和 Delta；新对象标记 `canonical` 且 `content_json._meta.auto_ingested=true`。
3. **结构分析**：基于 Scene 摘要、Delta 流、实体索引生成 `plot_threads`、`outline_arcs`、`foreshadowing_plans`、`reveal_plans`。

浏览器关闭后任务继续执行；重新进入项目时能通过 `task_id` 恢复进度展示。

真实 LLM 验收必须使用数据库中《诡秘之主 第一部》项目的第 1-3 章。

## 2. 当前状态

项目已有一个可运行的三阶段骨架：

- `backend/modules/imports/workflow.py`：`DeepImportWorkflow` 编排三步。
- `backend/modules/imports/scene_segmentation.py`：`SceneSegmentationService` 已实现 5 章/批 + 1 章 overlap、批次失败降级到单章、再失败机械分章。
- `backend/modules/imports/scene_entity_extraction.py`：`SceneEntityExtractionService` 按 Scene 串行提取实体并写 `delta_log`。
- `backend/modules/outline/services.py`：`PlotStructureGenerator` 生成剧情线/篇章纲/伏笔/揭示计划。
- `backend/modules/imports/api.py` / `facade.py`：提供 `/api/imports/deep`、`/deep/sync`、重复导入检测。
- `frontend-console/views/writingView.js`：深度导入入口、进度条、`localStorage` 恢复轮询。

但存在以下缺口，需要补齐才能满足验收要求：

| 缺口 | 影响 |
|---|---|
| Phase 1/2 未用 Pydantic schema 校验 LLM 输出 | 容易写入字段缺失/格式错误的 Scene 或实体 |
| Phase 2 未持久化关系 | 要求中的“关系”资产缺失 |
| Phase 2 未写 `content_json._meta.auto_ingested` | 自动对象缺少可回滚/可编辑元数据 |
| Phase 2 每 10 个 Scene 才拍快照，验收要求“每个 Scene 完成后更新记忆快照” | 记忆快照不满足 |
| 重复导入检测以整个 novel 为粒度，不是指定章节范围 | 会误报/漏报覆盖警告 |
| `force=true` 时没有真正 deprecate 旧派生数据 | 旧 Scene/Entity/Delta 残留 |
| API 只返回 `task_id`，未返回 `workflow_id` | 验收要求两者 |
| 缺少 Phase 1 降级、重复导入、novel_id 隔离、关系、快照的针对性测试 | 无法证明满足约束 |
| 真实 LLM 验收脚本覆盖的是章节级旧服务，不是当前 Scene 级流水线 | 验收数据不可靠 |

## 3. 设计方案

### 3.1 总体思路

采用**最小改动、补齐缺口**的策略：保留现有成熟骨架，围绕验收要求做精确增强，不推翻现有架构，不引入新基础设施。

- 在 `backend/modules/imports/` 下新增 `llm_schemas.py`，定义 Phase 1 `SceneSegmentationOutput` 与 Phase 2 `SceneEntityExtractionOutput`，并用 Pydantic 校验 LLM 输出。
- 在 `SceneEntityExtractionService` 中：
  - 解析并持久化 `relations`；
  - 创建实体时携带 `content_json._meta.auto_ingested=true` 及 `source_scene_index`；
  - 每个 Scene 处理成功后调用 `MemoryService.capture_snapshot`。
- 在 `facade.py` 中：
  - 将重复检测改为按章节范围查询 `scenes`、`core_entities`、`plot_threads`、`outline_arcs`；
  - `force=true` 时把该范围内的旧派生数据标记为 `deprecated`。
- API 返回同时包含 `workflow_id`（与 `task_id` 同值）和 `task_id`。
- 测试层补齐：状态机、降级、重复导入确认、novel_id 隔离、关系/快照、真实 LLM 1-3 章验收脚本。

### 3.2 备选方案

| 方案 | 说明 | 优缺点 |
|---|---|---|
| A（推荐） | 在现有 Scene 级流水线上补齐缺口 | 改动小、风险低、复用现有 worker/前端/测试基础设施 |
| B | 回退到章节级 `EntityExtractionService` 重新做 Scene 切分 | 已有真实 LLM 测试，但不符合“按 scene_index 串行”要求 |
| C | 引入新的任务状态机/持久化层 | 能更优雅地支持断点恢复，但违反“不引入新基础设施”约束 |

选择 **方案 A**。

### 3.3 组件与文件变更

| 文件 | 变更 |
|---|---|
| `backend/modules/imports/llm_schemas.py` | 新增 `SceneChunk`、`SceneItem`、`SceneSegmentationOutput`、`ExtractedEntity`、`ExtractedRelation`、`DeltaEvent`、`SceneEntityExtractionOutput` |
| `backend/modules/imports/scene_segmentation.py` | `_process_batch` / `_process_batch_single_chapter` 用 `SceneSegmentationOutput.model_validate` 校验；机械 fallback 也补字段默认值 |
| `backend/modules/imports/scene_entity_extraction.py` | `_call_llm_extraction` 用 `SceneEntityExtractionOutput.model_validate`；`_persist_entities` 写 `_meta`；新增 `_persist_relations`；每个 Scene 成功后调用 `MemoryService.capture_snapshot` |
| `backend/modules/imports/facade.py` | `_check_duplicate_import` 改为按章节范围；`start_deep_import` 在 `force=true` 时调用 `_deprecate_derived_data`；返回 `workflow_id` |
| `backend/modules/imports/api.py` | `/deep` 与 `/deep/sync` 返回 `workflow_id` |
| `backend/modules/imports/workflow_schemas.py` | 可选：增加 `workflow_id` 字段 |
| `backend/modules/imports/tests/test_workflow.py` | 增加失败降级、degraded_batches、workflow_id 测试 |
| `backend/modules/imports/tests/test_imports_integration.py` | 增加重复导入确认、novel_id 隔离、机械 fallback 测试 |
| `backend/modules/imports/tests/test_scene_entity_extraction.py` | 新增：relation 持久化、auto_ingested、每 Scene 快照 |
| `backend/scripts/acceptance_deep_import.py` | 新增：对《诡秘之主 第一部》第 1-3 章执行真实 LLM 深度导入，统计输出数量 |
| `frontend-console/views/writingView.js` | 若需要，处理 `workflow_id` 并确保无章节时入口不显示（已满足） |

### 3.4 数据流

```
用户点击“启动深度导入”
  → POST /api/imports/deep
    → facade.start_deep_import
      → 按范围检查已有派生数据
        → 有数据且 force=false → 返回 requires_confirmation
        → 有数据且 force=true  → deprecate 旧数据 → enqueue deep_import
        → 无数据              → enqueue deep_import
      → 返回 {workflow_id, task_id, status, requires_confirmation}
  → Worker 领取 deep_import 任务
    → DeepImportWorkflow.run_step
      Phase 1 SceneSegmentationService.segment_chapters
        → 5 章/批 + 1 章 overlap
        → LLM 输出 → SceneSegmentationOutput.model_validate → 写入 scenes
        → 批次失败 → 单章 fallback → 仍失败 → 机械分章
      Phase 2 SceneEntityExtractionService.extract_by_scenes
        → 串行遍历 scenes
        → LLM 输出 → SceneEntityExtractionOutput.model_validate
        → 去重 → create_entity (canonical + _meta.auto_ingested)
        → create_relation (canonical)
        → create_delta_log
        → MemoryService.capture_snapshot 每个 Scene
      Phase 3 PlotStructureGenerator.generate
        → 生成 plot_threads / outline_arcs / foreshadowing_plans / reveal_plans
  → 前端轮询 /api/tasks/{task_id} 更新进度条
  → 浏览器关闭后重新打开 → localStorage task_id → 恢复轮询
```

### 3.5 错误处理与降级

- 单次 LLM 调用：内部已重试 3 次。
- Phase 1 批次失败：降级为逐章切分；仍失败则按章机械切分。
- Phase 2 Scene 失败：记录 warning，继续下一个 Scene，不阻塞 Phase 3。
- Phase 3 失败：返回空结果，workflow 仍标记 `done`（与现有行为一致，避免阻塞）。
- 记忆快照失败：记录 warning，不影响 Scene 级流程。

### 3.6 验收标准

- 自动化测试通过：状态机、降级、重复导入确认、novel_id 隔离、关系/快照。
- 真实 LLM 验收：《诡秘之主 第一部》第 1-3 章生成 Scene、Entity、PlotThread、OutlineArc、ForeshadowingPlan、RevealPlan、Relation、DeltaLog、MemorySnapshot，数量记录到脚本输出。
- 前端 E2E：启动、进度展示、路由切换恢复、无章节不显示入口。

## 4. 问题与假设

1. 假设现有 PostgreSQL 开发库和 LLM API Key 已配置，可用于真实 LLM 验收。
2. 假设 `modules.world.facade.create_relation` 在传入有效 source/target ID 时可用（已在 `test_world.py` 验证）。
3. 假设 `content_json._meta` 不会与现有 schema 冲突（`CoreEntityCreate.content_json` 是自由 dict）。

## 5. 下一步

本设计通过后将进入实现计划阶段（`writing-plans`）。
