# 小说结构化创作控制台 — 前端

面向中文作者的**小说结构化创作控制台**。全站采用“编辑档案”视觉系统：米白纸张、深蓝结构线、朱红功能索引和克制的几何编排，同时支持暖色与暗色主题。

## 快速启动

开发时使用 Vite dev server，支持 CSS 热更新和 JS/HTML 自动刷新。地图视图首次初始化时会按需从固定 CDN 加载 Leaflet，因此离线使用时需要确保浏览器可访问该资源。

```bash
cd frontend-console
npm install
npm run dev
# 打开 http://localhost:8080
```

常用验证脚本：

```bash
npm run test
npm run test:watch
npm run test:e2e
npm run test:e2e:functional
npm run test:e2e:smoke
npm run test:e2e:map
npm run test:e2e:map-perf
npm run test:e2e:real-llm
npm run test:e2e:worker
npm run test:all
```

当前 `package.json` 未定义前端构建脚本，也没有独立 lint/format 依赖；前端验证以 Vitest、Playwright 和仓库级 diff 检查为主。

## 后端连接

前端默认连接 `http://localhost:8000/api`。

如需修改后端地址，可在页面加载前注入全局 `API_HOST`，或调整 `api.js` 中的默认地址。

## E2E 测试

Playwright 的所有 profile 都 fail-closed：必须显式提供名称含独立 `audit` / `e2e` / `test`
标记的 PostgreSQL `DATABASE_URL`，并设置 `PW_REUSE_EXISTING_SERVER=0`。配置在创建
`webServer` 之前完成校验，因此缺失 URL、非 PostgreSQL、开发库名或复用未知服务都会在
migration 前失败。可通过环境变量避开端口冲突：

```bash
DATABASE_URL='<dedicated-postgresql-url>' PW_REUSE_EXISTING_SERVER=0 \
  BACKEND_PORT=8010 FRONTEND_PORT=8090 npm run test:e2e:smoke
```

启动命令会在后端启动前执行 `APP_ENV=test alembic upgrade head`；
默认 `test:e2e` / `test:e2e:functional` 只收集功能测试，排除地图性能、真实 LLM 和
worker 套件。各专用入口分别为：

```bash
DATABASE_URL='<dedicated-postgresql-url>' PW_REUSE_EXISTING_SERVER=0 npm run test:e2e:functional
DATABASE_URL='<dedicated-postgresql-url>' PW_REUSE_EXISTING_SERVER=0 npm run test:e2e:map-perf
DATABASE_URL='<dedicated-postgresql-url>' PW_REUSE_EXISTING_SERVER=0 npm run test:e2e:real-llm
DATABASE_URL='<dedicated-postgresql-url>' PW_REUSE_EXISTING_SERVER=0 npm run test:e2e:worker
```

如果默认端口已有旧服务，先停止旧服务，或像上面一样指定备用端口；测试配置不会复用它。
`APP_ENV=test` 只切换应用模式与测试路由，不会自动改写 `DATABASE_URL`。
若本机同时运行开发 worker，应确保它不连接同一个 E2E 数据库，避免抢占 E2E 创建的任务。
`scripts/e2e-servers.sh` 使用同一 fail-closed guard，会先校验并迁移当前 `DATABASE_URL` 再启动
backend；通用 `backend/scripts/dev_server.py` 不自动迁移。

地图功能回归使用 `npm run test:e2e:map`；专用性能采样使用
`DATABASE_URL='<dedicated-postgresql-url>' PW_REUSE_EXISTING_SERVER=0 npm run test:e2e:map-perf`。
性能命令只接受名称含独立 `audit` / `e2e` / `test` 标记的 PostgreSQL 库，
固定 Chromium 1280×720、workers=1、retries=0，并断言真实 Leaflet 1.9.4 已加载；从页面公开
`map:interactive` / `map:performance-sample` 事件采集冷启动、预热、10 次热导航、
100 帧和真实点击/拖动/wheel/touch 输入。Playwright 输出保留
`map-performance-standard.json` 与 `map-performance-stress.json`，包含 fixture checksum、
实际 API payload checksum、混合地形语义 payload、原始 frame/input 分段样本和运行环境。普通 24×18 / 压力 200×200 热导航 p75 分别强制
`≤2s` / `≤3s`，任一热样本不得超过预算两倍；真实输入到下一帧 p95 强制 `≤33ms`。

深度导入完成条会根据项目地图上下文保留一个明确下一步：已有 active 地图时进入项目地图
收件箱；无地图但有已采用地点时复用 quick-create 预览/确认；仅有候选地点时带
`entity_type=location&source=deep_import&workflow_id=...` 打开世界对象审核。存在该行动时完成条
不会自动消失，刷新后仍从持久化 workflow 恢复。下一步上下文或待处理列表
加载失败时显示可重试错误，不将错误伪装成“无下一步”；弹窗被拦截或导航回调
失败时也不清理完成条。所有异步回写都绑定 task 启动时的 project/workflow 和生命
周期代数，项目切换、新任务或 dispose 后的晚到响应会被丢弃。

后端地址可用 `API_HOST` 覆盖，支持 `http://localhost:8000` 或 `http://localhost:8000/api`。
如果 `webServer` 超时，先运行：

```bash
cd ../backend
python scripts/doctor.py --json
```

## 文件结构

```
frontend-console/
├── index.html              # 单页应用入口
├── styles.css              # 基础布局、组件和页面样式（设计 Token 驱动）
├── editorial-theme.css     # 全站编辑档案主题覆层（浅色 / 暖色 / 暗色）
├── state.js                # 全局响应式状态管理
├── stateSlices.js          # 状态副作用、listener 通知、DOM 同步调度 helper
├── api.js                  # API 封装（projects/world/rag/context/writing/imports/tasks）
├── apiContracts.js         # vanilla JS 共享 API 契约注册表（高风险 wrapper 子集）
├── router.js               # Hash 路由系统
├── commands.js             # 命令系统（全中文帮助）
├── app.js                  # 应用主入口（快捷键绑定）
├── shared/                 # 可复用业务组件与工具
│   ├── smartDedup.js       # 智能去重管理器
│   ├── referencePicker.js  # 作者向对象名称搜索与稳定 ID 回写
│   ├── confirmAsync.js     # 异步二次确认封装
│   ├── writingToolsResult.js # 工具结果应用到 orchestrator
│   ├── sceneLocator.js     # 光标/章节定位当前 Scene
│   └── ...                 # 其他共享模块
├── views/                  # 一级路由视图
│   ├── projectView.js      # 项目
│   ├── writingView.js      # 写作台 orchestrator
│   ├── writing/            # 写作台子模块
│   │   ├── chapterTree.js
│   │   ├── editor.js
│   │   ├── versions.js
│   │   ├── publish.js
│   │   ├── deepImportRecovery.js
│   │   ├── autoExtraction.js
│   │   ├── conflictCheck.js
│   │   ├── sceneAlerts.js   # Scene 确定性现场警报与校验新鲜度
│   │   ├── scenePanel.js
│   │   ├── versionDiff.js   # 只读临时版本 Diff
│   │   ├── outlineFloat.js
│   │   ├── focusMode.js
│   │   ├── tools.js
│   │   ├── mobileQuickNote.js
│   │   └── submodules.js   # 子模块工厂
│   ├── worldView.js        # 世界对象 / 关系 / 别名 / 世界书 / 地图子标签
│   ├── mapWorkspaceView.js # 地图一级工作台
│   ├── mapView.js          # 动态地图主视图
│   ├── mapState.js         # 地图前端可观察会话状态
│   ├── mapEditingSession.js # 编辑草稿、历史、CAS 基线与 apply 生命周期
│   ├── mapHexRenderer.js   # 六边形渲染
│   ├── mapEditPanel.js     # 地图编辑面板
│   ├── mapLayerSession.js  # exclusive/floor 当前子层与 isolate 会话投影
│   ├── mapPathRenderer.js  # 连续道路/水系几何、裁剪、命中与 Canvas 绘制
│   ├── mapTimelineProjection.js # Scene 状态/差分归一化与只读 Canvas 覆盖
│   ├── mapTerrainAssets.js # 内置覆盖素材包与样式预设
│   ├── mapTerrainRenderer.js # 程序化 Canvas 覆盖素材渲染
│   ├── mapRouteContext.js  # 地图路由上下文
│   ├── outlineView.js      # 剧情结构
│   ├── storyOutlineView.js # 小说总纲当前版、修订历史与 AI 预览采用
│   ├── sceneWorkbenchView.js # Scene 一级工作台
│   ├── ragView.js          # RAG 检索
│   ├── contextView.js      # 旧上下文页代码；当前 hash 入口重定向到生成中心任务页
│   └── generateView.js     # 生成中心
├── tests/                  # 测试目录
│   ├── writing/            # 写作台子模块单元测试
│   └── shared/             # shared 模块测试
└── README.md
```

## 技术栈

- 纯原生 HTML + CSS + JavaScript
- 无前端框架；地图视口按需加载 Leaflet（ADR-0003）
- 地图编辑器用 `editorLayer` 区分地点、正式底图、覆盖地形、连续线路、标记和领地；`mapEditingSession.js` 统一拥有各内容层草稿、Undo/Redo、冻结的提交范围、临时 ID 对账和 revision CAS baseline，图层树保留独立 draft/history。“应用当前图层”“应用图层结构”或原子“保存全部”共享该生命周期；从请求发出到服务端状态、图层树和线路重载完成期间，整个地图工作区保持锁定并拒绝二次提交，409 会刷新基线但保留本地草稿。
- 图层面板使用递归树，展示祖先继承后的有效显隐、锁定、透明度与 zoom；exclusive/floor 当前子层由 route + localStorage 会话投影管理，isolate 不持久化。世界对象通过 map presence 在多张地图和多条线路间选择并双向定位。
- 连续道路/水系由 `mapPathRenderer.js` 负责 RDP 简化、平滑采样、变宽绘制、AABB 裁剪和命中测试；Pointer 手绘、节点拖动、端点吸附与线路草稿由 `mapView` 编排。地图 Canvas 使用单 RAF 和 revision/viewport 缓存。
- Scene 时间轴由 `mapWorkspaceView` 消费 timeline/state-at 只读投影，支持 Scene 游标、前后步进、
  播放节奏、轨道过滤、candidate preview 和空间连续性面板。`mapTimelineProjection.js` 负责
  响应归一化、投影签名和 Canvas 覆盖；事实变化不依赖 `editor_revision` 失效缓存。
- 地图总览包含项目级“地图收件箱”，只展示未分配的待处理 observation。作者可按类型、
  Scene、来源、置信度和服务端 eligibility 筛选；筛选在服务端分页前生效。分配到 active 地图后继续完成四类类型化表单；
  来源证据与置信度只读。所有写操作携带 observation `updated_at`，409 时保留本地输入并展示
  最新服务器摘要。普通卡片把导入来源和事件类型转换为作者可读标签，并移除已经由
  Scene/章节锚点满足的矛盾“缺少来源”提示；原始 Scene ID 只保留在诊断筛选与复制信息中。
- 地点和标记拖动统一使用 Pointer Events，并在拖动期间暂停 Leaflet 平移。归档列表与 active 地图树分离，地图删除入口实际归档整棵子树。
- 地点标签和聚合簇位于专用 Leaflet pane，标签命中先打开地点详情，
  只有未被标签/控件消费的背景指针才进入 Canvas。
- 覆盖地形使用自然环境、城市交通、奇幻危机三个内置程序化素材包及标准/柔和/高对比预设；未知素材显示中性占位并保留原 asset key，不支持用户上传。
- 所有 UI 文字为中文
- 作者主流程的对象引用统一按名称搜索和选择；共享 `referencePicker` 仅把 ID 回写到现有隐藏字段/请求 payload。同名项用类型、状态和摘要消歧，无法解析的旧引用保留为“不可用引用”。Workflow、任务和原始 Scene ID 只位于折叠诊断区，并标记 `data-diagnostic-field`。
- 编辑档案主题以米白纸张、深蓝结构线和朱红索引色为主，支持暖色与暗色模式

## 路由与设置

- 项目回收站支持单个恢复、单个永久删除、批量恢复和批量永久删除；永久删除必须二次确认，批量删除使用后端原子接口，不做部分成功。回收站每页 20 条，桌面端大模态框用双列完整展示当前页，并提供上一页、下一页和总数。
- 一级路由包含 `project`、`writing`、`world`、`map`、`outline`、`rag`、`generate`、`settings`、`project-settings`；`outline` 默认进入层级最高的 `story-outline`，子导航再依次进入篇章纲、剧情线、Scene 等结构资产。Scene 工作台位于 `outline/scenes`，旧 `scene` 路由会自动跳转到该入口。快速切换项目或初始化期间使用浏览器前进/后退时，晚到的项目元数据请求不会继续提交旧路由和页面，也不会覆盖当前工作区。新鲜渲染由路由提交 view 返回的 HTML 后再调用 `onRendered()`；需要访问新 DOM 的事件绑定应放在该生命周期中，keep-alive 恢复仍使用 `onActivate()`，不要用零延时定时器猜测 DOM 提交时机。
- 地图 hash 使用 `overview` / `recent` / `dashboard` / `live` / `lens` 规范模式；旧
  `mode=map` 首次读取后使用 replace 规范为 `mode=live`。跨地图/返回总览使用
  history push，同地图的模式、Scene 和聚焦变更使用 replace。
- 应用首屏、全局路由切换以及写作、大纲和 Scene 工作台的主加载边界使用共享骨架屏；状态容器保留屏幕阅读器可感知的具体加载文本，视觉占位标记为装饰内容，并遵守 `prefers-reduced-motion`。按钮提交、任务进度和局部数据刷新继续使用各自的明确状态，不用通用骨架替代业务反馈。
- 项目级“智能去重”不再占用独立全局操作条，只在世界对象与大纲的页面内工具栏显示；Scene 工作台中与“场景（scene）自动提取”和大纲子标签同行。每个页面只保留一个入口，扫描状态跨页面持续，返回世界或大纲后恢复“查看智能去重/查看去重建议”。每行根据当前最高优先级待办切换主按钮；桌面端额外保留“编辑”，移动端收敛为主按钮与更多菜单。健康标签可点击，跨章建议刷新后从后端恢复。
- 项目级智能去重使用大尺寸双栏裁决工作台：左侧按 group 展示状态，
  右侧展示字段对比、合格主对象、逐成员动作、影响和证据。草稿以
  `projectId + scanTaskId + groupId` 隔离，不提供手填主对象 ID；窄屏时队列移到
  对比区上方。只提交全部成员已明确裁决的组，成功组锁定，失败/过期组
  保留裁决和错误以便重试。旧任务只有 `suggestions` 时仍使用 pair 兼容面板。
- 剧情线、篇章纲、伏笔和揭示加载失败时显示可重试的内联错误，不把失败伪装成空列表；通用 API 409 显示“请求冲突”并继续附带后端领域消息。
- 大纲的剧情线、篇章纲、伏笔和揭示子标签顶部提供“AI 分析大纲”。作者先填写可选的
  分析目标与章节范围，再在通用 AI 参考弹窗中检查该范围内按顺序排列的 Scene、相关结构
  计划、人物和物品；确认后提交可恢复的 `outline_analyze` 任务。完成结果以转义后的只读
  Markdown 和已确认资料摘要展示，不提供应用入口，也不会直接修改大纲资产。同一项目只保持一个运行中的
  手动分析；后端允许时可二次确认取消，取消状态按终态恢复而不伪装成失败。新请求只在获得有效 `task_id`
  后替换上一份已完成报告，并以所属项目隔离持久化与轮询，避免晚到响应在项目切换后回写当前页面。
- `outline/story-outline` 展示当前小说总纲的全部 creative core、Markdown 正文、主要剧情线、宏观推进和开放决策。手工保存、采用 AI preview 和采用历史内容都会使用 current revision 作为 CAS base 创建新 revision；历史不会被原地改写或回退版本号。AI 表单只包含作者意图、计划尺度、覆盖描述、显式可选人物/世界对象和是否参考当前总纲，不包含起止章；人物/对象不显式选择时由后端自动取 Top-K，结果完整可编辑且不自动采用。生成任务只恢复匹配 project / `story_outline_generate` / `outline.story_outline.generate` 的记录，接受受管 LLM provenance 但拒绝其他结果字段；轮询与取消显式携带 `novel_id`。409 保留当前 DOM 编辑内容，重新加载后更新 CAS base；同一 apply payload 重试复用幂等键，内容或 base 改变时轮换。
- Scene 融合与拆分使用大尺寸字段对比表，完整展示 AI 建议、原 Scene 引用、叙事标签、POV 和章节映射；默认显示全部字段，可只看服务端初始预览中的差异。融合预览属于同步 LLM 请求，使用 90 秒生成窗口，不受普通 API 的 15 秒超时限制。长来源证据按需展开，AI 建议始终可见。叙事标签统一用 `draft` 表示“未标注”，拆分时显式清空的字段会按空值保存。废弃融合来源需要在预览内再次确认；保存请求期间所有融合操作保持锁定，失败后恢复控件并保留当前编辑内容。
- 深度导入和 Scene 自动提取任务以 `taskId + projectId` 持久化；查询与取消都显式携带 `novel_id`。Scene stage 百分比是基于历史实测的耗时估算，Phase 0 只显示准备状态。Scene 工作台轮询只局部更新进度卡，不重绘正在浏览的列表。运行中的进度卡可在二次确认后取消当前任务；瞬时查询失败保留恢复记录，只有明确 404 或用户关闭时清理失败/已取消任务。
- 共享任务卡只在后端 `available_actions` 包含 `retry` 时显示重试；`restart_origin` 与深度导入 `resume/abandon` 继续走各自领域流程。
- 生成中心自定义模板可查看修订历史并把旧版本载入编辑器；载入不写库，仍需用户明确保存。
- 前端依后端契约分页或拦截超限请求：Scene 建议每次最多忽略 100 条，地图分组每次最多处理 100 条，地形修改每次最多 10000 格，单地点每次最多绑定 5000 格；不会通过多请求静默产生部分成功。
- 生成中心 world 工作区每次最多附带 20 章索引，长对话只发送最近 40 条消息；当前页面历史不因请求上限被删除。本地 v2 会话按“项目 + world workspace + 来源页 + target”隔离，只缓存对话、选择项和 suggestion ID，不缓存服务器页面正文，也不迁移旧 v1 状态。
- 世界书资料编辑支持稳定 section 排序和页面模板，AI 参考规则继续使用受限表单、发布与 dry-run trace；AI 对话、目标和模板选择已从世界书侧栏移除。“用 AI 完善此页”会在未保存时要求先保存，随后进入生成中心。世界书、生成中心和通用 AI 参考弹窗只在作者显式选择已发布 Activation Profile 后发送 profile ID，不默认激活长期规则。
- 生成中心 world 工作区提供项目/来源页状态、对象/完善当前页/新建页面目标、大尺寸共创对话、章节/Scene/剧情线/人物/世界对象/简介/Profile 上下文面板，以及可编辑的完整页面预览。页面应用只写服务器工作稿，成功后返回世界书；正式页仍需作者显式发布。
- 世界书默认使用中文类别和任务状态；投影恢复键、任务 ID、原始状态与后端 warning
  收入折叠的“诊断信息”，不占用作者阅读和编辑设定的主界面。
- 写作台自动保存以编辑序号保护请求期间的新输入；版本切换触发局部重绘时不会用旧响应覆盖正文。发布成功提示只在章节状态刷新完成后出现；后台 RAG / 记忆后处理完成只收起进度，不再次重载当前编辑器，且已 dispose 或已被新任务取代的轮询响应不会回写。恢复历史正文时保留选择当时的最新版本快照，发布前若其他会话已更新则提示 409 冲突。“AI 工具”菜单与“专注模式”位于编辑器顶部同一操作行，正文反向提取入口统一显示为“从正文整理 Scene”。
- 写作页右侧“写作副驾驶”常驻显示当前 Scene 的确定性警报摘要，并在“警报”标签中组合 Scene 结构、must/must_not 字面覆盖、地图风险和最近冲突检查；编辑后旧检查立即标记过期，切换项目、章节、Scene 或草稿时晚到响应不会覆盖当前驾驶舱。警报不自动运行 LLM，也不创建 finding。
- 版本条与版本历史提供只读“比较版本”，可临时比较工作稿、待审核、已发布和归档版本。Diff 先按段落对齐，再在变化段落内标记中文字符、标点和英文词，识别稳定段落移动并对超长输入安全降级；动态正文统一转义，比较本身不创建、恢复或采用版本。
- 390px 速记输入会实时同步同一编辑器状态；首次保存返回的 draft id/version 会立即回写，连续保存复用同一工作稿，切换“完整编辑器”时保留尚未保存的正文。
- RAG 索引维护的技术诊断区可按需加载隐私安全的检索追踪摘要，不展示 raw query 或正文。
- 小说检索的智能/字面模式都按章节聚合同章结果：智能模式解释为语义相关性检索，字面模式解释为完全一致文字匹配；结果卡显示该章聚合的相关片段数或出现次数。
- 小说检索一次最多取回 100 条现有 evidence 命中，但首屏只挂载 20 张结果卡；“加载更多”
  每次再显示 20 条。检索词、方式、正文版本、可见视角、章节和 scope 写入 hash URL，刷新与
  前进/后退会恢复并重新检索；显示游标和证据抽屉不写 URL。新查询会 abort 旧请求，并以
  project/lifecycle generation 拒绝晚到响应。证据抽屉另有独立 abort/generation/project/drawer
  门禁，关闭抽屉或切换项目后的旧正文、引用和导航结果不能覆盖当前抽屉。
- `settings` 是无项目也可访问的全局设置页；`project-settings` 管理当前项目的 LLM 主配置、深度导入参数和作者偏好。主配置中的“默认输出上限”由非深度导入业务调用继承，系统默认 `12000`；深度导入继续显示并使用自己的阶段预算。
- 旧 `llm` 入口会按当前项目状态跳转到 `project-settings` 或 `settings`。
- 旧 `context` hash 不再是一级页面，路由层会重定向到 `generate?tab=task`。

## 内容优先布局

- 项目页采用编辑式“作品档案”布局：米白纸张、深蓝与朱红索引色、几何拼贴项目封面；
  当前项目置顶并占主版面，搜索、批量选择、导入和回收站仍沿用原有交互与接口。
  `720px` 以下改为单栏，390px 保持完整统计与主操作且不横向溢出。
- `editorial-theme.css` 将同一档案语言扩展到全部一级页面、子标签、弹窗、表格与辅助栏；
  `styles.css` 继续拥有结构布局，主题覆层不得改变路由、DOM 事件契约或 API/wire shape。
- 项目页以外的工作区使用独立档案编号、英文索引角标和克制的几何切线；一级空状态采用分栏海报式构图，
  窄屏自动收敛为单栏，不以装饰遮挡操作或业务反馈。
- 全局设置与项目设置在桌面背景中增加低对比度单色齿轮、电路线和节点水印；装饰层不接收指针事件，
  `760px` 以下隐藏，避免挤压表单和触控区域。
- 功能控件必须保持可辨识：主操作使用深蓝实体面与朱红索引线；普通按钮有明确边框；文本输入、
  选择器和编辑区使用纸张底、完整边框与左侧功能线，聚焦时切换朱红并显示焦点环。暗色主题
  保留同一层级，`760px` 以下常用控件高度不低于 `42px`，表单输入不低于 `44px`。
- 写作、Scene、世界书、地图和生成中心采用统一的内容优先分栏；桌面端正文、主列表、编辑区或画布获得约三分之二的可用宽度。
- 辅助栏使用统一的主题化折叠控件，折叠选择按项目和页面保存在当前浏览器会话中；写作专注模式仍优先隐藏两侧栏。
- 中等宽度会重排第三栏，`760px` 及以下改为单栏、抽屉或手风琴；折叠控件完整支持浅色、暗色、键盘焦点和减少动效偏好。
- 390px 地图保留浏览、tap 和拖动，地形、线路节点、势力 hex 与递归图层编辑
  显示只读摘要并提示转交桌面端。世界书在 ≤760px 为单栏；Scene 工作台无
  `scene_id` 时保持未选中列表。
- 任务进度默认显示紧凑摘要、状态和细进度条；失败、恢复或需要用户确认的状态自动展开，用户手动选择在任务重绘时保持。
- 共享业务模态框使用带标题关联的 modal dialog 语义；打开后焦点进入内容或操作区，Tab/Shift+Tab 不离开对话框，Escape 关闭后恢复到原触发控件。连续替换模态内容时仍保留最初触发点；正文中的可编辑控件发生未保存变化时，关闭按钮、取消、遮罩和 Escape 都会先确认是否放弃，成功操作不重复确认。

## 安全与契约

- `index.html` 配置 CSP meta baseline：脚本仅允许本源和 Leaflet CDN，连接仅允许本源及本地开发后端；`style-src` 暂保留 inline style 兼容。
- 封闭测试服的 `APP_ACCESS_TOKEN` 只保存在 `api.js` 当前页面的 module memory，不读写 Web Storage；刷新页面后需要重新输入。普通请求、导入上传和前端错误上报共用该内存令牌，被后端以 401 拒绝后立即清除。
- 动态内容默认使用 `textContent`；必须拼 HTML 时先走 `esc()`。
- 当前已落地 vanilla JS 共享 API 契约校验第一阶段：`apiContracts.js` 注册高风险 wrapper 的 method/path/query/body/timeout，浏览器 `api.js` 与 Playwright API helper 共用同一 registry 和序列化规则；Vitest 覆盖加载顺序、必填 body、method 固定与代表 endpoint 映射。
- TypeScript / OpenAPI codegen 仍是未来设计项；当前契约层不覆盖响应字段级 schema drift，设计记录见 `docs/frontend/typescript-api-contracts.md`。

## 快捷键

| 快捷键 | 功能 |
|--------|------|
| `?` | 打开快捷键帮助 |
| `:` | 聚焦命令栏 |
| `/` | 搜索 |
| `Esc` | 返回 / 关闭弹窗 |
| `j` / `k` | 上下移动选择行 |
| `n` | 新建 |
| `e` | 编辑 |
| `s` | 保存 |
| `g` | 生成 |
| `r` | 复查 |
| `c` | 确认 |
| `x` | 删除（二次确认） |

## 管理页批量操作约定

- 列表型管理页支持多选、当前可见列表全选和批量工具条，包括项目、世界对象/待处理项/关系/别名、剧情结构、Scene 工作台、写作章节树和地图列表。
- 世界对象库与 Scene 工作台标题区提供“普通 / 热点”模式。URL 的 `mode` 优先；未指定时按项目和页面读取本地偏好，首次默认热点。模式切换保留搜索、类型、状态等通用筛选，并清除热点阶段/focus、分页偏移和批量选择。
- 世界对象热点模式使用后端全量智能排序，不再按自动入库批次切断顺序；顶部显示“重要 / 近期热点 / 其他”聚合和索引覆盖提示，表格与卡片共用热点标签。普通模式保留原批次分组与既有排序。Scene 热点模式仍按剧情顺序，新增“当前 / 后续 / 已写过 / 未定位”进度聚合并默认定位当前 Scene；健康卡继续独立显示整理待办。
- “全选”只作用于当前可见列表或当前分页，不跨分页选择全部筛选结果。
- 世界对象的对象库与待处理对象/别名/关系子标签都在批量工具条提供显式全选；所有筛选区默认折叠，展开状态按项目缓存在浏览器本地，折叠后仍保留当前筛选条件。
- 待处理关系默认按有向对象对分组，别名按所属对象分组；每页可选 20 / 50 组，全选只作用于当前可见项，不隐式选中全部筛选结果。
- 关系组先在右侧抽屉（390px 为全屏复核页）准备独立采用、证据归并或忽略决策；仅相同类型或同一保守映射的候选默认勾选。端点搜索调用项目对象接口，不受当前 20 条列表限制。
- 关系卡显式提示反向候选/正式关系，抽屉实时预览采用结果。前端在确认前校验 20 个关系决策 / 50 条所选关系上限，成功后自动进入下一组；单项失败会在原卡片展示服务端原因。
- 别名编辑器保留未收录的原类型；映射建议必须点击才会修改。批量采用/忽略均一次确认、一次请求，上限 50 条；部分失败或过期项保留选中和编辑草稿便于重试。由建议队列拥有的 compatibility shadow 别名不可在该工作台另行采用。
- 复核卡默认只展示作者可读的来源、Scene、章节、短引用与强度/置信度；Workflow、Scene UUID 和原始证据收进可复制的“诊断信息”。关系数值始终称为“强度”。
- 已采用对象库的多选工具条提供“融合”和“标记为别名”，不再提供“批量标记已检查”或“批量采用”。两种操作都要求选中至少两个同类型对象、明确选择保留对象并二次确认；融合会合并内容和关系，别名化只迁移关系和登记来源名称，来源对象均进入可审计历史态。
- 所有待处理世界对象都可在采用前微调名称、类型和概要；普通 candidate 通过 promote 请求在同一事务中编辑并采用，建议队列对象继续走队列裁决。待处理别名和关系在分组工作台中先保存决策草稿，再统一预览、确认和提交。
- 世界对象的新建、编辑后采用和普通编辑共用项目类型目录：可复用已有自定义类型或创建新类型；对象库筛选同步支持自定义类型。已采用对象改类型会二次确认，后端专属依赖 blocker 在原弹窗内按类别和数量展示并保留输入。
- 待处理对象中，已有明确别名目标的条目按目标对象合并展示；没有明确目标但同类型名称高度相似的条目也会合并展示。该分组只影响当前页界面，不自动合并、采用或写库。
- 删除、忽略、永久删除等危险批量动作必须二次确认；执行后会显示成功/失败数量。
- 普通待处理对象的“合并”是行内主操作，不放在更多菜单里；没有明确目标对象时需要先搜索并选择目标。由建议队列拥有的兼容影子只通过建议采用/忽略，不直接修改影子对象。
- RAG、Context、Generate 等状态/生成页面不强制提供批量操作，只保留清晰的空状态、错误状态和任务进度。
