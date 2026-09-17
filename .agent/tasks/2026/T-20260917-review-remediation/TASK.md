---
id: T-20260917-review-remediation
title: 审计报告核查与全量修复（World 根因 / LLM 信任边界 / 信封加固 / 配额 provenance）
status: complete
created: 2026-09-17T13:30:00+08:00
updated: 2026-09-17T21:30:00+08:00
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
- Wave 2：全量 modules 3429 passed, 12 skipped（temperature 默认 0.7→None 全局回归无异常）；
  llm client/schema/envelope 85+74 passed；project 147 passed；ruff 通过；docs-check 通过
  （12_infrastructure.md 与 llm README 同步 profile 请求默认与 extra 信任边界）。
  新增测试：test_client.py profile 默认/extra 封锁（4）、test_llm_settings_api.py extra 校验（1）。
- Wave 3：infrastructure+evidence 1061+205 passed；modules+infrastructure 全量 3904 passed
    （2 个失败为仓库根目录跑 pytest 的相对路径伪失败，backend/ 下复跑 76 passed）；ruff、
    docs-check 通过（12_infrastructure.md 与 tasks README 同步 token_limit/deadline 裁剪/
    embedding 计量/RAG 任务上限）。
- Wave 4：writing/story/project/imports 1614→全部通过（更新 2 个 deadline pin）；
  evals 141+193 passed；ruff、docs-check（--no-change-reason 核对豁免）通过。

## 阻塞 / 下一步

- 全部 5 波完成（Wave 2/3/4 的进度与验证记录见各分支上的本文件较新版本，已随本合并进入
  main 历史）：
  - Wave 1 `codex/world-review-root-cause`：RB-1 + RB-2（036e97a83）。
  - Wave 2 `codex/llm-profile-extra-boundary`：P1-1 + P1-2（e7bd69ba6）。
  - Wave 3 `codex/llm-envelope-hardening`（基于 Wave 2）：P1-3/4/5（2073ce0b9）。
  - Wave 4 `codex/budget-caps-provenance`：P1-6/7/8 + P2（e98485213）。
  - Wave 5 `codex/world-verified-review`（rebase 到 Wave 1）：WIP 整理为 5 提交 +
    失败公开停止回执 + gate 去同预算化（a6d6d11df）；worktree world+evals 1139 passed。
- 2026-09-17 二轮 review（Standards 3 硬性 + Spec 4）：全部修复——
  W5 返修后知识复审补传 author_requirements（7a488c34d）；失败回执改私有键
  `_world_design_review_failure` + redact_diagnostic 消毒（公开 wire 剥离）；writing/
  story/project 模块 README 同步墙钟与冲突配额（e7efe7293，Wave 4 分支）；gate 报告补
  per-arm request_limits/reasoning_efforts 并清理 same_budget 测试名；indexing README
  同步 RAG 信封声明、provider 暴露 request_timeout、预算谓词收敛 schema 单点
  （af684b56e，Wave 3 分支）；codex max 补参数化测试。判断性气味中 WGC 三处
  run_managed_structured 重复与大类拆分维持缓议（与首轮审计决定一致）。
  修正后回归：W5 1139 passed、W3 线 3906 passed、W4 线 32 targeted passed；ruff/
  docs-check 全过。
- 下一步：2026-09-17 用户授权合并与付费重跑，均已执行完毕——
  - 合并：Wave 1 → 5 → 2 → 3 → 4 依次 --no-ff 合入 main（合并解决 TASK.md 并集 +
    infrastructure/tasks/README 语义并集）；合并后门禁后端 5815 passed / 前端 2500
    passed / ruff / docs-check 全过（其中修正 Wave 3 漏同步的 evidence 模块 README 与
    08_evidence.md 信封声明过时，d670c65f8）；已推送 origin/main。
  - 付费重跑（11 对，baseline f67845dc1 vs candidate d670c65f8，真实 DeepSeek）：
    gate 仍失败但结构反转——severe 11 vs 10（severe_errors_reduced 首次转绿，首轮
    8 vs 11 未减少）；新增 review friction 2（insufficient-evidence）与 knowledge-
    boundary 回归 2（information-flow、insufficient-evidence）致总体不通过。证据与
    脱敏总览：backend/.test-artifacts/world-verified-review-live-20260917/（SUMMARY.md）。
    一次性库/worktree 已清理。后续若继续：先定位低证据场景下新返修/复审链的判定
    口径，再另行授权付费验收。
