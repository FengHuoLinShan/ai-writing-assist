# Module: imports / 小说导入模块（原设计以外新增）

## 定位

imports 模块负责将本地小说文件解析并导入系统，创建 WritingDraft 记录以供后续实体抽取和创作使用。它也负责深度导入的工作流编排，但各阶段的具体业务写入仍通过对应模块的公开接口完成。

## 数据表

- `import_records` — file_name / file_type / file_size / total_chapters / imported_chapters / status / error_message

## 文件解析器（parsers.py）

| 格式 | 库 | 说明 |
|------|----|------|
| .txt | 内置 + chardet | 编码检测 + 章节正则分割 |
| .epub | ebooklib | 逐章提取 |
| .html/.htm | beautifulsoup4 | 提取文本 |
| .mobi/.azw3 | 内置 | 原始解析 |

## 服务

- ImportService.upload_and_import()：文件校验 → 解析 → 创建 WritingDraft → 更新 ImportRecord
- DeepImportWorkflow：带预取、补强、融合和恢复语义的深度导入流水线，运行在 `async_tasks` 的 `deep_import` 任务中

## 深度导入流水线

DeepImportWorkflow 将 Scene 提取、实体抽取和结构分析串成全自动流水线，
直接入库无需用户中途确认。新版 Scene 阶段拆为候选预取、逐批补强和融合提交，
避免固定 batch 边界截断 Scene，并允许恢复时略微重复局部任务以保证质量。
Phase 0 / Phase 1a 都是 workflow 中间候选层，不写正式 `scenes` 表；正式 Scene
只在 Phase 1b 融合和 scene commit 后写入。

启动前会执行 LLM health preflight。若 `LLM_HEALTH_REQUIRED=true` 且 LLM 不可用，
任务直接进入 `phase="failed"` / `quality_status="failed"`，不写入半成品 Scene。

### Phase 0 / 1a / 1b: Scene 候选与融合（40%）
- Phase 0 使用两轮错位 batch 并发预取候选 Scene，默认并发较高，允许缺失和错误。
- Phase 1a 是受控正文补强器，不是最终 Scene 切分器；它按 budget 收敛正文和 Phase 0 reference，输出短候选锚点供 Phase 1b 使用。
- Phase 1a 对 `network / rate_limit / empty_result` 做短重试；最终仍失败的 `timeout / schema_error` 等非 422 错误会生成 `degraded_fallback` 低质量中间候选，保留章节锚点继续推进。
- Phase 1a 的 422 错误率超过阈值仍阻断，避免不兼容 API 通道污染后续流程。
- Phase 1b 不带正文，以补强后的两轮结果做智能融合 / 切分建议，再提交正式 Scene。
- 正式 Scene 写入携带 provenance / workflow 信息；恢复或重跑时按 provenance 跳过已提交结果。
- Phase 0 / 1a 的最终 422 错误率超过 40% 时阻断深度导入，并提示使用稳定官方 API；Phase 1b 超阈值时降级使用 Phase 1a 结果继续。

### Phase 2: 实体增量提取（串行，40%）
- 按 scene_index 顺序串行处理每个 Scene
- 加载当前 Memory 上下文 → LLM 抽取 → 3 层去重检测 → 自动入库
- 实体写入 `core_entities`，当前 `status="candidate"`，并带 `content_json._meta.auto_ingested=true`、来源 Scene/章节和批次元数据
- Delta 变更写入 delta_log（Scene 内坍缩后）
- 每个 Scene 完成时触发 Memory 增量快照

### Phase 3: 结构分析（单次，20%）
- 输入：全量 Scene 摘要 + 坍缩后 Delta 变更流 + 实体索引
- LLM 输出：plot_threads / outline_arcs / foreshadowing_plans / reveal_plans
- 四类产物分别写入对应表

### 进度状态

由 `DeepImportProgress` Schema 定义，并写入 `async_tasks.result`；`async_tasks.progress` 使用 0.0 / 0.4 / 0.8 / 1.0 表示阶段推进：
- current_step: scene_segmentation / entity_extraction / structure_analysis
- completed_steps: 已完成阶段
- message: 当前可展示给用户的中文状态
- current_chapter / current_scene / current_batch / current_round / quality_stats: 前端进度条周围展示的实时位置和质量统计
- phase1_total_batches / phase1_completed_batches
- phase2_total_scenes / phase2_completed_scenes
- degraded / degraded_batches 标记降级
- quality_status: pending / complete / partial / failed
- phase_errors: 各阶段可机器读取的失败或降级原因
- recovery_required / recovery_summary: worker/backend 中断后提示用户手动继续或放弃恢复
- quality_stats.phase1a.degraded_fallback: Phase 1a 因非阻断 LLM 错误降级生成的中间候选数量

当任务能跑完但 Phase 2/3 未生成关键 AI 资产时，`phase` 仍可为 `done`，但
`quality_status="partial"` 且 `degraded=true`。前端应把它显示为“部分完成”，
验收脚本不得只凭 `phase="done"` 判定真实 LLM 导入成功。

重复导入时，`POST /api/imports/deep` 先返回：
- `status="requires_confirmation"`
- `requires_confirmation=true`
- `warning`

前端确认覆盖后重新提交 `force=true`，此时才创建 `deep_import` 任务。默认将旧数据标记为 deprecated；demo 阶段如重构导入派生表或重跑全量导入，也可以直接清空该小说的导入派生数据后重建。两种方式都必须保留用户确认和 novel_id 范围限制。

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
POST /api/imports/deep/resume              # 用户确认后继续可恢复的原 deep_import task
POST /api/imports/deep/abandon             # 放弃恢复并清理同 workflow 自动派生资产
```

## 跨模块依赖

- 写入 writing_drafts 通过 `writing.facade.create_draft_only()`
- 导入后逐章提交 `publish_chapter` 任务，由发布任务统一完成 RAG 索引与 memory 快照
- Phase 1 通过 scene_segmentation 任务写入 `scenes` 表
- Phase 2 通过 world facade / 注册服务写入 `core_entities` / 关系数据，通过 memory 模块记录 `delta_log`
- Phase 3 通过 outline 注册服务写入 `plot_threads` / `outline_arcs` / `foreshadowing_plans` / `reveal_plans`
- 新增跨模块依赖应优先走 facade 或 DI container 注册服务；不得直接 import 其他模块 repositories/services

## 真实 LLM 验收与测试 artifact

60 章真实 LLM 验收入口是 test-only，不改变 HTTP API：

- `RUN_DEEP_IMPORT_60_PHASE0_REAL_LLM=1`：只跑 Phase 0 prefetch，输出 `phase0_real_llm_<timestamp>.artifact.json`
- `RUN_DEEP_IMPORT_60_PHASE1A_REAL_LLM=1`：默认复用最近通过的 Phase 0 artifact，再跑 Phase 1a 后停止；可通过 `PHASE1A_PHASE0_ARTIFACT_PATH` 显式指定 artifact。后续 phase-only 真实验收入口默认消费上一个 phase 已通过 artifact，避免因前置 phase 临时波动重复整轮失败。
- `RUN_DEEP_IMPORT_60_SCENE_REAL_LLM=1`：跑 Phase 0 / 1a / 1b / scene_commit 后停止

artifact 只落在 `.test-logs/deep_import_real_llm/`，用于验收、复盘和 failed-batch repair；
Phase0 / Phase1a-only 入口还会创建 test-only `AsyncTask` result 映射，使 artifact
里的 `project_id` / `task_id` 能对上对应验收项目。它不进入前端主流程，也不等同于正式
Scene。repair 按 batch key 合并新旧结果，常用变量包括
`PHASE0_REPAIR_SOURCE_ARTIFACT_PATH`、`PHASE0_REPAIR_MAX_FAILED_BATCHES`、
`PHASE0_REPAIR_CONCURRENCY`、`PHASE0_REPAIR_ATTEMPTS`、
`PHASE1A_REPAIR_SOURCE_ARTIFACT_PATH`、`PHASE1A_REPAIR_MAX_FAILED_BATCHES`、
`PHASE1A_REPAIR_ATTEMPTS` 和 `PHASE1A_REPAIR_BATCH_IDS`。
