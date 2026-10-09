---
id: T-20261009-borrowing-plan-refinement
title: 对照项目实施交接的借鉴开发计划完善
status: completed
created: 2026-10-09T10:32:15+09:00
updated: 2026-10-09T12:50:00+09:00
---

# 对照项目实施交接的借鉴开发计划完善

## 恢复快照

- 实际完成：外部交接逐项对照当前代码核查（5 个只读调查 + 主会话复核关键证据），写成
  `docs/plans/2026-10-09-guided-flow-borrowing.md`；文档门禁通过。
- 当前里程碑：完成。§6 五项裁定已写入计划；BR-5 按“较完整的世界观骨架”、BR-6 按“正文单章、多章只到大纲级”重写，依据两份补充只读调查。
- 下一步：若用户要求实施，新建实施任务，从计划 §5 的 BR-0a/0b/0c、BR-1a、BR-2 开始（均可立即开始）；BR-3 先起草 ADR-0032。
- 阻塞：无。
- 工作区：主工作区 main = origin/main = f35c2bb0f；本任务只新增计划文件、本记录与索引行，未提交。
  既有 architecture-optimization TASK.md 修改、两个未跟踪任务目录和 `.workbuddy/` 不属本任务，未触碰。
- 最后核实：2026-10-09T12:50:00+09:00。

## 目标与验收

- 目标与交付物：把外部交接（原则级建议）落为基于当前代码事实的可执行开发计划。
- 完成条件：计划文件入 `docs/plans/`；`make docs-check`（含 BASE_REF=origin/main）与空白检查通过。
- 非目标：不实现业务代码、不建 migration、不调用付费模型、不提交/推送/开 PR。

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

## 验证证据

- `make docs-check` 与 `make docs-check BASE_REF=origin/main`：通过（2026-10-09，基线 f35c2bb0f + 未提交计划文件；裁定修订后复跑通过）。
- 新增文件无行尾空白。

## 交付结果

- 已交付：`docs/plans/2026-10-09-guided-flow-borrowing.md`。
- 未交付：任何实现。
- 交付边界：仅本地工作树，未提交、未推送、无 CI、无部署。
- 正式知识与后续任务：实施时按计划同步模块 README、`docs/modules/*` 与新 ADR（暂定 ADR-0032）。
