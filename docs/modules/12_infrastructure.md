# Module: infrastructure / 基础设施模块

## 1. LLM 客户端

`infrastructure/llm/` 目录提供 OpenAI 兼容的 LLM 调用能力。
默认使用显式 HTTP transport，避免进程隐式继承系统代理；如需代理，配置
`LLM_PROXY_URL`，如需读取系统代理，显式设置 `LLM_TRUST_ENV=true`。

### 核心方法

```python
llm = LLMClient(provider_name="openai")

# 使用项目级 LLM Profile（project.settings.llm）
llm = LLMClient.from_project_settings(project_context.settings)

# 普通调用
resp = await llm.generate(request)

# 结构化 JSON（Pydantic 校验 + 自动修复）
result = await llm.generate_structured(request, MySchema, max_fix_attempts=2)

# 业务 text / structured generation 默认通过受控 step 包装
resp = await run_managed_generate(llm, request, step_name="module.flow.generate")
result = await run_managed_structured(
    llm,
    request,
    MySchema,
    step_name="module.flow.structured",
)

# 流式输出
async for chunk in llm.generate_stream(request): ...

# 简写（字符串入参，字符串出参）
text = await llm.generate_simple(system_prompt, user_prompt)

# Embedding 生成（单文本 → list[float]，文本列表 → list[list[float]]）
embedding = await llm.generate_embedding(text)

# 切换 Provider（关闭旧连接，创建新连接）
await llm.switch_provider("openai", base_url="...")

# 关闭 Provider（释放 HTTP 连接）
await llm.close()

# 获取 Provider 状态
stats = await llm.get_usage_stats()
```

### 受控 LLM Step Harness

`infrastructure.llm.agent_step_harness` 提供 `ManagedLLMStep`、
`OutputGuard`、`ContextBudgetGuard` 以及 `run_managed_generate()` /
`run_managed_structured()`。业务模块的普通文本生成和结构化生成应通过这两个
helper 进入，以统一 step name、journal、timeout 和错误分类。

helper 不改变 `LLMClient` 的 provider/retry/structured repair 行为：结构化 JSON
修复仍由 `LLMClient.generate_structured()` 执行，失败时重新抛出原始异常实例，
由调用方保留现有 fallback 或状态更新逻辑。`context_budget` 默认不自动截断
request messages；需要裁剪时显式使用 `ContextBudgetGuard`。

Embedding、streaming 和 `generate_simple()` 不是本 harness 的默认迁移范围。

### 配置与健康检查

业务调用的项目级 LLM 配置由 `infrastructure.llm.profiles.resolve_llm_profile()`
解析，优先级固定为：

```text
project settings.llm > test override > code default
```

resolver 返回 effective api_key / base_url / model / timeout / max_tokens /
temperature / top_p / extra，并保留字段来源。日志、JSONL、health check 和前端响应
只能使用脱敏 summary：`provider_id`、`label`、`model`、`base_url_host`、
`timeout`、`max_tokens`、`api_key_configured`、`sources`、`extra_keys`。API Key
不得进入日志、错误信息、任务结果或前端响应。

业务供应商 profile 不再从 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL` 等环境变量
继承。项目上下文会物化项目 > 全局默认 > 系统默认的 LLM 设置；系统默认是官方
DeepSeek：`https://api.deepseek.com` + `deepseek-v4-flash`。

- `LLM_TRUST_ENV`：是否允许 httpx/OpenAI SDK 读取系统代理环境，默认 `false`
- `LLM_PROXY_URL`：显式代理地址，默认空
- `LLM_HEALTH_REQUIRED`：深度导入启动前是否要求 LLM health 通过，默认 `true`
- `LLM_RETRY_MAX_ATTEMPTS` / `LLM_RETRY_BASE_DELAY` / `LLM_RETRY_MAX_DELAY`：LLM 重试预算

健康检查入口：

```bash
python scripts/check_llm.py
GET /api/health/llm
```

返回只包含 host、model、错误类型、延迟等脱敏诊断信息，不返回 API key。
常见 `error_kind` 包括 `dns_fake_ip`、`proxy_error`、`tls_error`、`auth_error`、
`rate_limit`、`timeout`、`provider_error`。

## 2. 异步任务系统

基于 PostgreSQL 表 + 进程内 worker（FOR UPDATE SKIP LOCKED）。

### 任务类型

| 处理器 | 模块 | 说明 |
|--------|------|------|
| `world_entity_extraction` | world | 从章节正文抽取世界对象并按当前 world 规则入库 |
| `plot_structure_generate` | outline | 从正文生成剧情线+篇章纲 |
| `rag_index_chapter` | rag | 单章 RAG 索引 |
| `rag_reindex_novel` | rag | 全量/范围重建项目索引 |
| `publish_chapter` | writing | 发布章节草稿并触发后续索引/记忆流程 |
| `deep_import` | imports | 深度导入流水线（Scene 切分 → 实体提取 → 结构分析） |

### API

```
POST /api/tasks            # 提交任务
GET  /api/tasks/{id}       # 查询任务状态
POST /api/tasks/{id}/cancel # 取消任务
```

## 不做

- 复杂分布式调度 / 优先级队列 / 任务 DAG / 定时任务系统
- Redis / Arq
