# Module: map / 动态地图子系统

## 定位

动态地图是 `world` 模块的子系统，不是独立后端模块。

- 后端文件位于 `backend/modules/world/`
- API 前缀为 `/api/world/maps`
- 当前前端主入口是一级路由 `map`（`mapWorkspaceView`）
- `world` 里的 `map` 子标签只保留兼容跳转

**设计来源**：[`map-prd-v1.1.md`](../references/map-prd-v1.1.md)；当前代码已覆盖地图基础 P0-P2、世界动态 P0/P1，并提供类型化 Scene 状态、差分、连续性检查和 P3 只读播放。

---

## 功能总览

| 阶段 | 功能 | 状态 | 后端 | 前端 |
|------|------|------|------|------|
| P0 | 世界地图 / 城市 / 区域 / 地下城创建与层级 | ✅ | `MapConfigService` | `mapWorkspaceView.js` + `mapView.js` |
| P0 | 六边形地形网格初始化与批量编辑 | ✅ | `MapTileService` | 画笔 / 油漆桶 / 应用 |
| P0 | 地点绑定（location 实体 → 一个或多个 hex） | ✅ | `MapLocationBindingService` | 绑定工具 |
| P0 | 地图聚合状态（map + breadcrumbs + tiles + bindings） | ✅ | `MapConfigService.get_state` | 主视图 |
| P0 | 详图快速生成（中心 city + 外 road） | ✅ | `MapConfigService.generate` | 编辑工具栏 |
| P0 | 快速创建地图预览与地点多选落库 | ✅ | `MapQuickCreateService` | `mapQuickCreateView.js` |
| P0 | 地图子树归档/恢复与 active 名称唯一 | ✅ | `MapArchiveService` | 地图总览归档列表 |
| P0 | 视觉 revision CAS 与原子批量保存 | ✅ | `MapEditorApplyService` | 应用当前图层 / 保存全部 |
| P0 | 地图 Observation/Fact 证据与事实底座 | ✅ | `MapDynamicFactService` | 待处理/已采用动态事实摘要 |
| P1 | 世界动态总控台（首屏层 / 动态队列 / 检查器 / 批量分组） | ✅ | `MapDynamicFactService.get_dashboard` | 工作台右侧总控台 |
| P1 | 统一地图打开目标（写作页 / 世界对象页 / 默认地图入口） | ✅ | `GET /open-target` | `writingView.js` / `worldView.js` / `mapWorkspaceView.js` |
| P1 | 对象信息框与检查器聚焦 | ✅ | dashboard queue / inspector 扩展字段 | 动态队列、语义气泡、播放事件统一打开信息框 |
| P1 | 待处理批量动作与事实状态修改 | ✅ | `POST /{map_id}/batch-actions` | 批量采用、忽略、标记冲突、软更新 fact 状态 |
| P1 | Scene 时间层与动态标记（character/event/item） | ✅ | `MapMarkerService` | Scene 导航 + 标记工具 |
| P2 | 组织势力范围（territory tiles） | ✅ | `MapTerritoryService` | 势力范围工具 |
| P2 | 聚焦模式（按组织过滤势力范围） | ✅ | `GET /{map_id}/focus` | 聚焦按钮 |
| P2 | 写作页 Scene 地图摘要 | ✅ | `GET /scene-summary` | `writingView.js` |
| P2 | 自动布局、避让、聚合簇 | 部分实现 | 复用 dashboard / state 契约 | `mapLayoutEngine.js` + `mapView.js`；仍缺少路线/危机区等高级避让 |
| P2 | 总控台 / 活地图 / 叙事透镜三视图 | 部分实现 | 同一套地图事实 | `mapWorkspaceView.js`；当前是视图模式入口和焦点权重 |
| P2 | 递归图层树与继承显隐/锁定/透明度/缩放 | ✅ | `MapLayerTreeService` | 递归图层面板 |
| P2 | 独占组、楼层组与临时隔离 | ✅ | 图层树保存模式/楼层结构 | route + localStorage 会话选择 / isolate |
| P2 | 连续道路与水系、端点吸附和节点精修 | ✅ | `MapPathService` | `mapPathRenderer.js` + path 编辑层 |
| P2 | 世界对象多地图 presence 与双向定位 | ✅ | `MapEntityPresenceService` | 地图选择器 / typed selection |
| P2 | 上方语义气泡带与低动效模式 | 部分实现 | 同一套动态队列 | `mapWorkspaceView.js` + `mapLayoutEngine.js` |
| P3 | typed observations、Scene 状态与确定性差分 | ✅ | `GET /{map_id}/timeline`、`/{map_id}/state-at` | Scene 游标、正式状态、candidate 预览与冲突分区 |
| P3 | 人物旅程 / 势力变化 / 危机推进 / 资源控制 / 状态变化轨道 | ✅ | `MapTimelineService` + 兼容 playback | 差分轨道、只读 Canvas 覆盖与空间连续性面板 |
| P3 | AI 位置建议 | ❌ | 未建表 | 未实现 |
| P3 | 既有 Scene 地图事实补充 | ✅ | imports 独立 task + world candidate seam | 地图总览章节范围、高质量模式、可恢复进度与候选复核入口 |
| P4 | 地图缩略图 / 图片底图 / 伪 3D | ❌ | 未规划 | 未实现 |

---

## 数据模型

所有地图表均含 `novel_id` 字段，查询强制按 `novel_id` 隔离。

### `map_configs` — 地图配置

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID PK | |
| `novel_id` | UUID FK → projects | 项目隔离 |
| `name` | VARCHAR(255) | 地图名称 |
| `map_type` | VARCHAR(32) | `world` / `city` / `region` / `dungeon` |
| `description` | TEXT | 描述 |
| `default_center_x` / `default_center_y` | FLOAT | 默认视口中心（0~1） |
| `default_zoom` | FLOAT | 默认缩放层级 |
| `grid_width` / `grid_height` | INT | 网格尺寸（1~200） |
| `hex_size` | INT | 六边形像素半径（默认 30） |
| `parent_map_id` | UUID FK → map_configs | 自引用层级，`NULL` 为顶层 |
| `parent_entity_id` | UUID FK → core_entities | 详图对应的 location 实体 |
| `sort_order` | INT | 同层级排序 |
| `status` / `archived_at` | VARCHAR / TIMESTAMPTZ | `active` / `archived` 与归档时间 |
| `editor_revision` | INT | 地图视觉资产的乐观锁版本 |

**约束**：
- active 子地图使用 partial unique `(novel_id, parent_map_id, name) WHERE status='active' AND parent_map_id IS NOT NULL`；active 根地图使用 `(novel_id, name) WHERE status='active' AND parent_map_id IS NULL`。归档历史可与新地图同名。
- `parent_entity_id` 必须是同 novel 的 `location` 类型实体。
- 作者入口不硬删除已采用地图。归档/恢复锁定整棵子树并在单事务修改状态，资产和父子关系保持不变。

### `map_tiles` — 六边形地形

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID PK | |
| `novel_id` / `map_id` | UUID FK | 隔离与级联 |
| `hex_q` / `hex_r` | INT | 轴向坐标（0 起始） |
| `terrain_type` | VARCHAR(32) | 地形白名单见下 |
| `elevation` | INT | 海拔（默认 0） |
| `style_override` | JSONB | 样式覆盖 |

**地形白名单**：`grassland`, `forest`, `desert`, `mountain`, `water`, `city`, `road`, `ruin`, `secret`, `danger`。

**坐标约定**：
- 后端只存 `(q, r)`，第三坐标 `s = -q - r` 由前端计算。
- `hex_q` 范围 `[0, grid_width)`，`hex_r` 范围 `[0, grid_height)`。
- `UNIQUE(map_id, hex_q, hex_r)`，批量编辑走 `INSERT ... ON CONFLICT DO UPDATE`。

### `map_location_bindings` — 地点绑定

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID PK | |
| `novel_id` / `map_id` | UUID FK | 隔离与级联 |
| `location_entity_id` | UUID FK → core_entities | 必须 `entity_type = "location"` |
| `hex_q` / `hex_r` | INT | 绑定格 |
| `is_center` | BOOLEAN | 是否中心点（显示标签 + 下钻入口） |
| `label_override` | VARCHAR(255) | 标签覆盖 |
| `style_override` | JSONB | 样式覆盖 |

**约束**：
- `UNIQUE(map_id, location_entity_id, hex_q, hex_r)` 防止同一地点重复绑定同一格。
- 同一地点在同一地图最多一个 `is_center = true`（业务层 `clear_center` 保证；PG 部分唯一索引 `ix_map_binding_center` 在 Alembic 中声明）。

### `map_location_layouts` — 地点布局节点

`map_location_layouts` 把地点在地图上的编辑布局与原始绑定分开保存，字段包括
`map_id`、`location_entity_id`、中心 hex、占用半径、锁定状态、布局来源、版本、
`sync_geo_setting` 与扩展 `meta`。同一地图内每个地点最多一条布局记录；它服务快速创建、
拖拽与布局恢复，不替代 `map_location_bindings` 的地点→hex 事实绑定。
布局写入只接受已采用地点；默认列表隐藏关联待处理或归档地点的遗留布局，
聚合状态只把 draft/candidate owner 的遗留布局放入显式 candidate 分层。

### 地形图层与区域

手绘地形不是 `map_tiles.style_override` 的临时前端数据，而是以下四张 world 拥有的表：

| 表 | 用途 |
|---|---|
| `map_terrain_layers` | 地图上的命名地形图层，保存素材、透明度、层级、显隐与锁定状态。 |
| `map_terrain_regions` | 图层中的可命名连续区域与区域状态。 |
| `map_terrain_patches` | region 覆盖的离散 hex 及强度/笔刷来源。 |
| `map_terrain_bindings` | region 与地点的用户确认绑定，记录 binding 类型、复核状态、来源和 metadata。 |

这些表均按 `novel_id` 和 `map_id` 隔离。图层/区域/patch 的增删改由
`MapTerrainService` 原子处理，前端不能只改本地画布后假定持久化已完成。
地形绑定的正式写入与更新必须关联已采用地点；默认读取只返回
`review_state="confirmed"` 且 owner 为 canonical 的绑定，显式
`include_candidates=true` 才返回 `candidate_bindings`。

`map_tiles` 是 `baseTerrain` 正式底图；上述四表是 `terrainOverlay` 覆盖层。
覆盖层按 `(z_index, created_at, id)` 升序渲染，高层后绘制。锁定层拒绝绘制、
覆盖保存和删除；素材包只写覆盖层 metadata，不修改底图 tile。

### `map_layer_nodes` — 递归图层树

`map_layer_nodes` 是图层局部 `visible/locked/opacity/sort_order/min_zoom/max_zoom`
的唯一权威。允许多个顶层 group，最大深度 8；底图、地点、人物/事件/物品标记、
领地、覆盖素材组、连续线路组和待处理预览是必须且唯一的 singleton，每个 terrain layer
和 path layer 必须且只能对应一个 leaf。

有效显隐取祖先逻辑与，锁定取祖先逻辑或，透明度沿祖先链相乘，zoom 取区间交集；
空交集不可见。`map_terrain_layers.visible/locked/opacity/z_index` 只是兼容投影，
树写入后按 DFS 顺序在同一事务内重算。

group 可设置 `selection_mode=normal|exclusive|floor`；floor 的直接子节点使用唯一
`floor_level`。当前 active child 与 isolate 不入库：路由值优先于按 novel/map 隔离的
localStorage，嵌套组沿全部祖先选择共同决定会话有效可见性。隐藏、zoom 外或锁定的当前子层
不会被自动替换，前端会解释空画布原因。

### 连续线路

| 表 | 用途 |
|---|---|
| `map_path_layers` | transport / water 线路容器；显示名称与图层属性由对应 tree leaf 拥有。 |
| `map_paths` | 道路/水系、样式、起止地点、active/archived 生命周期与 `content_revision`。 |
| `map_path_nodes` | 有序浮点轴向坐标、逐节点宽度、张力和出向分段类型。 |

线路使用 Canvas 连续覆盖层，hex 仍是地图范围和地点吸附权威。每条线路 2–500 个节点，
每张地图最多 500 条线路和 20,000 个节点；起止地点只能关联同项目 canonical location，
但地点未布置时可保持 unresolved 语义端点。地点移动不静默改写线路，用户必须显式重新吸附。
线路本体只归档，含 active 或 archived 线路的 layer 不可删除。

### `map_markers` — 动态标记（P1）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID PK | |
| `novel_id` / `map_id` | UUID FK | 隔离与级联 |
| `entity_id` | UUID FK → core_entities | 关联实体（任意类型） |
| `marker_type` | VARCHAR(16) | `character` / `event` / `item` |
| `hex_q` / `hex_r` | INT | 标记坐标 |
| `offset_x` / `offset_y` | FLOAT | 偏移（避免同格重叠，范围 [-1, 1]） |
| `label` | VARCHAR(255) | 标签 |
| `style_json` | JSONB | 样式 |
| `start_scene_id` / `end_scene_id` | UUID | Scene 时间锚点（**无数据库 FK 到 outline.scenes**） |
| `start_scene_index` / `end_scene_index` | INT | 排序冗余 |
| `visible` | BOOLEAN | 是否可见 |

**说明**：`start_scene_id` / `end_scene_id` 不建 FK 到 `outline.scenes`，业务层通过 `SceneService.get()` 校验；避免跨模块 ORM 强耦合。

### `map_territory_tiles` — 势力范围（P2）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID PK | |
| `novel_id` / `map_id` | UUID FK | 隔离与级联 |
| `faction_entity_id` | UUID FK → core_entities | 必须 `entity_type = "organization"` |
| `hex_q` / `hex_r` | INT | 范围格 |
| `style_override` | JSONB | 颜色 / 透明度覆盖 |

**约束**：`UNIQUE(map_id, faction_entity_id, hex_q, hex_r)`。

### `map_observations` — 地图观察层（世界动态 P0）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID PK | |
| `novel_id` | UUID FK → projects | 项目隔离 |
| `map_id` | UUID FK → map_configs, nullable | 未解析空间时可为空 |
| `target_entity_id` | UUID FK → core_entities, nullable | 未消歧时可为空；不得存入跨 novel 引用 |
| `target_entity_type` / `target_name` | VARCHAR | 作者界面优先显示名称和类型文案 |
| `dynamic_type` | VARCHAR(64) | `location` / `status` / `boundary` / `crisis` / `resource` / `semantic` / `delta_event` 等 |
| `time_anchor` / `spatial_anchor` | JSONB | Scene/章节/地图/hex/地点等锚点 |
| `value_json` | JSONB | 观察到的状态或值 |
| `confidence` | FLOAT | 置信度 0~1 |
| `review_state` | VARCHAR(32) | `candidate` / `confirmed` / `ignored` / `conflicted` |
| `source_ref` | JSONB | 来源引用，如 `delta_log_id`、`context_snapshot_id` |
| `evidence_text` | TEXT | 可读来源证据摘要 |
| `scene_id` / `scene_index` / `source_chapter_index` | UUID / INT | 来源时间锚点 |

`deep import` Phase 2 仍写 `memory.delta_log`。新的地图动态链只接受人物地点、事件地点、
线路状态、势力范围四类显式 proposal，并经稳定 world contract/facade 写入
`map_observations(review_state="candidate")`；旧 `delta_event` → observation 路径仅保留兼容。
候选 UUIDv5 由项目、workflow、Scene、source item 和 proposal type 决定，`source_ref` 保存
Scene 输入指纹、context snapshot、evidence anchor 与原始 payload hash。同一重试复用；身份相同
但 payload 改变时 409 fail closed，不覆盖作者字段，也不直接写 Fact。`source_item_key`
继续细分为 Scene 输入指纹 + proposal type + evidence anchor + 同源局部序号，避免同类
proposal 重排导致假冲突。任务提交时的冻结授权快照须跨 imports/world seam 原样携带；
world 验证 novel/章节 scope 并持久化快照指纹。PostgreSQL 用确定性事务锁串行化尚未
存在的候选身份；导入 proposal type 属于不可变来源身份。逐字证据按发布正文 offset 排序，
同一 Scene 内不同位置使用 `time_anchor.scene_sequence` 表达叙事先后；只有相同 Scene 和相同
sequence 的同对象同维度异值才构成同一时刻冲突。

已经完成深度导入的项目可调用 `POST /api/imports/stages/map-observations`，运行独立
`map_observation_enrichment` 任务补充四类地图候选。该路径不调用深度导入 Phase 0/1/2/3，
不修改 Scene、世界对象或剧情结构；它从既有 Scene span 与 published draft 组装一次性、
非重叠正文覆盖，保留 chapter/draft/hash/offset 和唯一逐字证据。名称必须能通过冻结的
canonical 名称或已确认别名词典归一，否则只进入不确定诊断。最终 observation 的
`source_ref.source` 为 `map_enrichment_typed_map_proposal`，始终保持未采用候选。高质量模式固定
执行首轮抽取和第二遍全文完整性审计；非逐字、非唯一、目标未在证据中命名，以及“只离开但
没有可投影到达位置”的结果均由确定性门禁降为诊断。目标/地点名称可唯一归一时写入 canonical
ID；地点在 active 地图中恰有一个中心绑定时自动分配该地图和 hex，否则进入项目收件箱等待
作者选择。无论是否自动分配，都必须由作者复核后才能确认成 Fact。

### `map_facts` — 已采用时间化地图事实（世界动态 P0）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID PK | |
| `novel_id` | UUID FK → projects | 项目隔离 |
| `observation_id` | UUID FK → map_observations, nullable | 来源 observation |
| `map_id` / `target_entity_id` | UUID FK, nullable | 关联地图和对象 |
| `target_entity_type` / `target_name` | VARCHAR | 作者界面显示文案 |
| `dynamic_type` | VARCHAR(64) | 与 observation 一致 |
| `time_anchor` / `spatial_anchor` / `value_json` | JSONB | 已采用事实内容 |
| `confidence` | FLOAT | 来源置信度 |
| `fact_status` | VARCHAR(32) | `confirmed` / `rolled_back` / `deprecated` |
| `source_ref` / `evidence_text` | JSONB / TEXT | 来源引用和证据摘要 |

采用 observation 会生成或复用 `map_facts`；忽略 observation 只更新审查状态，不硬删除观察记录。响应保留 raw `review_state/fact_status`，同时派生 `display_state/source/attention_reasons/suggested_action`；`conflicted` 仍是待处理并附冲突原因。

---

## API 契约

统一前缀：`/api/world/maps`

### 地图管理与摘要

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/?novel_id={}&parent_map_id={}&status={}&skip={}&limit={}` | 分页地图列表；默认只返回 active |
| POST | `/?novel_id={}` | 创建地图，同时按模板生成初始 tiles |
| GET | `/scene-summary?novel_id={}&scene_id={}` | 写作页 Scene 地图摘要 |
| GET | `/open-target?novel_id={}&scene_id={}&focus_entity_id={}` | 统一地图打开目标；返回 `map_id` / `scene_id` / `focus_entity_id` 和 fallback 文案 |
| GET | `/{map_id}?novel_id={}` | 地图详情 |
| PATCH | `/{map_id}?novel_id={}` | 更新地图配置（name / description / 默认视口 / sort_order / parent_map_id / parent_entity_id） |
| DELETE | `/{map_id}?novel_id={}` | 兼容入口：归档整棵子树，保留旧 204 响应 |
| GET | `/{map_id}/archive-impact?novel_id={}` | 返回子树地图数与各类关联资产数量 |
| POST | `/{map_id}/archive?novel_id={}` | 单事务归档完整子树 |
| POST | `/{map_id}/restore?novel_id={}` | 单事务恢复完整子树；`root_name` 只重命名恢复根 |
| POST | `/{map_id}/editor/apply?novel_id={}` | 按 `expected_revision` 原子执行视觉命令 |
| GET | `/{map_id}/layer-tree?novel_id={}` | DFS 图层树与继承后的有效属性 |
| POST | `/{map_id}/generate?novel_id={}` | 快速生成详图地形（仅 `city/region/dungeon`） |
| GET | `/{map_id}/state?novel_id={}&scene_id={}&filter_types={}` | 聚合状态 |
| GET | `/{map_id}/dashboard?novel_id={}&scene_id={}&focus_entity_id={}` | 世界动态总控台：首屏层、动态队列、检查器、批量分组 |
| GET | `/{map_id}/playback?novel_id={}&scene_id={}&focus_entity_id={}&include_candidates={}` | 世界动态播放：typed observation 轨道和播放事件 |
| GET | `/{map_id}/timeline?novel_id={}&from_scene_index={}&to_scene_index={}&focus_entity_id={}&include_candidates={}&skip={}&limit={}` | Scene 时间线：正式差分、冲突、候选预览、未定时间事实与连续性问题 |
| GET | `/{map_id}/state-at?novel_id={}&scene_index={}&focus_entity_id={}&skip={}&limit={}` | 指定 Scene 的正式有效状态和未解决冲突 |
| GET | `/{map_id}/focus?novel_id={}&faction_entity_id={}` | 聚焦模式（仅返回该组织势力范围） |

`dashboard`、`playback`、`timeline` 和 `state-at` 是作者可见的只读派生视图。
`MapFact` 仍是唯一持久化动态事实；`MapDelta`、冲突、连续性问题和 `WorldDynamic` 不回写
数据库。深度导入接入的通用 `delta_event` 必须在这里归一化为对象名、关系名、可读类型和
来源摘要，不能把 `entity_created`、`entities[4]` 或原始 JSON 结构暴露给前端。

`timeline` 默认不包含 candidate，未给范围时使用最近 50 个存在 confirmed fact 的 Scene stop；
显式范围最多跨 500 个 Scene。`timeline/state-at` 默认每页 100、最大 500 条，并通过
`total/has_more` 明示后续数据。旧 `playback` 保持 `include_candidates=true` 的兼容默认值。

### 快速创建

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/quick-create/context?novel_id={}&include_candidates={}` | 获取快速创建上下文，默认只含 canonical/draft 地点，显式开启后包含 candidate |
| POST | `/quick-create/preview?novel_id={}` | 生成可调整预览，不落库、不识别正文、不创建世界对象 |
| POST | `/quick-create/confirm?novel_id={}` | 确认创建地图；同层同名默认 409，只有显式 `replace_map_id` 才替换目标地图的布局、bindings 与 quick-create facts |

world 默认加载全部 canonical 地点；detail/drilldown 默认只加载父地点及通过
canonical `contains/contained_in/located_in` 关系关联的直接子地点，调用方可通过
`location_entity_ids` 显式加入其他 canonical 地点。candidate 只读预览，不得确认保存。
替换复用目标地图类型、网格和父层级，并保留底图、覆盖层、标记与领地。

生成中心确认视觉简报后可在原页面复用同一个 quick-create 对话框；视觉简报只提供作者意图与
来源边界，不改变上述 API payload，也不自动选择或放置地点。打开 context／preview 仍为零写入，
candidate 仍只读；作者在对话框内点击“创建”才进入既有 confirm。当前地图模块不接收、保存或
版本化候选图片，图片细节不能作为 observation、fact 或权威状态来源。

### 原子编辑命令

`POST /{map_id}/editor/apply` 接受 `base_terrain_replace`、地点 layout/binding replace、
terrain layer create/update/delete、terrain patch replace、marker create/update/delete、
territory replace、path layer create/delete、path create/update/archive/restore 和
`layer_tree_replace`。创建命令通过请求级唯一 `client_id` 被后续命令引用，正式 UUID 始终由
服务端生成；每批最多一个 layer-tree replace，涉及图层创建/删除时必须排在这些命令之后。
响应返回正式 ID 映射。单批最多 200 个命令、展开后最多 20,000 个 hex；服务先锁
active map row 并比较 revision，任一命令失败则 savepoint 回滚整批，成功后 revision
只递增一次。旧视觉写入口每次成功也递增 revision。

### 连续线路

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/{map_id}/paths?novel_id={}&status=active|archived|all` | 读取线路图层、线路和节点，并返回 editor revision |
| GET | `/{map_id}/paths/{path_id}?novel_id={}` | 读取单条 active 或 archived 线路 |
| GET | `/{map_id}/paths/{path_id}/archive-impact?novel_id={}` | 归档前查询 Observation / Fact 引用数 |

线路创建、修改、归档、恢复和空图层删除只通过 editor apply。路径节点使用连续 `q/r`，
必须为有限数且落在地图网格范围；单批最多变更 2,000 个路径节点。锁定线路只允许单独解锁，
祖先图层锁定继续阻断全部内容写入。

### 地形编辑

| 方法 | 路径 | 说明 |
|------|------|------|
| PATCH | `/{map_id}/tiles?novel_id={}` | 批量 upsert 地形，`changes` 数组 |

### 地点绑定

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/{map_id}/location-bindings?novel_id={}` | 批量创建绑定 |
| PATCH | `/{map_id}/location-bindings/{binding_id}?novel_id={}` | 更新单个绑定 |
| DELETE | `/{map_id}/location-bindings/{binding_id}?novel_id={}` | 删除单个绑定 |

### 地点布局与手绘地形

| 方法 | 路径 | 说明 |
|---|---|---|
| GET/PUT | `/{map_id}/location-layouts?novel_id={}` | 读取或替换地点布局；PUT 可用 `sync_bindings=true` 同步平移完整 footprint |
| GET | `/{map_id}/terrain?novel_id={}&include_candidates={false|true}` | 读取图层、区域、patch 与绑定；默认只含 active 绑定 |
| PATCH | `/{map_id}/terrain/layers/{layer_id}?novel_id={}` | 只更新请求明确提供的覆盖图层属性 |
| DELETE | `/{map_id}/terrain/layers/{layer_id}?novel_id={}` | 删除已解锁覆盖层并返回级联计数 |
| PUT | `/{map_id}/terrain/layers/{layer_id}/patches?novel_id={}` | 替换一层的 patch 集合 |
| POST | `/{map_id}/terrain/regions/{region_id}/bindings?novel_id={}` | 创建区域与地点绑定 |
| PATCH | `/{map_id}/terrain/bindings/{binding_id}?novel_id={}` | 修改区域绑定复核/metadata |

### 动态标记（P1）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/{map_id}/markers?novel_id={}&scene_id={}` | 标记列表 |
| POST | `/{map_id}/markers?novel_id={}` | 创建标记 |
| PATCH | `/{map_id}/markers/{marker_id}?novel_id={}` | 更新标记 |
| DELETE | `/{map_id}/markers/{marker_id}?novel_id={}` | 删除标记 |

### 势力范围（P2）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/{map_id}/territories?novel_id={}` | 势力范围列表 |
| POST | `/{map_id}/territories?novel_id={}` | 批量创建势力范围 |
| PATCH | `/{map_id}/territories/{territory_id}?novel_id={}` | 更新单格样式 |
| DELETE | `/{map_id}/territories/{territory_id}?novel_id={}` | 删除单格 |
| DELETE | `/{map_id}/territories?novel_id={}&faction_entity_id={}` | 按组织删除全部势力范围 |

### 世界动态事实（P0）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/project-observations/inbox?novel_id={}&dynamic_type={}&scene_id={}&source={}&confidence={low\|high}&eligibility={ready\|missing}&skip={}&limit={}` | 项目级未分配 candidate/conflicted 收件箱；筛选在分页前生效 |
| PATCH | `/project-observations/{observation_id}?novel_id={}` | 用 `expected_updated_at` 更新作者字段 |
| POST | `/project-observations/{observation_id}/assign?novel_id={}` | 分配到 active 地图、换图或以 `map_id=null` 退回收件箱 |
| POST | `/project-observations/{observation_id}/ignore?novel_id={}` | 用 `expected_updated_at` 忽略项目候选 |
| GET | `/{map_id}/observations?novel_id={}&review_state={}` | 地图 observation 列表（未转 Fact 项显示为待处理） |
| POST | `/{map_id}/observations?novel_id={}` | 创建地图 observation；201 表示已提交，可立即读取或确认 |
| PATCH | `/{map_id}/observations/{observation_id}?novel_id={}` | 用 `expected_updated_at` 更新作者字段或候选审查状态 |
| POST | `/{map_id}/observations/batch-review?novel_id={}` | 用带 revision 的 `items` 批量确认、忽略或标记冲突 |
| POST | `/{map_id}/batch-actions?novel_id={}` | 批量动作入口：采用/忽略/冲突 observation、更新 fact 状态、记录图层可见性 patch |
| POST | `/{map_id}/observations/{observation_id}/confirm?novel_id={}` | 采用 observation 并生成/复用 `map_facts`（路径名保留兼容） |
| POST | `/{map_id}/observations/{observation_id}/ignore?novel_id={}` | 忽略 observation，不生成正式事实 |
| GET | `/{map_id}/facts?novel_id={}&fact_status={}` | 已采用地图事实列表 |
| PATCH | `/{map_id}/facts/{fact_id}?novel_id={}` | 软更新 fact 状态：`confirmed` / `rolled_back` / `deprecated` |

`spatial_anchor` 使用类型化 `MapSpatialAnchor`。带 `path_id` 时必须解析到当前
`novel_id + map_id`；deep import 的非法或跨图 path 引用会被移除并记录
`invalid_spatial_anchor`。确认 Fact 时固化 path revision、名称和代表点，后续线路变化不
改写旧 Fact；Playback 可读取 archived 几何并提示“线路已更新”。

`value_json.schema_version=1` 支持 `location`、`route_state`、`status`、`boundary`、
`resource`、`terrain`、`crisis` 和 `semantic` 类型化值。服务端生成稳定
`dimension_key`；响应附加
`normalized_value` 与 `normalization_state=typed|legacy_normalized|untyped|invalid`。
同一 Scene、对象和维度的相同值合并证据，不同值产生 conflict，不按创建时间覆盖。
candidate 即使通过 `include_candidates=true` 返回，也只进入独立预览，不参与有效状态、差分、
连续性问题或 canonical projection token。

创建 observation 的普通非流式请求由 `DbSession` 的 request-owned transaction 在
function-scope dependency 结束时提交；返回 201 后，后续确认、列表和地图状态请求可以立即通过独立数据库连接读取该 observation。

人物位置、事件发生地、线路/阻隔和势力范围可以先以显式
`payload_kind="proposal"` proposal union 进入 observation；proposal 不伪装成 canonical typed
value，读取时保持 `normalization_state="untyped"`。响应附加由服务端计算的 `eligibility`：
从 proposal 首次转为 canonical value 时，服务端会在只读来源中保留
`proposal_type`；因此人物位置仍只能绑定已采用人物，事件发生地仍只能绑定已采用事件，
且事件发生地不得只靠 path 通过采用门禁。
只有 canonical value、同项目已采用目标对象、active 地图、合法 location/path/hex，以及
Scene/章节来源或人工 `initial_state` 齐全时 `can_confirm=true`。

公共作者 PATCH 只允许目标对象、作者值、空间锚点和候选状态；来源、证据、workflow、原始
置信度、Scene/章节来源与来源时间均只读，额外字段返回 422。PATCH、assign、ignore、confirm
和 batch-review 都要求 `expected_updated_at`；409 响应 context 带最新只读 observation。
confirm 在 observation 行锁内重验资格并创建或复用 Fact，批量操作按 UUID 稳定锁定并在写入
前验证全部项目。项目收件箱只返回 `map_id IS NULL` 的待处理项，具体地图的
list/dashboard/playback 不会混入未分配候选。

### `MapStateResponse` 结构

```json
{
  "map": { /* MapConfigResponse */ },
  "breadcrumbs": [ /* MapConfigResponse 顶层→当前 */ ],
  "tiles": [ /* MapTileResponse */ ],
  "location_bindings": [ /* MapLocationBindingResponse */ ],
  "markers": [ /* MapMarkerResponse，无则为 [] */ ],
  "territories": [ /* MapTerritoryResponse，无则为 [] */ ],
  "location_layouts": [ /* canonical-owner MapLocationLayoutResponse */ ],
  "terrain_bindings": [ /* confirmed + canonical-owner MapTerrainBindingResponse */ ],
  "candidate_location_layouts": [ /* draft/candidate-owner legacy preview */ ],
  "candidate_terrain_bindings": [ /* 待处理地形绑定 */ ],
  "scene": { "id": "...", "index": 12, "title": "...", "chapter_title": null } | null
}
```

`filter_types` 参数当前被消费但**不触发后端过滤**（P0 返回全量，前端按 `showBoundary` 控制地点边界显隐）。

---

## 业务规则与约束

### 创建地图

- `map_type` 和 `terrain_type` 均为白名单，`Literal` 校验失败返回 **422**。
- `grid_width` / `grid_height` 范围 `[1, 200]`，`hex_size` `[4, 200]`。
- `template` 仅在 `map_type = "world"` 时生效：`blank` / `continent` / `islands`；非 world 类型创建时自动使用 `blank`。
- `parent_map_id` 必须存在且属于同 novel；`parent_entity_id` 必须存在、属于同 novel、`entity_type = "location"` 且已经采用。默认 list/get/state 与后续操作隐藏 owner 已待处理或归档的遗留详图。
- 同层级（同 `novel_id` + 同 `parent_map_id`）下 `name` 唯一，冲突返回 **409**。
- 既有 active 地图可通过 PATCH 修改 `parent_map_id` / `parent_entity_id`；这只改变地图树
  位置，不重建 tiles、bindings、图层、线路或动态事实。修改前锁定项目地图层级，
  目标父地图必须 active 且属于同 novel；禁止指向自身或任意后代，移动后仍会重验同层同名冲突。

### 地形编辑

- `PATCH /tiles` 为 **upsert**：已存在格更新，不存在格创建。
- 所有变更必须落在网格范围内，否则返回 **400**。
- 单次请求 `changes` 最多 10000 条。

### 地点绑定

- 只能绑定 `entity_type = "location"` 的实体，否则返回 **400**。
- 跨 novel 绑定实体返回 **404**。
- 批量创建时，若新增格中包含 `is_center=true`，会先清除该地点在该地图上的旧中心点。
- PATCH 单条绑定设为 `is_center=true` 时，同样会清除旧中心。

### 详图快速生成

- 仅允许对 `city` / `region` / `dungeon` 调用，对 `world` 调用返回 **400**。
- 会**清空**现有 tiles 后重新生成：中心 3 圈 `city`，外 1 圈 `road`，其余随机 `grassland` / `forest`。

### 动态标记

- `marker_type` 限定 `character` / `event` / `item`。
- 创建标记时 `entity_id` 必须存在且属于同 novel（不限制 entity_type）。
- `start_scene_id` / `end_scene_id` 传值时会同步设置 `start_scene_index` / `end_scene_index`（前端自动从 sceneList 取 index）。
- `list_markers` 和 `get_state` 的 scene 过滤逻辑：
  - 无 scene_id：返回所有标记。
  - 有 scene_id：返回无 scene 范围限制的标记，或 `start_scene_id` / `end_scene_id` 等于该 scene 的标记，或 scene_index 落在 `[start_scene_index, end_scene_index]` 区间内的标记。

### 势力范围

- 只能绑定 `entity_type = "organization"` 的实体，否则返回 **400**。
- 单格样式通过 PATCH `style_override` 更新。
- 支持按组织一键清空全部势力范围。

### 聚焦模式

- `GET /{map_id}/focus` 返回完整 `MapStateResponse`，但 `territories` 只保留指定 `faction_entity_id` 的格。
- 前端据此将不相关 hex 透明度降为 0.3。

### Scene 地图摘要

- `GET /scene-summary` 返回当前 Scene 对应的主地点、人物、事件、势力、危机、风险和 warning
- 该接口用于写作页右侧摘要，不返回完整地图状态
- 接口必须放在 `/{map_id}` 路由前，避免被路径参数捕获
- Scene 无 marker 但有该 Scene 的 active observation 时，会用 observation 中的 `map_id` 作为地图上下文，并返回可见风险/危机摘要。

### 地图打开目标

- `GET /open-target` 是写作页、世界对象页和地图默认入口共用的公开能力。
- 传 `scene_id` 时复用 Scene 地图摘要的 `open_target`，确保写作页和地图工作台一致。
- 传 `focus_entity_id` 时按地点绑定、动态 marker、组织势力范围查找代表地图；找不到时返回 `mode="recent"` 与可见 fallback 文案。
- 不传上下文时返回首个可用地图；项目没有地图时返回 `mode="overview"` 与空状态文案。

`GET /api/world/entities/{entity_id}/map-presence` 返回对象在全部 active 地图上的
layout/binding/marker/territory/terrain presence，并给出代表坐标、角色、绑定数、Scene
范围和 `open_target`，但不返回完整 territory hex。candidate 仅在显式
`include_candidates=true` 时返回，并标记 `display_state="review"`。

### 归档与恢复地图

- 归档确认展示整棵子树与关联资产数；归档后地图不参与地图树、presence、open-target 或编辑。
- 恢复要求外部祖先 active，并在写入前检查完整子树名称冲突；后代不能单独恢复。
- 已采用地图与视觉资产不提供作者可见硬删除入口。

### 独立视觉资产与可逆编辑历史

- 地形图层、Marker 和连续线路保留稳定 ID；作者侧“删除”归档资产，默认读取只返回 active，
  恢复前重验地图、实体、Scene、图层、线路端点和坐标，失效依赖返回 409。
- 地点绑定格、势力范围格、底图 tile 和 terrain patch 是当前画布投影，可以从当前表删除；
  删除前后的逐资源值仍进入不可变 revision，因此可按历史版本反向恢复。
- `map_visual_revisions` 与 `map_configs.editor_revision` 一一对应，保存提交后状态及资源级
  正向/反向变更。首次新编辑会惰性保存当前 baseline；不扫描或补录测试项目旧历史。
- `POST /editor/apply` 与旧单项写接口都通过同一个 revision seam。恢复历史必须带当前
  `expected_revision`，成功后创建新 revision，旧版本不被覆盖。
- 地图工作台沿用原 toolbar、card、modal、button 与 toast 样式提供“编辑历史”；409 时要求
  重新打开历史，不覆盖当前草稿，也不引入新的视觉语言。

## 前端实现现状

- Vue `MapWorkspaceView.vue` / `useMapWorkspace.js`：总览首屏只突出“继续最近地图”或“创建第一张地图”一个主操作；归档、资料补全、地图树和图层管理渐进展开，收件箱使用作者可读待处理卡片。总览仍可按章节范围启动独立地图资料补充，明确说明不重跑深度导入并持久化/恢复进度。原始场景 ID 只进入诊断筛选。具体地图继续提供“总控台 / 活地图 / 叙事透镜”以及既有编辑能力；Leaflet/Canvas 仍由 `MapViewportAdapter.vue` 下的窄 controller seam 承载。Leaflet 1.9.4 由本源按需 chunk 加载，失败在地图内原位重试且不影响其他页面；API、schema 和地图状态机不变。
- 从具体地图创建并打开工作台索引中尚不存在的子地图/根地图时，工作台会先刷新地图与地点索引，保证返回总览后地图树、数量和搜索立即包含新地图。
- 动态历史与当前动态分区展示；“查看历史”加载 ignored observation、rolled-back/deprecated fact 后，历史不会再受当前动态八条展示上限影响。
- `worldView`：对象行先读取全部 map presence；一张时直接定位，多张时展示地图角色与绑定数量选择器，无 presence 时回退 `open-target`。
- `writingView`：Scene 面板展示地图摘要、危机、风险和 warning，并通过 `open_target` 打开地图工作台。
- `mapView`：浏览模式以 typed selection 区分地点、marker、territory、terrain 与底图，fact/observation 仍走 dashboard inspector。地图设置可将既有地图移到其他层级并关联上级地点，后代地图不进入可选父项。Canvas 使用单 RAF、视口裁剪和 revision/viewport 缓存，隐藏、zoom 外和视口外节点不进入绘制队列。
- 具体地图已选中 Scene 时，同一个 `SceneMemoryRepairPanel` 在“总控台”和“活地图”中可用，不在“叙事透镜”重复展示。AI 参考资料的修复入口通过既有 `buildMapUrl(..., mode='live')` 路由深链接到该面板，未新增路由或 API。
- 标记编辑器按 `character` / `event` / `item` 过滤同类型世界对象，切换类型时清空旧选择；桌面编辑态释放隐藏动态栏的布局宽度，编辑侧栏在画布高度内独立滚动。
- 地点标签与聚合簇使用专用 `mapLabels` Leaflet pane；pane 本身不拦截背景，
  仅可交互 marker 消费点击。地点点击先打开信息框，详图/创建预览由信息框内按钮触发。
- `mapLayoutEngine.js`：纯前端布局引擎，根据视图模式、焦点、风险、待处理/已采用状态和视口空间，派生标签、聚合簇、语义气泡与低动效状态。
- `mapRouteContext.js`：统一解析/生成 `overview/recent/dashboard/live/lens` 规范 hash；
  旧 `mode=map` 首次读取后 replace 为 `mode=live`。跨地图/总览使用 push，同地图的
  mode、Scene、entity/hex/path/layer focus 使用 replace。

### 跨 novel 隔离

- 所有读取、更新、删除操作都会校验资源 `novel_id` 与请求 `novel_id` 一致，否则返回 **404**。
- 列表查询强制带 `novel_id`。

---

## 错误码速查

| 场景 | HTTP 状态码 | 说明 |
|------|-------------|------|
| 非法 `map_type` / `terrain_type` / `marker_type` | 422 | Pydantic `Literal` 校验失败 |
| 非法 UUID 格式 | 400 / 422 | `parse_uuid` 失败 |
| hex 坐标越界 | 400 | 超出 `grid_width` / `grid_height` |
| 对 `world` 调用 `generate` | 400 | 仅详图可用 |
| `parent_entity_id` 非 location | 400 | 创建详图时 |
| `faction_entity_id` 非 organization | 400 | 创建势力范围时 |
| 地图 / 绑定 / 标记 / 势力不存在 | 404 | 包括跨 novel 情况 |
| 父地图 / 父实体不存在 | 404 | 创建地图时 |
| 同层级同名地图 | 409 | 业务层校验 |
| `expected_revision` 过期 | 409 | 返回当前 revision，前端保留本地草稿 |
| observation `expected_updated_at` 过期 | 409 | 返回最新只读 observation，前端保留当前作者输入 |
| observation 缺少 canonical 对象、空间或时间条件 | 422 | `map_observation_not_eligible`，响应 context 含 eligibility |
| 图层或祖先锁定 | 409 | 新旧视觉写入口统一拒绝 |

---

## 混乱测试检查清单

以下测试点专门针对容易出错的边界场景，适合作为 chaos / monkey / 回归测试用例。

### 创建与层级

- [ ] 创建 `world` 地图时使用 `continent` / `islands` / `blank` 模板，确认 tiles 数量和地形分布。
- [ ] 创建 `city` 地图时不传 `template`，确认默认生成全 `grassland` tiles。
- [ ] 同层级同名地图返回 409。
- [ ] 用跨 novel 的 `parent_map_id` 创建子地图返回 404。
- [ ] 用非 location 实体作为 `parent_entity_id` 返回 400。
- [ ] 归档父地图后完整子树从 active 列表隐藏，资产和父子关系仍保留。
- [ ] 同名新地图创建后恢复冲突；只重命名恢复根可恢复完整子树。

### 地形编辑

- [ ] 批量 upsert 同一格两次，最终地形为第二次值，无唯一约束冲突。
- [ ] `hex_q` 或 `hex_r` 等于 `grid_width/grid_height` 时返回 400（边界为开区间）。
- [ ] 负数坐标返回 400。
- [ ] 单次提交 10000+ 条 changes 是否被 schema 拒绝（max_length=10000）。
- [ ] 非法 `terrain_type`（如 `lava`）返回 422。

### 地点绑定

- [ ] 同一地点绑定两个 `is_center=true` 的格，最终只保留后一个中心。
- [ ] PATCH 非中心格为中心格，旧中心被清除。
- [ ] 绑定非 location 实体（如 character）返回 400。
- [ ] 跨 novel 绑定实体返回 404。
- [ ] 同一地点重复绑定同一格返回 409（DB 唯一约束）。
- [ ] 兼容 DELETE 返回 204 且只归档，binding/marker/terrain/territory 不被删除。
- [ ] 两个相同 revision 的编辑请求只能一个成功；失败 batch 的数据和 revision 全部回滚。
- [ ] group 锁定阻断旧 marker/territory/terrain 写入口，显式解锁后恢复可写。
- [ ] 图层树拒绝循环、深度超限、漏 singleton 和 terrain leaf 重复，并正确计算 zoom 空交集。
- [ ] presence 合并 layout/binding，默认排除 archived map 与 candidate。

### 详图生成

- [ ] 对 `world` 地图调用 `generate` 返回 400。
- [ ] 对 `city` 地图调用 `generate` 后，tiles 中同时存在 `city` 和 `road`。
- [ ] `generate` 会覆盖已有 tiles，而非追加。

### 动态标记

- [ ] 创建 `marker_type = "invalid_type"` 返回 422。
- [ ] 跨 novel 删除标记返回 404。
- [ ] 设置 `start_scene_id` 后，按该 scene_id 查询能命中标记。
- [ ] 设置 `start_scene_index` / `end_scene_index` 后，按中间 scene 查询能命中标记。
- [ ] 无 scene 范围标记始终返回。

### 势力范围

- [ ] 用 organization 实体创建势力范围成功。
- [ ] 用非 organization 实体创建势力范围返回 400。
- [ ] 势力范围 hex 越界返回 400。
- [ ] `delete_by_faction` 返回正确删除行数。
- [ ] 聚焦模式只返回指定组织的势力范围，其他字段保持完整。

### 聚合状态

- [ ] `get_state` 对不存在的地图返回 404。
- [ ] `markers` 和 `territories` 字段始终存在且为 `list`，不会为 `null`。
- [ ] 带 `scene_id` 查询时，`scene` 字段包含场景信息；不带时为 `null`。
- [ ] `filter_types` 传 `all` / `location` / 任意字符串均不导致后端错误。

### 跨 novel 隔离

- [ ] 用 novel A 的 `map_id` 配 novel B 的 `novel_id` 查询返回 404。
- [ ] 用 novel B 的 `novel_id` 更新 novel A 的 binding / marker / territory 返回 404。
- [ ] 列表接口用不存在的 `novel_id` 返回空列表（不校验 project 存在性）。

### 并发与数据一致性

- [ ] 同一地点在短时间内两次设中心，最终只保留一个（业务层 `clear_center`）。
- [ ] 批量地形编辑与地点绑定编辑可独立进行，互不影响。

---

## 已知限制与前端行为

- **编辑分层**：前端内部使用 `editorLayer = none | location | baseTerrain | terrainOverlay | marker | territory`；不改变工作台 `dashboard/live/lens` 或路由 `mode`。
- **撤销**：每个编辑层保存独立 session 历史；新操作清空该层 redo。已经成功提交到后端的操作不提供跨会话历史回滚。
- **地点锚点**：旧地图读取时按 layout → center binding → footprint 质心最近格确定锚点但不写库；首次显式保存才物化缺失 layout/center binding。
- **内置素材**：仅支持自然环境、城市交通、奇幻危机三个程序化素材包和三套预设，不支持用户上传。
- **全量 state wire**：本批保持完整 tile wire shape。专用 Playwright 性能用例通过现有 API
  建立固定 24×18 与 200×200 混合地形 manifest/checksum 样本，重新读取完整 API payload
  并核对规范化 checksum；在 Chromium 1280×720、workers=1、retries=0 下断言真实 Leaflet
  1.9.4 已加载，再从
  `map:interactive` / `map:performance-sample` 公开事件采集冷启动、预热、10 次热导航、
  100 帧和真实 pointer/wheel/touch 输入。每个 profile 的 JSON 附件保存原始 frame/input 数组、
  fixture 语义 payload/checksum 与环境元数据；热导航 p75 分别强制 `≤2s` / `≤3s`，任一
  热样本不超过预算两倍，真实输入到下一帧 p95 强制 `≤33ms`。
- **390px 边界**：地图保留只读状态、标签 tap、Canvas 拖动和桌面端转交；
  quick-create 支持预览、地点微调和确认；地形绘制、线路节点精修、势力 hex 涂抹和递归
  图层编辑不在窄屏提供。
- **Scene 时间轴 UI**：按后端返回的 Scene stop 使用前后按钮、下拉与游标导航；Scene 序号
  在 API/路由中保持 0 起始的稳定索引，作者界面统一显示为 1 起始序号。它表示
  逻辑叙事顺序，不是经过时长，播放节奏也不代表人物移动速度。
- **人物旅程轨道**：只有目标对象为人物（或保留 `character_location` proposal
  语义）的位置变化进入“人物旅程”。地点本身的快速创建/静态布局事实与事件发生地
  属于“世界状态”，不得虚增人物旅程数量。
- **聚焦模式**：仅按组织过滤势力范围；人物 / 事件聚焦未实现。
- **世界动态事实边界**：有意不建立 `MapDelta` / `WorldDynamic` 持久表；它们连同 Scene
  状态和连续性问题均从 confirmed `map_facts` 确定性派生，避免形成第二事实源。
- **AI 位置建议**：P3 未实现，`map_position_suggestions` 表未建。
- **hex_s**：后端不存储，第三坐标由前端计算。
- **前端安全**：所有动态文本经 `esc()` 转义后入 DOM，不直接写入 `innerHTML`。

---

## 关键源码文件索引

| 文件 | 职责 |
|------|------|
| `backend/modules/world/map_models.py` | ORM 模型（地图基础表 + 动态事实表） |
| `backend/modules/world/map_schemas.py` | Pydantic Schema / 白名单（含 dashboard / playback 派生响应） |
| `backend/modules/world/map_repositories.py` | 数据访问层 |
| `backend/modules/world/services/map_service.py` | 历史兼容导出层（Config / Tile / Binding / Marker / Territory / DynamicFact） |
| `backend/modules/world/services/map/` | 地图业务服务实现子包 |
| `backend/modules/world/services/map/map_editor_apply.py` | revision CAS 与原子 command batch |
| `backend/modules/world/services/map/map_layer_tree.py` | 递归图层树、继承属性与 terrain 兼容投影 |
| `backend/modules/world/services/map/map_archive.py` | 地图子树归档/恢复 |
| `backend/modules/world/services/map/map_entity_presence.py` | 世界对象多地图 presence |
| `backend/modules/world/services/map/map_dynamic_projection.py` | 类型化动态值与 legacy 安全归一化 |
| `backend/modules/world/services/map/map_timeline_service.py` | Scene 状态、差分、冲突与空间连续性只读投影 |
| `backend/modules/world/services/map/map_context.py` | 共享上下文守卫（novel 隔离 / hex 越界 / entity 类型校验） |
| `backend/modules/world/map_api.py` | FastAPI 路由 |
| `backend/modules/world/map_facade.py` | 跨模块地图动态入口（deep import delta → observation） |
| `backend/modules/world/tests/test_map_*.py` | 测试套件 |
| `backend/alembic/versions/20260703_squashed_current_schema.py` | 当前 demo schema 初始化（含 P0/P1 地图表、P2 势力范围、世界动态 observation/fact 表） |
| `backend/alembic/versions/20260714_map_editor_layer_tree.py` | 地图归档/revision partial unique 与图层树回填 |
| `backend/alembic/versions/20260714_map_dynamic_timeline.py` | observation/fact Scene 时间线组合索引 |
| `frontend-console/views/mapView.js` | 主视图 |
| `frontend-console/views/mapLayoutEngine.js` | P2 自动布局、避让、聚合簇、语义气泡带派生 |
| `frontend-console/views/mapState.js` | 前端会话状态 |
| `frontend-console/views/mapHexRenderer.js` | 六边形 Canvas 渲染 |
| `frontend-console/views/mapEditPanel.js` | 编辑侧边栏 |
| `frontend-console/api.js` | 前端 API 封装 |
| [`docs/references/map-prd-v1.1.md`](../references/map-prd-v1.1.md) | 原始 PRD 与实现偏差记录 |
