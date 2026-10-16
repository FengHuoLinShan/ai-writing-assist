# 第 4 批：M3/M4 空间简报、提醒、声明状态与 Evidence 编译

审查基线：`codex/map-enhancement-plan` @ `a479e006b`（merge-base `00d861283` = origin/main）。
规格：ADR-0037、`docs/plans/2026-10-15-map-system-enhancement.md` §M3/M4、`docs/modules/02_world.md`、
`docs/modules/15_map.md`。

## 结论

空间简报的入选条件、揭示过滤、排除链路和快照版本比对都符合 ADR-0037；第 3 批转来的“节点合并后
Context 排除”边界成立：排除的节点或修订经 `map_merge_lineage` 递归找到合并目标并整节点省略，同时给出
提示。发现 1 个 P2、2 个 P3：提醒在途经点只是文字标签时误报“通路网络未连通”；被重算取代的旧阅读运行
持续冒出“上次阅读已暂停”；问世界打开地图引用时不带原排除项。前两项有 strict xfail 回归测试，第三项
修复需要给引用加字段，形状未定，只记录不写测试。

## 已审范围

- ADR-0037 全文。
- `backend/modules/world/`：`map_spatial_brief_service.py`（全文）、`map_merge_lineage.py`、
  `map_spatial_advisory_service.py`（全文）、`map_declaration_state.py`、`validity_policy.py` 的
  地图声明部分、`notice_sources.py`（全文）、`services/worldbuilding/ask_world_service.py` 与
  `schemas/ask_world.py` 的 diff、`map_structure_service.read_map_node_heads`。
- `backend/modules/evidence/compilation/`：`knowledge/{contracts,scope,workflow}.py` 的参考维度改动、
  `services/loaders/map_spatial_loader.py`、`context_compiler.py` 的空间简报 section 与条目排除、
  `snapshot_service.py` 的 diff、`confirmation_service.py` 的地图基线与物化、`review_projection.py`。
- `backend/modules/writing/notice_sources.py`（全文）、`backend/modules/evolution/reading_notice_sources.py`
  （全文）；统一提醒的处置匹配只读了 `assistant/notice_service.py` 120–175 行，其余转第 8 批。

## 确认无问题

- 排除链路：作者排除简报条目时写入 `target_ref = map_spatial:<node_id>`，loader 原样传给简报，
  简报归入 excluded_nodes；整段排除时所有条目记为 excluded。合并后，`excluded_merge_targets` 用递归
  CTE 沿 `map_node_merge` 记录找出所有后代目标（UNION 终止撤销造成的环），整节点省略并返回
  `EXCLUDED_MERGE_UNKNOWN`。简报内容不按图元 ID 排除，所以合并改写图元 ID 不影响排除。
- 排除超过 200 条时 loader 直接不加载简报，不静默丢排除项。
- 简报入选：节点 adopted、未合并、修订 saved；图元须在 canonical 集合、event_observed、生效区间
  覆盖截止点、对象可见（`check_knowledge_visibility` + `inspect_novel_target`）、来源可见
  （原文经 `read_novel_evidence` 可见性，世界书只在 author_safe 投影内且引文命中）。每节点 3000 字符，
  条数受 `limit` 限制。
- 参考维度：省略写入 `advisory_omitted`，不影响 `scope_complete`；审查者对参考维度的发现降为 minor，
  只在全部发现都属参考维度时把 unverifiable/not_checked/blocked 改为 pass。
- 快照：读取时用 `read_map_node_heads` 比对状态、修订、标题、几何 hash 与来源子集；节点合并或删除
  记为 changed，读取失败记为 unavailable。确认物化时核心指纹不含地图，地图基线变化则整段省略并提示。
- 提醒：只比较明确声明；方位冲突要求同空间、两端绑定对象；行程耗时冲突要求同交通方式、旅行者类别、
  通行条件与单位；跨空间要求 `cross_space` 特性；场景移动统一附“无法判断移动是否来得及”。
- 声明状态：写入时对节点 FOR UPDATE、比对当前修订、要求 event_observed 与 canonical 端点；读取时
  要求身份（含修订）精确一致、作者确认、观察早于截止 Scene。地图一保存即退回作者区间并标缺口，属于
  保守的失败关闭。
- 问世界：已确认问答只引用 confirmation 选中的地图节点；未确认问答实时读简报。

## 发现

### B4-F1（P2）途经点只是文字标签时，提醒误报“通路网络未连通”

- 位置：`backend/modules/world/map_spatial_advisory_service.py:935-938` 构建通路图时，只连接两端都
  绑定对象（`entity_id`）的相邻点；975 行 `disconnected_known_network`；993 行发出
  `route_no_active_connection`。
- 问题：地图声明“东城 经 山口 通往 西城”，山口是作者画的文字地标（未绑定世界对象，简报和地图都
  允许）。路径 [东城, 山口, 西城] 的两段都被跳过，图里东城与西城不相连；只要两地各自还有别的通路，
  它们就都在已知网络里，提醒便断言“地图记录过这两地之间的通路，但当前有效的通路网络未连通”。这与
  地图自己的声明矛盾，违反 ADR-0037“只依据明确声明、不能确认时说无法确认”。
- 复现：回归测试构造上述地图（另加北镇、南镇两条邻接），场景从东城移动到西城，提醒出现
  `route_no_active_connection`。对照：同一地图去掉途经点后不再出现（临时测试，已删除）。
- 建议方向：按图元 ID 建图，转移端点再映射到图元；或把未绑定对象的中间点当作透明节点。

### B4-F2（P3）被重算取代的旧阅读运行，持续冒出“上次阅读已暂停”

- 位置：`backend/modules/evolution/reading_notice_sources.py:533` 从新到旧逐个运行查找需要处理的
  运行；`_run_attention`（参数名 `latest`，356 行）对非 active 且未完成的运行一律记为 `stopped`
  （388-393 行）。
- 问题：`scoped_recompute`/`revise` 会新建运行并 drain 原运行（`workflow.py:840-841`）。原运行停在
  中途、新运行完成后，最新运行返回 None，循环继续落到已 drain 的旧运行，提醒“上次阅读已暂停；已完成
  的部分仍保留”。而阅读面板 `reading_status` 只看最新运行，显示已完成；drain 的运行也无法恢复。提醒
  指纹含全部已采用正文的 hash，作者忽略后，任一章正文变化又会重新出现。
- 复现：回归测试插入 drained 的原运行（完成 1/2 场）和已完成的重算运行，`list_reading_notices`
  返回 `evolution.reading:run:reading-original`。
- 说明：跨运行查找本身有意为之（e2e 测试用它跳过截止点之后的较新运行），问题只在已完成或已取代的
  运行没有终止查找。
- 建议方向：遇到覆盖当前范围的已完成运行即停止查找，或跳过 drained 运行。

### B4-F3（P3，未写测试）问世界打开地图引用时不带原排除项

- 位置：`backend/modules/world/services/worldbuilding/ask_world_service.py:312-353` 重读简报时只传
  scene、章节、问题和 `author_safe`，没有传原问答的排除项；`AskWorldCitation` 也没有保存它们。
- 问题：作者在确认问答 Context 时排除了某个对象（或节点的上游资料），原简报内容不含相关图元；打开
  引用时重读的内容包含它们，`content_hash` 不同，引用被标成“已变化”，正文里还出现作者排除过的资料。
- 未写测试：修复需要给引用新增排除项字段，测试只能按假设的字段形状写，容易误报。
- 建议方向：引用里保存原排除项（或 confirmation id）并在重读时传入。

## 观察（未定为问题）

- `world.object_validity` 对每个带有效期但没有 Story 对应的地图声明、档案条目和关系都出一条“暂不可
  核实”的缺口提醒（`docs/modules/02_world.md:114` 规定投影冲突和缺口）。B3-F4 会把线索有效期复制到
  地点上，提醒数量会被放大，上限 100 条。
- `writing.conflict` 条目提醒的指纹含当前正文 hash 与地图过期状态，作者的“稍后/保留”处置在每次
  保存正文后失效、重新显示为未读；“忽略”经领域适配器写回条目，不受影响。可能是有意的“依据变化即重开”。
- 阅读提醒的依据文案直接拼内部状态（`阅读当前状态：stopped`），显示在“查看依据”折叠区
  （`frontend-console/vue/views/writing/components/UnifiedNoticesPanel.vue:54-57,349`）。
- 简报接受 working 模式的原文来源，提醒只接受 canonical，两者口径不一致。
- 简报：类型检查跳过的通路仍把来源 hash 计入条目（只会让过期判断更保守）；只有歧义移动位置的节点会
  产出各列表均为空的条目。
- 提醒：同一文档两个图元绑定同一对象时，`endpoint_features` 以后者为准。
- loader 从不产生 `map_atlas_revision` 排除；简报把未知 kind 整串放入 excluded_nodes，无害。
- 换用其他消费动作物化 confirmation 时，即便确认时没有地图，也会追加空间简报；排除项照常生效，
  符合“领域 overlay 可追加本域执行资料”。
- 节点合并后图元 ID 与节点身份改变，绑定在来源节点声明上的 Story 状态不随之迁移，读取时退回作者区间。

## 回归测试

- `backend/modules/world/tests/test_map_series_review_regressions.py`：新增 B4-F1
  （`test_b4_route_through_text_only_waypoint_is_not_reported_disconnected`）。
- `backend/modules/evolution/tests/test_map_series_review_regressions.py`：新增 B4-F2
  （`test_b4_superseded_drained_run_does_not_raise_a_reading_notice`）。
- 验证（在 `backend/` 下）：两个文件正常模式 `16 xfailed`；加 `--runxfail` 为 `16 failed`，新增两条分别
  失败在 `route_no_active_connection` 断言与 `reading-original` 提醒断言。ruff format/check 通过。
