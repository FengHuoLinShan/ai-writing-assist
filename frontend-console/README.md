# 小说结构化创作控制台 — 前端

面向中文作者的**小说结构化创作控制台**，采用 Apple 极简 + 杂志留白风格的浅色主题，同时支持暗色模式。

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
npm run test:e2e:smoke
npm run test:all
```

当前 `package.json` 未定义前端构建脚本，也没有独立 lint/format 依赖；前端验证以 Vitest、Playwright 和仓库级 diff 检查为主。

## 后端连接

前端默认连接 `http://localhost:8000/api`。

如需修改后端地址，可在页面加载前注入全局 `API_HOST`，或调整 `api.js` 中的默认地址。

## E2E 测试

Playwright 默认启动 fresh backend/frontend，只有显式设置
`PW_REUSE_EXISTING_SERVER=1` 时才复用本机已有服务。可通过环境变量避开端口冲突：

```bash
BACKEND_PORT=8010 FRONTEND_PORT=8090 npm run test:e2e:smoke
```

启动命令会在后端启动前执行 `APP_ENV=test alembic upgrade head`；
`PW_REUSE_EXISTING_SERVER=0` 可作为显式的 fresh-server 声明：

```bash
BACKEND_PORT=8010 FRONTEND_PORT=8090 PW_REUSE_EXISTING_SERVER=0 npm run test:e2e
```

如果默认端口已有旧服务，先停止旧服务，或像上面一样指定备用端口。
`APP_ENV=test` 只切换应用模式与测试路由，不会自动改写 `DATABASE_URL`。
若本机同时运行开发 worker，应为 Playwright 显式传入独立测试库的
`DATABASE_URL`，避免 worker 抢占 E2E 创建的任务。`scripts/e2e-servers.sh`
也是 E2E 专用入口，会先迁移当前 `DATABASE_URL` 指向的数据库再启动
backend；通用 `backend/scripts/dev_server.py` 不自动迁移。

地图 E2E 包含 200×200 Canvas 性能门禁：固定 Chromium 1280×720 视口，预热 20 帧后采样 100 帧，并将 payload、首绘、平均帧耗时和 p95 写入 Playwright 附件 `map-canvas-performance.json`。门禁仅比较同次运行的视口裁剪与未裁剪基线，退化超过 20% 才失败。

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
├── styles.css              # 完整样式表（浅色主题 + 暗色模式，设计 Token 驱动）
├── state.js                # 全局响应式状态管理
├── stateSlices.js          # 状态副作用、listener 通知、DOM 同步调度 helper
├── api.js                  # API 封装（projects/world/rag/context/writing/imports/tasks）
├── apiContracts.js         # vanilla JS 共享 API 契约注册表（高风险 wrapper 子集）
├── router.js               # Hash 路由系统
├── commands.js             # 命令系统（全中文帮助）
├── app.js                  # 应用主入口（快捷键绑定）
├── shared/                 # 可复用业务组件与工具
│   ├── smartDedup.js       # 智能去重管理器
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
│   │   ├── scenePanel.js
│   │   ├── outlineFloat.js
│   │   ├── focusMode.js
│   │   ├── tools.js
│   │   ├── mobileQuickNote.js
│   │   └── submodules.js   # 子模块工厂
│   ├── worldView.js        # 世界对象 / 关系 / 别名 / 世界书 / 地图子标签
│   ├── mapWorkspaceView.js # 地图一级工作台
│   ├── mapView.js          # 动态地图主视图
│   ├── mapState.js         # 地图前端会话状态
│   ├── mapHexRenderer.js   # 六边形渲染
│   ├── mapEditPanel.js     # 地图编辑面板
│   ├── mapLayerSession.js  # exclusive/floor 当前子层与 isolate 会话投影
│   ├── mapPathRenderer.js  # 连续道路/水系几何、裁剪、命中与 Canvas 绘制
│   ├── mapTimelineProjection.js # Scene 状态/差分归一化与只读 Canvas 覆盖
│   ├── mapTerrainAssets.js # 内置覆盖素材包与样式预设
│   ├── mapTerrainRenderer.js # 程序化 Canvas 覆盖素材渲染
│   ├── mapRouteContext.js  # 地图路由上下文
│   ├── outlineView.js      # 剧情结构
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
- 地图编辑器用 `editorLayer` 区分地点、正式底图、覆盖地形、连续线路、标记和领地；各内容层独立保存草稿及 Undo/Redo，图层树另有独立 draft/history。revision CAS 支持“应用当前图层”“应用图层结构”或原子“保存全部”，409 会刷新基线但保留本地草稿。
- 图层面板使用递归树，展示祖先继承后的有效显隐、锁定、透明度与 zoom；exclusive/floor 当前子层由 route + localStorage 会话投影管理，isolate 不持久化。世界对象通过 map presence 在多张地图和多条线路间选择并双向定位。
- 连续道路/水系由 `mapPathRenderer.js` 负责 RDP 简化、平滑采样、变宽绘制、AABB 裁剪和命中测试；Pointer 手绘、节点拖动、端点吸附与线路草稿由 `mapView` 编排。地图 Canvas 使用单 RAF 和 revision/viewport 缓存。
- Scene 时间轴由 `mapWorkspaceView` 消费 timeline/state-at 只读投影，支持 Scene 游标、前后步进、
  播放节奏、轨道过滤、candidate preview 和空间连续性面板。`mapTimelineProjection.js` 负责
  响应归一化、投影签名和 Canvas 覆盖；事实变化不依赖 `editor_revision` 失效缓存。
- 地点和标记拖动统一使用 Pointer Events，并在拖动期间暂停 Leaflet 平移。归档列表与 active 地图树分离，地图删除入口实际归档整棵子树。
- 覆盖地形使用自然环境、城市交通、奇幻危机三个内置程序化素材包及标准/柔和/高对比预设；未知素材显示中性占位并保留原 asset key，不支持用户上传。
- 所有 UI 文字为中文
- 浅色主题（#F5F5F7）为主，支持暗色模式

## 路由与设置

- 项目回收站支持单个恢复、单个永久删除、批量恢复和批量永久删除；永久删除必须二次确认，批量删除使用后端原子接口，不做部分成功。回收站每页 20 条，桌面端大模态框用双列完整展示当前页，并提供上一页、下一页和总数。
- 一级路由包含 `project`、`writing`、`world`、`map`、`outline`、`rag`、`generate`、`settings`、`project-settings`；Scene 工作台位于 `outline/scenes`，旧 `scene` 路由会自动跳转到该入口。快速切换项目或初始化期间使用浏览器前进/后退时，晚到的项目元数据请求不会继续提交旧路由和页面，也不会覆盖当前工作区。新鲜渲染由路由提交 view 返回的 HTML 后再调用 `onRendered()`；需要访问新 DOM 的事件绑定应放在该生命周期中，keep-alive 恢复仍使用 `onActivate()`，不要用零延时定时器猜测 DOM 提交时机。
- 应用首屏、全局路由切换以及写作、大纲和 Scene 工作台的主加载边界使用共享骨架屏；状态容器保留屏幕阅读器可感知的具体加载文本，视觉占位标记为装饰内容，并遵守 `prefers-reduced-motion`。按钮提交、任务进度和局部数据刷新继续使用各自的明确状态，不用通用骨架替代业务反馈。
- Scene 工作台的“场景（scene）自动提取”和“智能去重”与大纲子标签同行，去重只保留一个入口。每行根据当前最高优先级待办切换主按钮；桌面端额外保留“编辑”，移动端收敛为主按钮与更多菜单。健康标签可点击，跨章建议刷新后从后端恢复。
- 项目级智能去重使用大尺寸双栏裁决工作台：左侧按 group 展示状态，
  右侧展示字段对比、合格主对象、逐成员动作、影响和证据。草稿以
  `projectId + scanTaskId + groupId` 隔离，不提供手填主对象 ID；窄屏时队列移到
  对比区上方。只提交全部成员已明确裁决的组，成功组锁定，失败/过期组
  保留裁决和错误以便重试。旧任务只有 `suggestions` 时仍使用 pair 兼容面板。
- 剧情线、篇章纲、伏笔和揭示加载失败时显示可重试的内联错误，不把失败伪装成空列表；通用 API 409 显示“请求冲突”并继续附带后端领域消息。
- Scene 融合与拆分使用大尺寸字段对比表，完整展示 AI 建议、原 Scene 引用、叙事标签、POV 和章节映射；默认显示全部字段，可只看服务端初始预览中的差异。融合预览属于同步 LLM 请求，使用 90 秒生成窗口，不受普通 API 的 15 秒超时限制。长来源证据按需展开，AI 建议始终可见。叙事标签统一用 `draft` 表示“未标注”，拆分时显式清空的字段会按空值保存。废弃融合来源需要在预览内再次确认；保存请求期间所有融合操作保持锁定，失败后恢复控件并保留当前编辑内容。
- 深度导入和 Scene 自动提取任务以 `taskId + projectId` 持久化；查询与取消都显式携带 `novel_id`。Scene stage 百分比是基于历史实测的耗时估算，Phase 0 只显示准备状态。Scene 工作台轮询只局部更新进度卡，不重绘正在浏览的列表。运行中的进度卡可在二次确认后取消当前任务；瞬时查询失败保留恢复记录，只有明确 404 或用户关闭时清理失败/已取消任务。
- 共享任务卡只在后端 `available_actions` 包含 `retry` 时显示重试；`restart_origin` 与深度导入 `resume/abandon` 继续走各自领域流程。
- 生成中心自定义模板可查看修订历史并把旧版本载入编辑器；载入不写库，仍需用户明确保存。
- 前端依后端契约分页或拦截超限请求：Scene 建议每次最多忽略 100 条，地图分组每次最多处理 100 条，地形修改每次最多 10000 格，单地点每次最多绑定 5000 格；不会通过多请求静默产生部分成功。
- 生成中心与世界书 AI 每次最多附带 20 章正文，长对话只发送最近 40 条消息；当前页面历史不因请求上限被删除。生成中心本地会话按项目最多保存 512 KiB、最多保留 5 个项目快照；容量不足时先省略可重新生成的预览，再只持久化最近 40 条对话，保存失败会保留页面内容与旧快照并显示警告。
- 世界书工作区使用“分类/页面—资料编辑—AI 参考规则”三栏：资料编辑支持稳定 section 排序和页面模板，规则栏只提供受限表单、发布与 dry-run trace。世界书 AI、生成中心和通用 AI 参考弹窗只在作者显式选择已发布 Activation Profile 后发送 profile ID，不默认激活长期规则。
- 写作台自动保存以编辑序号保护请求期间的新输入；版本切换触发局部重绘时不会用旧响应覆盖正文。发布成功提示只在章节状态刷新完成后出现；后台 RAG / 记忆后处理完成只收起进度，不再次重载当前编辑器，且已 dispose 或已被新任务取代的轮询响应不会回写。恢复历史正文时保留选择当时的最新版本快照，发布前若其他会话已更新则提示 409 冲突。“AI 工具”菜单与“专注模式”位于编辑器顶部同一操作行，正文反向提取入口统一显示为“从正文整理 Scene”。
- RAG 索引维护的技术诊断区可按需加载隐私安全的检索追踪摘要，不展示 raw query 或正文。
- 小说检索的智能/字面模式都按章节聚合同章结果：智能模式解释为语义相关性检索，字面模式解释为完全一致文字匹配；结果卡显示该章聚合的相关片段数或出现次数。
- `settings` 是无项目也可访问的全局设置页；`project-settings` 管理当前项目的 LLM 主配置、深度导入参数和作者偏好。主配置中的“默认输出上限”由非深度导入业务调用继承，系统默认 `12000`；深度导入继续显示并使用自己的阶段预算。
- 旧 `llm` 入口会按当前项目状态跳转到 `project-settings` 或 `settings`。
- 旧 `context` hash 不再是一级页面，路由层会重定向到 `generate?tab=task`。

## 内容优先布局

- 写作、Scene、世界书、地图和生成中心采用统一的内容优先分栏；桌面端正文、主列表、编辑区或画布获得约三分之二的可用宽度。
- 辅助栏使用统一的主题化折叠控件，折叠选择按项目和页面保存在当前浏览器会话中；写作专注模式仍优先隐藏两侧栏。
- 中等宽度会重排第三栏，`760px` 及以下改为单栏、抽屉或手风琴；折叠控件完整支持浅色、暗色、键盘焦点和减少动效偏好。
- 任务进度默认显示紧凑摘要、状态和细进度条；失败、恢复或需要用户确认的状态自动展开，用户手动选择在任务重绘时保持。
- 共享业务模态框使用带标题关联的 modal dialog 语义；打开后焦点进入内容或操作区，Tab/Shift+Tab 不离开对话框，Escape 关闭后恢复到原触发控件。连续替换模态内容时仍保留最初触发点；正文中的可编辑控件发生未保存变化时，关闭按钮、取消、遮罩和 Escape 都会先确认是否放弃，成功操作不重复确认。

## 安全与契约

- `index.html` 配置 CSP meta baseline：脚本仅允许本源和 Leaflet CDN，连接仅允许本源及本地开发后端；`style-src` 暂保留 inline style 兼容。
- 封闭测试服的 `APP_ACCESS_TOKEN` 只保存在 `api.js` 当前页面的 module memory，不读写 Web Storage；刷新页面后需要重新输入。普通请求、导入上传和前端错误上报共用该内存令牌，被后端以 401 拒绝后立即清除。
- 动态内容默认使用 `textContent`；必须拼 HTML 时先走 `esc()`。
- 当前已落地 vanilla JS 共享 API 契约校验第一阶段：`apiContracts.js` 注册高风险 wrapper 的 method/path/query/body/timeout，`api.js` 对应 wrapper 消费该 registry，Vitest 覆盖加载顺序与代表 endpoint 映射。
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
- “全选”只作用于当前可见列表或当前分页，不跨分页选择全部筛选结果。
- 世界对象的对象库与待处理对象/别名/关系子标签都在批量工具条提供显式全选；所有筛选区默认折叠，展开状态按项目缓存在浏览器本地，折叠后仍保留当前筛选条件。
- 已采用对象库的多选工具条提供“融合”和“标记为别名”，不再提供“批量标记已检查”或“批量采用”。两种操作都要求选中至少两个同类型对象、明确选择保留对象并二次确认；融合会合并内容和关系，别名化只迁移关系和登记来源名称，来源对象均进入可审计历史态。
- 所有待处理世界对象都可在采用前微调名称、类型和概要；普通 candidate 通过 promote 请求在同一事务中编辑并采用，建议队列对象继续走队列裁决。待处理别名和关系保留各自的“编辑后采用”入口。
- 世界对象的新建、编辑后采用和普通编辑共用项目类型目录：可复用已有自定义类型或创建新类型；对象库筛选同步支持自定义类型。已采用对象改类型会二次确认，后端专属依赖 blocker 在原弹窗内按类别和数量展示并保留输入。
- 待处理对象中，已有明确别名目标的条目按目标对象合并展示；没有明确目标但同类型名称高度相似的条目也会合并展示。该分组只影响当前页界面，不自动合并、采用或写库。
- 删除、忽略、永久删除等危险批量动作必须二次确认；执行后会显示成功/失败数量。
- 普通待处理对象的“合并”是行内主操作，不放在更多菜单里；没有明确目标对象时需要先搜索并选择目标。由建议队列拥有的兼容影子只通过建议采用/忽略，不直接修改影子对象。
- RAG、Context、Generate 等状态/生成页面不强制提供批量操作，只保留清晰的空状态、错误状态和任务进度。
