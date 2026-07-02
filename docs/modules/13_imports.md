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
- progress_events: compact JSONL-like 服务事件流，用于详细进度显示，不含正文、API key 或 raw prompt
- acceptance_checks: 结构化门禁结果，用于展示 coverage、repair、zero output、degraded 等诊断
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
POST /api/imports/deep/resume              # 用户确认后继续可恢复的原 deep_import 或 stage task
POST /api/imports/deep/abandon             # 放弃恢复并清理同 workflow 自动派生资产
```

分阶段真实服务会把 compact artifact 写入现有 `async_tasks.result.phase_artifacts`：
记录章节覆盖、阶段计数、checkpoint 摘要、repair 状态、质量状态和脱敏 provider 摘要。
该字段只用于恢复、审计和前端轮询展示，不保存 API key、完整正文、raw prompt 或 raw LLM 输出；
artifact builder 会递归移除 prompt/body/content/context/raw LLM payload 字段，只保留 compact 计数、
coverage、checkpoint 和脱敏 provider summary。
服务路径也会把测试期 JSONL / Markdown 中有价值的事件和验收信息转成
`progress_events` / `acceptance_checks`，作为前端默认摘要和“详细进度”展开区的数据源；
真实服务不依赖 `.test-logs` 文件路径。
测试期 `.artifact.json` 仍只作为 `.test-logs` 下的验收证据，不是业务数据源。

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
- `RUN_DEEP_IMPORT_60_PHASE1B_REAL_LLM=1`：默认复用最近通过的 Phase 1a artifact，再跑 Phase 1b 后停止；60 章默认使用确定性 reducer，不调用 LLM。可通过 `PHASE1B_PHASE1A_ARTIFACT_PATH` 显式指定输入，或用 `PHASE1B_USE_LLM=1` 复测 LLM reducer。LLM reducer 是最小决策器，只输出 `use_primary_round`，由代码物化 Phase 1a 候选。
- `RUN_DEEP_IMPORT_60_PHASE2A_REAL_LLM=1`：默认复用最近通过的 Phase 1b artifact，先把 `FinalSceneCandidate` 提交成 draft Scene，再只跑 Phase 2a 世界对象/Delta 抽取；明确跳过 Phase 2b alias/relation 与 Phase 3。可通过 `PHASE2A_PHASE1B_ARTIFACT_PATH` 指定输入。新 artifact 会写入 `world_snapshot`，供 Phase2b-only hydrate 上游世界对象。
- `RUN_DEEP_IMPORT_60_PHASE2B_REAL_LLM=1`：默认复用最近通过且带 `world_snapshot` 的 Phase 2a artifact，重新导入正文、提交 Scene、hydrate Phase2a 世界对象后只跑 Phase 2b alias/relation；明确跳过 Phase 3。可通过 `PHASE2B_PHASE2A_ARTIFACT_PATH` 指定输入。旧的无 `world_snapshot` Phase2a artifact 不能作为 Phase2b-only 输入。Phase2b 记录 scene 级 `alias_relation_checkpoints`，repair 时复用 `done` / `skipped` checkpoint；截断 JSON 会记录为 `alias_relation_fallback_scenes` 并以空结果完成该 Scene。
- `RUN_DEEP_IMPORT_60_PHASE3_REAL_LLM=1`：默认复用最近通过且带 `world_snapshot` 的 Phase 2b artifact，重新导入正文、提交 Scene、hydrate Phase2b 世界对象/关系快照后只跑 Phase 3 结构分析。可通过 `PHASE3_PHASE2B_ARTIFACT_PATH` 指定输入。输出 `phase3_real_llm_<timestamp>.md` 与 `.artifact.json`。
- `RUN_DEEP_IMPORT_60_SCENE_REAL_LLM=1`：跑 Phase 0 / 1a / 1b / scene_commit 后停止

artifact 只落在 `.test-logs/deep_import_real_llm/`，用于验收、复盘和 failed-batch repair；
Phase0 / Phase1a / Phase1b / Phase2a / Phase2b / Phase3-only 入口还会创建 test-only `AsyncTask` result 映射，使 artifact
里的 `project_id` / `task_id` 能对上对应验收项目。它不进入前端主流程，也不等同于正式
Scene。repair 按 batch key 合并新旧结果，常用变量包括
`PHASE0_REPAIR_SOURCE_ARTIFACT_PATH`、`PHASE0_REPAIR_MAX_FAILED_BATCHES`、
`PHASE0_REPAIR_CONCURRENCY`、`PHASE0_REPAIR_ATTEMPTS`、
`PHASE1A_REPAIR_SOURCE_ARTIFACT_PATH`、`PHASE1A_REPAIR_MAX_FAILED_BATCHES`、
`PHASE1A_REPAIR_ATTEMPTS`、`PHASE1A_REPAIR_BATCH_IDS`、
`PHASE2A_REPAIR_SOURCE_ARTIFACT_PATH` 和
`PHASE2B_REPAIR_SOURCE_ARTIFACT_PATH`。Phase2a repair 读取失败/降级 Phase2a
artifact 的 checkpoint，按本轮 Scene commit 结果 remap 旧/新 Scene ID，先 hydrate
source `world_snapshot`，再只重跑失败或未完成 Scene，并写入新的
`phase2a_real_llm_<timestamp>.artifact.json`，不覆盖旧 artifact。Phase2b repair
同样 remap `alias_relation_checkpoints`，优先 hydrate source Phase2b
`world_snapshot` 以保留已成功的别名/关系，再只重跑失败或未完成 Scene，并写入新的
`phase2b_real_llm_<timestamp>.artifact.json`。

Phase2b 稳定性可通过 `PHASE2_ALIAS_RELATION_TOTAL_TIMEOUT_SECONDS`、
`PHASE2_ALIAS_RELATION_LLM_TIMEOUT_SECONDS`、
`PHASE2_ALIAS_RELATION_SCENE_CHAR_LIMIT`、
`PHASE2_ALIAS_RELATION_ENTITY_INDEX_CHAR_LIMIT` 和
`PHASE2_ALIAS_RELATION_ENTITY_INDEX_FALLBACK_LIMIT` 调整。Phase3 深度导入模式使用
紧凑结构 prompt：不生成新 Scene，以少量剧情线/篇章纲/伏笔/揭示作为稳定基线。
