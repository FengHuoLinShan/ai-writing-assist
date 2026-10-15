---
id: T-20261015-agent-operation-surface
title: 全模块 AI 操作入口、目标运行与操作留痕设计
status: active
created: 2026-10-15T14:30:00+08:00
updated: 2026-10-15T14:30:00+08:00
---

# 全模块 AI 操作入口、目标运行与操作留痕设计

## 恢复快照

设计稿与 ADR-0039、ADR-0040（Proposed）已起草，2026-10-15 经用户授权本地提交，未推送。与地图增强设计
（T-20261015-map-enhancement-design）同在工作树 `.worktrees/map-enhancement-plan`、分支
`codex/map-enhancement-plan`（基于 main `d2ab2dbf3`；核对现状时 origin/main 为 `4efe7f21a`）。
下一步：用户评审 ADR-0039/0040，并裁定两项（目标运行是否允许 R2 自动执行、本机默认记录界面操作）；
推送或开 PR 按用户安排。实施由用户另行安排执行者，本任务只负责设计与文档。

## 目标与验收

- 目标：各模块开放或增加 AI 操作入口，让 AI 能自主规划、操作，完成作者的目标；
  操作留痕，便于以后把常用操作代码化。
- 验收：设计稿和 ADR 写明与 ADR-0013、0023、0027、0029、0031、0032 的关系（修订 ADR-0023 的
  写入确认在目标运行内的适用）；`make docs-check BASE_REF=origin/main` 通过。

## 用户要求（2026-10-15）

- 开放或增加各模块的 agent/AI 操作入口，方便 AI 自主规划、操作，以完成用户目标。
- 操作留痕，方便后续版本将用户常用操作代码化实现。

## 已核实现状（main `4efe7f21a`）

- 助手业务操作 47 个：world 18（含地图 4）、story 11、writing 9、imports 5、project 3、evidence 1；
  `suggest` 9 个，其余 `confirm`。
- 后端路由约 680 个，写路由约 430 个；evolution、interaction、collaboration、account、local_agent
  没有助手操作。
- `available_operations` 一次返回全部操作的完整 schema。
- 没有统一操作留痕，也没有前端埋点；`local_agent` 的产品工具中继已删除（ADR-0029）。

## 关键决定与理由

- 界面与 AI 共用一份操作目录，并加性扩展字段：两条路径校验一致，留痕也能放在同一层。
- R0–R4 风险分级：现有 `suggest`/`confirm` 两档不足以支撑自主执行；采用和正史（R3）、
  付费外部或不可逆（R4）始终停下确认。
- 新增模型规划的目标运行，而不是放开引导流程：计划是数据，只能引用目录项；
  执行由确定性引擎推进；高频计划经留痕代码化为引导流程。
- 留痕挂在目录层而不是前端埋点；不记录内容，自由文本只记长度和加盐 hash；
  执行事件与写入同事务；明细 180 天后汇总。
- 外部 Agent（MCP）接入不在本轮范围：ADR-0029 已删除工具中继，需要时另立 ADR。

## 交付

- `docs/plans/2026-10-15-agent-operation-surface.md`
- `docs/adr/0039-unified-operation-catalog-and-goal-runs.md`
- `docs/adr/0040-operation-trace-and-codification.md`
- `docs/adr/README.md`、`docs/README.md` 索引；ADR-0038 已链接本框架

## 验证

- 2026-10-15：`make docs-check BASE_REF=origin/main` 通过（48 个 ADR 文件，架构决策规则所需文档
  均已更新）；`git diff --cached --check` 通过。

## 风险与待决

- 待用户裁定：目标运行是否允许 R2 自动执行（建议允许，默认关闭）；本机单用户默认记录界面操作
  （建议采用）。
- ADR 编号 0039–0040：起草时 main 和本机 worktree 中没有占用。
