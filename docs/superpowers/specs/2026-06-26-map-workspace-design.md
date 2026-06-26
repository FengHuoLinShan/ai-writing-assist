# 地图一级工作台体验设计

## 背景

动态地图已经在 `world` 模块内完成 P0/P1/P2：地图层级、六边形地形、地点绑定、Scene 标记、势力范围和聚焦模式均已有前后端基础。当前体验问题不是地图不存在，而是入口仍藏在 `world` 子标签里，写作流程也只能间接使用地图。

本设计把地图升级为侧边栏一级功能，并补齐写作页的新标签入口、Scene 地图摘要、地图总览和编辑效率能力。AI 位置建议不进入本轮。

## 目标

- 地图成为侧边栏一级菜单，与写作台、世界对象、大纲同级。
- `world/map` 保留为兼容入口，但跳转到一级地图页，不维护第二套地图界面。
- 地图页默认显示项目空间总览，并提供醒目的“打开最近地图”入口。
- 写作页顶部工具栏提供“打开地图”按钮，默认浏览器新标签页打开。
- 写作页 Scene 面板显示紧凑地图摘要：地点、人物/事件、势力和少量异常提示。
- 地图内增强编辑效率：地图树、搜索定位、图层开关、Scene 切换、批量编辑入口、会话编辑历史。
- 所有前端自动回退都必须给用户可理解的 toast 或页内提示。

## 非目标

- 不实现 AI 位置建议。
- 不新增 LLM 推断表，不让 AI 输出直接写入正式地图表。
- 不把写作页变成地图编辑器；写作页只显示摘要和新标签入口。
- 不做持久化编辑历史或审计日志；本轮只做会话级操作记录和现有撤销能力增强。
- 不新增地图底图、缩略图、路线播放、伪 3D 或上传能力。

## 用户体验

### 侧边栏一级入口

左侧侧边栏新增 `地图` 入口。点击后进入一级 `map` 路由。地图不再作为 `world` 的真实子视图承载。

`世界对象 -> 地图` 子标签保留给旧习惯和旧链接。用户点击后立即跳到一级地图页。该入口不显示独立地图 UI。

### 地图首页

地图页默认是项目空间总览，而不是直接打开某张地图。

总览包含：

- 醒目的“打开最近地图”主操作。
- 地图树：世界地图、城市、区域、地下城层级。
- 最近地图信息：名称、类型、最近打开时间。
- 简要统计：地图数、地点绑定数、Scene 标记数、势力范围数。
- 搜索入口：按地图名和地点名定位。
- 创建世界地图入口；无地图时显示空态。

点击“打开最近地图”直接进入最近使用的地图。如果最近地图已删除或不可访问，清除本地记录，提示“最近地图不可用，已返回地图总览”。

### 地图编辑器

进入具体地图后，默认界面只露出高频能力：

- 地图树或面包屑。
- 搜索定位。
- 图层开关：地形、地点、人物、事件、物品、势力范围。
- Scene 切换。
- 编辑模式开关。

复杂能力放进编辑模式或二级面板：

- 批量选择和批量清除。
- 地形画笔、油漆桶、地点绑定、动态标记、势力范围。
- 会话编辑历史。
- 组织聚焦和势力调色盘。

删除地图、清除整组地点绑定、清除整组势力范围等危险操作仍需二次确认。

### 写作页入口

写作页编辑器顶部工具栏新增“打开地图”按钮。按钮默认通过 `window.open` 打开浏览器新标签页，让用户自行拖动浏览器并排查看。

打开规则：

1. 当前 Scene 有推荐地图上下文时，打开该地图并带上 `scene_id`。
2. 当前 Scene 无地图上下文时，回退最近地图。
3. 最近地图也不可用时，打开地图总览。

回退必须提示用户。例如从 Scene 回退最近地图时，地图页或写作页提示“当前 Scene 暂无地图位置，已回退到最近地图”。

### Scene 面板地图摘要

写作页右侧 Scene 面板新增紧凑地图摘要，不放主按钮，避免重复入口。

摘要默认显示事实，异常仅轻量提示：

- `地点：洛阳外城`
- `人物：沈砚、陆青在场`
- `事件：东门封锁；势力：北府`
- `提示：陆青上一场在江陵，需确认移动合理性`

摘要为空时显示短提示，例如“当前 Scene 暂无地图位置”。接口失败时显示“地图摘要暂不可用”。这些提示不能阻断写作。

## 前端结构

### 路由

新增一级路由：

```js
map: { title: "地图", subViews: [] }
```

侧边栏新增 `data-view="map"` 的地图入口。

`world` 路由的 `map` 子标签保留为兼容入口。渲染 `world/map` 时不挂载 `mapView`，而是调用 `router.navigate("map")` 或显示极短跳转提示后跳转。

### 视图分层

新增 `frontend-console/views/mapWorkspaceView.js`：

- 渲染地图一级页外壳。
- 渲染空间总览、最近地图、地图树、搜索和图层开关。
- 解析地图深链接参数。
- 根据打开上下文决定显示总览或挂载具体地图。
- 记录和清理最近地图。

保留 `frontend-console/views/mapView.js`：

- 继续负责 Leaflet 初始化、Canvas 渲染、地形/地点/标记/势力编辑。
- 接受 `mount(rootId, context)`，其中 `context` 可包含 `mapId`、`sceneId`、`focusEntityId`、`mode`。
- 加载具体地图后通知 `mapWorkspaceView` 记录最近地图。

写作页只新增：

- 顶部工具栏按钮。
- `MapSummary` 小块。
- 调用 `scene-summary` 接口和 `buildMapUrl()`。

### 深链接上下文

新增前端工具模块，例如 `frontend-console/views/mapRouteContext.js`：

```js
export function buildMapUrl({ projectId, mapId, sceneId, focusEntityId, mode }) {}
export function parseMapRouteContext(hash = window.location.hash) {}
```

推荐 hash：

```text
#workbench/:projectId/map?map_id=...&scene_id=...&focus_entity_id=...&mode=...
```

全局 router 只需在解析 view 时忽略 `?` 后的 query，保持当前 hash 路由模型。地图相关 query 只由 `mapWorkspaceView` 消费，避免写作页、世界对象页、事件页各自拼接规则。

`mode` 支持：

- `overview`：显示地图总览。
- `recent`：打开最近地图，失败回退总览并提示。
- `map`：打开指定 `map_id`。

## 后端与数据流

### 复用现有地图 API

地图工作台继续复用现有 `/api/world/maps` 能力：

- 地图列表、创建、更新、删除。
- 地图状态聚合。
- 地形、地点绑定、动态标记、势力范围。
- 聚焦模式。

地图树可先由现有地图列表构建，不新增地图层级接口。最近地图本轮使用 `localStorage`，不新增偏好表。

### Scene 地图摘要接口

新增一个轻量聚合接口：

```text
GET /api/world/maps/scene-summary?novel_id=&scene_id=
```

该静态路由必须注册在 `/{map_id}` 动态路由之前，避免被当作 `map_id` 捕获。

响应契约：

```json
{
  "scene_id": "uuid",
  "primary_location": {
    "entity_id": "uuid",
    "name": "洛阳外城",
    "map_id": "uuid",
    "hex_q": 12,
    "hex_r": 8
  },
  "characters": [
    {"entity_id": "uuid", "name": "沈砚", "map_id": "uuid", "hex_q": 12, "hex_r": 8}
  ],
  "events": [
    {"entity_id": "uuid", "name": "东门封锁", "map_id": "uuid", "hex_q": 13, "hex_r": 8}
  ],
  "factions": [
    {"entity_id": "uuid", "name": "北府", "map_id": "uuid"}
  ],
  "warnings": [
    {"level": "info", "code": "scene_without_location", "message": "当前 Scene 暂无地图位置"}
  ],
  "open_target": {
    "mode": "map",
    "map_id": "uuid",
    "scene_id": "uuid",
    "fallback_reason": null,
    "fallback_message": null
  }
}
```

`primary_location` 可以为 `null`。`characters` 最多 5 个，`events` 最多 3 个，`factions` 最多 3 个，`warnings` 最多 2 条。

摘要规则必须保守：

- 只使用已有 `map_markers`、`map_location_bindings`、`map_territory_tiles` 和 Scene 排序信息。
- 不调用 LLM。
- 不推断正文中未结构化的位置。
- 主地点只来自当前 Scene 可见标记所在 hex 的同格地点中心或绑定；无法确定则为 `null`。
- 势力只来自当前 Scene 相关 hex 上叠加的 territory。
- 一致性提示只做结构化低风险检查，例如缺少地点标记、Scene 不存在地图上下文、同角色相邻 Scene 标记跨地图。

后端必须保持 `novel_id` 隔离。Scene 校验通过 outline facade 或 DI port，不直接 import `outline.models`。

### 打开目标

新增稳定契约 `MapOpenTarget`，由摘要接口返回，也可在前端本地 fallback 时构造：

```json
{
  "mode": "overview | recent | map",
  "map_id": "uuid|null",
  "scene_id": "uuid|null",
  "focus_entity_id": "uuid|null",
  "fallback_reason": "scene_without_map | recent_missing | invalid_map | null",
  "fallback_message": "用户可读提示|null"
}
```

前端使用 `fallback_message` 决定是否显示 toast 或页内提示。正常打开不刷 toast，只有发生自动回退时提示。

## 回退与提示

任何前端自动回退都必须给用户可理解的提示。

| 场景 | 行为 | 提示 |
|------|------|------|
| 最近地图已删除 | 清理本地记录，回到总览 | 最近地图不可用，已返回地图总览 |
| Scene 无地图上下文 | 新标签打开最近地图或总览 | 当前 Scene 暂无地图位置，已回退到最近地图 |
| `scene-summary` 失败 | 摘要显示降级文案，按钮仍可打开最近地图 | 地图摘要暂不可用 |
| URL 指定地图不可用 | 回到总览 | 指定地图不可用，已返回总览 |
| URL 指定 Scene 不可用 | 按普通地图打开 | Scene 不可用，已按普通地图打开 |
| Leaflet 未加载 | 显示现有地图引擎错误空态 | 地图引擎加载失败，请检查网络连接 |

提示要短，不在正常成功路径刷 toast。

## 安全与约束

- 所有地图和摘要查询必须带 `novel_id`，跨 novel 资源返回 404 或空摘要。
- 前端所有地图名、地点名、Scene 标题、实体名必须经 `esc()` 后进入 HTML。
- 删除地图继续硬删，但前端必须二次确认。
- 批量清除只能出现在编辑模式或二级面板。
- 不新增前端运行时依赖。Leaflet 仍是唯一地图视口依赖，沿用 ADR-0003。
- 不在 API 层写复杂业务逻辑；Scene 摘要编排放入 world/map 服务层或独立 assembler。

## 测试计划

### 前端

新增或扩展 Vitest：

- `router.js` 或导航相关测试：新增 `map` 路由，侧边栏可激活。
- `worldView.test.js`：`world/map` 跳转到一级 `map`，不再挂载第二套地图。
- `mapWorkspaceView.test.js`：总览、最近地图入口、最近地图失效回退提示、地图树、搜索、图层开关。
- `mapRouteContext.test.js`：`buildMapUrl()` 和 `parseMapRouteContext()` 处理 `map_id`、`scene_id`、`focus_entity_id`、`mode`。
- `writingView.test.js`：顶部打开地图按钮生成新标签 URL；Scene 面板摘要成功、为空、失败时的显示。
- `mapView.test.js`：保留现有地图渲染、Scene、territory、focus 回归。

优先回归命令：

```bash
cd frontend-console && npx vitest run tests/mapView.test.js
```

实现后还需要运行新增测试文件。

### 后端

新增 `backend/modules/world/tests/test_map_scene_summary.py`：

- Scene 不存在或跨 novel 隔离。
- 无地图标记时返回空摘要和 `open_target.mode = "recent"` 或 `overview`。
- 有当前 Scene 标记时返回 characters/events 和推荐 `map_id`。
- 同格地点绑定可成为 `primary_location`。
- territory 覆盖当前 hex 时返回 factions。
- warnings 数量上限和内容保守。

扩展 `test_map_api.py`：

- `GET /api/world/maps/scene-summary` 不被 `/{map_id}` 捕获。
- 响应 schema 稳定。

## 未来扩展

本设计为后续能力保留接口，但不在本轮实现：

- AI 位置建议：新增候选表和确认流，确认后写 `map_markers` 或 bindings。
- 图层 registry：将地形、地点、人物、事件、势力、路线、风险等作为可插拔图层。
- 后端最近地图偏好：从 `localStorage` 迁移到 `map_user_preferences`。
- 更强一致性检查：独立 `MapConsistencyService`，仍只返回提示，不直接改数据。
- 地图缩略图和图片底图：另行定义文件白名单、存储策略和 ADR。

## 验收标准

- 用户能从侧边栏直接进入地图一级工作台。
- `world/map` 旧入口不会坏，且跳转到一级地图页。
- 地图首页显示总览和醒目的最近地图入口。
- 写作页按钮默认新浏览器标签页打开地图。
- Scene 面板显示紧凑地图摘要，失败或无数据时有短提示。
- 所有自动回退都有 toast 或页内提示。
- 不引入 AI 位置建议、不新增 LLM 相关表、不增加新运行时依赖。
- 受影响前后端测试覆盖并通过。
