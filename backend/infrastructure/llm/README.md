# infrastructure/llm — LLM 客户端封装

## 定位

封装模型调用，不放小说业务逻辑。

## 目录

```
infrastructure/llm/
├── README.md
├── __init__.py
├── client.py       # LLMClient 主入口
├── profiles.py     # 项目级 LLM Profile + 前端供应商模板
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
- 支持项目级 OpenAI-compatible LLM Profile
- 记录 token 和调用耗时
- 提供受控 LLM step harness，用于 text / structured generation 的统一
  envelope、journal、timeout 和错误分类

## 对外接口

```python
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

### 项目级 LLM Profile

前端可通过 project 模块维护 `projects.settings.llm`，字段包括：

- `provider_id` — 供应商模板 ID，如 `deepseek` / `kimi` / `openrouter`
- `label` — 前端显示名称
- `base_url` — OpenAI-compatible Base URL
- `model` — 默认模型名
- `api_key` — 写入字段；存储时使用 `LLM_SETTINGS_ENCRYPTION_KEY` 加密，
  API 响应必须脱敏，不得回显

业务模块若要使用项目级配置，应通过项目上下文读取 `settings`，再构造客户端：

```python
client = LLMClient.from_project_settings(project_context.settings)
```

缺失字段会回退到数据库全局默认或代码内置 DeepSeek 默认。业务 LLM Profile
不会从 `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` 等环境变量继承；API Key
只允许项目级配置。代理、重试和 health gate 等运行参数仍由 `core.config.Settings`
管理。

封闭测试服可配置 `APP_ACCESS_TOKEN` 作为单一访问令牌；配置后前端请求通过
`Authorization: Bearer ...` 访问 `/api/*`，本地 `development/test/local` 默认不启用。

## 不负责

- 世界对象生成逻辑
- 剧情结构逻辑
- 审稿逻辑
- 业务状态写入
