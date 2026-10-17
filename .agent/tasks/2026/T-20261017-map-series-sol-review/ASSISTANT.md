# Assistant 与前端复审

审查快照：`codex/map-series-review-fixes`，HEAD `3b2ac9441c0dc08533a3e62269cd054ff35c5302`，2026-10-17。修复审查使用 `git diff HEAD`；原系列补审使用 `00d861283e34bdc0ef3f34ee5605c71e1f89c553..a479e006bc336c0009e5207f7659609ab483e901`，并回读当前实现和调用方。工作树原有修改全部保留。

本轮修复把地图阅读入口、目标规划目录和错误提示与执行约束对齐，并把创作试验的技术回执放到次级详情。仍确认 **2 项 P2、1 项 P3**；没有确认 P1。依据为静态调用链和现有测试内容，没有新增或运行测试。

## P2

### A1：补扫与追加阅读的互斥只在前端成立，旧页面仍可使同一运行并发推进

- 位置：`frontend-console/vue/components/ReadingFlow.vue:86`、`:210`；`backend/modules/evolution/workflow.py:246-266`（`_plan` 的 append 分支）、`:814-825`（`start_reading` 的重放与预览核对）、`:875-879`（保留空间补扫记录）。这是 B5-F1 尚未闭环的服务端路径。
- 具体场景：同一作品的 A 页在已完成阅读上取得追加预览；B 页启动该运行的空间补扫，A 页没有重新读取状态便确认追加。或者 A 页已加载 completed 状态，B 页启动补扫后，A 页才做追加预览与确认。前端 `canStart` 使用 A 页缓存的 `state.run.spatial_rescans`，仍为真。
- 证据：`_plan` 的 append 只检查主运行状态、待完成可选阶段、已提交场景和准备进度；没有检查 `spatial_rescan_states`。返回的 plan 由 `workflow.py:277-369` 单独构造，不含 `spatial_rescans`，所以补扫排队本身不使追加指纹失效。补扫启动在 `spatial_rescan.py:459-492` 排队并加入该字段；已有额度足够时无需改变预算。`start_reading` 持项目排他锁，但轮到它执行时依然接受追加，并把补扫记录原样保留。`register_run` 在相同 run_key 已存在时直接返回（`store.py:76-98`）；其新运行单写者约束不阻止这条同运行路径。
- 影响：两个任务可同时使用同一理解前缀。主阅读若先提交下一场，补扫后续发送的父回执核对会触发 `pipeline.py:1280-1285` 的 `parent_advanced`，已完成部分虽保留，原补扫不能按原前缀顺利完成。反向入口已有 `_idle`（`spatial_rescan.py:204-221`）拒绝主阅读在跑，说明此处缺少的是追加方向的同一互斥检查。
- 最小修法：在服务端新追加授权的规划及启动路径共用一次空间补扫活动检查，启动时在现有项目锁内重验；保留 `start_reading:816-822` 的原 operation_id 幂等回读优先级。前端保留当前提示。补一个“两页面旧状态/已取得预览，补扫先排队，追加必须拒绝”的服务级用例。
- 排除误报：不声称 bootstrap 能创建第二个活跃 live 运行；`store.py:104-108` 与数据库唯一约束已保护新运行。也不声称补扫会越过来源校验写入错误结果。

### A2：新增的开始门槛挡住原启动请求的核对，随后连恢复理解也被本地 pending 禁用

- 位置：`frontend-console/vue/components/ReadingFlow.vue:210-218`（`start`）、`:64`（`authorizationLocked`）、`:465-468`（刷新/恢复按钮）、`:568`、`:608`（保留 pending 表单与“确认启动结果”）。属于本轮修复引入的回归。
- 具体场景：作者确认启动，服务端已创建运行，但 POST 响应丢失，组件保留 `pending`。作者点“刷新进度”，发现运行在准备边界后进入 `needs_scene_review`，需要在场景调整完后恢复；或准备场景期间任务中断，状态 failed 且 `total_scenes=0`。这两类状态都不满足新 `canStart`。
- 证据：`start` 现在首先执行 `if (!canStart.value ...) return`，即使 `pending` 已有原请求也直接返回。模板仍显示“确认启动结果”，点击没有回读也没有报错。`pending` 只在启动成功或明确 4xx 时清空，普通 `read/refresh` 不清空它；因此 `authorizationLocked` 始终为真，恢复按钮也禁用。后端 `start_reading:814-822` 本来会先按同一 operation_id 返回现有状态，完全不创建新授权；前端却到不了它。`workflow.py:1530-1531,1588-1594` 明确允许 `needs_scene_review` 状态恢复，排除了“领域本来就不能恢复”的解释。
- 影响：丢响应之后，即使作者已从只读刷新知道原请求落库，当前页面也不能核对并解除本地 pending，不能使用原有恢复入口。running 期间只是核对按钮空转；进入上述作者处理停点后才出现实质恢复阻断。重新挂载组件可清掉内存状态，但不能代替正常的原请求恢复路径。
- 最小修法：只对没有 `pending` 的新授权检查 `canStart`；已有 `pending` 始终用原 operation_id/body 做幂等核对，不能生成新请求。按钮的空间补扫禁用条件同样区分新授权与原请求核对。扩充已有 `ReadingFlow.test.js:27-50` 的失联用例，在重试前插入刷新到 `needs_scene_review/can_resume=true`，断言原请求可核对、pending 清空后恢复可用。

## P3

### A3：目标预算被 422 明确拒绝后，仍被当作未知提交锁住整个新目标表单

- 位置：`frontend-console/vue/components/GoalRunsPanel.vue:43-56`（两项独立额度输入）、`:557-568`（冻结 pendingStart）、`:585-594`（错误分支）；字段禁用在 `:40,46,49,52,55,60`。这是原系列已有遗漏，本轮 B9-F1 只补了 404/409 的释放。
- 具体场景：作者把“模型请求数”从默认 8 改成 2，保留“可能产生费用的请求数”8。两个输入分别都满足 HTML min/max，表单会正常提交。`GoalBudget.charge_budget_fits_requests`（`backend/modules/assistant/goal_runs/contracts.py:21-25`）在请求入口以 422 拒绝，尚未进入 `start_goal` 或创建运行。
- 证据：API 公共层 `_shared.js:469-494` 把错误 status=422 传给组件。`submitStart` 只在 404/409 清空 pendingStart。随后目标文本、全部预算和确认勾选都因 pendingStart 被禁用；“恢复上次提交”与表单提交只会重发同一份无效预算。`refresh` 只读 recentGoals，不释放 pendingStart。现有 B9-F1 回归只覆盖 409。
- 影响：作者看得到预算错误却不能修正预算，也不能放弃这次明确未提交的请求；要重建组件才能恢复编辑。不会产生模型费用。
- 最小修法：422 属于入口校验的明确拒绝，应与现有 404/409 一起清掉 pendingStart 并保留输入；网络失败/5xx 继续保留未知请求。可同时把第二个额度输入的 max 限为总请求数作即时提示，但服务端校验保持不变。回归覆盖上述真实可输入额度及拒绝后可编辑即可。

## 原发现修复覆盖

| 原发现 | 本轮复审结论 |
|---|---|
| B5-F1 | 单页面已读取到补扫状态时能拦截；服务端同运行并发尚缺，见 A1。新门槛又影响已有 pending 核对，见 A2。 |
| B5-F2 | MapColdStart 对 running、pending、needs_reconciliation、needs_scene_review 等状态不再准备新阅读；冻结确认重新读取状态后也检查 mode/run_key。已核对底层单写者约束，不沿用原报告“必能创建重复 live 运行”的推断。 |
| B5-F3 | 已完成且没有空间发现的运行默认选择补扫，普通空间追加选项禁用，提示先普通追加再补扫；原补扫 API 与授权参数匹配。 |
| B5-F4 | `restoreView` 与 `applySpatialDocument` 先切空间再设选择，与 `activeSpaceId` 的同步 watcher 相容；未见残余丢选择路径。 |
| B8-F1 | 目录与计划校验复用 `operation_plan_unavailable_reason`，目标准备/执行也经过 `_assert_plan_operations_supported`；结构编辑按真实 op_id 排除，审批同源。托盘的只读+apply 矛盾不再进入目标规划。其余地图写入保留领域逐步确认，未发现凭此越权。 |
| B9-F1 | 409 保留服务端实际原因并刷新服务端状态；404/409 解锁启动表单。422 明确拒绝仍遗漏，见 A3。 |
| B10-F1 | 采用确认正文为资料/修改数量，UUID、内部类型、完整指纹和 tokens 移至关闭的详情，连接角色映射为作者语言；原采用/核对 API 及请求结构没有被文案修改改变。 |

## 原未审范围补审

- **`assistant/operation_trace_http_adapter.py`：已补审全文及挂载、领域 route metadata、trace service、现有 PG/路由门禁测试内容。** 检查有效路由包装、owner/project 守卫、稳定调用号、confirmed/previewed/executed/outcome_unknown 时机、事务提交失败和恢复回执匹配。动态参数进入脱敏摘要，不直接保存正文；未确认新增缺陷。没有实际运行 HTTP/PG 用例，故不声称本轮证明了运行时挂载和事务行为。
- **`assistant/forecast/preparation.py`、`contracts.py` 及相关剩余改动：已补审。** 追到 service 的安全候选投影/旧新上下文选择、runtime 的独立物化/检查点/共享四请求预算与成对发布、context 的角色隔离和原确认重物化；核对 preparation 的父评估/方向重验、operation_manifest legacy 读取、子运行/唯一批次与 trace context。未确认本次补审的新缺陷。人物反应/转场入口的已知不可达与 feed 422 属于已决定延期的 B10-F2，没有重复计入。
- **`GoalPlanField.vue`：已补审全文与 `GoalPlanStep`、GoalRunsPanel、服务端 `_parameter_fields`/计划校验调用链。** 动态内容由 Vue 插值输出；标识/引用不提供自由输入；递归修改回传当前参数并保留兄弟字段；未确认新缺陷。
- **`WorldRelationsTab.vue` 模板：已补审原系列完整差异及当前全文，连同场景列表/关系 API 和编辑/删除 registry 调用。** 核对 scene 过滤、错误重试、分页、选择集对齐、有效期提示与来源详情；文本采用 Vue 转义，项目切换丢弃旧请求结果。未确认新缺陷。

## 审查边界

只读生产代码，唯一写入为本报告。没有修改实现、测试、配置、ADR 或全局记忆；没有提交、推送、合并、部署或业务模型/真实数据库调用。审查按可同时打开同作品页面、任务 worker 可重叠执行的现有产品形态判断，不要求高吞吐负载才能触发发现。

本组指定代码范围已补读，没有把未执行测试混作未读代码。真实浏览器交互、HTTP/PG 重现、真实模型、封存评测及作者验收均未做；上述发现仍需修复并针对性验证，静态审查不能代替这些验收。
