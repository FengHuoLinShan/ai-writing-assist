---
id: T-20260917-review-remediation
title: 审计报告核查与全量修复（World 根因 / LLM 信任边界 / 信封加固 / 配额 provenance）
status: in_progress
created: 2026-09-17T13:30:00+08:00
updated: 2026-09-17T13:30:00+08:00
parent: .agent/tasks/agent-integration.md
---

# 审计报告核查与全量修复

来源：用户提供的 codex 审计报告（审计对象 `codex/world-verified-review` worktree 未提交 WIP，基线
f67845dc1）。2026-09-17 三路 Explore 核查结论：3 RB / 8 P1 / P2 全部属实；worktree 零提交、
全部为未提交 WIP（22 文件 +1505/-137）；RB-1、RB-2、P1-1~P1-7 问题代码在 main 基线已存在，
仅 RB-3 的 24/66 常量与 P1-8 review_state 机制为 WIP 新增。措辞修正两处：conflict 任务为
max_attempts=2（1 次 requeue）；CodexStructuredExecutor 默认模型 gpt-5.3-codex-spark，medium 仅为
Luna 专属默认。

## 用户拍板（2026-09-17）

- 修复范围：全量分期（Wave 1–5）。
- world WIP：本轮一并整合（Wave 5 rebase 到修复后 main + 确定性回归；付费重跑单独授权）。
- RB-1 策略：合并时确定性消毒（confirmed 优先去重），不 fail-closed 历史数据。

## 波次

1. `codex/world-review-root-cause`（main 侧）：RB-1 `_merge_saved_decisions` constraints→confirmed
   映射修复 + 规范化消毒；RB-2 审查冻结投影（task_instruction 传 compiled brief/decision state、
   投影不截断）+ `output_permissions` 进入审计语义。
2. `codex/llm-profile-extra-boundary`：P1-1 profile 请求默认在 client seam 透传；P1-2 extra
   reserved 字段封锁。
3. `codex/llm-envelope-hardening`（Wave 2 后）：P1-3 信封 token_limit + provider await 按剩余
   deadline 裁剪；P1-4 checkpoint 失败回滚兼容账本；P1-5 远程 embedding 入信封 + RAG indexing
   任务声明 root capability/limit。
4. `codex/budget-caps-provenance`（可与 3 并行）：P1-6 conflict cap 重算；P1-7 入队冻结工作量
   receipt + 补 deadline（成本分级 UI 另立产品任务）；P1-8/RB-3 通用侧（codex_executor max、
   eval meta provenance）；P2 捎带 imports partial 明示。
5. 续用 `codex/world-verified-review`：worktree WIP 整理成提交 rebase 到修复后 main；失败路径写
   公开脱敏 stop-stage receipt；eval artifact 诚实化（真实 cap/累计 usage/effective config）；
   确定性回归。11 对付费重跑不在本轮。

## 进展

- 2026-09-17：核查完成；Wave 1 分支已建。未开始编码。
- 2026-09-17（续）：Wave 1 实现完成于 `codex/world-review-root-cause`。
  - RB-1：`_merge_saved_decisions` 改为单一归类——constraints 与既有决定同文条目跟随决定
    归属，其余进入 `confirmed_requirements`；`GeneratedWorldGenerationDecisionState` 新增
    model_validator 做规范化（去空白+casefold）confirmed 优先消毒，所有构造路径生效。
    深度语义发现：`revise_world_design` 会把 rejected 决定文本写进 constraints，故不能
    无条件把 constraints 映射为 confirmed（会反转否定语义），按文本归类是正确解。
  - RB-2：`GovernedWorkflowHooks` 新增 `author_requirements`（不截断冻结投影）；
    `_audit_messages` 渲染【输出权限】与【作者要求（冻结投影）】；policies 新增
    `OUTPUT_PERMISSION_AUDIT_CLAUSES`（proposal 输出的新增不单独判 unsupported_fact）；
    AUDIT_SYSTEM_PROMPT 同步；WGC 抽取 `_author_decision_state_block` 供生成消息/决策审计/
    知识审查三处同源复用，`_govern_structured`/`_govern_text` 自动接线（chat/convergence/
    exploration/inspection/suggestion 全覆盖）。资料投影仍 24K 截断。

## 验证

- Wave 1：world+evidence 全量 1561 passed, 2 deselected；writing 治理/semantic/interaction
  knowledge 25 passed；prompt contracts 18 passed；ruff 通过；docs-check BASE_REF=origin/main
  以 --no-change-reason 通过（无 ORM/map/DB 影响，行为契约同步 02_world.md）。
- 新增测试：test_world_decision_merge.py（4）、test_workflow.py 审查 prompt 组装（2）、
  test_world_knowledge_governance.py 冻结投影接线（1）。

## 阻塞 / 下一步

- 无阻塞。下一步：Wave 2 `codex/llm-profile-extra-boundary`（P1-1 profile 请求默认透传 +
  P1-2 extra 保留字段封锁）。Wave 1 合并 main 待用户授权。
