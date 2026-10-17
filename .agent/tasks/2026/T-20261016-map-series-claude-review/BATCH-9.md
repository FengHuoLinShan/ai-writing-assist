# 第 9 批：评测驱动、评测只读服务与前端抽查

审查基线：`codex/map-enhancement-plan` @ `a479e006b`（merge-base `00d861283` = origin/main）。
规格：`evals/datasets/map_spatial/README.md`、ADR-0038 §6、AGENTS.md“产品与前端”（失败/冲突反馈、
作者语言）、`testing-guide.md` 的真实模型与私有目录规则。

## 结论

地图评测驱动的守卫是完整的：私有目录必须在仓库外、权限 0700/0600、拒绝符号链接；live 命令需要
`--execute` 加地图专用开关；数据库只接受专用 loopback PG；holdout 判分要先过开发门禁；质量门按题材
累加真实分子分母，未知即阻断。三个评测只读服务都先过 `require_active_project`，每条查询按
`novel_id` 过滤，只被 evals 调用。前端抽查的重排对话框、统一提醒、人物弧计划和世界推进的确认路径都
绑定了预览或版本，并有防重复提交。发现 1 个 P3：目标运行面板把所有 409 换成同一句“目标状态已更新”，
丢掉服务端给出的具体原因；有一条前端 `it.fails`。

## 已审范围

- 评测：`evals/map_spatial.py`（私有目录、案例占用、live 审批、数据库目标、报告）、
  `evals/map_spatial_guard.py`（`BOUNDS`、`Metric`、`summarize_metric`、裁判提示）、
  `evals/map_spatial_control.py` 的 `explicit_execution` 与 `score`、`evals/schemas.py` 的教师模型常量、
  `evals/datasets/map_spatial/README.md`。
- 评测只读服务：`modules/{assistant,evolution,world}/map_evaluation_read_service.py`。
- 前端：`GoalRunsPanel.vue`（脚本全文）、`UnifiedNoticesPanel.vue`（脚本全文）、
  `ChapterOrderDialog.vue`（脚本全文）及 `WritingView.vue` 的完成回调、`editorController.js` 的
  `autosave`、`useWritingWorkspace.js` 的 `selectChapter` 与人物弧计划函数、`OutlineFloat.vue` 的按钮禁用、
  `WorldProgressionPanel.vue` 的启动、轮询、钩子预览与采用；为核对补读后端
  `story/continuity/chapter_order.py` 的 `restore`/`preview_restore`、`story/world_progression_api.py` 的启动接口。
- 未审：`InteractionAuthorPanel.vue`、`ObjectDossierPanel.vue`、`OperationTraceReport.vue`、
  `StoryFactTimelinePanel.vue`、`SceneDirectorPanel.vue`（第 7 批只看了暂停提示）、`CreativeExperiments.vue`、
  `ForecastDock.vue`、`GoalPlanField.vue`/`GoalPlanStep.vue`、`WorldDossierManifestImport.vue`、
  `WorldRelationsTab.vue`/`worldRelationsAliasesOps.js`、`ProjectSettingsView.vue`、Scene 工作台的其余改动；
  `WorldProgressionPanel.vue` 的连续授权、分支管理与导演入口。

## 确认无问题

- 评测守卫：私有根在仓库外且权限严格；案例占用防重入；live 需显式 `--execute` 与
  `MAP_SPATIAL_EVAL_ALLOW_LIVE=1`；`run_writing_pair` 读源之前已过 live 审批；被测调用固定为 Codex
  `gpt-6-luna`，快照的 `reasoning_effort` 必须为 `max`。
- 质量门：`summarize_metric` 遇到缺失或 unknown 整组阻断；spatial_consistency 必须严格优于无地图，
  正文质量不得低于无地图；无预设阈值的辅助指标不进门禁。
- 评测只读服务：只读查询，先校验当前账户 owner，再按 `novel_id` 过滤；生产代码无调用方。
- 章节重排：确认要求预览的目标顺序与当前一致、无阻断项、编辑器未处于只读/未保存/保存中，并带预览
  哈希；恢复在服务端锁内重验重排后的指纹，来源变化则拒绝。
- 统一提醒：处置带依据指纹与 `expected_row_version`，`busyKey` 防重复，409 后按最新状态刷新；
  作用域切换时丢弃迟到响应。
- 人物弧计划：确认前比对草稿与预览文本，带 `operation_id`、`expected_version` 与预览指纹；按钮按人物
  禁用；只有持久化成功后才提示“已保存”。
- 世界推进：启动带资料确认与预算预览哈希；预览哈希包含本作品推进根统计，首次启动成功后用旧预览重试
  会得到 409，不会重复付费；钩子采用的 `operation_id` 在预览时固定，草稿改动后服务端因哈希不符拒绝。
- 目标运行面板：所有动作带 `expected_revision` 与 `busy` 守卫；启动的 `request_id` 随草稿保存，结果未知时
  用同一编号重试，服务端按请求哈希幂等。

## 发现

### B9-F1（P3）目标运行面板把所有 409 换成同一句“目标状态已更新”，作者看不到真实原因

- 位置：`frontend-console/vue/components/GoalRunsPanel.vue` 第 547–549 行 `readableError` 遇到 409 一律返回
  “目标状态已更新。服务器进度已刷新；未提交的目标和计划草稿仍保留。”；`submitStart`（第 585 行）和
  `runAction`（第 700 行）的 409 分支都用它。`api/_shared.js` 已把服务端原因放在 `error.message`
  （“请求冲突：<原因>”）和 `error.detail`。
- 规格：AGENTS.md“验收受影响的……失败/冲突”“默认用作者/读者语言”；服务端的 409 已经是作者语言，
  而且很多不是“状态已更新”，而是需要作者采取别的行动。
- 问题：
  - 启动时项目模型连接不可用（`goal_runs/service.py:1615`，`ConflictError("当前项目模型连接不可用，请先检查作者账户设置")`）：
    作者只看到“目标状态已更新……”和“恢复上次提交”，重试仍是同一个 409，不知道该去账户设置。
  - 继续运行时时限已到（第 4130 行）、重规划时有步骤待核对（第 4068 行）等同样被换成“状态已更新”。
  - 启动的 `pendingStart` 只在成功后清空；失败后目标文字、预算和确认框都被禁用，界面上只能重发同一请求。
    结果未知时这样做是对的，但服务端明确拒绝（409/404）时作者无法修改或放弃，只能刷新整个页面
    （草稿存在模块级 `Map`，切换面板不会丢）。
  - 不涉及数据或安全：服务端的拒绝都成立，只是作者拿不到原因。
- 复现：`frontend-console/tests/vue/assistant/GoalRunsPanel.test.js` 的
  `B9-F1: 启动目标被 409 拒绝时，显示服务端给出的具体原因`。去掉 `.fails` 后失败在
  `expected '目标状态已更新。服务器进度已刷新；未提交的目标和计划草稿仍保留。恢复上次提交' to contain '模型连接不可用'`。
- 建议方向：409 时同时显示服务端原因（优先 `error.detail`）与“已刷新”的提示；服务端明确拒绝启动后
  解锁表单或提供“放弃这次提交”。现有测试“retains an unsent replan reason when the server returns 409”
  只断言出现“目标状态已更新”，可保留。

## 观察（未定为问题）

1. 地图评测的教师校准与裁判（`score`）经 Codex 调用 `EVAL_TEACHER_MODEL`，即 `gpt-6.1-sol/xhigh`
   （`evals/schemas.py:17–18`，`map_spatial_control.py:2068` 起），开发门禁与 holdout 判分都依赖它。
   2026-10-16 用户为编辑审读对照试跑定下的分工是“被测只用 Codex Luna；盲评由用户手动开 Sonnet 5.5，
   执行 Agent 不调用裁判，只写 handoff”。如果这一分工也适用于地图评测，live 运行前要用户决定：单独授权
   Sol 裁判，或把 `score` 改成产出盲评包与 handoff。代码本身需要 `--execute` 加 live 开关，不会被误触发。
   **已定（2026-10-17）**：用户确认地图评测裁判用 Sol，xhigh 可，现有常量不改；上述盲评分工只适用于
   编辑审读试跑。
2. `summarize_metric` 的 `without_map` 按带地图一臂的分母加权（`map_spatial_guard.py:1580–1583`）。每个案例
   只有一个无地图分数，两臂观察机会数不同时，汇总的无地图分数会偏向带地图一臂机会多的案例。
3. 某题材全部案例对门禁指标都是 not_applicable 时，该指标 `passed=False`，门禁一直阻断。README 要求
   “仅真实零机会可 0/0”，属于设计选择，记录以免误读为缺陷。
4. 章节重排对话框的恢复按钮与 `confirmRestore` 不检查 `blocked`（编辑器只读、未保存或正在保存），重排确认
   却检查。服务端恢复在锁内重验指纹；未保存正文在换章时按草稿 ID 和 `expected_version` 保存，不会写进别的
   章节或丢失，所以只是两条路径口径不一致。

## 回归测试

- 前端：`frontend-console/tests/vue/assistant/GoalRunsPanel.test.js` 末尾追加 `B9-F1`（`it.fails`），复用文件内
  `setupApi`/`mountedPanel`，错误对象按 `api/_shared.js` 的形态构造（`message`、`status`、`detail`）。
- 验证（2026-10-17，基线 `a479e006b`）：该文件 `12 passed | 1 expected fail`；临时去掉 `.fails` 后失败在上述
  断言，已改回。后端回归文件未改动。
