# Module: frontend / 前端控制台

## 定位

前端为 SPA 控制台，通过 REST API 驱动整个创作工作台：外壳（`index.html` 骨架、hash router、
Proxy 状态、命令栏）保持 Vanilla JS，视图按 ADR-0009 以 island 模式渐进迁移到 Vue 3
（`project` / `rag` / `settings` / `project-settings` 已迁移；Vue 视图经 `vue/mountIsland.js`
注册进 vanilla router，组件只经 `vue/bridge/index.js` 访问既有基建，动态内容禁止 `v-html`）。
动态地图视口使用 Leaflet。

## 架构

- 入口：`index.html`
- 基础样式：`styles.css`
- 全站主题覆层：`editorial-theme.css`
- 全局状态：`state.js`
- 状态切片 helper：`stateSlices.js`
- 路由：`router.js`
- API 封装：`api.js`
- API 契约注册表：`apiContracts.js`
- 视图：`views/*.js`（vanilla）+ `vue/views/**`（Vue SFC island，经 `vue/mountIsland.js` 注册）
- Vue 基建：`vue/bridge/`（组件访问 vanilla 基建的唯一入口）、`vue/composables/`
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
| `vue/views/project/ProjectView.vue` | `project` 路由（Vue island）；编辑式作品档案首页、项目检索/排序/批量选择、项目 CRUD、回收站与导入入口 |
| `writingView` | Scene 树 + 工作稿编辑器 + AI 建议采用 + Scene 面板；版本历史；授权深度导入；Scene 地图摘要跳转 |
| `worldView` | 对象库普通/热点双模式、统一待处理（对象/关系/别名）、历史筛选；热点模式显示重要/近期热点聚合并使用服务端全量排序；世界书编辑概览/结构化 sections、管理页面模板和 AI 参考规则，并以“工作稿保存 → 明确发布”维护页面；不承载 AI 对话侧栏，只提供“用 AI 完善此页”保存后跳转；展示只读作者版世界观简介及版本/自动维护状态；`map` 子标签现在只做兼容跳转 |
| `mapWorkspaceView` | 地图一级工作台，总览、最近地图、地图树、图层开关、搜索、聚焦；世界动态总控台、活地图、叙事透镜、Scene 时间轴与连续性检查 |
| `mapView` | 具体地图渲染与编辑：地形、地点绑定、标记、势力范围；浏览态地点标签避让与聚合 |
| `outlineView` | 大纲分层创作；默认组合 `storyOutlineView` 管理小说总纲，在篇章纲、剧情线和 Scene 工作台分别提供当前层 AI 创作。伏笔/揭示作为剧情线的信息推进时间线与未归类区展示，不再是顶层子标签 |
| `sceneWorkbenchView` | 由 `outline/scenes` 承载的 Scene 普通/热点双模式、管理筛选、当前剧情定位、拆分/合并、复核与深度导入 Scene 整理；旧 `scene` 路由仅作兼容重定向 |
| `vue/views/rag/RagView.vue` | `rag` 路由（Vue island）；智能/字面检索说明、同章结果聚合、章节索引、索引重建，以及隐私安全的近期检索追踪诊断 |
| `generateView` | 生成中心：world 工作区承载对象/完善当前页/新建页面的共创对话、来源与上下文选择、结构化预览和工作稿应用；同时保留上下文任务预览/编译、POV 与其他既有领域流程 |
| `vue/views/settings/GlobalSettingsView.vue` | `settings` 路由（Vue island）；管理全局 LLM 默认、全局作者偏好、引用此默认的项目列表和本地偏好迁移；全局 LLM 默认不存 API Key |
| `vue/views/settings/ProjectSettingsView.vue` | `project-settings` 路由（Vue island）；管理项目 LLM 主配置、深度导入参数和项目作者偏好；展示 effective source 并支持字段恢复继承；通用输出上限与深度导入阶段预算分开说明 |

## 路由与状态特性

- `router.js` 维护 `_lastSubViewMap`，在主视图切换后恢复最后子标签
- `outline` 的规范默认子视图是 `story-outline`，导航层级为“小说总纲 → 篇章纲 → 剧情线 → 场景工作台”。旧 `scene` 路由重定向到 `outline/scenes`；旧 `outline/foreshadowing` 与 `outline/reveals` 重定向到剧情线的信息推进区域。
- `writing` 与 `outline` 被标记为 KeepAlive 视图；DOM 缓存按项目分桶，renderer 单例的项目级内存状态必须在 `onActivate()` 校验归属，不匹配时重新装配。`outline/scenes` 为避免复用过期工作台 DOM，不进入 KeepAlive 缓存
- 世界对象库和 Scene 工作台使用 `mode=normal|hot`；URL 优先于按“项目 + 页面”保存的 localStorage 偏好，无偏好默认热点。切换模式保留通用筛选，清除模式专属筛选、分页偏移和批量选择。
- Scene 工作台的筛选、详情和复核状态由 `sceneWorkbenchView` 持有；当前 Scene 与模式通过 `outline/scenes?mode=...&scene_id=...` 写入浏览器历史。热点默认请求 `anchor=latest`，显式 Scene、分页、阶段或管理筛选时不自动锚定。
- `map` 路由会解析 query 上下文，用于承接写作页和世界页跳转
- `world/map` 仍保留入口，但现在会自动跳转到一级 `map`
- `settings` 是无项目也可访问的全局设置页；`project-settings` 依赖当前项目，未进入项目时显示空态并提供返回全局设置
- `llm` 是旧入口兼容别名：有当前项目时跳转 `project-settings`，否则跳转 `settings`
- Vue island 生命周期（ADR-0009）：`onEnter` 预取数据（router 会 await）→ `render` 返回挂载点 div → `onRendered` 挂载（同视图 forceRefresh 不触发 `onLeave`，先卸载残留实例）→ `onLeave` 卸载；当前已迁移的 `project` / `rag` / `settings` / `project-settings` 均不在 KeepAlive 名单内，keep-alive 视图（writing/outline）的 island 策略留待对应迁移阶段
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
  不新增封面数据或 API；`720px` 以下收敛为单栏，`390px` 不产生页面级横向溢出。
- 全部一级页面、子标签、弹窗、表格和辅助栏共用“编辑档案”主题：米白纸张、深蓝结构线、
  朱红索引与低圆角几何编排。`styles.css` 保持结构布局，`editorial-theme.css` 作为后加载
  覆层拥有视觉表达；路由在 `#workspace-content` 写入 `data-workspace-view/subview` 只供样式
  定位，不得被业务逻辑、数据请求或测试 fixture 当作状态来源。
- 功能性按钮、输入框、选择器和编辑区要比只读内容更易辨识，但不脱离主题：主操作使用深蓝
  实体面与朱红索引线，普通操作保留可见边框；可编辑字段使用纸张底、完整边框与左侧功能线，
  focus-visible/聚焦切换朱红并显示焦点环。暗色主题保持相同层级；`760px` 以下常用按钮高度
  不低于 `42px`，输入控件不低于 `44px`。
- 创作工作台以正文、主列表、编辑区、生成结果和地图画布为主对象；桌面端主对象目标占分栏内容宽度的约 `64%–68%`。
- `shared/workspaceRail.js` 统一渲染主题化辅助栏，并以 `项目 + 页面 + 栏位` 为 key 在 `sessionStorage` 保存折叠状态。辅助栏折叠不得重置选择、筛选、滚动位置或未保存编辑内容。
- 写作专注模式高于普通辅助栏状态；中等宽度重排第三栏，`760px` 及以下使用单栏、抽屉或手风琴，不允许产生页面级横向溢出。
- `shared/progressRenderer.js` 的任务卡默认可折叠：普通运行/完成态显示紧凑摘要，失败或调用方标记 `attentionRequired` 的恢复、重试和确认状态默认展开；用户保存状态优先于自动规则。
- `shared/smartDedup.js` 对 schema v2 结果打开 `{size: "large", protectUnsaved: true}`
  双栏工作台；队列、对比、主对象和逐成员动作共享同一个 group 草稿。
  对比默认“只看差异”；勾选操作与切换合格主对象会保留工作台滚动位置，且主对象 radio
  必须使用真实 asset ID，不能退化为浏览器默认值。
  Scene merge 进入已就绪前必须调用现有 Scene merge preview 并由用户确认。
  工作台不把 `needs_review` 或“稍后处理”发到 apply API，也不允许手填任意主对象 ID。
- 折叠栏和进度摘要必须使用现有设计 token，并覆盖 hover、focus-visible、disabled、错误、暗色主题和 `prefers-reduced-motion`，不得暴露浏览器默认折叠标记。

## 开发与验证脚本

- 开发服务器使用 Vite：`npm run dev`，默认端口 8080，可通过 `FRONTEND_PORT` 覆盖。
- 单元测试使用 Vitest：`npm run test`；监听模式为 `npm run test:watch`。
- 浏览器 E2E 使用 Playwright：`npm run test:e2e`；烟雾子集为 `npm run test:e2e:smoke`。默认启动 fresh 8000/8080 服务，只有 `PW_REUSE_EXISTING_SERVER=1` 才复用已有服务；后端启动前执行 `APP_ENV=test alembic upgrade head`。`APP_ENV=test` 不改写 `DATABASE_URL`；本机存在开发 worker 时应显式传入独立测试库。如端口被旧服务占用，使用 `BACKEND_PORT=8010 FRONTEND_PORT=8090 PW_REUSE_EXISTING_SERVER=0`。
- `npm run test:all` 先跑 Vitest，再跑 Playwright。
- `npm run build`（vite build）仅作 Vue 构建链冒烟验证：`dist` 仍缺少 classic vanilla scripts，不能视为可部署产物。无独立 lint/format 依赖；前端静态约束以现有测试和 `git diff --check` 为主。
- 当前已落地 vanilla JS 共享 API 契约校验第一阶段，覆盖项目、设置、导入、上下文、世界/地图、写作冲突检查和 RAG 的高风险 wrapper 子集；TypeScript / OpenAPI codegen 仍是未来设计项，当前说明见 `docs/frontend/typescript-api-contracts.md`。
- 小说检索继续消费 context evidence API：单次最多取回 100 条现有命中，DOM 首批只挂载
  20 张结果卡并按 20 条渐进加载。检索词、方式、正文版本、可见视角、章节范围和 scope
  保存在 hash URL；前进/后退会恢复表单并重新检索，显示游标和证据抽屉不持久化。新查询
  abort 旧请求，晚到响应还需通过 project/lifecycle generation 才能回写；证据抽屉使用独立
  abort/generation/project/drawer 门禁，关闭抽屉或切换项目后不接受旧正文、引用或导航结果。
- 任务进度卡仅依据后端 `available_actions` 显示 retry；RAG 和世界书投影在 retry 成功后恢复原 task id 的轮询，请求失败时保留原失败卡。
- 生成中心 world 工作区默认开启作者版世界观简介，可按会话关闭；“查看本次上下文”读取响应中的实际 `context_usage`，不事后重编译。来源页面正文始终由服务器重载，本地 v2 会话只缓存对话、选择项和 suggestion ID，并按项目 + 来源页 + target 隔离。任务页签只编译/预览上下文；POV 明示并强制禁用作者全知简介。
- 生成中心任务页签选择章节后，Scene 选择器先展示该章的可用 Scene，同时仍可按名称搜索项目内其他活跃 Scene。
- 世界书、生成中心和通用 AI 参考弹窗只列出已发布 Activation Profile；只有作者显式选择后才随请求发送。世界书规则编辑器提供受限表单和 dry-run trace，不提供 raw JSON、regex 或 Prompt 插槽。世界书存在未保存修改时，“用 AI 完善此页”必须先保存成功再跳转；生成中心页面 apply 只写工作稿，成功后带页面/工作稿 ID 返回世界书。中等宽度把第三栏下移，窄屏改为单栏且不得产生页面级横向溢出。
- 世界书编辑器把“保存并发布”作为始终可见的主操作；只有“保存工作稿”不会改变正式页。
  世界观简介的终止任务 ID 不得在同一页面生命周期内重新挂回轮询，避免失败刷新反复重绘并
  阻断点击。
- 世界书类别、简介状态与投影状态默认使用作者可读中文；投影恢复键、任务 ID、原始状态和
  后端 warning 只放在折叠的“诊断信息”中，不在设定正文和主操作区直接展示。

## 写作流补充

`writingView` 当前不只是草稿编辑器，还承担：

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

- `shared/assetDisplayState.js` 是前端唯一通用映射：结构资产显示“待处理 / 已采用 / 历史”，正文显示“待处理 / 工作稿 / 已发布”。页面不得自行再维护 `candidate` / `canonical` 文案表。
- `attention_reasons`、低置信、冲突和 `needs_review` 显示为注意标签，不替代主状态。
- 主列表默认隐藏历史；只有显式选择历史/raw status 筛选时加载或展示。
- API 保留原始 `status/review_state/fact_status` 兼容字段，前端优先消费领域 `display_state`，必要时才由共享 helper 回退映射。
- AI 正文建议在编辑器中以只读预览打开；“采用到工作稿”成功后加载服务端新 draft 并恢复编辑/自动保存，“拒绝建议”经确认后软废弃候选并回到当前工作稿/已发布稿。顶部“AI 续写”只对服务端已保存的可写或已发布 base draft 开放，不拿未保存本地文本或跨章 Scene 作为替换范围；异步任务轮询没有前端总截止时间，完成后自动打开候选审核面板。普通生成的 `pov_validation=not_applicable` 不显示角色视角失败提示。
- 生成中心的角色视角正文按“章节 + Scene + POV 角色”确认上下文；已有目标章时锁定完整 active 正文，候选仍是该章完整替换稿，Scene 即使跨章也不扩大范围。结果入口跳转写作台统一审核，POV 面板只描述知识边界诊断，不把“未发现明显越权”显示成整体质量通过。
- deep import/stage 启动入口必须先展示自动采用范围并取得明确授权，完成卡展示 `asset_summary` 的已采用/待处理/未采用三类汇总。

## 世界对象分组复核

- 待处理导航与对象/别名/关系子标签复用现有三个列表接口的 `total`，不单独维护计数 API。
- 关系按有向对象对、别名按所属对象分组。每页 20 / 50 组，全选仅作用于当前可见项；搜索常驻，高级筛选折叠，当前条件同步显示为可删除标签。
- 关系复核先准备 `accept` / `merge` / `ignore` 决策；仅相同类型或落入同一保守映射的候选默认勾选。卡片显式提示反向关系但不自动归并，抽屉在提交前预览最终端点、类型、强度和证据范围。
- 端点搜索覆盖同项目 canonical / draft / candidate 对象，排除历史对象和 suggestion shadow，不依赖对象库当前首页。
- 未收录的别名/关系类型以“保留原类型”打开；类型建议只有在用户点击后才更改草稿。置信度只用于筛选/预选，不自动采用。
- 批处理一次确认只发送一个请求，并在客户端先校验关系 20 个决策 / 50 条所选成员、别名 50 条的上限。成功项移出当前选择并自动进入下一组；`stale` / `failed` 项在原卡片显示原因并保留选中与决策草稿，网络异常不丢草稿。筛选、分页和滚动位置在就地刷新后保留。
- compatibility shadow 仍由建议队列拥有；其内联别名在分组复核页只显示“随对象建议处理”，不进入多选或批处理。
- 默认卡片不展示 UUID，只展示“来源 · Scene · 章节 · 强度/置信度”和短引用；Workflow、Scene UUID 与证据引用收进可复制的诊断区。关系字段始终称为“强度”。
- 桌面使用右侧抽屉；390px 变为全屏复核页，复核搜索和主操作按钮高度不小于 44px。

## 结构整理补充

- `storyOutlineView` 只管理 StoryOutline 聚合，不会因为采用总纲而创建 PlotThread、OutlineArc 或 Scene。当前版完整展示 title、creative core 四字段、`outline_markdown`、`major_storylines`、`macro_movements` 和 `open_decisions`。手工保存、AI preview apply 和历史采用都带 current `base_revision_id` 与 `idempotency_key` 创建新 revision；同一 payload 重试保持 key，内容或 base 改变后轮换。409 保留当前 DOM 编辑草稿，显式重新加载后把它 rebase 到最新 current。
- StoryOutline AI 请求只接受作者意图、计划尺度、覆盖描述、可为空的显式人物/世界对象选择和 `include_current_outline`，不提供起止章或强制模板/数量；显式选择为空时由后端自动使用 Top-K。返回内容以 strict 完整 preview 编辑，三个嵌套数组用带字段说明与错误提示的 JSON 编辑区。导航数组是辅助摘要，不要求名称唯一或精确字符串引用；生成完成不自动采用。
- 生成恢复复用通用 workflow 记录与 `/tasks/{id}` 轮询/取消，但只恢复同一 project、`task_type=story_outline_generate` 且 `action=outline.story_outline.generate` 的任务。完成结果允许服务端附带 `managed_llm_steps` provenance；已标记 adopted 的 task 不重复恢复为可采用 preview。路由离开或项目切换后丢弃晚到响应；取消、过期、任务上下文不匹配和短暂查询失败保持不同的作者可读状态。

- `sceneWorkbenchView` 是 Scene 管理主入口，支持按 status / source / workflow_id / needs_review / phase 等条件筛选深度导入结果。
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
- `outlineView` 的剧情线、篇章纲与底层伏笔/揭示数据继续支持 status / deep_import source /
  workflow_id / needs_review 筛选；后两者只在剧情线页内部消费，不再占顶层导航。
- 筛选只改变视图，不自动 promote、deprecated 或删除资产；状态变更必须来自明确按钮、选择器或二次确认操作。

## 地图工作台补充

- `mapWorkspaceView` 保存“最近地图”到本地存储
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
- 写作冲突 AI 修复建议以可编辑草稿展示，用户显式插入当前正文编辑器后才影响草稿内容
- 390px 写作页默认折叠章节辅助栏；作者展开章节后使用带程序化名称的速记编辑器保存短文本
  工作稿，刷新后从后端版本恢复。速记输入实时同步同一编辑状态，首次保存返回的 draft
  id/version 会回写以支持连续保存，切换完整编辑器时保留未保存正文。速记主操作不低于
  44px，发布、版本恢复和长篇结构编辑仍转交桌面端。
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

- 动态文本优先走 `textContent`
- 必须插入 HTML 时先走 `esc()`
- 不把用户/AI/API 返回的未转义内容直接写入 `innerHTML`
- `index.html` 通过 CSP meta 建立 baseline：脚本仅允许本源和 ADR-0003 接受的 Leaflet CDN（`https://unpkg.com`），连接仅允许本源、本地 `localhost` 和 `127.0.0.1` 开发后端，并禁止 `object-src`
- 现阶段 `style-src` 仍保留 `'unsafe-inline'`，用于兼容入口和现有静态模板中的 inline style；迁移 inline style 并收紧 `style-src` 留到下一批
