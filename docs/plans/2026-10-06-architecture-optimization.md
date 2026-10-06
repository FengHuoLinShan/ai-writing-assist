# 架构优化计划（2026-10-06）

日期：2026-10-06。状态：**计划，未实施**（AO-12 已转为正确性修复单独实施）。本轮用户要求核验
`output/architecture-report.html`（不入库，`.gitignore` 覆盖 `/output/`）并写架构优化计划；
没有修改实现、生成 migration、提交、推送或部署。

基线：分支 `codex/review-remediation-20261006`，HEAD `af20f1a2a`，另有当日全库审查整改的
未提交 WIP（world 仓储、语义评审重试等 11 个文件）。下文数字均为该工作树的只读实测；
实施前须在新 HEAD 上重算，不得直接沿用。

**复核（2026-10-06，`main` = `77620459d`，PR #199 合入后）**：阶段 0 已完成。按同一口径重算，
§6 的依赖图（90 边、33/17 双向对、导入语句 321/572、world core↔worldbuilding 23/27）、
7 个超 3000 行生产文件和 28 处路由级 XHR 依赖均与基线相同。PR #199 未改动 `main.py`、
`run_worker.py`、`core/crud.py`、`deploy/`（测试 fixture 除外）和导入门脚本，§2、§3 结论不变，
仅个别行号顺移，已就地更正。AO-12 已由用户裁定，见该项。

## 1. 结论

报告的总体框架（模块化单体、PostgreSQL 承载队列与向量、Vue 孤岛 + bridge、受控 LLM
工作流、固定 SHA 发布）与代码一致，技术栈无须更换。报告有近 30 处数字或描述偏差（§2.1），
多数是计数口径或细节问题，其中三处影响架构判断：

1. 报告称“边界由机器守护”。实际 `scripts/check_module_imports.py` 只校验导入**形态**
   （必须经 facade/contracts），不校验**方向**。12 个模块间有 90 条有向依赖边，57 个有依赖的
   模块对中 33 对双向，17 对在顶层 import 就双向；另有 572 条函数内延迟导入掩盖循环。
   现有 ADR 只承认 outline/writing 一对双向依赖。
2. 报告称 worker 启动前执行 `wait_for_schema_current()`。实际只有 `--reload` 开发路径调用，
   生产 `python run_worker.py` 不做 schema 校验，依赖 `release.sh` 先迁移后起服务。
3. 报告称生产 Compose“全部”只读 + `cap_drop: ALL` + `no-new-privileges`。实际 10 个服务中
   只有 5 个第一方服务满足；postgres、embedding、minio、minio-init 三项均无。

因此本计划的重点是：先用棘轮门禁冻结依赖方向，再逐对解环；按职责拆分 world 等超大聚合；
补齐运行时与部署不变量；最后收敛已证明等价的横切重复。不做微服务化、换队列、换前端栈。

## 2. 报告核验

核验方式：脚本计数（行数、表、迁移、契约、路由、组件、测试），加 4 个只读子代理分组核对
语义断言。主会话复算了依赖图、表数、文件规模，并逐条抽查子代理的关键结论。

### 2.1 偏差

| 区域 | 报告说法 | 实测 | 证据 |
|---|---|---|---|
| 基线 | 分支 `codex/ring-worldbook-import`，1726 次提交 | 当前分支 `codex/review-remediation-20261006`，1728 次 | `git rev-list --count HEAD` |
| 测试规模 | 后端测试 267,427 行 | 约 249,614 行（模块内测试 + `backend/tests`） | 口径可能含 evals |
| 任务 | 51 个 handler，约 39 种 task_type | 56 个 handler，56 种 task_type（一对一） | `make docs-check` 清单；`infrastructure/tasks/registry.py:90` 禁重复 |
| 任务队列 | 三个部分唯一索引 | 两个部分唯一索引（pending/running），第三个是非唯一普通索引 | `infrastructure/tasks/models.py:44-62` |
| 任务队列 | lease + heartbeat 判 stale | `lease_id` 只是 fence token，无 TTL；stale 只看 `heartbeat_at`/`started_at` | `models.py:136`，`lifecycle.py:1272-1289` |
| Worker | 启动前 `wait_for_schema_current()` | 仅 `--reload` 路径调用 | `backend/run_worker.py:156-160,193-197` |
| 中间件 | 图 2：认证 → 安全 → CORS → 限流 | 请求进入顺序：Timing（安全头）→ 限流 → ServerError → CORS → AccountAuth → ApiSecurity（Bearer/XHR） | `backend/app/main.py:486-640` 注册顺序，后加先执行 |
| 文档开关 | 生产 public 模式关闭 docs | 条件是 `auth_mode == "public"`，与 `app_env` 无关 | `main.py:323-326` |
| 配置校验 | 6 个 fail-closed 校验器 | 数量对；S3 校验惰性调用、LLM 限流只查负数，非启动期 fail-closed | `core/config.py:114-266` |
| 404 统一 | novel_id 不匹配一律 404 | 仅 `CrudService._assert_found_in_novel` 约定，无全局实现 | `core/crud.py:190-204` |
| CrudService | 删除降级为 deprecated | 仅对象有 `status` 才软删，否则硬删（如 Event）；仅 10 个子类 | `core/crud.py:164-183` |
| LLM | 五级线性 JSON 修复链 | 五个函数都在，但前四个是解析内部的回退分支，`_repair_structured_format` 是再发一次 LLM 请求 | `infrastructure/llm/client.py:281,1345` |
| LLM | 成本路由在 LLMClient | 在 `agent_step_harness.py:765-789`，决策在 `modules/project/model_routing.py` | — |
| LLM | provenance 写入 `managed_llm_steps` 表 | 无此表，是 task result/meta 的 JSON 键 | `agent_step_harness.py:41`，`tasks/worker.py:955-958` |
| 向量 | 镜像构建后 `check_embedding.py` 校验 ONNX | 在 `release.sh:160` 与 `runtime_health.sh:27` 调用，探测的是 HTTP 端点；生产默认 TEI 容器（`EMBEDDING_PROVIDER=openai`），BGE ONNX 子进程只在 `bge_onnx` 时启用 | `deploy/compose.production.yml:55-58,148-156` |
| world | contracts 30+ 协议 | 35 个类，其中 Protocol 2 个 | `modules/world/contracts.py:361,572` |
| world | services/core 17、worldbuilding 31、map_* 13 | 19、34、15 | 目录计数（不含 `__init__`） |
| story | 7 个任务常量；facade 48 项 | 8 个常量；`__all__` 47 项 + `*outline_state` 展开约 91 名 | `story/outline_state/generation.py:33-36`，`story/facade.py:391` |
| project | facade 33 个函数 | 31 个（另 9 个再导出） | `modules/project/facade.py` |
| evolution | contracts 最厚 | 第二（world 635 > evolution 494 > collaboration 394） | — |
| assistant | operations 合并 14 组 | 17 组展开 | `bootstrap.py:188-208` |
| 前端 | api.js 42 个命名空间 | 19 个顶层命名空间 + 1 个嵌套，共 573 个方法 | 运行时加载统计 |
| 前端 | 11 × `*Island.js` | 10 个文件，`settingsIslands.js` 含 2 个孤岛，合计 11 个孤岛 | `frontend-console/vue/` |
| 后端测试 | 模块内约 368 个测试文件 | 339 个 `test_*.py`；368 为目录内全部 `.py` | — |
| 部署 | 15 个服务 + 5 个卷 | 10 个服务、3 个卷、2 个网络 | `deploy/compose.production.yml` |
| 部署 | 全部服务三项加固 | 仅 api/worker/frontend/migrate/account-maintenance；searxng 无只读 | 同上 |
| 发布 | 两个 trap | 一个 handler（`:108`），两处解除 | `deploy/scripts/release.sh` |
| CI | 多数 workflow 仅 push 触发 | 5 个为 `pull_request` + `push(main)`；PG E2E 仅 schedule/dispatch；codeql 另含定时 | `.github/workflows/` |
| ADR | 39 项，另 9 份专题 | 38 个文件：30 个编号 ADR、0009 附录、7 份专题 | `docs/adr/` |
| ADR | ADR-0003 由 ADR-0009 调整 | 由 ADR-0012 取代 | `docs/adr/0003-leaflet-for-map-viewport.md:3` |

### 2.2 已核实一致

非测试后端 285,748 行（报告 285,610，差异在 WIP 量级）；组合根 42 个具名服务（报告“约 40”）；
85% 覆盖门（`backend/pyproject.toml:155`）；文件规模门阈值；12 个模块的源码/测试文件数与表数；
147 个 `__tablename__`（145 + `async_tasks` + 测试基类）；89 个迁移、单一 head
`20261005_world_revision_metadata`；177 条 API 契约；16 条路由与四个兼容重定向；167 个 `.vue`、
295 个 vue 文件；状态 12 键与 Proxy 通知链；bridge/ESLint 边界；`mountIsland` 视图契约；
bootstrap 281 行、17 个 models 模块、单一注册点；容器 API 语义；ORM Mixin；跨模块导入门
12 模块 / 8 豁免；熔断 256 桶、重试截止、预算信封与脱敏函数；ManagedLLMStep 拒绝
autonomous；BGE 单例批处理与 ONNX 回退；连接池参数；Dockerfile 钉版与非 root；三个 systemd
timer；`release.sh` 步骤顺序；7 个 workflow；68 个 Make target、21 个 eval；8 个 Playwright 配置
（base 工厂 + 6 个变体 + 默认）；测试分层与付费门禁自锁；`testing-guide.md` 51KB。

报告第 15 节“需要留意”中 world 规模、evolution/collaboration 建设中、工程接线不等于质量
验收三点成立。

## 3. 现状问题

### 3.1 模块依赖方向不受约束（最高优先级）

依赖图按生产代码 AST 统计（`modules.<other>` 的任意导入，含函数内导入）：

- 90 条有向边，132 条可能边中占 68%；66 个模块对中 57 对有依赖，33 对双向。
- 顶层双向 17 对：account↔assistant、account↔project、assistant↔evidence、
  assistant↔local_agent、assistant↔project、assistant↔story、assistant↔writing、
  collaboration↔evidence、collaboration↔story、collaboration↔writing、evidence↔story、
  evidence↔writing、interaction↔local_agent、project↔story、project↔world、project↔writing、
  story↔world。
- 跨模块导入语句：顶层 321 条，函数内 572 条。函数内导入多数为规避循环。
- DI 只有约 49 处 `container.get`，对比约 850 处 facade/contracts 引用。DI 没有承担解环职责，
  与 `core/container.py` 文档声称的目的不符。

成因可分三类，处理方式不同：

1. **插件式 SPI 反向依赖**。各领域的 `assistant_*_tools.py` 与 `forecast.py` 向 assistant
   提供工具/前瞻事实，同时 import `modules.assistant.facade`（`require_operation_targets`、
   `run_discussion_scope`、`AssistantSessionService`、`lock_background_slot` 等）。
   领域 → assistant 的导入约 70% 来自这类文件。而 assistant 的 teams/forecast/service
   又直接调用各领域 facade，于是形成环。
2. **身份根模块承担业务聚合**。`project` 是隔离根，却在 `workspace_service.py`、`services.py`、
   `smart_dedup.py`、`assistant_*tool*.py`、`forecast.py` 中顶层 import world/story/writing/
   assistant。`account/forecast.py` 同理反向依赖 assistant 与 project。
3. **领域核心互相调用**。story↔world、evidence↔story、evidence↔writing、
   collaboration↔story/evidence/writing、interaction↔local_agent。

world 模块内部有同样问题：`services/core` → `services/worldbuilding` 23 条导入语句，
反方向 27 条，例如 `core/entity_service.py`、`dedup_service.py` 在函数内导入
`worldbuilding.world_validation_service`。这与 `docs/adr/world-services-subpackage-layout.md`
的分区意图相悖。

### 3.2 超大聚合与 facade 变厚

超过 3000 行的生产文件共 7 个：
- `world/services/worldbuilding/world_generation_center_service.py` 5232 行（等于基线）
- `world/schemas.py` 5031 行
- `world/api.py` 4170 行
- `writing/services.py` 4166 行
- `interaction/services.py` 3287 行
- `story/outline_state/scene_workbench.py` 3093 行
- `frontend-console/api.js` 3116 行

world 生产代码约 7.8 万行，53 张表。`world/api.py` 一个文件承载 15 组以上路由，其中
library、entities、bible 各 13 个端点，另有 characters、relations、events、canon 等。

facade 违背“仅适配与委托”的例子：

- `project/facade.py:417-523` 直接写 `select`/`delete`，含 `pg_advisory_xact_lock` 与账户
  清理编排。
- `assistant/facade.py:54` `submit_comment_proposals` 内建会话、拼 prompt。
- `evidence/indexing/facade.py:100` 自行聚合计数并生成中文告警。
- `evidence/compilation/facade.py` 有约 30 参数的纯转发函数（如 `confirm_context`）。

### 3.3 运行时与部署不变量缺口

- 生产 worker 不校验 schema head（见 §1）。API lifespan 的 pgvector 探测失败只告警
  （`app/main.py:228-243`）。
- ORM 与迁移的一致性只靠人工 `alembic check`。2026-10-04 的 world-edit-history G0 记录为零漂移，
  但 9 月多份任务记录都出现过漂移，CI 没有对应门禁。
- 第三方容器（postgres、embedding、minio、minio-init）未加固。
- MinIO 对象不在备份范围（`deploy/scripts/backup.sh` 只备 `pg_dump`）。这是 2026-09-12 提案
  A8 的遗留项，仍待产品决定 RPO/RTO。
- 生产 embedding 由 TEI 容器提供 HTTP 服务（同一 `BAAI/bge-base-zh-v1.5` 模型），
  `BgeOnnxWorker` 只在 `EMBEDDING_PROVIDER=bge_onnx` 时启用。架构报告把 BGE ONNX 子进程
  描述为主路径；两条路径的验证对象也不一致。

### 3.4 横切实现重复

- XHR 写操作校验重复：`_ApiSecurityMiddleware` 已对所有 `/api/` 写方法强制
  `X-Requested-With`（`main.py:447-481`），7 个 API 文件仍挂 28 处
  `Depends(require_xhr_request)`。`AccountAuthMiddleware`（`account/middleware.py:253-262`）
  对演示请求另加同源校验，语义更严，不属于重复。
- DI 字符串键无类型（`get(name) -> Any`）。键前缀 rag/outline/context/memory 与模块名不一致；
  `_Registration` 已退化为透传包装。
- 共享件已存在，但各模块仍自带本地包装：
  - `infrastructure/stable_hash.py` 只有 23 处引用，另有 72 个生产文件自带 `sort_keys` +
    `sha256`；
  - 统一底座 `run_managed_structured` 已有 55 处调用，imports/world/evolution 仍有自带的结构化
    调用包装。
- 作者迁移的 plan/apply/rollback 在 world、story、spreadsheet 三处并行实现。

### 3.5 前端基建

- `api.js` 3116 行，573 个方法挂在一个对象上，并混用 `contractFetch` 与裸 `request`。
- classic 脚本清单在 `index.html:16-27` 与 `vite.config.js:13-23` 各维护一份。
- `vue/shell/shellServices.js:14-18` 直接读 `globalThis.appState/router/api/toast`，绕过
  ESLint 的 `no-restricted-globals`（该规则只拦裸标识符）。

## 4. 原则与非目标

- 保留 FastAPI + PostgreSQL（队列、pgvector）+ Vue 3 孤岛。不拆微服务，不引入 Redis/Celery，
  不引入 Vue Router/Pinia，不做全仓 TypeScript 或强制类型门禁，不重写 ORM，不 squash 迁移。
- **先立门禁再重构**：先用棘轮冻结现状，禁止新增依赖边和新增双向对，再逐对削减。
  门禁只允许数字下降，与 `check_file_sizes.py` 的基线策略一致。
- 拆分以职责和依赖方向为依据，不以行数为唯一理由。HTTP wire shape、`novel_id`/owner 隔离、
  领域确认、confirmation 指纹、CAS 与发布合同保持原样。
- hash/指纹只合并字节级等价的实现；领域版本化的指纹名称与格式不改，避免旧 confirmation、
  幂等键失效（沿用 2026-09-12 提案 A5 的约束）。
- 每个工作项独立分支、独立 PR、可单独回退；按 `testing-guide.md` 运行受影响模块测试与门禁。

## 5. 工作项

编号 AO-n。优先级 P1 先做；“需授权”项本计划不构成授权。

### 阶段 0：前置

**已完成**。全库审查 11 项 P1 整改经 PR #199 合入 `main`（`77620459d`）；§6 基线已在该提交上
重算，数字未变，可直接作为 AO-1 门禁的初始值。

### 阶段 1：门禁与运行时不变量（P1，低风险）

**AO-1 依赖方向棘轮门禁。**
- **做法**：扩展 `scripts/check_module_imports.py`，在现有形态校验之外，统计模块级有向边（含
  函数内导入）与顶层双向对。基线以字典形式写在脚本内：新增边或新增顶层双向对即失败，基线只许
  下降。同时在 `docs/architecture/README.md` 写明目标分层：
  - L0 account
  - L1 project、local_agent
  - L2 world、story、evidence、writing
  - L3 imports、evolution、interaction
  - L4 assistant、collaboration

  高层经 facade/contracts 调低层；低层调高层只能经 contracts 中的纯 SPI 类型或 bootstrap
  注册的 DI port。L2 内部的方向在 AO-5 逐对裁定。
- **验收**：在 `repo-gates` 中运行；人为新增一条边、一个顶层双向对的负例均失败；当前基线通过。

**AO-2 运行时不变量。**
- **做法**：
  - 生产 worker 启动时 fail-closed 校验 schema head。复用 `backend/scripts/dev_schema_guard.py` 的
    检测逻辑，生产路径不等待、直接失败。
  - API lifespan 的 pgvector 缺失在 production 失败退出，开发环境仍只告警。
  - 在 PostgreSQL critical CI job 迁移到 head 后加 `alembic check`。
  - 修正 `deploy/systemd/ai-writing-account-maintenance.timer:2` 的 Description：写的是
    “every day”，实际调度为 `OnCalendar=hourly`。
- **验收**：
  - schema 落后时 worker 拒绝启动，有单测；
  - 缺 pgvector 时 production 拒绝启动；
  - 人为制造 ORM 漂移时 CI 失败；
  - `make test-deploy` 通过。
- **注意**：先确认 CI 的 PG 库迁移到 head 后 `alembic check` 为零漂移。若有漂移，先单独修正，
  不在门禁 PR 里顺带生成 migration。
  - 调用方式会影响结果。`tests/e2e/test_00_fresh_migrations.py` 用 `python -m alembic check`，
    2026-10-06 实测零漂移。
  - alembic 1.20 的 `alembic` 命令行入口会额外加载 `checkconstraint_byname` 比较。它在同一个库上
    报出 9 项既有 CHECK 约束差异操作：
    - `assistant_forecast_candidates` 有 3 个约束、`collaboration_runs`/`collaboration_work_items`
      各 1 个约束，只存在于迁移，ORM 中没有；
    - `world_library_favorites`/`recents` 的约束名与 ORM 单复数不一致。
  - 门禁需固定调用方式，并先裁定这些差异是修正还是排除。

### 阶段 2：解环（P1/P2，按对一个 PR）

**AO-3 assistant/forecast 插件 SPI 下沉（P1）。**
- **做法**：领域插件文件需要的纯类型与无状态 helper（`AssistantOperation`、
  `ForecastDomainFact`、`require_operation_targets` 等），在确认无副作用后移入
  `assistant/contracts` 或其 SPI 子模块。领域插件需要的运行期服务（`AssistantSessionService`、
  `run_discussion_scope`、`lock_background_slot`）改由 bootstrap 注册的 DI port 注入。
  操作注册仍只在组合根。
- **验收**：领域 → `modules.assistant.facade` 导入为 0。涉及 assistant 的 6 个顶层双向对中，
  由插件 SPI 引起的部分清零，其余（如 evidence、local_agent 的非插件调用）并入 AO-5。
  assistant 及各领域工具测试、项目助手浏览器用例通过。

**AO-4 身份根去业务聚合（P1）。**
- **做法**：
  - `project/workspace_service.py` 与 `services.py` 的统计聚合改为 `project.contracts` 声明的
    provider 协议，由 world/story/writing 在 bootstrap 注册实现。
  - `smart_dedup.py` 跨 world/story 编排，移到其实际 owner：先核对调用方，再决定迁到 world
    还是 assistant。
  - `account/forecast.py`、`project/forecast.py` 随 AO-3 一并处理。
  - `project/facade.py:417-523` 的 SQL 与锁编排下沉到 service。
- **验收**：project 无顶层 import world/story/writing/evidence/assistant；account 无顶层 import
  assistant/project；作品档案首页、去重、账户清理的现有测试与浏览器链通过；项目隔离 404
  用例不变。

**AO-5 领域核心逐对裁定（P2）。**
- **做法**：对 story↔world、evidence↔story、evidence↔writing、
  collaboration↔story/evidence/writing、interaction↔local_agent 逐对确定 owner 方向。
  把 `docs/adr/outline-writing-bidirectional-dependency.md` 扩展为通用的“模块依赖方向” ADR，
  记录每对的方向与理由。反方向调用改为 DI port 或已有的事件 seam（如 `source.changed`）。
  world 内部同样处理：`services/core` 不得导入 `worldbuilding`，校验钩子改为注入。
- **验收**：顶层双向对 17 → 0；双向对总数 33 → 不高于 15（棘轮逐步下调）；函数内跨模块导入
  逐 PR 减少；受影响模块测试与 PG critical 通过。

### 阶段 3：按职责拆分（P2，行为不变）

**AO-6 world API/schema 按子域拆分。**
- **做法**：
  - `world/api.py` 拆为 `world/api/` 包，每个子域（library、entities、bible、characters、
    relations、events、canon …）一个 `APIRouter`，前缀不变。
  - `world/schemas.py` 按子域拆分，原文件保留再导出，调用方逐步迁移。
  - `world_generation_center_service.py` 先读清阶段边界，再按阶段拆分。
- **验收**：拆分前后 OpenAPI 文档的路由、方法、请求/响应模型零差异（用脚本对比
  `app.openapi()`）；world 全量测试通过；三个文件退出告警，基线同步下调。

**AO-7 其余超大服务。**
`writing/services.py`、`interaction/services.py`、`scene_workbench.py` 在下次实质改动时按同一
方法拆分，不单独开批。

**AO-8 facade 回归薄层。**
- **做法**：
  - `assistant/facade.py:54` 的编排移入 service；
  - `evidence/indexing/facade.py:100` 的状态聚合移入 service；
  - `evidence/compilation/facade.py` 的 30 参数转发改为传单个请求 dataclass。
  - 在 AO-1 门禁中加一条 AST 检查：`facade.py` 不得出现 `select(`、`text(` 或直接 session 写操作。
- **验收**：facade 检查通过；Evidence compilation/indexing 测试、confirmation 指纹固定样本
  不变。

### 阶段 4：横切收敛（P2/P3）

**AO-9 XHR 单一闸门（P2，安全相关）。**
- **做法**：新增测试，枚举全部 `/api` 写路由，断言缺 `X-Requested-With` 时返回 403，并确认
  不存在 `/api` 之外的写路由。测试通过后，移除 28 处 `Depends(require_xhr_request)`。
  演示请求的同源校验保留。
- **验收**：路由枚举测试覆盖所有写路由；安全中间件测试与浏览器写操作通过。不得削弱任何
  路径的保护。

**AO-10 DI 键类型化（P3）。**
- **做法**：引入 `ServiceKey[T]` 常量与类型化 `get`；旧字符串键保留一个过渡期别名，删除
  `_Registration` 透传层。
- **说明**：不引入强制类型门禁，目的是消除拼写错误并让 IDE 可导航。
- **验收**：启动时校验所有声明的键均已注册；DI 测试通过。

**AO-11 已证明等价的重复收敛（P3）。**
- **做法**：
  - 本地 hash 实现先用固定输入做字节比较，只把完全等价的迁到 `stable_hash`；
  - 结构化 LLM 包装仅在语义相同时改用 `run_managed_structured`；
  - 作者迁移的 plan/apply/rollback 先评估三处是否共享协议，结论写入任务记录后再决定是否抽象。
- **范围**：回执类型不统一，因为语义不同。

**AO-12 CrudService 删除语义复核（已裁定，转正确性修复）。**
10 个 `CrudService` 子类中只有 Event 无 `status`，会被硬删。用户裁定 Event 属于“已采用对象
默认保留历史、不硬删”的范围，对齐 EntityRelation 先例：`events` 加 `status` 列（默认
`canonical`），删除改置 `deprecated`，`EventRepository._active_conditions()` 追加
`Event.status == "canonical"`。按正确性修复单独分支实施，不进重构批。PR #199 的 `0997f767a`
曾删除 `EventService.delete` 中不可达的软删分支、把测试改为断言硬删，本修复会反转这两处。
实施分支 `codex/event-soft-delete`（迁移 `20261006_event_soft_delete`）。除 `_active_conditions()`
外，以下读取点也只认 canonical：service 的 get/update、`world_background._event_summaries`、
`entity_fusion` 的扩展载荷（排除 `status` 键，保持既有指纹不变），以及类型转换的
`event_extension`/`event_location` 阻断计数。主键即 `entity_id`，所以对同一对象再次 create
会复活原行，已有未删除扩展时返回 409（原先是主键冲突 500）。
`EventService.delete` 仍只处理扩展行，不废弃 CoreEntity，这一点保持原语义。

### 阶段 5：前端基建（P2/P3）

**AO-13 api.js 按命名空间拆分（P2）。**
- **做法**：按命名空间拆为 `api/<domain>.js` 模块，由 `api.js` 组装同一 `api` 对象；新代码
  统一走 `contractFetch`。
- **验收**：对象键集合与方法签名快照不变；前端单测、lint/build 与 functional 浏览器套件通过；
  `api.js` 退出告警。

**AO-14 classic 清单单一来源与全局旁路（P3）。**
- **做法**：`vite.config.js` 从 `index.html` 解析 classic 清单，或反向生成，并加一致性测试。
  ESLint 增加 `no-restricted-properties`，禁止 `vue/**` 读取 `globalThis`/`window` 上的
  api/appState/router/toast；`shellServices.js` 改走 bridge。
- **验收**：清单漂移测试失败可复现；lint 通过。

### 阶段 6：部署与数据保护（需发布授权）

**AO-15 第三方容器加固。**
- **做法**：postgres、embedding、minio、minio-init 加 `cap_drop: [ALL]`，按需 `cap_add`，并加
  `no-new-privileges`；镜像支持时改只读并为可写路径挂 tmpfs。
- **验收**：`make test-production-images`、`make test-deploy` 通过；隔离环境恢复演练与健康检查
  通过。生产发布另行授权。

**AO-16 MinIO 对象备份。**
沿用 2026-09-12 提案 A8：先由产品确定 RPO/RTO 与是否外发，再设计 DB 引用与对象的一致备份
批次。

**AO-17 embedding 生产路径澄清（P3）。**
- **做法**：确认 TEI HTTP 为生产唯一路径，BGE ONNX 子进程仅作离线/开发路径或删除。更新
  `infrastructure/embedding` README 与相关文档。
- **验收**：`check_embedding.py` 的验证对象与生产路径一致。

## 6. 度量基线与目标

| 指标 | 基线（2026-10-06） | 目标 | 门禁 |
|---|---|---|---|
| 模块间有向依赖边 | 90 | 只降不升 | AO-1 |
| 双向模块对 / 顶层双向 | 33 / 17 | ≤ 15 / 0 | AO-1 |
| 函数内跨模块导入语句 | 572 | 逐 PR 下降 | AO-1 报告 |
| world core↔worldbuilding 导入 | 23 / 27 | core→worldbuilding 为 0 | AO-1 扩展 |
| 超 3000 行生产文件 | 7 | ≤ 3 | `check_file_sizes.py` |
| facade 内直接 SQL | ≥ 1 处（project） | 0 | AO-8 |
| 路由级重复 XHR 依赖 | 28 处 | 0（中间件为唯一闸门） | AO-9 |
| 三项加固的 Compose 服务 | 5 / 10 | 9 / 10（minio-init 视镜像而定） | AO-15 |
| ORM/迁移漂移 | 人工核对 | CI 自动 | AO-2 |

## 7. 顺序与交付

推荐顺序：阶段 0 → AO-1、AO-2 → AO-3、AO-4 → AO-6、AO-8、AO-9 → AO-5（持续）→
AO-13 → 其余 P3。阶段 6 与产品决定并行推进，不阻塞代码工作。

- 每项从最新 `origin/main` 建 `codex/<slug>` 分支，PR 合入。公共契约、facade、跨模块调用变化
  须同步模块 README、`docs/architecture/README.md` 与 ADR，并在收尾运行
  `make docs-check BASE_REF=origin/main`。
- AO-1 至 AO-14 属于内部重构，不改对外契约，但仍需用户明确开始实施。AO-12 已裁定，作为
  正确性修复单独交付；AO-15、AO-16 涉及生产与数据，需发布授权。
- 预计跨多个会话，开始实施时在 `.agent/tasks/` 建主任务记录。

## 8. 与既有工作的关系

- **2026-09-12 架构改进提案**（`.agent/tasks/full-codebase-review/architecture-improvement-proposal.md`）：
  - A7 已修复：生产模块中无特定作品名；
  - A4 的漂移至 2026-10-04 已归零，本计划用 AO-2 防止回退；
  - A5 的约束由 AO-11 继承；
  - A8 转为 AO-16；
  - A1–A3、A6、A9 本轮未复核，不在此改判。
- **2026-10-06 全库代码审查**（`docs/reviews/2026-10-06-full-codebase-review.md`）：P1/P2 为正确性
  整改，不在本计划重复。11 项 P1 已随 PR #199 合入，阶段 0 完成；P2 状态以审查报告为准。
- **CI 优化计划**（`docs/plans/2026-10-04-ci-optimization.md`）独立推进。AO-1、AO-2 新增的门禁
  应放入现有 `repo-gates` 与 PG critical job，不新增 workflow。
- **架构报告**位于 `output/`，不入库。如需修订，按 §2.1 更新数字和描述，并在第 15 节补充
  §3.1 的依赖方向结论。
