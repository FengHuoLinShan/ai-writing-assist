---
id: T-20261016-map-series-claude-review
title: 地图增强系列实现的独立 review（分批）
status: active
created: 2026-10-16T21:30:00+08:00
updated: 2026-10-16T21:30:00+08:00
---

# 地图增强系列实现的独立 review（分批）

## 恢复快照

- 实际完成：第 1 批（M0 空间模型 v2 与项目词表），报告见 [BATCH-1.md](BATCH-1.md)。
- 当前里程碑：第 2 批 M1 演化空间发现。
- 下一步：读 ADR-0036，再审 `backend/modules/evolution/spatial.py`、`spatial_rescan.py`、可选步骤
  registry/workflow/quota、`backend/modules/world/map_spatial_clue_service.py` 与 schemas，带上 Q1。
- 阻塞：无。
- 工作区：`.worktrees/map-series-claude-review`，分支 `codex/map-series-claude-review`，基于
  `codex/map-enhancement-plan` @ `a479e006b`；只有本任务记录的本地提交。
- 最后核实：2026-10-16T21:30:00+08:00。

## 目标与验收

- 目标与交付物：按用户要求 review 地图增强系列计划的实现，并按 Claude 限额分批进行；每批产出
  报告（结论、证据、分级发现、待核疑点）。
- 完成条件：9 个批次都有报告；发现给出位置、场景和证据，能复现的做最小复现；最后汇总。
- 非目标：修复发现、推送、开 PR、合入、部署；真实模型、真实稿件或作者验收。

## 上下文与边界

- 关键路径与来源：`docs/plans/2026-10-15-map-system-enhancement.md`、ADR-0035/0036/0037/0038 §10、
  `.agent/tasks/2026/T-20261015-map-enhancement-design/TASK.md`、
  `.agent/tasks/2026/T-20261016-worktree-checkpoints/{REVIEW.md,INTEGRATION-REVIEW.md}`。
- 硬约束与授权范围：只做 review，不扩大成修复。集成分支 `codex/map-enhancement-plan` 未推送，含 374 个
  提交，推送 review 分支会把它们带上远端，所以不推送。不碰封存的 R3–R6 评测、holdout、能力门禁和
  真实/评测数据库。不委派子代理（用户未要求）。复现测试只在本工作树临时创建，跑完删除。
- 依赖：无。
- 已确认事实：规模为 374 个提交、805 个文件、约 17.6 万行；前次 Codex 集成审查完整 CI 绿
  （后端 9108 passed / 2 skipped，覆盖率 85.00%）。
- 假设与待决问题：Q1、Q2 见 BATCH-1.md。

## 里程碑与进度

- [x] 1. M0：空间模型 v2、几何指纹、项目词表、migration、助手词表操作。
- [ ] 2. M1：`evolution/spatial.py`、`spatial_rescan.py`、可选步骤 registry/workflow/quota、
  `world/map_spatial_clue_service.py`/schemas。
- [ ] 3. M2：`map_auto_draft_service.py`、`map_node_merge.py`、`assistant_map_tools.py`、
  `map_progression_state`、map_cold_start 引导流程。
- [ ] 4. M3/M4：`map_spatial_brief_service.py`、`map_spatial_advisory_service.py`、
  `map_declaration_state.py`、`evidence/compilation` 改动、writing/world notice_sources、ask_world。
- [ ] 5. 地图前端。
- [ ] 6. 档案：`dossier_service.py`、`dossier_interchange.py`、evidence 档案简报、`assistant_dossier_tools.py`。
- [ ] 7. Story：director_*、world_progression_*、continuity、character_arcs、simulation。
- [ ] 8. Assistant：goal_runs、operation_trace*、notice_service、operations.py、guided_flow。
- [ ] 9. 评测驱动 `backend/evals` 与其余前端。

## 决策、发现与失败

- 2026-10-16：第 1 批发现 F1（P2，作者合并类型后地图计算退化，已复现）、F2（P3，助手与服务端去重口径
  不一致），详见 BATCH-1.md。

## 验证证据

- F1 临时复现：`make test TESTS=modules/world/tests/test_tmp_claude_review_f1.py`，合并前
  `['direction_conflict']`，合并后 `['spatial_type_not_computable', 'spatial_type_not_computable']`；
  测试文件已删除，未提交。2026-10-16，基线 `a479e006b`。

## 交付结果

- 已交付：第 1 批报告。
- 未交付：第 2–9 批。
- 交付边界：只有本地提交；未推送，无 PR、CI、部署。
- 正式知识与后续任务：无。
