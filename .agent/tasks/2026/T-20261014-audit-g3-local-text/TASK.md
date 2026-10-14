---
id: T-20261014-audit-g3-local-text
title: 本机文字入口缩面与 RP 连接误判修复
status: completed
created: 2026-10-14
updated: 2026-10-14T11:39:00+08:00
---

# 本机文字入口缩面与 RP 连接误判修复

## 恢复快照

- 已完成：本机 task/claim 图片白名单、旧文字终止与回执保留、RP 旧 snapshot 续写拒绝、账户文字连接判断；权威文档同步。
- 下一步：主 Agent 在本树审查最终 diff，并按用户授权决定集成；本 Agent 不提交。
- 开发库只读计数：用户对复用数据库凭据、仅统计 `ai_novel_engine` 明确答复“全部授权”后，主代理以 READ ONLY 事务完成：旧 pending 文字 task 0、旧 pending 文字 invocation 0、旧 interaction 本机文字 snapshot 0。受保护 Guimi 库未查询，未读取正文或输出凭据。初次 JSON 运算符类型不兼容与后续自动审批拒绝记录保留；明确授权后的计数已成功。
- 工作区：`.worktrees/audit-g3-local-text`，分支 `codex/audit-g3-local-text`，基线 `22bb499789cba89fea92e918fd853ab768688e07`。仅该 worktree 单一写入，不改共享任务索引。
- 临时测试设施：主 Agent 创建 PostgreSQL 17/pgvector `audit_g3_e2e_test`，127.0.0.1:18647；浏览器独占18120/18121。运行显式 DATABASE_URL/E2E_DATABASE_URL，未使用默认.env。共享 backend解释器只读、前端node_modules仅链接；Vitest/Vite cacheDir定向仓库外 `/private/tmp`。

## 目标与验收

按外部只读计划 `.worktrees/audit-followup/docs/plans/2026-10-14-audit-followup-batch.md` §5.2 G3③a、§9–10 完成本机 pending task/companion claim 图片白名单、历史文字终止与回执保留、旧 RP snapshot 续写拒绝、RP 账户文字连接判断。模块测试、前端 Vitest/ESLint、lint/repo-gates/docs-check/diff、合成 PG E2E 与浏览器 390px 验收。

## 上下文与边界

用户授权首批、GPT-6.1 Sol medium 工程子代理。应用 ponytail full。禁止 G2 WIP、DI 键及 G3③b–d 清理，禁止真实 LLM、真实数据写入、提交/推送/PR/合并/部署。

## 发现与决定

- `api.py` pending/approve 接受所有 `_local_agent`；claim 未限定 request mode。
- `_story_task_meta` 为复用旧 snapshot 的 manual/see_sea/length 续写附加 `_local_agent`；集中拒绝可覆盖共享边界。
- `retry_attempt` 已创建新账户 snapshot，保留此重新发起语义，不把它变成复用旧 snapshot。
- `InteractionView.vue` 用 `executor.kind !== gateway` 绕过账户文字未连接检查；删该查询与兜底。
- 现有文本工具 HTTP/PG 测试必须迁为历史已分发 invocation fixture，保留 lease/tool budget/receipt 断言。

## 验证

- 开工 `make docs-check`：通过。
- local_agent模块最新：53 passed；interaction完整模块：201 passed，2真实模型用例按默认门禁排除。
- 定向前端RP/地图/对象图片：119 passed；完整前端：237文件、2977 passed；ESLint通过。
- 专用PG fresh Alembic upgrade到head成功；`test_local_agent_cli.py -m e2e`最终：5 passed in 1.78s；其中新增3例原生PG旧文字pending/approve/claim拒绝，验证JSON筛选及保留回执。
- `make test-postgresql-critical`：95 passed in 144.56s，JUnit在backend/.test-artifacts/postgresql-critical.junit.xml（忽略文件）。
- `make lint`、`make repo-gates`、`make docs-check BASE_REF=origin/main`、`git diff --check`：通过。使用只读既有解释器覆写BACKEND_LOCKED_CI_RUN，无依赖写入。
- 浏览器：新 `local-image-approval.spec.js` 6 passed in 11.8s；1280/390px 地图册与对象图片批准失败重试、RP无文字连接提示与刷新草稿恢复均通过。使用实际路由页面、合成API夹具和专用PG；不调用模型。浏览器需在macOS sandbox外启动Chromium（首次MachPort permission denied，无页面执行），原生受控提权运行通过。首次对象图片测试定位到旧编辑弹窗，改为实际资料详情deep link后通过，未改产品路由。
- 临时 `.playwright-g3/.vite-g3/.vitest-g3` 配置已删除，产品配置未改；spec使用项目标准functional配置支持的fixture与路由。实际本机运行只替换webServer解释器到已安装只读runtime、cacheDir到tmp，数据库/端口/env仍用标准配置约定。图片请求和LLM请求合成mock，真实后端仅创建/清理测试项目与对象。

## 交付

本地实现、测试、文档已完成；未提交/推送/PR/合并/部署。真实数据与模型调用均未执行。
与独立docs-refresh WIP可能交叠：local_agent/interaction README、docs/modules/18_interaction.md、23_local_agent.md、frontend-console/README.md、ADR-0029与ADR索引；主Agent按块合并。未改共享索引、DI、G2 WIP或第二波死分支。

## 主代理集成复核

- 已读生产/测试/文档 diff，确认真正新账户 retry 语义保留、历史回执仍可读，图片和文字连接判断已分离。
- 本任务副本已集成到 `codex/audit-first-batch`；原独立树保持未提交 WIP，集成验证另见主任务。
