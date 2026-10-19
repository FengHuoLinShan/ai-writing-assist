---
id: T-20261017-director-scales-impl
title: 导演多尺度独立探索多批次实施
status: active
created: 2026-10-17T19:30:00+08:00
updated: 2026-10-18T12:54:22+08:00
---

# 导演多尺度独立探索：多批次实施

## 恢复快照

- 2026-10-18 深审追加发现 5 项：Goal 失败账本回退、历史编辑绕过锁、Scene 缺父版本 CAS、
  取消后领域检查点不可恢复、沙盘受影响者字段不匹配。用户要求“修复，然后 pr”。
- 五项已修，追加 PostgreSQL 根/分支外键排序和截止后历史费用结算修复；沿用主实施工作树 codex/director-scales-impl；修复提交 a12c80169。
  原 26 项修复的未提交成果保留并纳入本次 PR；修改前补丁与 3 个未跟踪文件备份在
  /private/tmp/director-before-review-fix.patch 与 director-before-review-untracked.tgz。
- 阶段证据：完整 test-ci 通过（后端 9505/85.48%，前端 3335，部署 324），专用 PG critical 112 项通过。
  最终后端全量 9508 passed / 2 skipped，覆盖率 85.48%；详细证据见 REVIEW-FIXES.md。
- 已提交推送并创建 [PR #255](https://github.com/FengHuoLinShan/ai-writing-assist/pull/255)；固定修复提交 a12c80169 的 repo-gates/docs-check 通过，与 origin/main 083843474 可无冲突合并。
- 下一步：核对 PR 远端 CI；后续合并、第五批真实模型/作者验收仍需相应授权，不自动执行。
- 真实数据库、业务模型与作者验收未获本轮新增授权；ADR-0042 仍 Proposed。
- 上轮工程证据保留在 REVIEW-FIXES.md；上轮“未见剩余缺陷”已被本轮反例推翻。

此前实施批次及 4778e40c8 等提交仅为工程历史；审查发现的旧设计偏差已由本轮整改替换。

## 目标与授权

- 用户指令（2026-10-17）：“并行执行 codex/director-scales-plan 中的多批次计划”，视为实施授权。
- 依据计划：`docs/plans/2026-10-17-director-scales-independent-exploration.md`（Draft）与 ADR-0042（Proposed）。
- 执行范围：第一批 P0–P4 全量；第二/三/四批按依赖推进；第五批仅离线准备。
  不调用真实业务模型、不招募作者、不开启生产功能、不部署；封存评测不动。
- 前置规划任务：[T-20261017-director-layer-design](../T-20261017-director-layer-design/TASK.md)（completed）。

## 工作区

- 主实施区：`/Users/tywww/项目/ai-writing-assist/.worktrees/director-scales-impl`，
  分支 `codex/director-scales-impl`，基线 origin/main `6004d3703`（2026-10-17 与本地 main 一致）。
- 规划参考区：`.worktrees/director-scales-plan`（只读参考，不再写入）。
- 并行代理按独立 worktree/分支规则工作；主区负责集成与验证。

## 批次与并行结构（依赖序）

- Wave0：三探索（Evidence / Story / Assistant+前端）并行 → P0 契约冻结（P0-CONTRACTS.md）。
- Wave1 P1：Evidence 新起点确认 + Story 两类根/历史 + Alembic（契约冻结后分 Evidence/Story 并行）。
- Wave2 P2：B1+B2 世界推进链 / B3 导演链并行。
- Wave3 P3：助手操作目录与前端结果闭环并行。
- Wave4 P4：兼容回归 + 文档 + 门禁。
- 第二批起按计划依赖顺序，跨批并行仅限设计/准备类只读工作。

## 决策、发现与失败

- 2026-10-17：规划分支 `codex/director-scales-plan` 无领先提交（完全包含于 main），实施改从
  origin/main 新建分支；计划文档已在 main。
- 实施不放松：novel_id 隔离、owner 校验、Evidence confirmation 重物化、预算/幂等、不可变触发器。
- P0 关键裁定（细节见 P0-CONTRACTS.md）：紧凑输出复用两类既有根/分支/结果表 + `output_kind`
  判别联合（不新建表/模块）；两根表加 `source_kind` 列并放开 scene_id 非空（CHECK 限定仅
  provisional 可空）；Evidence 新增 `ExplorationContextRequest` 与三项能力注册，重物化跳过
  Scene/大纲指纹门但保留核心指纹；隐藏守卫仅覆盖 canonical 引用，临时主体以声明知识包为边界；
  联网仅冻结助手当轮已读快照，worker 不做实时检索；操作目录六项、runtime_version 17→18；
  gate `STORY_EXPLORATION_ENABLED` 默认关，history/compare 关闭可读。

## 验证证据

- 2026-10-17：基线 origin/main 与本地 main 6004d3703 一致；各批实施历史见 Git 与同目录契约材料。
- 2026-10-18：整改完成后的完整门禁、逐项回归映射、未验范围及本地日志见 [REVIEW-FIXES.md](REVIEW-FIXES.md)。
- 最终离线通过不构成 ADR 采纳、作者确认、真实模型效果、生产可用性或远端交付证明。

## 下一步

- 本轮工程修复和 PR 创建已完成，远端 CI 以 PR 当前状态为准；第五批独立验收仍待，当前不合并或部署。
