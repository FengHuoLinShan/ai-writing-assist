# 动态地图功能 PRD v1.1

## 1. 功能概述

动态地图是小说世界对象的空间可视化工具，作为 `world` 模块的第四个子视图（`#world/map`）存在。首版目标不是自动推断剧情位置，而是让作者手工搭建和浏览世界地理结构。

核心能力按阶段拆分：

- **P0 静态地图编辑**：创建地图、绘制六边形地形、绑定地点、浏览地图、创建下钻详图。
- **P1 Scene 时间层**：按 Scene 显示人物/事件位置变化、时间轴筛选、活动标记。
- **P2 组织与聚焦层**：势力范围、人物/组织聚焦模式、关系高亮。
- **P3 AI 建议层**：从深度导入或 Scene 正文中提取位置建议，用户确认后写入地图。

技术上仍采用 vanilla JS SPA。可引入 Leaflet 1.9.x 作为轻量地图视口/缩放/拖拽引擎，六边形网格与业务图层由项目自定义 Canvas/DOM 图层渲染。Leaflet 是本功能的新增前端依赖，实施前需由用户确认或补 ADR，理由是避免自研平移、缩放、坐标换算和视口裁剪基础设施。

## 2. 目标与非目标

### 2.1 P0 目标

- 作者可以在 `worldView` 的"地图"子标签创建世界地图和地点详图。
- 作者可以用画笔和油漆桶编辑六边形地形。
- 作者可以把 `core_entities.entity_type = "location"` 的地点绑定到一个或多个六边形。
- 地图浏览模式显示地点中心标签，并支持点击地点进入详情或下钻到详图。
- 地图数据严格按 `novel_id` 隔离。

### 2.2 P0 非目标

- 不做人物/事件随 Scene 动态出现消失。
- 不做势力范围和聚焦模式。
- 不做 LLM 位置推断。
- 不做地图缩略图、伪 3D、图片填充、路线播放。
- 不允许上传地图底图。图片底图属于后续能力，另行定义白名单和存储策略。

## 3. 用户路径

### 路径 1：创建世界地图（P0）

**入口**：`worldView` → "地图"子标签 → 地图列表为空 → "创建世界地图"

1. 弹出模态框：
   - 名称：输入，如"九州世界"
   - 类型：固定为 `world`
   - 尺寸：固定 30x20，共 600 格
   - 模板：大陆型 / 群岛型 / 空白
2. 确认后创建 `map_config` 和 30x20 的 `map_tiles`。
3. 自动进入编辑模式。
4. 侧边栏显示地形工具：
   - 地形画笔：选择地形 → 点击或拖拽六边形 → 加入待确认选择
   - 油漆桶：点击六边形 → 填充同地形的连通区域
5. 点击"应用"批量写入地形变更。
6. 点击"保存"退出编辑模式。

**快捷键**：编辑模式下 `Ctrl+Z` 撤销当前未应用的待确认变更（清空 pending 队列）；已应用的变更不可撤销。撤销只覆盖当前前端会话，不要求跨刷新持久化。（实现简化说明见文末"实现记录"。）

### 路径 2：绑定地点（P0）

**前提**：`world` 对象库中已存在 `location` 类型实体，如"洛阳"。

1. 进入地图编辑模式。
2. 侧边栏切换到"地点绑定"。
3. 搜索并选择"洛阳"。
4. 点击多个六边形，作为该地点的覆盖区域。
5. 选择其中一个六边形设为中心点 `is_center = true`。
6. 点击"应用"批量保存绑定。
7. 浏览模式下仅中心六边形显示"洛阳"标签；其他绑定格不显示名称。
8. 中心点显示下钻图标：无详图为灰色，有详图为蓝色。

约束：
- 同一地点在同一地图上最多一个中心点。
- 一个六边形可以同时拥有地形、地点绑定、后续势力范围和后续动态标记。
- P0 不允许同一六边形绑定多个地点中心；如确需重叠地点，先允许绑定区域重叠，中心点冲突时要求用户选择保留哪一个中心标签。

### 路径 3：创建地点详图（P0）

**前提**：世界地图上的"洛阳"已绑定中心点。

1. 点击"洛阳"中心六边形 → 打开详情面板。
2. 点击"创建详图"或下钻图标。
3. 弹出创建模态框：
   - 名称：默认"洛阳"
   - 类型：默认 `city`
   - 尺寸：按重要性默认分配，可手动调整：
     - `core`：60x45，共 2700 格
     - `important`：40x30，共 1200 格
     - `normal` / 其他：20x30，共 600 格
   - 父地图：当前世界地图
   - 父实体：洛阳
4. 创建后进入详图编辑模式。
5. P0 提供"快速生成"按钮：
   - 中心 3 圈 `city`
   - 外圈 1 圈 `road`
   - 其余随机 `grassland` / `forest`
6. 用户可继续手工调整后保存。

### 路径 4：浏览地图（P0）

默认视图：
- 显示当前选中地图。
- 显示所有地点中心标签。
- 默认不显示地点区域边界，只显示中心标签和下钻图标。

交互：
1. 点击地点中心 → 右侧详情面板显示地点名称、摘要、绑定格数、下钻按钮。
2. 点击无地点六边形 → 详情面板显示地形信息。
3. 点击筛选器：
   - "全部"：地点中心标签
   - "地点"：地点中心标签 + 地点绑定区域边界
   - P0 中"人物"、"事件"、"组织"筛选项不显示或置灰
4. 面包屑显示当前地图层级：
   ```
   九州世界 -> 洛阳 -> 皇宫
   ```
5. 点击面包屑层级返回上级地图。

### 路径 5：Scene 时间层（P1）

P1 在 P0 静态地图基础上增加动态标记：

- 时间轴从 `outline.scenes` 读取 Scene 列表。
- `map_markers` 使用 `scene_id` 作为稳定锚点，冗余保存 `scene_index` 方便排序和查询。
- 人物/事件/物品标记按 `start_scene_id` / `end_scene_id` 判断是否显示。
- 鼠标悬停人物标记时，气泡显示当前 Scene 附近的相关事件。
- 点击事件标记跳转到对应 Scene。

### 路径 6：势力范围与聚焦模式（P2）

P2 增加组织控制区域和聚焦浏览：

- 势力范围单独存储为 territory tile，不复用地点绑定。
- 势力范围可与地点绑定叠加；地点颜色和标签优先于势力半透明覆盖。
- 聚焦人物/组织时，不相关六边形透明度降为 0.3，只显示相关地点、人物、组织和事件。
- 不做路线播放；路线属于 P3 或更后续能力。

### 路径 7：AI 位置建议（P3）

P3 才接入 LLM 推断：

- 从深度导入流程或 Scene 正文中提取人物/事件位置建议。
- AI 输出不直接写入正式地图表，而是写入 `map_position_suggestions`。
- 用户在地图编辑界面逐条确认、修改或忽略建议。
- 用户确认后才写入 `map_markers` 或其他正式地图表。

## 4. 数据模型

地图数据属于 `world` 模块，表名使用 `map_*`，所有表都必须包含 `novel_id` 并在查询条件中校验 `novel_id`。

### 4.1 `map_configs`（地图配置，P0）

```sql
CREATE TABLE map_configs (
    id UUID PRIMARY KEY,
    novel_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    map_type VARCHAR(32) NOT NULL,        -- world / city / region / dungeon
    description TEXT,

    default_center_x FLOAT DEFAULT 0.5,
    default_center_y FLOAT DEFAULT 0.5,
    default_zoom FLOAT DEFAULT 0,

    grid_width INT NOT NULL,
    grid_height INT NOT NULL,
    hex_size INT DEFAULT 30,

    parent_map_id UUID REFERENCES map_configs(id) ON DELETE SET NULL,
    parent_entity_id UUID REFERENCES core_entities(id) ON DELETE SET NULL,

    sort_order INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);
```

约束建议：
- `UNIQUE(novel_id, parent_map_id, name)` 防止同一层级重名。
- `parent_entity_id` 必须属于同一 `novel_id`。

### 4.2 `map_tiles`（地形网格，P0）

```sql
CREATE TABLE map_tiles (
    id UUID PRIMARY KEY,
    novel_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    map_id UUID NOT NULL REFERENCES map_configs(id) ON DELETE CASCADE,
    hex_q INT NOT NULL,
    hex_r INT NOT NULL,
    hex_s INT GENERATED ALWAYS AS (-hex_q - hex_r) STORED,

    terrain_type VARCHAR(32) NOT NULL,    -- grassland / forest / desert / mountain / water / city / road / ruin / secret / danger
    elevation INT DEFAULT 0,
    style_override JSONB DEFAULT '{}',

    UNIQUE(map_id, hex_q, hex_r),
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);
```

### 4.3 `map_location_bindings`（地点绑定，P0）

```sql
CREATE TABLE map_location_bindings (
    id UUID PRIMARY KEY,
    novel_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    map_id UUID NOT NULL REFERENCES map_configs(id) ON DELETE CASCADE,
    location_entity_id UUID NOT NULL REFERENCES core_entities(id) ON DELETE CASCADE,

    hex_q INT NOT NULL,
    hex_r INT NOT NULL,
    is_center BOOLEAN DEFAULT false,
    label_override VARCHAR(255),
    style_override JSONB DEFAULT '{}',

    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);
```

约束建议：
- `UNIQUE(map_id, location_entity_id, hex_q, hex_r)` 防止同一地点重复绑定同一格。
- 对 `is_center = true` 建部分唯一索引：`UNIQUE(map_id, location_entity_id) WHERE is_center`。
- 业务层校验 `location_entity_id` 的 `entity_type = "location"` 且 `novel_id` 匹配。

### 4.4 `map_territory_tiles`（势力范围，P2）

```sql
CREATE TABLE map_territory_tiles (
    id UUID PRIMARY KEY,
    novel_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    map_id UUID NOT NULL REFERENCES map_configs(id) ON DELETE CASCADE,
    faction_entity_id UUID NOT NULL REFERENCES core_entities(id) ON DELETE CASCADE,

    hex_q INT NOT NULL,
    hex_r INT NOT NULL,
    style_override JSONB DEFAULT '{}',

    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now(),

    UNIQUE(map_id, faction_entity_id, hex_q, hex_r)
);
```

### 4.5 `map_markers`（动态标记，P1）

```sql
CREATE TABLE map_markers (
    id UUID PRIMARY KEY,
    novel_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    map_id UUID NOT NULL REFERENCES map_configs(id) ON DELETE CASCADE,
    entity_id UUID NOT NULL REFERENCES core_entities(id) ON DELETE CASCADE,

    marker_type VARCHAR(16) NOT NULL,     -- character / event / item
    hex_q INT NOT NULL,
    hex_r INT NOT NULL,
    offset_x FLOAT DEFAULT 0,
    offset_y FLOAT DEFAULT 0,

    label VARCHAR(255),
    style_json JSONB DEFAULT '{}',

    start_scene_id UUID NULL,
    start_scene_index INT NULL,
    end_scene_id UUID NULL,
    end_scene_index INT NULL,
    visible BOOLEAN DEFAULT true,

    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);
```

说明：
- `scene_id` 是稳定锚点；`scene_index` 是排序和查询冗余。
- 后端不得直接 import `outline.models`，如需 Scene 信息，通过 outline facade/DI port 获取。

### 4.6 `map_position_suggestions`（AI 位置建议，P3）

```sql
CREATE TABLE map_position_suggestions (
    id UUID PRIMARY KEY,
    novel_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    map_id UUID REFERENCES map_configs(id) ON DELETE SET NULL,
    entity_id UUID REFERENCES core_entities(id) ON DELETE CASCADE,

    suggested_hex_q INT,
    suggested_hex_r INT,
    scene_id UUID NULL,
    scene_index INT NULL,
    source_text TEXT,
    confidence FLOAT DEFAULT 0.5,
    status VARCHAR(16) DEFAULT 'pending', -- pending / accepted / ignored

    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);
```

## 5. 前端设计

### 5.1 路由与文件

`world` 子视图新增 `map`：

```javascript
world: { title: "世界对象", subViews: ["objects", "relations", "aliases", "map"] }
```

前端文件建议：

```
frontend-console/views/
├── worldView.js             -- 继续承载 world 子标签入口
├── mapView.js               -- 地图主视图（浏览 + 编辑）
├── mapEditPanel.js          -- 编辑侧边栏
├── mapHexRenderer.js        -- 六边形 Canvas 渲染
├── mapState.js              -- 地图状态管理
└── mapApi.js                -- 地图 API 封装，或合并进 api.js 的 world.map 命名空间
```

### 5.2 技术栈

> **历史文档标注（2026-08-06）：** 下方 unpkg/CDN 示例已被 ADR-0003 的
> 2026-08-06 修订取代。当前交付使用精确锁定的 npm Leaflet 1.9.4 和 Vite
> 按需自托管产物，生产浏览器不再请求 unpkg。本段仅保留历史原文。

```html
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
```

自定义图层：
- `HexGridLayer`：Canvas 绘制六边形地形（P0）
- `HexLocationLayer`：地点绑定边界与中心标签（P0）
- `HexMarkerLayer`：人物/事件/物品标记（P1）
- `HexTerritoryLayer`：势力范围半透明覆盖（P2）
- `HexTooltipLayer`：气泡/提示 DOM（P0 起）

暂不实现 `HexFogLayer`。信息揭示遮罩需要和 reveal_level/视角知识边界结合，单独设计。

### 5.3 坐标系统

使用轴向坐标 `(q, r)`：

```javascript
function hexToPixel(q, r, size) {
  const x = size * 3 / 2 * q
  const y = size * Math.sqrt(3) * (r + q / 2)
  return [x, y]
}

function getNeighbors(q, r) {
  return [
    [q + 1, r], [q - 1, r], [q, r + 1],
    [q, r - 1], [q + 1, r - 1], [q - 1, r + 1],
  ]
}
```

### 5.4 视觉分层

| Layer | 内容 | 渲染方式 | 阶段 |
|-------|------|----------|------|
| 0 | Leaflet 视口背景 | CSS | P0 |
| 1 | 六边形地形 | Canvas | P0 |
| 2 | 地点绑定区域边界 | Canvas | P0 |
| 3 | 地点中心标签与下钻图标 | DOM | P0 |
| 4 | 人物/事件/物品标记 | Canvas | P1 |
| 5 | 势力范围 | Canvas | P2 |
| 6 | 气泡/提示 | DOM | P0 |

### 5.5 地形配色（默认）

| 地形 | 填充色 | 描边色 |
|------|--------|--------|
| grassland | `#7CB342` | `#558B2F` |
| forest | `#2E7D32` | `#1B5E20` |
| desert | `#F9A825` | `#F57F17` |
| mountain | `#ECEFF1` | `#CFD8DC` |
| water | `#1565C0` | `#0D47A1` |
| city | `#D7CCC8` | `#8D6E63` |
| road | `#BDBDBD` | `#9E9E9E` |
| ruin | `#8D6E63` | `#5D4037` |
| secret | `#7B1FA2` | `#4A148C` |
| danger | `#C62828` | `#B71C1C` |

### 5.6 布局

```
┌─────────────────────────────────────────┐
│ [地图] 九州世界 -> 洛阳      [编辑]      │
├─────────────────────────────────────────┤
│ 左侧地图列表 │         地图区域          │
│             │   洛阳 ▾                 │
│             │                          │
├─────────────────────────────────────────┤
│ [全部] [地点]                            │
└─────────────────────────────────────────┘
```

P1 后再添加 Scene 时间轴：

```
│ [←] Scene 12: 洛阳夜雨 [→]               │
│ ─────────────────────○───────             │
```

## 6. 后端 API 设计

地图 API 放在 `world` 模块下，统一前缀 `/api/world/maps`。

### 6.1 地图管理（P0）

```python
GET    /api/world/maps?novel_id=xxx
POST   /api/world/maps?novel_id=xxx
GET    /api/world/maps/{map_id}?novel_id=xxx
PATCH  /api/world/maps/{map_id}?novel_id=xxx
DELETE /api/world/maps/{map_id}?novel_id=xxx
POST   /api/world/maps/{map_id}/generate?novel_id=xxx
```

删除地图属于危险操作，前端必须二次确认；后端按 `novel_id` 校验后硬删除地图及其 tiles / location_bindings / markers（FK CASCADE）。子地图（`parent_map_id` 指向被删地图者）不级联删除，而是置为顶层（`parent_map_id = NULL`，FK `ON DELETE SET NULL`）。项目处于 demo 阶段，地图删除不要求 status 软删除。（删除语义澄清见文末"实现记录"。）

### 6.2 地图状态聚合（P0 起）

```python
GET /api/world/maps/{map_id}/state?novel_id=xxx&filter_types=all
```

P0 返回：

```json
{
  "map": "MapConfig",
  "breadcrumbs": ["MapConfig"],
  "tiles": ["MapTile"],
  "location_bindings": ["MapLocationBinding"],
  "scene": null
}
```

P1 起增加：

```json
{
  "markers": ["MapMarker"],
  "scene": { "id": "...", "index": 12, "title": "...", "chapter_title": "..." }
}
```

P2 起增加：

```json
{
  "territories": ["MapTerritoryTile"]
}
```

### 6.3 地形批量编辑（P0）

```python
PATCH /api/world/maps/{map_id}/tiles?novel_id=xxx
```

请求体：

```json
{
  "changes": [
    { "hex_q": 1, "hex_r": 2, "terrain_type": "forest", "elevation": 0 }
  ]
}
```

### 6.4 地点绑定（P0）

```python
POST   /api/world/maps/{map_id}/location-bindings?novel_id=xxx
PATCH  /api/world/maps/{map_id}/location-bindings/{binding_id}?novel_id=xxx
DELETE /api/world/maps/{map_id}/location-bindings/{binding_id}?novel_id=xxx
```

批量创建请求体：

```json
{
  "location_entity_id": "...",
  "hexes": [
    { "hex_q": 10, "hex_r": 6, "is_center": true },
    { "hex_q": 10, "hex_r": 7, "is_center": false }
  ]
}
```

### 6.5 动态标记（P1）

```python
GET    /api/world/maps/{map_id}/markers?novel_id=xxx&scene_id=xxx
POST   /api/world/maps/{map_id}/markers?novel_id=xxx
PATCH  /api/world/maps/{map_id}/markers/{marker_id}?novel_id=xxx
DELETE /api/world/maps/{map_id}/markers/{marker_id}?novel_id=xxx
```

### 6.6 势力范围与聚焦（P2）

```python
PATCH /api/world/maps/{map_id}/territories?novel_id=xxx
GET   /api/world/maps/{map_id}/focus?novel_id=xxx&entity_id=xxx&scene_id=xxx
```

### 6.7 AI 位置建议（P3）

```python
GET  /api/world/maps/{map_id}/position-suggestions?novel_id=xxx&status=pending
POST /api/world/maps/{map_id}/position-suggestions/{suggestion_id}/accept?novel_id=xxx
POST /api/world/maps/{map_id}/position-suggestions/{suggestion_id}/ignore?novel_id=xxx
```

## 7. 技术实现边界

### 7.1 后端模块文件

在 `backend/modules/world/` 内新增地图相关文件：

```
backend/modules/world/
├── map_models.py
├── map_schemas.py
├── map_repositories.py
├── map_services.py
└── map_api.py
```

`map_api.py` 由 `modules.world.api` 或 `app.main` 注册到同一个 `/api/world` 命名空间。不要为了地图创建新的顶层 `maps` 模块。

### 7.2 跨模块依赖

- 地图读取地点、人物、组织、事件时，只访问 `world` 自有表。
- 地图需要 Scene 列表或 Scene 标题时，通过 `outline` facade/DI port 获取，不直接 import `modules.outline.models` / `repositories` / `services`。
- `map_markers.start_scene_id` / `end_scene_id` 不建数据库 FK 到 `scenes`，避免跨模块 ORM 强耦合；业务层通过 `novel_id` 和 outline 公共接口校验。

### 7.3 安全与校验

- 所有地图 API 必须要求 `novel_id` 并校验所属关系。
- Pydantic schema 校验所有请求体。
- 前端渲染地点名、事件名、气泡内容时必须使用 `esc()` 或安全 DOM text API；不把用户/AI/API 动态内容直接写入 `innerHTML`。
- 地图删除、批量覆盖绑定、接受 AI 建议等操作需要前端确认。
- 不记录或返回 API Key、LLM 原始敏感内容。

## 8. 迭代规划

| 阶段 | 内容 | 优先级 |
|------|------|--------|
| P0 | 地图列表、世界地图创建、地形编辑、地点绑定、地点详图、浏览/下钻 | 必做 |
| P1 | Scene 时间轴、人物/事件/物品动态标记、事件气泡、活动标记 | 次优先 |
| P2 | 组织势力范围、聚焦模式、组织调色盘 | 后续 |
| P3 | LLM 位置建议、路线播放、多人物对比聚焦 | 后续 |
| P4 | 地图缩略图、伪 3D 纹理、图片填充、AI 地形生成 | 暂缓 |

## 9. 附录

### 9.1 六边形像素坐标换算

```javascript
function pixelToHex(x, y, size) {
  const q = (2 / 3 * x) / size
  const r = (-1 / 3 * x + Math.sqrt(3) / 3 * y) / size
  return hexRound(q, r)
}

function hexRound(q, r) {
  let s = -q - r
  let rq = Math.round(q)
  let rr = Math.round(r)
  let rs = Math.round(s)
  const dq = Math.abs(rq - q)
  const dr = Math.abs(rr - r)
  const ds = Math.abs(rs - s)
  if (dq > dr && dq > ds) rq = -rr - rs
  else if (dr > ds) rr = -rq - rs
  else rs = -rq - rr
  return [rq, rr]
}
```

### 9.2 地形填充（BFS）

```javascript
function floodFillTerrain(startQ, startR, targetTerrain, nextTerrain, mapId) {
  const queue = [[startQ, startR]]
  const visited = new Set()
  const changes = []

  while (queue.length > 0) {
    const [q, r] = queue.shift()
    const key = `${q},${r}`
    if (visited.has(key)) continue
    visited.add(key)

    const tile = getTile(mapId, q, r)
    if (!tile || tile.terrain_type !== targetTerrain) continue

    changes.push({ hex_q: q, hex_r: r, terrain_type: nextTerrain })

    for (const [nq, nr] of getNeighbors(q, r)) {
      queue.push([nq, nr])
    }
  }

  return changes
}
```

---

**文档状态**：P0 + P1 已实现（2026-06-15）
**下次更新**：P2 实现后根据实际 API、数据模型和交互细节同步调整。

## 实现记录（P0 偏差说明）

P0 已实现，以下为实现与 PRD 原文的偏差，均已在 ADR-0003 或代码注释中记录决策理由：

1. **Leaflet 1.9.4 引入**：本历史实施记录中的原方案通过 CDN 加载
   （`unpkg.com/leaflet@1.9.4`）；该交付方式已被 ADR-0003 的 2026-08-06
   修订取代，当前使用锁定 npm 依赖和 Vite 按需自托管产物。Leaflet 仍仅作视口引擎
   （平移/缩放/坐标换算），六边形业务图层继续使用自研 Canvas 叠加。
2. **`map_tiles.hex_s` 列未建**：PRD §4.2 要求 `hex_s GENERATED ALWAYS AS (-hex_q-hex_r) STORED`。项目无 `sqlalchemy.Computed` ORM 先例且 SQLite 测试不支持 PG 生成列。决策：ORM 不声明 `hex_s`，第三坐标由前端 `s = -q - r` 计算，后端只存 `(q, r)`。如未来需后端按 s 查询，再补 Alembic 原始 SQL（参照 `search_text` 的 `d967c0547255` 迁移模式）。
3. **地点中心点部分唯一索引**：PRD §4.3 要求 `UNIQUE(map_id, location_entity_id) WHERE is_center`。SQLAlchemy 的 `Index(unique=True, postgresql_where=...)` 在非 PG dialect 仍生成无 WHERE 的 unique index，破坏 SQLite 测试。决策：ORM 不声明该索引，由业务层 `MapLocationBindingService.clear_center` 保证唯一性；PG 部分唯一索引待 Alembic 迁移补 `op.execute` 原始 SQL。
4. **编辑面板**：项目无现成抽屉/侧边栏组件。决策：mapView 容器内绝对定位 `.map-edit-panel`（CSS `position: absolute; right: 0`），不引入抽屉框架。
5. **后端文件组织**：按 PRD §7.1 新建独立 `map_models.py` / `map_schemas.py` / `map_repositories.py` / `services/map_service.py` / `map_api.py`，均在 `modules/world/` 下。`map_api.py` 用独立 router（`prefix=/api/world/maps`）由 `app.main` 单独 include，满足 PRD 的 `/api/world` 命名空间要求。
6. **P1 数据层预留**：`map_markers` 表已建（P1 用），但 P0 不实现其 service/API。`map_territory_tiles`（P2）和 `map_position_suggestions`（P3）表未建。

### 偏差修复轮（PRD 审计后）

7. **撤销模型简化**：PRD §路径1 原文要求撤销覆盖"未保存或已应用"两类。决策：简化为只撤销未应用的 pending 变更（清空 `pendingTerrainChanges`），已应用的变更不可撤销。理由：已应用回滚需在 stage 时记录原值并 batchUpdateTiles 回写，脏数据风险高且收益低；P0 用户路径中"应用"本身就是显式确认动作。PRD §路径1 已同步修改文字。
8. **删除语义澄清**：PRD §6.1 原文"硬删除地图及其子数据"与 §4.1 `ON DELETE SET NULL` 自相矛盾。决策：采纳 SET NULL 语义——删除地图时 tiles/bindings/markers 随之 CASCADE 删除，子地图置为顶层（`parent_map_id=NULL`）而非级联删除。理由：级联删除子地图可能误删大量作者工作，demo 阶段孤儿顶层地图成本更低。PRD §6.1 已同步修改文字。
9. **地图更新方法 PATCH**：PRD §6.1 要求 `PATCH /api/world/maps/{map_id}`，首轮实现误用 `PUT`。已修正为 `@router.patch`（后端 `map_api.py`）+ `method: "PATCH"`（前端 `api.js`），消除 405 风险。
10. **`parent_entity_id` 校验**：PRD §4.1 要求 parent_entity_id 属同 novel 且 §4.3 要求 entity_type=location。首轮实现 create 中该校验是空 `pass`。已补真实校验（查 CoreEntity + novel 归属 + entity_type=location），不符抛 400/404。
11. **地形/地图类型白名单**：PRD §5.5 固定 10 种地形、§6.1 固定 4 种 map_type。首轮实现只有 `max_length` 约束，任意字符串可入库。已在 `map_schemas.py` 用 `Literal[...]` 强校验，非法值返回 422。
12. **generate 限制详图**：PRD §路径3 的"快速生成"是详图（city/region/dungeon）功能。首轮实现对 world 地图也可调用。已加校验：对 `map_type=world` 调 generate 返回 400。
13. **MapStateResponse 契约预留位**：PRD §6.2 是渐进式扩展契约（P1 加 markers、P2 加 territories）。首轮实现未声明这两个字段。已补 `markers: list = []` / `territories: list = []` 默认空 list，保证前端解构安全。

### 已知前端偏差（P0 未处理，后续迭代）

以下 PRD 明确要求但 P0 前端未实现，记为已知偏差待后续补全：
- **Layer 6 气泡/提示（tooltip）**（PRD §5.4）：悬停六边形无 DOM tooltip 提示。
- **右侧详情面板**（PRD §路径4）：点击地点中心仅 toast，无名称/摘要/绑定格数/下钻按钮的面板。
- **pending 格视觉反馈**（PRD §路径1）：`_redrawPending` 为空实现，画笔点击后无半透明高亮。
- **画笔拖拽绘制**（PRD §路径1）：仅支持点击，不支持拖拽连线绘制。
- **地点绑定批量保存**（PRD §路径2）：当前逐格即时调 API，非"应用"批量保存。
- **删除地图前端入口**（PRD §6.1）：列表无删除按钮 + 二次确认。
- **地图元信息编辑 UI**（PRD §6.1）：无改名/改描述入口（API 已就绪）。

以上 7 项 P0 前端偏差已于 2026-06-15 前全部实现修复：
- Layer 6 气泡/提示：`_showTooltip` / `_buildTooltipContent` 已实现 Leaflet popup
- 右侧详情面板：`_renderDetailPanel` / `_updateDetailPanel` 已实现
- pending 格视觉反馈：`drawPendingTerrain` / `drawPendingBindings` 已实现
- 画笔拖拽绘制：`_handleCanvasMouseDown` / `_handleDragDraw` 已实现
- 地点绑定批量保存：`_applyBindings` 已实现
- 删除地图前端入口：`_deleteMap` + `confirmAction` 已实现
- 地图元信息编辑 UI：`_showSettingsModal` 已实现

### P1 实现记录

P1（Scene 时间层）于 2026-06-15 实现，以下为与 PRD 原文的偏差说明：

14. **Marker 前端即时创建**：PRD 未明确定义标记的前端创建交互。P1 实现在编辑模式下新增"标记"工具，点击六边形即时调 API 创建标记（非 stage→apply 模式），理由：标记是单次操作（与地形/绑定的批量编辑性质不同），即时创建更符合直觉。
15. **Scene 列表来源**：PRD §7.2 要求通过 outline facade/DI port 获取 Scene 信息。P1 实现通过 `SceneService.get()` 懒加载场景查询（`map_service.py` 中方法内 import，避免循环依赖），布局与 outline contracts 一致。
16. **Scene 时间轴 UI**：PRD §5.6 描述完整时间轴（`← Scene 12: 洛阳夜雨 →` 滑块）。P1 实现为简化的前后导航按钮 + 下拉选择器，无连续滑块。理由：时间轴滑块需 outline 模块提供 chapter 分组信息且交互复杂度高，P1 MVP 先用离散导航。
17. **P2/P3 数据表**：`map_territory_tiles`（P2）和 `map_position_suggestions`（P3）表未建，待对应迭代创建。

### P2 实现记录

P2（组织与聚焦层）于 2026-06-22 实现，以下为与 PRD 原文的偏差说明：

18. **势力范围数据表**：`map_territory_tiles` 表已建，与 PRD §4.4 设计一致。Alembic 迁移 `20260622_add_territory_tables` 创建表，含 `novel_id`, `map_id`, `faction_entity_id`, `hex_q`, `hex_r`, `style_override` 字段，唯一约束 `(map_id, faction_entity_id, hex_q, hex_r)`。

19. **势力范围后端 CRUD**：`MapTerritoryService` 提供 `list`, `create`, `update`, `delete`, `delete_by_faction` 方法。`create` 校验 `faction_entity_id` 必须是 `organization` 类型，且 hex 在网格范围内。`delete_by_faction` 用于一键清除某组织的全部势力范围。

20. **聚焦模式 API**：`GET /api/world/maps/{map_id}/focus?entity_id=xxx` 返回与该实体关联的所有 hex 坐标（通过 markers 和 territories 查询）。前端据此将不相关 hex 透明度降为 0.3。

21. **组织调色盘**：前端 `mapState.factionColors` 存储用户自定义颜色，默认使用 `hashColor(factionId)` 生成确定性颜色。势力范围渲染使用 `color + "66"`（40% 透明度）填充。

22. **势力编辑工具**：编辑模式侧边栏新增"势力范围"工具组，支持选择组织、选择颜色、绘制/清除势力范围。绘制模式为即时 API 调用（非 stage→apply 模式），与 P1 Marker 一致。

23. **P3 数据表**：`map_position_suggestions` 表未建，待 P3 迭代创建。

**文档状态**：P0 + P1 + P2 已实现（2026-06-22）
**下次更新**：P3 实现后根据实际 API、数据模型和交互细节同步调整。
