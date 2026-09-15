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

## 未擅自裁决

- `H`（单次授权安全闸门）仍未写死：没有产品证据时不发明额度。
- 完整 `deep_import` 仍跨 `imports.scene_*`、`imports.entity_extraction`、
  `imports.structure_analysis` 与 `world.entity_fusion` 多个 root，继续 opt-out；不得用单一
  root 或 `infrastructure.*` 伪装迁移。
- 因此本轮只把 manifest 和可恢复批次语义落到现有 checkpoint；真正的 L0/H 暂停/续算 UI 需要
  产品确认后接入，不改变已存在的正常任务行为。

## 本轮验收

- `pytest backend/infrastructure/tasks/tests backend/modules/interaction/tests backend/modules/world/tests/test_entity_fusion.py backend/modules/world/tests/test_ai_run_envelope_world.py backend/modules/imports/tests/test_admission.py backend/modules/imports/tests/test_phase2_dedup_pipeline.py -q`：**378 passed, 2 deselected**。
- `make prompt-contracts`：**24 contracts passed**；changed-file `ruff check`：**All checks passed**。
- `make docs-check BASE_REF=origin/main` 与 `git diff --check`：通过。
- 主 Agent 独立运行 `make test-ci TEST_WORKERS=2`：test-deploy **270 passed**；backend
  **5746 passed, 13 skipped, 11 warnings**，coverage **86.02%**；frontend **191 files / 2491 tests**。
  secret hygiene、backend/frontend audit、lint、docs 均通过；backend audit 仅有已存档的
  `langchain-community` adverse status，无漏洞。
- PostgreSQL 与真实 provider 未执行；未连接开发库或受保护验收库。
