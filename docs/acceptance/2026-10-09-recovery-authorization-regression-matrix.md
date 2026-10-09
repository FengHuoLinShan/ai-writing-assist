# 恢复与授权回归矩阵基线（BR-0b，2026-10-09）

依据 `docs/plans/2026-10-09-guided-flow-borrowing.md` §5 BR-0b 与外部交接 P0-4
「恢复与授权回归矩阵」。八场景逐一钉成可定位用例；测试暴露的两处真实缺陷已按
计划做最小修复。验收口径：不会重复领域写入、不会覆盖新稿、部分结果不成为正式事实。

行号与用例名以本文提交时的 HEAD 为准；后续重构请以场景语义迁移用例，勿删断言。

## 矩阵

| # | 场景 | 用例（文件::用例名） | 状态 |
|---|---|---|---|
| 1 | 模型返回但结果未提交 | `backend/modules/writing/tests/test_writing_generate_recovery.py::test_requeued_generation_reuses_frozen_paid_output`；`test_frozen_candidate_reused_only_on_fingerprint_match`；`backend/infrastructure/tasks/tests/test_api.py::test_task_status_hides_private_run_envelope`（冻结负载不进 wire） | **缺陷已实测并修复**：finalize 前崩溃重排原会第二次调用付费模型（实测 `generate_calls == 2`）；现按 Evolution `freeze_attempt` 模式在 worker checkpoint 把已付费输出冻结进任务私有 meta（`_frozen_candidate`，下划线键不进任务状态 API），重排按来源指纹复用，模型仅调用一次。租约丢失时栅栏拒绝冻结，行为安全退回重调。finalize 的 project/确认/指纹重验仍是最终门禁。 |
| 2 | 正文已存、派生未完成 | `backend/modules/writing/tests/test_publish_index_recovery.py::test_publish_success_index_failure_visible_and_pending_index_recovers` | 发布落库与索引派生分别投影：索引失败（3 次重试耗尽）任务 failed、正文不回滚；`RagIndexState` 非 succeeded 且在 `freshness` 投影里 stale，作者可见；`mark_dirty` 入队的 `rag_index_chapter` 在途 owner 任务完成索引后恢复 `succeeded`/fresh。chunk 级 embedding 失败另有 `retry-embeddings` 入口。 |
| 3 | 等待中编辑或撤权 | `backend/modules/writing/tests/test_writing_generate_task_transactions.py::test_continuation_discards_candidate_when_base_draft_edited`；`test_generation_revoked_model_connection_writes_no_candidate`；既有漂移族 `test_generation_discards_context_and_evidence_drift`、`test_generation_discards_confirmation_lifecycle_drift`、`test_project_profile_drift_before_finalize_writes_no_candidate` | 续写基稿被编辑 → finalize 指纹重验丢弃，模型已付费但候选不落库，作者编辑过的工作稿不被覆盖；撤销模型连接 → finalize 的 snapshot 恢复失败关闭，不落候选。 |
| 4 | 旧 worker 回写 | `backend/modules/writing/tests/test_writing_lease_writeback.py::test_semantic_review_rejects_stale_lease_writeback`（真实审查链经 worker，provider 等待期捕获运行中租约）；`test_targeted_revision_rejects_stale_lease_writeback`（重排后新租约完成，旧租约 poison 回写被拒）；通用栅栏 `backend/infrastructure/tasks/tests/test_lifecycle.py::test_claim_freezes_lease_and_rejects_old_lease_completion`、`test_heartbeat_is_fenced_by_lease` | 晚到回写携带旧租约时 finalize/心跳按 `(task_id, lease_id)` 行锁匹配拒绝，已落库的审查/返修结果不被覆盖。 |
| 5 | 回包丢失后重复点击 | `backend/modules/writing/tests/test_writing_operation_replay.py::test_submit_generation_replays_same_operation_without_second_task`；`backend/modules/writing/tests/test_adoption_idempotency.py::test_adopt_replay_with_same_key_returns_original_receipt`、`test_adopt_replay_without_key_or_with_other_key_still_rejected`、`test_adopt_route_replay_with_idempotency_key`；通用 receipt `backend/infrastructure/tasks/tests/test_coalescing.py::test_operation_receipt_reuses_terminal_task_and_rejects_drift` | 写作生成同 `operation_id`+同指纹重放返回原任务，异指纹 409；**缺陷已修复**：候选采用原无幂等键，重放报错而非返回原回执；现 `POST /writing/drafts/{id}/adopt` 支持可选 `idempotency_key`，同键重放返回原采用结果（键存于候选与采用稿 provenance），无键/异键维持原校验错误。前端按 `writing-adopt-v1:<draftId>` 确定性带键。 |
| 6 | 页面重连 | `frontend-console/tests/vue/writing/writingCommandController.test.js`「restores a completed result after reload…」「刷新后恢复在途独立语义审查…」「刷新后恢复在途定向返修…」「does not recover another tab's writing receipt」「clears a missing generation receipt without replaying the request」 | 刷新恢复只续轮询已登记回执，不重提交；语义审查/定向返修与生成同一 `recover()` 路径（`MANAGED_WRITING_TYPES`）。换设备恢复的服务端查询归 BR-1a。 |
| 7 | 候选完成但审查失败 | `backend/modules/writing/tests/test_writing_knowledge_governance.py::test_blocked_knowledge_review_keeps_candidate_unadoptable`、`test_blocked_knowledge_review_rejects_adoption_at_service_gate`；语义门禁 `backend/modules/writing/tests/test_semantic_review.py::test_unmet_contract_item_yields_major_finding_and_blocks_adoption` | 候选照常保存（作者可作手工素材），知识复核 blocked 时采用门禁失败关闭：服务端不产生工作稿、候选状态不被改写。显示分层（不弹成功等）归 BR-2。 |
| 8 | 计费状态未知 | `backend/infrastructure/tasks/tests/test_run_envelope.py::test_stale_recovery_converges_in_flight_into_the_same_run`、`test_external_cancel_finishes_the_run_and_converges_in_flight`（`writing_generate` 类型）、`test_completed_payload_never_exposes_private_run_envelope`；投影 `backend/infrastructure/tasks/tests/test_lifecycle.py::test_operation_projection_unifies_receipt_recovery_and_partial_result` | 恢复/取消把未 settle 请求收敛为 `requests_unknown`/`charge_state=possible`，绝不写成零用量；信封是 meta 私有键，公开投影只给 `possible_charge` 标记。跨任务聚合与文案归 BR-0a。 |

## 交接评测表 13 项对应

| 评测项 | 覆盖 |
|---|---|
| 模型后保存失败（冻结结果可复用；不悄悄重复付费生成） | 场景 1（本轮修复+实测） |
| 确认回包丢失（同 operation/attempt 不重复写入） | 场景 5 |
| 派生状态更新失败（正文和状态分别投影） | 场景 2 |
| 生成中编辑/撤权（旧结果不覆盖、不越权采用） | 场景 3 |
| 检查覆盖不完整（保留遗漏与 unverifiable，不给虚假通过） | 场景 7 + BR-0c（单次路径收口） |
| 其余 8 项（未发生的未来事实、角色说谎、同长度替换、跨进程缓存、轻微风格问题、RP 来源版本冻结、从零开篇、长篇续写） | 由 BR-0c、BR-2、BR-5、BR-6 与既有 World/Story 测试覆盖，不在本包 |

## 遗留与边界

- 冻结负载在任务终态后仍留在任务行 meta（下划线私有键，不进 API）；`restart_origin`
  复用已付费输出是期望语义。任务行清理策略不变。
- 冻结发生在模型返回后、finalize 前；进程在模型调用中途死亡时输出本就无法持久化，
  该窗口不承诺 exactly-once（与交接口径一致）。
- 采用的并发串行化依赖章节版本锁的 Postgres advisory key（SQLite 测试不模拟
  真并发）；见 `test_writing_api_generation.py::test_writing_version_lock_uses_sorted_postgres_advisory_keys`。
- 场景 2 中 `publish_chapter` 任务自身的 `restart_origin` 动作在任务 API 的
  `/retry` 入口仅受理 `auto_requeue`；实际恢复路径是 `mark_dirty` 入队的
  `rag_index_chapter` 在途任务与设置页 `retry-embeddings`/reindex 入口。
  该动作可执行性的差距记入 BR-1a/BR-2 的前端展示裁定，不在本包改行为。
