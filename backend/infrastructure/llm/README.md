# infrastructure/llm — LLM 客户端封装

## 定位

封装模型调用，不放小说业务逻辑。

## 目录

```
infrastructure/llm/
├── README.md
├── __init__.py
├── client.py       # LLMClient 主入口
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
- 记录 token 和调用耗时
- 提供受控 LLM step harness，用于 text / structured generation 的统一
  envelope、journal、timeout 和错误分类

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

### 受控 LLM Step

业务模块的 text / structured generation 应优先通过
`run_managed_generate()` 或 `run_managed_structured()` 包装 `LLMClient` 调用。
这两个 helper 不改变 provider/retry 行为：structured JSON 修复仍由
`LLMClient.generate_structured()` 负责；失败时 helper 重新抛出原始异常实例，
由业务模块保留自己的 fallback 或状态更新逻辑。
`OutputGuard` 是直接使用 `ManagedLLMStep` 时可选的低层 output schema guard；
`run_managed_structured()` 默认不启用第二层 `OutputGuard`，避免和
`LLMClient.generate_structured()` 的结构化校验/修复语义重叠。

`context_budget` 默认只作为 step envelope 元数据传入，不会自动截断或重写
request messages。需要主动裁剪上下文时，应显式使用 `ContextBudgetGuard`。
本 harness 不实现自治 agent loop、工具自主选择或跨模块业务编排。

### 账户连接与 novel-scoped client

前端通过 settings 模块维护账户连接。第一版 provider 模板固定为：

- DeepSeek `deepseek-v4-flash`
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
provider/model、非 secret 参数、endpoint/extra hash 和项目工作流设置，恢复时读取原 provider
当前轮换后的账户 Key。没有已验证连接、原 provider Key 已清除或 endpoint 漂移时
fail-closed。业务 LLM Profile 不从 `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` 等环境变量
继承；代理、重试和 health gate 等运行参数仍由 `core.config.Settings` 管理。

账户连接的等值指纹复用 `LLM_SETTINGS_ENCRYPTION_KEY`，并使用用途分隔的
HMAC-SHA256；数据库字段和公开 wire 不变。旧的无密钥 SHA-256 指纹不会被当作相同 Key，
作者下次保存连接时先执行真实验证，再在同一事务内惰性升级。指纹不是认证或 Key 恢复接口。

provider 初始化日志只记录固定事件名，不记录 model、完整 endpoint 或动态异常值。进入日志、
task status 或诊断响应前必须先做 secret redaction 和控制字符规范化；降级日志只允许规范 UUID、
受限枚举/原因 token 与异常类型，不能记录 exception message。

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
