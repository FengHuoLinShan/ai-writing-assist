---
id: T-20261009-guided-flow-borrowing-br0b
title: 借鉴计划实施包 BR-0b 恢复与授权回归矩阵基线
status: completed
created: 2026-10-09T14:30:00+09:00
updated: 2026-10-09T18:40:00+09:00
parent: T-20261009-borrowing-plan-refinement
---

# BR-0b 恢复与授权回归矩阵基线

## 交付结果

- 8 场景全部钉成可定位用例，矩阵见
  `docs/acceptance/2026-10-09-recovery-authorization-regression-matrix.md`。
- 缺陷 1（实测确认）：写作生成 finalize 前崩溃重排会第二次调用付费模型。已按
  Evolution `freeze_attempt` 模式修复：模型返回后、finalize 前经租约栅栏 checkpoint
  冻结已付费候选进任务私有 meta（`_frozen_candidate`，下划线键不进任务状态 API），
  重排按来源指纹复用；租约丢失拒绝冻结、退回重调；finalize 重验仍是最终门禁。
- 缺陷 2（矩阵暴露）：候选采用无幂等键，重放报错。已加可选 `idempotency_key`
  （API query 参数 + service/facade 参数），同键重放返回原采用回执，键存 provenance；
  前端按 `writing-adopt-v1:<draftId>` 确定性带键。
- 文档：Writing README（冻结+采用幂等）、tasks README、docs/modules/11、12、14、
  frontend-console/README 已同步；docs-check（含 BASE_REF=origin/main）通过。

## 验证

- `pytest modules/writing/tests infrastructure/tasks/tests`：467 passed。
- `pytest tests/`（除 e2e/integration 目录约定）：1851 passed；integration authoring 4 passed。
- evidence indexing/compilation knowledge、assistant 测试目录通过。
- 前端 `vitest run tests/vue/writing/`：258 passed；api-contract + editorController 52 passed。
- `ruff check`、`eslint`（触碰文件）、`scripts/check_module_imports.py`、docs-check 均通过。
- 基线已知：从仓库根跑 writing 测试有 2 个 CWD 相对路径用例失败（test_writing.py
  读 `modules/...`），从 backend/ 目录跑全绿，与基线一致。

## 遗留

- 场景 2：`publish_chapter`（restart_origin）在任务 API `/retry` 仅受理 auto_requeue，
  实际恢复路径是 mark_dirty 入队的 rag_index_chapter 在途任务与设置页 reindex/
  retry-embeddings；动作可执行性差距记入矩阵，留给 BR-1a/BR-2 裁定。
- 冻结负载终态后留任务行 meta（私有键）；进程在模型调用中途死亡不承诺 exactly-once。
- 计划外发现：发布流程会留下两个 scope 不同的 pending rag_index_chapter 任务
  （coalescing key 不同，非本包范围）；SQLite 环境 advisory lock 不模拟真并发。

# BR-0b 恢复与授权回归矩阵基线

## 目标与验收

- 依据 `docs/plans/2026-10-09-guided-flow-borrowing.md` §5 BR-0b：交接 P0-4 八个场景逐一钉成
  可定位用例；缺的补测试；测试暴露真实缺陷时才做最小修复。
- 验收：8 场景均有可定位用例；不会重复领域写入、不会覆盖新稿、部分结果不成为正式事实。
- 非目标：BR-0a（用量聚合 unknown）、BR-0c（知识复核单次路径收口）、BR-2（显示分层）、
  BR-1a（服务端在途查询）、迁移 schema（本包无 migration）。

## 场景清单与处理决定（调查结论）

| # | 场景 | 现状 | 本包动作 |
|---|---|---|---|
| 1 | 模型返回但未提交 | finalize 单事务写候选+绑定确认；崩溃后重排无冻结→重调模型（代码已确认无 freeze 机制） | 实测用例 + 按 Evolution freeze_attempt 模式在 meta 私有键 `_frozen_candidate` 冻结已付费输出，重排复用（无 migration，meta 下划线键不进 API） |
| 2 | 正文已存、派生未完成 | 发布标索引 dirty+入队 publish_chapter；索引失败标 state failed | 补"发布成功、索引失败→作者可见且可重试"集成用例 |
| 3 | 等待中编辑或撤权 | finalize 行锁重验指纹；有 context drift 用例 | 补续写基稿被编辑、撤销模型连接两个专测 |
| 4 | 旧 worker 回写 | finalize/heartbeat 租约栅栏；T test_lifecycle 有通用用例 | 补语义审查与定向返修的旧租约回写拒绝用例 |
| 5 | 回包丢失重复点击 | operation_id 幂等（enqueuer+coalescing 通用用例） | 补写作生成同 operation 重放用例；采用加幂等键（缺陷：二次采用报错而非返回原回执） |
| 6 | 页面重连 | 前端 recover() 只续轮询；有生成恢复用例 | 补语义审查/返修刷新恢复组件测试 |
| 7 | 候选完成但审查失败 | 候选先存、知识未通过禁采用；已有用例 | 矩阵标注现有用例，视情况补服务端 adopt 门禁用例 |
| 8 | 计费状态未知 | 恢复/取消记 unknown/possible；已有用例 | 矩阵标注现有用例 |

## 关键设计（场景 1 冻结）

- `handle_writing_generate` 把 task ORM 对象传入 `generate_candidate_for_task`；
  LLM 返回构建 candidate 后、finalize 前，把 `candidate.model_dump(mode="json")` +
  `source_fingerprint` + attempt/lease 写入 `task.meta["_frozen_candidate"]`，
  经 `checkpoint_handler_session` 租约栅栏提交（复用 `_TaskHandlerSession` commit hook）。
- 重排时 prepare 后比对 `plan.source_fingerprint`：一致则跳过模型调用直接 finalize；
  不一致丢弃冻结、走原路径重调（finalize 重验仍是权威门禁）。
- 采用成功不主动清冻结负载（终态 finalize 的 UPDATE 不含 meta，且 restart_origin 复用
  已付费输出是期望语义）；任务 API 经 `_public_task_meta` 剥离下划线键，负载不进 wire。
- 采用幂等（场景 5）：`adopt_candidate_to_working` 增可选 `idempotency_key`；
  已 deprecated 且 provenance 有 `adoption_result_draft_id` 时，键一致→返回原采用回执，
  键不一致/无键→维持现有 ValidationError。

## 工作区

- worktree `.worktrees/br0b`，分支 `codex/borrow-br0b`（以 7b30d9b44 为基线，含计划提交）。
- 只在分支 commit；不 merge/push/rebase。

## 下一步

1. 场景 1 实测用例（先写暴露重调的失败用例，再实现冻结）。
2. 其余场景补测试 + 采用幂等最小修复。
3. 回归矩阵文档（docs/acceptance/ 日期命名），标注现有用例。
4. 受影响模块测试 + lint + docs-check；commit。
