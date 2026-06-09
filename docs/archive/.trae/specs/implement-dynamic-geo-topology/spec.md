# 动态地理拓扑与旅行时间计算 Spec

## Why

当前 geo 模块的 `get_travel_constraints` 只查询静态 `geo_edges` 表中两点之间的**直接**通行关系，无法反映主线剧情事件（如神战断航、秘境封印解除）对地理连通性的动态影响。需要构建一个"内存动态网络编译器"，在特定章节时间点下合并静态边与时间线事件的地理突变脚本，用 Dijkstra 算法计算最短可达路径与旅行耗时。

## What Changes

- **新增 `RouteCalculationResult` 契约**：`geo/contracts.py` 中添加路径计算结果数据类
- **新增 `GeoTopologyService`**：`geo/services.py` 中添加动态图编译 + Dijkstra 路径搜索服务
- **新增 `calculate_route` Facade 方法**：`geo/facade.py` 中暴露路径计算对外接口
- **新增 `get_geo_effects_up_to_chapter` Facade 方法**：`timeline/facade.py` 中暴露截止某章节的地理影响数据
- **新增 `/api/geo/calculate-routing` API 端点**：`geo/api.py` 中添加路径计算请求路由
- **新增 Pydantic Schema**：`geo/schemas.py` 中添加 `RouteQueryRequest` / `RouteQueryResponse`

## Impact

- Affected specs: geo 模块（contracts/facade/services/api）、timeline 模块（facade）
- Affected code:
  - `modules/geo/contracts.py` — 新增契约
  - `modules/geo/services.py` — 新增 `GeoTopologyService`
  - `modules/geo/facade.py` — 新增 `calculate_route`
  - `modules/geo/api.py` — 新增 API 端点
  - `modules/geo/schemas.py` — 新增 Schema
  - `modules/timeline/facade.py` — 新增 `get_geo_effects_up_to_chapter`
  - `modules/timeline/repositories.py` — 新增查询方法
  - `modules/timeline/services.py` — 新增业务方法

## ADDED Requirements

### Requirement: 内存动态网络编译器

系统 SHALL 在收到路径计算请求时，实时编译一张"当前章节专属"的地理连通图。

#### Scenario: 编译静态基础图
- **WHEN** 系统收到 `(novel_id, chapter_index)` 的路径计算请求
- **THEN** 系统从 `geo_edges` 加载该项目所有 `status='canonical'` 的边，排除 `relation_type='blocked_path'` 的边，将剩余边解析为加权邻接表

#### Scenario: 应用时间线事件覆写
- **WHEN** 存在 `chapter_index <= X` 且 `geo_effects` 非空的 `status='canonical'` 时间线事件
- **THEN** 系统通过 `TimelineFacade.get_geo_effects_up_to_chapter` 获取这些事件的 `geo_effects`，按事件 `order_index` 顺序应用 `edge_mutations`：
  - `action='block'`：从邻接表中移除该边
  - `action='connect'` 或 `action='reveal_hidden'`：向邻接表中添加/恢复该边

#### Scenario: 旅行耗时文本解析
- **WHEN** `travel_time` 字段包含中文/英文文本（如 "3天"、"12小时"、"2d"、"8h"）
- **THEN** 系统将其解析为标准浮点小时数；解析失败时降级为 24.0 小时并记录 warning 日志

### Requirement: Dijkstra 最短路径计算

系统 SHALL 基于编译后的加权有向图，使用 Dijkstra 算法计算最短旅行耗时路径。

#### Scenario: 两地可达
- **WHEN** 起点到终点存在至少一条连通路径
- **THEN** 返回 `RouteCalculationResult(is_reachable=True, total_hours=<最短耗时>, path=<途经节点UUID列表>)`

#### Scenario: 两地不可达
- **WHEN** 起点到终点无连通路径（所有路径被阻断）
- **THEN** 返回 `RouteCalculationResult(is_reachable=False, total_hours=inf, reason="受当前章节历史事件物理阻断，路线不通")`

#### Scenario: 起点不存在
- **WHEN** 起点在编译后的图中无出边
- **THEN** 返回 `RouteCalculationResult(is_reachable=False, total_hours=inf, reason="起点在当前章节无通路连通外部")`

#### Scenario: 起终点相同
- **WHEN** `source_id == target_id`
- **THEN** 返回 `RouteCalculationResult(is_reachable=True, total_hours=0.0, path=[source_id])`

### Requirement: 跨模块 Facade 接口

#### Scenario: TimelineFacade 暴露地理影响数据
- **WHEN** `TimelineFacade.get_geo_effects_up_to_chapter(novel_id, chapter_index)` 被调用
- **THEN** 返回所有 `status='canonical'` 且 `chapter_index <= X` 的时间线事件的 `geo_effects` 字段列表，按 `order_index` 排序

#### Scenario: GeoFacade 暴露路径计算
- **WHEN** `GeoFacade.calculate_route(novel_id, source_id, target_id, chapter_index)` 被调用
- **THEN** 返回 `RouteCalculationResult` 实例

### Requirement: API 端点

#### Scenario: POST /api/geo/calculate-routing
- **WHEN** 前端发送路径计算请求
- **THEN** 系统返回 `RouteQueryResponse`，包含 `is_reachable`、`total_travel_hours`、`recommended_path`、`message`

### Requirement: 性能约束

- 单次路径计算耗时 SHALL 不超过 50ms（节点 ≤1000，边 ≤5000）

### Requirement: geo_effects JSON Schema 契约

`timeline_events.geo_effects` 字段 SHALL 遵循以下 Schema：

```json
{
  "edge_mutations": [
    {
      "source_id": "uuid",
      "target_id": "uuid",
      "action": "block | connect | reveal_hidden",
      "new_relation": "string (optional)",
      "travel_time": "string (optional)"
    }
  ]
}
```

## MODIFIED Requirements

无。所有变更为新增，不修改现有功能。

## REMOVED Requirements

无。
