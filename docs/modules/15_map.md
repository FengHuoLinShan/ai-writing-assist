# Module: map / 动态地图子系统

## 定位

动态地图是 `world` 模块的子系统，不是独立后端模块。

- 后端文件位于 `backend/modules/world/`
- API 前缀为 `/api/world/maps`
- 当前前端主入口是一级路由 `map`（`mapWorkspaceView`）
- `world` 里的 `map` 子标签只保留兼容跳转

**设计来源**：`docs/PRD-动态地图功能.md`；当前代码已覆盖地图基础 P0-P2、世界动态 P0/P1，并提供世界动态 P2/P3 的前端与只读派生脚手架。

---

## 功能总览

| 阶段 | 功能 | 状态 | 后端 | 前端 |
|------|------|------|------|------|
| P0 | 世界地图 / 城市 / 区域 / 地下城创建与层级 | ✅ | `MapConfigService` | `mapWorkspaceView.js` + `mapView.js` |
| P0 | 六边形地形网格初始化与批量编辑 | ✅ | `MapTileService` | 画笔 / 油漆桶 / 应用 |
| P0 | 地点绑定（location 实体 → 一个或多个 hex） | ✅ | `MapLocationBindingService` | 绑定工具 |
| P0 | 地图聚合状态（map + breadcrumbs + tiles + bindings） | ✅ | `MapConfigService.get_state` | 主视图 |
| P0 | 详图快速生成（中心 city + 外 road） | ✅ | `MapConfigService.generate` | 编辑工具栏 |
| P0 | 地图观察事实候选与正式事实底座 | ✅ | `MapDynamicFactService` | 工作台动态事实摘要 |
| P1 | 世界动态总控台（首屏层 / 动态队列 / 检查器 / 批量分组） | ✅ | `MapDynamicFactService.get_dashboard` | 工作台右侧总控台 |
| P1 | Scene 时间层与动态标记（character/event/item） | ✅ | `MapMarkerService` | Scene 导航 + 标记工具 |
| P2 | 组织势力范围（territory tiles） | ✅ | `MapTerritoryService` | 势力范围工具 |
| P2 | 聚焦模式（按组织过滤势力范围） | ✅ | `GET /{map_id}/focus` | 聚焦按钮 |
| P2 | 写作页 Scene 地图摘要 | ✅ | `GET /scene-summary` | `writingView.js` |
| P2 | 自动布局、避让、聚合簇 | 部分实现 | 复用 dashboard / state 契约 | `mapLayoutEngine.js` + `mapView.js`；仍缺少路线/危机区等高级避让 |
| P2 | 总控台 / 活地图 / 叙事透镜三视图 | 部分实现 | 同一套地图事实 | `mapWorkspaceView.js`；当前是视图模式入口和焦点权重 |
| P2 | 上方语义气泡带与低动效模式 | 部分实现 | 同一套动态队列 | `mapWorkspaceView.js` + `mapLayoutEngine.js` |
| P3 | typed observations 播放派生 | 部分实现 | `GET /{map_id}/playback` | 电影化播放面板；当前基于 observation/fact 的只读派生 |
| P3 | 人物旅程 / 势力变化 / 危机推进 / 资源控制 / 状态变化轨道 | 部分实现 | `MapDynamicFactService.get_playback` | 轨道归类列表；仍缺少完整差分模型 |
| P3 | AI 位置建议 | ❌ | 未建表 | 未实现 |
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

**约束**：
- `UNIQUE(novel_id, parent_map_id, name)` 防止同层级重名（业务层在 PG NULL 场景补校验）。
- `parent_entity_id` 必须是同 novel 的 `location` 类型实体。
- 删除地图时，`tiles` / `bindings` / `markers` / `territories` 级联删除；子地图 `parent_map_id` 置 `NULL`（FK `ON DELETE SET NULL`）。

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

### `map_observations` — 地图观察事实候选（世界动态 P0）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID PK | |
| `novel_id` | UUID FK → projects | 项目隔离 |
| `map_id` | UUID FK → map_configs, nullable | 未解析空间时可为空 |
| `target_entity_id` | UUID FK → core_entities, nullable | 未消歧时可为空；不得存入跨 novel 引用 |
| `target_entity_type` / `target_name` | VARCHAR | 作者界面优先显示名称和类型文案 |
| `dynamic_type` | VARCHAR(64) | `location` / `status` / `boundary` / `crisis` / `resource` / `semantic` / `delta_event` 等 |
| `time_anchor` / `spatial_anchor` | JSONB | Scene/章节/地图/hex/地点等锚点 |
| `value_json` | JSONB | 观察到的候选状态或值 |
| `confidence` | FLOAT | 置信度 0~1 |
| `review_state` | VARCHAR(32) | `candidate` / `confirmed` / `ignored` / `conflicted` |
| `source_ref` | JSONB | 来源引用，如 `delta_log_id`、`context_snapshot_id` |
| `evidence_text` | TEXT | 可读来源证据摘要 |
| `scene_id` / `scene_index` / `source_chapter_index` | UUID / INT | 来源时间锚点 |

`deep import` Phase 2 仍写 `memory.delta_log`，同时把每条 `delta_event` 接入 `map_observations`，默认 `review_state="candidate"`，不直接写正式事实。

### `map_facts` — 已确认时间化地图事实（世界动态 P0）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID PK | |
| `novel_id` | UUID FK → projects | 项目隔离 |
| `observation_id` | UUID FK → map_observations, nullable | 来源 observation |
| `map_id` / `target_entity_id` | UUID FK, nullable | 关联地图和对象 |
| `target_entity_type` / `target_name` | VARCHAR | 作者界面显示文案 |
| `dynamic_type` | VARCHAR(64) | 与 observation 一致 |
| `time_anchor` / `spatial_anchor` / `value_json` | JSONB | 已确认事实内容 |
| `confidence` | FLOAT | 来源置信度 |
| `fact_status` | VARCHAR(32) | `confirmed` / `rolled_back` / `deprecated` |
| `source_ref` / `evidence_text` | JSONB / TEXT | 来源引用和证据摘要 |

确认 observation 会生成或复用 `map_facts`；忽略 observation 只更新审查状态，不硬删除候选。

---

## API 契约

统一前缀：`/api/world/maps`

### 地图管理与摘要

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/?novel_id={}&parent_map_id={}` | 地图列表；`parent_map_id` 为空表示顶层 |
| POST | `/?novel_id={}` | 创建地图，同时按模板生成初始 tiles |
| GET | `/scene-summary?novel_id={}&scene_id={}` | 写作页 Scene 地图摘要 |
| GET | `/{map_id}?novel_id={}` | 地图详情 |
| PATCH | `/{map_id}?novel_id={}` | 更新地图配置（name / description / default_center_x / default_center_y / default_zoom / sort_order） |
| DELETE | `/{map_id}?novel_id={}` | 硬删地图（前端需二次确认） |
| POST | `/{map_id}/generate?novel_id={}` | 快速生成详图地形（仅 `city/region/dungeon`） |
| GET | `/{map_id}/state?novel_id={}&scene_id={}&filter_types={}` | 聚合状态 |
| GET | `/{map_id}/dashboard?novel_id={}&scene_id={}&focus_entity_id={}` | 世界动态总控台：首屏层、动态队列、检查器、批量分组 |
| GET | `/{map_id}/playback?novel_id={}&scene_id={}&focus_entity_id={}&include_candidates={}` | 世界动态播放：typed observation 轨道和播放事件 |
| GET | `/{map_id}/focus?novel_id={}&faction_entity_id={}` | 聚焦模式（仅返回该组织势力范围） |

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
| GET | `/{map_id}/observations?novel_id={}&review_state={}` | 地图观察事实候选列表 |
| POST | `/{map_id}/observations?novel_id={}` | 创建地图观察事实候选 |
| PATCH | `/{map_id}/observations/{observation_id}?novel_id={}` | 更新 observation 审查状态 |
| POST | `/{map_id}/observations/batch-review?novel_id={}` | 批量确认、忽略或标记冲突 observation |
| POST | `/{map_id}/observations/{observation_id}/confirm?novel_id={}` | 确认 observation 并生成/复用 `map_facts` |
| POST | `/{map_id}/observations/{observation_id}/ignore?novel_id={}` | 忽略 observation，不生成正式事实 |
| GET | `/{map_id}/facts?novel_id={}&fact_status={}` | 已确认地图事实列表 |
| PATCH | `/{map_id}/facts/{fact_id}?novel_id={}` | 软更新 fact 状态：`confirmed` / `rolled_back` / `deprecated` |

### `MapStateResponse` 结构

```json
{
  "map": { /* MapConfigResponse */ },
  "breadcrumbs": [ /* MapConfigResponse 顶层→当前 */ ],
  "tiles": [ /* MapTileResponse */ ],
  "location_bindings": [ /* MapLocationBindingResponse */ ],
  "markers": [ /* MapMarkerResponse，无则为 [] */ ],
  "territories": [ /* MapTerritoryResponse，无则为 [] */ ],
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
- `parent_map_id` 必须存在且属于同 novel；`parent_entity_id` 必须存在、属于同 novel 且 `entity_type = "location"`。
- 同层级（同 `novel_id` + 同 `parent_map_id`）下 `name` 唯一，冲突返回 **409**。

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

- `GET /scene-summary` 返回当前 Scene 对应的主地点、人物、事件、势力和 warning
- 该接口用于写作页右侧摘要，不返回完整地图状态
- 接口必须放在 `/{map_id}` 路由前，避免被路径参数捕获

### 删除地图

- 硬删除（demo 阶段不使用 status 软删除）。
- 级联删除：`map_tiles`、`map_location_bindings`、`map_markers`、`map_territory_tiles`。
- 子地图 `parent_map_id` 置 `NULL`，不会级联删除子地图。
- 前端必须二次确认。

## 前端实现现状

- `mapWorkspaceView`：总览、最近地图、地图树、搜索、图层开关、打开具体地图；具体地图默认进入世界动态总控台，并提供“总控台 / 活地图 / 叙事透镜”切换、上方语义气泡带、低动效开关、电影化播放面板和动态对象信息框。
- `mapView`：地图编辑器本体；浏览模式下地点中心标签消费布局引擎，密集时自动偏移、缩短、图标化或聚合。
- `mapLayoutEngine.js`：纯前端布局引擎，根据视图模式、焦点、风险、候选/正式状态和视口空间，派生标签、聚合簇、语义气泡与低动效状态。
- `mapRouteContext.js`：处理从写作页或其他工作流带入的 `map_id` / `scene_id` / `focus_entity_id`

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

---

## 混乱测试检查清单

以下测试点专门针对容易出错的边界场景，适合作为 chaos / monkey / 回归测试用例。

### 创建与层级

- [ ] 创建 `world` 地图时使用 `continent` / `islands` / `blank` 模板，确认 tiles 数量和地形分布。
- [ ] 创建 `city` 地图时不传 `template`，确认默认生成全 `grassland` tiles。
- [ ] 同层级同名地图返回 409。
- [ ] 用跨 novel 的 `parent_map_id` 创建子地图返回 404。
- [ ] 用非 location 实体作为 `parent_entity_id` 返回 400。
- [ ] 删除父地图后，子地图 `parent_map_id` 变为 `NULL`，但子地图本身仍存在。
- [ ] 删除地图后，关联的 tiles / bindings / markers / territories 全部不可查。

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
- [ ] 删除地图后绑定随之删除（FK CASCADE）。

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

- **撤销**：仅撤销当前未应用的 pending 地形变更（清空 `pendingTerrainChanges`），已应用变更不可撤销。
- **地点绑定提交**：前端当前即时调用 API 创建/更新绑定，非 stage→apply 批量模式（与 PRD 路径 2 有偏差）。
- **标记与势力范围**：前端即时创建，非 stage→apply 模式。
- **Scene 时间轴 UI**：简化为前后导航按钮 + 下拉选择器，无连续滑块。
- **聚焦模式**：仅按组织过滤势力范围；人物 / 事件聚焦未实现。
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
| `backend/modules/world/services/map_service.py` | 业务服务（Config / Tile / Binding / Marker / Territory / DynamicFact） |
| `backend/modules/world/services/map_context.py` | 共享上下文守卫（novel 隔离 / hex 越界 / entity 类型校验） |
| `backend/modules/world/map_api.py` | FastAPI 路由 |
| `backend/modules/world/map_facade.py` | 跨模块地图动态入口（deep import delta → observation） |
| `backend/modules/world/tests/test_map_*.py` | 测试套件 |
| `backend/alembic/versions/20260614_add_map_tables.py` | P0 + P1 表迁移 |
| `backend/alembic/versions/20260622_add_territory_tables.py` | P2 势力范围表迁移 |
| `backend/alembic/versions/20260629_add_map_dynamic_fact_tables.py` | P0 世界动态 observation/fact 表迁移 |
| `frontend-console/views/mapView.js` | 主视图 |
| `frontend-console/views/mapLayoutEngine.js` | P2 自动布局、避让、聚合簇、语义气泡带派生 |
| `frontend-console/views/mapState.js` | 前端会话状态 |
| `frontend-console/views/mapHexRenderer.js` | 六边形 Canvas 渲染 |
| `frontend-console/views/mapEditPanel.js` | 编辑侧边栏 |
| `frontend-console/api.js` | 前端 API 封装 |
| `docs/PRD-动态地图功能.md` | 原始 PRD 与实现偏差记录 |
