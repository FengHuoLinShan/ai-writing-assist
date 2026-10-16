---
id: T-20261016-map-series-claude-review
title: 地图增强系列实现的独立 review（分批）
status: active
created: 2026-10-16T21:30:00+08:00
updated: 2026-10-16T22:40:00+08:00
---

# 地图增强系列实现的独立 review（分批）

## 恢复快照

- 实际完成：第 1 批（M0 空间模型 v2 与项目词表），报告见 [BATCH-1.md](BATCH-1.md)；第 2 批（M1 演化
  可选步骤与空间发现），报告见 [BATCH-2.md](BATCH-2.md)；第 3 批（M2 自动草图与地图编辑），报告见
  [BATCH-3.md](BATCH-3.md)；第 4 批（M3/M4 空间简报、提醒、声明与 Evidence 编译），报告见
  [BATCH-4.md](BATCH-4.md)。能复现的问题都有 strict xfail 回归测试。
- 当前里程碑：第 5 批地图前端。
- 下一步：在 `frontend-console/vue/` 下找地图相关视图与组件（地图册、自动草图托盘、空间线索审核、
  冷启动引导、简报/提醒展示），对照 `docs/modules/15_map.md` 核对首次进入、空态、失败/冲突、保存反馈、
  误操作保护与作者语言；顺带核对第 2 批转来的两点：补扫运行期间是否禁用 append、英文
  `ValidationError` 是否直接显示给作者。前端回归测试按 `frontend-console/tests/vue/` 既有写法补。
- 阻塞：无。
- 工作区：`.worktrees/map-series-claude-review`，分支 `codex/map-series-claude-review`，基于
  `codex/map-enhancement-plan` @ `a479e006b`；只有本任务记录与回归测试的本地提交。
- 最后核实：2026-10-16T22:40:00+08:00。

## 目标与验收

- 目标与交付物：按用户要求 review 地图增强系列计划的实现，并按 Claude 限额分批进行；每批产出
  报告（结论、证据、分级发现、待核疑点）。用户追加要求：发现的问题要记录好；合适时写断言或测试，
  防止类似问题。
- 完成条件：9 个批次都有报告；发现给出位置、场景和证据，能复现的写成 strict xfail 回归测试；
  最后汇总。
- 非目标：修复生产代码、推送、开 PR、合入、部署；真实模型、真实稿件或作者验收。

## 上下文与边界

- 关键路径与来源：`docs/plans/2026-10-15-map-system-enhancement.md`、ADR-0035/0036/0037/0038 §10、
  `.agent/tasks/2026/T-20261015-map-enhancement-design/TASK.md`、
  `.agent/tasks/2026/T-20261016-worktree-checkpoints/{REVIEW.md,INTEGRATION-REVIEW.md}`。
- 硬约束与授权范围：只做 review，不改生产代码。集成分支 `codex/map-enhancement-plan` 未推送，含 374 个
  提交，推送 review 分支会把它们带上远端，所以不推送。不碰封存的 R3–R6 评测、holdout、能力门禁和
  真实/评测数据库。不委派子代理（用户未要求）。
- 回归测试约定：每个确认的问题写一条 `pytest.mark.xfail(strict=True, reason="<编号>: …")`，按规格
  写正确行为；修复后意外通过会让测试失败，提醒移除标记。文件为
  `backend/modules/{world,evolution}/tests/test_map_series_review_regressions.py`，后续批次按模块追加。
- 依赖：无。
- 已确认事实：规模为 374 个提交、805 个文件、约 17.6 万行；前次 Codex 集成审查完整 CI 绿
  （后端 9108 passed / 2 skipped，覆盖率 85.00%）。
- 假设与待决问题：Q2 已在第 3 批确认为 B3-F6；第 2、3 批遗留观察见 BATCH-2.md、BATCH-3.md 的
  “疑点”小节。

## 里程碑与进度

- [x] 1. M0：空间模型 v2、几何指纹、项目词表、migration、助手词表操作。
- [x] 2. M1：`evolution/spatial.py`、`spatial_rescan.py`、可选步骤 registry/workflow/quota、
  `world/map_spatial_clue_service.py`/schemas。
- [x] 3. M2：`map_auto_draft_service.py`、`map_node_merge.py`、`assistant_map_tools.py`、
  `map_progression_state`、map_cold_start 引导流程。
- [x] 4. M3/M4：`map_spatial_brief_service.py`、`map_spatial_advisory_service.py`、
  `map_declaration_state.py`、`evidence/compilation` 改动、writing/world notice_sources、ask_world；
  另含 evolution 的 `reading_notice_sources.py`。
- [ ] 5. 地图前端。
- [ ] 6. 档案：`dossier_service.py`、`dossier_interchange.py`、evidence 档案简报、`assistant_dossier_tools.py`；
  另含 evolution 的 `evidence_read.py`、`completed_read_chapters.py`。
- [ ] 7. Story：director_*、world_progression_*、continuity、character_arcs、simulation。
- [ ] 8. Assistant：goal_runs、operation_trace*、notice_service、operations.py、guided_flow。
- [ ] 9. 评测驱动 `backend/evals`、`evolution/map_evaluation_read_service.py` 与其余前端。

## 决策、发现与失败

- 2026-10-16：第 1 批发现 F1（P2，作者合并类型后地图计算退化）、F2（P3，助手与服务端去重口径不一致），
  详见 BATCH-1.md。
- 2026-10-16：第 2 批发现 B2-F1（P2，Scene 卡片编辑使可选阶段永久 running）、B2-F4（P2，超出上下文的
  涌现中类型使整条线索被拒）、B2-F5（P2，先采用地点再采用线索被打回且不可恢复）、B2-F6（P2，补扫
  重复计划已补扫的 Scene）、B2-F2（P3，密度预检单字词几乎总命中）、B2-F3（P3，复核上下文缺当前证据
  下标）。Q1 关闭。详见 BATCH-2.md。
- 2026-10-16：按用户追加要求，把确认的问题写成 strict xfail 回归测试，不改生产代码；仓库已有
  xfail 目标形态先例（`test_p2c_revision_adoption.py`），无禁止 xfail 的门禁。
- 2026-10-16：第 3 批发现 B3-F1（P2，被拒线索回到托盘）、B3-F2（P2，草图挂到同地点的规划节点并改写
  层级）、B3-F4（P2，带时效的关系把两端地点移出布局）、B3-F6（P2，Q2 确认：只有作者安排的行程进入
  读者预览）、B3-F3（P3，拒绝一条线索冻结整个批次）、B3-F5（P3，v1 旧地图上助手结构编辑失败）。
  Q2 关闭。详见 BATCH-3.md。
- 2026-10-16：第 4 批确认“节点合并后 Context 排除”边界成立。发现 B4-F1（P2，途经点为文字标签时提醒
  误报通路未连通）、B4-F2（P3，被重算取代的 drained 运行持续提醒“上次阅读已暂停”）、B4-F3（P3，问世界
  打开地图引用不带原排除项；修复需新增引用字段，未写测试）。详见 BATCH-4.md。

## 验证证据

- F1 临时复现：`make test TESTS=modules/world/tests/test_tmp_claude_review_f1.py`，合并前
  `['direction_conflict']`，合并后 `['spatial_type_not_computable', 'spatial_type_not_computable']`；
  临时文件已删除，现由回归测试覆盖。2026-10-16，基线 `a479e006b`。
- 回归测试（2026-10-16，基线 `a479e006b`，在 `backend/` 下运行）：
  `uv run --locked --extra ci -- pytest modules/evolution/tests/test_map_series_review_regressions.py modules/world/tests/test_map_series_review_regressions.py --timeout=120 -q -p no:cacheprovider`
  结果 `8 xfailed`；加 `--runxfail` 结果 `8 failed`，各条都失败在对应断言（如 B2-F2 计数为 2、
  B2-F5 状态为 `pending_verification`、B2-F6 未抛 ConflictError）。ruff format/check 通过。
- 第 3 批后（2026-10-16，同一基线与命令）：`14 xfailed`；`--runxfail` 为 `14 failed`，新增 6 条各自失败在
  对应位置（见 BATCH-3.md“回归测试”）。ruff format/check 通过。
- 第 4 批后（2026-10-16，同一基线与命令）：`16 xfailed`；`--runxfail` 为 `16 failed`，B4-F1 失败在
  `route_no_active_connection` 断言，B4-F2 失败在 `reading-original` 提醒断言。B4-F1 另有去掉途经点的
  临时对照测试通过（已删除）。ruff format/check 通过。

## 交付结果

- 已交付：第 1–4 批报告；16 条 strict xfail 回归测试。
- 未交付：第 5–9 批。
- 交付边界：只有本地提交；未推送，无 PR、CI、部署。
- 正式知识与后续任务：无。
