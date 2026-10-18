---
id: T-20261018-ci-full-postgresql
title: 修复 PostgreSQL nightly 并启用 PR 全量门禁
status: completed
external_ref: https://github.com/FengHuoLinShan/ai-writing-assist/pull/254
created: 2026-10-18T10:04:00+08:00
updated: 2026-10-18T10:43:40+08:00
---

# CI/CD 修复

## 恢复快照

- 工作区：`.worktrees/ci-full-postgresql`，分支 `codex/ci-full-postgresql`，基线 `6004d3703d03c5110044239c86362d23df39df53`。
- 已复用 `268cc1289` 的 simulation 测试补丁；原分支保留。
- 恢复核验：`gh pr view 254 --json state,headRefOid,mergeCommit,statusCheckRollup`。本地实现和验证已完成；远端交付状态以该 PR 为准，禁止把此处历史本地结果替代固定 head 检查。
- 数据库：本任务新建容器 `ci-full-postgresql-20261018`，loopback 65418，库 `ci_full_e2e_test`（初始诊断）、`ci_focus_e2e_test`（定向/critical）、`ci_final_e2e_test`（最终全量）；不访问其他库。
- 本地验证阶段结束时尚未提交；本轮用户已明确授权提交、合并、推送，不含部署。后续状态以关联 PR 为准。

## 目标与验收

- 修复 run 39064153427 的 25 failed / 381 passed；保留预算、取消、事务与隔离断言。
- PR 的稳定 `PostgreSQL critical` 检查运行串行确定性全量；nightly 复用 `make test-e2e`。
- 定向、critical、全量 E2E、适用 lint、合同测试、test-ci、docs 与 diff 门禁。
- 不升级依赖，不修改生产发布方式，不调用真实模型。

## 决策、发现与失败

- 常规 main CI 成功不能替代失败的 nightly。用户选择修复全部业务/夹具失败，并将全量提升为 PR 门禁。
- 根目录 `make docs-check` 已通过。uv 默认 cache 沙箱不可写，使用任务独立临时 cache 和独立 venv。

## 验证证据

- 初始诊断 24 failed / 384 passed / 7 deselected（已带 simulation 补丁），日志 `/private/tmp/ci-full-baseline.log`；不作固定版本验收。
- 失败文件定向 52 passed / 5 failed；补齐场景准备 client.profile_summary 后剩余 5 passed，合计 57 项通过。
- `make test-ci TEST_WORKERS=2` exit 0：后端 9205 passed / 2 skipped / 14 warnings，覆盖率 85.27%；前端 259 文件 / 3253 passed；部署合同 324 passed；lint、secret hygiene、依赖审计与 docs 均通过。日志 `/private/tmp/ci-full-test-ci.log`。
- 工作流合同/分类 56 passed；适用 Ruff 与 git diff --check 通过；`make docs-check BASE_REF=origin/main` 通过。
- `alembic upgrade head` 和 `alembic check` 通过，无 ORM 漂移。
- 最终 `make test-e2e` exit 0：409 passed / 7 deselected（真实模型或外部数据），386.12s；`make test-postgresql-critical` exit 0：108 passed，209.91s。
- Node 24.21.0 重新 npm ci 后前端 259 文件 / 3253 passed，exit 0；所有 12 个源码指纹复核未变。
- 本机 PostgreSQL 17.10 / pgvector 0.8.2；CI 保留原锁定 0.8.6 镜像。默认 Node 22.22.3 的完整 test-ci 已通过，另用仓库锁定 Node 24.21.0 完成前端复核。远端 Ubuntu/锁定镜像未执行。
- 12 个变更源码的 SHA-256 快照：`/private/tmp/ci-full-tested-sources.json`；最终验收前重验。
- 临时日志可被系统清理；原失败日志可从 `gh run view 39064153427 --log-failed` 恢复。

## 交付结果

- 已交付：两份 CI workflow、回归夹具/断言、安全失败路径、合同测试和测试指南；所有计划内本地验证通过。
- 本地实现完成时未交付：提交、推送、PR、远端 CI 与合并；用户随后已授权这些操作。部署及真实模型/作者验收仍不在范围内。
- 持久证据：[验证与源码指纹](artifacts/verification.json)。临时日志在 `/private/tmp/ci-*.log`。
- 本任务专用容器停止后保留合成测试库与日志，可按原容器名恢复；未删除数据或其他资源。

## 实施检查点

- PR 与 nightly 已统一 make test-e2e；稳定检查名、隔离、诊断和安全门禁保留。工作流合同/分类 56 passed。
- 已修复作品计数、任务领取范围、合成 snapshot、独立未配置账户和过时 mock；未知用量保持失败关闭，另覆盖已知 usage 的成员失败可部分完成。
- 原 25 项失败分组：团队2、Creative事务3、Creative worker2、forecast1、项目删除2、simulation1、coalescing1、understanding13。修复均在测试层，生产逻辑与数据契约未改。
- 初始整套仅用于诊断：其运行期间实施了测试修复，不作为固定版本验收。最终全量必须在文件不再变化后运行。
- 5 项场景准备失败来自 client 缺 profile_summary；补齐后回调、取消与恢复断言均执行并通过。

## 远端交付

- 用户已授权提交、合并与推送。已 fetch 的 main 为 `98598127f933782f26019ca0e9970c53849c2a97`，包含 #253 的同一 simulation 补丁；接入后不重复交付。
- ponytail-review 已检查 workflow、实际 Make target、分类、任务 claim scope、原回滚与未知用量保护，未发现阻断项。
- 本地源码指纹与验证回执一致；远端 Ubuntu/锁定镜像、浏览器与镜像门禁以关联 PR 的固定 head 结果为准，不能由本地结果替代。

- 已提交并接入最新 main，推送主题分支并创建 [PR #254](https://github.com/FengHuoLinShan/ai-writing-assist/pull/254)。实际提交、远端检查和合并结果均可从该 PR 恢复；此笔记的 completed 对应本地实现验收，不预先宣称远端 CI 或合并成功。
