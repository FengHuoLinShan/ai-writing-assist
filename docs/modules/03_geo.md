# Module: geo / 地理关系与宏观历史模块

## 定位

geo 模块不是专业地图系统，而是小说地理关系与宏观历史辅助模块。地点本体属于 world_entities（entity_type = location），geo 只提供地理扩展信息。

## 数据表

- geo_locations — 地理扩展（关联 world_entity_id，含父级/坐标/地形/气候/访问级别，era_states 放 content_json）
- geo_edges — 地理关系边（road_to / river_to / inside / north_of / borders 等）
- geo_eras — 历史时期

## 服务

- GeoLocationService：地点 CRUD + 地点树
- GeoEdgeService：关系边 CRUD
- GeoEraService：历史时期 CRUD

## Facade

```python
async def get_location_context(db, novel_id, location_id, depth=1) -> GeoContextBundle
async def get_location_tree(db, novel_id) -> list[dict]
async def get_travel_constraints(db, novel_id, source_location_id, target_location_id) -> dict
async def get_geo_history_context(db, novel_id, era_id=None, location_ids=None) -> dict
```

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

# 历史时期
POST   /api/geo/eras
GET    /api/geo/eras
GET    /api/geo/eras/{id}
PUT    /api/geo/eras/{id}
DELETE /api/geo/eras/{id}
```

## 不做

- PostGIS / 地图瓦片 / 精确坐标 / 多边形疆域
- 战争行军模拟 / 自动路径规划
- 地图历史动画
