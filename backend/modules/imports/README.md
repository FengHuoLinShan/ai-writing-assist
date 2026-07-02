# Module: imports / 小说文件导入模块

## 定位

imports 模块负责小说文件的导入与解析。它不是一个独立的创作模块，而是将外部小说文件转换为系统内部章节正文的通道。
同时，imports 负责深度导入的工作流编排：把已导入章节交给 Scene 切分、实体抽取和结构分析三个阶段执行。

## 负责

- 上传并解析 txt / epub / html / mobi / azw3 格式的小说文件
- 自动检测文本编码
- 按章节模式（第X章、Chapter X、卷X 等）自动分章
- 将解析结果写入 writing_drafts（每章一个 draft）
- 记录导入历史
- 提交并编排深度导入任务（基于 async_tasks）
- 提交并编排分阶段自动提取任务：Scene、世界对象与别名/关系、剧情结构
- 在重复导入时返回覆盖确认要求，确认后才入队
- 深度导入 Scene 阶段执行 Phase 0 双轮预取、Phase 1a 正文补强、Phase 1b 融合提交，并记录质量统计
- Phase 0 / Phase 1a 是 workflow 中间候选层，不写正式 Scene；真实 LLM 验收会持久化 JSONL / Markdown / artifact 作为测试证据，供复跑和失败 batch repair
- Phase 1a 默认作为受控正文补强器：输入正文按预算收敛，输出短候选锚点；最终仍失败的非 422 LLM 错误会生成 `degraded_fallback` 低质量中间候选，保留每章锚点给 Phase 1b 融合
- 深度导入保持自动流水线，不弹出“AI 参考资料”确认；Phase 3 结构分析显式使用 `context_mode="working"` 并包含待确认对象
- 分阶段世界对象自动提取执行 Phase 2a / 2b：先基于已提交 Scene 抽取世界对象与 Delta，再补抽别名 / 关系
- Phase 2 对大量 Scene 使用 batch 间并发、batch 内 Scene 串行的调度：默认 12 Scene / batch、6 batch 并发；真实 LLM 调参可用 `PHASE2_BATCH_SIZE_SCENES` / `PHASE2_BATCH_CONCURRENCY` 临时覆盖；每个 batch 保留局部 rolling context
- Phase 2 只对相邻 batch 边界执行补充抽取：前批最后 2 个 Scene + 后批最前 2 个 Scene；不做全局对象融合扫描
- Phase 2 入库前通过 world facade 使用名称 / 别名 / embedding 去重能力，并在 progress/result 中记录 action、dedup、boundary supplement 和 degraded 统计
- 深度导入 Phase 2 拆为 Phase 2a 世界对象/Delta 抽取与 Phase 2b 别名/关系提取；Phase 2b 失败只降级，不丢弃已抽取对象
- 深度导入 Phase 2/Phase 3 的真实 LLM 调用通过 `modules.context.facade` 写入 `context_snapshots` 审计记录

## 不负责

- 直接实现世界对象、记忆或大纲的业务规则
- 绕过各模块 facade 直接写跨模块内部模型
- 直接 import context 模块内部的 models / repositories / services
- 文本改写或格式转换导出

## 数据表

- import_records：导入操作记录（元信息，不存正文）
- async_tasks：深度导入任务载体，运行中写入 progress/result 供前端轮询

`context_snapshots` 由 context 模块拥有。imports 只通过 facade 创建、标记成功/失败和回写 result refs，不直接访问 context 内部表或 repository。

## 跨模块依赖

- writing.facade.create_draft — 写入解析后的章节正文
- outline facade / DI handler — 深度导入 Phase 1/3
- world facade / DI handler — 深度导入 Phase 2a 对象抽取、Phase 2b 别名/关系提取
- context.facade — Phase 2/3 LLM 调用上下文快照审计
- memory.facade.capture_snapshot — Phase 2 后记录记忆快照

## 上下文快照边界

- Phase 2 保持当前 handcrafted prompt/context 构造，不重接 context compiler；Phase 2a 快照记录实体抽取上下文，Phase 2b 快照记录别名/关系提取的对象索引与 Scene 摘要，二者都回写 result refs。
- Phase 3 结构分析由深度导入调用时传入 `workflow_id` / `task_id` 并开启 `audit_context_snapshot=True`；手动 AI 操作默认不创建 snapshot。
- Phase 3 快照使用 `context_mode="working"` 和 `include_pending_objects=true`，记录结构上下文的 section/token metadata。若当前编译结果未暴露完整 asset ids，只记录可见资产并在 metadata 中说明。
- 默认不保存完整 rendered context；调用方显式开启保留时才落库，并由 context 模块按保留策略清理。

## 快照健康摘要兼容

深度导入任务结果现在优先返回 `snapshot_health_summary`，用于展示快照数量、状态分布、超时 running、保留 full context 数和最近失败摘要。

`audit_summary` 暂时保留为兼容 alias，旧前端或旧测试仍可读取；新代码应优先读取 `snapshot_health_summary`，再回退到 `audit_summary`。前端只展示“快照健康摘要 / 快照状态”的轻量信息，不新增审计工作台。

快照维护入口由 context 模块提供：`POST /api/context/snapshots/maintenance`，默认 `dry_run=true`，imports 不直接访问 `context_snapshots` 表。

## 深度导入恢复语义

worker 启动时会检测 stale 的 `deep_import` 任务并标记为需要恢复，但不会自动继续。
前端通过 `GET /api/tasks/{task_id}` 展示 `recovery_required` / `recovery_summary`，
用户点击继续后调用 `POST /api/imports/deep/resume` 复用原 task；放弃恢复调用
`POST /api/imports/deep/abandon`，只清理同 `workflow_id` 的自动派生 Scene、实体和结构资产。
Phase 0 / Phase 1a 的最终 422 错误率超过 40% 时阻断任务；Phase 1a 的
network / rate_limit / empty_result 可短重试，最终仍失败的 timeout / schema 等非 422
错误会降级为 `degraded_fallback` 中间候选继续推进；Phase 1b 超阈值时降级继续。

## 深度导入内部结构

`DeepImportOrchestrator` 负责重复导入策略、任务提交、恢复和放弃清理；
`DeepImportWorkflow` 只保留 worker 执行入口和兼容 wrapper。阶段实现拆在同模块内部：

- `workflow_scene_phase.py` — Phase 0 / Phase 1a / Phase 1b / Scene commit
- `workflow_entity_phase.py` — Phase 2a / Phase 2b 与 world_objects stage
- `workflow_structure_phase.py` — Phase 3、plot_structure stage 与小样本结构保底
- `workflow_progress.py` — progress timeline、诊断计数、checkpoint/audit/snapshot summary 合并
- `workflow_llm_adapters.py` — 深度导入 LLM adapter、Phase 0/1a/1b prompt 和 token 预算控制
- `scene_reinforcement.py` — Phase 1a 正文补强、compact payload、短候选 normalize 和 degraded fallback
- `deep_import_retry.py` — 深度导入 LLM 错误分类与阶段可控 retry 策略
- `agent_step_harness.py` — imports 内部受控 LLM step envelope / journal / 输出守门；由 `workflow_llm_adapters.py` 使用，不提供自治 agent loop 或工具自主选择
- `agent_text_tools.py` — imports 内部只读正文 Search/Read 工具 adapter，复用 RAG 检索和 writing draft 权威正文

这些文件不改变 async task result shape、HTTP API、数据库 schema 或前端轮询字段。

## 真实 LLM 验收与 artifact

真实 LLM 验收入口默认跳过，只在显式环境变量开启时运行：

```bash
RUN_DEEP_IMPORT_60_PHASE0_REAL_LLM=1 LLM_TIMEOUT=180 \
  PHASE01_SCENE_MAX_TOKENS=8192 pytest modules/imports/tests/test_deep_import_real_llm.py -q -s

RUN_DEEP_IMPORT_60_PHASE1A_REAL_LLM=1 LLM_TIMEOUT=180 \
  PHASE1A_SCENE_MAX_TOKENS=6144 pytest modules/imports/tests/test_deep_import_real_llm.py -q -s
```

Phase 0 / Phase 1a 验收会写入 `.test-logs/deep_import_real_llm/` 下的
JSONL、Markdown summary 和 `.artifact.json`，同时创建 test-only `AsyncTask`
结果映射，确保分阶段结果有对应 `Project` / `task_id` 可追踪。artifact 是测试/验收证据，
不是业务表；repair 会按 batch key 合并新旧结果，避免少量 provider 波动导致整轮
60 章作废。Phase 1a-only 默认会自动使用最近一个完整通过的 Phase 0 artifact；
需要复核旧结果或指定输入时，可用 `PHASE1A_PHASE0_ARTIFACT_PATH` 显式覆盖。后续
phase-only 真实验收入口也应默认消费上一个 phase 已通过的 artifact。
常用 repair 环境变量：

- `PHASE0_REPAIR_SOURCE_ARTIFACT_PATH`
- `PHASE0_REPAIR_MAX_FAILED_BATCHES`
- `PHASE0_REPAIR_CONCURRENCY`
- `PHASE0_REPAIR_ATTEMPTS`
- `PHASE1A_REPAIR_SOURCE_ARTIFACT_PATH`
- `PHASE1A_REPAIR_MAX_FAILED_BATCHES`
- `PHASE1A_REPAIR_ATTEMPTS`
- `PHASE1A_REPAIR_BATCH_IDS`

Phase 2 的 Scene 实体抽取由 `SceneEntityExtractionService` 保持对外入口和旧私有
wrapper，内部策略拆在同模块内部：

- `scene_entity_single_scene.py` — 单 Scene 串行 Phase 2a
- `scene_entity_parallel.py` — 小样本并发抽取与 bulk 失败 fallback
- `scene_entity_bulk.py` — bulk 抽取、小样本 LLM supplement 与 fallback 候选
- `scene_entity_alias_relation.py` — Phase 2b 别名/关系抽取
- `scene_entity_persistence.py` — entity / alias / relation / delta / map observation 写入
- `scene_entity_text.py`、`scene_entity_snapshots.py`、`scene_entity_llm_adapters.py`
  — Scene 正文、context snapshot、LLM adapter 支撑逻辑
- `scene_entity_checkpoint.py`、`scene_entity_config.py` — checkpoint、错误分类和 Phase 2 常量

这些拆分不改变 `extract_by_scenes()` / `extract_alias_relations()` 返回字段、
checkpoint shape、snapshot/audit summary、LLM prompt 或 timeout 语义。

## Facade

```python
async def import_file(db, novel_id, file_name, file_content) -> ImportResponse:
    """导入小说文件"""

async def start_deep_import(db, novel_id, start_chapter, end_chapter, force=False) -> dict:
    """提交深度导入任务；重复导入时先返回 requires_confirmation"""

async def start_deep_import_stage(db, novel_id, start_chapter, end_chapter, *, stage, force=False) -> dict:
    """提交分阶段自动提取任务：scenes / world_objects / plot_structure"""
```

## API

```http
POST /api/imports/upload      — 上传文件（multipart multipart）
GET  /api/imports             — 导入记录列表
GET  /api/imports/{id}        — 导入记录详情
POST /api/imports/deep        — 提交深度导入任务；重复导入时先返回 requires_confirmation
POST /api/imports/stages/scenes — 提交场景（scene）自动提取任务，只执行 Phase 0/1a/1b + Scene commit
POST /api/imports/stages/world-objects — 提交世界对象与别名/关系自动提取任务，只执行 Phase 2a/2b
POST /api/imports/stages/plot-structure — 提交剧情线自动提取任务，只执行 Phase 3
POST /api/imports/deep/sync   — 同步执行深度导入（测试/无 worker 场景）
POST /api/imports/deep/resume — 用户确认后继续可恢复的原 deep_import task
POST /api/imports/deep/abandon — 放弃恢复并清理同 workflow 自动派生资产
```

## 安全约束

- 文件类型白名单：txt, epub, html, htm, mobi, azw3
- 文件大小上限：50MB
- 文件名 sanitize：防止路径穿越
- 不保存上传文件到可执行目录，解析后即释放

## 测试

```bash
pytest modules/imports/tests/
```
