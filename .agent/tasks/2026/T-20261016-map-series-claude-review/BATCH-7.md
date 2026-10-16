# 第 7 批：Story（导演、世界推进、连续性、人物弧、模拟）

审查基线：`codex/map-enhancement-plan` @ `a479e006b`（merge-base `00d861283` = origin/main）。
规格：`backend/modules/story/README.md`、ADR-0039 §6（场景导演）、ADR-0041（世界推进）、
`docs/modules/19_story.md`、`docs/modules/05_memory.md`、`docs/01_数据库设计.md` 的章节重排回执一节，
以及 AGENTS.md 的确认与排除资产约束。

## 结论

Story 新增面的写入门禁整体扎实：钩子采用、持续授权、章节重排、人物弧和助手生成工具都做到预览指纹、
应用时重验、排他锁或 CAS，以及 operation_id 防重，候选不会自动采用。问题集中在导演的预算与结算
口径：按预览最大值授权时，最后一回合会在中途暂停，且暂停后没有续演入口（P2）；意图校验与结算对
收听者的判断不一致，在没有位置资料的 Scene 里会让已计费的回合确定性失败（P3）。另有世界推进不按
资料确认收窄对象档案（P3），以及事实时间线在章节重排后永久显示“待重验”（P3）。前两条有 strict xfail
回归测试。

## 已审范围

- 导演：`director_api.py`（启动、续演、预算续算、`/advance`）、`director_tasks.py`（`_run_one_round`、
  暂停与失败处理、检查点）、`director_budget.py`、`director_consistency.py`、`director_context.py`、
  `director_state.py`、`director_candidate_transfer.py`；前端 `SceneDirectorPanel.vue` 的暂停提示。
- 模拟：`simulation_v3.py` 全文，对照基线 `observations.py`。
- 世界推进：`world_progression_hooks_api.py`、`world_progression_continuous.py`、
  `world_progression_operations.py`、`world_progression_context.py`、`world_progression_tasks.py`
  的确认与授权重验。
- 连续性：`continuity/chapter_order.py`（应用、恢复、派生失效、待重验计划）、`fact_timeline.py`。
- 人物弧：`character_arcs/service.py`。
- 助手操作：`assistant_generation_tools.py`、`assistant_scene_operations.py`、
  `assistant_state_operations.py`。
- 未逐行审：`director_service.py`、`forecast.py`、`rehearsals.py`、`simulation.py`、
  `character_arcs/operations.py`、`continuity/field_provenance.py` 与 `scene_projection.py`。

## 确认无问题

- 钩子采用：钩子 id 绑定步骤的 output_hash；已删除分支不能采用；预览 hash 含来源指纹与确认。采用时
  先预览，再取项目排他锁和 `require_fresh_confirmation(for_update)`，重新预览并比对指纹；
  `attach_result_ref` 与 `mark_asset_context_changed` 在 `begin_nested` 中执行。
- 持续授权：按整章计数并排除已计入章节；章节重排的应用和恢复都会撤销授权
  （`writing/draft_service.py` 调用 `_invalidate_standing_authorization`）；执行时重验授权修订号与
  参与者；GET 不触发任务。
- 推进操作：R1 要求普通作者回合、同一 Scene、同一份确认；钩子预览与采用要求项目级工作范围。
- 导演预算续算：未知用量需要 `allow_possible_duplicate_charge`；只追加 Token 走正常授权；不追加额度
  且单轮时 `/branches` 返回 400，改走 `/advance`。
- 导演资料：确认范围哈希正确，按确认范围收窄（`scope_director_source` → `restrict_object_dossier_brief`）。
- 导演候选转入：World 相似对象返回 409，阻止重复建实体。
- 章节重排：应用校验指纹和 blocker；恢复要求 after_fingerprint 未变并带 receipt 防重；链接表经负数
  中转避免唯一约束冲突；计划锚点在作者改动后不再列为待重验。
- 人物弧：`expected_version` CAS、operation_id 加 request_hash 幂等、owner 校验、归档与恢复。
- 助手生成工具：重验确认的 Scene、人物与 POV；有排除项时必须沿用原确认；只在 `inline_only` 父任务
  预算内入队。
- 助手 Scene 与状态操作：应用时先锁行再重新预览比对；重排要求覆盖全部有效 Scene；预览与仓储都用
  0 起的 `scene_index`。状态确认经 World 校验模板版本或地图声明身份。

## 发现

### B7-F1（P2）按预览最大值授权时，导演在最后一回合中途暂停；暂停后没有续演入口

- 位置：`director_tasks.py` 的 `_run_one_round`（第 801 行起）在每个 provider 请求前调用
  `budget_stop_reason`（第 901、1014、1092、1198 行）；`director_budget.py` 第 132 行判断
  `requests_started / request_limit >= 0.8`。`preview_director_budget`（第 22–24 行）给出的最大值是
  `(2n+2) × 回合数`，而每回合实际请求正好是 2n+2（意图 n、裁决 1、表演卡 n、素材 1；
  `max_fix_attempts=0`，不重试）。
- 规格：README 第 489–491 行写明，导演在最后一个已选回合完整落盘后，即使达到 80% 预算线仍返回完成；
  尚有已选回合未完成时才暂停。
- 问题：作者按预览最大值授权时，80% 线落在最后一回合内部。1 个人物 2 回合时上限为 8，第 8 次请求前
  7/8 ≥ 0.8，暂停；2 个人物 1 回合时上限为 6，第 6 次请求前 5/6 ≥ 0.8，暂停。只有授权约为最大值的
  1.25 倍以上，最后一回合才能跑完。
- 续演断路：`continue_director_root`（`director_api.py` 第 327 行起）总是新建分支，并把
  `pending_round_json` 置为 `{}`（第 450 行）；`DirectorContinueRequest.parent_round_id` 为必填
  （`director_schemas.py` 第 107 行）。因此暂停回合里已计费的意图与裁决会被丢弃；首回合就暂停时没有
  已完成回合，根本无法续演。前端（`SceneDirectorPanel.vue:90`）却提示“请查看累计账本，再明确追加
  额度后继续”。`pending_round_json` 只在同一任务重跑时复用。
- 复现：`modules/story/tests/test_map_series_review_regressions.py` 的
  `test_b7_director_last_round_completes_within_previewed_maximum`（离线工作流，合成 provider），去掉
  xfail 后返回 `{'status': 'paused_budget', 'completed_rounds': 1, 'budget_stop':
  'request_budget_80_percent', ...}`。现有 `test_director_failure_keeps_checkpoint_and_stops_requests`
  只断言会暂停，从未测试续演。
- 建议方向：80% 判断只用于“是否开始下一回合”，回合内部只按硬上限停止；或把预览最大值作为必须完成
  的额度，80% 线只决定是否提醒。另需给暂停的回合（含首回合）提供追加额度后在原分支续跑的入口，
  复用 `pending_round_json` 中已计费的结果。

### B7-F2（P3）意图校验接受收听者，结算却在没有位置资料时抛错，已计费回合确定性失败

- 位置：`director_consistency.py` 的 `validate_intents`（第 53–88 行）只检查收听者是否在该人物已知范围
  内（`known_participant_ids` 来自 continuity 中的 `knows:<id>` 与观察到的事件）。
  `simulation_v3.py` 的 `_observers_for`（第 246–264 行）要求说话人与收听者位置都已知且相同，否则抛出
  `ValueError("Observation recipients must belong to this scene")`；它对每条意图无条件调用
  （第 336 行），与裁决结果无关。位置只来自精确的 continuity 位置事实（`director_state.py`）。
- 问题：人物 A 已知 B、但 Scene 没有两人的位置资料时，A 对 B 说话或私语的意图能通过校验
  （`director_tasks.py` 第 1003 行），在第 n+1 次（裁决）请求计费后，结算（第 1070 行）抛错。异常落到
  第 465 行的通用分支，分支和根都标为 failed；`pending` 已缓存裁决结果，重跑会确定性地再次失败。
  基线 `observations.py` 在位置未知时视为同处一地，v3 收紧为“位置已知且相同”是有意设计
  （`test_public_event_requires_known_shared_location_for_other_observers`），但校验端没有同步收紧。
  README 对移动的口径是“资料缺失时结算为 uncertain”，而这里是直接失败。
- 复现：同文件 `test_b7_intent_audience_accepted_by_validation_settles_without_positions`。测试与修法
  无关：校验拒绝（在计费前）或结算成功都算通过，只有“通过校验后抛错”失败。去掉 xfail 后失败在
  `simulation_v3.py:259` 的 ValueError。
- 建议方向：要么在 `validate_intents` 里用同一份位置状态判断收听者（在裁决前拒绝并提示作者补位置），
  要么让结算把超出可观察范围的收听者降为“未送达”或 uncertain，而不是抛错。

### B7-F3（P3，不写测试）世界推进不按资料确认收窄对象档案

- 位置：`world_progression_context.py` 的 `read_progression_source`（第 253 行起）直接读
  `read_object_dossier_brief`（第 353、396 行，作者全量与逐角色视角），从不与 `confirmed.compiled`
  求交集；导演则会求交集（`director_context.py` 第 369–377 行）。`handle_world_progression` 只用这份
  确认核对 Scene 与人物范围（`world_progression_tasks.py` 第 272 行），持续授权路径甚至跳过
  `prepare_confirmed_ai_action`。
- 问题：给 `story.one_click` 开启对象档案维度（`object_dossier_enabled_capabilities`，默认关闭）后，
  作者在资料确认弹窗里排除的档案条目仍会进入角色包，违反 AGENTS.md“不带回排除资产”。默认配置下
  确认弹窗根本没有档案条目，但角色包含有档案内容，作者看不到它们被使用。ADR-0041 §3 把对象档案
  列为推进背景，所以读取本身是允许的，问题在于不受确认约束。
- 不写测试的理由：复现需要非默认开关和完整的编译、确认链路；修法方向（按确认收窄，或把档案列为
  确认之外的独立背景并向作者显示）还没定。

### B7-F4（P3，不写测试）章节重排后，受影响 Scene 的事实在时间线上永久显示“待重验”

- 位置：`continuity/fact_timeline.py` 第 86–91 行把所有 `status == "applied"` 回执的
  `affected_scene_ids` 都视为待重验；`_event_status`（第 348–353 行）据此把这些 Scene 的事件标为
  `stale`，`status=current` 筛选（第 323–331 行）会排除它们。回执状态只有 `applied` 与 `restored`
  （`continuity/models.py` 第 151 行）。
- 问题：除了恢复重排，没有任何操作能清除这个状态。重排之后在同一 Scene 新记录或重提取的事件，也因
  Scene 身份相同而永远是“待重验”；作者重排 Scene、修订 checkpoint 都不影响。相比之下，计划锚点的
  待重验在作者改过锚点后就不再列出（`chapter_order.py` 的 `list_pending_plan_reviews`）。助手的
  `story.fact_timeline.read` 读到的也是同样的状态。
- 不写测试的理由：现有 `test_fact_timeline_projects_current_chapter_without_mutating_history` 明确
  断言重排后创建的事件同样为 `stale`，修复要先定“何时算已重验”（例如事件绑定时间晚于回执、
  对应 checkpoint 已重验），写 xfail 会直接与现有断言冲突。

## 观察（未定为问题）

- 预算预览的最小值 `4 × 回合数` 偏低：人物数 n≥2 且无人离场时，实际请求总是 2n+2。
- 没有位置资料时，导演回合里人物看不到彼此的公开行动（`_observers_for` 只把说话人自己列为观察者）。
  这是 v3 的有意收紧，但对导演的价值影响大，建议在导演面板提示“补充位置后人物才能互相观察”。
- 钩子采用的 operation_id 防重在 Python 中遍历全部 PlotThread、OutlineArc 和 Scene 的 provenance，
  长篇项目上较慢。
- 持续授权：删除第 N 章后重建同序号章节，新章读完不计数；重排撤销授权时没有更新 `updated_at`。
- `fact_timeline` 的条目仍返回 `scene_id`、`entity_id` 等原始字段（只有快照做了作者化处理），依赖前端
  不直接展示。

## 回归测试

- 新文件 `backend/modules/story/tests/test_map_series_review_regressions.py`，复用
  `test_director_offline_workflow.py` 的 `director_workflow` fixture（回滚数据库、合成 provider）。
  - B7-F1：`test_b7_director_last_round_completes_within_previewed_maximum`，2 回合，按预览最大值 8 授权，
    断言状态为 complete 且完成 2 回合。
  - B7-F2：`test_b7_intent_audience_accepted_by_validation_settles_without_positions`，纯函数，状态由
    `SimulationV3Context(...).initial_state()` 构造，观察者与导演的调用方式一致。
- 验证（2026-10-16，基线 `a479e006b`，在 `backend/` 下运行）：
  `uv run --locked --extra ci -- pytest modules/story/tests/test_map_series_review_regressions.py modules/evolution/tests/test_map_series_review_regressions.py modules/world/tests/test_map_series_review_regressions.py --timeout=120 -q -p no:cacheprovider`
  结果 `22 xfailed`；Story 文件加 `--runxfail` 为 `2 failed`，分别失败在 `paused_budget` 断言与
  `simulation_v3.py:259` 的 ValueError。ruff format/check 通过。
