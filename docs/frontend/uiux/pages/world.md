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

1. **已解决：共享路由骨架覆盖 world 全部子视图**。`router.js` 在业务 loader 完成前渲染
   `role="status"`、`aria-busy="true"` 的通用骨架，`mountIsland` 只在数据返回后挂载组件；
   1800ms 延迟实测子视图切换期间不会闪空态（2026-08-23）。world 不再重复维护第二套
   页面级 skeleton，局部任务仍使用各自的明确进度反馈。
2. **已解决：relations / aliases 正式列表错误态统一**。两者均使用 `role="alert"` +
   “重新加载”，内部处理批次与原始场景/章节标识默认收进“诊断信息”（2026-08-23）；
   review-objects / review-aliases / review-relations 同样具备可重试错误态。

### P1 — 核心循环体验断裂

3. **已解决：「需要决定」角标按注意力语义显示**。0 项时隐藏，超过 99 项显示 `99+`，
   辅助技术仍通过按钮可访问名称获得精确总数；复用 Today 的注意力计数样式，不新增同义
   badge（2026-08-23）。
4. **已解决：审核入口改为直接导航按钮**。不再使用需要额外关闭语义的 `<details>`；
   点击后直达统一“需要决定”工作台，当前页使用 `aria-current="page"`（2026-08-23）。
5. **已解决：三队列批量操作条位置统一**。对象、别名、关系都在「当前结果」后直接显示
   同一个批量栏；正常队列为 0 项时保持可见但禁用写入动作，加载失败时隐藏（2026-08-23）。
6. **已解决：审核筛选按作者任务分层**。三个队列统一为「常驻搜索 → 有可见名称的快速查看
   → 已启用条件 → 更多筛选」；快速项只承载高频任务，场景、章节、置信度、类型和证据等
   精确条件保留在带可见 label 的折叠面板内，URL 恢复语义不变（2026-08-23）。
7. **已解决：objects 头部操作按任务分层**。「从正文整理资料」成为独立次级动作；
   「浏览方式」只保留显示方式与资料范围两组切换，并用 `aria-pressed` 暴露当前状态；
   窄屏面板提供明确的「完成」关闭动作（2026-08-23）。
8. **已解决：卡片/表格默认视图统一**。URL 未指定或值无效时统一回落「表格」，组件
   prop 默认同为 `"table"`；旧 `view=card` / `view=table` 链接继续有效（2026-08-23）。

### P2 — 一致性与可读性

9. **已解决：世界资料空态统一为文字优先**。objects 与 review-objects 移除零散 emoji、
   裸字符及行内颜色，和 aliases、relations、bible 使用相同的标题、说明与就地操作层级；
   不为装饰目的新增第二套图标系统。
10. **已解决：待决定工作台移除行内视觉样式**。二级导航、更多筛选间距和对象证据单元格
    均改为 token 驱动的语义 class，三种主题可统一接管（2026-08-23）。
11. **已解决：对象表格按作者扫读任务收敛为四列**。状态、类型、名称与近期标签合并为
    「对象」，摘要、来源与重要度合并为「资料概览」；无注意事项时不再常驻空列，有事项时
    在对象名下显示短提示。行内只保留编辑和当下必须处理的动作，上传图片、合并、回滚、
    知识与删除继续保留在既有更多菜单（2026-08-23）。
12. **已解决：relations / aliases 正式列表支持就地搜索**。关系可按端点名称、类型与描述，别名可按
    别名、所属对象与引用查找；输入带可见中文标签并支持 Enter 提交、清除和无结果恢复提示。
    搜索词与分页共用 URL 恢复，刷新、前进/后退和项目切换不会串用旧条件（2026-08-23）。
13. **已解决：bible editor 改用作者语言并渐进展开**。`markdown` / `author_safe` /
    `eligible` 等 wire 值保持不变，但界面只显示“普通资料”“作者规划可见”“参与自动整理”等
    中文；分区标识和局部引用标识收进“维护信息”，规则预览与后端警告码也改为可读说明
    （2026-08-23）。
14. **已解决：bible 页内双 header 与同级按钮堆叠已收敛**。页内标题改为独立区块工具行，
    不再复用 `.view-header` 的页面级视觉；新建页面是唯一主按钮，分类、模板、导入、建议、
    冲突和检修收进“更多工具”，页面历史、归档、丢弃和写作参考更新收进“页面工具”
    （2026-08-23）。
15. **已解决：窄屏待决定工作台统一最小触控尺寸**：工作台范围内按钮不小于
    44px，决策页底部预留固定导航安全距离（2026-08-23）。
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
- 「从正文整理资料」是独立二级动作；「浏览方式」details 只承载卡片/表格、
  最近相关/全部资料两组 `role="group"` + `aria-pressed` 切换，不用 `btn-primary`
  表达选中；窄屏用面板内「完成」明确关闭。
- 视图模式默认值统一为「表格」：worldIsland URL 解码与两个组件 prop 同值；显式
  `view=card` / `view=table` 继续随 URL 恢复。

### 4.2 对象库（卡片 + 表格双视图；映射 §5.3 Card / §5.4 Table / §5.10）

- **表格视图**（默认，工作台密度）：选择列之外只保留「对象 / 资料概览 / 操作」。名称是
  第一视觉锚点，类型、状态和近期标签作为同组辅助信息；摘要最多显示两行并保留全文 title，
  来源与重要度退为次级元数据。只有存在注意事项时才显示 6px 语义色点和短提示，不再为正常
  对象渲染一列破折号。操作列右对齐，保留编辑及当前必须处理的动作，低频操作进入既有
  ActionMenu；全部业务能力与 `data-action` 契约不变。
- **卡片视图**：仅用于浏览/挑选场景；卡片 = paper-raised + `--line-subtle`，无阴影
  （§5.3）。有图时顶部显示上半部分裁切缩略图，无图沿用 `entityAvatarColor` 首字色块；卡片为
  等高纵向布局，底部操作区贴底且不再放“编辑”。整卡可点击并支持 Enter/Space，打开现有编辑
  弹窗的左表单/右完整图详情；窄屏为单列。上传图片、复选框和更多菜单独立处理，不触发详情；
  首列更多菜单在局部向右展开，避免左侧遮挡。表格同样提供“上传图片”。
- 热点概览 `.world-hot-overview` 的 facet chips 用 §5.8「标签」形态（描边小胶囊、
  中性色），不染色；状态行文字用 `--text-secondary`。
- 空态保留现有引导型结构（一句说明 + 「手动新建对象」CTA），各世界资料区统一为文字优先，
  不引入装饰性 emoji 或第二套图标体系。

### 4.3 统一待决定工作台（映射 §5.3 / §5.4 / §5.8 / §5.10）

> **复用声明（全产品统一心智）**：本节定义的「待处理队列」视觉与交互标准——
> 朱红计数角标、队列说明、常驻搜索、任务标签、已启用条件、更多筛选、当前结果、
> 附着列表顶部的批量操作条、候选条目
> （卡片/表格行）+ 行内采纳/拒绝、条目级 `role="alert"` 错误、「全部处理完」空态——
> 是全产品「AI 产出 → 待处理 → 人工采纳」模式的**基准实现**。outline 的大纲建议、
> scene 的场景候选项、map 的动态事件待处理等同类队列必须复用同一套 class 语义与
> 布局顺序，不得各自发明；world 三队列自身先收敛为完全同构，再向其他模块推广。

- **布局顺序统一**（三个类型队列一致）：队列说明 → 常驻搜索 →「快速查看」任务标签 → 已启用条件
  → 更多筛选 → 当前结果 → 批量处理 → 列表 / 分页。批量操作条恒渲染于结果摘要之后、
  列表正上方（消除 §2-5 的位置分裂；未选中时操作按钮 disabled，计数显示「未选中」）。
- **候选条目**：review-objects 候选表格沿用 `.data-table.table-card-list`；名称、中文类型、
  重要程度与两行摘要合并为「待处理对象」，来源缺失时明确显示「未附来源」，不暴露 raw 类型。
  候选动作徽标 `.candidate-action-badge--*` 改为「文字 + 色点」（§5.8），不用彩色 pill。
  「建议设为别名」「名称相似」分组卡保留（分组是本队列的真实决策单元），组头
  「全选本组」与组级操作用 `.btn-text`。
- **采纳 / 拒绝**：对象、别名与关系队列条目都只提供次级「查看并决定」；完整摘要、
  AI 建议、来源依据与全部可用决策集中到桌面右侧决策区或 390px 全页复核页。对象决策只让
  AI 建议对应的采用 / 设为别名 / 合并动作成为主按钮；只有「采用别名 / 采用关系」是
  `.btn-primary`，忽略保持
  危险文字/边框形态，「稍后再决定」是普通次级按钮。别名决策使用「归属对象、待采用名称、
  名称用途、具体称呼」等作者语言，不在主操作层暴露内部归并心智。
- **选择恢复与焦点**：当前待决定项写入前端 URL query `review_item`，刷新、浏览器前进/后退
  都恢复同一条，项目 ID 改变后不复用旧选择。桌面选中后聚焦带标题的决策区；窄屏聚焦
  「返回队列」，返回后恢复原条目焦点。
- **共创闭环**：设定共创生成对象建议后，以兼容影子的 `result_ref_json.id` 同时写入
  `entity_id + review_item`，直接加载并选中该条，不要求作者在全队列重新搜索；决策区保留
  「返回继续完善」。已采用、忽略、归档或不存在的精确对象只显示已离队提示，不重新进入
  待处理列表。旧的无精确 ID 深链继续进入对象队列。
- **批量操作**：三队列 scope 独立的 `.bulk-toolbar` 保留；批量按钮继续走 confirmAction
  二次确认（AGENTS.md 危险操作约束）；批量结果用 toast 反馈（§5.7），乐观更新失败
  回滚时 toast 说明「未生效，请重试」。别名批量采用只应用作者逐条打开并准备过的归属与分类，
  草稿必须与当前执行指纹一致，且归属对象、别名、名称用途和具体称呼均已补全；
  否则在请求前阻断。单条采用成功后先把下一条 `review_item` 写入 URL 再刷新，新组件直接
  恢复下一条与桌面/窄屏焦点；末项则清除定位并返回队列。
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
  「新建页面」为该区块唯一 `.btn-primary`；分类、模板、导入、建议、冲突和检修收进
  原生「更多工具」，不再与展示模式平级抢占首屏。
- **枚举中文化**（消除 §2-13）：分区类型/敏感度/投影策略下拉全部经中文映射展示
  （如 `markdown`→「普通资料」、`author_safe`→「作者规划可见」）；右栏规则方案、预览任务与
  单次参考篇幅收敛进「AI 参考规则」折叠
  区块，默认收起，属诊断能力次级入口（AGENTS.md 渐进展开原则）。
- **编辑优先**：世界健康与世界观简介默认只显示可读状态摘要；校验运行、失败或阻断时世界
  健康自动展开，简介生成中自动展开。编辑器只常驻「用 AI 完善、保存工作稿、保存并发布」；
  历史、归档、丢弃和写作参考更新收进「页面工具」，排序与模板收进「页面设置」。
- **建议应用**：编辑创设建议只开放标题、类别和页面概览；分区与关联资料原样带入工作稿，
  作者在现有页面编辑器中继续调整。主流程不显示或接受 sections/资产关联 JSON。
- editor 三栏布局在 AI 参考规则展开时保留 `18fr 57fr 25fr`；默认收起时主栏扩为
  `18fr 67fr 15fr`（符合内容优先契约主栏 64-68% 的意图）；
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
| objects | 首进与筛选导航沿用共享路由骨架 | 保留文字引导型空态 + 新建 CTA | `role="alert"` 说明原资料未变 + 原位重新加载 | 加载期间不得渲染空态 |
| review-objects | 首进与筛选导航沿用共享路由骨架 | 文字反馈「没有待处理对象」+ 一句引导 | `role="alert"` + 重试；诊断信息默认收起 | 三段分组各自的局部空态不另做 |
| review-aliases | 首进与筛选导航沿用共享路由骨架 | 同上正面反馈（「别名建议都处理完了」） | 已有 `role="alert"` + 重试；诊断信息默认收起 | 行内错误 `.review-item-error[role="alert"]` 保留 |
| review-relations | 首进与筛选导航沿用共享路由骨架 | 同上正面反馈（「关系建议都处理完了」） | 已有 `role="alert"` + 重试；诊断信息默认收起 | 同上 |
| relations 正式列表 | 首进、搜索与分页沿用共享路由骨架 | 无资料时保留引导；搜索无结果时保留搜索栏与清除提示 | 已有 `role="alert"` + 重试；内部标识默认收进“诊断信息” | 搜索词与分页写入 URL |
| aliases 正式列表 | 首进、搜索与分页沿用共享路由骨架 | 无资料时保留引导；搜索无结果时保留搜索栏与清除提示 | 已有 `role="alert"` + 重试；内部标识默认收进“诊断信息” | 搜索词与分页写入 URL |
| bible（三模式） | 首进沿用共享路由骨架；synopsis/projection 任务沿用 WorkflowProgressCard | gallery/filter/editor 各保留文字优先空态 | 投影失败沿用「重试投影」按钮，错误文案人话化 | |
| 批量操作反馈 | 操作 pending 期间按钮 disabled + loading（§7 反馈闭环） | — | 乐观更新回滚时 toast「操作未生效，请重试」 | 选择状态不持久化（现状合理，保留） |
| 窄屏 | 骨架随布局降档 | 空态 CTA 全宽、待决定工作台按钮 ≥44px | 重试按钮 ≥44px，决策页底部留出固定导航安全距离 | 见 §6 |

统一规则：空态与错误态**不得同形**——空态无重试、错误态必有重试；加载态与空态
不得同屏先后闪现（有加载态期间隐藏空态）。「全部处理完」类空态是正面反馈，
语气肯定、不带警告色，可附「去对象库看看」次级链接。

## 6. 响应式行为（四档，映射主规范 §6）

现状断点 720/760/980/600 并存，执行时按主规范 §6 归并到 760/1100 两档；
下表为目标行为，迁移期间保持 390px 零横向溢出（`world.spec.js:62-69` 回归矩阵）。

- **Desktop（≥1440）**：对象表格使用「对象 / 资料概览 / 操作」三组信息；bible 三栏 `18fr 57fr 25fr`；
  subnav 单行。
- **Laptop（1100–1440）**：同 Desktop；bible 三栏按比例收窄，rail 不低于
  `--workspace-rail-*-min`。
- **Tablet（760–1100）**：bible 三栏塌为两栏、inspector 移到侧列（现 761-1100 规则
  保留并齐到 760 起）；候选分组条目单列（现 ≤980 规则归入本档）；对象表格沿用三组信息，
  不再依靠隐藏来源或注意事项维持列宽。
- **Mobile（<760）**：subnav 两列换行（editorial-theme.css:1334-1348 现状保留）；
  relations / aliases 正式表格已复用 `table-card-list` 与 `data-label`，完整保留归属对象、
  分类、状态、证据与操作；「需要处理」与「视图与整理」
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
  `ignore-candidates` `retry-candidate-load` `retry-alias-review-load` `retry-relation-review-load`
  `apply/reset-candidate-review-filters`
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

- `role="alert"`：objects、正式关系与正式别名错误态、三类 review 队列错误态与行内
  `.review-item-error`；队列错误的原始技术信息收在默认折叠的「诊断信息」。
- `role="group"` + `aria-label`：bible 模式切换、对象视图/排序切换、bible 分类组。
- `aria-current="page"`：全部 subnav 项（一、二级）；aliases 深链继续把“人物与设定”标为当前页。
- `aria-label`：需要决定有内容时保留精确总数，视觉角标超过 99 仅显示 `99+`。
- `aria-labelledby="world-review-decision-title"`：决策区的可访问标题；选中项后焦点按桌面/窄屏规则移动。
- `aria-expanded` / `aria-controls`：筛选面板 toggle（world-objects.spec.js 回归）。
- `aria-pressed`：bible 模式/分类按钮；§4.1 后视图切换组同样使用。
- `role="note"`：提取提示（WorldObjectsTab.vue:19）、bible 资料页提示（WorldBibleTab.vue:248）。
- `role="search"` + 可见中文 label：正式关系与正式别名的就地搜索；搜索失败、空态和清除操作时入口仍保留。
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
