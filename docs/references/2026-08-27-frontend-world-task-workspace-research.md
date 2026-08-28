# 前端世界资料与作者任务工作区研究

> 状态：产品与工程研究，结论均为待真实使用验证的产品假设，不构成当前稳定接口或 ADR。
>
> 日期：2026-08-27
>
> 事实源：`/Users/tywww/Desktop/项目/ai-writing-assist-worldbook-unification` 的重构后代码与开工时未提交修复。
>
> 关联研究：[世界对象、世界书、统一 Card 与事实权威](world-object-worldbook-unification-research.md)。

> 实施记录（2026-08-28）：Phase A–D 与 Phase E0 工程收口已在同一 worktree 落地；资料库收敛、兼容深链、最小作者任务和写作首页闭环已进入可试用候选。第 12 节仍是待真实作者数据验证的产品假设，不因自动化通过自动成为已验证结论。

## 1. 结论

本轮不再讨论“世界书与世界对象是否统一”，而是承接已经落地的 Phase 1 统一卡片读模型，确定下一步前端收敛方式：

1. “人物与世界”内部只保留三个一级入口：**资料库、关系、需要决定**。
2. 资料库继续消费当前 Page、Draft、CoreEntity 的 tagged Card read model；不建 Card 表，不增加第二套事实源。
3. 目录只做“全部资料、工作稿、按类型/分类”的浅层分组。它是筛选入口，不是文件系统，因此不增加父子页面字段或任意深度文件夹。
4. 资料库只保留卡片/列表两种浏览方式。页面编辑、对象详情、关联图、历史、校验、导入和模板都在当前资料上下文内打开，不与资料库平级。
5. 写作首页在唯一主行动之后增加紧凑的“计划中的任务”摘要；完整任务页使用 `writing?home=1&panel=tasks`，不增加主导航“任务”。
6. 作者任务只有标题、备注、`open/completed/archived`、可选日期和一个可选来源。不要优先级、负责人、依赖、子任务、看板、工时、提醒或重复规则。
7. 作者任务、领域“需要你决定”和后台异步流程是三种不同对象：只有作者任务可勾选完成；待决定必须返回所属领域处理；异步流程只显示进度、失败与恢复。
8. 前端按用户能力渐进拆分，不做一次性目录搬家：先让 `WorldView.vue` 成为子导航和懒加载外壳，再拆资料库、页面编辑、发布/历史和次级工具。
9. 未来作者任务由 `project` 模块拥有，候选表为 `project_author_tasks`；来源只保存封闭的领域类型和对象 ID，不保存 URL、路由字符串或 `owner_id`。

目标用户是 `docs/product/user-personas.md` 的长篇作者画像：需要快速找回设定、恢复工作、清楚知道哪些内容已采用，并避免被内部 ID、任务队列和复杂配置打断。阅读型用户不承担这套作者后台复杂度。

## 2. 研究基线与边界

### 2.1 开工快照

| 项目 | 开工事实 |
|---|---|
| 分支 | `codex/worldbook-world-object-unification` |
| HEAD | `a160ce5b6eacba2dbc5da04b71642fa6b3ba1caf` |
| `origin/main` | `ba6f7bbb1778a988e6c7e05bdf497e5730bdbbe1` |
| 分支关系 | 当前分支领先 `origin/main` 2 个提交 |
| 工作树 | 32 个已跟踪文件有修改，另有 1 个未跟踪测试文件 |
| 已跟踪差异摘要 | 32 files changed, 1368 insertions, 174 deletions |
| 主要并发修复 | World Authority/发布路径、迁移与测试；统一卡片状态文案、完整页面搜索、局部加载失败空态；相应架构与模块文档 |
| 开工门禁 | `make docs-check` 通过：8 个业务模块、99 个 ORM 表、30 个任务处理器、15 个前端路由、25 个 ADR |

因此本文把尚未提交的 `WorldBibleTab.vue`、`worldCards.js` 和世界统一研究修订也视为当前实现事实；不能从主 checkout 或仅从 HEAD 推断能力。这是研究开工时的原始快照；后续实施在该基线上增量进行，没有回退或覆盖快照中的并发修复。

### 2.2 本轮允许与禁止

本节保留研究阶段的允许/禁止边界；在用户后续明确批准实施后，生产代码、API、schema、migration、测试与稳定文档按第 11 节的 Phase A–D 边界增量变更。

明确不做：

- 新建一级任务中心；
- 新建深层 Wiki 文件树或页面父子关系；
- 引入完整项目管理；
- 新建 Card 持久表或新的世界事实源；
- 引入新的前端状态库、设计系统、配色或字体；
- 搬动当前超大文件；
- 修改 `world-model-evolution-research.md` 等探索式研究文档。

## 3. 当前实现证据

### 3.1 当前信息架构

```text
主导航
├── 写作
│   ├── 写作首页（旧 today 路由的 canonical 落点）
│   │   ├── 继续创作：唯一主行动
│   │   ├── 未完成创作：服务器工作稿与建议
│   │   ├── 需要你决定：跨领域只读聚合
│   │   └── 正在进行的整理：本机恢复的后台流程
│   └── 章节写作台
├── 人物与世界
│   ├── 人物与世界：Page / Draft / Entity 统一卡片、页面编辑、关联图与工具
│   ├── 对象库：Entity 的表格/卡片、搜索、筛选和对象编辑
│   ├── 关系
│   ├── 需要决定
│   └── 别名：对象库的兼容子路由
├── 故事结构
├── 地图
└── 查找
```

这个结构已经完成两项关键收敛：主导航没有独立任务入口；旧 `today` 路由会规范化到 `writing?home=1`。但世界模块仍同时暴露“统一卡片总览”和“对象库”，让同一个 Entity 在两个浏览心智中出现。

### 3.2 已实现／仍重复／缺失／应删除

| 判断 | 代码证据 | 当前效果 | 研究定案 |
|---|---|---|---|
| 已实现 | `worldCards.js` 以 `kind=page/entity` 组装 Page、自由 Draft、CoreEntity | 已有统一卡片 read model，没有 Card 表 | 保留为唯一总览来源，不另建模型 |
| 已实现 | 当前未提交修复让 Page 搜索覆盖 `free_text` 与 section 正文；Entity 保留服务端完整搜索结果 | 混合搜索不再只匹配 240 字预览，也不会误删别名命中 | 后续列表视图复用同一查询与结果，不写第二套搜索 |
| 已实现 | 当前未提交修复统一使用作者可读状态，并在 Entity 局部加载失败时保留 Page 卡片与重试 | 不再暴露原始状态；局部失败不伪装成空世界 | 作为资料库错误状态基线 |
| 已实现 | `worldCardFiltersFromQuery()` / `worldCardQuery()` 使用 `q`、`kind`、`type` | 统一卡片筛选可由 URL 恢复 | 扩展而不替换这条 seam |
| 已实现 | `worldIsland.js` 解析 `draft_id`、`page_id`、suggestion/conflict/import/adoption/AI 参数 | 外部入口能定位页面、工作稿和次级工具 | 兼容参数必须继续有效 |
| 已实现 | `useWorldBible.js` 保存项目隔离的活动页、工作稿和 editor baseline，并有路由离开与 `beforeunload` 防丢失 | 编辑态可恢复，未保存离开会确认 | 拆文件时保持同一行为，不把草稿塞入 URL |
| 已实现 | `WorldView.vue` 对重组件使用异步加载，失败可重试一次 | 已有可继续利用的路由外壳 | 最终只保留导航、懒加载和最薄的参数适配 |
| 已实现 | `TodayView.vue` 把“需要你决定”和“正在进行的整理”分开展示 | 系统决策与后台流程没有被误当成清单 | 加作者任务后仍保持三者分栏 |
| 已实现 | `ProjectWorkspaceSummaryResponse` 只返回 continuation、writing、attention，不含 raw task/owner/正文 | 写作首页的项目聚合边界已经成立 | 未来以加性 `author_tasks` 摘要扩展，不另建首页聚合服务 |
| 仍重复 | `WorldBibleTab.vue` 的统一 Entity 卡片点击后跳到 `world/objects`；对象库另有筛选、卡片/表格与详情 | 用户从“总览”离开到“另一个对象库”才能编辑同一资料 | 对象详情并入资料库；旧路由只做兼容入口 |
| 仍重复 | 世界书有 `gallery/filter/editor/graph` 四个平级显示模式，对象库另有 `card/table` | “资料是什么”与“怎样查看/编辑它”混在同一层 | 顶层只留 cards/list；编辑和图是内容上下文 |
| 仍重复 | `aliases` 既是对象附属信息，又是对象库兼容子路由和待决定类别 | 别名同时像资料库、关系工具和审查队列 | 已采用别名进对象详情；候选别名进“需要决定”；批量工具保留次级入口 |
| 缺失 | 当前无作者任务数据表、API、首页摘要或完整页 | 作者无法保存自己想做的轻量待办 | 在后续 Spec 中由 Project 模块补最小模型 |
| 缺失 | 统一卡片没有统一的列表视图与浅层常驻目录 | 大量资料只能在卡片与分类首页之间切换 | 增加同源 list 视图和浅层目录，不加文件树 |
| 缺失 | 打开页面/对象后，筛选和列表返回路径仍跨 `bible`/`objects` | 返回时容易失去“从哪里找到它”的上下文 | URL 保存可分享筛选；会话保存滚动和未提交编辑态 |
| 缺失 | `WorldBibleTab.vue` 1317 行，`useWorldBible.js` 2606 行；Review 与 Entity 操作也各超过 1200 行 | 单文件同时承担浏览、编辑、发布、历史、图、导入、模板、建议、校验等职责 | 按用户能力拆，不按“组件/工具”笼统分层 |
| 应删除 | 可见导航中的独立“对象库”和“别名”一级心智 | 与统一资料库重复 | 只删除可见入口；兼容深链保留并规范化 |
| 应删除 | `gallery/filter/editor/graph` 作为同级模式的选择负担 | 浏览、定位、编辑、分析被当成四种互斥视图 | 只保留 cards/list；其余转为内容内动作或工具 |
| 应删除 | 任何准备再建 Card 表、通用 Wiki tree、任务中心或项目管理属性的方案 | 会产生第二事实源和不必要的后台复杂度 | 不进入后续 Spec；真实验证证明必要时再重开 |

“应删除”指后续实现删除重复的**可见产品结构**，不是本轮删代码，也不是立即破坏兼容路由。

### 3.3 当前测试资产

后续迁移应复用并扩展以下现有测试，不另起一套框架：

- `frontend-console/tests/router.test.js`：旧 Today、世界子路由、query 和浏览器历史。
- `frontend-console/tests/vue/writingIsland.test.js`、`todayIsland.test.js`：写作首页加载、空态、唯一主行动、注意事项与后台流程。
- `frontend-console/tests/vue/world/worldIsland.test.js`：世界 URL 解码、深链和局部加载。
- `frontend-console/tests/vue/world/bible/WorldBibleTab.test.js`、`worldCards.test.js`：统一卡片、搜索、空态、编辑、防丢失、发布、历史和工具。
- `WorldObjectsTab.test.js`、`WorldRelationsTab.test.js`、`WorldAliasesTab.test.js`、`WorldReviewTab.test.js`：迁移前对象、关系、别名与待决定行为。

## 4. 外部产品机制比较

外部参考只用于提取经过验证的交互机制，不复制品牌样式、数据模型或全部功能。资料访问日期均为 2026-08-27。

| 产品与官方资料 | 可借机制 | 本项目采用 | 明确不采用 |
|---|---|---|---|
| [Notion：Views, filters, sorts & groups](https://www.notion.com/help/views-filters-and-sorts) | 同一个数据库可有多种视图；每个视图有自己的筛选、排序与分组；内容可在保留列表上下文的 side peek 打开 | 同一 Card read model 提供 cards/list；桌面编辑保留左侧目录和查询上下文 | 通用数据库搭建器、任意高级筛选树、看板/日历/时间线 |
| [Obsidian Bases：Views](https://obsidian.md/help/bases/views) | 同一 Base 的 table/list/cards 共享文件来源，各视图独立配置筛选与排序 | 视图是资料投影而非新资料；筛选进入 URL，局部偏好沿用现有 session/local preference seam | 公式编辑器、原始属性语法、插件式布局扩展 |
| [Capacities：Collections](https://docs.capacities.io/reference/collections) | Collection 是类型内的浅层、可重叠分组，不是嵌套存储树；规则稳定时应使用查询 | “工作稿/类型/分类”都是查询或现有分类的浅层入口，不产生父子结构 | 任意深度文件夹；为了分类而复制资料 |
| [Craft：Tasks](https://support.craft.do/en/plan-and-do/tasks) | 任务可在文档上下文创建，同时在 Inbox/Today/Upcoming 等集中视图出现；同一任务跨视图同步 | 世界资料、章节和 Scene 就地创建同一作者任务；写作首页汇总，点击返回来源 | 重复规则、提醒、日历、嵌套任务、标签体系、完整 GTD |
| [Notion：My Tasks](https://www.notion.com/en-gb/help/guides/give-your-to-dos-a-home-with-task-databases) | 多来源任务集中到一个简单视图，用户可在汇总处查看与更新 | Project 聚合一个项目内的轻量作者任务；首页只给摘要，完整页仍属于写作首页 | 多数据库配置、团队负责人、跨项目分配、任务数据库模板 |

由这些机制得到的工程推论是：**视图、目录和汇总都应指向同一来源对象**。它们不应各自拥有一份内容或状态。视觉上继续使用仓库现有语义 token、图标、焦点样式和 760/1100px 响应式约定；不引入外部产品的配色、字体或新状态库。

## 5. 目标信息架构

### 5.1 世界工作区

```text
人物与世界
├── 资料库（默认）
│   ├── 全部资料
│   ├── 工作稿
│   └── 按类型/分类
│       ├── 人物
│       ├── 地点
│       ├── 势力
│       └── 其余现有类型与页面分类
│
│   主区：搜索 + 筛选摘要 + 卡片/列表
│   打开资料后：页面编辑或对象详情
│   上下文工具：关联图、历史、校验、导入、模板、建议、冲突
├── 关系
└── 需要决定
    ├── 对象候选
    ├── 别名候选
    └── 关系候选
```

目录不是第三种数据模型：

- “全部资料”读取完整 tagged union；
- “工作稿”是 `kind=page` 且 state 为 working 的投影；
- 类型/分类根据现有 `page_type`、页面分类和 `entity_type` 生成作者可读分组；
- 同一资料可通过搜索和类型入口到达，但只有一个领域对象；
- 层级只有“目录入口 → 资料”，不显示面包屑。两层结构用明确标题和返回按钮更直接；未来真的出现三层以上稳定层级时再评估面包屑。

别名的落点固定为：

- 已采用别名：对象详情中的“别名”区域；
- 待确认别名：`需要决定?kind=aliases`；
- 批量维护：从对象详情或“更多工具”打开的次级工作台；
- `world/aliases`：兼容入口，不再出现在主子导航。

### 5.2 作者任务

写作首页的优先级不变：继续创作仍是唯一主行动。“计划中的任务”是下一层摘要，最多显示三项今天或逾期的 open 任务，以及“查看全部”入口。没有任务时只显示轻量创建入口，不用大面积空态抢占首页。

完整页固定四个视图：

| 视图 | 规则 |
|---|---|
| 今天 | `open` 且日期不晚于当前本地日期；逾期以文字加状态标识，不只靠颜色 |
| 收件箱 | `open` 且无日期 |
| 之后 | `open` 且日期晚于当前本地日期 |
| 已完成 | `completed`；可重开，按最近完成时间排序 |

`archived` 不在四个日常视图中出现，只能从次级“已归档”入口恢复或永久保留在服务端历史。后续 Spec 若没有真实恢复需求，可先只提供“归档并从列表隐藏”，不增加第五个主视图。

任务字段保持最小：

```text
标题（必填）
备注（可选）
状态：open | completed | archived
日期（可选，calendar date，不含时刻）
来源（可选，且最多一个）
```

任务可以从以下上下文创建：世界资料页、世界对象、写作章节、Outline Scene。上下文创建时预填来源与建议标题，作者仍需确认保存。任务在集中页和来源处是同一记录，任一处完成都会同步。

### 5.3 三种“要处理的事”必须分离

| 类型 | 谁创建 | 用户动作 | 能否勾选完成 | 生命周期与展示 |
|---|---|---|---|---|
| 计划中的任务 | 作者主动创建 | 完成、重开、归档、返回来源 | 是 | Project 持久化；写作首页摘要与任务完整页 |
| 需要你决定 | 领域规则、冲突或候选产生 | 进入 World/Writing/Outline 做接受、拒绝或修正 | 否 | 由所属领域拥有；首页只读聚合，不复制决策状态 |
| 正在进行的整理 | 确定性工作流提交 | 查看进度、重试、恢复、隐藏失败提示 | 否 | `infrastructure/tasks` 负责传输和恢复；不能写入作者任务表 |

界面文案和控件也要区分：作者任务使用 checkbox 与“完成”；待决定使用“查看/去处理”；后台流程使用 progress 与“查看/重试”。三个区域不能共用同一个计数徽标或批量完成动作。

## 6. 桌面与 390px 线框

线框表达信息层级和交互位置，不规定新视觉语言。

### 6.1 世界资料库：桌面

```text
┌──────────────────────────────────────────────────────────────────────┐
│ 人物与世界      [资料库] [关系] [需要决定 3]       [新建资料] [更多] │
├──────────────────┬───────────────────────────────────────────────────┤
│ 资料目录          │ 搜索资料……             [筛选] [卡片 | 列表]       │
│                  │ 当前：全部资料 · 27                               │
│ ● 全部资料  27    ├───────────────────────────────────────────────────┤
│   工作稿     4    │ [人物] 林秋  已采用      [地点] 沉钟港  工作稿     │
│                  │ 摘要……                  摘要……                    │
│ 类型与分类        │                                                   │
│   人物       8    │ [制度] 港口轮班          [势力] 守灯会             │
│   地点       6    │ 摘要……                  摘要……                    │
│   势力       4    │                                                   │
│   其他       9    │ 局部加载失败时：保留已加载资料 + 原位重试          │
└──────────────────┴───────────────────────────────────────────────────┘
```

打开资料时仍是两栏，左侧目录不消失；右侧从列表切换成内容。返回列表恢复 URL 筛选、滚动位置和当前目录。页面编辑的历史/校验/关联图进入右侧内容区的次级抽屉或折叠面板，不恢复当前桌面三栏常驻 inspector。

```text
┌──────────────────┬───────────────────────────────────────────────────┐
│ 资料目录          │ ← 返回“地点”    沉钟港 · 工作稿          [保存]    │
│ ● 地点       6    │ 标题、正文、结构化分区                           │
│                  │                                                   │
│ 当前筛选：雾港    │ [关联] [历史] [校验] [更多工具]                   │
│ 卡片视图          │ 次级工具按需在内容内展开，不常驻第三栏            │
└──────────────────┴───────────────────────────────────────────────────┘
```

### 6.2 世界资料库：390px

```text
┌──────────────────────────────┐
│ 人物与世界              [更多]│
│ [资料库] [关系] [决定 3]      │
├──────────────────────────────┤
│ [全部资料 27 ▾]               │
│ [搜索资料…………………] [筛选]    │
│ [卡片 | 列表]                 │
│                              │
│ ┌ 地点 · 工作稿 ───────────┐ │
│ │ 沉钟港                    │ │
│ │ 摘要……                   │ │
│ └──────────────────────────┘ │
│ ┌ 人物 · 已采用 ───────────┐ │
│ │ 林秋                      │ │
│ └──────────────────────────┘ │
└──────────────────────────────┘
```

点击卡片后单栏逐层进入：

```text
┌──────────────────────────────┐
│ ← 返回“地点”          [保存] │
│ 沉钟港 · 工作稿               │
├──────────────────────────────┤
│ 标题                         │
│ 正文                         │
│ 分区                         │
│                              │
│ [关联] [历史] [校验] [更多]   │
└──────────────────────────────┘
```

390px 下不常驻目录栏、不嵌套横向滚动，也不依赖 hover。目录选择器、筛选按钮、返回和保存至少 44px 高；打开筛选或更多工具时支持 Escape、外部点击关闭和焦点回到触发按钮。未保存离开继续使用现有确认门禁。

### 6.3 写作首页与任务页

```text
写作首页（桌面与移动均保持同一优先级）
┌────────────────────────────────────────────────────────────┐
│ 继续创作：第 12 章                              [继续写作] │  主行动
├────────────────────────────────────────────────────────────┤
│ 计划中的任务  今天 2 · 收件箱 1    [＋添加] [查看全部]     │
│ □ 核对沉钟港轮班制度          来源：沉钟港                 │
│ □ 补第 12 章结尾              来源：第 12 章              │
├────────────────────────────────────────────────────────────┤
│ 未完成创作 / 需要你决定 / 正在进行的整理                   │  系统状态
└────────────────────────────────────────────────────────────┘

writing?home=1&panel=tasks&scope=today
┌────────────────────────────────────────────────────────────┐
│ ← 写作首页     计划中的任务                     [＋添加任务]│
│ [今天 2] [收件箱 1] [之后 4] [已完成]                       │
├────────────────────────────────────────────────────────────┤
│ □ 核对沉钟港轮班制度      今天       沉钟港 →              │
│ □ 补第 12 章结尾          逾期       第 12 章 →            │
└────────────────────────────────────────────────────────────┘
```

390px 任务页只把四个视图做成可换行的分段选择或下拉，不做横向滚动标签。任务行的 checkbox、标题和来源跳转分别可聚焦；点击来源不切换任务完成状态。

## 7. 路由与状态定案

### 7.1 目标 URL 状态

可分享、可恢复的浏览状态进入 URL；未保存内容、滚动位置、打开的临时菜单和表单草稿继续使用现有项目隔离 session。

| 区域 | 目标 query | 说明 |
|---|---|---|
| 资料库筛选 | `q`、`kind=all/page/entity`、`type`、`state` | 扩展当前 `q/kind/type`；非法值回默认，不暴露 `custom` 内部兼容项 |
| 资料库视图 | `layout=cards/list` | 避免与旧对象库的 `view=card/table` 混淆；缺省为 cards |
| 资料定位 | `page_id`、`draft_id`、`entity_id` | 一次只接受当前上下文适用的定位；来源必须属于当前项目 |
| 次级工具 | 延续当前 `open`、suggestion/conflict/import/adoption/AI 参数 | 不把工具升级成子路由；关闭工具时保留资料筛选和定位 |
| 作者任务 | `home=1&panel=tasks&scope=today/inbox/later/completed` | `panel=tasks` 是写作首页内完整页；非法 scope 回 today |

列表返回所需的滚动位置不写入 URL；以 `{project_id, route_signature}` 为 key 保存到会话。编辑 payload 和 unsaved baseline 继续由当前 World/Writing session 管理，项目切换时必须清理，不能跨 `novel_id` 恢复。

### 7.2 旧深链落点

所有现有世界深链先保留解析，再规范化到目标界面。迁移期间可继续渲染旧组件，但对用户可见的当前位置与返回路径必须符合下表。

| 旧深链 | 目标落点 | 参数迁移与兼容要求 |
|---|---|---|
| `world/bible` | `world/bible` 资料库默认页 | 保留 `q/kind/type` 及全部 `page_id`、`draft_id`、suggestion/conflict/import/adoption/AI 参数 |
| `world/objects` | 资料库的 Entity 投影 | `q → q`、`entity_type → type`、`display_state → state`、`view=card/table → layout=cards/list`；`entity_id` 直接打开对象详情；source/workflow/review 等高级筛选收进“更多筛选”但继续解析 |
| `world/aliases` | 资料库对象别名次级工具；候选则进“需要决定” | 保留 `q`；有对象定位时打开对象详情别名区，无定位时打开批量别名工具；不能自动把待确认别名标为任务 |
| `world/relations` | 关系 | 保留 `q`、`group_id` 等现有定位和返回参数 |
| `world/review` | 需要决定 | 保留 `kind=objects/aliases/relations`、item/group/source 定位和 `return_*` 参数 |

现有 `world/review-objects`、`world/review-aliases`、`world/review-relations` 也继续由 router 规范化为 `world/review?kind=...`，其余 query 原样保留。完成兼容迁移前必须保留 router characterization tests，不能仅因新导航不再生成旧 URL 就删除旧解析。

作者任务来源跳转由 `source_kind + source_id` 在当前客户端映射到稳定路由：

| 来源类型 | 目标路由 |
|---|---|
| `world_page` | `world/bible?page_id=...` |
| `world_entity` | 目标为 `world/bible?kind=entity&entity_id=...`；兼容期可内部落到 `world/objects?entity_id=...` |
| `writing_chapter` | `writing?chapter_index=...` |
| `outline_scene` | `outline/scenes?scene_id=...` |

数据库不保存这些路由字符串，所以未来路由重构只改一处来源映射。

## 8. 渐进式目标源码树

### 8.1 写作首页与任务

```text
frontend-console/vue/views/
├── today/
│   └── TodayView.vue                 # 最终只做旧入口兼容，不拥有新业务逻辑
└── writing/
    ├── WritingView.vue
    ├── home/
    │   ├── WritingHomeView.vue       # 继续创作、三类摘要的页面组合
    │   ├── AuthorTasksView.vue       # 今天/收件箱/之后/已完成
    │   ├── AuthorTaskForm.vue        # 新建/编辑最小字段
    │   ├── authorTaskSource.js       # 封闭来源到稳定路由的映射
    │   └── useAuthorTasks.js         # 加载、创建、完成、重开、归档
    └── ...现有章节写作台文件
```

`todayIsland.js` 的聚合加载逻辑在迁移完成后并入 `writing/home/`，旧 `today` 入口只调用同一 loader。不要同时维护 `TodayView` 和 `WritingHomeView` 两套首页。

### 8.2 世界工作区

```text
frontend-console/vue/views/world/
├── WorldView.vue                     # 只负责资料库/关系/需要决定导航与懒加载
├── library/
│   ├── WorldLibraryView.vue          # 目录、查询、cards/list 与内容打开状态
│   ├── WorldLibraryDirectory.vue     # 浅层分组
│   ├── WorldLibraryCards.vue         # 复用 tagged Card read model
│   ├── WorldLibraryList.vue          # 同一 read model 的紧凑视图
│   └── worldCards.js                 # 当前纯组装/查询函数迁入，保持无持久化
├── pages/
│   ├── WorldPageEditor.vue           # 页面与工作稿编辑
│   ├── WorldPagePublish.vue          # Preview/Admit、冲突与不确定响应恢复
│   ├── WorldPageHistory.vue          # 历史与恢复
│   └── useWorldPageEditor.js         # 编辑 baseline、保存、防丢失
├── entities/
│   ├── WorldEntityDetail.vue         # 对象详情、图片、已采用别名
│   └── worldEntityOps.js             # 当前对象操作按实际职责继续拆分
├── relations/
│   └── WorldRelationsView.vue
├── review/
│   ├── WorldReviewView.vue
│   └── useWorldReview.js
└── shared/                            # 仅至少两个上述能力真实复用时进入
```

这不是要求一次性创建所有文件。最小迁移顺序是先抽纯展示，再把已有 composable 按职责移动。单一功能的 helper 留在所属目录；只有被至少两个功能实际调用，且删除测试证明不是 pass-through seam，才进入 `shared`。

`WorldBibleTab.vue` / `useWorldBible.js` 的拆分边界固定为：

1. 资料库浏览：统一 Card、目录、搜索、筛选和 cards/list；
2. 页面编辑：active Page/Draft、表单、保存、防丢失；
3. 发布与历史：Preview/Admit、冲突、响应恢复、版本浏览与恢复；
4. 次级工具：图、校验、导入、模板、建议；各自按需加载，不进入页面编辑 composable。

不按“utils”“managers”“components”做无语义搬家，也不把 `WorldView.vue` 变成新的巨型状态容器。

## 9. 未来作者任务接口候选

本节只是后续实施 Spec 的输入；当前 API、schema、wire 和数据库均未改变。

### 9.1 所有权与数据表

作者任务属于项目级个人工作组织，不属于某个内容领域，也不是后台任务。因此由 `project` 模块拥有最小表 `project_author_tasks`，避免再建业务模块，也避免与 `backend/infrastructure/tasks` 混淆。

候选字段：

| 字段 | 约束 |
|---|---|
| `id` | UUID 主键 |
| `novel_id` | 非空，级联到当前 Project；所有查询和更新必须过滤 |
| `title` | 非空、trim 后有内容；长度上限在 Spec 固定 |
| `note` | 可空纯文本；长度上限在 Spec 固定 |
| `status` | 封闭 `open/completed/archived` |
| `due_date` | 可空 SQL `DATE`，不保存时间和时区 |
| `source_kind` | 可空封闭 `world_page/world_entity/writing_chapter/outline_scene` |
| `source_id` | 与 `source_kind` 同时为空或同时非空；创建/更换来源时经领域 facade 验证属于同项目 |
| `created_at/updated_at/completed_at` | 内部审计和稳定排序；不是额外用户字段 |

跨领域多态来源不伪造数据库外键。删除或归档来源后，任务继续存在并显示“来源已失效”；用户仍可完成、重开、归档或清除来源。服务端永远不根据调用方提供的 URL 跳转。

### 9.2 候选 API

```text
GET   /api/projects/{project_id}/author-tasks
POST  /api/projects/{project_id}/author-tasks
PATCH /api/projects/{project_id}/author-tasks/{task_id}
```

- GET 以后续 Spec 固定的 `status/date/cursor/limit` 查询支持四个视图；不为了 UI 分组增加四条 endpoint。
- POST 只接受标题、备注、日期和可选封闭来源；初始状态固定为 `open`。
- PATCH 允许编辑字段、完成、重开、归档和清除失效来源；不提供硬删除。
- path 中的 `project_id` 是唯一项目输入；请求体不接受 `novel_id` 或 `owner_id`。
- API 先验证当前 account principal 对活跃 author Project 的 owner 门禁，再按 `novel_id` 读写任务。
- 来源验证只经 World/Writing/Story 的稳定 facade 或 DI port，不导入对方 model/repository/service。

`ProjectWorkspaceSummaryResponse` 候选加性字段：

```text
author_tasks:
  today_count
  inbox_count
  later_count
  preview          # 最多 3 个 today/overdue open task，只含作者可读字段和封闭来源
```

首页摘要不返回 archived、任意路由、内部 worker task、owner 或来源正文。严格响应快照、OpenAPI contract tests、`todayIsland`/writing loader 和空态必须随加性字段同步。

### 9.3 API/schema 风险

| 风险 | 后续实施要求 |
|---|---|
| `novel_id` / owner 泄漏 | 所有 list/create/patch 同时经过当前 principal owner 门禁与 `novel_id` 条件；跨项目 task/source 统一 404 |
| 与 async task 混淆 | Python 类、API path 固定使用 `AuthorTask` / `author-tasks`，用户界面使用“计划中的任务”；不得复用 worker Task ORM |
| 多态来源失效 | create/replace 时实时验证；read 时由 facade 解析可用性；失效不级联删除任务，也不泄漏别的项目标题 |
| 加性 summary 破坏严格客户端 | 默认工厂提供空摘要；同步 schema/OpenAPI/前端缓存和快照测试；旧客户端可忽略字段 |
| 日期边界 | 存 `DATE`；四个视图按作者本地 calendar date 分组。分页和服务端过滤协议在 Spec 中固定，不偷加时区/提醒系统 |
| 状态竞态 | PATCH 使用当前版本或 `updated_at` 条件，重复 complete/reopen 定义幂等；晚到响应不能覆盖新状态 |
| 内容过载 | title/note 长度受 Pydantic 与数据库共同限制；摘要不返回长 note |
| 未来范围膨胀 | 负责人、优先级、标签、依赖、重复、通知、附件、跨项目任务必须重新做删除测试和产品验证 |

新增表和 wire 前必须另建实施 Spec，同步 ORM、migration、Pydantic、API、Project README、数据库设计、前端文档与测试。只有所有权或生命周期扩展成新的长期架构决策时才需要 ADR；不能用研究文档代替契约。

## 10. 关键行为验收矩阵

| 场景 | 目标行为 | 最小验证 |
|---|---|---|
| 空世界 | 资料库说明还没有资料，提供“新建人物或设定”“新建资料页”两个明确起点；不显示空目录噪声 | Vue component test + 390px 视觉检查 |
| 混合卡片搜索 | Page 匹配标题、全文和 section；Entity 使用服务端搜索结果，别名命中不被前端摘要二次过滤 | `worldCards.test.js` + `worldIsland.test.js` |
| 局部加载失败 | Page 成功、Entity 失败时保留 Page；失败区域有原因与重试，不出现“还没有资料”假空态 | 组件测试 + 键盘重试 |
| 编辑后返回 | 从某目录/搜索打开资料，保存或无修改返回后恢复 query、layout、目录和滚动 | router + session test |
| 未保存离开 | 切资料、切入口、浏览器后退、刷新/关闭均有现有防丢失门禁；取消后焦点回编辑区 | guard test + browser E2E |
| 发布冲突 | 明确展示 baseline/冲突与恢复动作；未 Admit 不显示成功；不确定响应先查询 receipt/历史再决定重试 | World Bible publish component/API test |
| 创建任务 | 来源处点击“添加到计划中的任务”，来源预填；标题必填，日期/备注可空；无日期进入收件箱 | Project API + Vue form test |
| 完成任务 | 勾选只影响作者任务；从今天消失并出现在已完成；晚到响应不覆盖随后重开 | API concurrency/idempotency + component test |
| 重开/归档 | 已完成可重开到按日期计算的视图；归档从四个主视图隐藏，不硬删除 | API + component test |
| 来源失效 | 保留任务与原作者文字，显示“来源已失效”；跳转禁用并提供清除来源，不泄漏 404 目标信息 | 跨项目/删除来源 tests |
| 三类事项并存 | 同页分别显示“计划中的任务”“需要你决定”“正在进行的整理”；只有第一类有 checkbox | Today component + accessibility test |
| 键盘 | Tab 顺序与视觉顺序一致；按钮有可见焦点；route change 聚焦主标题；菜单可 Escape；来源跳转不依赖 hover | keyboard E2E / axe 或现有可访问性检查 |
| 390px | 资料浏览和编辑单栏逐层进入，无横向滚动；任务四视图不溢出；主要触控目标至少 44px | 390px browser screenshot + 操作回归 |
| 深链 | `world/bible`、`objects`、`aliases`、`relations`、`review` 及其 query 均落到表 7.2 的目标 | router parameterized tests |

此外要保留正常的 loading、retry、保存反馈、空态和延迟响应代次保护。卡片/列表切换、任务完成和状态徽标不能只靠颜色传义；动态计数用完整语境播报，不能建立多个竞争的 live region。

## 11. 分阶段迁移顺序

### Phase A：行为固化，不改接口

1. 给五类旧世界深链、返回筛选、滚动恢复和 390px 行为补 characterization tests。
2. 记录查找资料的基线耗时与当前入口误用，不先以代码结构替代产品证据。
3. 固定“作者任务/待决定/后台流程”术语，避免实现期间再次合并心智。

### Phase B：世界可见结构收敛

1. 将可见子导航改为资料库、关系、需要决定；`objects/aliases` 保留兼容解析。
2. 让 Entity 详情从统一资料库原位打开，卡片/列表共享 `worldCards.js`。
3. 加浅层目录和 `layout/state` URL 状态；旧对象查询映射到新 query。
4. 将 graph/filter/editor 从平级显示模式降为资料上下文；桌面保留两栏，390px 单栏进入。

这一阶段优先复用现有 API、router、bridge、worldSession 和组件。若只靠组合当前读模型即可完成，不新增后端接口。

### Phase C：按能力拆前端文件

1. 先抽 WorldLibrary cards/list 与纯 query 逻辑；
2. 再抽 Page editor baseline/save/leave guard；
3. 再抽 Publish/History；
4. 最后把 Import/Templates/Graph/Validation 做按需加载；
5. 每步迁移一组测试并删除原路径代码，避免长期双实现。

### Phase D：作者任务最小闭环

1. 接受独立实施 Spec；新增 `project_author_tasks`、Project API 与 isolation tests。
2. 先交付 `writing?home=1&panel=tasks` 的四视图与新建/完成/重开/归档。
3. 再给 Writing Home 添加最多三项摘要。
4. 最后在 World Page/Entity、Chapter、Scene 增加上下文创建与来源跳转。

先做集中页再做四处入口，可避免来源映射尚未稳定时同时维护五个创建表单。

### Phase E：验证后清理

根据真实指标决定是否移除旧可见组件和兼容实现。旧深链解析只有在路由遥测、文档索引与迁移策略均证明可安全退场时才考虑删除；在此之前只隐藏重复入口。

Phase E0 只做工程收口：资料返回位置按项目+查询保留，Page/Draft/Entity 使用稳定深链且普通入口不继承旧平级模式偏好，原对象库图片/批量/回滚/人物认知从次级工具继续可达；作者任务用项目共享锁、必填版本条件、本地日期分组和显式 409 重试收口。没有添加遥测，也没有删除兼容路由；真实作者试用仍是 Phase E 删除决策的前置。

### Phase E1：试用硬化与受控试用准备

Phase E1 不改 API/schema/wire，只修复受控试用会直接遇到的恢复摩擦：作者任务 409
后保留全部输入，绕过旧 GET 缓存重读最新 `updated_at`，并只在作者再次保存时重试；
来源入口显示实际绑定对象的明确名称；世界工作稿改名不冒充另一个正式页来源。世界书关联资产打开 Entity 时保留原筛选/布局和精确
`entity_id`，进入详情时滚动归零；390px 下对象返回、别名折叠、任务行和来源跳转保持至少 44px。

自动化验收使用合成数据覆盖桌面与 390px、双标签冲突、来源失效、Entity 局部 500
与原位重试、未保存离开、精确返回，并构造 100 个 Entity 和 50 个 Page，确认默认
50 条窗口外的对象仍可经现有服务端搜索找到。这些只是工程验收，不是真实作者证据。

受控试用仍需由 3–5 名长篇作者分别使用隔离的本地数据库和自己的长篇项目完成核心旅程。
人工只记录耗时、步骤、成功/失败和问题等级，不导出正文、标题、ID 或录屏。候选通过标准是：首次无帮助
核心旅程完成率至少 80%，有效来源返回 100%，创建任务最多只需确认标题并保存，零草稿/筛选/滚动静默
丢失，且至少 80% 参与者能区分“计划中的任务、需要决定、后台整理”。7 天后只追记任务页再次使用、创建/
完成、归档和来源返回情况。完成真实试用前，本分支只能标记为“可试用候选”；之后也只能记录为
“有限受控试用证据”，不得宣称广泛产品验证。

2026-08-28 已完成一名内部测试者的桌面与 390px smoke，并补验未保存离开选择“取消”后输入仍保留。
本轮覆盖资料搜索/详情/返回、任务创建/完成/重开/来源返回、双标签 409 与窄屏任务视图；根据观察修复
Entity 深链继承旧滚动而看不到返回入口，以及工作稿改名与正式页来源名称混用。当前测试条件只支持
内部验证，因此状态记为“单人内部 smoke 通过”，不冒充 3–5 名作者受控试用或 7 天重复使用证据。

## 12. 产品假设与验证指标

本文没有真实作者行为数据，以下全部是产品假设：

- 同源资料库会缩短“知道资料存在但找不到”的时间；
- 浅层目录比深层树更适合会跨多种分类的小说对象；
- 在来源处创建、在首页集中查看，会提高任务的重复使用率；
- 把三类事项分栏，会减少把系统候选或后台流程误当成个人待办的情况；
- 两栏桌面与 390px 单栏逐层进入会降低编辑时的导航丢失。

后续试用至少记录：

| 指标 | 建议定义 |
|---|---|
| 查找资料耗时 | 从进入“人物与世界”到打开目标资料的 p50/p90；区分搜索、目录和来源深链 |
| 创建任务步骤 | 从来源点击到保存成功的操作数与耗时；单一来源正常流目标不超过标题确认 + 保存 |
| 重复使用率 | 首次创建任务后的 7 天内，再次打开任务页或创建/完成任务的作者占比 |
| 完成率 | 创建后 7/30 天内进入 completed 的比例；归档单独统计，不算完成 |
| 来源返回成功率 | 点击任务来源后成功打开同项目对象的比例；失效来源单独统计 |
| 入口误用 | 打开“需要决定”后立即返回任务页、尝试勾选后台流程、在对象库/资料库反复切换的比例 |
| 390px 摩擦 | 横向溢出、误触、取消离开和筛选丢失的 session 观察与问题数 |

这些指标用于判断是否继续增加能力，不用于证明需要负责人、看板、提醒或深层目录。

## 13. 文档与工程影响

- 当前实现影响：Phase A–D、E0 与 E1 工程硬化已落地，包括世界资料库可见结构、位置恢复、旧深链/对象工具兼容、轻量作者任务、写作首页摘要、四类来源入口与受控试用自动化。真实作者试用尚未执行。
- 稳定接口/API/schema/wire：Project 加性提供 author-task GET/POST/PATCH 与 workspace summary `author_tasks`；summary 接受可选本地 `on_date`，PATCH 的真实变更需 `expected_updated_at`；请求不接受 owner/novel ID，旧世界深链仍兼容。
- 跨模块边界：来源验证只经 world/writing/story 稳定 facade，每次读写均显式使用同一 `novel_id`；作者任务不复用 `infrastructure/tasks`。
- 当前事实文档：已同步 Project/World/Frontend README、数据库与模块文档；研究结论仍以第 12 节指标验证。
- 探索式研究：未修改 `world-model-evolution-research.md` 或其他 MCEW/RBOS 文档。
- 收尾门禁：`make docs-check BASE_REF=origin/main`、`git diff --check`、本文本地链接检查，以及工作树差异复核。
