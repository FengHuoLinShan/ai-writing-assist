# Module: infrastructure / 基础设施模块

## 1. LLM 客户端

`infrastructure/llm/` 目录提供 OpenAI 兼容的 LLM 调用能力。
默认使用显式 HTTP transport，避免进程隐式继承系统代理；如需代理，配置
`LLM_PROXY_URL`，如需读取系统代理，显式设置 `LLM_TRUST_ENV=true`。

### 核心方法

```python
llm = LLMClient(provider_name="openai")

# novel-scoped 业务调用必须通过 project facade 管理 lifecycle
async with open_project_llm_client(db, novel_id) as llm:
    result = await run_managed_structured(...)

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

# 绑定 novel 的 chat client 会将 remote embedding 委托给独立 client
# 使 provider/model/base URL/API Key 继续由 EMBEDDING_* 边界决定

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

project runtime 创建的 client 带有 secret-free `runtime_scope`。managed helper
会自动把 `novel_id`、profile source 和脱敏 `profile_summary` 合并进 journal 的
`quality_stats.llm_runtime`；测试 fake 没有该属性时仍可按既有构造注入。
脱敏 summary 以 request 的实际 model/max_tokens/temperature/top_p 为准，
同时可保留 profile 默认 model 作 `default_model`。task worker 用
task-local context collector 聚合这些记录，并在成功、失败和取消路径
都合并到 result 的 `managed_llm_steps`；记录不包含 API Key、完整
Base URL/query、prompt 或正文。

step envelope 可表达 read / suggest / draft / act-with-confirmation 权限，但当前 harness
明确拒绝 `autonomous`。它记录确定性执行与输出守门，不实现 agent loop、工具自主选择或
跨模块业务编排。

Embedding、streaming 和 `generate_simple()` 不是本 harness 的默认迁移范围。

### 配置与健康检查

业务调用的项目级 LLM 配置由 `modules.project.facade.open_project_llm_client()`
加载，先按字段物化 effective settings，再使用
`infrastructure.llm.profiles.resolve_llm_profile()` 构造 profile。生产字段来源
优先级固定为：

```text
project settings.llm > global settings.llm > system default
```

`test override` 只用于显式测试注入，不是生产项目之间的回退来源。

resolver 返回 effective api_key / base_url / model / timeout / max_tokens /
temperature / top_p / extra，并保留字段来源。日志、JSONL、health check 和前端响应
只能使用脱敏 summary：`provider_id`、`label`、`model`、`base_url_host`、
`timeout`、`max_tokens`、`api_key_configured`、`sources`、`extra_keys`。API Key
不得进入日志、错误信息、任务结果或前端响应。
provider transport 的请求/失败日志只记录 endpoint host，即使 Base URL
包含 query 也不输出完整 URL。
task worker 对异常先执行 `redact_diagnostic`再写入 task status API 与
错误日志；数据库错误统一转成公开可展示的稳定消息，不输出可能
包含请求 URL/query 的 exception cause traceback。

可恢复任务不把 effective API Key 或完整 endpoint 写入 task meta。
project facade 在提交时生成 secret-free execution snapshot，冻结
model/非 secret 参数/字段来源和领域设置；deep-import 的
项目值、环境覆盖与代码默认也在此时物化为显式值。恢复时读取当前 Key，
允许 Key 轮换，但 endpoint 或 provider-specific extra 的 hash 变化会
fail closed。

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

| 模块 | 当前注册处理器 |
|------|------|
| project | `smart_dedup_scan` |
| world | `world_entity_extraction`、`world_alias_relation_extraction`、`world_entity_fusion_suggestions`、`world_bible_projection_refresh` |
| outline | `plot_structure_generate`、`chapter_card_extraction`、`chapter_scene_generate`、`outline_analyze`、`outline_generate`、`outline_chapter_scenes_extract` |
| rag | `rag_index_chapter`、`rag_reindex_novel`、`rag_retry_embeddings` |
| writing | `publish_chapter`、`writing_generate`、`writing_conflict_ai_review` |
| imports | `deep_import`、`scene_auto_extraction`、`world_object_auto_extraction`、`plot_structure_auto_extraction` |

任务处理器由模块 `tasks.py` 在应用/worker 启动时注册；新增或移除处理器时应更新此表并保留
`async_tasks` 的兼容状态语义。

### API

```
POST /api/tasks            # 提交任务
GET  /api/tasks/{id}       # 查询任务状态
POST /api/tasks/{id}/cancel # 取消任务
```

## 不做

- 复杂分布式调度 / 优先级队列 / 任务 DAG / 定时任务系统
- Redis / Arq
