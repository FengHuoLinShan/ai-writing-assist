# Module: imports / 小说导入模块（原设计以外新增）

## 定位

imports 模块负责将本地小说文件解析并导入系统，创建 WritingDraft 记录以供后续实体抽取和创作使用。它也负责深度导入的工作流编排，但各阶段的具体业务写入仍通过对应模块的公开接口完成。

## 数据表

- `import_records` — file_name / file_type / file_size / total_chapters / imported_chapters / status / error_message
- `imported_chapters` — 仍是活跃的章节正文表并被 world 事件/关系/版本来源 FK 引用；当前上传主路径把章节写为 `writing_drafts`，不把它当作第二个编辑入口

## 文件解析器（parsers.py）

| 格式 | 库 | 说明 |
|------|----|------|
| .txt | 内置 + chardet | 编码检测 + 章节正则分割 |
| .epub | ebooklib | 逐章提取 |
| .html/.htm | beautifulsoup4 | 提取文本 |
| .mobi/.azw3 | 内置 | 原始解析 |

## 服务

- ImportService.upload_and_import()：文件校验 → 解析 → 创建 WritingDraft → 更新 ImportRecord
- DeepImportWorkflow：带确定性规划、Scene 切分、Scene enrichment、实体/关系提取、结构分析和恢复语义的深度导入流水线，运行在 `async_tasks` 的 `deep_import` 任务中

## 深度导入流水线

DeepImportWorkflow 将 Scene 提取、实体抽取和结构分析串成受控自动流水线。启动前必须由
用户一次性确认 `adoption_policy="user_authorized_pipeline"`；运行中不逐项打断。当前权威 Scene 阶段是
`Phase 0 deterministic plan → Phase 1a scene slicing → Phase 1b scene enrichment → Scene commit`。
旧 `scene_prefetch` / `scene_reinforcement` legacy pipeline 已删除；
`scene_fusion` 仍作为内部兼容/修复组件保留，默认不进入 Scene 自动提取主路径。
`workflow.py` 不再保留旧 prefetch / reinforcement / single-chapter fallback / fusion wrapper；
默认路径只通过 `workflow_scene_phase.py` 调用 plan / slicing / enrichment / commit seam。
`workflow.py` 仅保留 `DeepImportWorkflowRuntime` 要求的活跃 phase runner seam；
非 runtime seam 的薄包装/死代码已清理，PhaseRunner DI 大重构不属于本次变更。

### Phase 0: deterministic plan
- 不调用 LLM；按章节字符数生成窗口计划、owned range、右侧 overlap 和每窗 token 预算。
- 计划结果决定 Phase 1a 的输入范围和 `max_tokens`，避免由模型自行决定 batch 边界。
- Phase 0 不写正式 `scenes` 表，也不执行 LLM health 或 422 门禁。

### Phase 1a: scene slicing
- 只切分并锁定 Scene 边界字段：`title` / `goal` / `core_conflict` / `start_chapter` / `end_chapter` / `boundary_status`。
- LLM 输出只用于 Scene 边界候选；`scene_chunks` 不由 LLM 定位。
- length / invalid JSON 等截断类失败会按受控 token 预算重试；仍失败的缺失章节生成 `needs_review` 的章节级 fallback。

### Phase 1b: scene enrichment
- 每个 Scene 一个 enrichment 请求，只补充描述性字段，不允许改写 Phase 1a 锁定的边界字段。
- `scene_chunks` 由系统按 `start_chapter` / `end_chapter` 的章级范围确定生成。
- 单 Scene enrichment 失败只影响当前 Scene：重试后仍失败则 fallback 并进入人工复核清单。

### Scene commit
- Phase 1a / 1b 都是 workflow 中间层；正式 Scene 只在 Scene commit 后写入。
- 正式 Scene 写入携带 provenance / workflow / auto_ingested 信息；恢复或重跑时按 provenance 跳过已提交结果。无复核标记的结果计为已采用，`needs_review` 结果进入待处理汇总。
- 提交前必须补齐 Scene 工作台健康检查依赖的 `core_conflict / must_happen / must_not_happen`，缺失时由来源目标和冲突保守派生。

### Phase 2a / 2b: 世界对象、Delta、别名与关系（40%）
- Phase 2a 基于已提交 Scene 抽取世界对象与 Delta。
- Phase 2 Scene 实体抽取实现位于 `entity_extraction/` 子包；`modules.imports.entity_extraction` 是稳定公共导出入口，旧顶层 `scene_entity_extraction.py` 兼容 hub 已删除。
- Phase 2a 路由选择集中在 `entity_extraction/scene_entity_strategy.py`，只决定 empty、small-sample parallel、bulk、batched 或 checkpoint resume；LLM 调用、persistence、checkpoint、prompt、timeout 和返回契约仍由子包内执行模块负责。
- Phase 2b 基于 Phase 2a 的对象索引补抽别名和关系；失败只降级，不丢弃已抽取对象。
- 大量 Scene 在 Phase 2a 以 Scene 为并发单元调用 LLM，再按 `scene_index`
  串行持久化；每个请求只含当前 Scene 和前序 brief，不带后续 Scene。
- 只对相邻 batch 边界执行补充抽取，不做全局对象融合扫描。
- 入库前通过 world facade 使用名称 / 别名 / embedding 去重能力；高置信重复实体会自动融合到已有对象，重复关系走 create-or-merge。
- Phase 2 的真实 LLM 调用通过 context facade 写入 `context_snapshots`，并在任务结果中记录 snapshot health、dedup、boundary supplement 和 degraded 统计。

### Phase 3: 结构分析（单次，20%）
- 输入：全量 Scene 摘要 + 坍缩后 Delta 变更流 + 实体索引
- LLM 输出：plot_threads / outline_arcs / foreshadowing_plans / reveal_plans
- 四类产物分别写入对应表
- 深度导入模式显式使用 `context_mode="working"` 并包含待处理对象；context 会给结果加“包含未采用内容”警告。
- 完成后会通过 outline facade 生成结构去重建议；仅自动应用同一 deep import workflow 内的高置信重复，跨已有资产的建议只写入任务结果。

### 进度状态

由 `DeepImportProgress` Schema 定义，并写入 `async_tasks.result`；`async_tasks.progress` 使用 0.0 / 0.4 / 0.8 / 1.0 表示阶段推进：
- current_step: scene_segmentation / entity_extraction / structure_analysis
- completed_steps: 已完成阶段
- message: 当前可展示给用户的中文状态
- current_chapter / current_scene / current_batch / current_round / quality_stats: 前端进度条周围展示的实时位置和质量统计
- phase1_total_batches / phase1_completed_batches
- phase2_total_scenes / phase2_completed_scenes
- progress_events: compact JSONL-like 服务事件流，用于详细进度显示，不含正文、API key 或 raw prompt
- acceptance_checks: 结构化门禁结果，用于展示 coverage、repair、zero output、degraded 等诊断
- degraded / degraded_batches 标记降级
- quality_status: pending / complete / partial / failed
- phase_errors: 各阶段可机器读取的失败或降级原因
- recovery_required / recovery_summary: worker/backend 中断后提示用户手动继续或放弃恢复
- quality_stats.phase1a：Scene slicing 覆盖、fallback、缺章与重试统计
- quality_stats.phase1b：enrichment 成功、fallback 与复核统计
- adoption_policy / authorization_snapshot：启动时持久化的授权策略、范围和时间
- asset_summary：互斥的 `adopted / review / not_adopted` 总数及 Scene、实体、关系、别名、结构分项

当任务能跑完但 Phase 2/3 未生成关键 AI 资产时，`phase` 仍可为 `done`，但
`quality_status="partial"` 且 `degraded=true`。前端应把它显示为“部分完成”，
验收脚本不得只凭 `phase="done"` 判定真实 LLM 导入成功。

重复导入时，`POST /api/imports/deep` 先返回：
- `status="requires_confirmation"`
- `requires_confirmation=true`
- `warning`

前端确认覆盖后重新提交 `force=true`，此时才创建 `deep_import` 任务。清理只作用于目标
`novel_id`/章节范围内带 `source=deep_import` 且有 workflow/auto_ingested 所有权标记的 Scene
及自动导入对象，人工 Scene 不得被废弃。demo 阶段如重构派生表可重建开发库，但仍不得
绕过用户授权和 novel_id 范围限制。

## 安全约束

- 文件类型白名单：`.txt .epub .html .htm .mobi .azw3`
- 大小上限：50MB
- 文件名必须 `os.path.basename` 处理，防止路径穿越

## API

```
POST /api/imports/upload                    # 上传并导入（multipart/form-data）
GET  /api/imports                           # 导入记录列表
GET  /api/imports/{id}                     # 导入记录详情
POST /api/imports/deep                     # 提交深度导入任务；重复导入需 force=true
POST /api/imports/stages/scenes            # 只执行 Phase 0/1a/1b + scene_commit
POST /api/imports/stages/world-objects     # 只执行 Phase 2a/2b
POST /api/imports/stages/plot-structure    # 只执行 Phase 3
POST /api/imports/deep/sync                # 同步执行深度导入（E2E/无 worker 场景）
POST /api/imports/deep/resume              # 用户确认后继续可恢复的原 deep_import 或 stage task
POST /api/imports/deep/abandon             # 放弃恢复并清理同 workflow 自动派生资产
```

`/deep` 与三个 `/stages/*` 请求都必须显式发送
`authorization_confirmed=true`；缺失或 false 返回 422 且不排队。任务 meta 和 result 都保存
同一授权快照，完成页从 result 的 `asset_summary` 展示已采用/待处理/未采用。

分阶段真实服务会把 compact artifact 写入现有 `async_tasks.result.phase_artifacts`：
记录章节覆盖、阶段计数、checkpoint 摘要、repair 状态、质量状态和脱敏 provider 摘要。
该字段只用于恢复、审计和前端轮询展示，不保存 API key、完整正文、raw prompt 或 raw LLM 输出；
artifact builder 会递归移除 prompt/body/content/context/raw LLM payload 字段，只保留 compact 计数、
coverage、checkpoint 和脱敏 provider summary。
服务路径也会把测试期 JSONL / Markdown 中有价值的事件和验收信息转成
`progress_events` / `acceptance_checks`，作为前端默认摘要和“详细进度”展开区的数据源；
真实服务不依赖 `.test-logs` 文件路径。
旧测试期 artifact harness 已移除，不再作为推荐验收入口；恢复、审计和前端展示都以
`async_tasks.result` 内的 compact 字段为准。

## 跨模块依赖

- 写入导入章节正文通过 `writing.facade.create_draft`
- Scene 阶段通过 outline facade / DI handler 提交已授权且带来源/回滚元数据的 `scenes`
- Phase 2a / 2b 通过 world facade / DI handler 写入 `core_entities` / 关系数据和 Delta
- Phase 2 后通过 `memory.facade.capture_snapshot` 记录记忆快照
- Phase 2 / Phase 3 通过 `context.facade` 创建、标记并汇总 `context_snapshots`
- Phase 3 通过 outline facade / DI handler 写入 `plot_threads` / `outline_arcs` / `foreshadowing_plans` / `reveal_plans`
- 新增跨模块依赖应优先走 facade 或 DI container 注册服务；不得直接 import 其他模块 repositories/services
- 放弃可恢复 workflow 通过各领域 facade 整批软回滚：outline/world 资产废弃、Memory DeltaLog 标记 `rolled_back`、MapObservation 转 `ignored`；所有操作按 novel/workflow 隔离并保留来源审计

## 真实服务验收与恢复证据

当前三阶段任务不依赖 test-only artifact 文件。生产任务和 stage task 在
`async_tasks.result` 写入 compact 证据：

- `phase_artifacts`：章节覆盖、阶段计数、checkpoint 摘要、repair 状态、质量状态和脱敏 provider 摘要
- `progress_events`：compact JSONL-like 事件流，供前端默认摘要和“详细进度”展开区使用
- `acceptance_checks`：coverage、zero output、degraded、repair 等结构化门禁结果
- `phase_errors`：各阶段可机器读取的失败或降级原因

这些字段只用于恢复、审计和轮询展示，不保存 API key、完整正文、raw prompt 或 raw LLM
输出。Phase 0 少量 batch 失败时自动重跑并合并一次；Phase 1a 对有限缺章做一轮
single-chapter fallback；Phase 2a / 2b 通过 checkpoint 和当前 Scene commit 结果复用已完成单元，
只重跑失败或未完成单元。`/api/imports/deep/resume` 与
`/api/imports/deep/abandon` 仍是生产兼容的恢复/放弃入口。

Phase2b 稳定性可通过 `PHASE2_ALIAS_RELATION_TOTAL_TIMEOUT_SECONDS`、
`PHASE2_ALIAS_RELATION_LLM_TIMEOUT_SECONDS`、
`PHASE2_ALIAS_RELATION_SCENE_CHAR_LIMIT`、
`PHASE2_ALIAS_RELATION_ENTITY_INDEX_CHAR_LIMIT` 和
`PHASE2_ALIAS_RELATION_ENTITY_INDEX_FALLBACK_LIMIT` 调整。Phase3 深度导入模式使用
紧凑结构 prompt：不生成新 Scene，以少量剧情线/篇章纲/伏笔/揭示作为稳定基线。

## Phase 2/3 Activation And Quality

Phase 2a 使用 `ImportContextActivation -> concurrent LLM -> scene_index ordered
persistence` 单一路径。默认 LLM 并发 64，并在连续限流、超时或格式失败时按
`64 -> 32 -> 16 -> 8` 降载；工作流的 `end_chapter` 作为可见硬截止，
跨章 Scene 只装载截止章/offset 以前的精确 span。checkpoint 记录 activation
version 和来源数量。Phase 2b
在其后执行全局别名/关系 reconciliation，不回写早期 Scene 的可见性语义。

Phase 3 复用 outline 的全书 Scene 摘要且不默认加载全书正文，追加 derived world
background。空结构、无结构引用和无有效篇章范围会触发一次同 workflow 的 draft/candidate
结构资产 replacement rerun；所有门禁与降级摘要保持在 task result 的加性诊断字段中。
