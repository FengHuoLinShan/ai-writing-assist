# 第 3 批：M2 自动草图与地图编辑

审查基线：`codex/map-enhancement-plan` @ `a479e006b`（merge-base `00d861283` = origin/main）。
规格：ADR-0035、ADR-0036 §7、`docs/modules/15_map.md`（助手消费、已保存节点合并、读者投影）。

## 结论

草图的层级优先级、canonical 引文定位、采用时的来源重验、分片续跑、托盘放置 CAS，以及节点合并的
预览/执行/撤回门禁，都与规格一致。没有发现跨 `novel_id` 访问或绕过 owner 的路径。共发现 4 个 P2、
2 个 P3：

- 被拒绝的线索会回到托盘；
- 同一地点存在规划节点时，草图会挂错节点；
- 拒绝一条线索会冻结整个批次；
- 带时效的关系会把两端地点移出布局；
- 旧版 v1 地图上，助手的结构编辑无法使用；
- 第 1 批疑点 Q2 确认：只有作者安排的行程会进入读者预览。

6 项都已写成 strict xfail 回归测试并用测试复现。

## 已审范围

- `backend/modules/world/map_auto_draft_service.py`（全文）、`map_node_merge.py`（全文）、
  `assistant_map_tools.py`（全文，diff 1029 行）、`map_progression_state.py`（全文）、
  `map_notification_service.py`（全文）、`map_assistant_read_service.py`。
- `backend/modules/assistant/guided_flow/map_cold_start.py`，以及 `guided_flow/runtime.py` 的
  选择停点门禁。
- `map_structure_service.reader_preview`、`save` 的 v1 升级、`node()` 的墓碑 409；
  `map_structure_review.changed_items`；`MapDocument` 的校验器。
- 所有过滤 `merged_into_node_id` 的读取方（atlas、简报、提醒、通知、进度、助手读取、地图链接、
  冷启动、预测）。

## 确认无问题

- 草图：层级优先级与 ADR 一致，冲突只标记不覆盖，循环父链被丢弃；`_unique_canonical_source`
  精确定位 canonical 引文；采用时重验来源线索，按 canonical 引文收窄，失效实体降级为文字；实体融合
  的重定向字段 `content_json["merged_into"]` 与读取侧一致；`_process_batch` 每次最多 20 个分片，
  带游标续跑，并重验依赖指纹与 head；托盘放置有预览指纹和基线 CAS，重放幂等，作者坐标锁定。
- 自动草图路径向 `_revalidate_stored_clue` 传 `allow_identity_transitions=True`，不受 B2-F5 影响；
  B2-F5 只影响 `review_spatial_clue`。
- 节点合并：预览覆盖规格列出的全部阻止条件（子节点、待审草图、图片页、标注绑定、入向子图/标注跳转、
  在途自动草图/托盘/任务/地图册运行、多跳合并、200/400/20 上限）；执行时按 UUID 顺序锁定两端，
  重算指纹，用 head + `updated_at` 做 CAS，回执也经 CAS 写入；撤回检查来源墓碑、来源 head、目标合并
  head、回执与 `change_summary` 一致，并追加恢复 revision，不改写历史。`_combine_documents` 把空间、
  图元、关系、行程 ID 稳定重映射到独立空间，v1 目标补主空间。指向墓碑的子图跳转在保存时由
  `node()` 抛出 `map_node_merged`，失败关闭。
- 助手操作：每个 apply 都重算预览并比对；目标经 `ASSISTANT_REQUIRE_OPERATION_TARGETS` 门禁；
  局部 Scene 范围拒绝整图编辑；结构编辑从当前 run 绑定的作者消息读取 `author_decision`，预览与确认
  时都重验；合并复用服务端指纹，`map.preview_node_merge` 只生成候选，不改节点。
- `map_progression_state`：只消费当前采用节点的 saved head 中有逐字来源的 `event_observed` 行程，
  按 cutoff 检查有效期、来源和端点 canonical 状态，角色路线逐条检查 Evidence 可见性；与 15_map.md
  的 Story C5 契约一致。
- 冷启动流程：运行时按当前停点门禁选择输入；授权绑定核对演化实际请求与冻结预览的指纹和范围，
  补扫核对请求 hash；流程不代为确认费用。
- 通知：批次信号只计 `pending_review/adopted` 的线索，按 Context 排除过滤线索、端点、来源稿、类型
  与 revision。

## 发现

### B3-F1（P2）隐式构建范围不过滤线索状态，被拒绝的线索回到托盘

- 位置：`backend/modules/world/map_auto_draft_service.py:178` `_load_build_rows` 在
  `clue_ids is None` 时只按 run 与 Scene 截止过滤，不看状态。`backend/modules/evolution/spatial.py:1193`
  `request_spatial_auto_drafts` 总是传 `clue_ids=None`，而注释写的是“World 只查询合格、已复核的线索”。
- 问题：被拒绝的线索在 `_validated_clue_inputs`（278）中抛出“空间线索不再处于可审状态”，被归为
  `source_stale`，两端地点进入托盘；放置时又被 `_placement_document`（2406）以“线索已拒绝、合并或
  失效”拒绝，只能永久留在托盘。`redo_map_auto_drafts`（2296）会带上 `plan.clue_ids` 全集，重做后
  问题依旧。被拒和被取代的线索还计入 `MAX_MAP_BUILD_CLUES`。通知服务按 `pending_review/adopted`
  过滤，构建侧却不过滤，两边口径不一致。
- 复现：拒绝一条线索后以 `clue_ids=None` 构建，托盘出现 `['source_stale', 'source_stale']`。
- 建议方向：隐式范围只加载 `pending_review/adopted`（以及有意保留的 `pending_verification`），
  重做时剔除已结束审核的线索。

### B3-F2（P2）同一地点同时有采用节点和规划节点时，草图挂到规划节点并改写其层级

- 位置：`map_auto_draft_service.py:566` `_ensure_location_nodes`，590 行 `order_by(MapAtlasNode.status.desc(), ...)`。
- 问题：按字符串降序时 `provisional` 排在 `adopted` 前面。`map_atlas_nodes` 对 `location_entity_id`
  没有唯一约束，`map_atlas_workflow.py:1254` 会为地图册规划创建带地点绑定的 provisional 节点。
  同一地点两种节点并存时，草图候选落在 provisional 节点上，并把它的 level 从 district 改为 region、
  parent 改为 None。这与 ADR-0036 §7“针对已保存节点的新线索…以已保存版本为基础”不符。
- 复现：先建作者采用的“西岸”节点，再加一个同地点的 provisional 规划节点，构建后候选挂在规划节点上，
  规划节点层级被改写。
- 建议方向：显式按 `adopted` 优先排序（`case`），不要依赖字符串顺序；只在没有采用节点时才认领
  provisional 节点。

### B3-F3（P3）拒绝一条线索会冻结整个批次，无关节点的候选也不能采用

- 位置：`map_auto_draft_service.py:1410` `invalidate_auto_drafts_for_clue` 把整个批次标为 stale；
  `prepare_auto_draft_adoption`（1209，1236 抛错）要求批次状态为 completed。
- 问题：拒绝一条线索后，同批次中与它无关的节点候选报 ConflictError“自动草图批次未完成或已经失效，
  请重新生成”。ADR-0036 §7 写的是“重做该分片”。影响会传到助手的按组审核（`stale` 时拒绝）和冷启动
  流程（`batches_ready` 变为 False，提示“尚未完整就绪”）。
- 复现：两条线索落到两个节点，拒绝其中一条后采用另一个节点的候选，抛出上述 ConflictError。
- 建议方向：只把依赖该线索的分片和候选标为 stale，批次保持 completed；或采用时按分片依赖判断。

### B3-F4（P2）带时效的关系线索把区间复制到两端地点，地点被移出布局

- 位置：`map_auto_draft_service.py:1528` `_auto_draft_document`（1580 行起的 `feature_effective`，
  1653 行写入图元）把任意线索的 `attributes.effective` 复制到两端地点图元上；`_placement_document`
  （2492）也一样。`map_structure_geometry.py:109` `calculable_features` 排除带 `effective` 的图元。
- 问题：两端地点都没有坐标，进入托盘 `placement_failed`，可计算图元数为 0，没有区间的普通连接也
  画不出来；之后每次增量构建都因 `incremental_placement_failed` 重做。线索种类中有专门的
  `effective_change`，按 ADR-0035，图元、关系、行程各自携带区间。
- 复现：一条带区间的连接加一条普通连接，构建后两端地点都带区间，托盘出现 `placement_failed`。
- 建议方向：区间只写到对应的关系或行程，地点只接受 `effective_change` 线索的区间。修复时同步现有
  测试 `test_drafts_keep_effective_range_and_exact_citation`，它目前断言地点图元带区间。

### B3-F5（P3）旧版 v1 地图上，助手无法新增空间、行程或带类型的关系

- 位置：`backend/modules/world/assistant_map_tools.py:243` `_document` 直接加载 head；
  `_structure_edit_preview` 在 900 行 `MapDocument.model_validate(...)` 前不做升级。
- 问题：迁移 `20261015_map_spatial_v2.py` 不改写已存 revision，M0 之前保存的地图 head 仍是
  `schema_version: 1`。工作台保存（`map_structure_service.py:735`）、自动草图（1560）和节点合并都会
  把 v1 升级为 v2，只有助手结构编辑不升级。于是新增空间、行程或带类型的关系时抛出 pydantic
  ValidationError（英文消息“v1 documents cannot contain v2 spaces or journeys”），而不是领域错误。
  旧地图只能先在工作台保存一次才能用助手编辑。
- 复现：节点 head 为 v1 文档时，`map.edit_spatial_structure` 的 `add_space` 预览抛出上述错误。
- 建议方向：`_document` 或结构编辑前按 `save` 的同一规则把 v1 升级为 v2。

### B3-F6（P2，第 1 批 Q2）只有作者安排的行程进入读者预览

- 位置：`backend/modules/world/map_structure_service.py:1427`，`reader_preview` 用
  `all([... for source in journey.sources])` 判断行程来源；`sources` 为空时 `all([])` 为真。
- 问题：15_map.md 规定读者投影中的行程“必须通过端点揭示、逐字来源和所引用类型状态检查”。只带
  `author_decision`、没有引文的行程（助手结构编辑写入的行程都是这种）只要两端可见，就会连同交通方式、
  耗时、距离和通行条件出现在读者预览中，提前透露作者尚未写进正文的安排。
- 复现：两端在第 1 章可见，一条有引文的渡船行程加一条只有作者安排的“地下暗道”行程，第 1 章读者
  预览返回两条行程。
- 建议方向：没有逐字来源的行程不进入读者投影（与 `map_progression_state` 的
  `journey_source_missing` 口径一致）。

## 观察与转入后续批次的疑点

- 第 4 批：15_map.md 要求空间简报和空间提醒按“不可变合并版本中的来源节点及确切来源修订”保留
  Context 排除，目标吸收被排除来源时整体省略。合并后图元 ID 改写为 `m<来源>_f_<摘要>`，需在
  `map_spatial_brief_service`、`map_spatial_advisory_service` 核对这条边界。
- 第 1 批 F1 的影响还包括 Story 路线：类型合并后，`map_progression_state` 把引用旧类型的行程记为
  `journey_type_unavailable`。
- 助手按“空间”分组审核时，`scope_id` 只是空间 ID，不带节点；`main` 会匹配所有节点的候选。预览按
  节点列出且受 20 项上限约束，作者能看到，所以只记为体验问题。
- 节点合并要求两份文档的文档级 `author_decision` 相同，而助手结构编辑会给整份文档盖上作者安排。
  经助手编辑过的地图不能与手工保存的地图合并，这是保守限制。合并后空间超过 20 个时只给出笼统的
  “地图内容无法安全合并”。
- 冷启动：运行没有产生任何草图批次时，流程停在“空间草图尚未完整就绪”，无法完成。
- `map_notification_service` 在 `_revalidate_stored_clue` 外只捕获 Conflict/NotFound/Validation
  三种领域错误，`review_spatial_clue` 还捕获 ValueError/TypeError；schema 异常会中断通知读取。
- 小问题：失效图元的 note 以换行开头；`preview_map_auto_draft_tray_placement` 走读门禁，却对行加
  `FOR UPDATE` 锁。

## 回归测试

都在 `backend/modules/world/tests/test_map_series_review_regressions.py`，每项一条
`pytest.mark.xfail(strict=True)`：

- `test_b3_rejected_clue_has_no_tray_effect_in_implicit_build`（B3-F1）
- `test_b3_auto_draft_targets_the_adopted_node_for_a_place`（B3-F2）
- `test_b3_rejecting_a_clue_only_blocks_the_shard_that_depends_on_it`（B3-F3）
- `test_b3_bounded_relation_does_not_unplace_its_endpoints`（B3-F4）
- `test_b3_assistant_structure_edit_upgrades_a_legacy_v1_map`（B3-F5）
- `test_b3_reader_preview_omits_journeys_without_verbatim_sources`（B3-F6）

验证：两个回归文件正常模式 `14 xfailed`。加 `--runxfail` 时 `14 failed`，每条都失败在对应位置：
B3-F1 托盘为 `['source_stale', 'source_stale']`，B3-F2 节点 ID 不符，B3-F3 在
`map_auto_draft_service.py:1236` 抛 ConflictError，B3-F4 地点带 `SpatialValidity`，B3-F5 在
`assistant_map_tools.py:900` 抛 pydantic ValidationError，B3-F6 多出 `secret-tunnel`。
