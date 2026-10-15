---
id: T-20261015-agent-operation-surface
title: 全模块 AI 操作入口、目标运行与操作留痕设计
status: active
created: 2026-10-15T14:30:00+08:00
updated: 2026-10-15T23:00:00+08:00
---

# 全模块 AI 操作入口、目标运行与操作留痕设计

## 恢复快照

设计稿与 ADR（Proposed）已于 2026-10-15 经用户授权本地提交 `87e56f241`，未推送。之后按用户要求核对
33 条外部评审并合并 ADR：原 ADR-0038（助手地图与势力操作）、0039（操作目录与目标运行）、0040（操作留痕）
合并为新 ADR-0038 `docs/adr/0038-ai-operation-catalog-goal-runs-and-trace.md`。用户随后裁定两项默认值
（见“关键决定”），修正与裁定经用户授权在第二个本地提交中提交，未推送。
与地图增强设计（T-20261015-map-enhancement-design）同在工作树 `.worktrees/map-enhancement-plan`、分支
`codex/map-enhancement-plan`（基于 main `d2ab2dbf3`；最后核对时 origin/main 为 `00d861283`）。
下一步：技术评审 ADR-0038 后转 Accepted；推送与 PR 按用户授权。实施由用户另行安排执行者，本任务只负责设计与文档。

## 目标与验收

- 目标：各模块开放或增加 AI 操作入口，让 AI 能自主规划、操作，完成作者的目标；
  操作留痕，便于以后把常用操作代码化。
- 验收：设计稿和 ADR 写明与 ADR-0013、0023、0027、0029、0031、0032 的关系（修订 ADR-0023 的
  写入确认在目标运行内的适用）；`make docs-check BASE_REF=origin/main` 通过。

## 用户要求（2026-10-15）

- 开放或增加各模块的 agent/AI 操作入口，方便 AI 自主规划、操作，以完成用户目标。
- 操作留痕，方便后续版本将用户常用操作代码化实现。
- 评审核对后：可合并的 ADR 合并。

## 已核实现状（main `4efe7f21a`，评审核对时复查）

- 助手业务操作 47 个：world 18（含地图 4）、story 11、writing 9、imports 5、project 3、evidence 1；
  `suggest` 9 个，其余 `confirm`。
- 装配两条路径：story、writing、project、evidence、world 开篇插件为 `OPERATIONS_SPEC`，经
  `app/assistant_operation_registry.py` 物化；world 对象、世界书页、结果、共创、复核、地图和 imports
  仍导出 `OPERATIONS`，在 `app/bootstrap.py` 直接合并。
- 后端路由约 680 个，写路由约 430 个；evolution、interaction、collaboration、account、local_agent
  没有助手操作。`available_operations` 一次返回全部操作的完整 schema。
- 费用只记计费状态（`AIChargeState`），`AgentRunBudget` 记请求、工具、网页、token 和用量是否完整，无金额。
- 没有统一操作留痕，也没有前端埋点；`local_agent` 的产品工具中继已删除（ADR-0029）。

## 关键决定与理由

- 三份草案合并为一份：目录、分级、目标运行、留痕共享同一组字段和测试，地图与势力是第一个实例。
- 界面与 AI 共用一份操作目录；剩余 `OPERATIONS` 插件先收口到注册表，未声明写路由用棘轮清单。
- R0–R4 风险分级；目标运行的计划是数据，执行由确定性引擎推进；重新规划时服务端确定性比较授权范围，
  任何扩大都停下重新审批。
- 费用只记计费状态，预算与预览用请求次数、token 和时限，不估金额。
- 留痕挂在目录层；会话 ID 加数据库单调序号，不用链表；执行事件写在保存点中，失败只标“不完整”；
  不记录内容，自由文本只记长度和加盐 hash；明细 180 天后汇总。
- 外部 Agent（MCP）接入不在本轮范围。
- 用户裁定（2026-10-15 评审后）：目标运行允许作者按目标开启 R2 自动执行，开关默认关闭；
  本机单用户默认记录界面操作，公开账户默认关闭。

## 交付

- `docs/plans/2026-10-15-agent-operation-surface.md`
- `docs/adr/0038-ai-operation-catalog-goal-runs-and-trace.md`
- `docs/adr/README.md`、`docs/README.md` 索引

## 验证

- 2026-10-15（起草）：`make docs-check BASE_REF=origin/main` 通过；`git diff --cached --check` 通过。
- 2026-10-15（评审核对与合并后，未提交）：`make docs-check BASE_REF=origin/main` 通过（49 个 ADR 文件）；
  `git diff --cached --check` 通过；旧文件名残留扫描为零。

- 2026-10-15（写入两项裁定后）：`make docs-check BASE_REF=origin/main` 与 `git diff --cached --check` 通过。

## 风险与待决

- 无待用户裁定项。实施前需技术评审转 Accepted；若其他分支先合入同号 ADR，顺延编号并同步引用。
