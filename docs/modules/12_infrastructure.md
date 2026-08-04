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

业务调用由 `modules.project.facade.open_project_llm_client()` 根据项目 owner 加载当前
已验证的账户 provider/model/Key，再使用
`infrastructure.llm.profiles.resolve_llm_profile()` 构造 profile。项目设置只叠加
非 secret 工作流参数，不能覆盖账户连接。

`test override` 只用于显式测试注入，不是生产项目之间的回退来源。

新增带 `novel_id` 的业务 LLM 服务必须使用 project facade 的 runtime seam，不能直接
构造 `LLMClient`、调用 `from_project_settings()` 或自行解析 profile。静态门禁会扫描
生产业务模块，并只允许已登记的 project runtime / project snapshot / 独立 embedding
窄例外；因此后续服务使用同一账户连接，不会悄然回退成模块私有配置。

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
provider/model/非 secret 参数/字段来源和领域设置；deep-import 的
项目值、环境覆盖与代码默认也在此时物化为显式值。恢复时读取 snapshot 原 provider
当前轮换后的账户 Key；账户切到其他模板不要求重建任务，但原 provider Key 被清除、
endpoint 或 provider-specific extra 的 hash 变化时 fail closed。

业务供应商 profile 不从 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL` 等环境变量
继承。当前账户模板默认是官方 DeepSeek：
`https://api.deepseek.com` + `deepseek-v4-flash`；没有已验证 Key 时 fail closed。

- `LLM_TRUST_ENV`：是否允许 httpx/OpenAI SDK 读取系统代理环境，默认 `false`
- `LLM_PROXY_URL`：显式代理地址，默认空
- `LLM_HEALTH_REQUIRED`：深度导入启动前是否要求 LLM health 通过，默认 `true`
- `LLM_RETRY_MAX_ATTEMPTS` / `LLM_RETRY_BASE_DELAY` / `LLM_RETRY_MAX_DELAY`：LLM 重试预算
- `LLM_MAX_CONCURRENT_REQUESTS`：单进程共享的 LLM 并发上限
- `LLM_RATE_LIMIT_PER_MINUTE`：单进程共享的 provider RPM；所有环境均可设为 `0`
  关闭额外 RPM 门禁。公开部署若由用户在账户设置中提供自己的 LLM 连接，可依赖各
  provider 的账户配额而不叠加全局 RPM，但仍应保留并发上限保护服务器资源。

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

基础部署健康检查 `GET /api/health` 只探测数据库，并在服务端以 2 秒 deadline 包住 session
获取和 `SELECT 1`。超时会取消该数据库操作、按既有脱敏 warning 路径返回原有的
`503 {status: degraded, database: unreachable, version, app_name}`；成功时仍返回同一四字段的
200 healthy 形状。生产 Compose 和 shared release/restore health gate 的 HTTP client timeout 是
3 秒，因此服务端会先给出可判定的 degraded 结果；该 deadline 不适用于 `/api/health/llm`。

生产 PostgreSQL 备份在 production operation lock 内以两份唯一的私有 staging 文件生成并校验，再
发布 `.dump` 与 `.sha256` 完整 pair；同一 UTC timestamp 的既有 dump 或 sidecar（包括 symlink）
会被拒绝，避免覆盖。可捕获的失败和信号只清理当前或遗留的 staging 文件，以及本次发布未完成的精确
half-pair，不会删除已完成 pair。完成的 pair 一经本地完成即按既有本地 retention 清理；其后的 restic
不可用、上传或 forget 失败仍保留新 pair。
这些脚本合同不表示外部 restic、B2 或 Healthchecks 服务已在当前环境完成验证。

systemd 的 backup/account-maintenance oneshot 分别以 4 小时/1 小时作为保守病态 `TimeoutStartSec`，
并使用 `TimeoutStopSec=2m`、`KillMode=control-group`：超时会让 service 失败，先给 shell/Docker CLI 子进程
TERM/cleanup 窗口，再由 systemd 结束整个 control group；Healthchecks `/fail` 与 missed ping 仍承担告警。
进程终止后 OS 会释放共享 operation lock。
它们 `Wants` 并 `After=network-online.target`，仅保证启动排序，不证明 Internet、B2 或 restic 可达。数值不是
SLA，应依据观测运行时间通过已评审 systemd drop-in 调整；仍需外部演练 Docker daemon/容器终止行为，本合同不表示
该演练已完成。

release、restore、backup、account-maintenance 与 runtime health 都以
`deploy/.state/production-operation.lock` 的 exclusive `flock` 作同主机协调。mutating scripts 首次获取锁会
以固定、不可由项目环境覆盖的 300 秒上限等待；到期仍被占用时继续以既有 held 错误 fail closed。runtime health
首次获取遇到有效但繁忙的锁时则只输出一条 bounded、无 secret 的 skip diagnostic 并以成功退出，不读取环境或
finalized release state、不运行 Git/Docker/curl，也不发送 Healthchecks `/start`、success 或 `/fail` ping。
获取成功后会通过继承 FD 的 reentry verification 持锁直到本机、embedding 与公网验证全部结束，避免健康检查与
变更脚本交叉使用不同 checkout/Compose 状态。runtime service 的既有 5 分钟 `TimeoutStartSec` 和 timer schedule
不变；operation lock 持有导致的 skip 依赖外部 Healthchecks missed-ping/grace 继续暴露过长停机或维护，而不是
把维护无限隐藏。该锁仅覆盖合作的同主机脚本，不是分布式、全局或跨主机互斥；本合同不表示外部 production 或
Healthchecks 已实际验证。

`deploy/backups/` 是 backup/restore 的私有文件系统边界。两个脚本都会在读取、清理或创建
任何备份内容之前，以原子创建或目录描述符打开校验最终目录组件：它必须不是 symlink、必须为
当前用户拥有的目录、权限必须精确为 `0700`。当前用户拥有的宽松既有目录会被收紧为 `0700`；
descriptor 与路径的 device/inode 和元数据会在打开后复查，任何替换、类型或所有者不一致都会
fail closed。该合同仅描述仓库脚本，不表示生产目录或外部备份已实际验证。

release/restore 以 finalized 的 `deploy/.state/current-release` 与 `current-commit` 成对状态作为
已部署 commit 的唯一来源，而不信任可能残留在失败目标上的 checkout/分支。失败或取消且尚未写完
最终 `current-release` 时，脚本只会切回该 finalized checkout，并在本次可能已启动新 application
services 时停止它们。cleanup trap 本身不会 reset/clean 工作树、额外写入或恢复数据库、重启旧服务或
改写 finalized state；但在数据库替换或 migration 后失败的底层操作可能已经改库，服务会保持停止并需
人工恢复。状态缺失、损坏、不匹配或 symlink 会 fail closed，需人工介入；首次发布才允许两份状态均
不存在并以当前、仍可达 `origin/main` 的 HEAD 作为 fallback。这是脚本合同，不表示生产环境或外部服务
已经验证。

runtime health 与 account maintenance 在 Compose 操作前从同一 validated finalized pair 导出本地镜像的
`RELEASE_ID`（完整 commit 的前 12 位），不读取 drifted checkout 的 HEAD。若 `.state` 存在，必须先通过
当前用户拥有、非 symlink、权限精确 `0700` 的私有目录检查；状态不安全、不完整或不匹配时 fail closed。
first release 在 `current-release` 与 `current-commit` 两个 finalized 文件都不存在时使用当前、
`origin/main` 可达的 HEAD；若 `.state` 目录本身不存在，该只读路径不会创建状态目录。该合同不表示
生产状态已经实际验证。

restore 在 fetch/check-out 前先执行当前 checkout 的 environment validator，并在切换到 target commit 后、
image build、archive list、确认提示、quiesce 或数据库工作前重新执行 target 自带 validator。target 校验失败时，
既有 cleanup 只恢复 finalized checkout/state，不执行 Docker 操作或进入 maintenance window。该合同不表示
生产环境已经实际验证。

release/restore 在 fetch 前及 target checkout 后都执行 strict deployment-checkout guard：任一 tracked/staged/
unmerged 路径都会 fail closed。只有 untracked/ignored operational data 可使用 `deploy/.env.production`、
`deploy/.state`（及 descendants）和 `deploy/backups`（及 descendants）这一 exact allowlist，且这些路径绝不允许被
Git 跟踪。两次 checkout 以 invocation-scoped Git hooks
禁用，避免本地 hook 先于 guard 执行。target validator 后，脚本用 `git archive` 从固定 40 位目标 commit 的 tracked
tree materialize 私有临时 build snapshot，并以临时 Compose override 让所有第一方 build context 指向它；runtime env、
state、backups、ignored cache 与其他 worktree 文件不进入 Docker context。snapshot/override 在本次操作结束后清理。
这只固定 source provenance，不保证 base image、build network、toolchain 或 Docker builder 的 byte-identical 输出，
也不表示外部生产环境已经验证。

release 在 target preflight 与 API/frontend build 后、pre-migration snapshot 前先停止 API/frontend/worker
（worker 按既有 2 分钟 grace drain），然后才 reconcile target PostgreSQL 与 embedding，并执行 fresh database
guard、embedding contract check、snapshot、migration 和新服务启动。Docker Compose 在依赖镜像或配置变更时可能
recreate 容器，因此该 reconcile 必须在旧 application services drain 后；maintenance window 相应覆盖这些检查，
停机可能长于仅 migration 阶段。restore 在确认与二次 checksum 后、safety backup 和数据库替换前也先完成该
quiesce。停止失败会 fail closed 并阻断后续数据库工作；quiesce 后失败会保持 application services 停止并需人工
恢复。它以发布/恢复期间作者和读者短暂不可用换取避免旧代码与新 schema 或已替换依赖容器重叠，不是 zero-downtime
部署，也不表示外部生产演练已经验证。

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

HTTP 请求在认证、CORS 和路由之前经过进程级 token bucket。限流身份只取最终 ASGI scope client
地址，middleware 自身不解析 `X-Forwarded-For` 等代理头；不同连接端口不会获得不同配额。生产
Tunnel 路径以 Cloudflare 为公网信任边界，OpenResty 对 API/frontend upstream 用
`CF-Connecting-IP` 覆盖（不追加）这两个 forwarding headers，Uvicorn 才可据 edge-sanitized XFF
规范化 scope。直接 loopback 属于受信 host scope；缺少 `CF-Connecting-IP` 时请求安全地共享 proxy
bucket。这不是分布式或全局 DDoS 防护，也不表示当前外部 Cloudflare 配置已被本仓库验证。
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
| world | `world_alias_relation_extraction`、`world_entity_fusion_suggestions`、`world_bible_projection_refresh`、`world_bible_synopsis_refresh` |
| outline | `plot_structure_generate`、`chapter_card_extraction`、`chapter_scene_generate`、`outline_analyze`、`outline_generate` |
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
独立 heartbeat 同样按 running lease 更新心跳与 handler 的最新百分比进度，但不写
业务 result/meta，也不提交 handler 事务。
这些基础设施 fence 不替代各业务任务自己的 source/profile/confirmation 校验。

生产 worker 另有不触及 task 状态的 control-loop liveness：组合根在每次 `run_forever()`
控制循环开始时原子写入 `/tmp` monotonic marker；Docker health 与 release/restore/runtime
共享 `python infrastructure/tasks/liveness.py`，要求 PID 1 argv token 为 `run_worker.py` 且
marker 不超过 30 秒。它只证明 worker 控制循环近期取得执行权；per-task lease heartbeat
仍负责 task progress、lease fence 和 stale recovery，二者不可互相替代。

生产 SIGTERM 只在 `run_worker.py` 组合根转换为 `TaskWorker.stop()`：worker 随后停止新 claim 并
drain 已领取任务，通用 worker 不感知操作系统信号。Compose 的 `stop_grace_period: 2m` 是 drain 的
外层时限；到期后的 SIGKILL 走既有 lease heartbeat/stale recovery 崩溃恢复，不保证长任务完成。

## 不做

- 复杂分布式调度 / 优先级队列 / 任务 DAG / 定时任务系统
- Redis / Arq
