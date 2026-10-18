# infrastructure/llm — LLM 客户端封装

## 定位

封装模型调用，不放小说业务逻辑。

## 目录

```
infrastructure/llm/
├── README.md
├── __init__.py
├── client.py       # LLMClient 主入口
├── image_client.py # 固定 gpt-image-2 的 Image API adapter
├── profiles.py     # 解析、校验与脱敏 LLM Profile
├── balance.py      # DeepSeek/Kimi 窄余额查询适配
├── providers.py    # Provider 抽象基类 + OpenAI 实现
├── schemas.py      # Pydantic 入参/出参 schema
├── errors.py       # 自定义异常
├── retry.py        # 重试逻辑（指数退避）
└── agent_step_harness.py  # 受控 LLM step envelope / journal / 输出守门
```

## 职责

- 管理不同模型 provider
- 支持普通 JSON 调用
- 支持流式输出
- 支持重试
- 支持结构化输出修复
  完整响应可在字符串外修复一个括号笔误：更正一个错误闭合符，或仅在正确闭合符紧随时
  移除一个多余闭合符；修复后必须再次通过完整 schema，诊断保留具体策略。
  不改字符串、业务字段或数值；新增的多余闭合符删除分支不补缺失括号，且拒绝多错误和
  多文档。原有包装、单错括号替换与轻截断恢复继续遵守已有 schema/完成原因门。
- 支持由上层 project facade 解析的账户级 OpenAI-compatible LLM Profile
- 提供版本化 model capability budget；当前校准 canonical `deepseek-flash`，并保留
  `deepseek-v4-flash` 冻结兼容配置；未知模型使用
  保守 short fallback，不继承上一模型的 context ceiling
- 记录 token 和调用耗时
- 结构化调用的每次首发/修复都向可选受控诊断写入 prompt/completion/total token；provider 提供时
  再附加 cache-hit/cache-miss token。诊断不含 Prompt、响应正文或 Key，缓存统计不参与质量门禁
- 提供受控 LLM step harness，用于 text / structured generation 的统一
  envelope、journal、timeout 和错误分类
- 提供地图册使用的 `OpenAIImageClient`，支持生成、整图编辑、蒙版、多参考图和连续派生

## 对外接口

```python
# 仅 infrastructure 内部、独立 embedding 适配器或测试可直接构造。
from infrastructure.llm import LLMClient

client = LLMClient()

# 普通调用
resp = await client.generate(request)

# 流式调用
async for chunk in client.generate_stream(request):
    ...

# 结构化 JSON 输出
result = await client.generate_structured(request, MyPydanticSchema)

# 可选容错：默认仍严格；业务方显式开启时可保留顶层列表中的有效项，
# 并在常规重试失败后做一次“只改格式、不改事实”的格式转换兜底。
diagnostics = []
result = await client.generate_structured(
    request,
    MyPydanticSchema,
    partial_list_fields={"items"},
    diagnostics=diagnostics,
    format_repair_attempts=1,
)

# 简化调用
text = await client.generate_simple(system, user)
```

OpenAI 3.x 的文字、独立 embedding 与图片 SDK 客户端使用原生 `httpx2.AsyncClient`，
不走旧 HTTPX 兼容路径；超时、显式代理与环境代理配置保持原语义。公共出站守卫同时
支持 HTTPX2 SDK 请求和现有 HTTPX 健康/余额探针，拒绝私网目标及非白名单直连。

OpenAI-compatible SDK 的内建重试固定关闭；普通调用、流式建连和 embedding 的重试均由
`LLMClient` 的显式退避策略统一拥有。需要避免重复付费或不可解释 sibling 的业务流可对
`generate_stream(..., transport_retries=False)` 关闭建连重试；流开始后的中断始终交给上层
按业务状态恢复，不自动重放。

ADR-0013 覆盖的作者长任务由 task registry 显式关闭 `LLMClient` transport retry；worker
只对连接、超时、限流和明确的临时 provider 错误重排一次，最多两个 task attempt。认证、
额度、内容过滤、结构校验和来源冲突不重排。结构化输出的既有格式修复预算仍属于同一
transport attempt。

### 受控 LLM Step

ADR-0023 的 `agent_runtime.py` 通过 `ProjectGatewayModel` 接入锁定的 PydanticAI。
工具历史使用显式调用 ID、JSON 参数和配对结果，拒绝孤立/重复/未完成配对；`extra` 和
`extra_body` 不可注入工具。供应商思考续接字段只在私有模型协议中保留，不进入普通 dump。

### Profile 请求默认与 extra 信任边界

`from_resolved_profile` 构造的 client 携带 profile 请求默认：
`resolve_request_defaults` 仅为请求未显式设置的 model / temperature / top_p / max_tokens
填充 profile 值，并把 profile `extra` 按键合并为请求 extra 的底座（请求键优先）。
`LLMCallRequest.temperature` 默认 None，未设置时继承 profile 默认（代码默认 0.3），
不再内置 0.7。`extra` 只允许 provider 特定参数：正式 request 字段与其 token 同义词
（`max_tokens`、`max_completion_tokens`、`temperature`、`top_p` 等）在项目设置
保存、client 构造与 provider kwargs 构建三层 fail closed。
请求、全部工具尝试和联网子请求按运行预算累计，恢复不重置；新 Agent 关闭 transport
自动重放，格式修复由 PydanticAI 独立拥有。现有确定性 structured helper 不改变行为。
`native_search.py` 保留供应商原生协议兼容代码，未通过真实兼容验证的能力不注册。
新运行使用 `web_search.py` 的私有 SearXNG 搜索与公开网页读取，不依赖模型供应商原生搜索。
前台与后台需要明确的新渠道授权；旧运行不会因为增加工具而获得新权限。网页只是外部参考，
只有实际读到的正文才能成为引用，搜索摘要不能作为已查证依据。

读取器仅支持公开 HTTP(S) HTML/纯文本，单页 2 MiB、正文 12,000 字、请求 20 秒、最多三次
重定向。DNS 解析后的全部地址必须为公网，实际连接绑定检查过的数值 IP，TLS 仍校验原主机名；
不执行网页脚本、不带浏览器 Cookie、不接受模型指定的请求头或任意 URL。管理员可用
`WEB_DNS_SERVERS` 指定公共 DNS，以适配返回代理占位地址的开发环境；没有放宽公网地址检查。

`WEB_SEARCH_URL` 仅指向管理员配置的私有 SearXNG。搜索按固定引擎顺序逐个请求，失败切换、
网页请求和重定向均计入同一运行的联网额度；不伪计模型请求或 token。联网子额度耗尽返回
明确遗漏，继续使用已取得的依据；模型、工具和总时限仍是硬边界。关闭 RP 联网只停止新检索，
已经冻结的合法准备资料可以用于续写。来源保存读取时间、最终 URL、字节和摘录指纹、覆盖说明。
费用无法核对时仍显示未知。


业务模块的 text / structured generation 应优先通过
`run_managed_generate()` 或 `run_managed_structured()` 包装 `LLMClient` 调用。
这两个 helper 不改变 provider/retry 行为：structured JSON 修复仍由
`LLMClient.generate_structured()` 负责；失败时 helper 重新抛出原始异常实例，
由业务模块保留自己的 fallback 或状态更新逻辑。
`OutputGuard` 是直接使用 `ManagedLLMStep` 时可选的低层 output schema guard；
`run_managed_structured()` 默认不启用第二层 `OutputGuard`，避免和
`LLMClient.generate_structured()` 的结构化校验/修复语义重叠。
`generate_structured()` 首次请求即补入当前 Pydantic JSON schema；调用方已给出相同紧凑 schema
时不重复追加。不修改调用方原请求，后续格式修复、预算和校验路径保持原契约。
受管 provenance 会保留白名单内的字段来源；`account` 表示 provider/model 来自项目
owner 当前账户连接，不得被净化为 `unknown`。

`context_budget` 默认只作为 step envelope 元数据传入，不会自动截断或重写
request messages。需要主动裁剪上下文时，应显式使用 `ContextBudgetGuard`。
本 harness 不实现自治 agent loop、工具自主选择或跨模块业务编排。

### AI 运行信封

`schemas.py` 定义版本化内部契约 `AIRunEnvelopeV1` 与 `AIStepReceiptV1`；
`workflow_budget.py` 的 `AIRunEnvelope` 是运行期累计账本，`ai_run_scope()` 与
`managed_step_scope()` 用 ContextVar 把运行身份和当前受管 step 注入调用链。
Goal v3 仅接受作者冻结的 Goal 范围；Assistant 目录 v4 只接受服务端冻结的
`story.character_card`、`story.reaction` 子能力；新任务明确开启批准模式时可额外冻结
`assistant.approval.judge`。三项均沿用父任务账本与启动时间，旧信封不自动获得判断能力。
v4 的未知扣费或 80% 请求阈值在下一次 provider 预留前拒绝；v1/v2 能力规则不变。
一次权威领域运行只有一个 run：自动重试、恢复、requeue 与 manual resume 都累加同一账本，
只有作者明确续算或确认可能重复扣费时才通过 `authorize_additional_requests()` 追加请求或 Token 额度，
至少一项为正。只追加 Token 时请求上限不变；授权回执记录新增请求为 0 与实际追加 Token，
原请求计数、起始时间、未知请求和 deadline 均保留。旧正请求追加回执仍可原样读取。

所有变更与 `on_change` checkpoint 在同一临界区内串行，持久化顺序与变更顺序一致，旧快照
不会后写覆盖新状态；回调不得重入同一账本。

账本只保存稳定 ID、计数、哈希与安全错误类型，step 的 profile 摘要按 allowlist 重建，`api_key`、
完整 endpoint、Prompt 与正文不会进入信封。`requests_started` 是已发出的 provider 请求，
`requests_settled` 是已取得含 usage 完整回执的请求，`requests_unknown` 是已发出但结果或用量
证据不完整的请求（超时、中断、取消、崩溃、provider 未返回 usage）。未知用量记 `possible`
且 `usage_complete=false`，不得写成零；有已知 usage 的失败请求同样记 `recorded`。
`recent_attempts` 保留最近 256 条摘要（新条目挤掉最旧），溢出计入 `recent_attempts_overflow`，
总请求、未知请求、重试与 usage 聚合不受影响。预算或 deadline 拒绝发生在任何计数之前，被拒绝的
调用不产生扣费记录；恢复与进入终态前，未 settle 的请求一律收敛为 unknown/possible，而不是删除
或当成未请求。自动 retry/requeue/recovery 只能累计同一 run，只有作者确认路径可以增加额度。

文本 provider I/O 由 `LLMClient` 单入口计量：`generate()` 对每次真实请求（含每次 transport
尝试）reserve 一次，并在取得响应、异常或取消后 settle；关闭 transport retry 的 structured、format
repair 与 `generate_stream()` 的建流尝试、`research()` 的每个 attempt 都回到同一入口，已开始的
stream 不自动重放。deadline 到期后不再退避也不再发请求：完整退避 delay 会跨过剩余 deadline 时不
执行整段 sleep、不发出下一次请求，直接抛出原始错误（structured/format repair 按各自的既有失败
契约收尾）；进程级 RPM token 与并发 semaphore 的 admission wait 同样受剩余 deadline 约束。
没有活动信封时重试与 admission 行为均与改造前一致。

checkpoint 是账本权威的一部分：持久化通道失效（租约被拒、DB 故障）时，reserve 在任何计数与
provider I/O 之前失败关闭（`AIRunCheckpointError`），瞬时故障恢复后自动补写自愈；settle 与收尾
路径的 checkpoint 失败不回滚已发出请求的落定真相，恢复按上次成功持久化的 in-flight 收敛为
unknown/possible。`discard()` 用于 provider I/O 前撤销一次预留：活动信封是权威请求闸门，兼容的
`AgentRunBudget`/`WorkflowBudget` 在其后预留、被拒时由此补偿，任一预算拒绝都不会让另一个账本
留下部分变更，成功请求在两个账本上各恰好计一次。embedding 与健康检查是首轮非目标。

`root_capability_id` 每 run 唯一；step 的 `step_capability_id` 必须等于 root 或取
`infrastructure.*`，否则账本拒绝。`managed_llm_steps` 仍是兼容投影：v0 五字段原样可读，
v1 由 `project_managed_llm_steps()` 从同一信封的 step receipt 派生，v1 细节放在 `ai_run`
注释块内，不构成第二事实源。

业务 prompt 将稳定角色、规则和 JSON schema 放在消息前缀，把动态 Scene、正文和 Context
放在最后的数据块，以利用 provider 自动前缀缓存。每次调用仍是独立、无状态的 Chat
Completions 请求；缓存命中不等于复用同一会话，项目不保存 provider 会话状态。

### 账户连接与 novel-scoped client

前端通过 settings 模块维护账户连接。第一版 provider 模板固定为：

- DeepSeek `deepseek-flash`（旧任务兼容 `deepseek-v4-flash`）
- Kimi `kimi-k3`（真实兼容门禁通过并显式启用前不可达）

带 `novel_id` 的业务模块不得自行读取项目配置或直接构造客户端，必须使用 project
模块的稳定 facade。该入口根据项目 owner 解析当前已验证的账户 provider/model/Key，
并统一处理项目 kind/owner、密钥校验、脱敏 metadata 与 client 关闭：

```python
from modules.project.facade import open_project_llm_client

async with open_project_llm_client(db, novel_id) as client:
    result = await client.generate(request)
```

可恢复任务使用 project snapshot seam；业务代码不得调用
`LLMClient.from_project_settings()` 或自行拼装 provider/profile。snapshot 只保存
provider/model、非 secret 参数、endpoint/extra hash、capability profile ID/hash/预算和项目工作流设置，恢复时读取原 provider
当前轮换后的账户 Key。没有已验证连接、原 provider Key 已清除或 endpoint 漂移时
fail-closed。业务 LLM Profile 不从 `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` 等环境变量
继承；代理、重试和 health gate 等运行参数仍由 `core.config.Settings` 管理。

DeepSeek V4 Flash 当前 capability 使用官方 1M context，但只按本地 dev eval 已验证的 400K
input ceiling 放行。新运行普通档为 high、128K normal、192K compact、400K hard，单次
summary 输入最多 256K；账户高级默认 extra.reasoning_effort=max 时冻结质量优先档：
max、256K/360K/400K、summary 最多 256K。旧快照按原值恢复。更早整理是基于历史证据的
调优假设，尚无新的速度/价格/质量 A/B 结论，不截断固定证据或取消可见性门禁。
unknown model 使用 16K/20K/24K normal/compact/hard short fallback；这些值不从浏览器或项目
设置读取。旧 task snapshot 缺 capability 字段时可恢复，但明确使用 unfrozen short fallback。

账户连接的等值指纹复用 `LLM_SETTINGS_ENCRYPTION_KEY`，并使用用途分隔的
HMAC-SHA256；数据库字段和公开 wire 不变。旧的无密钥 SHA-256 指纹不会被当作相同 Key，
作者下次保存连接时先执行真实验证，再在同一事务内惰性升级。指纹不是认证或 Key 恢复接口。

provider 初始化日志只记录固定事件名，不记录 model、完整 endpoint 或动态异常值。进入日志、
task status 或诊断响应前必须先做 secret redaction 和控制字符规范化；降级日志只允许规范 UUID、
受限枚举/原因 token 与异常类型，不能记录 exception message。

### 图片客户端

`OpenAIImageClient` 直接使用 OpenAI Images API 并固定 `gpt-image-2`，不经过 Responses API，
也不建立多 provider registry。业务模块只能通过 `project.facade.open_project_image_client()`
取得它。adapter 将权限、组织验证、额度、限流、moderation 和可能已计费的失败分开分类；
`provider_in_flight` 后是否重调由地图册领域状态决定，基础设施不做盲目自动重试。

### 健康检查边界

公共 `GET /api/health/llm` 是无账户、无项目的服务能力检查：它只静态验证 provider 模板和
服务自有代理配置，固定返回 `scope=service`、`remote_check=false`，不访问数据库、账户 Key
或远端 provider。保留的 model、host、profile 等旧响应字段在该端点为空；仅服务配置非法时
返回 503。它不表示任一作者账户可连接。

作者的真实连通性继续在账户设置保存连接时使用待保存 Key 远端验证；带 `novel_id` 的工作流
继续通过 project facade 和 owner/effective profile 前置检查。`scripts/check_llm.py` 与
`doctor --llm` 是显式的环境级远端诊断，只读取 `LLM_*` 环境值，输出
`scope=environment`、`remote_check=true`，同样不代表生产账户状态。

`balance.py` 只提供 DeepSeek `/user/balance` 与 Kimi `/v1/users/me/balance` 的窄 schema
适配，返回 provider 原币种总可用额。它不持久化余额、不轮询、不换算、不拆分，也不构成
账务系统；失败必须映射为不含响应正文或 Key 的安全不可用状态。

`LLM_MODEL_LIMITS_JSON` 按来源/provider/具体模型配置独立模型池，默认每池并发 8、RPM 0，
不再有跨模型总 semaphore 或全局 LLM RPM。键 `default` → `api/deepseek/*` 等 provider 默认
→ `subscription/codex/gpt-6-luna` 等精确型号依次覆盖；并发/输入预算为正整数，RPM 为非负整数。
普通、流式、修复与远程 embedding 按最终模型和实际 endpoint 归池。同宿主 API/worker 共享 OS 文件锁槽，
订阅池另绑定 ChatGPT 登录账户；配置改变等待本池已接纳请求结束，其他模型继续运行。
生产 API/worker 挂载同一私有 `llm-model-admission` 卷；本地使用系统用户私有目录。
RPM 是每模型的进程内 token bucket，默认关闭；正 RPM 部署仍按 worker 数核算 provider 总吞吐。
取消/进程死亡释放槽，排队受已有 run deadline 约束，provider timeout 不被删除。
演化并发批次通过共享停止信号约束等待槽、RPM 和最终 provider 任务；未知失败先停止接纳，再保存回执。
账本/兼容额度 checkpoint 后重新检查停止信号，证明未发送的请求撤销预留，不记 unknown；已发请求继续结算。

新 Codex `gpt-6-luna` 能力配置声明总窗口 1,050,000、完整输入默认 500,000、输出预留 128,000、
额外安全余量 32,000。CLI 显式覆盖 `model_context_window=1050000`、
`model_auto_compact_token_limit=800000`，继续 `--ignore-user-config`，不修改桌面全局 catalog。
完整执行输入计量包括指令、历史/身份/证据、JSON 包封和 schema；为不可观测 CLI 宿主包封另在输入内预留 32,000。
未确认 tokenizer 映射时使用 UTF-8 字节上界，并在能力快照标明估算方法；这不是已实测输入能力。
500k 是输入上限；超过时拆包或明确延期，复核超限保留生成及必要证据为待核对，禁止静默截断。
其他 Luna 型号仍须单独登记。官方规格和配置定义见
[模型规格](https://developers.openai.com/api/docs/models/gpt-6-luna) 与
[配置参考](https://learn.chatgpt.com/docs/config-file/config-reference)。
能力快照/方法/consumer read-set 固定策略；旧快照、字符规则、请求和原回执不扩大或重新盖章。
订阅 500k 可用性、语义质量和持续高并发未实测。

availability circuit breaker 不跨项目共享：它按
`project/system + chat/embedding + provider + model + normalized endpoint` 建立进程内桶。endpoint identity
只包含 scheme、host、有效端口和 base path，不包含 userinfo、query、fragment、API Key
或 model。已打开的桶在消耗 RPM token 或等待 semaphore 前失败；cooldown 后只允许一个
half-open probe。同一项目切换 endpoint 会使用新桶，不同项目即使使用同一 endpoint
也不会互相熔断。remote embedding 使用实际 `EMBEDDING_BASE_URL` identity，同时继续保留
全局 embedding 配置与项目 chat profile 的凭据边界。registry 最多保留 256 个失败桶并按
LRU 回收；API 与 worker 进程之间不共享 breaker 状态。

封闭测试服可配置 `APP_ACCESS_TOKEN` 作为单一访问令牌；配置后前端请求通过
`Authorization: Bearer ...` 访问 `/api/*`，本地 `development/test/local` 默认不启用。

## 不负责

- 世界对象生成逻辑
- 剧情结构逻辑
- 审稿逻辑
- 业务状态写入

### RP 兼容性与诊断

DeepSeek 新能力快照以 `interaction_reasoning_effort=high`（质量优先为 max）、
`interaction_timeout_seconds=900` 及三个65,536输出预算保存 RP 专用策略；旧快照保留原字段与数字。
World pro 和导入 high_quality 经 Project snapshot client 显式选择质量优先：Flash 整条客户端调用链
包括生成、知识审查和格式返修都强制 thinking/max，输出上限至少65,536（更大的显式上限保留），
provider 等待至少900秒，仍受领域总 deadline/请求次数护栏约束。普通请求保留各阶段输出上限及
显式 low/high。其他模型不被强加 Flash 的参数。流式片段只计数 `reasoning_chars` 且序列化排除，不保存或显示思考文本；结构化
诊断同时记录可见/思考字符数，便于区分有用量无正文与正常输出。

完整 JSON 可在解码器定位为非法反斜杠转义时最多修复8处，或在容器栈唯一确定且
仅有一个错误闭合括号时替换该括号；两者都不改业务文本，并继续 schema 校验。
截断、损坏Unicode或无法完整解析仍走失败路径。截断重试不会将调用方已设置的更大预算
降到旧40K扩展目标，重试层数不增加。

2026-09-10 的最新 DeepSeek 原生联网兼容门禁连续三次未收到搜索事件或引用，运行时注册已
撤下；适配代码仅保留给显式验证。账户文本/结构化模型连接不因此换供应商。无实际completed
搜索事件不出具联网结果；已收到但不符合搜索要求的响应仍保留已知用量，缺失用量为未知。

工具准备与读取中的内部模型步骤使用 workflow_budget.budgeted_tool；原工具签名保留，嵌套
工作流共享累计预算且不会重复计数，离开工具后恢复外层上下文。Pydantic 主循环的模型请求
仍由 ProjectGatewayModel 计量，不套入工具内部计量层。

### 有限协作

`collaboration.py` 只执行白名单角色的有界 DAG：最多三项并发、十二项工作，先持久化再
公布成功产物，验证输入/输出 hash，失败阻塞依赖，系统故障取消在途工作。宿主负责身份、
短事务和 lease fencing。`AgentAllocation` 只限制根预算的成员份额；legacy_v1 预算保持
旧语义，team_v1 共享 30/48/4 上限，成员额度不会成为第二计费账本。

## Agent 工具历史身份

新 checkpoint 标记 `pydantic-ai-2.42.0/tool-identity-v2`。初始工具回包按
`tool_call_id` 回查真实工具名。旧 `pydantic-ai-2.42.0` 记录仅在原调用唯一可证明时
修复历史适配器留下的 `result` 名称；重复、未配对和其它身份冲突拒绝恢复。
模型思考内容仍为私有信息，离线工具诊断只导出关联、来源和 hash。

## V2 工作图与前瞻预算

`collaboration_v2.py` 只处理有界 DAG 与失败传播，领域运行由 Collaboration 持有。
`collaboration_v2`、`forecast_v1` 的 AgentRunBudget 策略共用原请求与未知用量记账。
前瞻的生成、审查、修复共享四次额度；创作试验还校验 Case 的跨轮累计上限。

## 本机 CLI Agent transport

`cli_agent.py` 把 Codex、Claude、Kimi、DSH、Pi 的非交互输出解析为最终文本、可观测工具
次数和用量。子进程设时限、输出上限和进程组取消；stderr 原文丢弃，不将供应商思考、
原稿或本机诊断传给产品。原生Codex文本非零退出仅从有界stderr片段提取固定错误标签
（如output_schema、authentication、stream_disconnected、cli_configuration、unknown），
与JSON错误事件共用分类；标签不构成完成回执或可重试资格，未知仍禁止重发。CLI 登录态和 Key 留在作者 Mac，不从服务器 Project gateway 借用。
Kimi/Pi/DSH 通过 0600 任务文件接收正文，避免把作品资料放入进程参数；Codex/Claude
使用 stdin。DSH headless 当前只有纯文本结果，不能从其 stdout 准确计数原生工具；
产品工具仍由服务器限次，原生执行只受时限与输出上限约束，此限制须在验收中单列。
产品图片任务的配对与租约由 `modules/local_agent` 持有；本段描述底层 CLI transport，
不授权产品文字功能使用配对设备。文字功能统一经账户/project gateway，遗留本机文字任务
失败关闭，不静默切换到账户客户端。


## 结构化输出能力声明与任务级路由（B5）

`capabilities.py` 的 `structured_output` 默认 `unverified`，旧快照中的 `None`
也视为未校准。三态语义：`supported` 与 `unverified` 的 `generate_structured`
保持既有行为，默认发送 provider `json_object` 并尊重调用方预填，格式修复链同样
发送；`unverified` 只让模型失去 B5 路由候选资格，不影响调用本身；`unsupported`
在外发前失败关闭（`unsupported_structured_output`），预填不能绕过。`agent_step_harness` 的 managed step 按 client 注入的
`cost_routing`（`modules/project/model_routing` 决定）在 cheap 能力上覆盖
`request.model`，provenance 的 `profile_summary.model` 记录实际调用模型、
`sources.model=cost_routing`。路由能力与信封归属是两个参数：`routing_capability_id`
只供 B5 按子能力名（如 `imports.scene_slicing`）选模型；`capability_id` 仍是
运行信封归属，只接受 run root 或 `infrastructure.*`。

`generate`/`generate_structured`可由业务显式选择`complete_stream=True`：仍是一次
完整响应，SDK原生stream context聚合后复用原输出/schema链；须最终usage及结束原因，
原单次预算/信封/限流/全调用timeout保持，SDK与client不重放断流。默认关闭；Evolution
仅在项目账户DeepSeek连接的长结构步骤启用，方法指纹固定；短observer保持普通调用。
这提供已实测的传输替代，不证明远端reset责任或永久消除网络中断。

SDK完整消费后取公开终态snapshot，不用其自动结构解析丢弃已知length/filter用量；
length仍交原截断/schema规则，content_filter在结构化入口明确拒绝并记录完整已知用量。
迭代失败不得取partial snapshot；原始HTTPX迭代TransportError也经同一错误映射。


Codex 普通文本连接见 ADR-0033：本机单用户默认 gpt-6-luna/max；CodexProvider 经账户/project seam 使用受限 CLI，不使用 OpenAI SDK 或假 Key。封闭 schema 原生约束，开放字典包封后 Pydantic 校验；业务工具仅返回提案。未知完成禁止重发，输出上限按字节/超时保障，流式延迟至完整结果。CODEX_CLI_COMMAND 可选择已验证的新版 CLI；未登记的模型容量保持保守预算。
文本模式的原生 `item.completed/error` 与终端失败均只保留安全原因分类（如 `stream_disconnected`、`output_schema`）；任何未完成结果仍失败关闭且禁止自动重发，不返回原始错误正文。原生工具及未知事件守卫不变。


旧大段正文及长合成请求的未知失败原因未定；原未知请求保留且不重发。独立模型池仅为工程行为，不证明供应商并发或文学质量。


最终文本模式使用固定 model_instructions_file 替换默认编码指令、project_doc_max_bytes=0
和 skip_host_skill_discovery 隔离 AGENTS/host skills；ignore-rules 仅指 execpolicy .rules。
另外显式关闭 hooks、apps、浏览器、电脑操作、code_mode_host、goals、skill 自动安装与
原生无限重连，避免工具之外的本机环境行为。codex-text-v3 写入账户模板的非敏感 extra，
快照同时显式绑定 native_wrapper 的版本与固定指令SHA256，并由 extra_hash 固定连接；包装缺失/漂移不能静默沿旧快照恢复。历史快照和回执只读保留。

完整原生结果的格式/包封失败仍携带原生usage，既有信封、工作流meter和有界Agent保存为已知失败；只有没有完整回执的结果才未知，不补造或另建用量统计。

原生文本失败诊断只保留退出码和回合状态等固定字段，传入LLMError与结构化diagnostics；连接验证保留这些字段但仍返回原有安全错误文案。JSON事件、stderr、路径和认证Token均不进入该诊断。

原生Codex确定性的模型/档位/包装拒绝发生在客户端请求预留前，既不计可用性熔断失败，也不当作供应商可用证明。未知原生执行失败仍保持原熔断/禁止重放规则。

深度导入的原生 Codex 预检只核验已验证连接、当前登录身份和 Luna/max/包装配置，
并经 Project 请求授权回读当前作品 owner 的连接。它返回
`scope=project_configuration`、`remote_check=false`，不发送模型探针，也不证明远端可用。
真实模型连接验证仅由账户设置中的显式验证入口执行；未知验证结果不被导入恢复重发。

新 author-confirmed Luna 确定性流水线用 `confirmed_scope`，完成本次确认范围，
不因固定请求数、累计 tokens 或金额暂停。AIRun envelope v2 显式记录模式、可空请求上限及范围指纹；
未声明额度或授权策略不能把空值当放行。范围模式限已验证的冻结 Luna 模型，新队列仍经 owner、来源、
active run 和 lease 检查；其他模型/有界 Agent 仍用有限预算，循环、工具和单次超时不变。
Evolution `budget_total`/`budget_remaining` 允许成对为空；旧有限行原子扣减、旧信封保持原版本。
存在范围数据时迁移拒绝降级。旧未跟踪队列明确保留领域预算 seam，不能冒充已完整跟踪。

新范围信封在预留前同时核验步骤上下文与实际执行 provider/最终 model，步骤标签不能授权其他来源。新 B5 路由把附加型号能力快照保存在 `cost_routing.llm_capability_profile` 并纳入项目签名；发送按最终型号选冻结输入预算，旧路由缺此字段时保留旧策略。冻结 tokenizer 方法与当前工具不一致在装包/最终发送前失败关闭，不重试或默默放宽输入。

### 批准判断 low 隔离

Project 显式 `approval_judgment` 用途可以构造专用 client：仅当前 provider 的
`deepseek-flash`/`gpt-6-luna`、low、无工具且结构化请求；在请求预留与 I/O 前拒绝模型、
档位或输出模式漂移。普通 Codex client 仍拒绝 low。专用 Codex 原生命令仅改 low 参数，
保留原生工具关闭、只读沙箱、ignore-user-config/ignore-rules、schema 与身份重验；
回执记录实际 low，不输出私有思考。该能力不证明判断器已校准或自动模式已开放。
