# 第 8 批：Assistant

审查基线：`codex/map-enhancement-plan` @ `a479e006b`（merge-base `00d861283` = origin/main）。
规格：ADR-0038（§5 作者指令与模型推断、§6 目标运行、§10 地图与势力）、ADR-0040“统一提醒”、
ADR-0023/0027、`backend/modules/assistant/README.md`。

## 结论

目标运行的核心不变量都成立：计划校验只接受类型化引用；重规划和继续预算按确定性范围比较，
不采纳模型判断；R3 逐步确认，R4 不进入目标；R2 只在目标显式开启且有真实恢复入口时自动执行；
多阶段步骤结果未知时失败关闭，核对只认终态领域回执。统一提醒的处置 CAS、操作留痕的参数脱敏和
窄 HTTP 入口的预览—确认流程也符合规格。问题在目标规划器看到的操作目录与执行端不一致：地图操作
登记为 `map.*`，目标运行却按 `world.map.` 前缀排除地图作者决定，排除从未生效。发现 1 个 P3，
有两条 strict xfail 回归测试。

## 已审范围

- `goal_runs/`：`planning.py` 全文；`service.py` 的 `start_goal`、`_generate_plan_for_run`、
  `_goal_planning_catalog`、`_goal_operation_unavailable_reason`、`_assert_plan_operations_supported`、
  `_prepare_step`、`_resolved_target_pairs`、`_check_step_targets`、`_advance_steps_locked`、
  `_execute_single_step`、`_execute_task_step`、`_record_step_failure`、`_unknown_step_task_context`、
  `goal_step_receipt_preview`、`reconcile_goal_step`、`approve_goal_plan`、`approve_goal_step`、
  `replan_goal`、`resume_goal`、`restore_goal_changes` 与两类恢复清单；`api.py`。
- 统一提醒：`notice_service.py`、`notice_sources.py`、`notice_disposition_operations.py`、
  `map_notices.py`、`map_spatial_advisories.py`。
- 操作目录与留痕：`operations.py`（冻结目录解析、`find/describe/read_operation`）、`operation_api.py`、
  `operation_trace_service.py` 的参数摘要、引用提取与开关；`app/assistant_operation_registry.py` 的物化；
  `app/assistant_operation_metadata.py` 的地图项。
- 其他：`map_author_decision_service.py`、`guided_flow/world_progression_review.py`、
  `evidence_tools.py` 的 `map_spatial_brief`、`map_journey`、`map_object_position`。
- 未审：`operation_trace_report.py` 与 `operation_trace_http_adapter.py` 的统计细节、`forecast/` 改动。

## 确认无问题

- 计划校验：步骤数、体积、引用图（重复、自依赖、未声明前置、循环）、目录风险与权限一致、目标类型、
  多阶段操作必须有领域回执接口；引用值按声明类型校验。
- 范围比较：新增操作、模块、目标、更高风险、更大预算、开启 `auto_r2`、目录变化都算扩大；
  `resume_goal` 只允许 `larger_budget`，不能延长时限，未知计费时拒绝。
- 步骤执行：准备与执行前都按 `_check_step_targets` 和 `ASSISTANT_REQUIRE_OPERATION_TARGETS` 校验目标；
  参数漂移且原操作已开始时记为结果未知；预览指纹变化时阻断；单事务步骤在 savepoint 中执行，
  失败回滚后记录。多阶段步骤用稳定任务 ID 防重，原任务缺失、运行中或非终态都停下核对。
- 回执核对：预览与决定都绑定原 operation、调用 ID、参数指纹与任务引用；只有终态回执能证明
  已应用或未应用；未知计费仍阻止继续和重规划。
- 恢复清单：只覆盖待办可恢复字段与单事务档案编辑；应用后重新预览比对；恢复做版本 CAS，部分失败
  进入 `restore_stopped`。
- 统一提醒：处置按（来源、条目、依据指纹）CAS；“忽略”绑定指纹，依据变化后重新出现，符合 ADR-0040；
  来源失败降级为 `partial`。空间提醒静默绑定 Scene 与条目指纹并在确认范围内重验。
- 留痕：声明字段只存类型、长度/分桶和按作品加盐的 HMAC，未声明字段只记出现标记；引用只收 UUID；
  写入前总是重读账户开关，演示账户不记录；写入失败不阻断业务。
- 地图作者决定读取只接受作者模式、绑定会话与任务的运行，返回消息 ID 与原文摘要；目标运行
  （`mode="goal"`、无会话）读取时失败关闭，不会把目标文字当作作者决定。
- 窄 HTTP 入口与目标 API 都先经 `require_active_project`（按当前账户 owner 过滤），确认时重算预览指纹。
- 世界推进复核引导：钩子 ID 含步骤 ID 与输出哈希；采用前重算预览哈希；操作 ID 按运行与钩子窗口确定。
- 地图行程与位置工具读取的键与 World 空间简报一致；行程只有起点和终点、没有双向标记，反向询问返回
  unknown 是正确的。

## 发现

### B8-F1（P3）目标规划器看到两个必然失败的地图操作；地图作者决定的排除从未生效

- 位置：`backend/modules/assistant/goal_runs/service.py` 第 811–812 行
  `_is_map_author_decision_operation` 判断 `operation_id.startswith("world.map.")`，第 3877 行
  `approve_goal_step` 用同一前缀；地图操作在 `world/assistant_map_tools.py` 的 `OPERATIONS_SPEC` 中登记为
  `map.*`，从未有 `world.map.` 前缀的操作。另外 `map.prepare_tray_placement` 声明为 `permission="read"`
  并带 `apply`，`_goal_operation_unavailable_reason` 不拦，`planning.py` 的 `validate_plan` 却拒绝
  “只读操作声明写入回调”。
- 规格：ADR-0038 §6“作者决定适配器不能把 goal 计划或来源会话内容当作作者对地图/世界事实的决定。
  若没有可验证的 goal 作者决定凭据，必须返回原工作台确认”；README“地图作者决定读取仍需原工作台的
  作者决定凭据”。现有测试 `test_goal_planner_sees_only_operations_that_execution_can_authorize` 的意图是
  “规划器只看到执行端能授权的操作”。
- 问题：目标规划器收到全部 11 个地图操作。
  - `map.edit_spatial_structure`：目标运行没有会话，`read_map_author_decision` 必然拒绝；步骤在准备时
    失败，提示“步骤基线或项目授权已变化：没有找到当前作品中可核验的作者安排”，作者看不出原因是
    “需要回地图工作台”。为此准备的不可用原因“需在地图工作台核对作者决定来源”、停点
    `map_author_decision_required` 和 `approve_goal_step` 的拦截都是死代码。
  - `map.prepare_tray_placement`：模型选中后，选择与规划两次请求已计费，`validate_plan` 才拒绝，目标停在
    `planning_failed`，提示只是“计划暂未生成”。作者按原目标重规划，模型很可能再次选中它。
  - 安全边界没有被突破：结构编辑在领域侧失败关闭，其他地图写入在目标内都停在逐步确认。
- 复现：`modules/assistant/tests/test_map_series_review_regressions.py` 的
  `test_b8_goal_catalog_routes_map_author_decision_edits_to_workbench`（去掉 xfail 后失败在
  `map.edit_spatial_structure` 仍在可用列表）与 `test_b8_goal_catalog_offers_only_operations_validate_plan_accepts`
  （失败在 `{'map.prepare_tray_placement': '目录只读操作不能声明写入回调'}`）。临时探针另确认 11 个地图
  操作全部可用，只有托盘入口过不了计划校验。
- 建议方向：前缀改为实际操作名，或给目录项一个显式标记（例如需要作者决定凭据）而不是靠名字；
  `_goal_operation_unavailable_reason` 复用 `validate_plan` 的目录级检查，保证“规划器可见”与“计划可通过”
  同源。是否把其他地图写入也排除出目标，见下方观察 1，需先定口径。

## 观察（未定为问题）

1. 除结构编辑外，其他地图写入（加入已知地点、改图元名称、建节点、移动节点、合并节点、处理版本、
   审核线索与自动草图）都能进入目标运行并在逐步确认后执行。代码里的停点文案“地图作者决定需要在原
   地图工作台确认”像是打算排除全部地图写入；ADR-0038 §10 又允许助手做这些操作。另外
   `_TARGET_PARAMETER_FIELDS` 不含 `revision_id`、`feature_id`、`scope_id` 和线索决定列表，计划卡的目标
   范围覆盖不到这些对象；因为地图写入都要逐步确认、作者能看到预览，目前不越权。
2. 多阶段步骤的领域提交在建任务之前就失败（例如提交时的领域校验）时，记为结果未知
   （`task_receipt_missing`）。原任务不存在，核对无法给出终态回执，重规划也被阻止，作者只能取消目标。
   这符合 ADR-0038“缺失的回执继续阻断”，但对确定没提交的情况偏保守。
3. 统一提醒“忽略”后条目从列表消失，界面没有查看或撤回已忽略条目的入口；依据变化后会自动重新出现，
   API 也可以改回已读。
4. 目标运行中途执行恢复后，`stop_code` 清空、phase 为 `restored`，运行状态不变；之后只能重规划或取消，
   活动目标的唯一槽位继续占用。恢复还要求整个操作目录指纹不变，任何操作改版都会阻止恢复。
5. `notice_service.py` 末尾的 `OPERATIONS_SPEC` 没有被登记（实际登记的是
   `notice_disposition_operations.py`），是重复的死代码。
6. 助手提醒来源把请求范围（章节、Scene）直接写进条目 `target`；在章节范围列表里，没有位置信息的提醒会
   显示为属于当前章节。

## 回归测试

- 新文件 `backend/modules/assistant/tests/test_map_series_review_regressions.py`，沿用相同的文件头说明；
  两条 strict xfail 共用 `_goal_catalog()`，复用现有目录测试的装配方式
  （`app.bootstrap._container_services` 与 `register_task_handlers`），不访问数据库或模型。
- 验证（2026-10-17，基线 `a479e006b`，在 `backend/` 下运行）：新文件 `2 xfailed`；加 `--runxfail` 为
  `2 failed`，各自失败在上述断言。ruff format/check 通过。
