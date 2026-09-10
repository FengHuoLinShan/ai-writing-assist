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
受管 provenance 会保留白名单内的字段来源；`account` 表示 provider/model 来自项目
owner 当前账户连接，不得被净化为 `unknown`。

`context_budget` 默认只作为 step envelope 元数据传入，不会自动截断或重写
request messages。需要主动裁剪上下文时，应显式使用 `ContextBudgetGuard`。
本 harness 不实现自治 agent loop、工具自主选择或跨模块业务编排。

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
input ceiling 放行：256K normal、360K compact、400K hard，单次 summary 输入最多 256K。
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

所有 `LLMClient` 实例共享进程级并发 semaphore 与 RPM token bucket。所有环境均可将
`LLM_RATE_LIMIT_PER_MINUTE` 设为 `0` 关闭额外 RPM 限制，也可按 provider
配额显式配置正值。该配额按进程执行，部署多个 API/worker 实例时必须按实例数核算
总吞吐；代码不替 provider 选择固定生产 RPM。关闭 RPM 时仍应保留并发上限以保护
服务器资源。

availability circuit breaker 不跨项目共享：它按
`project/system + chat/embedding + normalized endpoint` 建立进程内桶。endpoint identity
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

DeepSeek 新能力快照以可选 `interaction_reasoning_effort=max`、`interaction_timeout_seconds=900`
及三个65,536输出预算保存 RP 专用策略；旧快照恢复为空策略并保留原数字。其他模型与业务调用
默认参数不变。流式片段只计数 `reasoning_chars` 且序列化排除，不保存或显示思考文本；结构化
诊断同时记录可见/思考字符数，便于区分有用量无正文与正常输出。

完整 JSON 仅在解码器定位为非法反斜杠转义时最多修复8处，保留字面内容并继续schema校验；
截断、损坏Unicode或无法完整解析仍走失败路径。截断重试不会将调用方已设置的更大预算
降到旧40K扩展目标，重试层数不增加。

2026-09-10 的最新 DeepSeek 原生联网兼容门禁连续三次未收到搜索事件或引用，运行时注册已
撤下；适配代码仅保留给显式验证。账户文本/结构化模型连接不因此换供应商。无实际completed
搜索事件不出具联网结果；已收到但不符合搜索要求的响应仍保留已知用量，缺失用量为未知。

工具准备与读取中的内部模型步骤使用 workflow_budget.budgeted_tool；原工具签名保留，嵌套
工作流共享累计预算且不会重复计数，离开工具后恢复外层上下文。Pydantic 主循环的模型请求
仍由 ProjectGatewayModel 计量，不套入工具内部计量层。
