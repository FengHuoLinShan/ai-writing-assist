---
id: T-20261016-map-series-claude-review
title: 地图增强系列实现的独立 review（分批）
status: active
created: 2026-10-16T21:30:00+08:00
updated: 2026-10-17T08:50:00+08:00
---

# 地图增强系列实现的独立 review（分批）

## 恢复快照

- 实际完成：第 1 批（M0 空间模型 v2 与项目词表），报告见 [BATCH-1.md](BATCH-1.md)；第 2 批（M1 演化
  可选步骤与空间发现），报告见 [BATCH-2.md](BATCH-2.md)；第 3 批（M2 自动草图与地图编辑），报告见
  [BATCH-3.md](BATCH-3.md)；第 4 批（M3/M4 空间简报、提醒、声明与 Evidence 编译），报告见
  [BATCH-4.md](BATCH-4.md)；第 5 批（地图前端），报告见 [BATCH-5.md](BATCH-5.md)；第 6 批（对象档案），
  报告见 [BATCH-6.md](BATCH-6.md)；第 7 批（Story），报告见 [BATCH-7.md](BATCH-7.md)；第 8 批（Assistant），
  报告见 [BATCH-8.md](BATCH-8.md)；第 9 批（评测驱动与前端抽查），报告见 [BATCH-9.md](BATCH-9.md)。
  最终汇总见 [SUMMARY.md](SUMMARY.md)。能复现的问题都有回归测试：后端 strict xfail，前端 vitest `it.fails`。
- 当前里程碑：第 10 批（补充）——SUMMARY.md“未审范围”里的前端与后端剩余项。
- 下一步：按 SUMMARY.md“未审范围”的顺序，先审 `ObjectDossierPanel.vue` 与 `InteractionAuthorPanel.vue`
  的确认、采用与防重复，再看 `SceneDirectorPanel.vue` 其余部分；有新发现时同步更新 SUMMARY.md 的计数与清单。
- 阻塞：无。
- 工作区：`.worktrees/map-series-claude-review`，分支 `codex/map-series-claude-review`，基于
  `codex/map-enhancement-plan` @ `a479e006b`；只有本任务记录与回归测试的本地提交。前端依赖已在工作树内
  按 lock `npm ci`（node_modules 被 git 忽略），前端测试用 `npm --prefix ../frontend-console run test`。
- 最后核实：2026-10-17T08:50:00+08:00。

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
  `backend/modules/{world,evolution,story,assistant}/tests/test_map_series_review_regressions.py`，后续批次按模块追加。
  前端用 vitest `it.fails`，名称以编号开头，追加到对应组件的既有测试文件以复用 fixture。
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
- [x] 5. 地图前端。
- [x] 6. 档案：`dossier_service.py`、`dossier_interchange.py`、evidence 档案简报、`assistant_dossier_tools.py`；
  另含 evolution 的 `evidence_read.py`、`completed_read_chapters.py`。
- [x] 7. Story：director_*、world_progression_*、continuity、character_arcs、simulation。
- [x] 8. Assistant：goal_runs、operation_trace*、notice_service、operations.py、guided_flow。
- [x] 9. 评测驱动 `backend/evals`、`evolution/map_evaluation_read_service.py` 与其余前端（抽查）；最终汇总。
- [ ] 10. 补充（用户要求继续到额度用尽）：SUMMARY.md“未审范围”的剩余前端与后端。

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
- 2026-10-16：第 5 批发现 B5-F2（P2，地图引导绕过 ReadingFlow 的 `canStart`，运行未结束时准备从第 1 章
  重读的 bootstrap）、B5-F1（P3，空间补扫运行中仍可追加阅读，第 2 批疑点 2 成立）、B5-F3（P3，未开空间
  发现的旧阅读，引导默认选项必被后端拒绝）、B5-F4（P3，非主空间的选中图元重开后丢失）。疑点 1 关闭。
  前端回归测试用 vitest `it.fails`（语义同 strict xfail），追加到对应组件的既有测试文件。详见 BATCH-5.md。
- 2026-10-16：第 6 批发现 B6-F1（P2，实体接口改概要/公开信息/隐藏真相不同步档案，回填条目保留旧值）、
  B6-F2（P2，回填条目的面向键不在 `CORE_FACINGS`，无法编辑、清除、恢复或导入）、B6-F3（P2，较早截止点
  的人物倾向读取绕过作者后来的拒绝/更正）。详见 BATCH-6.md。
- 2026-10-16：第 7 批发现 B7-F1（P2，按预览最大值授权时导演在最后一回合中途暂停，且暂停后无续演入口）、
  B7-F2（P3，意图校验接受收听者而结算在无位置资料时抛错，已计费回合确定性失败）、B7-F3（P3，世界推进
  不按资料确认收窄对象档案）、B7-F4（P3，章节重排后受影响 Scene 的事实永久“待重验”）。B7-F3 依赖
  非默认开关且修法未定，B7-F4 与现有测试断言冲突需先定口径，均未写测试。详见 BATCH-7.md。
- 2026-10-17：第 8 批发现 B8-F1（P3，目标规划器看到两个必然失败的地图操作：地图作者决定排除按
  `world.map.` 前缀判断而操作实际为 `map.*`，结构编辑必在准备时失败；托盘入口被 `validate_plan` 拒绝，
  规划请求已计费）。其他地图写入是否应排除出目标运行口径未定，记为观察。详见 BATCH-8.md。
- 2026-10-17：第 9 批发现 B9-F1（P3，目标运行面板把所有 409 换成“目标状态已更新”，丢掉服务端原因；启动被
  明确拒绝后表单锁定）。评测守卫与三个评测只读服务无问题；地图评测裁判固定用 Sol，与 2026-10-16 的评测
  分工冲突，记为观察待用户决定。详见 BATCH-9.md。最终汇总：30 个发现（P2、P3 各 15），无 P0/P1，
  见 SUMMARY.md。

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
- 第 5 批后（2026-10-16，同一基线）：`npm --prefix ../frontend-console run test` 结果 257 个文件通过，
  3234 passed、5 expected fail；去掉 `.fails` 的临时副本各自失败在目标断言（B5-F1 按钮可用、B5-F2
  `mode: bootstrap`、B5-F3 `mode: append` 且开空间发现、B5-F4 选中列表为空），B5-F4 另有主空间对照通过；
  临时文件已删除。`npm --prefix ../frontend-console run lint` 通过。后端回归文件未改动。
- 第 6 批后（2026-10-16，基线 `a479e006b`，同一后端命令）：`20 xfailed`；`--runxfail` 为 `20 failed`，B6-F1
  失败在档案仍为旧值，B6-F2 两条分别返回 400“该对象类型不支持此内核面向”和“清单中的内核面向已失效”，
  B6-F3 返回修订 1。ruff format/check 通过。
- 第 7 批后（2026-10-16，基线 `a479e006b`，命令加上 `modules/story/tests/test_map_series_review_regressions.py`）：
  `22 xfailed`；Story 文件 `--runxfail` 为 `2 failed`，B7-F1 返回 `paused_budget`（`request_budget_80_percent`，
  完成 1 回合），B7-F2 失败在 `simulation_v3.py:259` 的 ValueError。ruff format/check 通过。
- 第 8 批后（2026-10-17，基线 `a479e006b`）：新文件 `modules/assistant/tests/test_map_series_review_regressions.py`
  为 `2 xfailed`；`--runxfail` 为 `2 failed`，分别失败在 `map.edit_spatial_structure` 仍在可用列表和
  `{'map.prepare_tray_placement': '目录只读操作不能声明写入回调'}`。临时探针确认 11 个地图操作全部提供给
  规划器（已删除）。ruff format/check 通过。
- 第 9 批后（2026-10-17，基线 `a479e006b`）：四个后端回归文件 `24 xfailed`；前端全量
  `npm --prefix ../frontend-console run test` 为 `3234 passed | 6 expected fail`，lint 通过；B9-F1 临时去掉
  `.fails` 后失败在“错误区不含‘模型连接不可用’”，已改回。

## 交付结果

- 已交付：第 1–9 批报告与 SUMMARY.md；24 条后端 strict xfail 与 6 条前端 `it.fails` 回归测试。
- 未交付：第 10 批补充（可选，覆盖 SUMMARY.md 的未审范围）。
- 交付边界：只有本地提交；未推送，无 PR、CI、部署。
- 正式知识与后续任务：无。
