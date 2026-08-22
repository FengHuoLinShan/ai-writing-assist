# 人物与世界 UI/UX 执行规范

> 上级标准：`docs/frontend/uiux/design-standard.md`（唯一权威，下称「主规范 §N」）。
> 适用范围：`frontend-console/vue/views/world/`（WorldView + 统一待决定工作台 + 资产子视图组件 + logic）、
> `frontend-console/vue/worldIsland.js`、world 相关样式与 e2e。
> 事实来源：`frontend-console/vue/views/world/` 源码逐文件调研（2026-08），行号以当时源码为准；
> 执行前对引用行号做一次复核。
> 本模块是全产品「AI 产出 → 待处理 → 人工采纳」核心循环的最大实例（3 个审核队列），
> 也是 outline / scene / map 同类「待处理」模式的视觉基准（见 §4.3 的复用声明）。

## 1. 页面定位与目标画像

- **目标画像**：画像 A（长期创作的专业/业余作家，`docs/product/user-personas.md` §1）。
  本页是作者工作台内复杂度最高的页面，不服务画像 B；RP 路径不得反向复用本页心智。
- **页面任务**（对应画像 A 核心任务与共同承诺「AI 不越权」）：
  1. 维护已采纳的世界资产（人物/地点/物品/事件/关系/别名/世界书）——「记得住、找得到」；
  2. 处理 AI 与导入产生的待审核建议，逐条或批量采纳/拒绝——「改得安心、AI 不越权」；
  3. 通过筛选、热点排序、地图跳转回到任意设定——「找得到」。
- **核心循环定位**：审核队列是本页的**第一优先级区域**。AI 只产出建议，作者决定正史；
  「需要处理」计数是全产品统一的待处理信号，视觉必须常显、可读、可一键进入。
- **用户会喜欢的理由**（产品假设，待真实数据验证）：导入正文后自动整理出世界骨架，
  作者在一个页面内完成「看建议 → 采纳/拒绝 → 成为正式资产」的闭环，无需理解
  数据库、枚举或工作流概念。
- **主要摩擦**：队列动辄数百条时的加载与定位成本、筛选复杂度、内部枚举暴露（见 §2）。

## 2. 现状问题清单（按严重度排序，每条带 文件:行号 证据）

路径省略公共前缀 `frontend-console/`；`world/` = `vue/views/world/`。

### P0 — 阻断核心循环的反馈缺失

1. **页面级加载态完全缺失**：world 全部子视图无 loading/skeleton/aria-busy
   （`vue/views/world/` 全目录 grep 零命中；worldIsland.js 只在 catch 分支写 `*LoadError`）。
   加载期间直接渲染空态，首进审核队列会先闪「没有待处理对象」假空态
   （`world/components/WorldReviewTab.vue:63-69`）。
2. **review-aliases / review-relations 错误态无 `role="alert"`、无重试按钮**
   （`WorldReviewTab.vue:194-197, 295-298`），与 review-objects 的完整错误态
   （`:56-62`，含 `role="alert"` + 重试）不一致；relations/aliases 正式列表错误态
   同样只有一行裸文案（`world/components/WorldRelationsTab.vue:11-13`、
   `world/components/WorldAliasesTab.vue:12-14`）。用户无法区分「真的没有」与「没加载出来」。

### P1 — 核心循环体验断裂

3. **「需要处理」角标为 0 时仍显示「0」**（`world/WorldView.vue:15`，`<span class="badge">`
   无 v-if）；badge 无 99+ 上限，三位数会撑破 subnav 项高度；下拉面板内三项用裸
   `<strong>` 计数（`:17-19`），与 summary 的 badge 视觉不一致。
4. **审核入口 `<details>` 下拉无 ESC 关闭、无点击外部关闭的显式处理**
   （`WorldView.vue:14-21`，仅 `navigateSub` 里手动 `open=false`，`:145`）；
   `aria-expanded` 未绑定，展开态对辅助技术不可见。
5. **三队列批量操作条位置不统一**：review-objects 的批量条在最顶、筛选面板之上，
   且 `v-if="localCandidates.length"` 仅非空渲染（`WorldReviewTab.vue:19-31`）；
   review-aliases / review-relations 的批量条在筛选之后、列表之前（`:203, 304`）。
   三个同构队列肌肉记忆断裂。
6. **审核筛选三层堆叠、语义重叠**：搜索条 + `.review-quick-filters` 快捷按钮 +
   已激活筛选 chips + 折叠筛选面板同时存在（`WorldReviewTab.vue:163-192, 267-293`）；
   「按场景筛选」自由输入嵌在快捷筛选按钮行内（`:272`），交互模型混杂。
   review-objects 筛选面板 8 个控件一字排开，无分组、无可见 label（全靠 placeholder，
   `:33-53`），数字输入与文本输入无法区分。
7. **objects 头部操作密度过高、层级混乱**：新建、AI 资料整理开关、卡片/表格切换、
   最近相关/全部切换四种不同权重的功能挤在一个「视图与整理」details 里
   （`WorldView.vue:30-43`）；选中态用 `btn-primary` 表达（`:35-41`）而非
   `aria-pressed`，与 bible 模式切换（`WorldBibleTab.vue:15` 用 `aria-pressed`）模块内不一致。
8. **卡片/表格默认视图三处来源漂移**：WorldView prop 默认 `"table"`
   （`WorldView.vue:77`）；worldIsland URL 解码缺省 fallback 为 `"card"`
   （`vue/worldIsland.js:107`）；discoveryMode 另有 localStorage 偏好。
   同一偏好三套默认值，必然漂移。

### P2 — 一致性与可读性

9. **空态/错误图标不一致**：objects 空态 🌎 emoji、错误 ⚠ emoji 且带硬编码
   `style="color:var(--warning);"`（`world/components/WorldObjectsTab.vue:131,136`）；
   review-objects 错误用裸字符「!」（`WorldReviewTab.vue:58`）、空态 🔍（`:65`）；
   review-aliases/relations 与 bible 空态完全无图标（`:198, 299`、
   `world/bible/WorldBibleTab.vue:40`）。editorial 主题只对 `.empty-icon` 统一处理
   （`editorial-theme.css:995-998`），emoji 与纸面质感冲突。
10. **行内硬编码 style 散落**：`style="margin-bottom:12px;"`（`WorldReviewTab.vue:10,33,171,276`）、
    `style="max-width:220px;color:var(--text-dim);font-size:12px;"`（`:139`、
    `WorldAliasesTab.vue:67`）等——主题覆层无法接管，是 editorial 适配盲区，
    亦违反主规范 §1.4「组件样式只允许引用 token」。
11. **对象表格 9 列密度过高**，「注意」列为原因枚举拼接
    （`world/components/WorldEntityCollection.vue:37`），摘要列 ellipsis 与证据列
    220px max-width 并存，列宽策略不统一。
12. **relations / aliases 正式列表无任何筛选与搜索**（`WorldRelationsTab.vue` 全文无
    filter 控件；分页 state 存 session 而非 URL，`:138-145`），大项目只能靠分页翻找；
    与审核队列 8 控件筛选相比能力倒挂。
13. **bible editor 暴露内部枚举与工程概念**：分区类型/敏感度/投影策略下拉直接展示
    `markdown` / `author_safe` / `eligible` 等英文枚举（`WorldBibleTab.vue:325-337`）；
    右栏直接暴露 Activation Profile、试运行、token 容量（`:411-433`）。
    违反 AGENTS.md 与主规范 §0「不暴露内部枚举」。
14. **bible 页内双 header**：view-header（含 subnav）之下再渲染一层
    `.world-bible-toolbar`（`WorldBibleTab.vue:9-33`），三模式 + 5 个平级按钮无主次，
    首屏视觉焦点分散。
15. **`.world-review-touch-target` 只有 media query 内的样式、无基样式定义**
    （`styles.css` 的 `.world-*` 唯一定义点），命名即补丁。
16. **诊断信息折叠 `<details>` 三处重复、无统一组件**（`WorldObjectsTab.vue:78`、
    `WorldReviewTab.vue:43,173,275`），展开态绑定逻辑各异。
17. **分页器 `total <= limit` 时整体消失**（`world/components/WorldPager.vue:6`），
    第 1 页用户无法确认总数。

## 3. 目标布局与信息层级

### 3.1 已采纳资产与统一待决定工作台

一级 subnav 只放 4 个入口：

- **已采纳资产组**（3 个一级项）：`人物与设定`（objects；aliases 作为其深链子视图，
  无独立一级项，高亮归并到本项）、`关系`（relations）、`世界笔记`（bible）。
- **待处理组**（1 个一级项）：`需要处理` 直接进入 `world/review`，工作台内以
  `全部 / 对象 / 别名 / 关系` 切换队列。「全部」只承担概览与推荐下一项，不混排三种
  候选、不提供跨类型分页、多选或写入。

旧 `review-objects` / `review-aliases` / `review-relations` 路由仅作兼容重定向，保留 query
与精确 `entity_id` / `group_id` 定位。分组的认知依据仍是作者的两个问题：「我的世界现在
有什么」与「AI 又提出了什么要我决定」，而不是底层数据表或内部路由。

### 3.2 审核队列作为第一优先级区域的论证

- 对应产品核心循环「AI 产出 → 待处理 → 人工采纳」（共同承诺第 5 条「AI 不越权」）：
  未处理的建议会持续累积并阻塞后续提取质量，作者需要一眼知道「还有多少要我决定」。
- 因此「需要处理」入口上的总计数角标**必须常显**（为 0 时整个角标隐藏，见 §4.1），
  使用主规范 §2 朱红白名单第 2 条「待处理计数角标」——这是 world 页唯一允许使用
  朱红计数的位置，与 today attention、sidebar badge 同一语义。
- 队列内部信息层级：队列说明 → 常驻搜索 → 任务标签 → 已启用条件 → 更多筛选 → 当前结果
  → 批量处理 → 列表 / 分页。候选条目是页面上唯一的 Card/表格主体，
  不再叠加其他同级焦点区块。

## 4. 逐区域标准

### 4.1 subnav（映射主规范 §5.5）

- 形态：文字 tab + 激活 2px `--line-accent` 墨线；激活项 `aria-current="page"`（现状已具备，保留）。
- 「需要处理」是直达统一工作台的 subnav 项，总计数用 §5.8 待处理角标（朱红小圆点 +
  mono 数字）；**计数为 0 时角标整体隐藏**；计数 >99 显示「99+」。工作台内四个类型
  tab 使用同一计数语义，不再通过 `<details>` 下拉承载队列导航。
- 「视图与整理」details 拆分：AI 资料整理开关提升为独立二级按钮（它是动作不是视图设置）；
  卡片/表格、最近相关/全部两组切换改用 `role="group"` + `aria-pressed`（与 bible
  模式切换一致），不再用 `btn-primary` 表达选中。
- 视图模式默认值收敛为单一来源：prop 默认、URL 缺省 fallback、localStorage 偏好
  三处统一为「表格」一处定义（worldIsland 解码层），消除 §2-8 的漂移。

### 4.2 对象库（卡片 + 表格双视图；映射 §5.3 Card / §5.4 Table / §5.10）

- **表格视图**（默认，工作台密度）：9 列收敛——「注意」列改为 6px 语义色点 + 截断
  摘要（hover title 看全文），不整段拼接枚举文案；操作列右对齐，行内操作全部
  `.btn-text` / `.btn-icon`（§5.4），更多动作收敛进既有 ActionMenu。
  选中行 `--bg-active` + 左侧 3px 朱红 `--line-active`。
- **卡片视图**：仅用于浏览/挑选场景；卡片 = paper-raised + `--line-subtle`，无阴影
  （§5.3）。有图时顶部显示上半部分裁切缩略图，无图沿用 `entityAvatarColor` 首字色块；卡片为
  等高纵向布局，底部操作区贴底且不再放“编辑”。整卡可点击并支持 Enter/Space，打开现有编辑
  弹窗的左表单/右完整图详情；窄屏为单列。上传图片、复选框和更多菜单独立处理，不触发详情；
  首列更多菜单在局部向右展开，避免左侧遮挡。表格同样提供“上传图片”。
- 热点概览 `.world-hot-overview` 的 facet chips 用 §5.8「标签」形态（描边小胶囊、
  中性色），不染色；状态行文字用 `--text-secondary`。
- 空态保留现有引导型结构（一句说明 + 「手动新建对象」CTA），图标统一进 `.empty-icon`
  体系（去 emoji，见 §5）。

### 4.3 统一待决定工作台（映射 §5.3 / §5.4 / §5.8 / §5.10）

> **复用声明（全产品统一心智）**：本节定义的「待处理队列」视觉与交互标准——
> 朱红计数角标、队列说明、常驻搜索、任务标签、已启用条件、更多筛选、当前结果、
> 附着列表顶部的批量操作条、候选条目
> （卡片/表格行）+ 行内采纳/拒绝、条目级 `role="alert"` 错误、「全部处理完」空态——
> 是全产品「AI 产出 → 待处理 → 人工采纳」模式的**基准实现**。outline 的大纲建议、
> scene 的场景候选项、map 的动态事件待处理等同类队列必须复用同一套 class 语义与
> 布局顺序，不得各自发明；world 三队列自身先收敛为完全同构，再向其他模块推广。

- **布局顺序统一**（三个类型队列一致）：队列说明 → 常驻搜索 → 任务标签 → 已启用条件
  → 更多筛选 → 当前结果 → 批量处理 → 列表 / 分页。批量操作条恒渲染于结果摘要之后、
  列表正上方（消除 §2-5 的位置分裂；未选中时操作按钮 disabled，计数显示「未选中」）。
- **候选条目**：review-objects 候选表格沿用 `.data-table.table-card-list`；候选动作
  徽标 `.candidate-action-badge--*` 改为「文字 + 色点」（§5.8），不用彩色 pill。
  「建议设为别名」「名称相似」分组卡保留（分组是本队列的真实决策单元），组头
  「全选本组」与组级操作用 `.btn-text`。
- **采纳 / 拒绝**：行内主动作「采用」= 行内唯一 `.btn-primary`（行级，不违反每屏
  一个 primary——屏幕级 primary 是头部「新建」）；「忽略·设为临时」用 `.btn-danger`
  的文字/边框形态（非实心）。普通别名和关系在桌面右侧决策区预览并提交，390px 改为
  全屏复核页；主按钮文案写动作本身（「采用别名」「采用关系」）。
- **批量操作**：三队列 scope 独立的 `.bulk-toolbar` 保留；批量按钮继续走 confirmAction
  二次确认（AGENTS.md 危险操作约束）；批量结果用 toast 反馈（§5.7），乐观更新失败
  回滚时 toast 说明「未生效，请重试」。
- **筛选收敛**（消除 §2-6）：搜索框常驻，搜索候选名称、关系/别名类型、描述与证据摘录；
  任务标签只表达作者当前要解决的问题，已启用条件紧随其后并可逐项删除；其余条件进入
  「更多筛选」。全部输入使用可见 label（§5.2 结构），不靠 placeholder。三个队列的
  精确筛选如下：

  | 队列 | 任务标签 | 更多筛选 |
  |---|---|---|
  | 对象 | 可作为新对象 / 建议设为别名 / 建议合并 / 需我判断 | 对象类型、建议动作、章节、场景、置信度 |
  | 别名 | 同对象多别名 / 自定义类型 / 缺少引用 / 高置信度 | 别名类型、章节、场景、置信度、证据状态 |
  | 关系 | 同对象对多类型 / 有反向候选 / 已有正式关系 / 缺少引用 / 低强度 | 关系类型、章节、场景、强度、证据状态 |

- **搜索边界**：上述常驻搜索是审核任务内的候选定位，不合并到一级「查找」。一级「查找」
  继续面向正文、世界对象与故事结构的跨资产检索；本轮不改变其范围、结果卡、权限或 URL
  契约，也不要求从跨资产结果精确深链到待处理关系组。
- **关系筛选契约**：列表查询新增可选布尔参数 `has_reverse_candidates`（该有向组存在
  反向方向的待处理候选）与 `has_canonical_relation`（同一有向端点对已有正式关系）；
  两个任务标签仅传 `true`。服务端必须在计算关系组总数与分页之前过滤，保证「当前结果」
  与实际页内容一致。
- **计数语义**：一级「需要处理」、工作台类型 tab 与 Writing Home / Today 类型提醒均统计
  当前仍有效且未采用的候选条目数，不以分组数或当前页行数冒充待办总量；已采用、已忽略、
  过期和历史项不计入。别名与关系的「当前结果」同时展示 `group_total` 与 `item_total`，
  分页仍按组。Today 中 A→B 与 B→A 恢复为两条有向提醒，各自携带 `group_id`；工作台可提示
  反向候选，但不得自动归并两个方向。

### 4.4 世界书（映射 §5.5 / §5.6 / §5.10）

- **去双 header**：`.world-bible-toolbar` 与 view-header 视觉分层——toolbar 收窄为
  区块级工具行（区块标题 + 模式切换 role="group" aria-pressed + 操作按钮组），
  「新建页面」为该区块唯一 `.btn-primary`，其余 `.btn-ghost`。
- **枚举中文化**（消除 §2-13）：分区类型/敏感度/投影策略下拉全部经中文映射表展示
  （如 `markdown`→「自由文本」、`author_safe`→「作者限定」——具体文案执行时与产品
  确认）；右栏 Activation Profile / 试运行 / token 容量收敛进「AI 参考规则」折叠
  区块，默认收起，属诊断能力次级入口（AGENTS.md 渐进展开原则）。
- editor 三栏布局 `18fr 57fr 25fr` 保留（符合内容优先契约主栏 64-68% 的意图）；
  gallery/filter 模式的分类卡保留交错入场动效，`prefers-reduced-motion` 下降级（§7）。

### 4.5 更多筛选面板（objects 与三个类型队列共用模式；映射 §5.10）

- 默认收起为「更多筛选」入口，已启用条件在入口之前始终可见并可逐项删除；展开为面板。
  开合状态持久化保留（worldSession.js 现状），`aria-expanded` / `aria-controls` 契约不动。
- 面板内控件按「类型与状态 / 来源与批次 / 数值范围」分组，组间距 `--space-4`；
  所有输入带可见中文 label；「应用 / 清空」按钮组右对齐，应用 = `.btn-primary`
  （面板局部）、清空 = `.btn-text`。
- 对象、别名、关系仅展示 §4.3 为各自列出的更多筛选字段；任务标签不在面板内重复。
- 「已筛选」小标 `.world-filter-panel__active` 改为已启用条件区的计数文案，不另造徽章。

## 5. 状态覆盖清单

| 区域 | 加载 | 空态 | 错误 | 备注 |
|---|---|---|---|---|
| objects | **新增** `.loading-skeleton` 表格骨架（§5.9 归一，禁第四种） | 保留引导型空态 + 新建 CTA；图标入 `.empty-icon` | `.error-card` 基准 + `role="alert"` + 重试（现状有 alert 无重试，补重试） | 加载期间不得渲染空态 |
| review-objects | **新增** 骨架（候选行形态） | 正面反馈：「全部处理完，没有待处理对象」+ 一句引导（现状「没有待处理对象」文案升级） | 现状完整（`role="alert"` + 重试），图标「!」换 `.empty-icon` 体系 | 三段分组各自的局部空态不另做 |
| review-aliases | **新增** 骨架 | 同上正面反馈（「别名建议都处理完了」） | **补** `role="alert"` + 重试按钮（现状裸文案） | 行内错误 `.review-item-error[role="alert"]` 保留 |
| review-relations | **新增** 骨架 | 同上正面反馈（「关系建议都处理完了」） | **补** `role="alert"` + 重试按钮 | 同上 |
| relations / aliases 正式列表 | **新增** 骨架 | 保留现有空态，补一句引导 | **补** `role="alert"` + 重试（现状一行裸文案） | |
| bible（三模式） | synopsis/projection 任务沿用 WorkflowProgressCard；页面级**新增**骨架 | gallery/filter/editor 各保留现有空态，图标入 `.empty-icon` | 投影失败沿用「重试投影」按钮，错误文案人话化 | |
| 批量操作反馈 | 操作 pending 期间按钮 disabled + loading（§7 反馈闭环） | — | 乐观更新回滚时 toast「操作未生效，请重试」 | 选择状态不持久化（现状合理，保留） |
| 窄屏 | 骨架随布局降档 | 空态 CTA 全宽、触控 ≥42px | 重试按钮 ≥44px（`.world-review-touch-target` 补基样式） | 见 §6 |

统一规则：空态与错误态**不得同形**——空态无重试、错误态必有重试；加载态与空态
不得同屏先后闪现（有加载态期间隐藏空态）。「全部处理完」类空态是正面反馈，
语气肯定、不带警告色，可附「去对象库看看」次级链接。

## 6. 响应式行为（四档，映射主规范 §6）

现状断点 720/760/980/600 并存，执行时按主规范 §6 归并到 760/1100 两档；
下表为目标行为，迁移期间保持 390px 零横向溢出（`world.spec.js:62-69` 回归矩阵）。

- **Desktop（≥1440）**：现状形态。对象表格 9 列全显；bible 三栏 `18fr 57fr 25fr`；
  subnav 单行。
- **Laptop（1100–1440）**：同 Desktop；bible 三栏按比例收窄，rail 不低于
  `--workspace-rail-*-min`。
- **Tablet（760–1100）**：bible 三栏塌为两栏、inspector 移到侧列（现 761-1100 规则
  保留并齐到 760 起）；候选分组条目单列（现 ≤980 规则归入本档）；对象表格允许
  隐藏「来源/注意」低优先列（执行时核实列宽余量，若不足则提前卡片化）。
- **Mobile（<760）**：subnav 两列换行（editorial-theme.css:1334-1348 现状保留）；
  所有 `.data-table` 一律卡片化——relations / aliases 表格**补** `table-card-list`
  与 `data-label`（现仅 objects/候选表格有，§2 缺口）；「需要处理」与「视图与整理」
  下拉面板改底部浮层（现 ≤600 规则归入本档）；按钮 ≥42px、输入 ≥44px；
  bible 单栏、inspector 归位文档流尾。

## 7. 必须保留的契约

world 全部组件头部注释声明「DOM class/id/data-action 逐节点保留（e2e 契约）」。
以下为执行时不得改名/删除的钩子；新增钩子同步补进本清单与 selectors.js。

### 7.1 #id（模板）

- WorldView：`#btn-new-entity`
- ObjectsTab：`#w-extract-start` `#w-extract-end` `#w-extract-progress` `#w-extract-status`
  `#world-filter-panel-objects` `#filter-entity-type` `#filter-display-state` `#filter-q`
  `#filter-source` `#filter-workflow-id` `#filter-needs-review` `#filter-auto-ingested`
- ReviewTab：`#review-candidate-entity-type/action/source/workflow/scene/chapter/confidence-min/confidence-max`；
  `#review-alias-q/source/workflow/scene/chapter/confidence-min/type-kind/page-size`；
  `#review-relation-q/scene-quick/type/scene/source-chapter/strength-min/type-kind/page-size`；
  就地决策 `#alias-inline-target-id/text/kind/type/type-custom`、
  `#relation-inline-kind/type/type-custom/description/strength`
- Bible：`#bible-title` `#bible-page-type` `#bible-sort-order` `#bible-page-template`
  `#bible-free-text` `#bible-asset-ref-picker` `#bible-asset-refs` `#bible-activation-profile`
  `#bible-activation-task`；规则模态 `#bible-profile-key/name/action` `#bible-rule-name/positive/negative/target-picker/target/priority/top-k/token-cap`
- 模态（logic）：`#create-entity-name/type/summary`、`#edit-entity-name/type/summary/error`、
  `#merge-target-picker`、`#merge-target-id`、`#rollback-scene-index`、
  `#knowledge-target-id/level/content/chapter/misconception`（worldEntityOps.js）；
  `#rel-source/target/type/desc`、`#alias-entity/text/type`（worldRelationsAliasesOps.js）

### 7.2 data-action（按区域，全量保留）

- 导航：`nav-objects/relations/bible`、`nav-review-objects/aliases/relations`
- 对象库：`new` `toggle-extract` `set-object-view`(+data-view-mode) `set-discovery-mode`(+data-mode)
  `submit-extract` `toggle-filter-panel` `toggle-advanced-filters` `apply-filters` `reset-filters`
  `set-hot-focus` `set-hot-type` `mark-entity-reviewed` `edit-entity` `merge-entity`
  `open-entity-map` `promote-entity` `rollback-entity` `knowledge-entity` `delete-entity`
  `fuse-entities` `alias-entities` `delete-entities`
- 审核：`accept-candidate` `ignore-candidate` `resolve-candidate-alias` `accept-candidates`
  `ignore-candidates` `retry-candidate-load` `apply/reset-candidate-review-filters`
  `apply/reset-alias-review-filters` `apply/reset-relation-review-filters`
  `set-alias-quick-filter` `set-relation-quick-filter` `apply-relation-scene-quick`
  `remove-review-filter` `prepare-alias-review` `prepare-relation-review`
  `confirm-alias-merge` `ignore-current-alias` `cancel-alias-decision`
  `relation-person-card` `confirm-relation-decision` `ignore-current-relation` `cancel-relation-decision`
  `review-aliases-batch` `ignore-aliases-batch` `apply-relation-decisions`
  `ignore-relation-groups` `copy-review-diagnostic`
- 关系/别名：`create-relation` `delete-relation` `review-relations` `delete-relations`
  `create-alias` `delete-alias` `review-aliases` `delete-aliases`
- 批量基础：`bulk-run`(+data-scope+data-bulk-action) `bulk-clear` `bulk-toggle-all` `bulk-toggle-one`
- 分页：`prev/next-page` `prev/next-candidates-page` `prev/next-aliases-page` `prev/next-relations-page`
- Bible：`bible-set-display-mode` `bible-new-page` `bible-manage-categories`
  `bible-manage-page-templates` `bible-open-suggestions` `bible-open-conflicts`
  `bible-gallery-back` `bible-gallery-open` `bible-set-category` `bible-open-page-card`
  `bible-refresh-synopsis` `bible-synopsis-history` `bible-toggle-synopsis-auto`
  `bible-unpin-synopsis` `bible-improve-with-ai` `bible-save-page` `bible-publish-page`
  `bible-discard-draft` `bible-page-history` `bible-archive-page` `bible-refresh-projection`
  `bible-retry-projection` `bible-force-refresh-projection` `bible-apply-page-template`
  `bible-section-add/up/down/remove` `bible-activation-new/edit/publish/dry-run`

### 7.3 role / 可访问名称 / 其他语义钩子

- `role="alert"`：objects 错误态（WorldObjectsTab.vue:130）、review-objects 错误态
  （WorldReviewTab.vue:57）、行内错误 `.review-item-error`（:241, 337）；§5 要求补齐的
  四处错误态新增后同样保留。
- `role="group"` + `aria-label`：bible 模式切换、对象视图/排序切换、bible 分类组。
- `aria-current="page"`：全部 subnav 项（一、二级）。
- `aria-expanded` / `aria-controls`：筛选面板 toggle（world-objects.spec.js 回归）。
- `aria-pressed`：bible 模式/分类按钮；§4.1 后视图切换组同样使用。
- `role="note"`：提取提示（WorldObjectsTab.vue:19）、bible 资料页提示（WorldBibleTab.vue:248）。
- 结构钩子：`data-subview`（selectors.js:136）、`data-filter-panel`、`data-diagnostic-field`、
  `data-bible-page-id/draft-id`、`data-section-id`、`data-target-id`（候选别名分组）、
  `data-group-id`、`tr[data-id]`、`data-label`（表格卡片化）、
  `[data-reference-query/result/selected]`（资产引用 picker）、
  `input[name="world-bulk-target"]`、`span[data-role="smart-dedup-action"]`（外部注入位）。
- 可访问名称：筛选输入的中文 label 文案有 `world-relations-aliases.spec.js:127+`
  专项回归；改名前全局 grep `getByRole({name})` / `getByText`（主规范 §9）。

## 8. 验收标准 + 验证命令

### 8.1 验收标准（逐项可判）

1. §2 的 P0/P1 全部关闭：六个区域有骨架加载态；四处裸错误态补齐 `role="alert"` +
   重试；角标 0 隐藏、>99 显示 99+；「需要处理」直达统一工作台；三个类型队列统一为
   「队列说明 → 常驻搜索 → 任务标签 → 已启用条件 → 更多筛选 → 当前结果 → 批量处理
   → 列表 / 分页」；视图切换默认值单一来源。
2. 审核队列视觉与 outline/scene/map 待处理模式共用同一套 class 语义（§4.3 复用声明落地）。
3. bible 不再暴露英文内部枚举；枚举映射文案经产品确认。
4. 主规范 §1.4：本页新增/触碰样式零直写像素、零行内 style（§2-10 清除）。
5. 390px 无页面级横向溢出；≤760px 全部表格卡片化、触控目标达标。
6. 三主题（minimal/warm/dark）下朱红仅出现在白名单位置（角标、focus 环、错误、选中线）。
7. 全部 e2e 与视觉基线通过（下方命令）；契约钩子（§7）零改名零删除。

### 8.2 验证命令

```bash
cd frontend-console

# 功能 e2e（world 全量，含响应式矩阵与可访问名称回归）
npm run test:e2e:functional -- e2e/world.spec.js e2e/world-objects.spec.js \
  e2e/world-relations-aliases.spec.js e2e/world-view-switch.spec.js e2e/world-bible.spec.js

# 视觉基线：9 张快照 = 3 页面（objects / review-objects / bible）× 3 主题（minimal/warm/dark），
# 1440×900，darwin 基线；改任何 class 结构都会打破基线，需先确认再更新
npm run test:e2e:visual -- e2e/visual-world.spec.js
# 确需更新基线时：
npm run test:e2e:visual:update -- e2e/visual-world.spec.js

# 单元/契约（token 与主题门禁）
npm run test
```

非 darwin 平台视觉测试默认 skip，需 `VISUAL_BASELINE=1` 并先生成本地基线
（`e2e/visual-world.spec.js:34-37`）。已知未覆盖项（执行时补测）：hot 概览 chips、
批次分组折叠、bible gallery/filter 模式切换、窄屏表格卡片化的视觉回归。
