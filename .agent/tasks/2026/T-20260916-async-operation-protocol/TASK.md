---
id: T-20260916-async-operation-protocol
title: 统一异步操作协议
status: completed
created: 2026-09-16T11:07:35+08:00
updated: 2026-09-16T13:00:27+08:00
predecessor: .agent/tasks/2026/T-20260915-ai-run-envelope/TASK.md
successor: .agent/tasks/2026/T-20260916-ai-result-trace/TASK.md
---

# 统一异步操作协议

## 恢复快照

- 实际完成：PR #143 已 squash 合并到 `main`（`7bb786a66`）；M1–M3 已实现：实际提交模式
  receipt、`TaskOperationProjectionV1`、worker 稳定错误码、task API 和前端共享 normalizer。
- 当前里程碑：M0–M4、本地/远端验收和交付全部完成。
- 下一步：后继成果追踪任务已从更新的 `main` 启动。
- 阻塞：无。真实 provider、部署及真实项目数据不在本任务范围。
- 工作区：PR #144 已 squash 合并到 `main` 的 `aebf69263`；主题分支已清理。
- 最后核实：2026-09-16T13:16:48+08:00。

## 目标与验收

- 目标与交付物：复用 AsyncTask、operation receipt、coalescing、lifecycle 与前端共享 waiter，
  建立一个可向后兼容的异步操作公共投影，统一 `submission_mode / stage / error_code /
  retryable / possible_charge / partial_result / available_actions`。
- 完成条件：
  - 三类现有入队原语为新任务写入不可由调用方伪造的私有提交模式：普通追加、精确 operation
    回执、活动任务复用/单 pending follower；旧任务安全投影为 legacy。
  - `/api/tasks/{id}` 返回版本化 `operation` 投影；不公开 AI 信封、coalescing key、Prompt、正文、
    provider raw 或私有 checkpoint。
  - worker 将安全稳定的失败 code 写入既有 lifecycle receipt；DomainError、LLM、运行信封与未知
    故障均有确定性映射，不以异常文案充当 code。
  - `possible_charge` 仅由运行信封或领域显式事实产生；`partial_result` 只根据已公开结果和显式标记
    判断，不猜测隐藏业务状态。
  - 前端 `normalizeTaskProgress` 优先消费统一投影并保留旧 task wire fallback；现有调用方无需迁移
    即保持行为。
  - infrastructure task 定向测试、前端 workflowProgress 测试、lint、docs-check 与适用完整门禁通过。
- 非目标：不统一 MapAtlasRun、Interaction revision 或 Imports domain run 的内部状态机；不新增
  万能任务表、全局 error-code registry、前端 Modal、轮询器或 workflow engine；不改变各领域结果
  payload、恢复政策和并发语义。

## 上下文与边界

- 关键路径：`backend/infrastructure/tasks/{contracts,enqueuer,lifecycle,worker,api}.py`、
  `frontend-console/shared/workflowProgress.js` 及其现有测试。
- 硬约束：只做加性公共投影；私有下划线键继续被 task API 剥离；项目 owner + `novel_id` 门禁、
  lease/CAS、coalescing 唯一索引和领域确认不变。
- 已确认事实：当前有 47 个 task handler；`available_actions` 与恢复政策已有单一生命周期投影；
  AI 信封私有 meta 可可靠给出 possible-charge；`current_phase`、error code 与 partial result 仍由领域
  结果各自表达。
- 假设与待决问题：提交策略的“每 task type 允许哪些模式”先按实际任务 receipt 记录；只有发现
  生产误用证据时再增加 registry 级 fail-closed 声明，避免为静态分类复制 47 份配置。

## 里程碑与进度

- [x] M0：合并前序计划，建立干净主题分支，核对现有入队/生命周期/API/前端 normalizer 链并通过
  文档基线。
- [x] M1：提交模式私有 receipt 与版本化公共 operation projection。
- [x] M2：worker 稳定错误 code、possible-charge 与 partial-result 投影边界。
- [x] M3：前端共享 normalizer 消费新投影，旧 wire 兼容回归。
- [x] M4：文档、定向测试、完整门禁与交付记录。

## 决策、发现与失败

- 2026-09-16：选择“按实际入队 receipt 记录模式”，不先给 47 个 handler 增加重复声明。现有
  enqueuer 已是权威入口，写入实际模式比维护第二份静态配置更小且不会漂移。
- 2026-09-16：公共投影由 lifecycle 在读取时生成，不新增数据库列；只有异常稳定 code 随现有
  lifecycle receipt 持久化，避免把公开投影变成第二业务事实源。
- 2026-09-16：首次完整 CI 仅失败于既有 RAG 测试将内部 meta 精确写死；测试改为分别断言
  `novel_id` 与新增私有模式 receipt 后单项和完整 CI 均通过，未放宽业务断言。
- 2026-09-16：`partial_result=false` 与纯阶段/诊断字段不得被误判为部分结果；最终边界仅认显式
  true，或失败/取消结果中排除状态字段后仍存在的公开业务字段。

## 验证证据

- 2026-09-16，基线 `make docs-check`：通过；清单为 9 business modules、115 ORM tables、
  47 task handlers、16 frontend routes、33 ADR files。
- 2026-09-16，任务基础设施与旧兼容定向：`pytest infrastructure/tasks/tests
  tests/unit/test_infra_tasks.py` → **230 passed**；前端 `workflowProgress.test.js` → **33 passed**，
  定向 ESLint 通过。
- 2026-09-16，新建专用 PostgreSQL `ai_async_operation_e2e_20260916` 并迁移到 head；task
  coalescing 并发 + run envelope E2E → **7 passed**。未触碰开发库或受保护 Guimi 库。
- 2026-09-16，最终 `make test-ci TEST_WORKERS=2`：deploy **270 passed**；backend
  **5758 passed, 13 skipped, 11 warnings**，coverage **86.03%**；frontend
  **191 files / 2492 tests**；docs、secret hygiene、dependency audit 与 Ruff 全部通过。
- 2026-09-16，专用 PostgreSQL 全部 merge-gate → **36 passed**；Prompt contracts
  **24 passed**；`make docs-check BASE_REF=origin/main` 与 `git diff --check` 通过。全库
  `make format` 仍因主干已有 205 个未格式化文件失败，本任务 13 个 Python 改动文件的定向
  `ruff format --check` 与 `ruff check` 均通过，未批量改写无关文件。
- 2026-09-16 交付前独立重验：后端定向 **239 passed**，前端定向 **33 passed**；
  专用 PostgreSQL `ai_async_operation_e2e_20260916` 的 merge-gate **36 passed**；完整
  `make test-ci TEST_WORKERS=2` 再次通过，结果为 deploy **270 passed**、backend
  **5758 passed, 13 skipped**、coverage **86.03%**、frontend **191 files / 2492 tests**。

## 交付结果

- 已交付：本地 `codex/async-operation-protocol` 已实现版本化异步操作投影、实际提交模式 receipt、
  稳定错误码及前端共享 normalizer，并同步 task README 与 Infrastructure 模块文档。
- 已交付：本地提交 `580cdbccf`，PR #144 全部远端门禁通过后 squash 合并为
  `aebf69263`；本地/远端主题分支均已清理。
- 未交付：部署与真实 provider 调用。
- 交付边界：本地 `main`、`origin/main`、`upstream/main` 均为 `aebf69263`；未触碰真实
  业务数据或受保护验收库，专用 E2E 数据库保留复验。
- 正式知识与后续任务：正式知识已同步现有文档；后续成果治理方向需建立独立任务。
