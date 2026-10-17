# 第 1 批：M0 空间模型 v2 与项目词表

审查基线：`codex/map-enhancement-plan` @ `a479e006b`（merge-base `00d861283` = origin/main）。
规格：`docs/plans/2026-10-15-map-system-enhancement.md`、ADR-0035。

## 结论

M0 的数据库层、鉴权并发、几何指纹兼容和类型引用校验均符合规格，未发现安全或数据隔离问题。
发现 1 个 P2（合并类型后地图计算退化，已用临时测试复现）、1 个 P3（助手预览与服务端去重口径
不一致）。另有 2 个疑点转入后续批次核对。

## 已审范围

- migration：`20261015_map_spatial_v2.py`、`20261015_project_vocabulary.py`、`20261015_map_draft_superseded.py`
- `backend/modules/world/project_vocabulary_{models,schemas,service,api}.py`（service 全文）
- `map_structure_schemas.py`、`map_structure_geometry.py`、`map_structure_service.py` 的 diff，以及
  `reader_preview`、`canonical_map_feature_ids`
- `map_spatial_anchors.py`；`map_atlas_{service,schemas,api}.py` 的 diff
- `assistant_vocabulary_tools.py`（全文）

## 确认无问题

- 同 novel 复合外键齐全；只追加触发器经 `%I.projects` 与 `TG_TABLE_SCHEMA` 判断父项目已删，项目永久
  删除走 `ProjectRepository.permanent_delete` 的 CASCADE，不会被触发器误拒；降级前检查数据。
- 读走 `require_active_project`，写走 `require_active_project_exclusive`（拒演示项目，加排他项目锁），
  同项目词表写入串行。
- `geometry_hash` 约束按 v1 字段白名单计算，`space_id` 仅在存在非 main 空间时计入，有金标测试
  `backend/modules/world/tests/test_map_geometry_hash_v1.py`；v1 文档保存时升 v2。
- `calculable_features`/`diagnose`/`layout` 只算 `event_observed`、无生效区间、类型可计算的条目；多空间
  分别布局；route 上限计数正确。
- `resolve_spatial_vocabulary_references` 校验同项目、精确修订和种类；读者预览经
  `canonical_map_feature_ids` 排除候选对象绑定；`validate_document` 接受 canonical/candidate/draft 绑定，
  与 ADR-0036 §8 一致。
- 锚点融合替换（起点取最早、终点取最晚）、锚点删除、顺序倒置均标记待核对，符合 ADR §2。
- 地图册查询排除已合并节点；`level_type` 服务层校验 + DB 外键兜底。
- 预设各 13 项；助手单次确认上限 20 项，混搭预设可能被拒并提示拆分，属已声明限制。

## 发现

### F1（P2）作者合并词表类型后，引用旧类型的地图图元退出空间计算

- 位置：`backend/modules/world/map_structure_service.py:107-130`（`computable` 仅认 `status == "active"`），
  上游 `backend/modules/world/project_vocabulary_service.py:1132` `resolve_vocabulary_type_revisions` 返回
  词条**当前**状态；`map_structure_geometry.py:70` `_feature_geometry`。
- 问题：ADR-0035 §4 规定“被合并的 ID 保留重定向”，“按文字显示并提示作者”只针对归档。实现中 `merged`
  与 archived 同样被判不可计算，地图侧没有任何 `redirect_to_id` 处理。作者把类型 A 合并进 B 后，所有
  固定引用 A 修订的地点、关系都退出布局、诊断、读者预览和空间简报，只留下
  `spatial_type_not_computable`，作者只能逐条重设类型。
- 复现（临时测试，跑完已删除，未提交）：A、B 均为 `geometry=["point"]` 的 feature 类型，关系类型带
  `compass`；文档中 a 标为在 b 北方但坐标在南。合并前 `preview_layout` 报 `['direction_conflict']`，
  `merge_project_vocabulary_terms(A→B)` 后同一请求报
  `['spatial_type_not_computable', 'spatial_type_not_computable']`，方向冲突不再被检出。
- 触发面：合并只经作者 API（`project_vocabulary_api.py:146`）或作者确认后的助手工具
  （`assistant_vocabulary_tools.py:443`）触发，未实现模型自动合并。
- 建议方向：解析 merged 时沿 `redirect_to_id` 取目标当前修订的 traits 参与计算（或在合并预览中提示并
  提供批量改引用）；补“合并后仍可计算”的回归测试。

### F2（P3）助手词表去重与服务端口径不一致，预览通过、确认时冲突

- 位置：`backend/modules/world/assistant_vocabulary_tools.py:156-176` `_ensure_unique` 沿合并链把比对对象
  换成**目标**词条的键；`backend/modules/world/project_vocabulary_service.py:340-359`
  `_ensure_unique_keys` 比对的是墓碑词条**自身**快照的键。
- 场景：A 合并进 B 后，作者从 B 删掉 A 的旧名别名，再让助手新建与 A 同名的类型。助手预览认为不冲突，
  作者确认后服务端以 ConflictError 拒绝。失败关闭，不写坏数据，只是预览不可信。
- 建议方向：助手侧复用服务端口径（同时比对墓碑自身键），或预览直接调用服务端只读校验。

## 转入后续批次的疑点

- Q1（第 2 批）：`map_spatial_clue_service._validate_type_proposal`（约 640–700 行）要求同名模型词条再次
  提议时 `proposal_run_id` 相同且包含此前全部证据。需核对新演化运行或 append 再次提议同名类型时，
  `evolution/spatial.py` 是降级复用已有 ID，还是让该 Scene 失败；以及复核未通过把已 active 的模型词条
  降回 emerging 是否符合预期。
- Q2（第 3/4 批）：`reader_preview` 中只有 `author_decision`、没有 sources 的行程，`all([])` 为真且无
  `reader_from_chapter` 门槛，两端地点对读者可见时即进入读者预览。需核对助手或作者安排行程的默认
  modality；若默认 `event_observed`，作者计划可能提前透露给读者。

## 附注（不计入发现）

- `_layout_single_space` 遇到作者改为非 `event_observed` 的已生成 route 图元、而其约束仍可计算时，
  会用默认字段的新 route 覆盖原图元。场景极少，未复现。
