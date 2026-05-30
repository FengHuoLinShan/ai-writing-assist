# Module: geo / 地理关系与宏观历史模块

## 定位

geo 模块不是专业地图系统，而是小说地理关系与宏观历史辅助模块。地点本体属于 world_entities（entity_type = location），geo 只提供地理扩展信息。

## 数据表

- geo_locations — 地理扩展表（entity_id PK+FK → core_entities.id，仅存储地点层级/坐标/地形/气候/访问级别等地理特有字段；公共字段 name/summary/status 在 core_entities 中。parent_location_id 和边 FK 也引用 core_entities.id。era_states 放 content_json）
- geo_edges — 地理关系边（source_location_id / target_location_id → core_entities.id）
- geo_eras — 历史时期

## 服务

- GeoLocationService：地点 CRUD
- GeoEdgeService：关系边 CRUD
- GeoEraService：历史时期 CRUD
- GeoQueryService：查询聚合（地点上下文、地点树、通行约束、历史上下文、批量查询）
- GeoTopologyService：拓扑计算（最短路径计算、动态拓扑覆写）

## Facade

```python
async def create_location_extension(db, entity_id, novel_id, **kwargs) -> GeoLocationResponse
async def get_location_context(db, novel_id, location_id, depth=1) -> GeoContextBundle
async def get_locations_context_batch(db, novel_id, location_ids, depth=1) -> list[GeoContextBundle]
async def get_location_tree(db, novel_id) -> list[dict]
async def get_travel_constraints(db, novel_id, source_location_id, target_location_id) -> TravelConstraintResult
async def get_geo_history_context(db, novel_id, era_id=None, location_ids=None) -> dict
async def calculate_route(db, novel_id, source_location_id, target_location_id, chapter_index) -> RouteCalculationResult
```

## Contracts

- GeoLocationContract / GeoEdgeContract / GeoEraContract — 基础数据契约
- TravelConstraintContract — 通行约束结果
- RouteCalculationResult — 路径计算结果（is_reachable / total_hours / path / reason）
- GeoContextBundle — 地理上下文组合（供 Context Compiler 使用）

## API

```
# 地点
POST   /api/geo/locations
GET    /api/geo/locations
GET    /api/geo/locations/{id}
PUT    /api/geo/locations/{id}
DELETE /api/geo/locations/{id}
GET    /api/geo/locations/tree

# 关系边
POST   /api/geo/edges
GET    /api/geo/edges
GET    /api/geo/edges/{id}
PUT    /api/geo/edges/{id}
DELETE /api/geo/edges/{id}
GET    /api/geo/edges/by-location?location_id={id}

# 历史时期
POST   /api/geo/eras
GET    /api/geo/eras
GET    /api/geo/eras/{id}
PUT    /api/geo/eras/{id}
DELETE /api/geo/eras/{id}

# 业务查询
GET    /api/geo/travel-constraints?source={id}&target={id}
GET    /api/geo/history-context?era_id={id}&location_ids={ids}
POST   /api/geo/calculate-routing
GET    /api/geo/location/{location_id}/factions
GET    /api/geo/location/{location_id}/characters
```

## 不做

- PostGIS / 地图瓦片 / 精确坐标 / 多边形疆域
- 战争行军模拟 / 自动路径规划
- 地图历史动画
