---
id: T-20261017-director-scales-impl
title: 导演多尺度独立探索多批次实施
status: active
created: 2026-10-17T19:30:00+08:00
updated: 2026-10-18T00:00:00+08:00
---

# 导演多尺度独立探索：多批次实施

## 恢复快照

- **第四批（M4）全部完成并合入**：M4-A1 六向移交契约/服务（14f018bf8）、M4-C 正式 Scene
  参考副本（b85630f8c）、M4-A2 移交端到端测试、M4-A3 前端移交入口、M4-B1 探索操作接入
  目标运行（领域独立账本 + 结算后导入增量，含 app task manifest 补注册 `exploration_tasks`）。
- **收尾回归与治理修复完成（本地分支）**：依赖方向棘轮 517/517、治理/路由闭包/路由棘轮/
  evidence fusion 四门禁 70 passed；story+assistant 755 passed；docs-check（--no-change-reason
  通道）与 `git diff --check` 通过。修复要点：家族函数下沉 `exploration_schemas` 解导入环、
  守卫只放 `api_start` 包装层（operations 以 db=None 复用共享函数）、api/operations/service
  对 evidence facade 与 tasks facade 的调用改为模块属性晚绑定（恢复 monkeypatch 测试缝）、
  `_BASE_KIND_BY_SCALE` 映射纠正、`director_api`/`director_service` 懒导入上提。
- 待提交：9 文件（7 个 story 模块 + 2 个 README 增量），建议单 commit。
- 下一步：提交治理修复 → 全分支实施总结交付；合并 main/推送/ADR-0042 采纳待用户授权；
  真实模型调用、作者验证、生产功能开启、部署均不启动。
- 阻塞：无。
- 已知设计偏差（评审注意）：探索 worker 对推进链改为服务内直接落行（35a17dac3 docstring）；
  排演/多目标/诊断结果 detail/revise/lock/save-edit 一律 409；探索链无作者侧 resume 端点；
  排演 action 沿用 scene_line.generate；M4-C 端点用 operation-exemption 未入助手目录；
  handoff 链仅一跳记录；M4-B1 领域账本内目标侧 80% 实时检查存在盲区（结算后导入兜底）。

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
- 2026-10-18 收尾：治理四门禁 70 passed（含棘轮 517/517）；story+assistant 755 passed；
  全量后端套件、docs-check（no-change-reason）、`git diff --check` 结果随收尾提交记录。

## 下一步

- 提交收尾治理修复；交付全分支总结（含偏差清单）；其余待授权项见恢复快照。
