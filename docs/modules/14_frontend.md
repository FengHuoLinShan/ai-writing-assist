# Module: frontend / 前端控制台

## 定位

前端是纯 Vanilla JS SPA，通过 REST API 驱动整个创作工作台。动态地图视口使用 Leaflet，但应用主体仍保持无框架。

## 架构

- 入口：`index.html`
- 全局状态：`state.js`
- 路由：`router.js`
- API 封装：`api.js`
- 视图：`views/*.js`
- 通用交互：`shared/`、`ui/`

当前注册的一级路由为：

- `project`
- `writing`
- `world`
- `map`
- `rag`
- `outline`
- `generate`
- `context`

## 当前页面职责

| 视图 | 当前职责 |
|------|----------|
| `projectView` | 项目 CRUD、回收站、导入入口 |
| `writingView` | Scene 树 + 编辑器 + Scene 面板；版本历史；深度导入；Scene 地图摘要跳转 |
| `worldView` | 对象库、候选清洗、关系、别名；`map` 子标签现在只做兼容跳转 |
| `mapWorkspaceView` | 地图一级工作台，总览、最近地图、地图树、图层开关、搜索、聚焦；世界动态总控台、活地图、叙事透镜切换、电影化播放 |
| `mapView` | 具体地图渲染与编辑：地形、地点绑定、标记、势力范围；浏览态地点标签避让与聚合 |
| `outlineView` | 剧情线、篇章纲、Scene、伏笔、揭示、结构生成 |
| `ragView` | 检索、章节索引、索引重建 |
| `contextView` | 编译上下文、渲染 Markdown、查看 tier 预算/驱逐结果 |
| `generateView` | 手动 AI 生成入口，走 AI 参考资料确认流程 |

## 路由与状态特性

- `router.js` 维护 `_lastSubViewMap`，在主视图切换后恢复最后子标签
- `writing` 与 `outline` 被标记为 KeepAlive 视图
- `map` 路由会解析 query 上下文，用于承接写作页和世界页跳转
- `world/map` 仍保留入口，但现在会自动跳转到一级 `map`

## 写作流补充

`writingView` 当前不只是草稿编辑器，还承担：

- Scene 树导航
- 自动保存与未保存提醒
- 版本历史/恢复
- 深度导入进度展示
- `GET /api/world/maps/scene-summary` 的地图摘要展示
- 跳转到地图工作台并携带 `scene_id` / `focus_entity_id`

## 地图工作台补充

- `mapWorkspaceView` 保存“最近地图”到本地存储
- 可按地图名或地点名搜索
- 支持图层开关
- 右侧消费 `GET /api/world/maps/{map_id}/dashboard`，展示世界动态总控台、动态队列、检查器和批量分组
- 地图工作台消费同一套 dashboard / map state，支持“世界动态总控台 / 活地图 / 叙事透镜”三视图、上方语义气泡带、低动效模式
- 地图工作台同时消费 `GET /api/world/maps/{map_id}/playback`，按 typed observation 展示人物旅程、势力变化、危机推进、资源控制和状态变化播放轨道
- 动态队列、语义气泡和播放事件可打开对象信息框；observation 支持确认、忽略、标记冲突，fact 支持回滚、废弃、恢复确认，并保持技术 ID 不进入可见文本
- 批量修改分组可对候选 observation 执行批量确认、忽略和标记冲突；“打开检查器”会按对象聚焦刷新右侧检查器
- `mapLayoutEngine.js` 负责前端自动布局、标签避让、聚合簇和语义气泡排队；`mapView` 浏览态地点中心标签使用该布局结果避免高密度重叠
- 支持从写作流打开最近相关地图

## API 封装风格

- 统一 `request()` 处理超时、错误映射、FormData
- 按模块分组：`api.projects.*` / `api.world.*` / `api.outline.*` / `api.context.*`
- 地图接口统一挂在 `api.world.*` 下，后端前缀仍是 `/api/world/maps`

## 安全与渲染约束

- 动态文本优先走 `textContent`
- 必须插入 HTML 时先走 `esc()`
- 不把用户/AI/API 返回的未转义内容直接写入 `innerHTML`
