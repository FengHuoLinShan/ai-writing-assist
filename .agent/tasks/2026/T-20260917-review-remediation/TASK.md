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
- Wave 4：writing/story/project/imports 1614→全部通过（更新 2 个 deadline pin）；
  evals 141+193 passed；ruff、docs-check（--no-change-reason 核对豁免）通过。
- Wave 3：infrastructure+evidence 1061+205 passed；modules+infrastructure 全量 3904 passed
    （2 个失败为仓库根目录跑 pytest 的相对路径伪失败，backend/ 下复跑 76 passed）；ruff、
    docs-check 通过（12_infrastructure.md 与 tasks README 同步 token_limit/deadline 裁剪/
    embedding 计量/RAG 任务上限）。
- Wave 2：全量 modules 3429 passed, 12 skipped（temperature 默认 0.7→None 全局回归无异常）；
  llm client/schema/envelope 85+74 passed；project 147 passed；ruff 通过；docs-check 通过
  （12_infrastructure.md 与 llm README 同步 profile 请求默认与 extra 信任边界）。
- 新增测试：test_world_decision_merge.py（4）、test_workflow.py 审查 prompt 组装（2）、
  test_world_knowledge_governance.py 冻结投影接线（1）、test_client.py profile 默认/extra
  封锁（4）、test_llm_settings_api.py extra 校验（1）。

## 阻塞 / 下一步

- 无阻塞。Wave 3 实现完成于 `codex/llm-envelope-hardening`（基于 Wave 2 分支叠加）：
  - P1-3：`AIRunEnvelopeV1.token_limit`（可选累计 token 上限，reserve 按已结算用量闸断）；
    `AIRunAuthorizationV1.additional_tokens` + `authorize_additional_requests` 续算；registry
    `run_token_limit` 声明链 + worker 冻结 + lifecycle 预算判定/manual resume；单次 provider
    调用 timeout 取 min(profile timeout, 剩余 run deadline)（generate/generate_stream 建流/
    远程 embedding）。
  - P1-4：`WorkflowBudget.before_request` checkpoint 失败时 `release_pending_request()` 回滚
    兼容账本，不再留幻影计数。
  - P1-5：远程 embedding 经 `_embedding_step_scope`（infrastructure.embedding step）接入同一
    信封，honest-unknown 落账；本地 BGE 标注非计费窄例外；RAG 三任务（index_chapter 64 /
    reindex_novel 4096 / retry_embeddings 2048 请求 + token 上限 + deadline）声明信封，
    capabilities 注册 infrastructure.rag_* 三项。
  下一步：Wave 5 world WIP 整合。Wave 1/2/3/4 合并 main 待用户授权。

- Wave 4（`codex/budget-caps-provenance`，自 origin/main 独立分支）：
  - P1-6：writing_conflict 两任务 cap 6→16（两次 attempt 合法重放 12 + transport 余量 4，
    推导入代码注释与回归测试）。
  - P1-7 后端：evidence facade 新增 `confirmed_knowledge_source_count`（确定性来源计数，
    不小于实际 included），writing generate 入队冻结 `included_sources_upper_bound`，
    配额按真实 K 计（1544 虚高 cap 仅历史在途）；writing generate/story one_click·reaction/
    smart dedup 补保守总墙钟（7200/3600s，只切病态挂起）。作者成本分级 UI 另立产品任务。
  - P1-8/RB-3 通用侧：codex_executor 允许集补 `max`；eval meta sidecar 模式已有
    （cli.py model-review），world harness 侧 provenance 归 Wave 5。
  - P2：imports partial 已有 `quality_status=partial` 显式投影（前端呈现属产品任务，未改）；
    assistant 分层配额说明补入 20_assistant.md（外层 30/1800s vs 内层 author 12）。
