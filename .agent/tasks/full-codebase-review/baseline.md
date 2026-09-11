# W0 基线记录（全代码库优化审查）

生成：2026-09-11 18:2x +08:00，主 Agent。本文是 P0 出口产物；后续槽位审查以本文与
`coverage-ledger.csv` 为基线事实源。

## 1. Git 基线与 WIP

- 分支 `main`，HEAD `e7d0b8d5b`（bulk selection 清理已合入）；`git fetch origin` 后
  `origin/main` = `2c462f2c7`，本地领先 1 个未推送提交。与计划 §10.1 一致。
- 未提交 WIP（归属他任务，审查时只读并单独标注，不纳入优化候选的归属）：
  - `backend/modules/imports/api.py`、`backend/modules/imports/tests/test_import_api.py` — 导入审查减负任务
  - `frontend-console/styles.css` — 前端改动
  - `.agent/TASKS.md`、`.agent/tasks/code-simplification-audit.md` — 任务记录维护
  - 未跟踪：本审查计划文件、`ui-size-audit.md`、`.agent/tasks/2026/T-20260911-promo-recording-readiness/`

## 2. 覆盖账本

- 文件：`coverage-ledger.csv`；2453 个 Git 跟踪文件全部归属，与 `git ls-files -z` 比对
  无重复、无遗漏、无未归属。
- 生成方式：`git ls-files -s -z` 逐路径按规则映射主单元/槽位，指纹取 index blob SHA。
  归属规则（优先级序）：alembic 与模块内 `models*/repositories*` → R13/F4（横切唯一归属，
  模块槽位只引用）；`backend/modules/<mod>` → 对应 R03–R09；`backend/app|core|shared`、
  `backend/run_worker.py`、`infrastructure/schema_comparison.py` → F1；`backend/infrastructure/`、
  `backend/prompts/`、`docs/prompts/` → F2；前端壳（根 JS、vue/shell|bridge|composables|shared|auth、
  ui、islands、`frontend-console/shared`）→ F3；`vue/views|components|theme`、themes、prototypes、
  `views/` 遗留、styles/editorial CSS → D8*；`backend/tests`、conftest、`backend/evals` → E1；
  `frontend-console/tests` → E2；e2e、deploy/tests、playwright 配置 → E3；构建/依赖/部署
  （Makefile、锁文件、Docker、deploy、.github、前端构建配置）→ F5；docs、tools、scripts、
  workflows、.agent、工具历史目录（`.claude/.opencode/.playwright-mcp/.superpowers`）、
  `backend/.test-logs`、`backend/backend` → F6。
- 槽位文件数：F1=26，F2=83，F3=74，F4=91，F5=64，F6=695；D1=55，D2*=157，D3*=107，
  D4=34，D5*=107，D6*=113，D7=53，D8*=221，E1=199，E2=187，E3=187。

## 3. 入口 / 任务 / 模型清单（可再生成）

- HTTP 入口：`backend/app/main.py:754-773` 注册 18+ 路由（9 个业务模块 api.py +
  legal/debug/world_map_atlas/memory/tasks 等）；docs-check 报告 15 条前端路由、9 个业务模块。
- 任务注册：`@task_handler` 装饰器（`backend/infrastructure/tasks/registry.py`），docs-check
  统计 47 个 handler；imports 7 个 handler 均为 `recovery_policy="manual_resume"`。
- 模型：docs-check 统计 114 张 ORM 表；权威清单随 F4（R13）审查产出。
- 前端挂载：11 个 island 入口（`frontend-console/vue/*Island.js`）+ `mountIsland.js`。
- ADR 31 份。

## 4. 测试能力清单

- 后端：`make test`（默认 fast 层）、`make test-fast-coverage`、`make test-e2e`（需显式
  E2E_DATABASE_URL）、`make test-postgresql-critical`、`make test-real-llm`（显式付费）、
  `make test-ci`（docs-check+secret-hygiene+audit+lint+test-deploy）、eval-* 系列。
- 前端：`npm run lint`、`npm test`（vitest 全量）、`npm run build`、
  `npm run test:e2e:functional|smoke|visual|worker|real-llm`。
- 部署：`make test-deploy`、`make test-production-images`、`make test-restore-drill-real`。

## 5. 门禁与环境基线（2026-09-11 18:15–18:30 实测）

| 项 | 结果 |
|---|---|
| `make docs-check` | 通过（9 模块/114 表/47 handler/15 路由/31 ADR） |
| `make lint`（ruff） | 通过 |
| `make test`（fast 层） | **2 failed / 5288 passed / 12 skipped**（226s） |
| ├ `tests/unit/test_performance_probe.py::test_diagnostic_refuses_retargeting_before_changing_environment` | 已知本机必败（环境项，见任务记忆） |
| ├ `infrastructure/tasks/test_identity.py::test_production_ordinary_enqueue_calls_pass_explicit_novel_id` | 复跑确认（见 §6） |
| `npm run lint` | 通过 |
| `npm run build` | 通过（含 verify-production-build） |
| `npm test`（vitest 全量） | 183 文件 / 2480 测试全通过（31s） |
| PG 5207 | 端口可达（novelist/novel_dev_pass；alembic 仅 PG） |
| MinIO | 未测：本机代理干扰记录在案，需要时按 runbook 处理 |
| 浏览器 / 真实模型 / 付费验收 | 未运行（不在自动执行范围） |

## 6. 基线失败处置

- `test_performance_probe`：既有环境失败，非本轮引入；不计入审查回归。
- `test_identity` 单测失败：**W1 已根因定位（F4-1，P1 级发现）**——该测试在
  `backend/infrastructure/tasks/test_identity.py:26` 用 `BACKEND_ROOT.rglob("*.py")` 做 AST
  全库扫描，把 `backend/.venv`（约 1.4 万依赖文件）全部解析；fast 层被 per-test 超时判负。
  独立复跑允许跑完则通过（1 passed in 1623.90s，2026-09-11 实测），排除 venv 后断言本身
  通过。修复=测试文件内加 venv 排除，属实施批次；审查回归不按此失败计。

## 7. 出口核对（计划 §5 P0）

- 所有文件有主归属：是（§2）。
- 基线明确：是（§1、§5）。
- 未运行门禁有原因：PG critical/E2E/浏览器/性能/真实模型未运行——纯审查阶段不自动触发
  真实数据与付费操作；性能基线按计划 §5 P2 用 `docs/diagnostics/performance.md` 隔离流程另测
  （本机 performance_probe 必败已记录）。
- 未批准的真实数据、费用和发布操作未被触发：是。
