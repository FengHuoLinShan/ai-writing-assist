---
id: T-20261006-event-soft-delete-merge
title: 事件扩展软删修复并合入主干
status: completed
created: 2026-10-06T22:30:00+09:00
updated: 2026-10-12T23:36:26+08:00
---

# 事件扩展软删修复并合入主干

## 当前恢复快照（2026-10-12 整理核实）

- 实际交付：[PR #202](https://github.com/FengHuoLinShan/ai-writing-assist/pull/202) 已合入 main，合并提交 `85fb1c7be35ae687f949863d179f5fd63c53f3c0`，当前 main 可达。
- 状态：事件软删、并发互斥和迁移验证及合并已完成；保留原工作树独有的合并后验证结论。
- 主干检查：原合并提交检查已成功，旧“仍在运行/未合入”不再适用。
- 下一步：本任务关闭；第一阶段质量/费用及生产迁移、部署仍按其原授权与验收处理。

- 唯一后续主笔记：主工作树本路径 `/Users/tywww/Desktop/项目/ai-writing-assist/.agent/tasks/2026/T-20261006-event-soft-delete-merge/TASK.md`；旧工作树副本只读。
- 最后核实：2026-10-12T23:36:26+08:00。以下各节保留原验收、失败和授权的历史证据，不代表当前交付状态。

## 历史记录

## 恢复快照

- 实际完成：原事件分支在隔离工作树合入已核实主干；初版 World 相关 1276 测试通过。双轴审查发现不安全 downgrade 和并发状态失效，已修复并通过专用 PG 验证。
- 下一步：用户另行启动第一阶段时按更新后的计划执行 M0；生产迁移/部署仍需独立授权。
- 阻塞：无。
- 工作区：/Users/tywww/.codex/worktrees/event-soft-delete-merge/ai-writing-assist；codex/event-soft-delete-integration；固定 PR head 79fca4eb29823ce49a3b66c421a8620ae3fcfa2d；修复已提交/推送，本文最新状态更新留本地，不改变被验提交。
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
- [x] 固定 head 的六项必需检查、CodeQL 和 repo-gates 全部通过；PR #202 已于 2026-10-06T22:45:35+09:00 合并，main 为 85fb1c7be35ae687f949863d179f5fd63c53f3c0。
- [x] 第一阶段计划基线已更新到事件合并提交，架构复用点、剩余业务工作与验收边界已同步。

## 验证与交付

- 修复后 World 与 event helpers 1276 passed；专用 PG critical 63 passed。随后补锁前删除交错/表锁保护，新增生命周期与迁移 6 passed（含 backfill、拒绝降级、安全往返与 ORM parity）。
- ruff check 与 diff 检查通过；文档差异门按正式 no-change-reason 入口通过，逐项说明见 docs-impact.md。原始 make BASE_REF 因需补无影响说明而失败，未修改门禁。
- 未运行真实模型、作者试用或生产验收。
- PR #202 已创建并附着本任务：https://github.com/FengHuoLinShan/ai-writing-assist/pull/202；head 79fca4eb2。已合并 main，不含生产迁移或发布。

- 固定 head 远端 PostgreSQL critical：64 passed；Architecture docs、repo-gates、Frontend unit、Production image、CodeQL 与 Backend quality 已通过，浏览器分片尚在运行。仓库规则仍按实时必需检查完成后合并，不用管理员绕过。

- 最终 PR 工程证据：Backend quality 7138 passed/3 skipped，覆盖 86.31%；PostgreSQL critical 64 passed；functional 两片共 304 passed/2 skipped（长资料库性能默认关闭），shard 1 另有辅助流程 8 passed。所有六个必需检查及 CodeQL 均成功。
- 合并后 main 的独立 CI 已触发，当前仍在运行；不把 PR 检查替代 main CI。仅本任务创建的 event_soft_delete_merge_e2e_20261006_a7c39e 已删除，既有同名无后缀测试库、Guimi 和原工作区全部保留。
- 代码/迁移/文档已通过 PR #202 合入主干；本文合并后完成状态为本地恢复更新，未追加提交。第一阶段计划文档仍在其独立规划工作树，未提交/推送。
