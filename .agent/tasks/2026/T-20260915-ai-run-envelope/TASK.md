---
id: T-20260915-ai-run-envelope
title: 统一 AI 运行信封
status: active
created: 2026-09-15T10:42:18+08:00
updated: 2026-09-15T12:19:34+08:00
parent: .agent/tasks/agent-integration.md
---

# 统一 AI 运行信封实施计划

## 恢复快照

- 实际完成：Wave 0 只读冻结与 W0-B 第二轮重新冻结完成（三份 artifacts）；Wave 1 核心契约与
  S2.1 契约修正已完成并通过定向与全量 fast 层门禁；Wave 2 三路已从 `badac2db4` 启动。
- 当前里程碑：M0、M1 完成；M2 进行中（Wave 2 三路并行）。
- 下一步：等待 W2-Text / W2-Agent / W2-Task 各自完成后逐路审查、集成并复跑回归；集成点之后才
  进入 Wave 3。
- 阻塞：无硬阻塞。需要用户确认的决策点是 W0-B 发现的"无有限上界能力"（imports 各阶段、
  writing.generate、world.entity_fusion 等）迁移前必须先冻结的领域上界口径；真实 provider 验收仍需
  另行取得费用与凭据授权。
- 工作区：实现 worktree `.worktrees/ai-run-envelope`，主题分支 `codex/ai-run-envelope`，从计划
  提交 `81ef210e8` 创建；该提交等于 `origin/main 5a2524dae` 加一个仅含本 TASK 与
  `.agent/TASKS.md` 的文档提交，因此代码基线与 `origin/main` 完全一致。
- 最后核实：2026-09-15T12:19:34+08:00。

## 目标与验收

- 目标与交付物：复用现有 `CAPABILITY_REGISTRY`、`managed_llm_steps`、`WorkflowBudget`、
  `AgentRunBudget`、项目 execution snapshot、AsyncTask lease/receipt 和 Map possible-charge 语义，
  为所有用户可见 AI 文本、structured、stream、Agent、research 和图片请求建立一个版本化运行信封。
- 完成条件：
  - 每个 provider 请求都能关联唯一 `operation_id`、累计运行账本 `run_id`、canonical
    `root_capability_id`、step、task attempt（如有）和冻结模型 profile hash。
  - transport、structured、format、semantic、Agent follow-up 与 task requeue 全部消费同一 run 的
    request limit 和 deadline；自动重试、恢复或 worker 重排不得重置累计值。
  - 成功、失败、取消、中断、缺失 usage 和可能已扣费均产生脱敏回执；未知用量不得写成零。
  - 新 project-scoped provider 调用缺少活动信封时在发出请求前失败关闭；既有 v0 回执和旧在途任务
    可兼容读取，不回填历史、不改变已有 task/operation ID。
  - 通用 task API 不公开内部运行信封；领域已有公开状态、确认、采用、CAS、stale、partial result、
    图片重试确认和恢复语义保持不变。
  - 当前生产调用清单重新扫描后无未绑定旁路；代表性 Writing structured、Interaction
    Agent/stream、Assistant research、Map image 及 task auto-requeue 路径通过自动化验收。
  - 适用定向测试、PostgreSQL worker/requeue 测试、Prompt/capability 门禁、完整 `make test-ci`、
    docs-check 与 diff 检查通过；真实 provider 验收仅在另行取得费用/凭据授权后运行和声明。
- 非目标：
  - 不新建 LLM Client、第二 capability registry、第二 retry manager、全局 Agent 平台、
    AuditEvent 表、数据库列/migration、OpenTelemetry 或新的依赖。
  - 不把知识 Review、artifact refs、采用、回滚或跨域 stale 生命周期塞入运行回执；只用 `run_id`
    与各领域现有回执关联。
  - 首轮不纳入 embedding、本地 BGE、健康检查、账户连接验证、离线 eval CLI 或历史数据回填；
    它们作为显式 infrastructure exemption 记录，避免被静态门禁误当成遗漏。
  - 不统一业务 Prompt 内容、领域 semantic retry 算法、Map 图片补偿、RP 故事树或 Imports checkpoint。

## 上下文与边界

- 权威依据：ADR-0023 保留有界 Agent、累计预算与恢复不重置；ADR-0025 保留 canonical capability、
  确定性 step 和现有 JSON 回执，不新增运行时或事实库。
- 当前事实：`CAPABILITY_REGISTRY` 有 46 项（41 项业务能力、5 项 infrastructure）；
  `managed_llm_steps` 只冻结 step/profile 五类摘要，不能解释每层 provider request、总预算或扣费状态。
- 当前调用盲区：文件级 `CAPABILITY_BINDINGS` 不证明具体调用身份；`.generate`、`.research` 和图片
  generate/edit 未被可靠扫描，且 Interaction summary、Writing targeted revision、World design
  iteration、Imports 若干阶段存在文件绑定缺项或错位。
- 当前计量盲区：`LLMClient.generate_structured()` 在关闭 transport retry 和 format repair 时存在
  直接 provider 路径，绕过 `WorkflowBudget`；stream、research、图片尚无同形 run receipt。
- 当前 task 缺口：特殊 transient requeue 计算了 failure result/provenance 却没有持久化；真实
  `enqueue_task()` 冻结 `auto_requeue` 后，带 `retry_transient_llm_errors` 的非 transient LLM
  错误仍可能被通用 handler-error 分支重排，现有直接构造 AsyncTask 的测试没有覆盖该事实。
- 安全边界：信封不得包含 API Key、Prompt/响应正文、provider raw payload、完整 endpoint、隐藏
  reasoning、私人来源文本或用户输入；只保留 allowlist 字段、稳定 ID、计数、哈希和安全错误类型。
- 架构边界：infrastructure 不反向 import Evidence 实现；业务侧和静态门禁校验 capability registry
  membership，基础设施只校验格式、活动 scope 和同一 run 内身份不漂移。

## Wave 0 冻结结论（2026-09-15，只读）

- W0-A 调用清单（完整报告：`artifacts/wave0-a-call-inventory.md`）：`backend/modules` 生产路径有
  42 个受管入口调用点与 14 个裸 client 调用点。16 个调用点当前"不可见或绑定错误"：
  `writing.targeted_revision`、`interaction.summary_refresh`、`world.generation.design_iteration`、
  `imports.scene_enrichment`、`imports.scene_fusion`、`world.alias_relations.extract`，
  `evidence/compilation/knowledge/workflow.py` 整文件误挂 `infrastructure.format_repair`，
  `story/outline_state/generation/parser.py` 误挂 `story.outline.p20`，以及 5 个不被门禁标记识别的
  调用点（`assistant/evidence_tools.py:362`、`interaction/agent_runtime.py:313` 的 research、
  `map_atlas_workflow.py:1843/1857` 的图片 edit/generate、`world_generation_center_service.py:660`
  的自由问答）。注册表 46 项中 3 项从未绑定：`writing.targeted_revision`、`story.one_click`、
  `infrastructure.embedding`；`selection_proposal.py` 的 `infrastructure.rag_query_planner` 归属待复核。
- W0-C 身份与恢复（完整报告：`artifacts/wave0-c-identity-recovery.md`）：operation/run/task 在
  Assistant 与 Imports 上恒等（`operation_id == AssistantRun.id == task.id`；Imports
  `run.id == task_id`），在 Interaction 与 Map 上 run 稳定而 task 换行；Imports 的第二次尝试
  计数在领域列 `generation`，Map 靠 `run.task_id != task.id` 判定换 attempt，`AsyncTask.attempt`
  不足以表达跨 task 的运行进度。
- W0-C 关键风险与归属：把 `_ai_run_envelope` 写进 task.result 会打断 Story Outline 采用，因为
  域内采用走 `get_completed_payload`（`infrastructure/tasks/lifecycle.py:394-405`，原样返回含
  `_` 键的 result），而 `story_outline_service.py:248-259` 用 exact-key allowlist 判 forbidden。
  归属 W2-Task（过滤私有键）或 W3-A（扩 allowlist），二者必须完成一处。
- W0-C 其它硬约束：worker 成功路径整体替换 task.result，checkpoint 写入的 envelope 必须像
  `managed_llm_steps` 一样显式并入 result；lease 丢失时没有终态写入路径；`managed_llm_steps`
  现在就在公开 wire 上，前端 Story Outline 对顶层键做 exact-key 校验，因此"顶层只允许
  `managed_llm_steps` 一个非下划线兼容键、其余运行态一律下划线私有"是既有约束而非新增选择。
- W0-B 重新冻结（第二轮，2026-09-15）：第一轮报告把**默认值当合法最大值**，已按"C1 编译期常量
  上界 / C2 本次冻结工作量可算 / C3 运行期才知规模需分批授权"三分类重写，共 13 条修正。主 Agent 抽查
  5 处证据全部复现：`modules/world/schemas.py:3216`（max_packets le=256）、`schemas.py:1715`
  （max_suggestions le=200）、`map_structure_schemas.py:279-290`（location+feature 合计 ≤20）、
  `map_structure_workflow.py:687`（max_fix_attempts=1）、`entity_fusion.py:426-427`
  （深导入 max_suggestions=10_000）。关键修正：`world.map_structure.generate` **60**、
  `world.validation` **1536**（A=6P，P≤256）、`world.entity_fusion` 交互 **2400** / 深导入 **180000**
  （不可直接授权，必须分批且不得进入常规 L0）、`world.generation.suggestion` 同步 API **192**
  （原为算术错 144）、`story.structure_dedup` 复算 **870**（原 3200 无法复现）。
  `writing.generate`（6⌈K/64⌉+8）与 `world.alias_relations.extract`（4S）等执行前已冻结工作量的
  能力记为 C2 动态公式，不要求新增产品输入限制。
- W0-B 仍存疑（artifact 第 6 节 6 项），迁移前必须由领域确认的主要一项：`story.structure_dedup` 的
  `smart_dedup_scan.max_suggestions` 是未校验 int（`modules/project/tasks.py:51`），A 随它线性增长。
- W0-B 预算/retry/扣费（完整报告：`artifacts/wave0-b-budget-retry.md`）：transport 尝试次数不是
  全局常量——`infrastructure/tasks/worker.py:591-593` 按 task 的 `retry_transient_llm_errors` 在每次
  handler 执行前把 transport retry 置为 1 次；writing/story/world 系结构化调用实际 R=1、重试改由任务层
  整链重放（×2），其余路径 R=3，公式不带此分叉会整体高估 3 倍。请求上界的瓶颈在数据规模而非 provider
  层：`writing.generate` 随确认来源数 K，`imports.scene_slicing/enrichment/fusion/entity_extraction/
  structure_analysis/targeted_completion` 随 Scene 数 S 与复核批次数 B，`world.alias_relations.extract`
  与 `world.map_structure.generate` 随所选范围，均无代码级常量上界；单点最大值是 `world.entity_fusion`
  深导入路径的 180000 次（`entity_fusion.py:422-432,650`）。按计划这些能力必须先补领域上界才能迁移，
  口径需要用户确认。另有 `imports.scene_plan` 实际 0 次 provider 请求（确定性规划）。
- W0-B 计量旁路（Wave 2 必须覆盖）：① 关闭 transport retries 时 `generate_structured` 直连
  `self._provider.generate` 跳过 meter（`client.py:736-742,980-986`）；② `generate_stream` 完全不查
  `current_workflow_budget()`（`client.py:630-665`）；③ `research` 与远程 `generate_embedding` 不计
  （`client.py:667-683,1134-1144`）；④ `AgentRunBudget` 与 `WorkflowBudget` 无互斥，理论上同一请求会
  记 2 次（`agent_runtime.py:317` 与 `client.py:614-626`），当前 4 个 `run_project_agent` 调用点不在
  budget 上下文内故不可达，但 Wave 2 需要显式保护。
- W0-B 既有语义：文本 LLM 全链路没有 possible_charge 概念，`managed_llm_steps` 无 token 计数且按
  identity 去重，不能当账本；唯一有"可能已扣费"语义的是 Map 图片（页级 CAS →
  `retry_requires_confirmation` → `confirm_possible_duplicate_charge` → 补偿删除）。信封的
  `charge_state=possible` 必须与该既有语义对齐。
- 方法教训：Wave 0 与 Wave 1 曾并发读写同一 worktree，只读结论的行号按基线 `5a2524dae` 使用；
  后续只读核查必须记录读取时的 blob SHA。

## S2.1 契约修正（2026-09-15）

- 并发顺序：所有公开变更经 `_serialized` 在同一 `asyncio.Lock` 内完成"计数变更 +
  `on_change` checkpoint"，持久化顺序与变更顺序一致，旧快照不会后写覆盖新状态；回调
  不得重入同一账本（会自锁）。
- 信封边界：profile 摘要改由 `schemas.sanitize_profile_summary()` 按 allowlist 重建（从 harness
  移入契约层，v0/v1 共用同一函数与同一名单），白名单外的 `api_key`、`base_url`、Prompt、正文等
  一律丢弃；`profile_hash` 不再由调用方提供，改由净化后的摘要派生，v0 与 v1 身份函数统一。
- 终态一致性：`finish()` 写入终态前先把未 settle 请求收敛为 unknown/possible，终态信封不再
  保留 in-flight。
- 扣费一致性：有已知 usage 的失败请求在 step 与 attempt 上同为 `recorded`；缺少 usage 仍为
  unknown/possible，不伪造零用量。
- 窗口语义：`recent_attempts` 保留**最近** 256 条（新条目挤掉最旧），总请求、重试与 usage 聚合
  不受影响。
- 授权语义：从 `AIRunAuthorizationReason` 移除 `domain_recovery`，只保留作者确认路径可用的
  `author_resume` 与 `duplicate_charge_confirmed`；自动 retry/requeue/recovery 只能累计同一 run，
  不得增加 `request_limit`（测试 `test_automatic_recovery_never_expands_the_limit` 固化）。
- step 身份约束（Wave 3 必须遵守）：`steps` 按 (step_name, capability, call_kind, purpose,
  profile_hash) 聚合，动态 `step_name` 会让持久化 `steps` 随调用数增长。领域迁移必须使用稳定
  step 名（例如 `writing.semantic_review.chunk`），把 chunk/packet/shard 下标放进
  `input_fingerprint` 或 step 级计数，而不是拼进 `step_name`。已确认会踩坑的动态命名：
  `writing.semantic_review.chunk_{index}`、`world.validation.packet_N`、
  `{capability}.knowledge.director.shard_N`、`{step_name}.author_decision_audit` 以及 Imports 各阶段
  的 step_name 参数。Wave 4 门禁需要增加"领域 step 名不含调用序数"的检查项。

## 预算产品语义（Wave 3/4 实现约束）

```text
算法上界 A = 本次冻结工作量下的主请求
           + 既有 transport/schema/format/semantic retry
           + 既有自动 requeue

本次初始额度 L0 = min(A, capability 的单次授权安全闸门 H)
```

- A 由领域在运行开始时按已冻结输入（K/S/P/M 等）计算，不发明更宽松重试；自动 retry、自动
  requeue 与恢复都只消耗同一 A，不增加额度。
- H 是产品安全闸门，按能力的单次授权风险设定；当 A 显著大于 H 时必须分批授权，而不是一次性
  发放 A。`world.entity_fusion` 深导入路径（M=10000，A=180000）不得进入常规 L0。
- 超过 L0 后只有作者明确续算或确认可能重复扣费才能提高额度（`authorization_revision`），且不
  移动 deadline；需要新的时间边界时由领域建立新 run 并用 `previous_run_id` 关联。

## 冻结设计

### 1. 身份与预算语义

- `operation_id`：用户/领域的一次幂等逻辑操作。已有 operation receipt 时沿用其 UUID；否则使用
  领域 operation ID，仍无独立领域 run 时使用 `task.id`。
- `run_id`：一次权威领域运行及其累计授权账本。Assistant 使用 `AssistantRun.id`，Interaction 使用 generation
  attempt ID，Imports 使用 `ImportWorkflowRun.id`，Map 使用 `MapAtlasRun.id`，其余 task 使用
  `task.id`。自动 transport/repair/requeue/manual resume 保持同一 run。
- `task_id / task_attempt / lease_id`：只表示当前执行载体和所有权，不替代 operation/run 身份。
  Map 等恢复后 task 可变化；provider attempt 在同一 run 内继续单调递增。
- `authorization_revision`：只有作者明确续算或确认可能重复扣费时才可在同一 run 内增加请求额度，
  并记录原因；不得移动既有 deadline。超过 deadline 后继续必须由领域创建新 run，并通过
  `previous_run_id` 关联。普通 retry 不能增加 request limit 或重置 deadline。
- `deadline_at` 从领域 run 或 task 实际开始执行时冻结，不含排队等待；已有更短 provider/step/domain
  timeout 继续生效，实际边界取最早者。deadline 到期后不得继续 sleep 或发送下一次请求。
- `request_limit` 由领域按“现有最大正常调用 + 已允许 structured/format/semantic repair + transport
  余量”冻结，不发明更宽松重试。若当前合法最大输入下没有有限上界，该能力必须先增加领域上界，
  才能完成迁移。

### 2. 版本化内部契约

- 在 `infrastructure/llm/schemas.py` 增加严格、可序列化的 `AIRunEnvelopeV1` 与 step receipt；运行期
  累计和 ContextVar 逻辑放在现有 `workflow_budget.py`，不新建第二运行模块。
- run 级最小字段：`version=1`、`operation_id`、`run_id`、可选 `previous_run_id`、
  `root_capability_id`、`novel_id`、可选 task identity、`started_at/deadline_at`、`request_limit`、
  `requests_started/settled/unknown`、`authorization_revision`、聚合 token usage、
  `usage_complete`、`charge_state`、run status。
- step 级最小字段：`step_name`、`step_capability_id`、`call_kind`、`purpose`、profile hash、可选
  已存在的 `input_fingerprint` 与 Prompt contract `id/version/hash`、provider request 数、
  transport/structured/format/semantic retry 数、耗时、finish reason、安全 error kind、retryable、
  possible charge。不得为没有版本化 Prompt contract 的调用伪造 Prompt ref。
- `root_capability_id` 每 run 只能有一个；内部 helper 的 `step_capability_id` 必须等于 root 或取
  `infrastructure.*`。semantic repair 是 `purpose`，不是新 capability。
- 保留 `world.map_image_prompt` 表示视觉 brief；在同一个 `CAPABILITY_REGISTRY` 新增
  `world.map_image.generate` 表示实际 Image API generate/edit，二者不得共用一个 ID。generate/edit
  由 `call_kind` 区分，不再增加第三个图片 capability。
- 保存完整聚合计数，并仅保留有界 recent attempt 摘要；超过 256 条时并入 overflow aggregate，
  仍不得丢总请求、未知请求、retry 和 usage 计数。
- 费用只记录 `charge_state = none | recorded | possible`，不估算货币金额。provider 调用前被预算、
  deadline、鉴权或输入校验拒绝为 `none`；请求已发出但超时、中断、取消、崩溃或缺 usage 为
  `possible`；完整响应的已知 usage 为 `recorded`。

### 3. 执行与持久化

- 保留 `managed_llm_steps` 作为兼容投影：v0 五字段记录原样可读；v1 从同一 envelope 的 step
  receipt 派生，不成为第二事实源。现有消费者不得因新增字段或 v0 混合列表失败。
- Worker/inline task 在现有 ContextVar scope 中注入 task identity，恢复既有 envelope；成功、失败、
  取消、特殊 transient requeue 和 stale recovery 都合并同一 run。特殊 requeue 必须先持久化本
  attempt 回执再释放 lease。
- 运行快照保存到现有私有 JSON：task 使用 result/meta 的 `_ai_run_envelope`；Assistant 使用
  `checkpoint_json`，Interaction 使用 `agent_checkpoint_json/usage`，Imports 使用 workflow
  checkpoint，Map 使用 `context_snapshot`，同步 Evidence 任务使用 ContextSnapshot provenance。
  不新增表或列。
- provider 请求 reserve 后、真正 I/O 前，通过已有 lease/domain checkpoint 写入 `in_flight`；
  task 路径使用只更新 `_ai_run_envelope` 的窄 lease-fenced merge，禁止提交或覆盖 handler 的业务事务。
  重启遇到未 settle 请求时转为 unknown/possible，而不是删掉或当成未请求。
- `_public_task_result()` 必须继续剥离 `_ai_run_envelope`；首轮不增加前端/公开 API 字段。日志只写
  capability、run/attempt、安全 error kind 和计数，不写动态异常正文。

### 4. Provider 单入口与兼容顺序

- `LLMClient.generate()` 成为文本 provider I/O 的唯一计量入口；structured 普通、关闭 transport
  retry 和 format repair 分支均回到它，保留当前 limiter、解析和 retry 结果。
- stream 在建流前 reserve，完整消费并取得最终 usage 后 settle；建流后取消/断流且无最终 usage
  记 unknown/possible，禁止自动重放已开始的 stream。
- `run_managed_generate/structured` 必填 capability；新增窄 `run_managed_stream` 与
  `run_managed_research`。`run_project_agent` 必填 root capability，Pydantic retry、工具内嵌工作流和
  research 共享同一 run，不与 `AgentRunBudget`/`WorkflowBudget` 重复扣数。
- 图片 client 保持固定 GPT Image 2、零 SDK retry 和 Map 领域确认，只接同一 reserve/settle hook；
  request ID、retryable 与 possible_charge 直接投影到 receipt。
- 兼容开关不做长期配置：同一主题分支按“读 v0/v1 → 写 v1 但暂不 fail closed → 迁移全部调用 →
  门禁与 project-scoped runtime fail closed → 启用统一总预算/deadline”顺序提交和验收。旧在途 task
  首次进入 v1 时标记 `legacy_untracked/usage_complete=false`，继续现有领域边界，不回填猜测计数。

## 子代理 Waves 与写入所有权

宿主并发上限按“主 Agent + 最多 3 个子代理”安排。实现子代理使用隔离 worktree/主题分支；
每 wave 必须从主 Agent 已验收的上一 wave 集成点开始。`.agent/TASKS.md`、本 TASK、共享契约、
最终门禁和冲突修复始终由主 Agent 单写；子代理不得删除现有 `* 2.*` 文件或修改真实数据。

### Wave 0：重新冻结基线，只读并行

- W0-A：枚举全部生产 provider 调用、managed/Agent/image 入口及 46 项 capability 映射；标出动态
  root capability 和 infrastructure exemption。
- W0-B：逐能力计算当前最大 provider 请求公式、deadline、现有 retry/possible-charge 行为；特别
  复核 Story Outline、Imports 分批、Interaction summary、World chat/convergence 和 Map image。
- W0-C：核对 task/domain run/operation/checkpoint 身份与恢复路径，确认旧在途兼容和公共 wire。
- 主 Agent：验证 `origin/main`、工作树和调用清单，记录基线失败；只有干净 worktree 的 prompt、
  docs、核心 LLM/task 测试绿色后才放行 Wave 1。

### Wave 1：核心契约，单一写入者

- W1-Core 唯一写入：`llm/schemas.py`、`workflow_budget.py`、`agent_step_harness.py` 及其测试；实现
  v0/v1 解析、run/step 累计、嵌套 scope、并发隔离、reserve/settle、deadline、unknown/possible、
  compatibility projection。不得触碰 client、task 或领域文件。
- 其余两个子代理只读审查字段脱敏与恢复语义；主 Agent 验收 API 后冻结接口，后续 wave 不再自行
  改共享 contract。
- 退出门禁：contract round-trip、v0 兼容、ContextVar 并发隔离、预算拒绝前零扣费、未知 usage、
  256 条 overflow 聚合和秘密扫描测试绿色。

### Wave 2：底层通道，三路并行

- W2-Text：独占 `client.py`、`retry.py`、`modules/project/llm_runtime.py` 及对应测试；统一 provider
  单入口，覆盖 transport、structured/format repair、stream、project-scoped fail-closed 和
  deadline-aware backoff。
- W2-Agent：独占 `agent_runtime.py`、`native_search.py`、`workflow_budget` 的适配测试；不得修改 Wave 1
  contract 文件。完成 Pydantic request/retry、嵌套工具、research 和恢复预算的无双计数接线。
- W2-Task：独占 task worker/lifecycle/inline/enqueuer 与测试；完成 task identity、lease-fenced 私有
  checkpoint、success/failure/cancel/requeue/stale 合并，并修复“非 transient LLM 错误被通用
  auto_requeue”及“特殊 transient requeue 丢回执”。普通非 LLM auto_requeue 语义不变。
- 主 Agent：集成三路后独立跑 LLM + task 回归，检查 structured 行为、异常实例、limiter、lease、
  operation receipt 和领域事务顺序均未改变。

### Wave 3：业务通道迁移，三路并行

- W3-A：Writing + Story；显式绑定 generation/review/targeted revision/outline/card/reaction/script，
  删除重复 collector/手工计数但保留 Prompt、知识审查、一次 semantic repair 与采用门禁。
- W3-B：World + Map，并独占 `infrastructure/llm/image_client.py`、`modules/project/image_runtime.py`；
  覆盖 chat/design/convergence/validation/atlas structured 与图片 generate/edit，新增
  `world.map_image.generate`，保留 Map `provider_in_flight → retry_requires_confirmation`、页级
  CAS、上传恢复和补偿。
- W3-C：Assistant + Interaction；覆盖 bounded Agent、summary、legacy stream、research、RP resume，
  保留 AssistantRun/attempt 累计预算、模型历史、held release、停止和看海授权。
- 主 Agent：负责 Imports + Evidence，因为分批/parallel、inline child、director/audit 与 Context snapshot
  共用预算最复杂；逐阶段接 capability、request 公式和回执，不改变 phase checkpoint 或自动采用。
- 所有子代理只改各自领域与定向测试，不改 `capability_bindings.py`、共享 schema/runtime、公共文档
  或其他代理文件。主 Agent 逐路审查后才集成。

### Wave 4：静态门禁、文档与独立复核

- W4-Gate 单一写入者：更新 `capability_bindings.py` 和 prompt-contract 测试；唯一 managed/Agent/
  research/stream/image 入口必须显式 `capability_id` 且属于该文件允许集合，修正已知错绑。AST
  读取/解析失败改为 P1，不再静默返回无调用。
- 已知绑定修正必须包含：Interaction summary、Writing targeted revision、World design iteration、
  Imports enrichment/fusion/entity extraction、Assistant research；knowledge director/audit 继承调用方
  root capability，不继续误标为 `infrastructure.format_repair`。
- 不对所有同名 `.generate()` 做脆弱类型猜测；最终由“业务调用只走唯一受管入口”静态规则与
  “project-scoped client 无 active envelope 时运行前拒绝”双门禁覆盖。基础设施 exemption 必须
  精确到文件和原因，embedding 明确列为首轮非目标。
- W4-Security、W4-Retry 两个子代理只读复核：前者查 secret/正文/reasoning/novel_id/公共 wire；
  后者重算每条代表路径的 request/retry/deadline 与恢复累计。主 Agent裁决并修复，不直接接受报告。
- 主 Agent 更新 ADR-0023、ADR-0025、LLM/tasks README、Prompt/架构文档和本 TASK 恢复快照；不新建
  ADR，除非实际实现改变已采纳的运行所有权或持久化决策。

### Wave 5：主会话验收与交付边界

- 主 Agent 重新枚举调用点并核对零旁路、零未知 capability、零公开 `_ai_run_envelope`；运行全部
  定向、PostgreSQL、prompt/docs、lint 与 CI 门禁。任何子代理绿色结果仅作线索。
- 可选真实门禁必须单独获得费用和凭据授权：文本 structured、Agent/stream、research、图片各一条
  最小调用；只验证协议、回执和扣费不确定性，不宣称模型内容质量。
- 实现完成后记录本地 diff 与验证；commit、push、PR、合并、部署、清理分支和删除既存未跟踪文件
  均保持独立授权。

## 里程碑与进度

- [x] M0：干净 worktree 基线、调用/capability/budget/run 身份清单冻结——W0-A 调用清单、W0-C
  身份/恢复矩阵与 W0-B 第二轮预算上界均已落盘 artifacts 并通过主 Agent 抽查。
- [x] M1：v1 envelope 与 v0 compatibility projection 完成，无领域行为变化——含 S2.1 契约
  修正与 44 项信封测试。
- [ ] M2：文本、structured、stream、Agent、research、图片 provider 计量单入口完成。
- [ ] M3：task/inline/requeue/stale 跨 attempt 累计和 private persistence 完成。
- [ ] M4：全部业务调用迁移并启用 capability/runtime fail-closed 门禁。
- [ ] M5：文档、定向/PG/完整 CI 验收完成；真实 provider 状态单独记录。

## 验证矩阵

- Contract：v0/v1 混读、严格字段、未知版本、异步 scope 隔离、nested scope 复用、run 身份漂移拒绝、
  overflow 聚合、JSON round-trip、无 Prompt/正文/Key/完整 endpoint。
- Text/structured：一次成功、transport 失败后成功、schema repair、format repair、关闭 transport
  retry、预算耗尽、deadline 在 backoff 前耗尽；每个真实 provider I/O 只计一次。
- Stream：建流失败可按现有策略重试；首块后完成、取消、断流、无最终 usage；已开始 stream 不重放，
  unknown/possible 正确。
- Agent/research：Pydantic output retry、工具内 deterministic LLM、恢复模型历史、父子 inline task、
  搜索多请求与失败切换；AgentRunBudget 和 envelope 计数一致但不双扣。
- Image：generate/edit 成功、moderation/auth/quota 的请求前或确定失败、timeout/connection 的未知结果、
  request ID、Map 允许自动重试与必须人工确认两条分支。
- Task：真实 enqueuer 冻结 policy 后的 transient 与非 transient LLM 错误、普通非 LLM auto-requeue、
  success/failure/cancel、特殊 requeue、heartbeat stale、manual resume、lease 丢失、operation replay；
  run/deadline/count 不重置，旧 lease 不覆盖新 attempt。
- Wire：`GET /api/tasks/{id}` 和领域公开响应不含 `_ai_run_envelope`、Prompt、provider raw、Key 或私人
  provenance；已有 `managed_llm_steps` v0 消费者继续工作。
- 领域代表链：Writing candidate/semantic review、Story Outline 最坏重试、Imports 分批+一次知识返修、
  World chat/design、Assistant research、Interaction Agent/legacy stream/summary、Map image。
- 最终命令：受影响 pytest；专用 PostgreSQL worker/requeue E2E；`make prompt-contracts`；
  `make test-ci TEST_WORKERS=2`；`make docs-check BASE_REF=origin/main`；`git diff --check`。浏览器仅在
  实现改变公开状态/恢复交互时加入，当前设计不要求前端改动。

## 决策、发现与失败

- 2026-09-15：选择扩展现有 managed/budget/task JSON seam，而不是新 Client、表或观测平台；原因是
  当前缺口是覆盖和外层语义，不是底层能力缺失。
- 2026-09-15：运行回执不承载 Review/adoption/stale；用 `run_id` 关联，避免形成第二业务事实源。
- 2026-09-15：operation、run、task、provider attempt 分离；自动恢复不重置 run，只有明确续算才增加
  authorization revision，避免重试悄悄扩大成本授权。
- 2026-09-15：先兼容写入和迁移，再 fail closed/启用总预算；避免在调用清单不完整时改变生产行为。
- 2026-09-15：现有工作树的重复副本使 docs/prompt 检查假失败；实施必须用干净 worktree，不清理
  用户文件来获得绿色结果。
- 2026-09-15：用户随后明确要求清理并提交；逐个 `cmp` 证明 32 个副本完全相同后才移入系统
  废纸篓，未删除任何不同内容或缺少正式对应文件的路径。
- 2026-09-15：用户确认执行范围 S0–S2（基线、Wave 0 冻结、v1 核心契约），授权按 wave 并行委派
  子代理，并允许提交到主题分支但不 push。
- 2026-09-15：实现 worktree 从计划提交 `81ef210e8` 而非 `origin/main` 创建，以便唯一进度源
  TASK 随分支移动；两处差异仅为 `.agent/` 文档，代码基线与 `origin/main` 逐字节一致。
- 2026-09-15：运行账本落地在现有 `workflow_budget.py`，v1 契约在 `schemas.py`；不新建第二个
  运行模块，基础设施只校验格式、活动 scope 与同 run 身份不漂移，不 import capability 注册表。
- 2026-09-15：`requests_settled` 冻结为"已取得含 usage 完整回执的请求"，`requests_unknown` 为
  "已发出但结果或用量的证据不完整"；未知用量记 possible 且 `usage_complete=false`，绝不写零。
- 2026-09-15：同 run 增加额度只接受可审计原因码（`AIRunAuthorizationReason`），不保存作者自由
  文本，以符合"信封不含用户输入"的安全边界；deadline 不随额度移动。
- 2026-09-15：v1 兼容投影把细节放在 `managed_llm_steps` 记录内的单一 `ai_run` 注释块，前五个
  字段与 v0 完全一致；合并时对注释块做严格重验，未知键被丢弃而不是进入公开 result。
- 2026-09-15：Wave 1 只在受管入口建立 step 上下文，不在 harness 内预留 provider 请求；真正的
  每请求 reserve/settle 归 Wave 2 的 `client.generate()` 单入口，避免重复计数。
- 2026-09-15：主 Agent 复核确认 W0-C 结论——`get_completed_payload`（`lifecycle.py:394-405`）
  原样返回含 `_` 键的 result，而 `story_outline_service.py:248-259` 对 result 顶层键做 exact-key
  校验。因此通用 task 路径的运行信封**写入私有 meta**（`_ai_run_envelope`），不写 result：
  `_public_task_meta` 会剥离下划线键，story 采用门校验的是 result 而非 meta，成功路径整体替换
  result 也不会丢信封。领域自身 checkpoint（Assistant/Interaction/Imports/Map/Evidence）按原设计
  不变。

## 验证证据

- 计划阶段只读核验：纯 tracked `HEAD` 的 Prompt contracts 为 24 passed；主工作树一度因未跟踪
  `knowledge_audit 2.json` 重复 ID 失败。清理后本主题分支已重新通过 24 contracts。
- 计划阶段三个只读子代理分别核对 runtime contract、预算/retry/task 与跨通道门禁；其中预算/
  retry/Agent/worker 定向基线报告为 44 passed，通道基础 seam 定向基线报告为 42 passed。主 Agent
  尚未把这些子代理数字作为实施验收，Wave 0 必须在干净 worktree 独立复跑。
- 清理前 `make docs-check` 基线失败于未跟踪重复 ADR；清理后本主题分支的 `make docs-check` 与
  `make docs-check BASE_REF=origin/main` 均通过，影响检查确认没有 architecture-sensitive source
  change；tracked diff 与新增 TASK 的 no-index whitespace 检查均通过。
- 2026-09-15 Wave 1（worktree `.worktrees/ai-run-envelope`，基线 = `origin/main 5a2524dae`）：
  - 基线复跑：`make prompt-contracts` 24 passed；`make docs-check BASE_REF=origin/main` 通过；
    `python -m pytest infrastructure/llm/tests infrastructure/tasks/tests -q` 319 passed,
    2 deselected。
  - 实现后：同两套件 356 passed, 2 deselected（新增 37 项信封测试）；`ruff check` 对 4 个改动
    文件 All checks passed；`make prompt-contracts` 24 passed；`make docs-check
    BASE_REF=origin/main` 通过（已同步 `backend/infrastructure/llm/README.md` 与
    `docs/modules/12_infrastructure.md`）；`git diff --check` 干净。
  - 全量回归：`make test-fast-coverage TEST_WORKERS=2` → 5578 passed, 13 skipped，覆盖率
    85.69%（门槛 85%），确认共享契约改动没有领域行为回归。
- 2026-09-15 S2.1 契约修正：
  - `pytest infrastructure/llm/tests` → 242 passed, 2 deselected（新增 6 项 S2.1 回归：
    并发 checkpoint 单调、hostile profile_summary、终态收敛、已知 usage 失败、
    自动恢复不扩额、动态 step 名计数）。
  - 并发回归做了变异验证：临时移除 `reserve` 的 `@_serialized` 后该测试失败，恢复后通过，
    证明测试确实覆盖"旧快照后写覆盖新状态"。
  - `ruff check infrastructure/llm/` All checks passed；`make prompt-contracts` 24 passed；
    `make docs-check BASE_REF=origin/main` 通过；`git diff --check` 干净。
  - 全量回归：`make test-fast-coverage TEST_WORKERS=2` → 5585 passed, 13 skipped，覆盖率 85.83%。
- 2026-09-15 W2-Text 审查（主 Agent 独立复核提交 `0a521a116`）：独立复跑
  `pytest infrastructure/llm/tests` → 258 passed；确认 `generate()` 计量块在真实 provider I/O 前
  reserve、成功/异常/取消都 settle，且保留 WorkflowBudget 原有语义（BaseException 分支不额外调用
  `completed`）；被改写的旧测试改为断言"仍走 `generate(transport_retries=False)`、只发 1 次请求、
  不使用 retry helper"，属加严而非放宽；fail-closed 未启用也未留不可达分支。集成时需补
  README 与 `docs/modules/12_infrastructure.md` 的单入口口径，并把"semantic 返修不得再次
  `record_retry`"列为 Wave 3 约束。
- 2026-09-15 W0-B 重新冻结：主 Agent 抽查 5 处关键证据（world schemas 的 max_packets/max_suggestions
  上限、map_structure 的合计 ≤20 校验器与 max_fix_attempts、entity_fusion 深导入 10_000）全部与
  修订后的表一致；13 条修正与 6 项存疑已记入 artifact 第 5、6 节。
  - 覆盖的门禁项：v0/v1 混读与未知版本失败关闭、契约 JSON round-trip、step 能力越界拒绝、
    计数与 usage 收款一致性、预算/deadline 拒绝前零计数、未知 usage 记 possible、
    256 条 recent attempt 溢出聚合、嵌套 scope 复用与 run 身份漂移拒绝、asyncio 并发隔离与
    子任务共享账本、授权追加额度不移动 deadline、恢复把 in-flight 转 unknown、v0 五字段兼容
    投影、秘密/正文/endpoint 不入信封。

## 交付结果

- 已交付：Wave 0 只读冻结结论与两份 artifacts；Wave 1 的 `AIRunEnvelopeV1` /
  `AIStepReceiptV1` 契约、`AIRunEnvelope` 累计账本与 ContextVar scope、受管 step 归属、
  v0 兼容投影、37 项定向测试，以及 `infrastructure/llm/README.md`、`docs/modules/12_infrastructure.md`
  的同步。
- 未交付：Wave 2–5 的 provider 单入口接线、task/领域持久化、capability 门禁修正、ADR 更新、
  真实 provider 验收，以及 push、PR、合并与部署。
- 交付边界：改动只存在于本 worktree 的主题分支 `codex/ai-run-envelope`；未 push、未合并、
  未部署；`origin/main` 未受影响。
- 正式知识与后续任务：ADR-0023/ADR-0025 与 LLM/tasks README 的完整更新按计划在 Wave 4 完成；
  本 TASK 保持唯一进度源。
