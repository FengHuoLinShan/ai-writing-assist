# Module: frontend / 前端控制台

## 定位

前端为 Vue 3 SPA 控制台，通过 REST API 驱动整个创作工作台。Vue shell 拥有静态外壳，
所有一级业务页主 DOM 由 SFC 拥有；既有 hash router、Proxy 状态、命令服务和 API wrapper
保留为集中式基础设施 seam。业务视图经 `vue/mountIsland.js` 接入 `#workspace-content`
route host，只通过 `vue/bridge/index.js` 访问既有基建，动态内容禁止 `v-html`。动态地图的
Leaflet/Canvas 视口通过 `MapViewportAdapter` 封装保留的 `mapView` controller；这是地图唯一
命令式 DOM seam，不拥有 route-host 页面 DOM。Writing 只通过 `mapQuickCreateBridge` 调用
`mapQuickCreateView`，并复用 `sceneAlerts` / `versionDiff` 纯 helper，没有其他旧视图运行时依赖。

用户体验的目标画像、双入口方向和功能判断门禁以
[`../product/user-personas.md`](../product/user-personas.md) 为准。前端正确性不仅指请求与状态
正确，还包括目标用户能否无需技术或专业写作知识理解当前状态、完成高频任务并安心返回。

## 用户体验基线

- 每项用户可见能力明确服务作家、RP 用户或两者；不要求所有页面同时服务所有画像。
- 作者路径提供完整控制、证据、版本和专业整理能力；RP 路径提供自然语言开场、故事、分支、
  回顾和持续观看，不先暴露完整作者后台。
- 首屏围绕当前任务，只保留做决定所需信息；主操作、当前状态和下一步无需阅读说明即可理解。
- 使用用户语言呈现。raw ID、JSON、Prompt/token、内部枚举和诊断字段不得成为默认工作流。
- 高频查看与回顾就地完成；跨页时保护草稿、筛选、滚动、选择和长任务进度。
- 首次进入、空态、加载、失败/冲突、保存成功、撤销/回滚和窄屏不是装饰状态，而是适用功能
  的验收面。

## 架构

- 入口：`index.html`
- 基础样式：`styles.css`
- 全站主题覆层：`editorial-theme.css`
- 全局状态：`state.js`
- 状态切片 helper：`stateSlices.js`
- 路由：`router.js`
- API 封装：`api.js`
- API 契约注册表：`apiContracts.js`
- 静态外壳：`vue/shell/`（topbar/sidebar/命令栏/主题/快捷键/service hosts）
- 业务视图：`vue/views/**`（Vue SFC，经 `vue/mountIsland.js` 注册）
- 命令式接缝：`router.js`、`state.js`、`api.js`、集中式 `shared/` / `ui/` 服务，
  以及仅在 Vue 地图视口内运行的 `views/mapView.js`
- Writing 兼容接缝：`vue/views/writing/controllers/mapQuickCreateBridge.js` 是
  `views/mapQuickCreateView.js` 的唯一业务调用路径；`views/writing/sceneAlerts.js` 和
  `views/writing/versionDiff.js` 是无 DOM 纯 helper
- Vue 基建：`vue/bridge/`、`vue/composables/`、`vue/mountIsland.js`
- 通用交互：`shared/`、`ui/`

当前 router 识别的 hash 名称为：

- `home`
- `project`
- `today`
- `journeys`
- `interaction`
- `writing`
- `world`
- `map`
- `rag`
- `outline`
- `scene`（兼容重定向，不渲染独立页面）
- `generate`
- `settings`
- `project-settings`
- `llm`（兼容重定向，按当前项目状态跳转到项目设置或全局设置）

除上述两个无业务 DOM 的兼容重定向外，13 个实际路由目标的主 DOM 全部由 Vue SFC 拥有。

旧 `context` hash 不再作为一级页面注册；路由初始化或浏览器前进/后退遇到它时，会重定向到 `generate?tab=task`。

## 当前页面职责

| 视图 | 当前职责 |
|------|----------|
| `vue/views/interaction/HomeChoiceView.vue` | `home` 路由；作者入口校验当前账户的已选作品并智能续接 `today`，无有效作品时回作品档案；RP 卡使用“进入互动故事”并解释一次角色扮演（RP） |
| `vue/views/interaction/JourneyListView.vue` | `journeys` 路由；扁平旅程列表、新旅程、归档入口和按需搜索 |
| `vue/views/interaction/InteractionView.vue` | `interaction/{journey_id}` 路由；故事阅读、composer、流式恢复、分支、回顾、看海与右侧定位 |
| `vue/views/project/ProjectView.vue` | `project` 路由（Vue island）；紧凑作品档案，默认主操作为“继续创作”，搜索/筛选单行展示；批量、编辑、删除和回收站只在“管理作品”模式出现；无作品时优先显示新建与导入 |
| `vue/views/today/TodayView.vue` | `today` 路由（Vue island）；一个续写/第一章/继续整理主卡，待处理汇总和最多 3 个项目隔离的长任务恢复；摘要失败不阻断写作，未知状态保留并允许重试 |
| `vue/views/rag/RagView.vue` / `vue/views/outline/components/OutlineHeader.vue` / `vue/views/scene/SceneWorkbenchView.vue` / `vue/views/world/WorldView.vue` / `vue/views/world/components/WorldReviewTab.vue` | 可切换子导航使用原生 button，当前项公开 `aria-current="page"`；Scene 工作台当前项保持非交互，避免同路由刷新 |
| `vue/views/writing/WritingView.vue` | 工作稿编辑器、场景参考与 AI 建议采用；自动保存明确区分已保存/保存中/失败本地备份，“设为正式正文”继续调用原发布 API 并明确不会对外发布；版本、冲突、导出和导入收进分组菜单，菜单动作完成后关闭且不会被页头裁切 |
| `vue/views/world/WorldView.vue` | `world` 路由（Vue island）；对象库普通/热点双模式、统一待处理（对象/关系/别名）、历史筛选；热点模式显示重要/近期热点聚合并使用服务端全量排序；世界书编辑概览/结构化 sections、管理页面模板和 AI 参考规则，并以“工作稿保存 → 明确发布”维护页面；不承载 AI 对话侧栏，只提供“用 AI 完善此页”保存后跳转；展示只读作者版世界观简介及版本/自动维护状态；`map` 子标签现在只做兼容跳转 |
| `vue/views/map/MapWorkspaceView.vue` | 地图一级工作台，总览、最近地图、地图树、收件箱、图层开关、搜索、聚焦；世界动态总控台、活地图、叙事透镜、Scene 时间轴与连续性检查。动态队列、历史、活地图当前事实与叙事透镜时间线的标题均为同名原生按钮，可用键盘打开详情；整卡点击仍是鼠标快捷方式，采用/忽略不会触发详情。 |
| `views/mapView.js` | 仅作为 `MapViewportAdapter` 下的 Leaflet/Canvas viewport controller：地形、地点、标记、线路、势力范围与编辑会话；不拥有一级页面 DOM |
| `vue/views/outline/OutlineView.vue` | `outline` 的 Vue island 主视图；顶层为“故事总览、篇章、剧情线、场景”。故事总览的 AI 预览使用结构化重复项编辑器，提交时适配回原 wire payload；版本历史不可原地改写 |
| `vue/views/scene/SceneWorkbenchView.vue` | 由 `outline/scenes` 承载的 Scene 普通/热点双模式、管理筛选、当前剧情定位、拆分/合并/替换、复核与自动提取整理；旧 `scene` 路由仅作兼容重定向 |
| `vue/views/rag/RagView.vue` | `rag` 路由（Vue island）；普通路径只显示查找。资料未准备好时提供“修复查找功能”，索引、worker、embedding 等技术状态只在诊断详情中出现 |
| `vue/views/generate/GenerateView.vue` | 生成中心：world 共创对话、来源与上下文选择、结构化预览和工作稿应用；同时承担 suggestion-bound 未应用提案编辑的恢复、上下文任务预览/编译、POV、模板与既有领域流程 |
| `vue/views/settings/GlobalSettingsView.vue` | `settings` 路由（Vue island）；管理账户级 DeepSeek/Kimi 模板与 Key、只读余额和全局作者偏好；作者偏好的字体、专注模式显示为中文，保存/传输/存储仍使用稳定底层值（字体枚举与专注模式布尔值） |
| `vue/views/settings/ProjectSettingsView.vue` | `project-settings` 路由（Vue island）；只管理深度导入参数和项目作者偏好，不提供项目级 provider/model/Key；作者偏好的字体、专注模式显示为中文，保存/传输/存储仍使用稳定底层值（字体枚举与专注模式布尔值） |

## 路由与状态特性

- `router.js` 使用 `Map` 维护视图、异步 loader、pending loader 与最后子标签注册表；动态 key
  必须通过小写路由白名单并拒绝 `__proto__`、`prototype`、`constructor`，避免把路由输入解释为
  对象原型属性。主视图切换后仍恢复最后子标签，公开 hash 与生命周期契约不变。
- 作者 shell 的桌面主导航固定为“首页、写作、人物与世界、故事结构、地图、查找”；移动端固定为
  “首页、写作、世界、结构、全部”。项目切换器位于导航顶部，高级入口保留旧路由但只从“更多”
  或上下文错误进入。`today` 是作者有效项目的默认续接页。
- `home/journeys/interaction` 使用独立 RP 壳，不显示作者 sidebar；合法深链不要求先选择
  author 项目。RP 草稿按旅程保存在本地，服务端流式 buffer/分支/回顾负责跨刷新恢复。
- `outline` 的规范默认子视图是 `story-outline`，作者导航层级为“故事总览 → 篇章 → 剧情线 → 场景”。旧 `scene` 路由重定向到 `outline/scenes`；旧 `outline/foreshadowing` 与 `outline/reveals` 重定向到剧情线的信息推进区域。
- router 不再保留 KeepAlive/DocumentFragment 缓存；所有视图离开时卸载。写作快照、Outline/Scene workflow 与滚动位置采用显式项目隔离 session 恢复，详见 [ADR-0009 附录 A](../adr/0009-appendix-a-keep-alive-policy.md)
- 世界对象库和 Scene 工作台使用 `mode=normal|hot`；URL 优先于按“项目 + 页面”保存的 localStorage 偏好，无偏好默认热点。切换模式保留通用筛选，清除模式专属筛选、分页偏移和批量选择。
- Scene 工作台的筛选、详情和复核状态由 `useSceneWorkbench` 持有；当前 Scene 与模式通过 `outline/scenes?mode=...&scene_id=...` 写入浏览器历史。热点默认请求 `anchor=latest`，显式 Scene、分页、阶段或管理筛选时不自动锚定。
- `map` 路由会解析 query 上下文，用于承接写作页和世界页跳转
- `world/map` 仍保留入口，但现在会自动跳转到一级 `map`
- `settings` 是无项目也可访问的账户设置页；`project-settings` 依赖当前作者项目，未进入项目
  时显示空态并提供返回账户设置
- `llm` 是旧入口兼容别名：有当前项目时跳转 `project-settings`，否则跳转 `settings`
- `errorLogger.js` 的右下角错误徽标是当前项目/未关联项目范围的原生计数按钮；其非模态诊断面板用原生 DOM 与 `textContent` 展示已脱敏的记录。关闭返回徽标，清空必须在同一面板二次确认且只删除当前范围；`window.errorLog.clear()` 仍可供程序直接清空当前范围。
- 世界关系审查等命令式预览使用 DOM 节点与 `textContent` 组合动态内容，不把对象名称、关系类型
  或 API 文本送入 `innerHTML`。地图遥测 ID 只使用 Web Crypto：优先 `randomUUID()`，兼容环境
  使用 `getRandomValues()`，安全随机源不可用时不降级到 `Math.random()`。
- Shell 单键业务快捷键在表单、命令栏、快捷键帮助和既有业务 modal 中不触发；只有既有 workspace action 实际处理成功时才消费原始按键，避免同步聚焦的新字段收到触发字符。
- Vue 视图生命周期（ADR-0009）：`onEnter` 预取数据（router 会 await）→ `render` 返回挂载点
  div → `onRendered` 挂载（同视图 forceRefresh 先卸载残留实例）→ `onLeave` 卸载。
  `mountIsland` 为异步 `load()` 维护代次；新加载或 `onLeave` 会使旧请求失效，防止晚到数据
  覆盖当前 props。实际页面均使用该契约，兼容路由只重定向；不再有另一套 KeepAlive 生命周期
- 跨项目导航采用“同步预检 → 立即退出旧项目 → 中性过渡 → 目标提交”：`canLeave` 和有修改
  modal 任一拒绝都保持原 state/DOM/hash 且不请求目标；通过后在旧项目上下文中恰好执行一次
  `onLeave`，目标元数据返回前旧内容与操作已经移除。router 分开记录 mounted、pending 和
  failure；只有 `onEnter → render → onRendered` 全部成功才标记 mounted，快速切换与晚到结果
  由 abort + generation 丢弃。临时跨项目失败可重试目标或返回项目列表；同项目临时 refresh
  保留编辑页，权限或项目失效则立即退出。完整契约见 [ADR-0009 附录 A](../adr/0009-appendix-a-keep-alive-policy.md)
- 旧 `context` hash 会重定向到 `generate?tab=task`；上下文任务预览和编译入口由生成中心承担

## 对象引用交互契约

- 作者操作区以名称和语义信息选择对象，不要求记忆或粘贴 UUID。`shared/referencePicker.js`
  统一提供单选、多选、数量上限、类型切换、异步搜索、已选标签、键盘操作和不可用引用展示。
- 选择器内部条目统一为 `{ kind, id, label, description, status }`；页面提交时仍只向现有
  `*_id` 或 ID 数组字段写入 `id`。HTTP API、URL、缓存、Pydantic schema 和 wire shape 不因展示改造而变更。
- 各领域使用本模块现有列表/详情接口实现 `search(query, context)` 和
  `resolve(ids, context)`，不增加跨模块聚合 API。查询必须携带当前 `novel_id`，并使用 abort、
  项目 ID 和页面生命周期代数拒绝搜索或项目切换后的晚到结果。
- 同名结果必须附带类型、状态、章节/Scene 或摘要消歧；UUID 不作为主标签。历史数据中
  已归档或无法解析的引用显示为“不可用引用”，只有作者主动移除时才会从编辑值中删除。
- Scene 单行合并、生成中心的相关对象/人物/Scene/POV、智能去重兼容面板和世界书资产引用
  均按名称选择。世界书固定 AI 参考目标只允许已采用世界对象或已发布页面；通用 AI
  参考弹窗通过资料卡执行“本次排除”，不再暴露手填排除 ID。
- Workflow、任务和原始 Scene ID 只能出现在折叠的诊断区，可用于粘贴、复制和精确排障，
  并必须标记 `data-diagnostic-field`。

## 内容优先布局契约

- 项目页使用“作品档案”首屏和非对称项目网格：当前项目始终置顶，首张卡占更大版面；
  其余项目按最近更新时间排序。视觉层只消费既有标题、题材、阶段、简介和统计字段，
  不新增封面数据或 API；`760px` 以下收敛为单栏，`390px` 不产生页面级横向溢出。
- 全部一级页面、子标签、弹窗、表格和辅助栏共用“编辑档案”主题：米白纸张、深蓝结构线、
  朱红索引与低圆角几何编排。`styles.css` 保持结构布局，`editorial-theme.css` 作为后加载
  覆层拥有视觉表达；路由在 `#workspace-content` 写入 `data-workspace-view/subview` 只供样式
  定位，不得被业务逻辑、数据请求或测试 fixture 当作状态来源。
- 功能性按钮、输入框、选择器和编辑区要比只读内容更易辨识，但不脱离主题：主操作使用深蓝
  实体面与朱红索引线，普通操作保留可见边框；可编辑字段使用纸张底、完整边框与左侧功能线，
  focus-visible/聚焦切换朱红并显示焦点环。暗色主题保持相同层级；`760px` 以下常用按钮高度
  不低于 `42px`，输入控件不低于 `44px`。
- 创作工作台以正文、主列表、编辑区、生成结果和地图画布为主对象；桌面端主对象目标占分栏内容宽度的约 `64%–68%`。
- Vue 页内的主题化辅助栏由 SFC 模板渲染，并以 `项目 + 页面 + 栏位` 为 key
  在 `sessionStorage` 保存折叠状态。辅助栏折叠不得重置选择、筛选、滚动位置或未保存编辑内容。
- 卡片/表格、展开/收起、选中与其他纯呈现控件只更新局部状态；同路由仅需同步
  hash query 时使用 router 的就地 query seam，不重新执行 `onEnter/render`。确需重取
  服务端数据的操作也必须在返回后复核发起时的项目、路由/编辑器 owner，不得用旧响应
  重挂载用户已切换到的页面。同路由强制刷新恢复工作区纵向滚动位置。
- 写作专注模式高于普通辅助栏状态；中等宽度重排第三栏，`760px` 及以下使用单栏、抽屉或手风琴，不允许产生页面级横向溢出。
- Vue 业务页使用 `vue/components/WorkflowProgressCard.vue` 渲染任务卡：普通运行/完成态
  显示紧凑摘要，失败或调用方标记 `attentionRequired` 的恢复、重试和确认状态
  默认展开；用户保存状态优先于自动规则。
- `shared/smartDedup.js` 对 schema v2 结果打开 `{size: "large", protectUnsaved: true}`
  双栏工作台；队列、对比、主对象和逐成员动作共享同一个 group 草稿。
  对比默认“只看差异”；勾选操作与切换合格主对象会保留工作台滚动位置，且主对象 radio
  及当前控件焦点，且主对象 radio 必须使用真实 asset ID，不能退化为浏览器默认值。
  Scene merge 进入已就绪前必须调用现有 Scene merge preview 并由用户确认。
  工作台不把 `needs_review` 或“稍后处理”发到 apply API，也不允许手填任意主对象 ID。
- 折叠栏和进度摘要必须使用现有设计 token，并覆盖 hover、focus-visible、disabled、错误、暗色主题和 `prefers-reduced-motion`，不得暴露浏览器默认折叠标记。

## 开发与验证脚本

- 开发服务器使用 Vite：`npm run dev`，默认端口 8080，可通过 `FRONTEND_PORT` 覆盖。
- 单元测试使用 Vitest：`npm run test`；监听模式为 `npm run test:watch`。
- 浏览器 E2E 使用 Playwright：`npm run test:e2e`；烟雾子集为 `npm run test:e2e:smoke`。默认启动 fresh 8000/8080 服务，只有 `PW_REUSE_EXISTING_SERVER=1` 才复用已有服务；后端启动前执行 `APP_ENV=test alembic upgrade head`。`APP_ENV=test` 不改写 `DATABASE_URL`；本机存在开发 worker 时应显式传入独立测试库。如端口被旧服务占用，使用 `BACKEND_PORT=8010 FRONTEND_PORT=8090 PW_REUSE_EXISTING_SERVER=0`。
- `npm run test:all` 先跑 Vitest，再跑 Playwright。
- `npm run build`（vite build）仅作 Vue 构建链冒烟验证：`dist` 仍缺少 classic 基础设施 seam scripts，不能视为可部署产物。无独立 lint/format 依赖；前端静态约束以现有测试和 `git diff --check` 为主。
- 当前已落地共享 JS API 契约校验第一阶段，覆盖项目、设置、导入、上下文、世界/地图、写作冲突检查和 RAG 的高风险 wrapper 子集；TypeScript / OpenAPI codegen 仍是未来设计项，当前说明见 `docs/frontend/typescript-api-contracts.md`。
- 小说检索继续消费 context evidence API：单次最多取回 100 条现有命中，DOM 首批只挂载
  20 张结果卡并按 20 条渐进加载。章节范围的非整数、非正数或倒置条件会在请求前提示并保留给作者修正，不会被伪装成空结果。检索词、方式、正文版本、可见视角、章节范围和 scope
  保存在 hash URL；前进/后退会恢复表单并重新检索，显示游标和证据抽屉不持久化。同项目内在
  “查找 / 状态”间往返保留已执行结果和未提交筛选；切换项目时统一清空。新查询会
  就地 push hash query 并执行检索，不重挂页面或重取状态数据；同时 abort 旧请求，晚到响应还需
  通过 project/lifecycle generation 才能回写；证据抽屉使用独立
  abort/generation/project/drawer 门禁，关闭抽屉或切换项目后不接受旧正文、引用或导航结果。
  作者视角的聚合卡会为每个实际命中范围展示所属 Scene 位置和摘要，
  并用项目隔离的写作台 Scene 快照标记“当前/前序/后续”关系；同章多 Scene
  会逐个展示摘要和跳转入口。读者/角色视角不显示这些作者专用元数据，
  不将“因可见性被隐藏”误报为“未关联 Scene”。
- 任务进度卡仅依据后端 `available_actions` 显示 retry；RAG 和世界书投影在 retry 成功后恢复原 task id 的轮询，请求失败时保留原失败卡。创建 RAG 维护任务的写请求不随视图卸载取消，避免服务端已入队而浏览器丢失 task id；离页只停止轮询与晚到 UI 投影。
- 生成中心 world 工作区默认开启作者版世界观简介，可按会话关闭；“查看本次上下文”读取响应中的实际 `context_usage`，不事后重编译。来源页面正文与服务器工作稿始终由服务器重载；本地 v2 会话按项目 + 来源页 + target 隔离，只缓存对话、选择项、suggestion ID，以及 schemaVersion=1、精确绑定当前 pending suggestion 的作者未应用提案编辑。刷新或离开时仍在等待的聊天助手气泡仅在本地副本转为可见的中断终态，不自动重试且不进入后续聊天请求。该版本化 working copy 受 512 KiB / 最多 5 个会话边界约束，不代表 canonical 或服务器工作稿；匹配 suggestion 才恢复，成功应用或作者确认放弃后清理。任务页签只编译/预览上下文；POV 明示并强制禁用作者全知简介。
- 生成中心模式导航是受限 tab/tabpanel surface：方向键和 Home/End 只 rove 焦点，Enter/Space 继续走既有切换和离开确认；任务预设、世界目标和对象模板以可访问选择态公开当前值，任务原生字段与可见标签关联。
- 生成中心任务页签选择章节后，Scene 选择器先展示该章的可用 Scene，同时仍可按名称搜索项目内其他活跃 Scene。
- 生成中心角色视角正文在 lazy load 期间显示加载态；只有已成功确认零章节才显示前置条件空态，隐藏生成表单和顶部动作，并复用写作台/世界设定入口。加载错误保留 warning，不得被呈现为零章节。
- 世界书、生成中心和通用 AI 参考弹窗只列出已发布 Activation Profile；只有作者显式选择后才随请求发送。世界书规则编辑器提供受限表单和 dry-run trace，不提供 raw JSON、regex 或 Prompt 插槽。世界书存在未保存修改时，“用 AI 完善此页”必须先保存成功再跳转；生成中心页面 apply 只写工作稿，成功后带页面/工作稿 ID 返回世界书。中等宽度把第三栏下移，窄屏改为单栏且不得产生页面级横向溢出。
- 世界书编辑器把“保存并发布”作为始终可见的主操作；只有“保存工作稿”不会改变正式页。
  保存回包直接对账页内工作稿集合，不重挂编辑器，也不重置焦点、光标或当前页面选择。
  世界观简介的终止任务 ID 不得在同一页面生命周期内重新挂回轮询，避免失败刷新反复重绘并
  阻断点击。
- 世界书类别、简介状态与投影状态默认使用作者可读中文；投影恢复键、任务 ID、原始状态和
  后端 warning 只放在折叠的“诊断信息”中，不在设定正文和主操作区直接展示。

## 写作流补充

`vue/views/writing/WritingView.vue` 当前不只是草稿编辑器，还承担：

- Scene 树导航
- 自动保存与未保存提醒
- 版本历史/恢复
- 读取项目生效作者偏好并驱动日目标、编辑器字体和默认专注模式；优先使用设置服务的项目/全局继承结果，旧本地值只作为接口失败时的兼容回退
- 深度导入进度展示：恢复 localStorage 中的 task_id，展示当前章节 / Scene / batch、质量统计、降级状态和中断恢复提示
- 深度导入完成后只展示一个地图下一步：已有地图进入项目收件箱；有 canonical 地点但无地图时
  打开 quick-create；只有 candidate 地点时按地点类型、deep-import 来源和 workflow 精确进入审核。
  有下一步时完成条保留到用户执行或关闭，刷新后可恢复；上下文加载失败、
  弹窗被拦截或回调失败不得清理完成条。恢复/轮询/下一步的异步响应绑定启动时
  project/task/workflow，项目切换或新任务后的晚到响应不再写回当前页面。
- 中断恢复操作：用户显式点击“继续”才调用 `/api/imports/deep/resume`；“放弃恢复”必须二次确认并展示清理摘要
- `GET /api/world/maps/scene-summary` 的地图摘要展示，包括危机、风险和空间 warning
- 跳转到地图工作台并携带 `scene_id` / `focus_entity_id`

## 作者展示状态

- `shared/assetDisplayState.js` 是前端唯一通用映射：结构资产显示“待处理 / 已采用 / 历史”，正文显示“待处理 / 工作稿 / 正式正文”。页面不得自行再维护 `candidate` / `canonical` 文案表。
- `attention_reasons`、低置信、冲突和 `needs_review` 显示为注意标签，不替代主状态。
- 主列表默认隐藏历史；只有显式选择历史/raw status 筛选时加载或展示。
- API 保留原始 `status/review_state/fact_status` 兼容字段，前端优先消费领域 `display_state`，必要时才由共享 helper 回退映射。
- AI 正文建议在编辑器中以只读预览打开；“采用到工作稿”成功后加载服务端新 draft 并恢复编辑/自动保存，“拒绝建议”经确认后软废弃候选并回到当前工作稿/已发布稿。顶部“AI 续写”只对服务端已保存的可写或已发布 base draft 开放，不拿未保存本地文本或跨章 Scene 作为替换范围；异步任务轮询没有前端总截止时间，完成后自动打开候选审核面板。普通生成的 `pov_validation=not_applicable` 不显示角色视角失败提示。
- 生成中心的角色视角正文按“章节 + Scene + POV 角色”确认上下文；已有目标章时锁定完整 active 正文，候选仍是该章完整替换稿，Scene 即使跨章也不扩大范围。结果卡固定显示该次请求的 Scene 与 POV 角色，不随生成后的表单选择漂移。结果入口跳转写作台统一审核，POV 面板只描述知识边界诊断，不把“未发现明显越权”显示成整体质量通过。
- deep import/stage 启动入口必须先展示自动采用范围并取得明确授权，完成卡展示 `asset_summary` 的已采用/待处理/未采用三类汇总。

## 世界对象分组复核

- 待处理导航与对象/别名/关系子标签复用现有三个列表接口的 `total`，不单独维护计数 API。
- 关系按有向对象对、别名按所属对象分组。每页 20 / 50 组，全选仅作用于当前可见项；搜索常驻，高级筛选折叠，当前条件同步显示为可删除标签。
- 待处理别名与关系的高级筛选控件提供明确中文可访问名称；Workflow ID 仍收在“诊断筛选”内并标记为诊断字段，筛选与分页查询语义不变。
- 关系复核先准备 `accept` / `merge` / `ignore` 决策；仅相同类型或落入同一保守映射的候选默认勾选。卡片显式提示反向关系但不自动归并，抽屉在提交前预览最终端点、类型、强度和证据范围。
- 端点搜索覆盖同项目 canonical / draft / candidate 对象，排除历史对象和 suggestion shadow，不依赖对象库当前首页。
- 未收录的别名/关系类型以“保留原类型”打开；类型建议只有在用户点击后才更改草稿。置信度只用于筛选/预选，不自动采用。
- 批处理一次确认只发送一个请求，并在客户端先校验关系 20 个决策 / 50 条所选成员、别名 50 条的上限。成功项移出当前选择并自动进入下一组；`stale` / `failed` 项在原卡片显示原因并保留选中与决策草稿，网络异常不丢草稿。筛选、分页和滚动位置在就地刷新后保留。
- 世界对象的卡片/表格只切换当前组件呈现并就地同步 query；筛选表单的未应用副本
  放在现有 `worldSession` 中并精确绑定 query 签名。同项目分页、热点/全部资料切换或后台
  必要刷新可恢复草稿；外部深链、子页或项目变更仍以新 URL 为准。
- Outline 篇章/剧情线同样区分已应用 query 与编辑中筛选：翻页只改已应用条件的页码，
  不隐式提交未点“应用”的控件值；同 query 重挂载恢复草稿，各子页草稿相互隔离，
  外部 query 或项目变更时以新路由为准。
- compatibility shadow 仍由建议队列拥有；其内联别名在分组复核页只显示“随对象建议处理”，不进入多选或批处理。
- 默认卡片不展示 UUID，只展示“来源 · Scene · 章节 · 强度/置信度”和短引用；Workflow、Scene UUID 与证据引用收进可复制的诊断区。关系字段始终称为“强度”。
- 桌面使用右侧抽屉；390px 变为全屏复核页，复核搜索和主操作按钮高度不小于 44px。

## 结构整理补充

- `OutlineStoryTab.vue` 及 `useStoryOutline` 只管理 StoryOutline 聚合，不会因为采用总纲而创建 PlotThread、OutlineArc 或 Scene。当前版完整展示 title、creative core 四字段、`outline_markdown`、`major_storylines`、`macro_movements` 和 `open_decisions`。手工保存、AI preview apply 和历史采用都带 current `base_revision_id` 与 `idempotency_key` 创建新 revision；同一 payload 重试保持 key，内容或 base 改变后轮换。409 保留当前编辑草稿，显式重新加载后把它 rebase 到最新 current。
- StoryOutline AI 请求只接受作者意图、计划尺度、覆盖描述、可为空的显式人物/世界对象选择和 `include_current_outline`，不提供起止章或强制模板/数量；显式选择为空时由后端自动使用 Top-K。返回内容以 strict 完整 preview 编辑，三个嵌套数组用带字段说明与错误提示的 JSON 编辑区。导航数组是辅助摘要，不要求名称唯一或精确字符串引用；生成完成不自动采用。
- 生成恢复复用通用 workflow 记录与 `/tasks/{id}` 轮询/取消，但只恢复同一 project、`task_type=story_outline_generate` 且 `action=outline.story_outline.generate` 的任务。完成结果允许服务端附带 `managed_llm_steps` provenance；已标记 adopted 的 task 不重复恢复为可采用 preview。路由离开或项目切换后丢弃晚到响应；取消、过期、任务上下文不匹配和短暂查询失败保持不同的作者可读状态。

- `vue/views/scene/SceneWorkbenchView.vue` 是 Scene 管理主入口，支持按 status / source / workflow_id / needs_review / phase 等条件筛选深度导入结果。
- Scene 工作台把机械合并和 AI 融合建议分成两个入口。AI 融合前必须在卡片中选择主 Scene，随后在大尺寸语义表格中并列展示 AI 建议、主 Scene 原值和其他来源 Scene 原值；拆分使用“原 Scene / 建议 A / 建议 B”对比。两类预览覆盖语义字段、叙事标签、POV 和章节映射，默认显示全部字段并可只看初始差异；AI 建议保持完整可编辑，长来源证据按需展开。融合预览是同步 LLM 请求，API contract 使用 90 秒生成窗口。叙事标签把空值规范为 `draft`（未标注），拆分字段支持显式清空。保存模式包括保留原 Scene、保存并废弃原 Scene、放弃结果、继续编辑后保存；废弃来源必须在预览内再次确认，所有融合保存入口共享单次请求锁，失败时恢复操作并保留当前编辑。手动融合输出使用 `source="manual_fusion"`。
- 重复提取的 replacement suggestion 使用专用对比面板，展示受保护原 Scene、新候选、边界/章节重叠证据，并提供“保留原 Scene / 直接替换 / 编辑后替换”。历史列表区分“原已采用 · 重复提取替换”，替换后提示世界对象和剧情结构需按需刷新。
- Scene 每行只展示当前最高优先级主操作：复核、查看跨章建议、确认章节定位、整理映射、关联章节、补全设定、编辑。完成一项后刷新为下一项；健康标签可直接执行对应操作。桌面端显示“上下文主按钮 + 编辑 + 更多”，窄屏只显示“主按钮 + 更多”，“更多”固定包含打开写作、合并和拆分。
- 同类 Scene 批量选择显示具体操作；混合选择显示“批量处理”并按问题类型分组，不提供含义不明的一键清除。复核调用后端统一 review 命令，正文定位确认单独提示只接受章节精度。
- 跨章建议来自后端持久队列，刷新后恢复横幅和行内按钮。支持逐条融合与批量忽略，不提供“全部接受”。
- 剧情线、篇章纲与 Scene 工作台的 P20 表单都先验证当前 StoryOutline，支持新增设计或修订
  所选，恢复 `outline_generate` 任务，并展示完整可编辑 JSON preview、重叠资产、作者决策与
  总纲冲突。采用时保留 409 错误和编辑内容。P20 不进入生成中心。
- 剧情线详情把同一 `information_movement_id` 的伏笔/揭示按章节合成时间线；无 active 线程
  关联的计划进入“未归入剧情线”，作者通过现有 API 分配。旧入口打开后滚动到该区域。
- `OutlineView.vue` 的剧情线、篇章纲与底层伏笔/揭示数据继续支持 status / deep_import source /
  workflow_id / needs_review 筛选；后两者只在剧情线页内部消费，不再占顶层导航。
- 筛选只改变视图，不自动 promote、deprecated 或删除资产；状态变更必须来自明确按钮、选择器或二次确认操作。

## 地图工作台补充

- `vue/views/map/MapWorkspaceView.vue` 保存“最近地图”到本地存储；总览主操作按状态如实显示“打开最近地图 / 打开可用地图 / 查找可用地图”，陈旧记录清除后立即刷新卡片与按钮文字，点击仍复用既有最近/可用地图回退流程
- `MapQuickCreateDialog.vue` 的字段、地点选择、半径、方向移动与锁定均以作者可读的可访问名称公开；画布、视觉工作流和既有坐标/半径/锁定命令保持不变
- 可按地图名或地点名搜索
- 支持图层开关
- 右侧消费 `GET /api/world/maps/{map_id}/dashboard`，展示世界动态总控台、动态队列、检查器和批量分组
- 默认进入地图页时通过 `GET /api/world/maps/open-target` 打开最近/可用地图；世界对象行也通过该接口生成带 `focus_entity_id` 的地图 URL
- 地图工作台消费同一套 dashboard / map state，支持“世界动态总控台 / 活地图 / 叙事透镜”三视图、上方语义气泡带、低动效模式
- 地图工作台同时消费 `GET /api/world/maps/{map_id}/playback`，按 typed observation 展示人物旅程、势力变化、危机推进、资源控制和状态变化播放轨道
- 地图工作台消费 `GET /api/world/maps/{map_id}/timeline` 与 `/state-at`，按真实 Scene stop
  步进或播放类型化差分；正式状态、冲突和 candidate preview 分区展示，candidate 不进入
  当前 Scene 的有效状态
- 时间轴只读覆盖地点轨迹、范围变化、危机和线路状态，不写回 marker、territory、terrain
  或 path。编辑开始、地图切换或请求失效时暂停播放并清理覆盖；连续性面板只报告缺失锚点、
  路线未知/不通/阻断和线路版本变化，不把 Scene 顺序解释成旅行时长
- 动态队列、语义气泡和播放事件可打开对象信息框；信息框展示名称、类型、时间、状态、来源、地点/空间锚点，并提供修改和打开检查器
- observation 在界面统一显示为待处理，支持采用、忽略、标记冲突。作者编辑器只发送
  复核状态、目标名和类型化作者值；UUID、raw JSON、内部枚举、来源证据/时间与原始
  置信度不再作为可回写输入。fact 显示为已采用，支持回滚、废弃、恢复；“复制诊断信息”
  仅从 allowlist 组装一次性、只读、递归脱敏的剪贴板内容。
- 地图总览显示项目级“地图收件箱”，只包含未分配 candidate/conflicted。可按类型、Scene、
  来源、置信度和服务端 eligibility 筛选与分页；“分配并继续”先分配 active 地图，再打开规范
  地图 URL 和同一 observation 编辑器。换图、退回收件箱、忽略、编辑、确认和批量审查都携带
  当前 `updated_at`；409 保留作者输入并展示最新服务器摘要。
- 地图收件箱把 `deep_import_delta_event` 等内部来源转换为作者可读标签；已有 Scene/章节
  锚点时不再同时显示“缺少来源”提示。原始 Scene ID 只出现在诊断筛选或复制诊断信息中。
- 人物位置、事件发生地、线路/阻隔和势力范围使用各自的对象、地点、active path 或 hex
  选择器生成完整 canonical value。采用按钮只消费服务端 `eligibility.can_confirm`，前端不复制
  资格判断；390px 保留轻量审核，复杂线路和势力空间编辑继续转交桌面端。
- 写作冲突 AI 修复建议以可编辑草稿展示，用户显式插入当前正文编辑器后才影响草稿内容。冲突详情的导航动作只在持久化证据带有可用正文范围，或受支持的来源模块/打开目标时启用；不可用时保留禁用且明确的标签，既有处理函数与 API 契约不变。
- 世界书展示模式和筛选分类公开当前选中状态；未保存修改确认、偏好持久化及 API 契约不变。
- RP 旅程目录的归档、恢复与永久删除操作公开关联旅程名；故事页的分支选择、抽屉关闭和加载/失败状态提供程序化语义，不对流式正文或字数统计增加 live announcement，既有故事、分支、归档和 API/wire 契约不变。
- 公共认证和账号删除的邮箱验证码输入、认证忙碌状态与成功/失败通告可被辅助技术识别；账号设置关闭操作具有明确名称，既有认证、注销、删除恢复期及 API/wire 契约不变。
- 账户模型模板与项目设置页签支持方向键、Home/End 的选择和回焦，并保持 tab/panel 稳定关联；已有连接、刷新、保存和数据加载状态公开忙碌或状态语义，不改变模型连接、项目继承、保存/重置或 API/wire 契约。
- 章节前后导航、Scene 展开和大纲浮窗章节链接提供作者可读名称，并公开当前章节或展开状态；既有选择、收起与路由/API 契约不变。
- 地图总览搜索与 Scene 阶段修复输入提供程序化名称；地图视图模式和阶段修复维度公开当前选中状态，不改变既有路由或 API 契约。
- 390px 写作页默认折叠章节辅助栏；作者展开章节后使用带程序化名称的速记编辑器保存短文本
  工作稿，刷新后从后端版本恢复。速记输入实时同步同一编辑状态，首次保存返回的 draft
  id/version 会回写以支持连续保存，切换完整编辑器时保留未保存正文。速记主操作不低于
  44px，且首屏操作区保持在移动底栏上方；发布、版本恢复和长篇结构编辑仍转交桌面端。
- 批量修改分组按对象类型和地图时间展示，可通过 `batch-actions` 对待处理 observation 执行批量采用、忽略和标记冲突；“打开检查器”会按对象聚焦刷新右侧检查器
- `mapLayoutEngine.js` 负责前端自动布局、标签避让、聚合簇和语义气泡排队；`mapView` 浏览态地点中心标签使用该布局结果避免高密度重叠
- 地图 URL 规范模式为 `overview/recent/dashboard/live/lens`；旧 `mode=map` 会
  replace 为 `mode=live`。跨地图和返回总览使用 push，同地图 mode/Scene/focus 使用 replace。
- 浏览态标签/聚合簇使用专用 Leaflet pane，点击先打开地点信息流；空白背景指针
  继续由 Canvas 处理。390px 保留地图浏览、证据查看、确认/忽略及人物/事件地点的轻量修改；
  势力 hex、线路创建/节点精修等复杂空间编辑显示只读摘要和桌面端转交。
- 地图编辑的当前图层、图层结构和保存全部共用同一 apply 会话；从冻结 revision/命令到服务端
  状态、图层树和线路重载完成期间，整个地图工作区保持 busy/inert 并拒绝二次提交或离开。
  “待应用变更”覆盖当前内容图层的全部草稿类型；409 只刷新 CAS 基线并保留本地草稿；
  地图设置保存后保持当前 Scene、聚焦对象、视图模式和编辑会话，退出编辑前必须再次确认没有残留草稿。
- 支持从写作流打开最近相关地图

## API 封装风格

- 统一 `request()` 处理超时、错误映射、FormData；封闭测试令牌遭遇 401 时使用应用内密码模态框收集一次性内存令牌，不调用浏览器原生 `prompt()`
- 高风险 wrapper 的 method、path、必需参数和长耗时 timeout 由 `apiContracts.js` 注册，`api.js` 通过 helper 生成实际请求；同步 LLM 生成等待 35 分钟，为后端 30 分钟生成窗口留出收尾余量，异步任务提交和后续无总截止轮询分开处理。这只校验请求契约，不覆盖响应字段级 schema drift
- 按模块分组：`api.projects.*` / `api.world.*` / `api.outline.*` / `api.context.*`
- 地图接口统一挂在 `api.world.*` 下，后端前缀仍是 `/api/world/maps`

## 安全与渲染约束

- Vue 模板动态文本使用插值自动转义；命令式 seam 优先走 `textContent`
- 必须插入 HTML 时先走 `esc()`
- 不把用户/AI/API 返回的未转义内容直接写入 `innerHTML`
- `index.html` 通过 CSP meta 建立 baseline：脚本仅允许本源，样式不允许外部 origin，连接仅允许
  本源、本地 `localhost` 和 `127.0.0.1` 开发后端，并禁止 `object-src`。Leaflet 1.9.4 由锁定 npm
  依赖构建为地图按需 JS/CSS chunk，不暴露 `window.L`；失败可原位重试，非地图页面不下载。
- 当前 `style-src` 仍保留 `'unsafe-inline'`，用于兼容入口与少量 inline style；收紧
  `style-src` 需作为独立 CSP 变更评审，不是前端页面 Vue 所有权迁移的未完成阶段
- 生产构建复制 `/licenses/leaflet-BSD-2-Clause.txt`，资产契约同时验证 Leaflet CSS、许可文件
  和零 `unpkg.com` 引用；直接第三方运行时依赖见根 `THIRD_PARTY_LICENSES.md`
