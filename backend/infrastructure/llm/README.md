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
└── retry.py        # 重试逻辑（指数退避）
```

## 职责

- 管理不同模型 provider
- 支持普通 JSON 调用
- 支持流式输出
- 支持重试
- 支持结构化输出修复
- 支持项目级 OpenAI-compatible LLM Profile
- 记录 token 和调用耗时

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

# 简化调用
text = await client.generate_simple(system, user)
```

### 项目级 LLM Profile

前端可通过 project 模块维护 `projects.settings.llm`，字段包括：

- `provider_id` — 供应商模板 ID，如 `deepseek` / `kimi` / `openrouter`
- `label` — 前端显示名称
- `base_url` — OpenAI-compatible Base URL
- `model` — 默认模型名
- `api_key` — 写入字段；API 响应必须脱敏，不得回显

业务模块若要使用项目级配置，应通过项目上下文读取 `settings`，再构造客户端：

```python
client = LLMClient.from_project_settings(project_context.settings)
```

缺失字段会回退到 `core.config.Settings` 中的全局 `LLM_*` 环境配置，旧部署方式继续可用。

## 不负责

- 世界对象生成逻辑
- 剧情结构逻辑
- 审稿逻辑
- 业务状态写入
