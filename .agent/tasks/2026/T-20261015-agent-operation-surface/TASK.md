---
id: T-20261015-agent-operation-surface
title: 全模块 AI 操作入口、目标运行与操作留痕设计
status: active
created: 2026-10-15T14:30:00+08:00
updated: 2026-10-15T22:30:37+08:00
---

# 全模块 AI 操作入口、目标运行与操作留痕设计

## 恢复快照

设计稿与 ADR（Proposed）已于 2026-10-15 经用户授权本地提交 `87e56f241`，未推送。之后按用户要求核对
33 条外部评审并合并 ADR：原 ADR-0038（助手地图与势力操作）、0039（操作目录与目标运行）、0040（操作留痕）
合并为新 ADR-0038 `docs/adr/0038-ai-operation-catalog-goal-runs-and-trace.md`。用户随后裁定两项默认值
（见“关键决定”），修正与裁定经用户授权在第二个本地提交中提交，未推送。
与地图增强设计（T-20261015-map-enhancement-design）同在工作树 `.worktrees/map-enhancement-plan`、分支
`codex/map-enhancement-plan`（基于 main `d2ab2dbf3`；最后核对时 origin/main 为 `00d861283`）。
2026-10-15 技术评审后按推荐修订 ADR-0038：目录项事务形态、目标运行 `goal` 模式与每项目唯一索引、
高频操作留痕合并或豁免。修订经用户授权在第三个本地提交 `20d6f1eff` 中提交，未推送。
2026-10-15 用户采纳 ADR-0038（Accepted / 未实施）；ADR-0023 补充说明与索引同步。
用户现明确授权三份计划全部实施；本任务进入A0–A4分批实现。主树HEAD ba20dc79388133ee903e5522e9cf30ceae2905ba暂为地图真实评测固定版本，代码先在隔离树 /Users/tywww/项目/ai-writing-assist/.worktrees/map-operation-catalog-impl（codex/map-operation-catalog-impl，同base）实现。Luna/max负责A0，之后Sol/high review并直接修复；root负责集成验证，TASK唯一写入。当前下一步：完成六legacy插件纯SPEC收口、目录v2、find/describe、写路由绑定棘轮、隐私trace生命周期闭环；A1/A2/A3依批次继续。A4报表可以实现，基于数周真实数据选前三模式不能虚构。

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
- 技术评审（2026-10-15，用户同意按推荐处理）：
  - 事务形态：助手用 `begin_nested()` + `flush()`（`assistant/operations.py:502`），请求结束统一提交
    （`core/database.py:148`）；但 `world/map_atlas_service.py`、`world/entity_fusion.py` 内部多处提交，
    ADR-0013 只覆盖长任务。所以目录项声明单事务或多阶段，多阶段按领域回执对账，结果未知时停下。
  - 目标运行存储：`assistant_runs.mode` 只有 `author`/`background`，活动唯一性按 `session_id`
    （`uq_assistant_session_active`）。新增 `goal` 模式、不绑定会话、停点用 `waiting_approval`、
    按项目的部分唯一索引。
  - 高频写入（`writing/api.py:395` autosave）按会话加时间窗合并或豁免留痕。

## 交付

- `docs/plans/2026-10-15-agent-operation-surface.md`
- `docs/adr/0038-ai-operation-catalog-goal-runs-and-trace.md`
- `docs/adr/README.md`、`docs/README.md` 索引

## 验证

- 2026-10-15（起草）：`make docs-check BASE_REF=origin/main` 通过；`git diff --cached --check` 通过。
- 2026-10-15（评审核对与合并后，未提交）：`make docs-check BASE_REF=origin/main` 通过（49 个 ADR 文件）；
  `git diff --cached --check` 通过；旧文件名残留扫描为零。

- 2026-10-15（写入两项裁定后）：`make docs-check BASE_REF=origin/main` 与 `git diff --cached --check` 通过。
- 2026-10-15（技术评审修订后，未提交）：`make docs-check BASE_REF=origin/main` 与 `git diff --cached --check` 通过。

## 风险与待决

- 无待用户裁定项。ADR-0038 已采纳；若其他分支先合入同号 ADR，顺延编号并同步引用。

## 2026-10-15T21:56:18+08:00 实施检查点

- runtime目录已实调用register_container_services核实64项唯一操作：assistant1/evidence1/evolution2/imports5/map11/project3/story11/world21/writing9。旧55项只是snapshot初次赋值，后续update不可漏算。A0独占bootstrap/main/registry/service_keys和Assistant既有核心；档案、提醒子代理仅提供新纯SPEC与接线需求。只新migration operation_trace_v2，最终Sol统一链。
- 仅本地提交与隔离验证授权；未push/PR/main合并/部署。无新的真实模型/私有评测根/真实数据库访问授权给这些实现代理。工程检查与真实作者验收分开报告。

- 2026-10-15T22:16:25+08:00：地图R3五Scene完成后结构任务严格目标解析失败，已正常停止封存，真实质量未通过；当前无live runner，新功能首批提交审查后可集成，后续评测需新pipeline身份，不复用旧实验。

## 2026-10-15T22:30:37+08:00 首批交付与独立审修

- A0a f7ba93e8bc5e428a8aef76b6d483ef4236049220已交Sol/high sol_review_operation_catalog（map-advisory-review/codex/operation-catalog-v2-review）；干净归档29定向/Ruff/docs通过。trace与写路由A0b WIP完整保留原Luna树，尚未提交/集成，下一批继续。共享装配还需接C3a/C0新SPEC，不能把A0a当全A0。
- root主树fd372d5f2仅任务记录提交，新两批尚未集成；代码问题由Sol直接修。本地开发继续，未推送或部署。
