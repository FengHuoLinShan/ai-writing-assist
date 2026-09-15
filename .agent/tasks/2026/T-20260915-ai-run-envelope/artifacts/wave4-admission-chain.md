# Wave 4 准入链复核（2026-09-16）

## 结论

首个 provider 请求前已经存在可复用的接缝：Imports 在 `DeepImportOrchestrator._start` 冻结
授权/模型快照并经 `_enqueue_workflow` 写入 `AsyncTask.meta` 与 `ImportWorkflowRun`；worker 领取后
由 `TaskRunEnvelopeKeeper.open()` 恢复或建立账本，`persist()` 通过现有 lease-fenced
`checkpoint_run_envelope` 落到私有 meta；真正请求再由 `AIRunEnvelope.reserve()` 闸住。无需新表、
新队列或第二套预算运行时。

## 真实链路

1. 用户调用 `/api/imports/deep` 或 `/api/imports/stages/*`；API 只做 owner、章节范围和已有授权校验。
2. `DeepImportOrchestrator._start` 生成 `authorization_snapshot`、LLM execution snapshot，
   复核同作品活动 run 后进入 `_enqueue_workflow`。
3. `_enqueue_workflow` 使用现有 `enqueue_coalesced_task`，把章节范围、快照、采用策略和
   `authorization_snapshot` 写入 `AsyncTask.meta`，再创建 `ImportWorkflowRun` 的 checkpoint owner。
4. `TaskWorker._execute_task` 领取 lease 后打开信封；声明 root 的任务先写一次 lease-fenced 快照，
   失去 lease 或 checkpoint 失败则在 handler/provider 前失败关闭。
5. Imports 的每次阶段进度通过现有 `project` callback 写入 `ImportWorkflowRun.progress`、
   `checkpoints` 和 task result；实体融合的每个 12-pair 批次在同一 checkpoint 粒度落盘。
6. `AIRunEnvelope.reserve()` 位于 provider I/O 前；预算/期限/身份拒绝不会产生 provider 请求。
   预算耗尽由现有 lifecycle contract 呈现 `resume/abandon`，`resume_manual()` 才能以
   `author_resume` 增加同一 run 的额度，自动 retry/requeue/recovery 不扩额。

## 本轮已落地的无副作用准入信息

- Phase 0 结束、Phase 1a provider I/O 开始前，在现有 `DeepImportProgress.phase_artifacts` 写入
  `imports.run-admission.v1` manifest：窗口数、批次粒度和“Scene 数由模型产生，当前 A 不可有限化”；
  不把未知数伪装成上界。
- Entity fusion deep-import 在 `_prepare_task_scan` 完成后、第一对 provider I/O 前写入同版本
  manifest：candidate pair 数、12 对批次、pair 决策 `6 × pairs` 与 knowledge audit `9`；
  对实际 pair_count 逐项计算 `A=6M+9`，不截断数量后误报较小 A。
- Entity fusion 恢复读取最后一个 `batch` checkpoint，复用已完成 decisions/suggestions，
  从完整 12-pair 边界继续，尾批可以小于 12。pair 全部落盘先记 `pairs_complete`；
  只有带 `knowledge_review` 的 `decided` 才直接复用。旧 `decided` 缺审查回执时只补 audit，不重放 pair。
  普通 World 融合不产生 deep-import manifest；准入 manifest 只由 Imports 通过 world facade 的窄 callback 提供。
  预算类 `AIRunEnvelopeError` 不再被吞成
  degraded 结果。
- `world_cocreation_turn` 已以 `world.generation.cocreation` 作为 canonical parent，按
  `mode/quality_mode` 在领取前冻结 task-path A=10/14/24；其 chat/design 子步骤仍沿用各自
  知识审查策略。

## 后续裁决与完成

- 用户要求持续完成计划后，Imports 的完整/分阶段流水线采用真实业务 parent
  `imports.deep_import`，而不是 infrastructure fallback。模型产生的整轮 A 仍不伪造；每次
  作者授权 H=256，与信封 recent-attempt 窗口一致。首次 `authorization_confirmed` 只授权首段，
  后续沿用现有 resume/abandon，`author_resume` 每次只追加一段。
- Phase 0 manifest 在首次 provider I/O 前通过现有 progress callback 持久化。所有会把 provider
  失败降级的 Imports/Story/World 边界均先传播 `AIRunEnvelopeError`；额度耗尽不会静默 fallback。
- Entity fusion 在进入下一完整 12-pair checkpoint 批次前检查剩余额度，并为尾批预留最终 9 次
  knowledge audit 上界，避免为额度不足发出无法落盘的一部分 pair 请求。
- 独立 targeted completion / review resolution 分别从冻结 roots 批次与候选/Scene 问题组计算
  完整 A；alias/relation 在 API 入队前把章节范围解析为精确 Scene ID 清单；Map Atlas 使用自己的
  稳定 run mirror。未新增表、队列、通用预算服务或前端状态机。

## 本轮验收

- `pytest backend/infrastructure/tasks/tests backend/modules/interaction/tests backend/modules/world/tests/test_entity_fusion.py backend/modules/world/tests/test_ai_run_envelope_world.py backend/modules/imports/tests/test_admission.py backend/modules/imports/tests/test_phase2_dedup_pipeline.py -q`：**378 passed, 2 deselected**。
- `make prompt-contracts`：**24 contracts passed**；changed-file `ruff check`：**All checks passed**。
- `make docs-check BASE_REF=origin/main` 与 `git diff --check`：通过。
- 主 Agent 独立运行 `make test-ci TEST_WORKERS=2`：test-deploy **270 passed**；backend
  **5746 passed, 13 skipped, 11 warnings**，coverage **86.02%**；frontend **191 files / 2491 tests**。
  secret hygiene、backend/frontend audit、lint、docs 均通过；backend audit 仅有已存档的
  `langchain-community` adverse status，无漏洞。
- 后续专用 PostgreSQL 验收见 TASK；真实 provider 未获费用/凭据授权，保持未执行。
