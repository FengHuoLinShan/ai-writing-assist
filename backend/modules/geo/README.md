# Module: geo / 地理关系与宏观历史模块

## 定位

Geo 模块不是专业地图系统，而是小说地理关系与宏观历史辅助模块。

它服务：地点层级、通行关系、相对方位、访问限制、历史时期下的地点状态变化、王朝兴衰、迁都、战争路线、贸易路线、禁区形成、遗迹分布等宏观历史设计。

## 核心原则

- 地点本体属于 `world_entities`（`entity_type = location`），geo 只提供地理扩展信息
- 不引入 PostGIS、Leaflet、Mapbox、地图瓦片、精确坐标、多边形疆域
- x/y 仅为简易相对坐标，用于近似定位
- 地理系统用于解释「世界为什么会变成现在这样」

## 负责

- 地点层级树构建与管理（continent → country → region → city → district → landmark → building → room）
- 地点间通行关系与方位关系（道路、水路、方向、隐藏通道、阻断路径）
- 地点访问级别（normal / restricted / dangerous / forbidden / secret）
- 宏观历史时期划分（古王朝、焚城前/后、主线开始时等）
- 各历史时期下地点的状态变化（era_states 存储在 content_json）
- 通行约束查询（两地之间能否通行、难度、条件）
- 地理历史上下文输出（供 Context Compiler 读取）

## 不负责

- 地图历史动画
- 真实地理坐标 / GPS
- 复杂疆域多边形
- 战争行军模拟
- 自动路径规划
- PostGIS / 地图瓦片
- 地点本体创建（由 world_entities 负责）

## 数据表

| 表名 | 说明 |
|------|------|
| `geo_locations` | 地理地点 — 层级、坐标、地形气候、访问级别 |
| `geo_edges` | 地理关系边 — 通行/方位关系、难度、条件 |
| `geo_eras` | 宏观历史时期 — 时间顺序、起止事件 |

## 核心概念

### GeoLocation

- `world_entity_id` → 关联 `world_entities` 中的地点对象
- `location_level` → continent / country / region / city / district / landmark / building / room
- `parent_location_id` → 自引用外键，构建地点层级树
- `x / y` → 简易相对坐标
- `content_json.era_states` → 各历史时期下的地点状态

### GeoEdge

关系类型：
- `road_to` — 道路连接
- `river_to` — 水路连接
- `inside` — 位于内部
- `north_of` / `south_of` / `east_of` / `west_of` — 方位关系
- `near` — 附近
- `hidden_path` — 隐藏通道
- `blocked_path` — 阻断路径
- `borders` — 接壤

### GeoEra

历史时期示例：古王朝时期、旧王朝时期、焚城前、焚城后、主线开始时、当前剧情时点。

## Facade 接口

```python
async def get_location_context(
    db, novel_id, location_id, depth=1
) -> GeoContextBundle:
    """获取地点上下文 — 地点信息 + 父级链 + 子地点 + 边 + 历史时期"""

async def get_location_tree(db, novel_id) -> list[dict]:
    """获取地点层级树（递归结构）"""

async def get_travel_constraints(
    db, novel_id, source_location_id, target_location_id
) -> TravelConstraintResult:
    """查询两地之间的通行约束"""

async def get_geo_history_context(
    db, novel_id, era_id=None, location_ids=None
) -> dict:
    """获取地理历史上下文"""
```

## API 路由

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/geo/locations` | 创建地点 |
| GET | `/api/geo/locations` | 地点列表（分页、按层级筛选） |
| GET | `/api/geo/locations/tree` | 地点层级树 |
| GET | `/api/geo/locations/{id}` | 地点详情 |
| PUT | `/api/geo/locations/{id}` | 更新地点 |
| DELETE | `/api/geo/locations/{id}` | 删除地点 |
| POST | `/api/geo/edges` | 创建关系边 |
| GET | `/api/geo/edges` | 关系边列表 |
| GET | `/api/geo/edges/by-location` | 按地点查边 |
| GET/PUT/DELETE | `/api/geo/edges/{id}` | 边 CRUD |
| POST | `/api/geo/eras` | 创建历史时期 |
| GET | `/api/geo/eras` | 历史时期列表 |
| GET/PUT/DELETE | `/api/geo/eras/{id}` | 时期 CRUD |
| GET | `/api/geo/travel-constraints` | 通行约束查询 |
| GET | `/api/geo/history-context` | 地理历史上下文 |

## 对外契约

其他模块可导入：
- `modules/geo/contracts.py` — 数据类契约
- `modules/geo/facade.py` — 对外入口函数

禁止导入：
- `modules/geo/models.py`
- `modules/geo/repositories.py`
- `modules/geo/services.py`

## 测试

```bash
cd backend
pytest modules/geo/tests/ -v
```

## 依赖

- `core.database` — 数据库连接
- `core.base` — Base ORM 基类
- `shared.enums` — LocationLevel, GeoEdgeType, AccessLevel, ObjectStatus
- `shared.types` — NovelID, LocationID
- `shared.constants` — 分页、Context Budget

## 不做

- 地图历史动画
- 真实地理坐标
- 复杂疆域多边形
- 战争行军模拟
- 自动路径规划
- PostGIS
- 地图瓦片
