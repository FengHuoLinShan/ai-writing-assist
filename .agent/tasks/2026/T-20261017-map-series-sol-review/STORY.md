# Story / 世界推进 / Scene 前端只读审查

本轮改动补齐导演预算暂停恢复、世界推进原资料确认与档案交集、持续授权停止原因，以及重排后的事实时间线。审查发现 **4 个 P2、1 个 P3，无 P1**；其中一个是本轮修复引入的时点事实丢失，一个是 B7-F2 的残留场景，另外三个来自原报告明确未覆盖的前端路径。建议先修复下述问题再交付。

## 基线与方法

- 工作树：`.worktrees/map-series-review-fixes`，分支 `codex/map-series-review-fixes`，HEAD `3b2ac9441c0dc08533a3e62269cd054ff35c5302`；本轮修复以 `git diff HEAD` 为准，包括未跟踪的测试与迁移。
- 原系列实现以 `git diff 00d861283e34bdc0ef3f34ee5605c71e1f89c553 a479e006bc336c0009e5207f7659609ab483e901 -- <相关路径>` 定位，未把已存在于 HEAD 的实现当成已审。
- 读取本工作树 AGENTS.md、Story README、ADR-0038/0039/0040/0041 相关契约、原 SUMMARY/BATCH-7/9/10、世界推进原任务计划和本轮修复 TASK；按 ponytail-review 追踪入口、调用方、数据形状及现有回归。
- 假设正常多进程服务和作者可建立多个推进根；没有借只读审查启动服务或模型。以下证据为静态调用链推导，未新增或执行测试。

## P2

### S1：档案合并丢失 Scene 身份，使已确认的所有 continuity 条目被过滤

位置：`backend/modules/story/world_progression_context.py:547-549`、`:594-596`；共同原因在 `:52-65` 的 `_merge_briefs`。

**场景与影响：** 作者已在本次确认中选择本场人物位置、物件保管等时点事实，再预览或启动世界推进。两处读取将 `_merge_briefs(...)` 直接交给 `restrict_object_dossier_brief`，但合并结果没有 `scene_id`。Evidence 重新构造条目时使用空 Scene，而原确认使用真实 Scene，导致这些明确已选事实全部消失，角色包缺少本场知识与状态，模拟不能从已知位置和保管关系起步，正常移动/资源行动会退化为 unknown/uncertain。

**证据：** `evidence/compilation/services/object_dossier_sections.py:62-78` 使用传入简报的 `scene_id` 重新构造条目并按精确身份匹配；`:204-215` 的 continuity `fact_id` 将 `scene_id` 放进哈希。`director_state.py:39-84` 只从保留下来的 `continuity_items` 建位置与保管状态。新回归 `test_b7_progression_dossiers_are_intersected_with_confirmation` 的 `continuity_items=[]`，只能证明 World 条目排除，没有覆盖这一损失。

**最小修复：** 两处求交集前都补入已解析并核验的 `scene_id`，与 `scope_progression_source` 现有做法一致。增加一条保留已确认位置/保管事实、同时排除未选事实的行为回归；不要放宽 Evidence 的精确匹配。

### S2：首次持续授权没有任何可见入口，主动关闭后也无法重新开启

位置：`frontend-console/vue/views/outline/components/WorldProgressionPanel.vue:361`。

**场景与影响：** 一个从未开启持续提醒的作品完成了第一步推进。整块授权表单要求 `authorizationFor(root)?.branch_id === branch.id` 才渲染；没有授权记录时后端返回 `branch_id: null`，所以每条分支都隐藏表单，作者无法第一次选人物并授权。已有授权主动关闭时服务同样清空 `root_id/branch_id`，刷新后重新开启入口消失。

**证据：** 后端 `world_progression_continuous.py:256-270` 的无记录响应明确返回空根、空分支，`set_continuous_authorization` 在关闭时将这两个指针清空。前端唯一的 `setContinuous(..., true)` 按钮位于上述条件区内。现有前端用例通过替身直接提供 `branch_id: "branch-1"`，没有覆盖实际无授权响应。

**最小修复：** 在未绑定授权时，让可授权的已完成分支显示首次授权入口；已绑定时将开关显示在真实绑定分支。保留显式人物选择、原预算及 revision CAS。覆盖首次开启与关闭后重新开启。

### S3：创建新推进根后，旧根的持续授权无法从界面关闭

位置：`frontend-console/vue/views/outline/components/WorldProgressionPanel.vue:1138-1154`。

**场景与影响：** 根 A 已有持续授权，作者另建更晚的根 B，然后刷新历史或重新打开面板。前端只取最新根 B 的第一条分支读取授权，服务因授权仍绑定 A 返回 409；前端把它显示成历史错误，既不定位 A，也不读取 A 的授权。旧根 A 的 `authorizationFor(root)` 为空，关闭按钮不可见，作者无法撤销或迁移旧授权，而服务仍保留授权并可能继续使用 A 的剩余预算。后续给 B 开启授权也会被“已有另一条持续推进授权”拒绝。

**证据：** `world_progression_api.py:880-882` 明确拒绝读取另一根绑定的授权；组件 `authorizationFor`（`:1482` 起）又只暴露 `activeAuthorizationRootId` 对应根，`setContinuous(..., false)` 无其他界面入口。后端允许建立独立新根，不要求先关闭旧授权。

**最小修复：** 读取作品当前授权并绑定到它实际的根/分支，或在跨根冲突时查询历史根找到真实授权；确保旧根仍有明确关闭入口，再让作者切换授权。不要隐式撤销旧授权。覆盖 A 已授权后建立 B、重新挂载并关闭 A 的流程。

### S4：交汇转入导演时预览与启动的指示不同，预算指纹必然不匹配

位置：`frontend-console/vue/views/outline/components/WorldProgressionPanel.vue:1586`、`:1630`。

**场景与影响：** 作者从推进结果选择“以此交汇准备导演起点”，完成预算预览及资料确认，再点击开始导演。预览发送“从作者选择的世界推进交汇候选开始一轮场景导演排演。”，提交发送“从作者明确选择的世界推进候选交汇起点进行排演。”；分别为 25、23 字符。服务重算的预算指纹不同，每次都返回 409，重新预览也无法成功。

**证据：** `director_budget.py:88` 将 `instruction_chars` 放进 `preview_identity`；`director_api.py:213-216` 在创建运行前用正式请求重算并比对。现有 WorldProgressionPanel 回归只检查导演起点草稿和预算预览，没有点击最终启动。

**最小修复：** 预览和提交复用同一个指示文本/请求字段，保留预算指纹检查。补预览至启动的调用参数一致性回归。

## P3

### S5：B7-F2 仍允许对已离场人物发言，在裁决计费后确定性失败

位置：`backend/modules/story/director_tasks.py:1103-1107`；`director_consistency.py:70-80`。

**场景与影响：** A、B 原本同处一地且互相已知；第一轮 B 的 `leave` 成功，第二轮 A 把 B 放入受众。离场只更新 `departed`，不会清掉 B 的位置；校验收到的是全部 `character_ids`，只检查已知身份和位置相同，因此允许该意图进入下一次裁决请求。裁决已计费、结果也保存后，结算按 active 观察者排除 B，抛出 `Observation recipients must belong to this scene`，根与分支进入失败；重跑同一检查点仍会失败。

**证据：** `simulation_v3.py:382-389`、`:466-475` 显示离场不清位置；`director_tasks.py:924-927` 只从意图生成人物中去掉离场者，`:1105` 校验仍传全量；`:1172-1177` 结算使用 `participants - departed`，`simulation_v3.py:257-259` 必须拒绝不在观察者中的受众。本轮新用例覆盖无位置受众，没有覆盖已离场受众。

**最小修复：** 校验与结算使用同一 active 参与者/观察者集合，在裁决请求之前拒绝离场受众；保留角色知识与同场位置校验。补两轮离场后向离场者发言的用例。

## 覆盖结论与排除项

- **B7-F1：** 已读预算预览、回合内硬预算/回合间软阈值、原分支恢复 API/操作/schema/worker、根锁与任务幂等、检查点指纹、追加请求/Token、未知计费确认与原 deadline，以及 SceneDirectorPanel/API。首回合半步和已完成回合后的恢复已有合成回归；没有确认其他新缺陷。S5 单列为 B7-F2 残留。
- **B7-F2：** 无位置受众在裁决前拒绝已实现；离场受众仍有 S5。生产 `validate_intents` 调用方只有导演 worker，新参数已接齐，相关测试也已适配。
- **B7-F3：** 预览、启动、当前/冻结续跑、半步恢复、持续触发、历史失效读取及 eval 适配器已要求重新物化 confirmation，并分别收窄作者与 POV 档案；但新鲜读取路径因 S1 丢失已选时点事实。`scope_progression_source` 对作品/Scene 身份失败关闭；其 simulation 重建只消费传入并已收窄的 brief，DB 仅校验引用，不会自行读取当前或后续 Scene 状态，此假设已排除。
- **B7-F4：** 读取最新未恢复重排时间，按事件创建时间投影 stale/current，SQL 筛选与返回状态口径相同；`source_stale` 独立保留。现有测试已覆盖重排前/后事件、筛选及重提取，不再把同一 Scene 的所有新事件永久标 stale。
- **持续授权与迁移：** 已读授权开关、整章计数/outbox、根预算、修订 CAS、触发/worker 重验、关闭与删除绑定关系，以及未跟踪的 `test_world_progression_continuous.py`。新增 `20261017_story_world_progression_scope_stop.py` 仅追加 nullable `String(64)`，与 ORM 一致。最新 Scene 超过原确认截止时关闭授权并保留 `stop_reason` 是已说明产品限制，**不作为缺陷**；S2/S3 是限制之外的界面授权生命周期问题。
- **原未审前端：** 用原 merge-base 差异读 Scene 工作台的 v2 人物卡展示/保存、反应多方案选择及提交、运行草稿序列化/容量反馈、只读旧排演、移动端关闭保护与导演入口替换；读 WorldProgressionPanel 连续授权、分支元数据 CAS、软删除/30 天恢复、比较和交汇导演入口。除 S2/S3/S4 外没有确认新增问题。B10-F2 按用户要求留给 ADR-0042，没有重新报为缺陷。
- **eval 适配器：** 已追踪 `authoring_quality_product.py` 的原 confirmation 重物化、导演 scope 交集、推进 source 调用、任务/根/分支身份、输出/父 hash 和当前来源校验；调用方已适配新签名，仍会受到 S1 的来源信息损失。未读取或修改冻结评测原始材料。

结论：先修复 S1–S5。只写了本审查报告，未改生产代码、测试、迁移或其他任务记录，未提交。

未执行测试、浏览器、真实模型、真实数据库或封存评测；现有绿色结果不能覆盖上述未测试的调用场景。
