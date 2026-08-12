# Module: imports / 小说导入模块（原设计以外新增）

## 定位

imports 模块负责将本地小说文件解析并导入系统，创建 WritingDraft 记录以供后续实体抽取和创作使用。它也负责深度导入的工作流编排，但各阶段的具体业务写入仍通过对应模块的公开接口完成。

## 数据表

- `import_records` — file_name / file_type / file_size / total_chapters / imported_chapters / status / error_message
- `imported_chapters` — 仍是活跃的章节正文表并被 world 事件/关系/版本来源 FK 引用；当前上传主路径把章节写为 `writing_drafts`，不把它当作第二个编辑入口
- `import_workflow_runs` — 项目级活动 workflow、generation、task/attempt/lease owner、
  授权与 LLM snapshot、恢复 checkpoint；它是可恢复领域状态，不由 `async_tasks` 代替

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
`Phase 0 deterministic plan → Phase 1a scene slicing → Phase 1b scene enrichment → Phase 1c scene fusion → Scene commit`。
旧 `scene_prefetch` / `scene_reinforcement` legacy pipeline 已删除；
Phase 1c 仅在 `high_quality=true` 时运行：先按窗口批量审阅完整候选序列的相邻边界，再对高置信、来源精确、无不确定性的同一 Scene 连通组单独综合；其余进入通用融合建议队列。
`workflow.py` 不再保留旧 prefetch / reinforcement / single-chapter fallback / fusion wrapper；
默认路径只通过 `workflow_scene_phase.py` 调用 plan / slicing / enrichment / fusion / commit seam。
`workflow.py` 仅保留 `DeepImportWorkflowRuntime` 要求的活跃 phase runner seam；
非 runtime seam 的薄包装/死代码已清理，PhaseRunner DI 大重构不属于本次变更。

### Phase 0: deterministic plan
- 不调用 LLM；按章节字符数生成窗口计划、owned range、右侧 overlap 和每窗 token 预算。
- 计划结果决定 Phase 1a 的输入范围和 `max_tokens`，避免由模型自行决定 batch 边界。
- Phase 0 不写正式 `scenes` 表，也不执行 LLM health 或 422 门禁。

### Phase 1a: scene slicing
- 切分并锁定 Scene 语义字段，同时要求 LLM 从正文逐字复制
  起止 anchor；本地 materializer 负责唯一命中、chapter-local offset、
  draft/content hash 绑定和邻接/整章覆盖推断。
- `scene_chunks` 不由 LLM 自由填 offset；锚点未解析时使用统一
  reasoning 策略的小上下文 repair，连续覆盖缺口按整段恢复，仍失败才保留
  `needs_review` 的章节级语义 fallback。精确 span 重叠会先要求模型按本地诊断纠正；
  仍重叠时隔离整个受影响章节范围再恢复，不能把重叠候选传入后续阶段。
- 覆盖按实际源草稿 offset 判断，不以“章节出现在某个 Scene 的 chapter_ids 中”代替。
  相邻精确 span 之间若遗留实质正文，会得到一次携带原文与 offset 的语义纠正；纯空白、
  分隔符和标点由本地确定性吸收。纠正后仍未归属的文字保存为精确 gap fallback 并强制复核，
  因而既不会丢正文，也不会伪装成正常 Scene。

### Phase 1b: scene enrichment
- 每个 Scene 一个 enrichment 请求，只提炼供修订、续写和一致性检查使用的执行信息，
  不允许改写 Phase 1a 锁定的语义或 `scene_chunks`。
- 本地先按全部 chunks 验证 draft/hash/offset 并物化完整 Scene 正文；不发送混有相邻
  Scene 的整章正文，不做输入截断、摘要或采样。请求复用冻结 Phase 1a context，合并
  相邻 Scene、活跃剧情线/篇章纲/已有 Scene、人物 Top-6 和非人物对象 Top-16，并记录
  context/source fingerprint。
- `emotional_beat / must_happen / must_not_happen` 可以明确不适用并保持空值；
  `uncertain_fields`、来源完整性和 Phase 1a 状态由本地映射为复核。provider 或来源校验
  失败时保持空字段和 `narrative_tag=draft`，不制造占位语义。
- enrichment 默认 `max_tokens=32768`，不再使用旧 4096 上限；
  该值与其他结构化阶段使用同一预算策略，并在任务提交时
  物化进 `llm_execution_snapshot.deep_import`。项目保存的
  `phase1b.enrich_max_tokens` 会先传入 enricher payload，adapter 不再用
  env/default 值遮蔽项目配置。
- 单 Scene enrichment 失败只影响当前 Scene：重试后仍失败则 fallback 并进入人工复核清单。
- `valley`、`transition` 是合法叙事标签，不再作为 Phase 2 跳过 Scene 的依据；导入来源
  由 `source=deep_import` 表达，不能复用 `narrative_tag`。

### Phase 1c: scene fusion
- 仅 `high_quality=true` 运行；普通导入记录 `skipped/high_quality_required`。
- 默认自动融合阈值为 `0.92`，所有成员必须有精确 offset、draft/source hash，不得带 fallback、候选内部 concern 或边界 uncertainty。
- 边界 review 输出 `same_scene / duplicate / overlap / separate / uncertain` 与可选吸收方向；同章多 Scene 合法，标题相同不构成自动融合依据。
- 自动候选组必须再经过 `SceneFusionSynthesisOutputContract` 综合语义；不得拼接成员字段或制造伪冲突。低置信 synthesis、冲突或调用失败保持来源分离并生成建议。
- 高置信精确 `separate` 保存为隐藏 dismissed 决策；其他建议与 Scene commit 同事务持久化。pending、dismissed、adopted 决定由 Scene 工作台独占处理，项目级 Scene 去重仅在来源变化后重新扫描。

### Scene commit
- Phase 1a / 1b / 1c 都是 workflow 中间层；正式 Scene 只在 Scene commit 后写入。
- 正式 Scene 写入携带 provenance / workflow / auto_ingested 信息；恢复或重跑时按 provenance 跳过已提交结果。无复核标记的结果计为已采用，`needs_review` 结果进入待处理汇总。
- Scene commit 校验全部精确 span；残留的跨 Scene 重叠会令本次提交整体失败。带冻结
  draft/hash 的阶段还会读取 Writing 稳定契约，验证所选各章从 offset 0 到正文结尾无空洞、
  无 hash 漂移。覆盖替换以提交后的 active Scene 联合验证，因此受保护 Scene 可承担其原有
  span；失败仍在同一事务回滚，不产生部分写入。
- 提交不再补造 `core_conflict / must_happen / must_not_happen`。显式 `not_applicable` 的空字段是完整语义；缺状态或 `uncertain` 的空字段继续进入健康复核。

### Phase 2a / 2b: 世界对象、Delta、别名与关系（40%）
- Phase 2a 基于已提交 Scene 抽取长期世界对象、持久 Delta 与不确定项；不输出关系或新别名。
- Phase 2 Scene 实体抽取实现位于 `entity_extraction/` 子包；`modules.imports.entity_extraction` 是稳定公共导出入口，旧顶层 `scene_entity_extraction.py` 兼容 hub 已删除。
- Phase 2a 路由选择集中在 `entity_extraction/scene_entity_strategy.py`，只决定 empty、small-sample parallel、bulk、batched 或 checkpoint resume；LLM 调用、persistence、checkpoint、prompt、timeout 和返回契约仍由子包内执行模块负责。
- Phase 2b 复用 Phase 2a 的完整精确 Scene activation，并加入冻结的既有对象与关系引用，补抽别名和关系连续性；这是关系/新别名的唯一 LLM 阶段。它不裁剪输入，失败只降级，不丢弃已抽取对象。
- 大量 Scene 在 Phase 2a 以 Scene 为并发单元调用 LLM，再按 `scene_index`
  串行持久化；每个请求包含当前 Scene 完整精确正文、锁定 Scene 卡、相关 active
  working 大纲、服务端身份候选和前序证据，不带后续 Scene。直接提及候选全部保留，
  其余人物 Top-6、非人物对象 Top-16；不对 Phase 2a 输入做字符/token 裁剪。
- 只对相邻 batch 边界执行补充抽取，不做全局对象融合扫描。
- 入库前通过 world facade 使用名称 / 别名 / embedding 去重能力；
  高置信重复实体只记录建议目标并进入待处理，不自动融合到
  已有对象；重复关系走 create-or-merge。
- Phase 2 的真实 LLM 调用通过 context facade 写入 `context_snapshots`，并在任务结果中记录 snapshot health、dedup、boundary supplement 和 degraded 统计。

### Phase 3: 结构分析（单次，20%）
- 输入：全量 Scene 摘要 + 坍缩后 Delta 变更流 + 实体索引
- LLM 输出：plot_threads / outline_arcs / foreshadowing_plans / reveal_plans
- 四类产物分别写入对应表
- 深度导入模式显式使用 `context_mode="working"` 并包含待处理对象；context 会给结果加“包含未采用内容”警告。
- 完成后会通过 outline facade 生成结构去重建议；仅自动应用同一 deep import workflow 内的高置信重复，跨已有资产的建议只写入任务结果。

### 进度状态

由 `DeepImportProgress` Schema 定义，并写入 `async_tasks.result`。完整深度导入
保留 Scene / Entity / Structure 的全流水线区间；独立 Scene stage 的
`async_tasks.progress` 则按实测耗时估算。完整深度导入中 Phase 1b 推进到 `30%`，Phase 1c 为 `30–35%`，Scene commit/建议写入为 `35–40%`；独立 Scene stage 在 Phase 1c/commit 收敛到 100%。阶段内按 window / Scene 已完成单元线性推进：
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
- llm_execution_snapshot：提交时冻结的 secret-free effective project
  profile/deep-import 设置；不包含 Key、完整 URL/query 或 extra values
- asset_summary：互斥的 `adopted / review / not_adopted` 总数及 Scene、实体、关系、别名、结构分项

主 task 从持久化的 `llm_execution_snapshot` 恢复当前 provider Key。非 task 的内部兼容
调用也先临时构建 secret-free snapshot，再经 project runtime 恢复；通用
`ProjectContext.settings` 只承载项目拥有的非 secret 设置，不再作为 LLM 凭据来源。

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
POST /api/imports/upload                    # 上传并导入；201 表示导入记录、章节工作稿和发布任务已提交，可立即读取
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

上传成功的可见性来自 `DbSession` 的 request-owned transaction：function-scope dependency 在普通非流式响应开始前统一提交，上传路由本身不持有单独的成功提交逻辑。

`/deep` 与三个 `/stages/*` 请求都必须显式发送
`authorization_confirmed=true`；缺失或 false 返回 422 且不排队。任务 meta 和 result 都保存
同一授权快照，完成页从 result 的 `asset_summary` 展示已采用/待处理/未采用。
新任务还会在排队前把 `llm_execution_snapshot` 写入 meta 和初始
result；worker 继续使用提交时的 model/非 secret 参数与字段来源，
以及已物化的 deep-import 项目/env/default 设置；允许 Key 轮换，
但 endpoint/extra 漂移会 fail closed。

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
- 放弃可恢复 workflow 通过各领域 facade 整批软回滚：outline/world 资产废弃、Memory DeltaLog 标记 `rolled_back`；所有操作按 novel/workflow 隔离并保留来源审计

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
persistence` 单一路径。默认 LLM 并发 25，provider/LLM 超时为 240/270 秒，
结构化输出上限 32768；单波出现 429，或至少两个连接/超时失败时逐波减半降载，
schema、partial-list 等格式诊断不参与降载。工作流的 `end_chapter` 作为可见硬截止，
跨章 Scene 只装载截止章/offset 以前的精确 span。checkpoint 记录 activation
version、Prompt contract version、来源数量和包含完整上下文的输入指纹。`import-context-v2` 不把输入预算用于裁剪
Scene 正文；身份只能引用 `entity-xxx`，逐字证据、引用存在性与类型一致性由确定性
materializer 校验；可见 SceneSpan 不精确或覆盖不完整时不发送部分正文。模型输出不包含持久化动作或审核状态，provider 调用期间不持有数据库事务。Phase 2b
在其后执行全局别名/关系 reconciliation，不回写早期 Scene 的可见性语义。DeepSeek 下 Phase 2a/2b 普通模式使用 `high` reasoning，高质量模式使用 `max`；Phase 2b 单调用默认超时 120 秒，高质量模式有效超时翻倍。
阶段内自动修复只重跑首轮失败 Scene ID；即使首轮新增 working 世界对象使上下文指纹变化，也不会重放已完成 Scene。修复 checkpoint 按 Scene ID 合并，不能用小范围修复结果覆盖整轮 checkpoint。

Phase 1/2/3 的活跃 adapter 都使用上述冻结 project settings。
`high_quality=true` 只开启最大 reasoning 和 Phase 1c，不改写项目手动选择的 request model；context snapshot/managed provenance 记录实际
request model，不只记录 profile 默认模型。

Scene 提取统一使用 Phase 0/1a/1b 主链，高质量模式追加 Phase 1c；旧的批次切分、
单章 LLM 恢复和直接写 Scene 服务不再保留。

Phase 3 复用 outline 的全书 Scene 摘要且不默认加载全书正文，追加 derived world
background。空结构、无结构引用和无有效篇章范围会触发一次同 workflow 的 draft/candidate
结构资产 replacement rerun；所有门禁与降级摘要保持在 task result 的加性诊断字段中。
Phase 3 的单次结构化请求使用项目可配置的
`phase3.structure_max_tokens`（默认 32768），该值会进入任务冻结
快照，不再根据 prompt 长度做 token 阶梯扩容；replacement rerun 是业务
输出门禁，不是用更大 `max_tokens` 重放同一请求。
