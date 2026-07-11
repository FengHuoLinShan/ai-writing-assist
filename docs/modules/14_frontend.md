# Module: frontend / 前端控制台

## 定位

前端是纯 Vanilla JS SPA，通过 REST API 驱动整个创作工作台。动态地图视口使用 Leaflet，但应用主体仍保持无框架。

## 架构

- 入口：`index.html`
- 全局状态：`state.js`
- 状态切片 helper：`stateSlices.js`
- 路由：`router.js`
- API 封装：`api.js`
- API 契约注册表：`apiContracts.js`
- 视图：`views/*.js`
- 通用交互：`shared/`、`ui/`

当前注册的一级路由为：

- `project`
- `writing`
- `world`
- `map`
- `rag`
- `outline`
- `scene`
- `generate`
- `settings`
- `project-settings`
- `llm`（向后兼容别名，按当前项目状态跳转到项目设置或全局设置）

旧 `context` hash 不再作为一级页面注册；路由初始化或浏览器前进/后退遇到它时，会重定向到 `generate?tab=task`。

## 当前页面职责

| 视图 | 当前职责 |
|------|----------|
| `projectView` | 项目 CRUD、回收站、导入入口 |
| `writingView` | Scene 树 + 工作稿编辑器 + AI 建议采用 + Scene 面板；版本历史；授权深度导入；Scene 地图摘要跳转 |
| `worldView` | 对象库、统一待处理（对象/关系/别名）、历史筛选；世界书支持编辑、图鉴和筛选三种内部展示；`map` 子标签现在只做兼容跳转 |
| `mapWorkspaceView` | 地图一级工作台，总览、最近地图、地图树、图层开关、搜索、聚焦；世界动态总控台、活地图、叙事透镜切换、电影化播放 |
| `mapView` | 具体地图渲染与编辑：地形、地点绑定、标记、势力范围；浏览态地点标签避让与聚合 |
| `outlineView` | 大纲子导航与结构生成；在 `scenes` 子标签组合 Scene 工作台，其余子标签管理剧情线、篇章纲、伏笔和揭示 |
| `sceneWorkbenchView` | 由 `outline/scenes` 承载的 Scene 管理、筛选、拆分/合并、复核与深度导入 Scene 整理；旧 `scene` 路由仅作兼容重定向 |
| `ragView` | 检索、章节索引、索引重建 |
| `generateView` | 生成中心 Chatbox：自由共创、粘贴外部对话、可选附带正文，并承担上下文任务预览 / 编译入口和生成待处理世界对象建议 |
| `globalSettingsView` | `settings` 路由；管理全局 LLM 默认、全局作者偏好、引用此默认的项目列表和本地偏好迁移；全局 LLM 默认不存 API Key |
| `projectSettingsView` | `project-settings` 路由；管理项目 LLM 主配置、深度导入参数和项目作者偏好；展示 effective source 并支持字段恢复继承 |

## 路由与状态特性

- `router.js` 维护 `_lastSubViewMap`，在主视图切换后恢复最后子标签
- `writing` 与 `outline` 被标记为 KeepAlive 视图；`outline/scenes` 为避免复用过期工作台 DOM，不进入 KeepAlive 缓存
- Scene 工作台的筛选、详情和复核状态由 `sceneWorkbenchView` 持有；当前 Scene 通过 `outline/scenes?scene_id=...` 写入浏览器历史
- `map` 路由会解析 query 上下文，用于承接写作页和世界页跳转
- `world/map` 仍保留入口，但现在会自动跳转到一级 `map`
- `settings` 是无项目也可访问的全局设置页；`project-settings` 依赖当前项目，未进入项目时显示空态并提供返回全局设置
- `llm` 是旧入口兼容别名：有当前项目时跳转 `project-settings`，否则跳转 `settings`
- 旧 `context` hash 会重定向到 `generate?tab=task`；上下文任务预览和编译入口由生成中心承担

## 开发与验证脚本

- 开发服务器使用 Vite：`npm run dev`，默认端口 8080，可通过 `FRONTEND_PORT` 覆盖。
- 单元测试使用 Vitest：`npm run test`；监听模式为 `npm run test:watch`。
- 浏览器 E2E 使用 Playwright：`npm run test:e2e`；烟雾子集为 `npm run test:e2e:smoke`。默认本地可复用已有 8000/8080 服务；涉及数据库 schema 的 E2E 使用 `PW_REUSE_EXISTING_SERVER=0` 强制 fresh server，让后端启动前执行 `APP_ENV=test alembic upgrade head`。如端口被旧服务占用，使用 `BACKEND_PORT=8010 FRONTEND_PORT=8090 PW_REUSE_EXISTING_SERVER=0`。
- `npm run test:all` 先跑 Vitest，再跑 Playwright。
- 当前 `package.json` 未定义前端构建脚本，也没有独立 lint/format 依赖；前端静态约束以现有测试和 `git diff --check` 为主。
- 当前已落地 vanilla JS 共享 API 契约校验第一阶段，覆盖项目、设置、导入、上下文、世界/地图、写作冲突检查和 RAG 的高风险 wrapper 子集；TypeScript / OpenAPI codegen 仍是未来设计项，当前说明见 `docs/frontend/typescript-api-contracts.md`。

## 写作流补充

`writingView` 当前不只是草稿编辑器，还承担：

- Scene 树导航
- 自动保存与未保存提醒
- 版本历史/恢复
- 深度导入进度展示：恢复 localStorage 中的 task_id，展示当前章节 / Scene / batch、质量统计、降级状态和中断恢复提示
- 中断恢复操作：用户显式点击“继续”才调用 `/api/imports/deep/resume`；“放弃恢复”必须二次确认并展示清理摘要
- `GET /api/world/maps/scene-summary` 的地图摘要展示，包括危机、风险和空间 warning
- 跳转到地图工作台并携带 `scene_id` / `focus_entity_id`

## 作者展示状态

- `shared/assetDisplayState.js` 是前端唯一通用映射：结构资产显示“待处理 / 已采用 / 历史”，正文显示“待处理 / 工作稿 / 已发布”。页面不得自行再维护 `candidate` / `canonical` 文案表。
- `attention_reasons`、低置信、冲突和 `needs_review` 显示为注意标签，不替代主状态。
- 主列表默认隐藏历史；只有显式选择历史/raw status 筛选时加载或展示。
- API 保留原始 `status/review_state/fact_status` 兼容字段，前端优先消费领域 `display_state`，必要时才由共享 helper 回退映射。
- AI 正文建议在编辑器中以只读预览打开；“采用到工作稿”成功后加载服务端新 draft 并恢复编辑/自动保存。
- deep import/stage 启动入口必须先展示自动采用范围并取得明确授权，完成卡展示 `asset_summary` 的已采用/待处理/未采用三类汇总。

## 结构整理补充

- `sceneWorkbenchView` 是 Scene 管理主入口，支持按 status / source / workflow_id / needs_review / phase 等条件筛选深度导入结果。
- Scene 工作台把机械合并和 AI 融合建议分成两个入口。AI 融合前必须在卡片中选择主 Scene，随后显示字段级预览表：AI 建议、主 Scene 原值、其他来源 Scene 原值并列；保存模式包括保留原 Scene、保存并废弃原 Scene、放弃结果、继续编辑后保存。手动融合输出使用 `source="manual_fusion"`。
- Scene 每行只展示当前最高优先级主操作：复核、查看跨章建议、确认章节定位、整理映射、关联章节、补全设定、编辑。完成一项后刷新为下一项；健康标签可直接执行对应操作。桌面端显示“上下文主按钮 + 编辑 + 更多”，窄屏只显示“主按钮 + 更多”，“更多”固定包含打开写作、合并和拆分。
- 同类 Scene 批量选择显示具体操作；混合选择显示“批量处理”并按问题类型分组，不提供含义不明的一键清除。复核调用后端统一 review 命令，正文定位确认单独提示只接受章节精度。
- 跨章建议来自后端持久队列，刷新后恢复横幅和行内按钮。支持逐条融合与批量忽略，不提供“全部接受”。
- `outlineView` 的剧情线、篇章纲、伏笔、揭示列表支持按 status / deep_import source / workflow_id / needs_review 筛选，用于整理 Phase 3 结构资产。
- 筛选只改变视图，不自动 promote、deprecated 或删除资产；状态变更必须来自明确按钮、选择器或二次确认操作。

## 地图工作台补充

- `mapWorkspaceView` 保存“最近地图”到本地存储
- 可按地图名或地点名搜索
- 支持图层开关
- 右侧消费 `GET /api/world/maps/{map_id}/dashboard`，展示世界动态总控台、动态队列、检查器和批量分组
- 默认进入地图页时通过 `GET /api/world/maps/open-target` 打开最近/可用地图；世界对象行也通过该接口生成带 `focus_entity_id` 的地图 URL
- 地图工作台消费同一套 dashboard / map state，支持“世界动态总控台 / 活地图 / 叙事透镜”三视图、上方语义气泡带、低动效模式
- 地图工作台同时消费 `GET /api/world/maps/{map_id}/playback`，按 typed observation 展示人物旅程、势力变化、危机推进、资源控制和状态变化播放轨道
- 动态队列、语义气泡和播放事件可打开对象信息框；信息框展示名称、类型、时间、状态、来源、地点/空间锚点，并提供修改和打开检查器
- observation 在界面统一显示为待处理，支持采用、忽略、标记冲突，并可在采用前编辑字段、来源引用和字段差异；fact 显示为已采用，支持回滚、废弃、恢复，并保持技术 ID 不进入可见文本
- 写作冲突 AI 修复建议以可编辑草稿展示，用户显式插入当前正文编辑器后才影响草稿内容
- 批量修改分组按对象类型和地图时间展示，可通过 `batch-actions` 对待处理 observation 执行批量采用、忽略和标记冲突；“打开检查器”会按对象聚焦刷新右侧检查器
- `mapLayoutEngine.js` 负责前端自动布局、标签避让、聚合簇和语义气泡排队；`mapView` 浏览态地点中心标签使用该布局结果避免高密度重叠
- 支持从写作流打开最近相关地图

## API 封装风格

- 统一 `request()` 处理超时、错误映射、FormData
- 高风险 wrapper 的 method、path、必需参数和长耗时 timeout 由 `apiContracts.js` 注册，`api.js` 通过 helper 生成实际请求；这只校验请求契约，不覆盖响应字段级 schema drift
- 按模块分组：`api.projects.*` / `api.world.*` / `api.outline.*` / `api.context.*`
- 地图接口统一挂在 `api.world.*` 下，后端前缀仍是 `/api/world/maps`

## 安全与渲染约束

- 动态文本优先走 `textContent`
- 必须插入 HTML 时先走 `esc()`
- 不把用户/AI/API 返回的未转义内容直接写入 `innerHTML`
- `index.html` 通过 CSP meta 建立 baseline：脚本仅允许本源和 ADR-0003 接受的 Leaflet CDN（`https://unpkg.com`），连接仅允许本源、本地 `localhost` 和 `127.0.0.1` 开发后端，并禁止 `object-src`
- 现阶段 `style-src` 仍保留 `'unsafe-inline'`，用于兼容入口和现有静态模板中的 inline style；迁移 inline style 并收紧 `style-src` 留到下一批
