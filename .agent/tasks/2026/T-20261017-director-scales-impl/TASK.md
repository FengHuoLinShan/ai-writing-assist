---
id: T-20261017-director-scales-impl
title: 导演多尺度独立探索多批次实施
status: active
created: 2026-10-17T19:30:00+08:00
updated: 2026-10-17T19:30:00+08:00
---

# 导演多尺度独立探索：多批次实施

## 恢复快照

- 实际完成：**第一批全部门禁通过**（82ca717e6 一系）；**第二批 M2 全部完成**（7 个小切片：
  M2-a 反事实对照 8e1e1309c、M2-d 就地入口+教程 1024a1931、M2-e 对照 UI 6155fa7bb、
  M2-b 事件信息差/导向 5ee812d44、M2-f 事件渲染 551200671、M2-c 场景多目标+空间诊断 c9169bd2b、
  M2-g 场景渲染 9b0ce1fa4，全部合入 impl 至 fecbede89）。M2 收尾门禁：后端 1288、前端全量 3294、
  docs-check（no-change-reason）+ git diff --check 通过。
- M3 已交付：研究覆盖账本（702bab1c2）；M3-A1 锁定机制 + M3-A3 锁定展示并行实施中。
- M5 离线准备已交付。真实模型/作者验证未启动（未授权）。
- 下一步：合入 M3-A1/A3 → M3-A2 影响标记（compare counterfactual 增 affected_items）→
  M3-B 临时完整排演（拆 2-3 切片）→ M4-A/B/C。
- 阻塞：无。合并 main/推送/ADR 采纳/生产/真实验证均待用户授权。
- 已知遗留（沿批记录）：M2 反事实/event hint 字段部分未暴露进助手操作目录（REST-only）；
  goal 条目与多目标/诊断结果不支持 revise（失败关闭，M3-B 范围再评估）；scene_anchor 反事实 409；
  exploration_tasks 一处死代码分支（scale==EVENT_OUTPUT_KIND）待单独清理提交。

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

- 2026-10-17：基线核实 `git rev-parse origin/main main` = 6004d3703 一致；worktree 建立成功。
- 实施验证随各 Wave 记录（模块测试、lint、PostgreSQL 隔离库迁移、前端 Vitest、docs-check）。

## 下一步

- Wave0 三个 Explore 代理派出并回收；P0 契约文档落盘本任务目录并提交。
