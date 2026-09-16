---
id: T-20260916-ai-result-trace
title: 统一成果追踪与精确失效
status: completed
created: 2026-09-16T13:16:48+08:00
updated: 2026-09-16T14:58:32+08:00
predecessor: .agent/tasks/2026/T-20260916-async-operation-protocol/TASK.md
---

# 统一成果追踪与精确失效

## 恢复快照

- 实际完成：M0–M4 全部完成；实现 Confirmation 只读投影、Writing/Story
  内联成果追踪、精确失效与 Hidden Guard World facade 边界，并以三个可独立审查的提交交付 PR #145。
- 当前里程碑：完成。本记录只会在 PR #145 必需检查全绿、squash 合并并安全清理主题分支后进入 `main`。
- 下一步：无确定性开发任务；真实 provider smoke 仍须费用、凭据与一次性项目的独立授权。
- 阻塞：无。真实 provider smoke 需费用、凭据和一次性项目的独立授权，不阻塞确定性交付。
- 工作区：`/Users/tywww/Desktop/项目/ai-writing-assist`，分支 `codex/ai-result-trace`，
  基线 `aebf69263`；当前改动均属本任务。
- 最后核实：2026-09-16T14:58:32+08:00。

## 目标与验收

- 目标与交付物：让 Writing 正文候选和 Story P20 结构预览在原成果页内展示
  当时资料、异步运行、知识复核、成果引用、采用/拒绝与当前失效状态。
- 完成条件：
  - 新增只读 Confirmation GET，精确按 owner + `novel_id` 隔离，不暴露私有字段。
  - 两个原成果入口共用一个 Vue `<details>` 组件，继续使用现有 task normalizer 与成果定位器。
  - `stale_reasons` 为 fresh gate 权威事实；Writing/Story 的精确变更不漏失、不跨项目、
    不把本次 AI 采用误标为自身失效。
  - Writing 采用/拒绝和 Story P20 采用回写原 Confirmation 状态与结果引用。
  - Hidden Guard 仅通过 World contract/facade 批量读取冻结对象/关系，不再直引 ORM。
  - 定向、前端、专用 PostgreSQL、完整 CI、Prompt 与文档门禁通过。
- 非目标：不新增表/migration/成果中心/AuditEvent/依赖图/workflow engine；不接 World UI；
  不统一领域 Review taxonomy、状态机、dirty guard 或全局历史页。

## 上下文与边界

- 关键路径：Evidence Confirmation service/API，`infrastructure.tasks` 公共投影，Writing candidate，
  Story P20 apply，前端 Writing/Outline 成果页，Hidden Guard 与 World facade。
- 硬约束：单一写入者；保留当前领域状态机和业务操作；只读追踪失败不得阻断原采用/
  拒绝/编辑；失效写入与领域变更同事务失败关闭。
- 依赖：PR #144 的 `TaskOperationProjectionV1`，现有 `ContextConfirmationAssetRef`、
  `normalizeTaskProgress`、`locateAssistantSource`、World contracts/facade。
- 已确认事实：Confirmation 已保存 `selected_asset_ids/result_refs/result_status/stale_reasons`；
  task meta 已公开 `context_confirmation_id`；Writing provenance 已保存 confirmation/task/review；P20 preview
  已保存 confirmation/task/review。
- 假设与待决问题：无；不持久化的历史 section 不重编译，只展示当时已保存的类型、
  数量、指纹和结果引用。

## 里程碑与进度

- [x] M0：独立合并前置异步协议，建立新分支/任务记录，基线 `docs-check` 通过。
- [x] M1：Confirmation 只读 API + 共享追踪组件 + Writing/Story 两入口。
- [x] M2：fresh gate、Writing/Story 精确失效、采用/拒绝回执与 PostgreSQL 并发不变量。
- [x] M3：Hidden Guard World facade 批量读取边界。
- [x] M4：文档、定向/浏览器/专用 PostgreSQL/完整 CI、PR 交付与清理。

## 决策、发现与失败

- 2026-09-16：采用“现有 Confirmation + 确切 Task 的前端组合视图”，不建立新成果表或
  后端聚合服务；首批固定 Writing + Story 原成果页。
- 2026-09-16：运行终态、领域采用状态与来源有效性是三个正交事实；追踪 UI 组合展示，
  不用一个全局状态压平。
- 2026-09-16：计划中的新 GET 落在仓库现行 canonical
  `/api/evidence/compilation/confirmations/{id}`；不恢复已退场的 `/api/context` 别名。
- 2026-09-16：P20 终态进度卡默认折叠；共享追踪放在该原结果卡内，不复制到
  领域审阅表单，不新建页面或导航。
- 2026-09-16：远端完整浏览器首轮和一次无改动重跑都稳定暴露旧 World Bible
  离线备份用例的 dialog 等待死锁；产品链路和该用例单独复跑正常。修复只调整
  Playwright 等待顺序：先注册 dialog，启动 click，accept 后再等 click；断言与产品逻辑不变。

## 验证证据

- 2026-09-16，基线 `make docs-check`：通过；9 modules、115 ORM tables、47 task handlers、16 routes、33 ADRs。
- 2026-09-16，受影响 Evidence/Writing/Story/Tasks/World：1077 passed、12 skipped；定向 Ruff 全通过。
- 2026-09-16，前端 Vitest：63 passed；ESLint 通过；Playwright Writing + P20 三类正常流：4 passed。
- 2026-09-16，专用 PostgreSQL `ai_result_trace_e2e_20260916`：新并发用例 3 passed，
  `make test-postgresql-critical` 37 passed。
- 2026-09-16，`make prompt-contracts`：24 passed；文档影响检查通过，
  indexing/map 经逐项核对无本轮契约变化；`git diff --check` 通过。
- 2026-09-16，`make test-ci TEST_WORKERS=2`：deploy 270 passed；backend 5766 passed、
  13 skipped，coverage 86.06%；frontend 2498 passed；依赖审计无高危漏洞。
- 2026-09-16，World Bible reliability 完整文件在 dialog 等待修正后 7 passed；
  PR #145 的远端必需检查在合并前全部通过。

## 交付结果

- 已交付：前置异步协议已独立合并。
- 已交付：M1–M4 实现、文档、本地/远端验收、PR #145 squash 合并与分支清理；无数据模型变更。
- 未交付：真实 provider smoke 与部署，均不在当前确定性范围。
- 交付边界：仅新建并保留专用 E2E 库，未触碰开发库、受保护 Guimi 库、
  真实 provider、部署或用户数据。
- 正式知识与后续任务：完成时同步 Evidence/Writing/Story/Infrastructure/World 现有权威文档；
  条件性方向保持延期，不自动扩域。
