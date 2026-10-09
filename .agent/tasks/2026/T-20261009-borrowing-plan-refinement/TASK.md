---
id: T-20261009-borrowing-plan-refinement
title: 对照项目实施交接的借鉴开发计划完善
status: completed
created: 2026-10-09T10:32:15+09:00
updated: 2026-10-09T23:06:26+09:00
---

# 对照项目实施交接的借鉴开发计划完善

## 恢复快照

- 实际完成：原计划与已有 5 项补充再次对照基线及当前分支代码；修正跨窗全局字段、子集依赖、确认前排除、
  多证据取舍与同章联合修订、关闭自动审查后的采用门禁、请求次数及方向卡输入边界。
- 当前里程碑：计划完善与本地文档验收完成；Git 交付另以本轮 PR 的实时状态为准。
- 下一步：完成本轮 PR 固定 head 检查、合并及隔离分支清理；实施另需按当前授权核实，不能以计划完成推断实现完成。
- 阻塞：无。
- 工作区：隔离 worktree `guided-flow-plan-review/ai-writing-assist`，分支 `codex/guided-flow-plan-review`，
  从已 fetch 的 `origin/main@f35c2bb0f` 起步，仅交付计划及本记录；原工作区业务分支及 WIP 未修改。
- 最后核实：2026-10-09，当次 Git 与代码核查；精确版本随提交记录。

## 目标与验收

- 目标与交付物：把外部交接（原则级建议）落为基于当前代码事实的可执行开发计划。
- 完成条件：计划文件入 `docs/plans/`；`make docs-check`（含 BASE_REF=origin/main）与空白检查通过。
- 非目标：不实现业务代码、不建 migration、不调用付费模型；本轮用户授权提交、推送、PR 合并与本任务分支清理。

## 上下文与边界

- 来源：外部交接（仓库外 `~/Downloads/NovelCraft_implementation_handoff.md`）；上一轮借鉴
  `.zcode/reports/AI-Novel-Writer-对比与改进方案-独立设计.md`（对照的是另一个 Electron 项目）；
  本轮对照仓库 ExplosiveCoderflome/AI-Novel-Writing-Assistant@07fd243，源码只读副本在会话临时目录，不入库。
- 对照项目为自定义双许可（Biz Novel Studio License），计划限定只借鉴机制、不复制代码与提示词。

## 决策、发现与失败

- 2026-10-09；进度投影挂 project workspace-summary 而非 Assistant：Assistant 默认关闭，概览已有 DI provider 汇总机制。
- 2026-10-09；流程编排命名 `guided_flow`，避免与 collaboration `Recipe`、V4“多 Agent 配方”混淆；放 Assistant，
  只用 `scripts/check_module_imports.py` 已冻结的依赖边（Assistant 不能直连 World）。
- 2026-10-09；发现三处现有缺陷（计划 §1 第 5 点，已由主会话复核）：用量聚合把 unknown 抹成整数；知识复核单次路径
  不读 `dimensions[].checked`，与组路径不一致；生成完成即弹成功，不看复核结果。均列为 BR-0/BR-2，未修。
- 2026-10-09；用户裁定（原话）：“1:比较完整的世界观骨架。2:接受。3:同意。4:详细正文只做单章。多章提供故事线/大纲级别的候选。5:同意”。
  据此：流程 1 终点为较完整的世界观骨架；接受 guided_flow 与 ADR-0032；换设备提示后允许再生成；不做多章正文，
  多章只做大纲级候选（上一轮 C2 正文批量关闭）；生成后自动独立审查默认开、可关。按协议为同一结果的需求修正，重新打开本任务。
- 2026-10-09；`T-20260920-forecast-creative-engine` 记录仍称代码未提交，调查显示已在 main；不在本任务范围，未改。
- 2026-10-09；计划审查（用户转述）指出 5 处契约缺口，核对代码后全部成立并已补入计划：BR-6 窗口修订与 `_assign_arc`
  整体赋值冲突（首轮提议字段白名单，本轮改为跨窗只读提示）、`operation_id` 缺输入指纹（加入冻结输入指纹 + 主动重抽持久尝试标识）、
  `AdoptStructure` 只收 `task_id` 且 `_validate_preview_scope` 要求全量保序（改为子集保序 + 未选不落地）、
  BR-5 排除端点后 `_resolve_ref` 报错拖垮整包（首轮提议采用时剔除，本轮改为确认前连带排除）、BR-4 意见 1–4 条证据可跨章
  （补选区定位、跨章拆分、重叠确认与同基稿候选失效契约）。

## 验证证据

- `make docs-check` 与 `make docs-check BASE_REF=origin/main`：通过（2026-10-09，基线 f35c2bb0f + 未提交计划文件；裁定修订后复跑通过）。
- 本轮隔离基线 `origin/main@f35c2bb0f`：`make docs-check BASE_REF=origin/main` 通过；计划已纳入两轮审查修复。
- 提交前对暂存内容运行 `git diff --cached --check`，具体结果见本轮 PR。

## 交付结果

- 已交付：`docs/plans/2026-10-09-guided-flow-borrowing.md`。
- 未交付：任何实现。
- 交付边界：原轮只交付本地计划；本轮文档验收完成，用户已授权提交/推送/合并/分支清理，实际 Git 与 CI 状态以本轮 PR 为准。
  未验证业务实现、真实模型、作者体验或部署。
- 正式知识与后续任务：实施时按计划同步模块 README、`docs/modules/*` 与新 ADR（暂定 ADR-0032）。

## 本轮审查与交付（2026-10-09）

- 用户要求再审查计划并修复，提交、push、PR 合并、清理分支；沿用计划审查范围，未扩大为业务实现分支合并。
- `OutlineArc` 的目标/高潮等是整篇字段，白名单无法保护跨窗内容；跨窗只给提示，窗口细化落已有计划 Scene。
- 原有局部修订任务可处理同章多批注，采用会使同基稿候选过期；改为作者确认同章联合候选，避免批量产生互斥候选。
- World 排除依赖须在预览确认前完成；既有 UUID 端点无需包内 include；确认后变化拒绝重预览，不能静默改已确认包。
- 子集采用明确合法排除和非法缺漏，并补提案依赖确认；幂等固定原确认与尝试，防止刷新建新确认造成重复付费。
- 关闭自动审查不关闭采用门禁；方向卡仅在显式获准步骤输入，未选方向与未采用骨架不入普通检索。
- 初始 WIP 内容指纹保存于仓库外 `/tmp/guided-flow-plan-review-wip.json`，收尾核对；不清理未合入的业务分支或已有 worktree。
