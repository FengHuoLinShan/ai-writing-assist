# Module: frontend / 前端控制台

## 定位

Outline 与 Memory 的后端生产 owner 已融合到 Story 的
`outline_state` / `continuity` 子域；前端继续使用原 `/api/outline`、
`/api/novels/{novel_id}/memories` wire，并通过 `/api/story` 访问 Scene 人物卡与剧本。
前端 Evidence、账户设置与项目偏好 wrapper 已分别迁入
`/api/evidence/{indexing,compilation}/*`、`/api/account/settings/*` 与
`/api/projects/{project_id}/author-preferences`；不再主动调用待退场别名。
Writing 生成若采用 stale Story script，公开确认字段为
`confirm_stale_story_assets`，409 detail code 为 `stale_story_assets`。

前端为 Vue 3 SPA 控制台，通过 REST API 驱动整个创作工作台。Vue shell 拥有静态外壳，
所有一级业务页主 DOM 由 SFC 拥有；既有 hash router、Proxy 状态、命令服务和 API wrapper
保留为集中式基础设施 seam。业务视图经 `vue/mountIsland.js` 接入 `#workspace-content`
route host，只通过 `vue/bridge/index.js` 访问既有基建，动态内容禁止 `v-html`。AI 地图册由
`MapWorkspaceView.vue` 直接拥有层级、候选对比、来源、标注和审查交互，不保留命令式地图视口
或 Writing 跨模块桥接。

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
- 基础样式：`styles.css`（结构/排版/布局尺寸；ink 主题字体族覆写）
- 全站主题覆层：`editorial-theme.css`（视觉表达唯一权威；`--nc-*` 原语层 + 语义转发层 +
  `--archive-*` 兼容别名；末尾含 shell 级点缀分节）
- 写作页样式：`vue/views/writing/writing-desk.css`（页面级）与
  `vue/views/writing/writing-decorations.css`（编辑区点缀与水印字）
- 全局状态：`state.js`
- 状态切片 helper：`stateSlices.js`
- 路由：`router.js`
- API 封装：`api.js`
- API 契约注册表：`apiContracts.js`
- 静态外壳：`vue/shell/`（topbar/sidebar/命令栏/主题/快捷键/service hosts）
- 业务视图：`vue/views/**`（Vue SFC，经 `vue/mountIsland.js` 注册）
- 命令式接缝：`router.js`、`state.js`、`api.js` 与集中式 `shared/` / `ui/` 服务
- Writing 纯 helper：`views/writing/sceneAlerts.js` 与 `views/writing/versionDiff.js`
- Vue 基建：`vue/bridge/`、`vue/composables/`、`vue/mountIsland.js`
- 通用交互：`shared/`、`ui/`

当前 router 识别的 hash 名称为：

- `home`
- `project`
- `today`（兼容别名，实际进入 Writing Home）
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
| `vue/views/interaction/HomeChoiceView.vue` | `home` 路由；作者入口校验当前账户的已选作品并智能续接 Writing Home，默认进入 `writing?home=1`，无有效作品时回作品档案；RP 卡使用“进入互动故事”并解释一次角色扮演（RP） |
| `vue/views/interaction/JourneyListView.vue` | `journeys` 路由；扁平旅程列表、新旅程、归档入口和按需搜索 |
| `vue/views/interaction/InteractionView.vue` | `interaction/{journey_id}` 路由；故事阅读、composer、流式恢复、分支、回顾、看海与右侧定位 |
| `vue/views/project/ProjectView.vue` | `project` 路由（Vue island）；紧凑作品档案，默认主操作为“继续创作”，搜索/筛选单行展示；批量、编辑、删除和回收站只在“管理作品”模式出现；无作品时优先显示新建与导入 |
| `vue/views/writing/WritingHomeView.vue` / `vue/views/today/TodayView.vue` | `writing?home=1` 的写作首页；复用 Today 的正文/世界设定续接主卡、按当前 Scene 优先的最多 6 条跨领域待决投影和最多 3 个项目隔离的长任务恢复；移动端不自动打开第一章，事项只深链到所属领域。摘要失败时不误判为空项目，仍保留写作与各领域降级入口；失败/未知任务需确认才从首页隐藏 |
| `vue/views/rag/RagView.vue` / `vue/views/outline/components/OutlineHeader.vue` / `vue/views/scene/SceneWorkbenchView.vue` / `vue/views/world/WorldView.vue` / `vue/views/world/components/WorldReviewTab.vue` | 可切换子导航使用原生 button，当前项公开 `aria-current="page"`；Scene 工作台当前项保持非交互，避免同路由刷新 |
| `vue/views/writing/WritingView.vue` | 纯章节目录、工作稿编辑器、手选 Scene 副驾驶与 AI 建议采用；光标不切换 Scene，AI/检查/发布统一消费手选 Scene；桌面与移动端共用白名单“本场”摘要，POV 可见资料只在点击后加载并隔离晚到响应；移动速记在 390px 使用原生 details，并可逆进入按项目恢复的完整编辑模式；自动保存、导入和候选采用继续保持原安全语义 |
| `vue/views/writing/components/WritingWorkflowBars.vue` | 写作台长任务完成卡；深度导入额外显示自动归并数与遗留复核组数，有遗留项时用作者语言引导到现有“人物与世界 → 智能去重”，不自动发起第二次全项目扫描 |
| `vue/views/world/WorldView.vue` | `world` 路由（Vue island）；对象库普通/热点双模式、`world/review` 统一“需要决定”工作台、历史筛选；工作台用队列 + 决策区处理对象/别名/关系，窄屏分步显示；热点模式显示重要/近期热点聚合并使用服务端全量排序；世界书编辑概览/结构化 sections、管理页面模板和 AI 参考规则，并以“工作稿保存 → 明确发布”维护页面；世界书内置关联图模式复用只读 `GET /api/world/knowledge-graph`；`map` 子标签现在只做兼容跳转 |
| `vue/views/map/MapWorkspaceView.vue` | AI 地图册一级工作台：一键生成/更新、本次候选、已采用画廊、来源分类、冲突确认、停止恢复、图片编辑与标注。 |
| `vue/views/outline/OutlineView.vue` | `outline` 的 Vue island 主视图；顶层为“故事总览、篇章、剧情线、场景”。故事总览的 AI 生成弹窗优先显示三项作者问题并渐进展开参考资料；AI 预览与 `?edit=1` 手工页共用结构化重复项编辑器，两类未采用修改都按项目本机恢复；提交仍适配原 wire payload，版本历史不可原地改写 |
| `vue/views/scene/SceneWorkbenchView.vue` | 由 `outline/scenes` 承载的 Scene 普通/热点双模式、管理筛选、当前剧情定位、拆分/合并/替换、复核与自动提取整理；旧 `scene` 路由仅作兼容重定向 |
| `vue/views/rag/RagView.vue` | `rag` 路由（Vue island）；普通路径只显示查找。资料未准备好时提供“查看并修复”，修复范围、状态与任务进度直接可见；worker、embedding、trace 和失败片段重试等低频信息收在诊断详情中 |
| `vue/views/generate/GenerateView.vue` / `vue/components/OwnerAiDrawer.vue` | owner 页 AI 抽屉内复用生成中心：world 共创与 POV 正文都使用表单内唯一主操作，长等待显示真实阶段，失败可聚焦原位重试并保留作者输入；任务资料按作者语言展示标题、状态、加入理由和来源，技术诊断渐进展开，预览按项目在当前标签页恢复；POV 选择/指令进入既有 512 KiB 项目会话，跨世界/写作 owner 时替换到正确所属页；矮窗口解除裁切，手机操作避开固定底栏；保留 checkpoint、continuation、target 与 preset，API/schema/wire 不变；旧 `generate` hash 仅作兼容重定向 |
| `vue/views/settings/SettingsShellView.vue` / `GlobalSettingsView.vue` / `ProjectSettingsView.vue` | `settings` 与 `project-settings` 共用单标题的账户/当前作品设置外壳；加载失败可原位重试，字段错误和保存状态持续可见，图片连接按需展开，窄屏单栏且无横向溢出；账户级连接、余额、全局偏好和项目级导入参数/作者偏好的 API、保存载荷与离开保护不变，字体和专注模式只在显示层本地化 |

## 路由与状态特性

- `router.js` 使用 `Map` 维护视图、异步 loader、pending loader 与最后子标签注册表；动态 key
  必须通过小写路由白名单并拒绝 `__proto__`、`prototype`、`constructor`，避免把路由输入解释为
  对象原型属性。主视图切换后仍恢复最后子标签，公开 hash 与生命周期契约不变。
- 作者 shell 的桌面主导航固定为“写作、人物与世界、故事结构、地图、查找”；移动端固定为
  “写作、世界、结构、全部”。项目切换器位于导航顶部，导入与项目偏好从“更多”进入，AI 工具在 owner 页就地打开；旧入口仅保留兼容路由，或由上下文错误进入。`writing?home=1` 是作者有效项目的默认续接页；`today` 仅为薄兼容别名。
- `writing?home=1` 不装载章节、全部 Scene、编辑偏好或编辑器恢复监听；普通写作入口保持完整初始化。RAG 状态子页同样不装载未使用的人物和 Scene 列表。
- `WritingHomeView` 通过 `writingIsland` 复用 `todayIsland` 的 loader，把本机 Writing 指针作为可选排序焦点传给项目摘要，并行组合世界书工作稿和 generation-center pending 页面建议；项目摘要中的 Writing / World / Outline 待决事项按后端顺序展示，已进入投影的建议不再重复显示为未完成创作；超过 6 条时使用 `more_targets` 打开去掉单条 item 绑定的领域处理范围，不用旧计数猜测来源；
  导航不调用 LLM。项目级本地创作指针只允许 `generate / world_bible_draft /
  world_suggestion_review` 三种结构化 route，只有作者编辑/发送、打开/保存工作稿、进入/应用建议
  时更新。轮询、任务完成和迟到响应不能改写它；失效指针清除后降级到服务器资产，来源页删除时
  保留原会话内容并要求作者重新选择，不自动切成项目来源。该指针以 `novel_` 前缀纳入账户切换清理，
  不复制聊天或服务器正文，也不提供跨设备聊天恢复。
- 小说检索页复用同一输入增加作者端“问世界”：回答、逐条主张、可打开来源、不确定性和本次
  纳入／未查范围就地显示，不展示模型、token、hash、snapshot 或内部 ID。停止只承诺不再处理
  后续结果，不声称瞬时断开 provider；跨项目迟到响应会丢弃。回答默认只读，作者明确点击后才
  保存为待处理世界笔记建议，来源变化时要求重新提问。
- `home/journeys/interaction` 使用独立 RP 壳，不显示作者 sidebar；合法深链不要求先选择
  author 项目。RP 草稿按旅程保存在本地，服务端流式 buffer/分支/回顾负责跨刷新恢复。
- `outline` 的规范默认子视图是 `story-outline`，作者导航层级为“故事总览 → 篇章 → 剧情线 → 场景”。`outline/story-outline?edit=1` 是可刷新、可前后退的手工编辑页；AI 预览留在故事总览页内，两者草稿均按项目隔离在本机并受离开/冲突保护。旧 `scene` 路由重定向到 `outline/scenes`，旧 `outline/foreshadowing` 与 `outline/reveals` 重定向到剧情线的信息推进区域。
- router 不再保留 KeepAlive/DocumentFragment 缓存；所有视图离开时卸载。写作快照、Outline/Scene workflow 与滚动位置采用显式项目隔离 session 恢复，详见 [ADR-0009 附录 A](../adr/0009-appendix-a-keep-alive-policy.md)
- Writing session 使用原生 `Map` 保留当前章和最近四章、最近五个项目；未完成本地备份的 dirty 快照不可淘汰。正文输入立即更新内存，本地备份和恢复指针合并为 250ms trailing 写入，并在保存、切换、卸载及页面离开前强制 flush；网络自动保存仍为 3 秒。
- World/Outline 默认骨架和常用首屏同步加载；World Bible、“需要决定”、AI 抽屉，以及 Outline 的结构标签、AI 预览和 Scene 工作台使用 Vue 原生异步组件，chunk 失败自动重试一次。
- 写作页另以项目隔离的本机安全指针保存最后章节、工作稿 ID/版本/更新时间、手选 Scene、光标偏移与指针更新时间，不保存正文。Writing Home 把章节与 Scene 作为 workspace-summary 的可选排序焦点；服务端验证归属后才用于相关性排序。续写仍仅在服务器续写章与本机章节一致时携带 Scene；编辑器仅在工作稿 ID、版本和更新时间全部一致时恢复并 clamp 光标，且不主动聚焦。本机指针指向的工作稿失效时清理其工作稿/光标身份并回退当前有效版；显式 URL 工作稿则保留错误。章节加载失败不会把目标章与上一章工作稿混写到该指针，正文区改为可重试错误态；保存失败保留本机备份并在成功前阻止切章和正式正文提交。账户切换与退出会清理该指针。
- 世界对象库和 Scene 工作台使用 `mode=normal|hot`；URL 优先于按“项目 + 页面”保存的 localStorage 偏好，无偏好默认热点。切换模式保留通用筛选，清除模式专属筛选、分页偏移和批量选择。
- Scene 工作台的筛选、详情和复核状态由 `useSceneWorkbench` 持有；当前 Scene 与模式通过 `outline/scenes?mode=...&scene_id=...` 写入浏览器历史，Writing Home 可额外用 `suggestion_id` 定位并打开仍待处理的融合建议。热点默认请求 `anchor=latest`，显式 Scene、分页、阶段或管理筛选时不自动锚定。桌面无 `scene_id` 时只渲染通栏列表；选中后才显示详情栏，前进、后退、刷新和后端对齐分页的恢复语义不变。
- Writing Home 跳转 `world/review` 时以 `kind=objects|aliases|relations` 携带精确 `entity_id` / `group_id`；对象直接读取目标，别名与关系按现有分页查找目标组。A→B 与 B→A 是两条有向提醒，各自携带对应 `group_id`。旧 `review-objects` / `review-aliases` / `review-relations` 深链会保留定位参数并重定向到统一工作台。
- `map` 路由会解析 query 上下文，用于承接写作页和世界页跳转
- `world/map` 仍保留入口，但现在会自动跳转到一级 `map`
- `settings` 是无项目也可访问的账户设置页；`project-settings` 依赖当前作者项目，未进入项目
  时显示空态并提供返回账户设置；两页范围切换使用正常路由并支持前进、后退和刷新
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
- 旧 `context` hash 会重定向到 owner 页 AI 抽屉的任务模式；上下文任务预览和编译仍由生成中心承担。旧 `generate`
  hash 按 tab 薄重定向到 World 或 Writing owner 页，抽屉内直接挂载原 `GenerateView`，保留会话、未发送输入、取消/恢复和任务进度

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

- 项目页使用“作品档案”首屏和等宽紧凑项目网格：当前项目始终置顶但不额外放大，其余项目按
  最近更新时间排序；桌面首屏展示三个完整项目摘要，`1100px` 以下两列、`760px` 以下单列。
  视觉层只消费既有标题、题材、阶段、简介和统计字段，常见题材枚举显示为中文，不新增封面数据
  或 API；`390px` 隐藏纯装饰封面且不产生页面级横向溢出。
- 全部一级页面、子标签、弹窗、表格和辅助栏共用三主题换肤体系：`sticky`（晨光便签，浅色默认）、
  `night`（暗夜书房，深色）、`ink`（水墨写意，纸色），经 `<html data-theme="…">` 切换。
  `editorial-theme.css` 作为后加载覆层拥有视觉表达：`--nc-*` 原语层是唯一写色值的一层
  （`:root` = sticky，`[data-theme="night"|"ink"]` 只覆写 `--nc-*`），语义层全从 `--nc-*` 转发，
  `--archive-*` 保留为转发别名；`styles.css` 保持结构布局。全站线条为 1px hairline，阴影只用于
  浮层。主题持久化 key 为 `nc-theme`（首次从旧 key `novel_theme` 迁移并删除；legacy 值映射
  `light/minimal→sticky`、`dark/dark-soft→night`、`paper/warm→ink`）；无存储时跟随系统
  `prefers-color-scheme`（dark → night）。切换入口为顶栏三点切换器（`.topbar-theme` radiogroup +
  `button.theme-dot[data-theme-value]`，支持方向键），切换过渡 250ms、reduced-motion 关闭。
  点缀只允许顶栏品牌区、写作页编辑区（上 1 组 + 下 1 组）与左栏导航底部三处，近底色、
  `pointer-events:none`，专注模式与 ≤760px 一律隐藏。设计细则唯一权威：
  `docs/frontend/uiux/design-standard.md`。
- 路由在 `#workspace-content` 写入 `data-workspace-view/subview` 只供样式
  定位，不得被业务逻辑、数据请求或测试 fixture 当作状态来源。
- 全局布局尺寸：`--topbar-height:57px`、`--sidebar-width:211px`、rail 折叠 `44px`；
  写作页固定三栏：章节树 238px / 正文弹性 / 写作副驾驶 257px。
- 功能性按钮、输入框、选择器和编辑区要比只读内容更易辨识，但不脱离主题：主操作使用主题
  accent 实体面（sticky 蓝 / night 金 / ink 朱砂），普通操作保留可见边框；可编辑字段使用
  surface 底与完整边框，focus-visible 显示 2px accent 焦点环。暗色主题保持相同层级；
  `760px` 以下常用按钮高度不低于 `42px`，输入控件不低于 `44px`。
- 创作工作台以正文、主列表、编辑区、生成结果和地图册图片为主对象；桌面端主对象目标占分栏内容宽度的约 `64%–68%`。
- Vue 页内的主题化辅助栏由 SFC 模板渲染，并以 `项目 + 页面 + 栏位` 为 key
  在 `sessionStorage` 保存折叠状态。辅助栏折叠不得重置选择、筛选、滚动位置或未保存编辑内容。
- 卡片/表格、展开/收起、选中与其他纯呈现控件只更新局部状态；同路由仅需同步
  hash query 时使用 router 的就地 query seam，不重新执行 `onEnter/render`。确需重取
  服务端数据的操作也必须在返回后复核发起时的项目、路由/编辑器 owner，不得用旧响应
  重挂载用户已切换到的页面。同路由强制刷新恢复工作区纵向滚动位置。
- 写作专注模式高于普通辅助栏状态；中等宽度重排第三栏，`760px` 及以下使用单栏、抽屉或手风琴，不允许产生页面级横向溢出。
- Vue 业务页使用 `vue/components/WorkflowProgressCard.vue` 渲染任务卡：普通运行/完成态
  显示紧凑摘要，失败或调用方标记 `attentionRequired` 的恢复、重试和确认状态
  默认展开；用户保存状态优先于自动规则。取消终态统一说明为停止后续处理并保留已保存阶段，
  不把任务租约失效表述成远端模型连接已瞬时中断。
- 作者显式发起的 World/Outline/Writing 长耗时 AI 操作在请求前生成
  `operation_id` 并写入当前项目的页内 workflow 记录。刷新或离开返回只查询原 task；
  404 显示“未找到原任务，请重新开始”，不自动重放不确定提交。进度和结果只在
  发起位置显示，默认隐藏 raw task ID；Scene 融合完成后在工作台显示“查看预览”，
  不因晚到响应重开旧弹窗。任务完成不刷新整座 island，不覆盖当前输入、筛选、焦点、滚动和多选。
- `shared/smartDedup.js` 对 schema v2 结果打开 `{size: "large", protectUnsaved: true}`
  双栏工作台；队列、对比、主对象和逐成员动作共享同一个 group 草稿。
  对比默认“只看差异”；勾选操作与切换合格主对象会保留工作台滚动位置，且主对象 radio
  及当前控件焦点，且主对象 radio 必须使用真实 asset ID，不能退化为浏览器默认值。
  Scene merge 进入已就绪前必须调用现有 Scene merge preview 并由用户确认。
  工作台不把 `needs_review` 或“稍后处理”发到 apply API，也不允许手填任意主对象 ID。
- 折叠栏和进度摘要必须使用现有设计 token，并覆盖 hover、focus-visible、disabled、错误、暗色主题和 `prefers-reduced-motion`，不得暴露浏览器默认折叠标记。

## 开发与验证脚本

- 开发服务器使用 Vite：`npm run dev`，默认端口 8080，可通过 `FRONTEND_PORT` 覆盖。
- 静态检查使用 `npm run lint`：ESLint flat config 覆盖生产 JS、Vue SFC、Vitest、
  Playwright 和构建配置，只启用 JS correctness 与 Vue essential，不引入格式化规则。
- 单元测试使用 Vitest：`npm run test`；监听模式为 `npm run test:watch`。
- 浏览器 E2E 使用 Playwright：`npm run test:e2e:functional`；烟雾子集为 `npm run test:e2e:smoke`。默认启动 fresh 8000/8080 服务，只有 `PW_REUSE_EXISTING_SERVER=1` 才复用已有服务；后端启动前执行 `APP_ENV=test alembic upgrade head`。`APP_ENV=test` 不改写 `DATABASE_URL`；本机存在开发 worker 时应显式传入独立测试库。CI 的完整功能门禁同时启动 Compose 管理的私有 MinIO bucket，覆盖对象图片真实上传。如端口被旧服务占用，使用 `BACKEND_PORT=8010 FRONTEND_PORT=8090 PW_REUSE_EXISTING_SERVER=0`。
- `npm run build`（vite build）仅作 Vue 构建链冒烟验证：`dist` 仍缺少 classic 基础设施 seam scripts，不能视为可部署产物。
- 当前已落地共享 JS API 契约校验第一阶段，覆盖项目、设置、导入、上下文、世界/地图册、写作冲突检查和 RAG 的高风险 wrapper 子集；TypeScript / OpenAPI codegen 仍是未来设计项，当前说明见 `docs/frontend/typescript-api-contracts.md`。
- 小说检索继续消费 context evidence API：单次最多取回 100 条现有命中，DOM 首批只挂载
  20 张结果卡并按 20 条渐进加载。章节范围的非整数、非正数或倒置条件会在请求前提示并保留给作者修正，不会被伪装成空结果。检索词、方式、正文版本、可见视角、章节范围和 scope
  保存在 hash URL；前进/后退会恢复表单并重新检索，显示游标和证据抽屉不持久化。search
  不设置内容级 tab；status 仅由降级通知条或深链进入，并在修复卡内返回 search。同项目两个路由
  往返保留已执行结果和未提交筛选；切换项目时统一清空。新查询会
  就地 push hash query 并执行检索，不重挂页面或重取状态数据；同时 abort 旧请求，晚到响应还需
  通过 project/lifecycle generation 才能回写；证据抽屉使用独立
  abort/generation/project/drawer 门禁，关闭抽屉或切换项目后不接受旧正文、引用或导航结果。
  作者视角的聚合卡会为每个实际命中范围展示所属 Scene 位置和摘要，
  并用项目隔离的写作台 Scene 快照标记“当前/前序/后续”关系；同章多 Scene
  会逐个展示摘要和跳转入口。读者/角色视角不显示这些作者专用元数据，
  不将“因可见性被隐藏”误报为“未关联 Scene”。
- 小说检索查询卡使用原生表单并保持“查找资料”为唯一主操作；常用查找方式和正文版本显示可见说明，章节、资料范围和可见视角收进“更多条件”的两个 fieldset。待处理世界设定只有选中世界设定范围后才可用并解释原因；作者视角不显示读者/角色专用截止字段。该重排不改变 URL、evidence payload 或项目隔离契约。
- 任务进度卡仅依据后端 `available_actions` 显示 retry；RAG 和世界书投影在 retry 成功后恢复原 task id 的轮询，请求失败时保留原失败卡。创建 RAG 维护任务的写请求不随视图卸载取消，避免服务端已入队而浏览器丢失 task id；离页只停止轮询与晚到 UI 投影。
- 生成中心精确上下文可显式选择最多 16 个其他已采用世界书页，当前页不重复出现。选择按“项目 + 来源页 + target”会话恢复，只作聊天、收束与建议的参考；不合并、修改或自动采用页面。
- 生成中心 world 工作区默认开启作者版世界观简介，可按会话关闭；“查看本次上下文”读取响应中的实际 `context_usage`，不事后重编译。次级“收束本轮”只在作者触发后调用只读 convergence：界面显示实际范围、排除的更早消息、覆盖状态、细账统计与最多 7 张决定卡；接近 40 条只提示，不自动请求。卡内每项可改为“纳入／开放／放弃”，先编成可编辑作者消息，再由作者确认加入本地对话；此阶段不调用聊天、建议或采用 API。完整且未 stale 的收束可导航到既有 `outline/story-outline` 承接全书／分部的核心前提、叙事读法、基调和读者承诺；导航不搬运内容、不改世界事实，整页提案有未应用编辑时复用离开确认。来源页的新页面目标可额外执行只读深度 1 探索：最多展示 3 个带来源证据的相邻缺口，作者只能选 1 个，未选项不创建 suggestion；输入或来源改变会标记选择过期。生成返回的可选来源页修订与新页面分别显示为待审结果，均不自动应用或触发下一跳。不同 owner 只显示需分别处理，本次仍只生成当前 world target。刷新恢复 schemaVersion=1 的摘要、来源 refs、选择与消息；对话/来源选择变化或 409 会把旧稿降为只读，512 KiB 超限先删可重建展开说明而保留 refs、选择和作者消息。多轮结构化建议在结果和世界书建议审阅中默认折叠展示服务端 `decision_state` 的作者语言摘要；低置信或有未决项只标“请核对”，不显示分数，旧记录明确提示未保存摘要。当前已有 pending 提案时，生成动作必须由作者明确选“修订此版”或“另起方案”，不默认推断。修订成功后先展示决定摘要、“上一版 → 当前版”和关键字段差异；世界书审阅可展开不可再采用的线性历史。修订 409 或其他生成失败保留当前对话和未应用编辑；只有新版成功才替换本地预览。前端不读取对象 `_meta`、页面 payload 或原始 `result_ref_json` 来拼装决定/修订关系，也不允许编辑 JSON 伪造决定；作者通过补充明确纠正并重新生成更新它。来源页面正文与服务器工作稿始终由服务器重载；本地 v2 会话按项目 + 来源页 + target 隔离，只缓存对话、选择项、suggestion ID、收束草稿，以及 schemaVersion=1、精确绑定当前 pending suggestion 的作者未应用提案编辑。刷新或离开时仍在等待的聊天助手气泡仅在本地副本转为可见的中断终态，不自动重试且不进入后续聊天请求。该版本化 working copy 受 512 KiB / 最多 5 个会话边界约束，不代表 canonical 或服务器工作稿；匹配 suggestion 才恢复，成功应用或作者确认放弃后清理。任务页签只编译/预览上下文；POV 明示并强制禁用作者全知简介。
- 生成中心模式导航是受限 tab/tabpanel surface：方向键和 Home/End 只 rove 焦点，Enter/Space 继续走既有切换和离开确认；任务预设、世界目标和对象模板以可访问选择态公开当前值，任务原生字段与可见标签关联。
- 写作与人物/世界页内的 AI 抽屉以外层类别标明当前 owner；pov 归入「写作建议」，preview 归入「任务上下文」。旧 Generate 深链保留内部模式 tab 兼容；跨 world/pov 时使用 replace 路由切到正确 owner，不制造多余历史项。任务与 POV 使用原生表单和唯一主操作；任务结果先显示作者可读的资料标题、采用状态、加入理由、摘要和来源，raw key、token、裁剪事件只在折叠诊断区，完整文本、带到对话和采用正文均需作者显式触发。render 失败保留已整理摘要并只重试 render。预设、未提交条件、按项目隔离的资料预览与 POV 选择/作者指令复用既有有界 Generate 会话；刷新、前进/后退、类别往返和项目切换均恢复正确状态，晚到响应仍受 owner/project 生命周期门禁。超出 512 KiB 的资料预览刷新时仅恢复摘要；后端 API、schema、wire 与内容语义不变。
- “与外部模型交接”是 world 工作区的折叠次级入口，只服务长期作者。主输入框保留本次目标，
  外部回包单独进入现有 `pasted_context`；55,000 字符超限在请求前阻止且不截断输入，Web Crypto
  SHA-256 只对当前本地会话做精确重复 no-op。会话保存当前输入和最多 20 条无正文的包摘要；
  收束选择形成作者消息后也不自动生成 suggestion。只有完整、未 stale 且带 manifest 的预览
  才能复制／下载同一 Markdown；项目级材料明确提示无法证明全部来源未变化，外部 ID／检查声明
  不显示为本地对象或本地通过。该入口不上传文件、不跨设备同步、不建立导入批次。
- “准备视觉稿”复用同一份完整 convergence manifest 与 R06 文本交接，不新增图片 wire 或状态表。
  本地 `visualBrief` 只保存单一用途、来源清单 hash、作者编辑的“必须保留／准确标签／仍开放／
  不要新增”、确认时间和 stale 标记；不保存图片、Prompt、seed 或内部对象 ID。确认简报业务写入为
  0；输入、来源或收束选择变化会保留文字并使后续动作 fail closed。确认后可复制／下载包含同一
  创作交接快照的 Markdown，或在当前页面直接打开既有 `MapQuickCreateDialog`。quick-create 的
  context／preview 仍是只读，candidate 地点仍禁选，最终“创建”仍是独立的既有确认动作。首批
  不调用图像模型、不上传图片，也不把外部候选图细节转成 observation／fact。
- 生成中心任务页签选择章节后，Scene 选择器先展示该章的可用 Scene，同时仍可按名称搜索项目内其他活跃 Scene。
- 生成中心角色视角正文在 lazy load 期间显示加载态；只有已成功确认零章节才显示前置条件空态，隐藏生成表单并复用写作台/世界设定入口。整体与 Scene 加载错误均提供原位重试，不得被呈现为零章节。章节、Scene、角色和作者指令按项目保存；AI 参考弹窗关闭、生成失败或取消不清空表单。
- 世界书、生成中心和通用 AI 参考弹窗只列出已发布 Activation Profile；只有作者显式选择后才随请求发送。世界书规则编辑器提供受限表单和 dry-run trace，不提供 raw JSON、regex 或 Prompt 插槽。世界书存在未保存修改时，“用 AI 完善此页”必须先保存成功再跳转；生成中心页面 apply 只写工作稿，成功后带页面/工作稿 ID 返回世界书。中等宽度把第三栏下移，窄屏改为单栏且不得产生页面级横向溢出。
- 世界书编辑器把“保存并发布”作为始终可见的主操作；点击后先保存工作稿并显示发布前影响
  核对，用“发布后会自动处理／建议核对／本次未检查”区分确定性 typed 引用范围。空态明确
  自由文本和其他创作领域未检查；路径按需展开且不显示 raw ID/hash。确认时携带预演 scope，
  引用漂移以 409 保留工作稿并要求重查；预演服务不可用时保留工作稿和明确的人工发布出口。
  只有“保存工作稿”不会改变正式页。
- 世界书分区编辑器以作者语言显示序号、标题、普通资料／检查清单／资产清单和正文；原有
  `sensitivity_hint`、`projection_policy`、稳定 `section_id` 与局部引用 hash 保留在默认折叠的
  “创作辅助与高级设置”，不改变 section payload、恢复、排序或发布契约。公开世界常识明确指
  故事内知识范围，不代表向其他用户公开；自动整理策略也不冒充显式整页参考的全局排除门禁。
  保存回包直接对账页内工作稿集合，不重挂编辑器，也不重置焦点、光标或当前页面选择。
  世界观简介的终止任务 ID 不得在同一页面生命周期内重新挂回轮询，避免失败刷新反复重绘并
  阻断点击。
- 世界书类别、简介状态与投影状态默认使用作者可读中文；投影恢复键、任务 ID、原始状态和
  后端 warning 只放在折叠的“诊断信息”中，不在设定正文和主操作区直接展示。
- 世界书顶部用原生折叠区汇总 `author-open-questions` 中已保存的未勾选项；同一页面的工作稿
  覆盖正式页，归档页不计，点击项目打开来源并定位分区。空态只承诺“没有已保存的未决项”，
  不把未保存 DOM 编辑误报为已同步。该交互借鉴
  [GitLab open threads](https://docs.gitlab.com/user/project/merge_requests/#manage-comment-threads)
  的集中计数与
  [Gerrit ported unresolved comments](https://gerrit-review.googlesource.com/Documentation/user-porting-comments.html)
  的跨版本可达性，但不复制内容、不生成第二套状态，也不阻断发布。汇总与跳转全是确定性前端
  投影，因此不引入 Pi 或 Agent runtime。
- 世界书内的“世界健康”折叠面板显示待作者决定、待补证据和失效数，支持当前
  工作稿/采用包的定向校验、全面校验、后台恢复、来源回到与最近回执。主界面不展示
  raw ID、JSON、Prompt、token 或 hash。旧项目默认只自愿校验；作者二次确认“启用发布前校验”
  后才强制发布/采用门禁。warning 需写明理由并整体签收；stale/block 明确要求重跑或修正。

## 写作流补充

`vue/views/writing/WritingView.vue` 当前不只是草稿编辑器，还承担：

- 纯章节目录与手选 Scene 副驾驶
- 自动保存与未保存提醒
- 底部状态栏 `.writing-statusbar`（38px 通栏）：左侧为字数进度（当前 / 日目标 + 3px accent
  进度条）、段落数与预计阅读时长（字数 / 400 向上取整）；右侧为字体循环切换（会话内临时
  override，不写偏好存储）、专注模式按钮和保存/版本状态徽标——这些 DOM 自编辑器头平移，
  id 不变；版本选择条保留在编辑器上方工具区。状态栏始终吸底；发布、生成、冲突检查和自动提取的工作流反馈固定在全局顶栏下方、写作区居中的紧凑浮层，不挤动编辑器或状态栏。无后续操作的成功态 3 秒后自动关闭；失败、取消、降级、恢复待处理及带业务操作的终态持续显示。同一工作流生命周期不重复发送全局 toast
- 版本历史/恢复
- 读取项目生效作者偏好并驱动日目标、编辑器字体和默认专注模式；优先使用设置服务的项目/全局继承结果，旧本地值只作为接口失败时的兼容回退
- 深度导入进度展示：恢复 localStorage 中的 task_id，展示当前章节 / Scene / batch、质量统计、降级状态和中断恢复提示
- 中断恢复操作：用户显式点击“继续”才调用 `/api/imports/deep/resume`；“放弃恢复”必须二次确认并展示清理摘要

## 作者展示状态

- `shared/assetDisplayState.js` 是前端唯一通用映射：结构资产显示“待处理 / 已采用 / 历史”，正文显示“待处理 / 工作稿 / 正式正文”。页面不得自行再维护 `candidate` / `canonical` 文案表。
- `attention_reasons`、低置信、冲突和 `needs_review` 显示为注意标签，不替代主状态。
- “必须修复／需要决定／可以改进”只是当前页面的作者动作投影，不新增统一校验生命周期：世界候选只进入“需要决定”，当前列表加载失败才显示“必须修复＋重试”；写作规则与需人工判断的 AI 项进入“需要决定”，普通 AI 软判断和 RAG 证据降级只显示“可以改进”。已处理、忽略或稍后的历史项不再获得当前动作标签。冲突详情同时显示作者可读的来源版本和定向复检范围，不暴露 Scene ID；检查来源不完整时交还作者选择，不伪装成确定性阻断。
- Writing Home / Today 保留 A→B 与 B→A 两条有向关系提醒，并分别统计、携带 `group_id`；领域工作台可显示反向候选提示，但不自动归并两个方向。列表下方只保留一个“查看更多”，按当前排序的首个未展示类型进入对应页面。
- 主列表默认隐藏历史；只有显式选择历史/raw status 筛选时加载或展示。
- API 保留原始 `status/review_state/fact_status` 兼容字段，前端优先消费领域 `display_state`，必要时才由共享 helper 回退映射。
- AI 正文建议在编辑器中以只读预览打开；审核条位于正文前、加载完成后接收焦点，并按当前审查状态只保留一个主操作。采用/拒绝共用全局确认，处理中不可重复提交，失败在原位保留；≤760px 自动收起章节目录并隐藏只读状态条。“采用到工作稿”成功后加载服务端新 draft 并恢复编辑/自动保存，“拒绝建议”经确认后软废弃候选并回到当前工作稿/已发布稿。顶部“AI 续写”只对服务端已保存的可写或已发布 base draft 开放，不拿未保存本地文本或跨章 Scene 作为替换范围；异步任务轮询没有前端总截止时间，完成后自动打开候选审核面板。普通生成的 `pov_validation=not_applicable` 不显示角色视角失败提示。
- 生成中心的角色视角正文按“章节 + Scene + POV 角色”确认上下文；已有目标章时锁定完整 active 正文，候选仍是该章完整替换稿，Scene 即使跨章也不扩大范围。创作面称为「由谁来感受这一场」和「角色只会知道自己应当知道的事」，不展示过滤链、raw ID 或诊断缩写。结果卡固定显示该次请求的 Scene 与角色，不随生成后的表单选择漂移；入口跳转写作台统一审核，不把“未发现明显越权”显示成整体质量通过。
- 人物知识管理复用现有列表、创建和更新接口，按可读目标名称/类型展示“当前认知”和可展开的较早记录；作者通过类型化对象选择器新增，在同一目标与生效位置就地更新，并以 PUT 归档，不在主界面暴露 raw ID 或内部枚举。重复检查点会明确提示。角色视角的 AI 参考弹窗完整展示“会交给角色视角模型”的知识，并把导演约束分到“仅供作者约束”；“修正人物知识”在新标签页打开既有管理器，原表单和弹窗保留，作者返回后手动“重新整理”，不自动调用模型。
- 同一弹窗的 Scene 时点状态按“当时可证 / 人物所信 / 当前正典”分层，只把可追溯的历史投影作为导演约束；未覆盖对象显示“尚无时间锚”，不暴露 checkpoint ID 或内部状态。“核对 Scene 时点”在新标签页打开地图活视图中的既有修复台，原表单保留，返回后由作者手动重新整理。
- 这条人物知识修复流程目前只面向目标画像 A 的角色视角写作；它不新增角色扮演聊天入口，也不把知识图谱或 Agent 配置转嫁给普通作者。重复使用意愿仍是待真实用户验证的产品假设，当前验收覆盖空态、失败、晚到响应、保存反馈和 390px 触控尺寸。
- deep import/stage 启动入口必须先展示自动采用范围并取得明确授权，完成卡展示 `asset_summary` 的已采用/待处理/未采用三类汇总。

## 世界对象分组复核

- `world/review` 的“全部 / 对象 / 别名 / 关系”复用现有三个列表接口各自的待处理条目总数，不新增跨类型分页或统一写入 API。“全部”只显示概览与推荐下一项，默认优先对象，再到别名与关系。
- 对象、别名、关系队列使用同一顺序：队列说明 → 常驻搜索 → 任务标签 → 已启用条件 → 更多筛选 → 当前结果 → 批量处理 → 列表 / 分页。关系按有向对象对、别名按所属对象分组；每页 20 / 50 组，全选仅作用于当前可见项。
- 常驻搜索只定位当前审核队列内的候选名称、类型、描述与证据摘录，不合并到一级“查找”。一级“查找”仍负责正文、世界对象和故事结构的跨资产检索，本轮不改变其结果卡、权限、URL/query 或证据搜索契约。
- 任务标签与更多筛选固定为：
  - 对象：`可作为新对象 / 建议设为别名 / 建议合并 / 需我判断`；更多筛选为对象类型、建议动作、章节、场景、置信度。
  - 别名：`同对象多别名 / 自定义类型 / 缺少引用 / 高置信度`；更多筛选为别名分类、详细类型范围、章节、场景、置信度、证据状态。
  - 关系：`同对象对多类型 / 有反向候选 / 已有正式关系 / 缺少引用 / 低强度`；更多筛选为关系分类、详细类型、章节、场景、强度、证据状态。
- 待处理别名与关系的更多筛选控件提供明确中文可访问名称；Workflow ID 仍收在“诊断筛选”内并标记为诊断字段。任务标签不重复进入面板，已启用条件同步显示为可删除标签。
- 关系列表查询增加两个可选布尔参数：`has_reverse_candidates` 表示该有向组存在反向方向的待处理候选，`has_canonical_relation` 表示同一有向端点对已有正式关系。对应任务标签只发送 `true`；后端必须在计算 `group_total`、`item_total` 与分页之前过滤。
- 一级“需要处理”、工作台类型 tab 与 Writing Home / Today 类型提醒均统计当前仍有效且未采用的候选条目；已采用、忽略、过期和历史项不计入。别名与关系的“当前结果”同时展示 `group_total` 与 `item_total`，分页按组，不能用分组数或当前页行数替代待办总量。
- 普通列表、审核卡与决策区把 `alias_kind` / `relation_kind` 显示为中文通用分类，并把目录内 `alias_type` / `relation_type` 显示为中文详细类型；缺分类显示“待分类”，未收录详细值保留原文并标记“自定义”。已采用关系与别名在普通列表提供编辑入口，可修改两层类型或移动端点/所属对象。待处理别名以次级“查看并决定”选中，右侧决策区按“归属对象 ↑ 待采用名称”编辑对象、文本、名称用途和具体称呼，不再打开第二层决策弹窗；决策区只保留“采用别名”为主按钮。待处理关系同样不再打开第二层弹窗：右侧展示两张端点卡和“关系发起方 → 关系承接方”空槽，桌面拖动任一卡到任一槽即可自动补齐另一端，触屏或键盘先选卡再点槽；每次只处理当前推荐的同类关系事实，其余不同类型继续待定，决策区只保留“采用关系”为主按钮。两类决策的当前项以前端 `review_item` query 恢复；桌面选中后焦点进入决策区，窄屏沿用队列到决策页的分步视图并聚焦“返回队列”；返回后恢复原条目焦点，刷新和浏览器往返保留选择，作品切换保持隔离。取消只返回队列并保留草稿，归并、复用和忽略仍须二次确认。
- 别名目标搜索覆盖同项目 canonical / draft / candidate 对象，排除历史对象和 suggestion shadow，不依赖对象库当前首页；待处理关系的端点只在当前两张卡之间配对，已采用关系的普通编辑入口仍可修改端点。
- 作者未亲自选择通用分类时，详细类型变化会同步目录的 `default_kind`；作者选择后不再覆盖。未收录类型以“自定义详细类型”打开并显示原文，类型建议只有在用户点击后才更改草稿。缺分类时阻断别名采用，以及关系的采用和归并；兼容批量契约中的分别采用同样保持分类校验，忽略仍可执行。`type_kind=recommended|custom` 作为详细类型目录兼容筛选继续保留，分类筛选和当前编辑草稿同样随项目会话与 URL 状态恢复。置信度只用于筛选/预选，不自动采用。
- 工作台统一投影“待处理 / 需先处理对象 / 处理中 / 已完成 / 内容已变化 / 处理失败”；成功回执使用名称与数量说明采用、复用、忽略和剩余数，不显示 raw ID。关系端点为待处理对象时先进入对象决策，完成后按 `return_kind` / `return_group_id` 回到原组。
- 队列加载失败统一显示 `role="alert"`、作者可读的未变更说明和“重新加载”，原始技术原因默认收进“诊断信息”。
- 批处理降为当前类型内的次级折叠入口，保留现有上限、单请求和分组原子性。单项草稿以项目 + 待定项保存到 `sessionStorage`；执行指纹改变时丢弃旧字段、按当前内容重载并标记“内容已变化”，普通失败仍保留输入。
- 世界对象的卡片/表格只切换当前组件呈现并就地同步 query；筛选表单的未应用副本
  放在现有 `worldSession` 中并精确绑定 query 签名。同项目分页、热点/全部资料切换或后台
  必要刷新可恢复草稿；外部深链、子页或项目变更仍以新 URL 为准。
- 世界对象卡片和表格都提供“上传图片”。缩略图仅经鉴权接口取回并使用受控 Object URL；无图、
  失败或晚到响应继续使用首字色块，替换/卸载时释放旧 URL。卡片整体可用 Enter/Space 打开既有
  编辑弹窗的双栏详情，上传、复选框和“更多”保持独立；窄屏改为单列，图片失败不阻断文字编辑。
  卡片操作区贴底等高，首列“更多”只在局部向右展开，避免被左侧遮挡。
- Outline 篇章/剧情线同样区分已应用 query 与编辑中筛选：翻页只改已应用条件的页码，
  不隐式提交未点“应用”的控件值；同 query 重挂载恢复草稿，各子页草稿相互隔离，
  外部 query 或项目变更时以新路由为准。
- compatibility shadow 仍由建议队列拥有；其内联别名在分组复核页只显示“随对象建议处理”，不进入多选或批处理。
- 默认卡片不展示 UUID，只展示“来源 · Scene · 章节 · 强度/置信度”和短引用；Workflow、Scene UUID 与证据引用收进可复制的诊断区。关系字段始终称为“强度”。
- 桌面使用右侧抽屉；390px 变为全屏复核页，复核搜索和主操作按钮高度不小于 44px。

## 结构整理补充

- `OutlineStoryTab.vue` 及 `useStoryOutline` 只管理 StoryOutline 聚合，不会因为采用总纲而创建 PlotThread、OutlineArc 或 Scene。当前版完整展示 title、creative core 四字段、`outline_markdown`、`major_storylines`、`macro_movements` 和 `open_decisions`。手工保存、AI preview apply 和历史采用都带 current `base_revision_id` 与 `idempotency_key` 创建新 revision；同一 payload 重试保持 key，内容或 base 改变后轮换。409 保留当前编辑草稿，显式重新加载后把它 rebase 到最新 current。
- StoryOutline AI 请求只接受作者意图、计划尺度、覆盖描述、可为空的显式人物/世界对象选择和 `include_current_outline`，不提供起止章或强制模板/数量；显式选择为空时由后端自动使用 Top-K。返回内容保持 strict 完整 preview，并以带字段说明、排序和错误提示的作者可读表单编辑；导航数组是辅助摘要，不要求名称唯一或精确字符串引用；生成完成不自动采用。
- 生成恢复复用通用 workflow 记录与 `/tasks/{id}` 轮询/取消，但只恢复同一 project、`task_type=story_outline_generate` 且 `action=outline.story_outline.generate` 的任务。完成结果允许服务端附带 `managed_llm_steps` provenance；已标记 adopted 的 task 不重复恢复为可采用 preview。路由离开或项目切换后丢弃晚到响应；取消、过期、任务上下文不匹配和短暂查询失败保持不同的作者可读状态。

- `vue/views/scene/SceneWorkbenchView.vue` 是 Scene 管理主入口，支持按 status / source / workflow_id / needs_review / phase 等条件筛选深度导入结果。筛选默认收起为已启用条件数与未应用修改摘要，更多整理条件渐进展开；已应用条件和未应用输入均按作品保存在当前浏览器会话中，刷新、前后退和作品切换时不串用。
- Scene 剧情进度与健康待办共用原生「场景概况」`<details>`；桌面端保持展开，窄屏默认收起为当前剧情段、主要待办与其他类别数摘要。摘要优先显示当前已应用筛选，完整八个筛选的语义与请求保持不变。
- Scene 未选中时列表使用完整工作区，选中后才显示详情栏。详情用原生语义分组区分基本信息、创作要点与章节来源，顶部可返回列表，底部吸底操作栏区分已保存、待保存和保存中。当前待办保留为次操作，合并/拆分收入共享 ActionMenu 的「更多」菜单并向上展开；草稿未保存或保存中时，待办和结构操作原生禁用。未保存返回仍经既有放弃确认；窄屏模态详情打开时底部主导航不可见、关闭后恢复。
- Scene 工作台把机械合并和 AI 融合建议分成两个入口。AI 融合前必须在卡片中选择主 Scene，随后在大尺寸语义表格中并列展示 AI 建议、主 Scene 原值和其他来源 Scene 原值；拆分使用“原 Scene / 建议 A / 建议 B”对比。两类预览覆盖语义字段、叙事标签、POV 和章节映射，默认显示全部字段并可只看初始差异；AI 建议保持完整可编辑，长来源证据按需展开。融合预览是同步 LLM 请求，API contract 使用 90 秒生成窗口。叙事标签把空值规范为 `draft`（未标注），拆分字段支持显式清空。保存模式包括保留原 Scene、保存并废弃原 Scene、放弃结果、继续编辑后保存；废弃来源必须在预览内再次确认，所有融合保存入口共享单次请求锁，失败时恢复操作并保留当前编辑。手动融合输出使用 `source="manual_fusion"`。
- 重复提取的 replacement suggestion 使用专用对比面板，展示受保护原 Scene、新候选、边界/章节重叠证据，并提供“保留原 Scene / 直接替换 / 编辑后替换”。历史列表区分“原已采用 · 重复提取替换”，替换后提示世界对象和剧情结构需按需刷新。
- Scene 每行只展示当前最高优先级主操作：复核、查看跨章建议、确认章节定位、整理映射、关联章节、补全设定、编辑。完成一项后刷新为下一项；健康标签可直接执行对应操作。桌面端显示“上下文主按钮 + 编辑 + 更多”，窄屏只显示“主按钮 + 更多”，“更多”固定包含打开写作、合并和拆分。
- Scene 零选择时不渲染批量操作条；单选直接显示并执行真实主操作，至少双选后才显示机械合并与 AI 融合，同类多选显示具体批量操作，混合选择按问题类型列出
  数量并一次处理一组，成功只移除该组选择。复核调用统一 review 命令，正文定位确认单独提示
  只接受章节精度；结构类提醒可标记为无需整理，并从更多菜单恢复，不影响定位或融合建议。
- 跨章建议来自后端持久队列，刷新后恢复横幅和行内按钮。支持逐条融合与批量忽略，不提供“全部接受”。
- 剧情线、篇章纲与 Scene 工作台的 P20 表单都先验证当前 StoryOutline，支持新增设计或修订
  所选并恢复 `outline_generate` 任务。三类 preview 都进入对应子视图的 `?review=ai` 独立页，
  分别以作者可读字段编辑信息推进、篇章目标/冲突/关键转折，或 Scene 的章节范围/目标/冲突安排/场景走向/叙事作用；重叠资产、作者决策和总纲冲突
  按需展开。本机草稿以 project + source task 隔离，成功采用或明确放弃才清理，409 冲突跨刷新
  保留并阻止重复采用。Scene 隐藏引用字段原样保留，作者可读选项在提交前适配回既有字段。P20 不进入生成中心，apply wire 与后端 strict schema 不变。
- 剧情线详情把同一 `information_movement_id` 的伏笔/揭示按章节合成默认展开的时间线；无
  active 线程关联的计划进入“未归入剧情线”，作者通过现有 API 分配。旧入口打开后滚动、聚焦
  并短暂高亮包含对应类型的剧情线，无匹配项时聚焦信息推进区。
- `OutlineView.vue` 的剧情线、篇章纲与底层伏笔/揭示数据继续支持 status / deep_import source /
  workflow_id / needs_review 筛选；后两者只在剧情线页内部消费，不再占顶层导航。
- 筛选只改变视图，不自动 promote、deprecated 或删除资产；状态变更必须来自明确按钮、选择器或二次确认操作。

## AI 地图册工作台

- 首次主操作为“一键生成地图册”；已有 adopted 页面后为“补全/更新地图册”，完整重做在次级入口。
- “本次生成结果”和“我的地图册”分离；采用只增加候选，不替换旧图，同节点多张 adopted 页面组成画廊。
- 候选固定显示资料直接支持、AI 视觉补全和资料冲突；完整来源渐进展开，有冲突页面采用前二次确认。
- 有旧图时显示“地图册已有图片 / 新候选”对比与同步缩放；移出只在旧图区次级菜单，且单独确认、可恢复。
- 生成进度显示计划页数和当前页，支持“生成完当前页后停止”；`provider_in_flight` 恢复会明确提示潜在重复费用。
- 有空间补充时显示简短摘要；旧 run 不显示该区域，摘要不暴露事实、来源、prompt 或内部 ID，窄屏仍可阅读。
- 地图名称由 Vue 标注层显示；桌面支持精确拖动与蒙版，窄屏只保留浏览、采用和拒绝，不用滑动手势做决定。
- 图片以鉴权 Blob 读取，不向浏览器暴露 S3 key 或长期预签名 URL；切换项目和视图时释放 Object URL。
- 生成默认仍为快捷流；可选在生图前逐页检查、复制和 800ms 自动保存画面说明，并为每页选择站内或外部生成。
- PNG/JPEG 上传提供本地预览、进度、取消和保留表单重试，成功后仍进入候选审核；地图树与图片选择独立维护，可调整上级、层级和同级位置。

## API 封装风格

- 统一 `request()` 处理超时、错误映射、FormData；封闭测试令牌遭遇 401 时使用应用内密码模态框收集一次性内存令牌，不调用浏览器原生 `prompt()`
- 高风险 wrapper 的 method、path、必需参数和长耗时 timeout 由 `apiContracts.js` 注册，`api.js` 通过 helper 生成实际请求；同步 LLM 生成等待 35 分钟，为后端 30 分钟生成窗口留出收尾余量，异步任务提交和后续无总截止轮询分开处理。这只校验请求契约，不覆盖响应字段级 schema drift
- 按模块分组：`api.projects.*` / `api.world.*` / `api.outline.*` / `api.context.*`
- 地图册接口挂在 `api.world.*` 下，后端前缀为 `/api/world/map-atlas`；图片 wrapper 使用 Blob response

## 安全与渲染约束

- Vue 模板动态文本使用插值自动转义；命令式 seam 优先走 `textContent`
- 必须插入 HTML 时先走 `esc()`
- 不把用户/AI/API 返回的未转义内容直接写入 `innerHTML`
- `index.html` 通过 CSP meta 建立 baseline：脚本仅允许本源，样式不允许外部 origin，连接仅允许
  本源、本地 `localhost` 和 `127.0.0.1` 开发后端，并禁止 `object-src`。地图册图片由同源鉴权接口读取。
- 当前 `style-src` 仍保留 `'unsafe-inline'`，用于兼容入口与少量 inline style；收紧
  `style-src` 需作为独立 CSP 变更评审，不是前端页面 Vue 所有权迁移的未完成阶段
