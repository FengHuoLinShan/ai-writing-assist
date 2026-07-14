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

新增带 `novel_id` 的业务 LLM 服务必须使用 project facade 的 runtime seam，不能直接
构造 `LLMClient`、调用 `from_project_settings()` 或自行解析 profile。静态门禁会扫描
生产业务模块，并只允许已登记的 project runtime / project snapshot / 独立 embedding
窄例外；因此后续服务默认继承数据库全局 LLM 设置，而不会悄然回退成模块私有配置。

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
- `LLM_MAX_CONCURRENT_REQUESTS`：单进程共享的 LLM 并发上限
- `LLM_RATE_LIMIT_PER_MINUTE`：单进程共享的 provider RPM；本地/测试可为 `0`

`development/test/local` 可将 LLM RPM 设为 `0`；其他环境必须按实际 provider 配额
显式配置正值，否则 API、普通 task worker 和 `worker --reload` 监督进程均拒绝启动。
重载后的 worker 子进程会再次校验。该限制按进程执行，多个 API/worker 实例会共同放大
总吞吐，部署时必须按实例数拆分或核算 provider 总配额；代码不写死生产 RPM。

健康检查入口：

```bash
python scripts/check_llm.py
GET /api/health/llm
```

返回只包含 host、model、错误类型、延迟等脱敏诊断信息，不返回 API key。
常见 `error_kind` 包括 `dns_fake_ip`、`proxy_error`、`tls_error`、`auth_error`、
`rate_limit`、`timeout`、`provider_error`。

## 2. HTTP 响应边界与请求可观测性

应用最外层纯 ASGI middleware 为每个 HTTP 响应统一写入且只保留一份以下响应头：

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `X-Request-Time-Ms: <duration>`
- `Strict-Transport-Security: max-age=31536000`（仅权威 ASGI `scheme` 为 `https` 时）

边界会替换下游同名头，避免弱值或重复值绕过统一策略；HTTP 请求不会因为未经信任的
`X-Forwarded-Proto` 获得 HSTS。正式引入反向代理时，代理必须通过受信配置传递真实 scheme，
或由 TLS 终止层自行写入 HSTS。

该边界覆盖普通响应、稳定 500、流式输出、CORS 预检以及 access-token / XHR 门禁短路，
并保持 204/304 空响应语义。响应或流式输出结束后写一条结构化 access log；普通响应和 4xx
使用 INFO，5xx 与未处理异常使用 ERROR。默认及生产使用的非 DEBUG 模式下，未处理异常返回
统一 JSON 错误结构，并只记录一次异常日志和一次 access log；DEBUG 模式保留框架调试响应，
但仍经过统一响应头边界。

access log 只允许 method、FastAPI 路由模板、status、duration 和安全 `novel_id`。每个
HTTP 请求有独立日志作用域；只有 project facade 成功验证 active/context，或带项目路径参数的
路由成功返回后，才绑定规范化 UUID。未验证、非法或无项目请求统一使用安全占位符，不从原始
query/body/header 推断项目。实际 path 参数、请求体、header、token、异常消息、响应内容及
其他用户输入不得进入日志；未匹配路由或路由前短路统一记为 `<unresolved>`。畸形 method 或
route metadata 必须安全降级，不能形成日志注入。未知 500 只记录白名单异常类型和有界 frame
位置，不记录异常正文、cause chain 或源码行。

HTTP 请求在认证、CORS 和路由之前经过进程级 token bucket。限流身份只取 ASGI direct peer
地址，不读取 `X-Forwarded-For` 等未经信任的代理头；不同连接端口不会获得不同配额。
`OPTIONS` 不消耗配额，其他普通、认证失败、未匹配和健康检查请求均受限。超限返回 429、
固定 `{"detail":"Too many requests"}`、`Retry-After` 与 `Cache-Control: no-store`，并继续
经过外层安全响应头和 access log。

`development/test/local` 可用 `HTTP_RATE_LIMIT_PER_MINUTE=0` 显式关闭；其他环境启动时
必须提供正 RPM、正 burst 和正 bucket 容量，否则应用拒绝启动。该 limiter 按进程执行：
多 worker 会按进程数放大总配额，反向代理存在时 direct peer 也可能是代理本身，因此正式
部署必须结合 worker 数和可信代理边界设定配置。它限制单一 direct peer 的滥用，不等同于
多来源 DDoS 防护或全局连接池容量保证；聚合容量保护属于未来部署架构的独立决策。

## 3. 异步任务系统

基于 PostgreSQL 表 + 进程内 worker（FOR UPDATE SKIP LOCKED）。

### 任务类型

| 模块 | 当前注册处理器 |
|------|------|
| project | `smart_dedup_scan` |
| world | `world_entity_extraction`、`world_alias_relation_extraction`、`world_entity_fusion_suggestions`、`world_bible_projection_refresh`、`world_bible_synopsis_refresh` |
| outline | `plot_structure_generate`、`chapter_card_extraction`、`chapter_scene_generate`、`outline_analyze`、`outline_generate`、`outline_chapter_scenes_extract` |
| rag | `rag_index_chapter`、`rag_reindex_novel`、`rag_retry_embeddings` |
| writing | `publish_chapter`、`writing_generate`、`writing_conflict_ai_review` |
| imports | `deep_import`、`scene_auto_extraction`、`world_object_auto_extraction`、`plot_structure_auto_extraction` |

任务处理器由模块 `tasks.py` 在应用/worker 启动时注册；新增或移除处理器时应更新此表并保留
`async_tasks` 的兼容状态语义。

每个 worker attempt 使用独立日志作用域。claim 时即使 `meta.novel_id` 存在也只记录
`<unverified>`；组合根 project preflight 经 facade 确认项目存在后才绑定规范化 UUID，之后的
执行、完成、取消或失败日志共享该关联。缺少门禁、门禁失败或畸形 meta 不会产生可信项目 ID。
该关联仅覆盖当前进程内 HTTP 请求/worker attempt，不替代跨进程 trace/span。

### API

```
POST /api/tasks            # 提交任务
GET  /api/tasks/{id}       # 查询任务状态
POST /api/tasks/{id}/cancel # 取消任务
```

任务状态响应中的 `result` 只投影公开顶层字段。以下划线开头的顶层键属于 worker 的
私有 checkpoint/receipt：数据库、重试和 lifecycle 恢复路径保留原值，但
`GET /api/tasks/{id}` 不返回它们；业务 handler 不得把前端必需字段放入私有键。

通用 `POST /api/tasks` 不能绕过模块 API 的 request schema、确认和授权。业务任务默认
拒绝通用提交；只有注册时显式声明 Pydantic `generic_submit_schema` 的基础设施任务可走
该入口。校验错误只返回受控字段位置和错误类型，不回显提交值、动态 key 或密钥。

### 稳定 lifecycle seam 与提交 fence

本轮已收敛或新增的跨模块 lifecycle 操作通过
`infrastructure.tasks.contracts/facade` 使用窄接口，不新增对 `AsyncTask` ORM 的依赖。
deep-import orchestrator 与 World Bible projection coalescing 仍有已登记的直接 ORM
例外（见 2026-07-14 全量扫描报告 D-04 / D-07），后续应迁移且不得仿照扩张：

- `get_task_owner()` 只读取授权所需的 `novel_id`；
- `get_completed_task_payload()` 按 `task_id + task_type + novel_id + done` 返回冻结的
  完整 result、白名单 apply context 和 revision，`replace_completed_task_result()`
  以 revision CAS 保存采用结果；
- `list_running_task_types_for_novel()` 只返回指定项目/类型的运行中任务；
- `require_running_task_attempt()` 按 task type、owner、lease 与 attempt 锁定当前执行；
- 取消和永久删除使用 novel-scoped facade，不跨项目扫描或写入。

worker claim 使用 `FOR UPDATE SKIP LOCKED`，每次 attempt 生成新 `lease_id`。handler
session 的每次显式 checkpoint commit 和最终 commit 都在同一事务内执行
`project FOR SHARE -> running task + lease` fence；项目删除或 lease 丢失先线性化时，
当前业务写入与 checkpoint 一起回滚。慢 LLM/embedding/provider I/O 前如已发生 DB
读写，handler 必须先建立可恢复 checkpoint 释放事务，并在采用结果前重验适用来源。
这些基础设施 fence 不替代各业务任务自己的 source/profile/confirmation 校验。

## 不做

- 复杂分布式调度 / 优先级队列 / 任务 DAG / 定时任务系统
- Redis / Arq
