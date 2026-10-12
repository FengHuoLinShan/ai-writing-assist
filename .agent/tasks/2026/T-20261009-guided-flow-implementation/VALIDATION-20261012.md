# 集成验证记录（2026-10-12）

工程检查通过；[独立审查](REVIEW-20261012.md)未通过，功能和作者验收保持开放。全部使用合成数据/替身，未调用真实模型、未读取真实项目库。

## 版本与结果

| 检查 | 结果 | 对应版本与证据 |
| --- | --- | --- |
| 实施前 `make docs-check` | 通过 | 集成 merge 头；`/tmp/guided-flow-test-ci-final.log` 也含重新通过的 inventory |
| `make test-ci TEST_WORKERS=2` | 通过：后端 7661 passed/2 skipped、覆盖率 86.69%；前端 2953；部署脚本 272 | `1ffd64678ccf78b131c0712d84dd32e9c43acc7e`；`/tmp/guided-flow-test-ci-final.log` |
| Assistant 完整模块回归 | 132 passed | `50aff8ddc`；`/tmp/guided-flow-assistant-final.log`，含非替身真实 HTTP start/active/view/跨项目 404/abandon |
| EditorialDesk 单元 | 8 passed | `50aff8ddc`；`/tmp/guided-flow-editorial-unit.log`，含 skipped 原因与诚实状态 |
| PostgreSQL critical | 85 passed | `50aff8ddc`；`/tmp/guided-flow-pg-critical.log`，含新库迁移/ORM 对齐；没有覆盖新引导流程的双连接启动竞争 |
| 三个浏览器 spec，桌面 | 6 passed | 最终头 `ebd3bac37`；`/tmp/guided-flow-browser-desktop-final.log` |
| 同三个 spec，390×844 | 6 passed | 最终头 `ebd3bac37`；`/tmp/guided-flow-browser-narrow-final.log`；临时配置 `/tmp/guided-flow-narrow.config.mjs` |
| Ruff / ESLint / 生产前端 build | 通过 | Ruff 全量在 test-ci，生产改动后补受影响文件；ESLint 最终测试入口改动后重跑；`/tmp/guided-flow-frontend-lint-final.log`、`/tmp/guided-flow-build-final.log` |
| secret hygiene / 后端和前端依赖 audit | 通过 | test-ci 日志；未新增依赖 |
| `make repo-gates` | 通过 | 最终提交头；`/tmp/guided-flow-repo-gates-final.log`；既有 writing/services.py 超长警告，import ratchet 524/524 |
| 架构 inventory 与主干差异影响门禁 | 通过，有明确不变理由 | `/tmp/guided-flow-docs-final.log`；见下文 |
| `git diff --check` | 通过 | 最终提交及未提交任务记录 |
| 原工作树 WIP 保留核对 | 通过 | 57 个修改/未跟踪文件 SHA256、HEAD、暂存 diff 和 porcelain status 均与本轮前相同；私有快照 `/tmp/guided-flow-wip-before.json` |

全量 test-ci 在生产代码后两处 HTTP/状态修复之前完成；其后针对真实受影响模块、浏览器、lint/build 和文档重新验证，没有声称全量测试在最后一次提交上重新跑过。两个 skipped 与 13 个 warnings 均保留在全量日志，不隐藏。

## 失败与纠正

- 首轮 test-ci 仅 3 个新能力注册/标签/绑定用例失败，修复对应注册后全量重跑通过。
- 真实 HTTP 暴露子路由重复 `/api/assistant`；修复 prefix 后补真实 HTTP 回归。其后取消流程暴露 stop=None，已修复并回归。
- 初轮窄屏两个用例超时于桌面章节按钮。复用 `waitWritingReady({chapter: 1})` 打开移动章节目录后，六用例通过，未删除断言。
- 新 tails 用例此前没有被 editorial profile 发现；现配置包含 guided-flow*.spec.js，与功能套件去重。已有 CI editorial shard 会发现这些用例。
- 主干差异文档检查首次要求 8 份相关文档更新/确认。实际 owning 文档已同步，对无行为变化文档使用检查器已有 `--no-change-reason` 明确确认，没有修改门禁规则。命令为 `backend/.venv/bin/python scripts/check_architecture_docs.py --base-ref origin/main --no-change-reason '<逐项理由>'`，不是声称不带理由的 `make docs-check BASE_REF=origin/main` 自动通过。
- 不变理由：CLAUDE 仅导入规则；Evidence indexing/embedding/retrieval 不变；架构导航/维护/Drawio/HTML 的 12 模块节点、依赖、基础设施不变；Memory/Map 来源、接口、知识边界不变。同步文档覆盖 CONTEXT、总体/数据库设计、Assistant/World/Evidence README 与 compilation、Evidence 模块、知识策略、测试套件。

## 数据与覆盖边界

- Docker daemon 不可用，改用本机 PostgreSQL 17.10 + pgvector，创建任务独占集群 `/tmp/codex-guided-flow-20261012-pg`，端口 18432，数据库 `guided_flow_integration_test`。未连接任何真实项目库；测试结束关闭此集群，保留日志与集群目录供必要复现。
- 浏览器使用官方 editorial 功能开关 profile、新启动的 18000/18080 服务及合成项目。流程/审读/模型任务结果通过 API 路由替身返回，验证入口、显示、停点和导航；真实 HTTP 回归单独验证服务端路由与隔离。浏览器替身通过不能证明完整领域采用、付费恢复或真实作者体验。
- tails 的规划用例只断言打开结构工作台路由，日志在后续后台请求中仍出现 `GET /api/world/entities` 404；该用例没有覆盖目标页资料加载或断言所有浏览器错误。因此“导航通过”不表示结构工作台完成无错误验收，此信号保留待查，未擅自归因为新回归或服务端缺陷。
- 未运行真实模型/稿件、真实双设备并发探针或人工作者验收；审查缺口未全部修复。未推送、未建立 PR、未合入 main、未部署。

## 可复现关键命令

1. `uv sync --locked --extra ci` 与 `npm ci`；`make test-ci TEST_WORKERS=2`。
2. `E2E_DATABASE_URL=<任务独占 PostgreSQL URL> make test-postgresql-critical`。
3. frontend-console 下使用任务库 `DATABASE_URL`、`PW_REUSE_EXISTING_SERVER=0`、`APP_ENV=test`、`BACKEND_PORT=18000`、`FRONTEND_PORT=18080`、`API_HOST=http://localhost:18000`，剥离代理环境后执行 `npx playwright test guided-flow-continue-writing.spec.js guided-flow-tails.spec.js editorial-revision-bridge.spec.js --config playwright.editorial.config.js`。窄屏改用上述临时配置。
