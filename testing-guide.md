# Testing Guide — 测试与 Review 规则

测试目录的局部约束见 `backend/tests/AGENTS.md`；Claude Code 通过同目录 `CLAUDE.md` 导入。
目标模块内部测试可按该文件直接检查 implementation，跨模块行为仍优先从 facade、DI port 或
HTTP 验证。

## Review Severity Levels

### P0 — Blocking (must fix before merge)

- AI output writes canonical without a user-confirmed automated pipeline, provenance, editable/rollback metadata, or tests
- API allows cross-novel_id data read/write
- SQL injection, XSS, API key leakage, arbitrary file read/write
- Prompt injection triggers dangerous backend operations
- author_only / hidden_truth exposed in character-perspective context
- Context Compiler has no budget control, dumps entire DB
- Dangerous operations (merge/delete/deprecate) have no confirmation
- LLM output not validated before insert

### P1 — Must fix before release

- Production module directly imports another module's models/repositories/services
- Context output too long, no budget control, unclear focus
- Candidates lack importance_score or suggested_action
- Memory proposals lack source, confidence, confirmation entry point
- RAG only does vector search, no hybrid/keyword/filter support
- Frontend only supports command bar, no button entry points
- Missing module-level basic tests
- Review only checks format, not logical risks

### P2 — Recommend optimize

- Layout polish, help text completeness, filter richness
- Command coverage, copy/export completeness, log detail

## Per-Module Tests (every module)

Three layers:
- **Repository**: basic CRUD, not found, empty update, pagination
- **Service**: business logic happy path, exception paths (not found → 404, invalid UUID → 422)
- **API** (via root `backend/conftest.py` `async_client`): HTTP happy path + error path

Account connection/global preference coverage and project preference/effective composition coverage share
`backend/tests/account_project_preferences/` and use owner-aligned canonical routes.

Evidence indexing/compilation 回归集中在 `backend/modules/evidence/`；
`backend/tests/unit/test_evidence_fusion_contract.py` 保证业务调用方只经
`modules.evidence.facade/contracts` 访问；`backend/tests/unit/test_retired_owner_paths.py`
保证已退场的 RAG、Context 与 Settings HTTP 前缀返回 404。

## Test execution layers

下列自动化 backend 质量 Make 目标在进入 `backend/` 后自行使用 `uv run --locked --extra ci --`
解析 Python `3.14.7` 与锁定 `ci` 工具链，不要求预先激活虚拟环境；首次运行仍要求 `uv` 与可用
缓存或网络。该工具链约定不改变各层列出的数据库、凭据或浏览器等外部前提。

| Command | Scope | External prerequisites |
|---|---|---|
| `make test` | Modules, infrastructure, deterministic eval toolkit tests, unit, SQLite integration, prompt contracts; narrow with `TESTS=<path>` or `ARGS=<pytest-args>` | None; excludes E2E, real LLM, external source data, and the optional Ragas adapter when the `eval` extra is absent |
| `make test-fast-coverage TEST_WORKERS=2` | Same fast layer with parallel production-code coverage and an 85% gate | None |
| `make eval-fast` | The same locked deterministic eval toolkit tests without remote model calls | Python 3.13 (override with `BACKEND_EVAL_PYTHON`); the locked `scikit-network` 0.33.5 currently fails to build with the local Python 3.14 macOS toolchain |
| `make eval-ask-world` | Ask World project/API contracts, then retrieval, citation-fixture, refusal and integrity thresholds | None; targeted API tests plus deterministic synthetic evidence, not a semantic-answer quality claim |
| `make eval-context-planner NOVEL_ID=<id> OUTPUT=<path>` | 冻结 RAG 数据上对比 task-direct 与确定性 Planner，输出 split/purpose、MRR/P@5/R@10、结果数、source hash、stale/跨项目与延迟 | 已建立同一冻结语料索引的本地项目；不调 LLM |
| `make eval-context-planner NOVEL_ID=<id> LLM_PLANNER=1 OUTPUT=<path>` | 在上述对比中增加 `planner-v2-llm`，仅向当前项目模型发送 dev split 中达到复杂度门槛的查询 | 显式付费/外部模型验收；train/test 不发送给 Planner |
| `uv --directory backend run pytest -q evals/tests/test_rp_context.py` | RP source context 对照账本与盲评汇总契约；只保存 corpus/scenario hash、SourceRangeRef 和 rubric | None；该测试不调用模型，也不代表用户验证或实际减少出戏 |
| `make docs-check` | Architecture registry, modules, ORM tables, API prefixes, AST-discovered `*tasks.py` handlers (including string constants), routes, Prompt/ADR inventory, links and Draw.io structure | Python 3.12 standard library only |
| `make docs-check BASE_REF=origin/main` | Full inventory plus current-branch document-impact coverage | Local `origin/main` ref |
| `make test-ci TEST_WORKERS=2` | Cross-stack local quality gate: docs, secrets, dependency audits, Ruff, deploy contracts, backend coverage/RuntimeWarning, and frontend Vitest | Locked backend/frontend dependencies; excludes PostgreSQL, browser, image, and paid/manual suites |
| `make test-deploy` | Deployment static/CLI contract tests in `deploy/tests`, including committed Alembic graph and pre-checkout migration compatibility cases | Self-contained: `uv` resolves Python 3.14.7 from `backend/.python-version`, locked `backend/uv.lock` `ci` dependencies, and backend pytest config; no external service |
| `make test-production-images` | Build the pinned backend/frontend production images; verify backend non-root/no-uv/no-pip/import and frontend nginx/assets | Docker daemon plus image registry access; intentionally outside `make test-ci` |
| `make secret-hygiene` | Tracked/indexed runtime env, private-key, and high-confidence credential gate | Git working tree; no Python dependency install required |
| `make audit-backend-deps` | Audit every package in `backend/uv.lock`, including optional extras; only two no-fix eval advisories use fix-aware exceptions | OSV advisory data and `uv`; Python 3.14/Linux target, with `--no-build` |
| `make audit-frontend-deps` | Audit `frontend-console/package-lock.json`; fail only on high/critical dependency advisories | npm registry/advisory data |
| `npm --prefix frontend-console run lint` | Production JS, Vue SFC, Vitest, Playwright, and build-config correctness / Vue essential rules | Locked frontend dependencies; no formatting gate |
| `E2E_DATABASE_URL='<dedicated-postgresql-url>' make test-e2e` | PostgreSQL/pgvector behavior | Explicit dedicated test database at Alembic head; fails fast if missing, non-dedicated, unavailable, or stale |
| `E2E_DATABASE_URL='<dedicated-postgresql-url>' make test-postgresql-critical` | Serial merge-gate subset: fresh migration, isolation, uniqueness, CAS and advisory-lock races | Explicit dedicated PostgreSQL 17 + pgvector database at Alembic head; workers=1, retries=0 |
| `RUN_E2E_TESTS=1 E2E_DATABASE_URL='<dedicated-postgresql-url>' uv --directory backend run pytest tests/e2e/test_rp_source_versions.py -m e2e` | RP source revision 并发唯一性、历史 chunk 共存、来源删除门禁与 consumer snapshot 生命周期 | Dedicated PostgreSQL at Alembic head |
| `RUN_E2E_TESTS=1 E2E_DATABASE_URL='<dedicated-postgresql-url>' uv run pytest tests/e2e/test_project_task_gate_concurrency.py -m "not real_llm and not external_data"` | Project delete vs atlas upload/cleanup race | Dedicated PostgreSQL at Alembic head |
| `RUN_E2E_TESTS=1 E2E_DATABASE_URL='<dedicated-postgresql-url>' uv run pytest tests/e2e/test_task_coalescing_concurrency.py -m e2e` | Keyed coalescing and concurrent operation-receipt uniqueness | Dedicated PostgreSQL at Alembic head |
| `DATABASE_URL='<dedicated-postgresql-url>' PW_REUSE_EXISTING_SERVER=0 npm --prefix frontend-console run test:e2e:functional -- --workers=1 --retries=0` | Complete functional browser regression | Fresh dedicated PostgreSQL, local private MinIO buckets, and Chromium; automated on frontend-related PRs and every main push; backend-only PRs use test:e2e:smoke |
| `DATABASE_URL='<dedicated-postgresql-url>' PW_REUSE_EXISTING_SERVER=0 npm --prefix frontend-console run test:e2e:functional -- interaction.spec.js --workers=1 --retries=0` | RP 作品复用、导入恢复、关键歧义、剧情锚点、两种身份、资料抽屉与 390px 键盘流 | Same fresh dedicated stack; network responses use synthetic fixtures |
| `npm --prefix frontend-console run test:e2e:functional -- themes.spec.js` | 本地主题资源、预览取消、持久化／配额失败、刷新／导出／删除、字体偏好与手机正文稳定性 | 同一专用 PostgreSQL 与全新服务门禁；不调用模型 |
| `DATABASE_URL='<dedicated-postgresql-url>' PW_REUSE_EXISTING_SERVER=0 npm --prefix frontend-console run test:e2e:map` | Focused local map regression, including touch/390px; already contained in the functional suite | Explicit dedicated PostgreSQL and fresh backend/frontend |
| `make test-real-llm` | Explicit SQLite real-model acceptance | Configured provider credentials |
| `cd backend && RUN_E2E_TESTS=1 RUN_REAL_LLM_TESTS=1 E2E_DATABASE_URL='<dedicated-postgresql-url>' uv run --locked --extra ci -- pytest tests/e2e/test_writing_conflict_real_llm.py -m 'e2e and real_llm'` | Writing conflict review and suggestion through queued task routes | Dedicated PostgreSQL with a verified owner provider connection; two paid calls |
| `RUN_MAP_ATLAS_LIVE_IMAGE=1 MAP_ATLAS_LIVE_OPENAI_API_KEY='<temporary-key>' make test-map-atlas-live-image` | One paid GPT Image 2 smoke image; never part of aggregate gates | Explicit cost approval flag and temporary OpenAI key |
| `RUN_INTERACTION_REAL_KIMI=1 KIMI_API_KEY='<temporary-key>' DEEPSEEK_API_KEY='<temporary-key>' make test-real-kimi` | Paid Kimi K3 account connection, balance, RP streaming/branch/summary, provider hot-switch, and fail-closed recovery gate | Explicit temporary Kimi Open Platform and DeepSeek keys; Kimi remains disabled outside the test process |
| `RUN_INTERACTION_LONG_CONTEXT_CALIBRATION=1 KIMI_LONG_CONTEXT_COST_APPROVED=1 KIMI_API_KEY='<temporary-key>' KIMI_CONTEXT_LIMIT_TOKENS='<official-limit>' E2E_DATABASE_URL='<dedicated-postgresql-url>' make test-interaction-long-context` | Paid Kimi usage-token calibration at seven sizes plus a real PostgreSQL 530K emergency-summary journey | Explicit cost approval, current official context limit, temporary Kimi key, and dedicated PostgreSQL at Alembic head |
| `E2E_DATABASE_URL='<dedicated-postgresql-url>' make test-manual REAL_SOURCE_PATH=/abs/path/novel.txt` | Real source corpus and PostgreSQL/real-model acceptance | Source path, dedicated PostgreSQL, and configured provider credentials |

### Recommended regression cadence

Use the smallest existing entry point that covers the change, then stop when that layer is
green. Do not run overlapping aggregate targets back-to-back.

1. **While editing**: run only the affected pytest or Vitest file. For a changed browser flow,
   use the existing `test:e2e:smoke` or `test:e2e:map` subset with a dedicated database.
2. **Before review**: backend-only changes run `make test` plus `make lint`; frontend-only
   changes run `npm run lint` and complete Vitest, with `npm run build` only when the bundle, entry points, or build
   configuration changed. Cross-stack, security, or CI changes run
   `make test-ci TEST_WORKERS=2` once; it already subsumes the fast backend and frontend Vitest
   layers, so do not precede it with `make test` or frontend Vitest.
3. **When the risk requires it**: schema or concurrency changes add the PostgreSQL critical
   subset; deployment or image changes add their existing contract target;    real-LLM, long-context, worker, and real-corpus suites remain explicit
   acceptance gates.
4. **Private image storage changes**: run `make test-deploy`, the affected world storage/
   cleanup tests, and an isolated MinIO initializer smoke with synthetic credentials. Verify
   both private bucket quotas, application-user access to only those buckets, and that the
   root user is absent from API/worker runtime configuration. Re-run the initializer to prove
   idempotence and verify versioning plus object-version deletion; never use a production env
   file for this smoke.

Every non-trivial branch still finishes with `make docs-check BASE_REF=origin/main` and
`git diff --check`. GitHub selects relevant checks on pull requests and runs every gate on the resulting `main`
push. Frontend-related PRs and main run the complete functional suite; backend-related PRs run smoke. Before release,
verify all main checks succeeded for the exact fixed SHA, including the full browser regression.

`pytest` uses the same fast test paths by default. Every marker is strict: use
`real_llm` for a remote provider call and `external_data` for a user-supplied
local corpus. Neither may enter the default fast layer.

The Ask World launch command is explicit release evidence in addition to the full
suite. It first runs the actual API contract tests, then emits an offline report
whose quality scope is limited to evidence ranking and dataset integrity. Neither
part stands in for human review of prose usefulness or factual synthesis. R01–R14
product behavior remains covered directly by the affected Pytest, Vitest, and
Playwright paths; duplicate replay data is not maintained without a runner.

The Kimi targets fail before collection when any required flag, key, cost
approval, context-limit value, or dedicated database URL is absent. They do not
silently skip, retry an ordinary story request, or enable Kimi for the normal
application process. The long-context calibration records only numeric
provider/model/usage/latency evidence in the ignored
`backend/.test-artifacts/kimi-context-calibration.json`; it never records the
synthetic prompt or story output.

PostgreSQL E2E additionally installs a function-loop-scoped global
`DatabaseManager` that is bound to the same explicit `E2E_DATABASE_URL` as the
fixture session. The URL must use PostgreSQL and name a dedicated database with
a standalone `audit`, `e2e`, or `test` marker; no default URL exists, and the
developer `ai_novel_engine` database is rejected before any engine is created.
The fixture compares normalized backend, host (including canonical IPv6), port,
and the exact database name, fails closed on any mismatch, and awaits engine
disposal before that test loop exits. While the isolated scope is active,
resetting, losing, or replacing the global manager also fails closed instead of
rebuilding it from ordinary application settings. This covers production paths
that intentionally open an independent session instead of using FastAPI's
overridden `get_db`; tests must not suppress async connection cleanup warnings
or silently fall back to the developer database.

### 前端重设计回归契约

前端回归以用户任务的功能等价、数据正确和适用操作的幂等性为验收标准。
允许改变入口、步骤、定位器、组件和 DOM 结构；定位方式是测试适配细节，不是产品合同。
鉴权、项目隔离、确认与采用、保存恢复、冲突处理、重复提交/重试防重以及基本可访问性仍须验证。
可访问性检查键盘可操作、语义名称、焦点管理、可读对比度和减少动态效果，不规定具体视觉实现。
主题包导入/导出、用户字体选择与地图坐标属于功能数据；可检查这些输入的运行效果，不把其样例推广为内置视觉常量。
截图像素、CSS 写法、固定尺寸、布局、断点与组件层级不作阻断门禁；窄屏/缩放只是操作环境样本。
旧 PNG 只作历史参考，失败截图和 trace 只供诊断，无需更新基线。
删除混合视觉测试前，先把有效功能断言迁入现有行为测试；已有等价覆盖则记录对应测试与断言。

### Continuous integration

GitHub Actions 在 pull request 与 `main` push 上并行运行三个职责清晰的主工作流：
`Backend CI` 包含 `Backend quality` 与 `PostgreSQL critical`，`Frontend CI` 包含
`Frontend unit quality` 与 `Frontend functional browser`，`Production Image CI` 包含
`Production image contract`。
每个质量 job checkout 完整历史后运行 `scripts/classify_ci_changes.py`。PR 比较事件中的
base/head 完整 SHA，删除和重命名前后路径都参与分类；读取失败直接阻断。main 始终全量。
PR 多类变更取并集：

| 路径 | 需要执行的质量检查 |
| --- | --- |
| 后端 tests 目录中的 test_*.py | 后端；tests/e2e 另加 PostgreSQL critical |
| 前端 tests 中的 JS/Vue | 前端 |
| 历史截图 PNG | 仅始终执行的检查；不比较像素、不要求重建 |
| 其他后端目录（包括共享 fixture/support） | 后端、PostgreSQL critical、浏览器冒烟、生产镜像 |
| 前端目录（除 Dockerfile） | 前端单测、完整功能浏览器回归、生产镜像（含构建）；CSS、主题、组件、入口、依赖及测试变更均覆盖全站用户任务 |
| 两个 Dockerfile 或 deploy 目录 | 后端及部署合同、生产镜像及恢复演练 |
| Markdown 文档 | 仅始终执行的检查；根 README.md 额外运行镜像 |
| CI、脚本、Makefile、其他未知路径 | 全部，浏览器使用完整功能套件 |

Markdown 规则优先于目录规则。文档门禁、secret hygiene 和 CodeQL 始终执行。
所有必需 job 名称保持不变，无关安装、测试及产物步骤跳过；runner 和 service container
仍会初始化。禁止用 workflow paths 过滤让必需检查保持 Pending。
前端及未知路径 PR 使用 `test:e2e:functional`，覆盖新版写作、作者工作区、主题与读者流程；
后端相关 PR 保留四文件 `test:e2e:smoke`，main 始终完整。均保持专用数据库、私有 MinIO、
workers=1、retries=0。全量结果失败时暂停发布，不能用截图更新、重试或删断言追认通过。

它们与独立的 `Architecture docs` 分开运行，因此前端或镜像失败不会再以
`Backend CI` 工作流失败呈现。后端快速 job checkout 后先用系统 Python 执行零依赖的 repository
secret hygiene gate，再安装 uv `0.12.3` 与 Python `3.14.7`，
先运行 `make audit-backend-deps`，随后通过 `backend/uv.lock` 安装窄 `ci` 依赖
（不安装本地 embedding 运行时），然后依次执行 `make lint`、`make test-deploy` 与
`make test-fast-coverage TEST_WORKERS=2 ARGS="-W error::RuntimeWarning"`。
仅 main push 在覆盖率门禁通过后还会以 `continue-on-error` 运行 `make eval-ask-world` 并始终上传 JSON
报告；它只提供离线证据排序与引用完整性诊断，不阻断 PR，也不代表模型语义回答质量。
这些 CI step 直接调用同一 Make target，由 target 自行解析锁定工具链，避免 CI 与本地走不同
的 pytest/Ruff 可执行文件。
架构文档 job 使用 Python 标准库相对 PR base SHA 验证当前清单和代码差异影响；普通实现变化仅提示，稳定契约等硬门禁命中时，未修改的必查文档
只有在 PR 模板逐项核对并提供无影响原因后才能通过。该 workflow 显式监听
`opened / synchronize / reopened / edited`，因此维护者补齐 Dependabot PR 的文档
影响说明后会用当前 PR 正文重新验证，无需修改 bot 生成的提交。
PostgreSQL job 使用锁定版本的 PostgreSQL 17 + pgvector 一次性 service container，按串行、
零重试规则执行 fresh migration、高风险事务契约，以及上传 201、工作稿保存 200/201、
地图 observation 201 和世界书投影任务响应后的跨 session 立即可见性契约，
并分别保留测试前、测试后的脱敏
JUnit/版本/Alembic/锁等待诊断；诊断查询自身有独立短超时，不会吞掉主体测试预算。完整
PostgreSQL E2E 由每日定时及手动发布前 workflow 执行，显式安装与服务端同主版本的
PostgreSQL 17 客户端以覆盖备份恢复演练，不包含真实 LLM 或外部数据。
Backend audit reads OSV advisory data for the complete lockfile, including the
optional `eval` extra. It uses `--no-build`, so the standalone audit does not build
source distributions just to read metadata. The only current fix-aware exceptions are the two
eval-only advisories with no published fixes: DiskCache unsafe pickle
deserialization (`GHSA-w8v5-vhqr-4h9v`) and Ragas multimodal Faithfulness SSRF
(`GHSA-95ww-475f-pr4f`). They are not permanent ignores: `--ignore-until-fixed`
causes a published fix to fail the gate again. Production does not install `eval`,
and the extra remains trusted/offline-only even though this project's adapter uses
text collection metrics with an isolated local Codex evaluator. Frontend job first uses
the SHA-pinned Node setup action with `frontend-console/.node-version` (`24.20.0` LTS) and
the committed lockfile cache, then uses `frontend-console/package-lock.json` to run `npm ci`, then
`npm audit --package-lock-only --audit-level=high`, ESLint and complete Vitest. The production
image job owns the production build. `Frontend functional browser` starts a fresh dedicated PostgreSQL, the Compose-managed private
MinIO buckets, and Chromium, then runs the
complete functional suite on frontend-related PRs and main (smoke only for backend-related PRs), with workers=1 and
retries=0, and retains
`frontend-console/test-results` failure diagnostics for 14 days. The existing smoke command is
reused inside the same browser job; `test:e2e:map` remains a focused local subset. Real-LLM and worker Playwright suites remain explicit/manual acceptance runs.
Visual review uses diagnostic screenshots and recordings; there is no visual comparison suite.
The backend
audit depends on OSV network data and the frontend audit on npm registry/advisory
data; both complement rather than replace builds and tests, and a passing audit is
not proof of zero dependency or supply-chain risk.
CodeQL separately analyzes GitHub Actions, JavaScript/TypeScript and Python with the
`security-extended` query suite on PRs, `main` pushes, weekly schedule and manual
dispatch. Its extended rules intentionally trade some precision for wider coverage:
a finding requires normal exploitability and reachability triage, not automatic
confirmation. Dependabot configuration opens staggered weekly version-update PRs
for workflow actions, backend uv, frontend npm and production Docker manifests;
minor/patch updates are grouped but majors stay independent. Coordinated manifest,
digest and lockfile changes still need the affected tests and image-contract review.
Workflow contract tests do not duplicate current action SHAs. They require every allowed action
to use a version-commented 40-character commit SHA and keep each action family on one SHA/version
across all workflow files, so Dependabot can update a pin without weakening supply-chain review.
Dependabot alerts and security updates are separate remote repository settings and
are not enabled merely by this version-update configuration.
secret hygiene gate 同时检查 Git index 的各 stage 和已跟踪工作区版本，拒绝运行时 `.env`、
常见私钥文件名、私钥块与高置信服务凭据；测试/文档中的显式占位值仅在受控路径豁免。
失败日志只包含安全化路径、规则名和不可逆短指纹，不输出凭据原文。等价本地入口是
`make secret-hygiene`；它不替代真实凭据发生泄露后的吊销、轮换和历史处置。
`make test` 直接复用 `pyproject.toml` 的测试路径和 marker 排除；覆盖率门禁只额外增加
单测试超时、`loadscope` 并行和 coverage 参数。coverage 只统计
`app/core/shared/infrastructure/modules` 中的生产 Python 文件，排除测试目录、pytest
支持的测试文件命名和 `conftest.py`，输出缺失行并要求总覆盖率不低于 85.0%。该检查不连接 PostgreSQL、真实
LLM 或本地语料；这些验收层仍按上表显式触发，且不继承 fast 层超时。仓库文件不会自动启用
远端 ruleset/分支保护，需单独配置；启用后，应把 `Architecture docs`、`Backend quality`、`PostgreSQL critical`、
`Frontend unit quality`、
`Frontend functional browser` 和 `Production image contract` 设为合并前必需状态检查；CodeQL
由 ruleset 的 code-scanning merge protection 阻断高严重度结果，不再重复登记三个矩阵状态。
`Production image contract` 独立执行 `make test-production-images`：它从固定 tag+digest
构建 backend/frontend 镜像，并在容器内确认 backend 非 root、没有 uv、可导入 app，以及
frontend 的 nginx 配置和入口资产都可用。它不归入本地 `make test-ci`，因为实际镜像拉取和构建
远重于默认快速门禁。tag 与 digest 必须成对评审和轮换；固定输入提高可复查性，但不同 Docker
builder 的层输出不承诺逐字节相同。
该 CI job 在 smoke 后为两份本地镜像生成 CycloneDX SBOM，验证 JSON 后作为 14 天 artifact
上传，再扫描并只阻断可修复的 HIGH/CRITICAL OS 或 library 漏洞。SBOM 仍保留未修复和低严重度
发现，便于审查；扫描通过并不证明镜像或供应链零风险。本地 `make test-production-images` 不运行
这些 CI SBOM/漏洞步骤。

生产 Compose 的容器收敛只覆盖第一方 `api`、`worker`、`frontend`、`migrate` 和
`account-maintenance`：它们使用只读根、`cap_drop: ALL` 与 `no-new-privileges`。backend
服务的唯一声明写路径是 `/tmp` tmpfs；frontend 的是 nginx-owned `/run` 与
`/var/cache/nginx` tmpfs。PostgreSQL 和 embedding 不继承这些尚未单独验证的设置。
`make test-production-images` 在同一受限运行时检查 UID、`CapEff` 为零、`NoNewPrivs: 1`、
只读应用/静态路径、backend tempfile 及真实 nginx health/asset 请求。该边界降低容器内
写入和提权面，并不消除应用、镜像、daemon 或宿主机风险；若发现未声明写路径，应保留证据并通过
固定-SHA 发布流程回滚，不得以放宽根文件系统作为临时修复。

`make test-deploy` 只验证部署文件、环境校验与 CLI 的静态合同，不启动 Compose、不会连接
外部服务，也不等同于真实发布或备份恢复演练。本地等价聚合入口是
`make test-ci TEST_WORKERS=2`；它不包含上述显式验收层。

`make format` 暂未纳入 CI：当前仓库仍有历史格式债务，应先在独立机械变更中形成干净
基线，避免新门禁因无关存量文件持续失败。

### Test setup pattern

Use the root `backend/conftest.py` SQLite fixture for normal tests. It imports
the ORM metadata and creates the schema once per test session; every test gets
an outer transaction plus a savepoint-backed `AsyncSession`, so application
`commit()` calls are rolled back before the next test. Module `conftest.py`
files should contain only module-specific factories and mocks:

```python
@pytest_asyncio.fixture
async def world_map(db_session: AsyncSession, project_novel_id: str):
    return await _create_default_map(db_session, project_novel_id)
```

测试 schema 中的 PostgreSQL `UUID` 类型由根 `conftest.py` 仅在 SQLite dialect 下编译为
`CHAR(32)`。不要删除这一测试适配：SQLite 会给未知的 `UUID` 类型名 NUMERIC affinity，
并可能把形如科学计数法的合法 UUID hex 转成浮点 `inf`；生产 PostgreSQL 仍使用原生
`UUID` DDL。

Fixture 使用者只通过测试函数参数名请求 fixture。不得使用
`from conftest import ...`、`from tests.conftest import ...` 或其他普通 Python
import 复用 fixture；这会让 `conftest` 的解析取决于 pytest 收集顺序。所有
`backend/modules/*/tests/` 目录必须包含 `__init__.py`，统一收集可用
`make test ARGS="--collect-only -q"` 快速验证。

### Test import convention

跨模块行为测试应优先通过 public 接口（facade + contracts / API / DI port）进行，而非直接 import 其他模块内部实现：

```
✅ 推荐: from modules.xxx.facade import some_function
❌ 避免: from modules.other.repositories import SomeRepository
❌ 避免: from modules.other.services import SomeService
```

理由：
- **测试验证的是行为而非实现** — facade 是稳定的公共接口，内部重构不影响测试
- **跨模块测试穿过稳定接口** — 调用方不应知道另一个模块的 repository/service 形状
- **本模块内部行为可以直接测** — repository 的复杂查询、service 状态机、错误路径和事务边界属于本模块实现，直接 import 本模块内部是可接受的
- **metadata import 是例外** — fixture / conftest 为注册 FK 模型导入 `modules.project.models` 等模型，不代表业务代码可跨模块依赖内部实现

Key points:
- Root conftest owns model registration, the shared schema, DI reset, and FastAPI dependency override cleanup.
- Each test starts with an empty logical database through transaction rollback; do not add per-module `create_all()` fixtures.
- Feature fixtures may import the concrete models they construct (for example `modules.story.outline_state.models` for `scenes` / `scene_spans`); `WritingDraft` itself has no `chapter_cards` FK.

### Mock conventions

给 `@patch` / `mock.patch` 的所有调用必须加 `autospec=True`，确保 mock 对象签名与被 mock 的 API 一致：

```python
# ✅ 正确
@patch("modules.world.services.SomeService.method", autospec=True)
# ❌ 错误 — 签名变化时不失败
@patch("modules.world.services.SomeService.method")
```

例外仅在 C 扩展等无法 autospec 的场景，在 patch 调用结束行注明 `# autospec-exempt: 具体原因`；空说明不通过。不得用例外规避可用的签名检查。

**禁止在生产代码中检测 Mock** — 不要写 `isinstance(db, Mock)` 守卫或 `from unittest.mock import Mock` 在生产 import。测试替身应通过 DI 注入（可选参数或 `Depends` override）传递，而非运行时类型检测改变生产逻辑。

### Fixture conventions

- `asyncio_mode = "auto"` 下异步 fixture 可使用 `@pytest.fixture` 或 `@pytest_asyncio.fixture`；用行为测试验证事务回滚、事件循环和资源释放，不冻结装饰器写法。
- `asyncio_mode = "auto"` 启用后，`@pytest.mark.asyncio` 是冗余装饰器。新测试无需添加；旧测试可逐步清理
- 模块级 fixture 应放在模块的 `conftest.py` 中；E2E 共用的 `ctx` fixture 应提取到 `e2e/conftest.py`，避免 20+ 次重复实现
- 静态结构门禁应通过 `tests.support.inventory` 共用缓存的 Python 文件、源码和 AST inventory；各门禁仍保持独立的文件筛选与断言，不合并安全规则
- PostgreSQL E2E 通用种子优先请求 `base_scene` / `full_scene` / `project_client` 等语义 fixture；专用扩展数据仍留在所属测试中

### Future subpackage test paths

`imports` and `world` may later split large internal service directories into subpackages such as `imports/parsing/`, `imports/workflow/`, `imports/entity_extraction/`, `imports/scene/` or `world/services/core/`, `world/services/map/`, `world/services/worldbuilding/`. When that happens, tests may follow the owning subpackage path to keep fixtures close to the implementation.

This does not relax module boundaries: cross-module behavior tests still go through facade/contracts/API/DI port, and production code still must not import another module's repositories/services/models directly.

## Key Integration Tests (in `tests/integration/`)

1. **Candidate/proposal review**: input text → generate candidates/proposals → dedup → confirm alias or preserve canonical auto-ingest provenance
2. **Character knowledge boundary**: character's unknown info not in compiled context
3. **Scene and structure generation**: schema validation passes and retains goal/conflict/must_not_happen/hook
4. **Structure review**: detects early reveal of hidden_truth
5. **Novel_id isolation**: project A API cannot read project B objects
6. **XSS protection**: `<script>` tags display as text, not executed
7. **Deep import Phase 2b alias/relation extraction**: Scene text + working entity index → append candidate alias metadata inline and create candidate relations without creating new entities. Required coverage:
   - schema normalization for alias confidence/type and relation strength
   - working index includes only `canonical` / `draft` / `candidate`, never `deprecated` / `ignored`
   - alias append is novel-scoped, normalized, idempotent, and stores `status/source/workflow_id/scene_id/confidence/quote/needs_review`
   - unresolved relation endpoints are skipped; created relations use `status="candidate"`
   - single-scene Phase 2b failures mark degraded diagnostics without aborting Phase 2a output
   - manual `world_alias_relation_extraction` tasks require `novel_id` and invoke the DI handler with chapter range / scene ids
   - frontend world object auto-extract panel exposes the secondary “补抽别名/关系” entry and disables it while extraction is running
8. **Authoring lifecycle**: `test_authoring_lifecycle.py` serially verifies import → imported chapter publish/index/snapshot → confirmed generation using imported evidence → explicit adoption → publish/index/snapshot → canonical retrieval. It must also prove foreign-novel evidence and project LLM credentials never enter the generation prompt.
9. **Recoverable author tasks**: operation receipt tests cover concurrent one-row enqueue, terminal reuse,
   request drift 409, project-scoped 404, exactly two transient attempts and immediate terminal handling
   for auth/quota/content/schema/source failures. Frontend tests cover persisted pre-submit receipt, 404
   no-replay recovery and page-local completion without island refresh.

## Optional local performance diagnostics

The [isolated performance runbook](docs/diagnostics/performance.md) covers synthetic
production-bundle browser measurements, public-auth API/SQL timings, task state,
and fixed-data memory observation. It is opt-in, uses a dedicated loopback PostgreSQL
database, and never substitutes mocked providers or small samples for real-model
latency or reliable p95/p99 claims. Keep performance runs separate from test load.
The [2026-09-07 baseline report](docs/diagnostics/2026-09-07-performance-baseline.md)
records results and their limits; this diagnostic does not add a latency CI gate.
The [alias optimization and input follow-up](docs/diagnostics/2026-09-07-alias-optimization-and-editor-input.md)
separates real clipboard gestures from automated `fill`, and records native IME as
unverified. `tests/e2e/test_world_alias_projection.py` checks the shared read path
with more than 1,000 objects using the explicit PostgreSQL E2E environment and `-m e2e`.

## Security Tests

- SQL injection search strings
- Cross-novel_id access
- XSS text display
- Oversized input
- Invalid enum values
- LLM output invalid JSON
- RAG top_k overflow

## Code Review Checklist

当进行 code review 时，检查以下常见错误：

### Python 陷阱
- `importance or 0.5` — 0.0 是 falsy，应使用 `is not None`
- SQLAlchemy ORM 模型上没有的属性（如 `entity.aliases` 不存在于 WorldEntity）
- `except Exception:` 吞掉数据库 flush 失败导致 session 中毒
- `dict.get("key", default)` 中 default 表达式可能被意外求值

### 跨模块
- 模块 API 是否验证 novel_id 隔离
- facade 是否导出所有新增函数到 `__init__.py`
- 新模块是否在 `app/main.py` 注册路由
- 新模块的模型是否在 root `backend/conftest.py` 导入

统一地图新增 `backend/modules/world/tests/test_map_structure*.py` 与
`frontend-console/tests/vue/map/MapStructureEditor.test.js`。PostgreSQL 定向门禁为
`tests/e2e/test_unified_map_concurrency.py`，验证 CAS、不可变内容、同节点 head 和节点生命周期；
真实浏览器 `map-structure.spec.js` 使用合成地图/PNG、专用 PostgreSQL 和私有 MinIO，
不调用付费模型。模型质量和付费图片效果必须通过各自显式实测报告，不能由上述结果代替。

RP 长期约定与max兼容性用例位于 interaction 的 services/prompts/tasks 测试、LLM能力/客户端测试、
`tests/e2e/test_rp_agreements.py` 和前端 InteractionView/interaction E2E。验收包括旧快照、零覆盖、
省略/清空、多次reducer、分支、并发、格式失败与30秒等待状态。工程测试不调用付费模型。

专项查证验收包含 `frontend-console/e2e/focused-evidence.spec.js` 的地图、副驾驶和对象
补全入口，及 `tests/e2e/test_focused_completion_concurrency.py` 的 PostgreSQL 两连接
字段漂移/撤销门禁。继续使用显式专用数据库与 fresh server；模型网络响应可用合成证据
替身，验证不等于付费真实模型效果或作者满意度。新增与填空的自动采用必须另覆盖
旧授权拒绝、混合置信度、来源过期和后续人工编辑保护。

## Agent 核心与项目助手验收（ADR-0023）

- `modules/assistant/tests` 覆盖身份/范围、成组预检/重放/部分重试、变化合并、提醒与事件游标；
  `infrastructure/llm/tests/test_agent_runtime.py` 与 `test_native_search.py` 验证同一 SDK 预算和协议。
- `tests/e2e/test_assistant_concurrency.py` 在独立 PostgreSQL 以两连接及真实 worker 验证批准、
  合并领取、故障后的累计预算；`test_assistant_review_runtime.py` 验证父助手直接调用领域
  只读复核的双 lease 与共享预算。模型输入输出为合成数据。
- `RUN_ASSISTANT_REAL_LLM=1 pytest infrastructure/llm/tests/test_agent_live.py -m real_llm`
  显式调用 DeepSeek，验证工具、保存后的历史续接、原生联网、流关闭；报告只含计数/用量/耗时，
  位于 `.test-artifacts/assistant-live-core.json`。未知费用不记为零，不能据此宣称 RP 质量通过。
- `playwright.assistant.config.js` 需要独立、带 `agent_e2e` 标记的本地 PostgreSQL、
  `PW_REUSE_EXISTING_SERVER=0`。真实 API 与 worker 由 test-only harness 启动，模型 IO 合成；
  检查确认、跨页/刷新恢复、窄屏和键盘。该 harness 在其他数据库/环境拒绝启动，不用于生产。
- 强提醒精确率、RP 人物可信度/连贯性需要冻结人工评测，实际采用率和复用意愿另行观察。

### 回归测试的精简边界

测试优先断言输入输出、失败路径和用户可见效果，不冻结 CSS 属性顺序、普通修辞、
CI 显示名称或重复的工具版本常量。新增 facade/Prompt 合同不应因完整集合相等而失败；
既有必要接口与合同仍检查存在性，导出与实现保持自洽。纯 mock 转发与 schema 测试不请求数据库 fixture。
前端遵守上方“前端重设计回归契约”，不维护 CSS 源码或像素门禁。
后端覆盖率阈值由 pyproject.toml 唯一配置为 85%，不可用重试或吞 warning 隐藏失败。

项目助手功能另由 `test:e2e:assistant` 使用已有的合成模型 harness 验证（专用库名含 `agent_e2e`）；普通 functional 不加载此用例。CI 两者都运行，仍无付费模型调用。
