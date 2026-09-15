---
id: T-20260915-ai-run-envelope
title: 统一 AI 运行信封
status: draft
created: 2026-09-15T10:42:18+08:00
updated: 2026-09-15T11:08:46+08:00
parent: .agent/tasks/agent-integration.md
---

# 统一 AI 运行信封实施计划

## 恢复快照

- 实际完成：已复核当前文本、structured、stream、Agent、research、图片、预算、task retry、
  provenance 与 capability 门禁；已形成决策完整的实施顺序和子代理 wave。尚未实现代码。
- 当前里程碑：计划已冻结，状态为 `draft`。
- 下一步：用户明确要求实施后，从当前已核实的 `origin/main` 创建干净
  `codex/ai-run-envelope` worktree，执行 Wave 0 基线复核。
- 阻塞：无技术阻塞；当前请求授权计划落盘、清理已证明冗余的副本并提交，未授权运行时代码
  实现、推送或部署。
- 工作区：主题分支 `codex/ai-run-envelope-plan` 从
  `origin/main == 5a2524dae7b5322f83fe68353b8962d24900bb0e` 创建；32 个既存 `* 2.*` 未跟踪文件均与
  正式文件字节一致，已移入系统废纸篓。当前仅本 TASK 与 `.agent/TASKS.md` 属于交付改动。
- 最后核实：2026-09-15T11:08:46+08:00。

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

- [ ] M0：干净 worktree 基线、调用/capability/budget/run 身份清单冻结。
- [ ] M1：v1 envelope 与 v0 compatibility projection 完成，无领域行为变化。
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

## 验证证据

- 计划阶段只读核验：纯 tracked `HEAD` 的 Prompt contracts 为 24 passed；主工作树一度因未跟踪
  `knowledge_audit 2.json` 重复 ID 失败。清理后本主题分支已重新通过 24 contracts。
- 计划阶段三个只读子代理分别核对 runtime contract、预算/retry/task 与跨通道门禁；其中预算/
  retry/Agent/worker 定向基线报告为 44 passed，通道基础 seam 定向基线报告为 42 passed。主 Agent
  尚未把这些子代理数字作为实施验收，Wave 0 必须在干净 worktree 独立复跑。
- 清理前 `make docs-check` 基线失败于未跟踪重复 ADR；清理后本主题分支的 `make docs-check` 与
  `make docs-check BASE_REF=origin/main` 均通过，影响检查确认没有 architecture-sensitive source
  change；tracked diff 与新增 TASK 的 no-index whitespace 检查均通过。

## 交付结果

- 已交付：本实施计划、固定 contract/兼容/失败语义、子代理 wave、写入所有权与验收矩阵。
- 未交付：任何运行时代码、测试修改、正式文档同步、推送、PR、合并或部署。
- 交付边界：本 TASK 与开放任务索引是本次唯一提交内容；32 个完全相同的冗余副本已移入可恢复的
  系统废纸篓。未授权 push、合并、部署或其他清理。
- 正式知识与后续任务：实施完成后按实际结果更新 ADR-0023/ADR-0025 和基础设施文档；本 TASK
  保持唯一进度源。
