# 第 5 批：地图前端

审查基线：`codex/map-enhancement-plan` @ `a479e006b`（merge-base `00d861283` = origin/main）。
规格：`docs/modules/15_map.md`、`docs/product/user-personas.md`、AGENTS.md“产品与前端”验收项。

## 结论

地图工作台新增的 7 个面板在并发守卫、确认、409 冲突提示、草稿保护和离开守卫上基本完整；工作台
`useLeaveGuard` 与 `beforeunload` 覆盖了所有新面板的 dirty/busy 状态。发现 1 个 P2、3 个 P3：地图引导
自己推导阅读模式，绕过了 ReadingFlow 只对已结束运行开放新阅读的门槛；空间补扫运行时仍可追加阅读
（第 2 批疑点 2 成立）；未开空间发现的旧阅读，引导的默认选项必被后端拒绝；非主空间的选中图元在重开
地图后丢失。4 项都有前端回归测试（vitest `it.fails`，语义同 strict xfail）。第 2 批疑点 1 关闭。

## 已审范围

- `frontend-console/vue/views/map/`：MapColdStartPanel、MapNodeMergePanel、MapSpatialMetadataPanel、
  ProjectVocabularyPanel、MapCandidateLocations（全文）；MapAutoDraftPanel、MapSpatialCluePanel（全文，
  本批上半段）；MapStructureEditor.vue、mapStructureEditor.js、MapWorkspaceView.vue 的 diff；
  `vue/shared/mapTrayNavigation.js`。
- `frontend-console/vue/components/ReadingFlow.vue` 的空间发现、空间补扫与冻结授权部分。
- 为核对前端问题补读的后端：`evolution/workflow.py` 的 `_plan`、`start_reading`、`reading_status`；
  `evolution/assistant_tools.py`；`assistant/guided_flow/map_cold_start.py`。

## 确认无问题

- 自动草图托盘：epoch/projectId 守卫、确认、409 提示；助手入口经 `parseMapTrayNavigation` 校验
  （1–20 项、身份去重、长度上限），只带冻结身份，坐标只来自画布。
- 空间线索审核：确认、草稿保护、409 处理；审核路径的错误都是中文。
- 节点合并：预览 → 勾选来源处置 → 二次确认 → 带指纹提交；撤回也先预览；409 时保留选择并提示重新
  预览。
- 项目词表：放弃未保存编辑需确认；409 保留编辑内容；归档、合并、拆分都要确认；换项目全部重置。
- 候选地点：确认后逐个采用，每批 ≤20，部分成功保留并提示；409 触发重新预览。
- 结构编辑器：确认带 epoch；`busy` 覆盖元数据面板、确认框、采用预览与地点采用；自动草图按
  `review_base_revision_id` 判断是否过期；勾选候选地点未处理前不能确认采用地图。
- 元数据面板：Story 状态记录带幂等键，Story 已写入时只重试场景投影；保存期间经父级 busy 禁用翻页与
  重读；锁定的图元不能移空间；用作底图校准的图元先要解除校准。
- 工作台：节点合并后旧链接显示“此地图已合并”，须作者点击才打开目标；新面板 dirty/busy 时写操作和
  RP 入口都被锁定并给出原因。

## 发现

### B5-F2（P2）地图引导绕过“只对已结束运行开放新阅读”的门槛

- 位置：`frontend-console/vue/views/map/MapColdStartPanel.vue:52-63`（`prepare()` 按运行状态推 mode，
  不在映射表里的状态一律落到 `bootstrap`）；冻结授权路径
  `frontend-console/vue/components/ReadingFlow.vue:25`（`authorizePrepared`）也不检查运行状态。
  对照：ReadingFlow 自己的入口受 `canStart`（第 83 行）限制，只对 completed、stopped、
  source_changed、needs_budget 和部分 failed 开放。
- 问题：最新阅读处于 running、pending、needs_reconciliation、needs_scene_review、interrupted 等状态时，
  地图引导准备的是 `mode: bootstrap, run_key: null`，范围从第 1 章到“当前读到的章节 + 1”。后端
  `_plan` 的 bootstrap 分支和 `start_reading` 都不检查已有活跃运行（`register_run` 也不检查），作者确认
  后会在原运行之外再起一个从头重读的运行，重复计费。needs_reconciliation 的含义是“上次请求可能已计费，
  不能直接重试”，这条路径绕过了它。作者确认页会显示场景数和调用上限，所以不是静默扣费。
- 复现：`MapColdStartPanel.test.js` 的 B5-F2（running、needs_reconciliation 两条），去掉 `.fails` 后
  失败在 `mode: "bootstrap", run_key: null, end_chapter: 4`。
- 建议方向：引导复用 ReadingFlow 的 `canStart` 判断（或由 `map_cold_start` 后端按最新运行状态校验
  mode）；运行未结束时只提供“等待/去演化核对”。

### B5-F1（P3）空间补扫运行中仍可追加阅读（第 2 批疑点 2 成立）

- 位置：`ReadingFlow.vue:554` 表单只看 `canStart || pending`；“查看理解范围”（第 580 行）和
  “确认并开始理解”（第 594 行）只看 `authorizationLocked`/待授权的补扫，不看 `spatialRescanActive`
  （第 60 行，仅用于禁用补扫 fieldset，第 460、482 行）。后端 `_plan` 的 append 分支与 `start_reading`
  也不检查进行中的补扫。
- 问题：补扫运行时阅读状态仍是 completed，作者可以预览并启动追加。追加推进 head 后，补扫下一次发送在
  `pipeline.py` 预约时报 `parent_advanced` 失败；恢复仍绑定旧 head，只能重新预览补扫。再叠加 B2-F6
  （补扫规划不读已补扫的回执），重新预览会把已补扫的 Scene 再计费一次。补扫本身失败关闭，不重复发送。
- 说明：类别补扫（`rescanActive`）在基线就有同样缺口，空间补扫沿用了这个模式；本条只针对本系列新增的
  空间补扫写测试。
- 复现：`ReadingFlow.test.js` 的 B5-F1，去掉 `.fails` 后失败在“查看理解范围仍可用”的断言。
- 建议方向：补扫 pending/running 时禁用追加入口；后端 append 同时拒绝进行中的补扫（若只在后端修，
  前端用例仍会保持“预期失败”，需同步调整）。

### B5-F3（P3）未开空间发现的已完成阅读，引导默认选项必被拒绝

- 位置：`MapColdStartPanel.vue:52-63`，`scope.kind` 默认 `reading`，completed 时推出
  `mode: append, discover_spatial: true`；后端 `workflow.py` `_plan` 的 append 分支拒绝改变空间发现开关
  （“追加章节不能静默启用或关闭空间发现”）。`reading_status` 已返回 `spatial_discovery_enabled`，面板
  没有使用。
- 问题：地图引导面向“正文已读但没有空间资料”的作者，正好是这种旧运行。默认选项提交后只得到一条
  不指向下一步的错误，作者要自己想到改选“已读范围补扫空间”。对旧运行，新章节也无法带空间发现追加，
  只能先普通追加再补扫，面板没有说明。
- 复现：`MapColdStartPanel.test.js` 的 B5-F3，去掉 `.fails` 后失败在
  `mode: "append", discover_spatial: true, run_key: "old-run"`。
- 建议方向：旧运行未开空间发现时默认选中补扫，并说明新章节需先普通追加再补扫。

### B5-F4（P3）非主空间的选中图元在重开地图后丢失

- 位置：`frontend-console/vue/views/map/MapStructureEditor.vue:550`（`restoreView` 先设
  `selectedId`、再切 `activeSpaceId`）与第 1067 行切空间时同步清空选择的 watcher；`applySpatialDocument`
  （移入其他空间后跟随切换空间）是同样的先选后切顺序。
- 问题：作者在“梦境”空间选中图元后离开再回来，空间恢复为梦境，但选择被清空；用元数据面板把图元移入
  另一空间后，编辑器跟到新空间却丢了选择，而这个图元坐标已清空、正需要重新定位。主空间不受影响。
  属于 AGENTS.md 的“离开恢复”验收项。
- 复现：`MapStructureEditor.test.js` 的 B5-F4，去掉 `.fails` 后失败在选中列表为 `[]`；对照把
  记住的图元换成主空间的 `a`，选择正常恢复（临时用例，已删除）。
- 建议方向：先切空间再设选择，或在 watcher 中保留属于新空间的选择。

## 第 2 批疑点处理

- 疑点 1 关闭：英文 `ValidationError` 只写入缺口 detail，`ReadingFlow.vue:449` 只显示“另有 N 条检查缺口”
  的计数，不显示 detail。
- 疑点 2 成立，记为 B5-F1。

## 第 3 批观察在前端的表现

- 节点合并后空间超过 20 个：前端原样列出后端 blocker（“地图内容无法安全合并”），没有更多指引，观察不变。
- 冷启动零批次：停点原因“空间草图尚未完整就绪”经 WritingFlowHost 显示，作者可以“结束本次引导”，
  但无法完成，观察不变。
- 失效图元 note 以换行开头：只读展示在 `<p>` 中，前导换行被折叠；只在编辑框中显示为空首行，无害。

## 观察（未定为问题）

- 排演路线跳过带类型、有效期或非观察性质的通路与端点（有测试，属有意设计），但跳过后的提示是
  “之间没有足够的明确道路资料”，与地图上实际有通路不符；前端也没有服务端空间查询入口。自动草图生成的
  图元多带项目类型，排演对这类地图基本不可用。
- 空间线索面板折叠的“来源与端点身份”显示 scene_id、entity_id、type_ref 的原始 UUID（次级诊断入口）。
- 元数据面板的说明直接使用“Scene”“Story 记录”“图元”等内部用语，不符合作者语言要求。
- 元数据面板的通行条件超限错误在改回合法输入后不会清除。
- 冷启动 bootstrap 默认读到“当前章节 + 1”，B5-F2 修复后若保留该默认值仍需核对。

## 回归测试

- `frontend-console/tests/vue/assistant/ReadingFlow.test.js`：新增 B5-F1。
- `frontend-console/tests/vue/map/MapColdStartPanel.test.js`：新增 B5-F2（running、needs_reconciliation
  两条）与 B5-F3，共用 `prepareDefaultScope`；只在提交按钮及其 fieldset 未禁用时才提交，所以“禁用入口”
  和“拦截提交”两种修法都会让用例转绿。
- `frontend-console/tests/vue/map/MapStructureEditor.test.js`：新增 B5-F4。
- 写法：vitest `it.fails`，语义同 strict xfail；修复后用例会意外通过并让测试运行失败，提醒去掉 `.fails`。
- 验证（2026-10-16，基线 `a479e006b`；工作树内按 lock 执行 `npm ci`，node_modules 已被 git 忽略）：
  `npm --prefix ../frontend-console run test` 结果 257 个文件通过，3234 passed、5 expected fail；去掉
  `.fails` 的临时副本各自失败在上述断言（临时文件已删除）；`npm --prefix ../frontend-console run lint`
  通过。
