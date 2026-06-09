# Tasks

- [x] Task 1: Timeline 模块 — 新增 `get_geo_effects_up_to_chapter` 跨模块接口
  - [x] 1.1: `timeline/repositories.py` — 新增 `get_geo_effects_up_to_chapter` 查询方法，筛选 `status='canonical'` 且 `chapter_index <= X` 且 `geo_effects` 非空的事件，按 `order_index` 排序
  - [x] 1.2: `timeline/services.py` — 新增 `get_geo_effects_up_to_chapter` 业务方法，调用 repository 并提取 `geo_effects` 字段
  - [x] 1.3: `timeline/facade.py` — 新增 `get_geo_effects_up_to_chapter` 对外接口，代理 service 调用
  - [x] 1.4: 编写 timeline 模块单元测试

- [x] Task 2: Geo 模块 — 新增 `RouteCalculationResult` 契约和 Schema
  - [x] 2.1: `geo/contracts.py` — 新增 `RouteCalculationResult` frozen dataclass（is_reachable, total_hours, path, reason）
  - [x] 2.2: `geo/schemas.py` — 新增 `RouteQueryRequest` 和 `RouteQueryResponse` Pydantic 模型

- [x] Task 3: Geo 模块 — 新增 `GeoTopologyService` 核心服务
  - [x] 3.1: 实现 `_parse_time_to_hours` 旅行耗时文本解析器（支持中文/英文格式，解析失败降级 24h）
  - [x] 3.2: 实现 `_compile_active_graph` 内存动态图编译器（加载静态边 + 应用时间线 geo_effects 覆写）
  - [x] 3.3: 实现 `calculate_route` Dijkstra 最短路径搜索（heapq 优先队列）
  - [x] 3.4: 编写 GeoTopologyService 单元测试（静态图、动态覆写 block/connect/reveal、不可达、起终点相同、解析降级）

- [x] Task 4: Geo 模块 — 新增 Facade 和 API 层
  - [x] 4.1: `geo/facade.py` — 新增 `calculate_route` 对外接口
  - [x] 4.2: `geo/api.py` — 新增 `POST /api/geo/calculate-routing` 端点
  - [x] 4.3: 编写 API 集成测试

# Task Dependencies

- [Task 2] depends on [Task 1] — GeoTopologyService 需要调用 TimelineFacade
- [Task 3] depends on [Task 1] and [Task 2] — 核心服务依赖契约定义和 Timeline 接口
- [Task 4] depends on [Task 3] — API 层依赖核心服务
