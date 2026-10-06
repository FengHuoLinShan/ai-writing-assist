---
id: T-20261006-event-soft-delete-merge
title: 事件扩展软删修复并合入主干
status: active
created: 2026-10-06T22:30:00+09:00
updated: 2026-10-06T22:30:00+09:00
---

# 事件扩展软删修复并合入主干

## 恢复快照

- 实际完成：原事件分支在隔离工作树合入已核实主干；初版 World 相关 1276 测试通过。双轴审查发现不安全 downgrade 和并发状态失效，已修复并通过专用 PG 验证。
- 下一步：运行新增生命周期 PG 用例、受影响 World 测试和文档门禁；固定提交开 PR，必需检查通过后合并。
- 阻塞：无。
- 工作区：/Users/tywww/.codex/worktrees/event-soft-delete-merge/ai-writing-assist；codex/event-soft-delete-integration；集成 HEAD 44c9cc1032d958ec484cefca9622b5c36a90adad，尚有本任务修复未提交。
- 最后核实：origin/main 9e98128775fc53d5672e8f47eccb5a325522fcf1（PR #201）；原 codex/event-soft-delete@221ef2339 及全部原工作区 WIP 保留。

## 目标与验收

- 用户要求“事件软删的分支线先合并”，包括必要修复、验证、提交/PR 与主干合并；此后继续更新远景计划。
- AO-12 历史保留、过滤、复活、409、来源失效与 novel_id 边界正确；迁移一致；固定 PR head 的全部必需检查通过再合入 main。
- 不包含生产迁移/部署、真实作品写入或付费模型运行。

## 上下文与边界

- 原实现：221ef23394047e45fdffe26b1f83762f055f21a6；需求见 docs/plans/2026-10-06-architecture-optimization.md AO-12。
- 独立 Standards/Spec 只读审查获 code-review 技能要求；主 Agent 负责写入和验证。
- 仅本任务新建 event_soft_delete_merge_e2e_20261006_a7c39e 为可丢弃 PG 库；同名无后缀旧库已存在，未使用或修改。
- 保护 Guimi/共享真实库、原分支和其他工作树；迁移仅应用到专用库。

## 进度与决策

- [x] 核实分支、主干、WIP 和实时 main ruleset；隔离集成。
- [x] 初版 baseline 文档及受影响 World 测试通过。
- [x] 两轴确认历史硬删与无锁复活；Spec 另确认删除后更新可绕过 canonical 检查。
- [x] 修复、PG 实测与独立复核；结果见 review.md。
- [ ] 固定 head 的 PR 检查、合并与结果核验。
- [ ] 更新原第一阶段计划、交付状态与恢复快照。

## 验证与交付

- 修复后 World 与 event helpers 1276 passed；专用 PG critical 63 passed。随后补锁前删除交错/表锁保护，新增生命周期与迁移 6 passed（含 backfill、拒绝降级、安全往返与 ORM parity）。
- ruff check 与 diff 检查通过；文档差异门按正式 no-change-reason 入口通过，逐项说明见 docs-impact.md。原始 make BASE_REF 因需补无影响说明而失败，未修改门禁。
- 未运行真实模型、作者试用或生产验收。
- 交付尚在本地主题分支；未创建 PR 或合并本分支。
