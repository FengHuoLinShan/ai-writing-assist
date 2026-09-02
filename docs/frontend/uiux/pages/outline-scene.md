# 故事结构与场景工作台 UI/UX 执行规范

> 上游：`docs/frontend/uiux/design-standard.md`（下称「主规范」）、`docs/product/user-personas.md`。
> 覆盖范围：`outline` 路由下四个子视图（story 故事总览 / arcs 篇章 / threads 剧情线 / scenes 场景）
> 与场景工作台（`SceneWorkbenchView` 及其模态、进度卡、融合流程）。源码锚点前缀均为
> `frontend-console/`，下文行号基于调研时点快照，漂移时以 grep 重新定位。

## 1. 页面定位与目标画像

- **目标画像：画像 A（长期创作的作家）**。这里是作者确认 AI 整理出的故事骨架、规划篇章与
  剧情线、并逐场景打磨细纲的核心工作台。画像 B（RP 用户）不进入本页。
- **用户任务**：从「导入正文 / AI 生成 → 看见故事结构 → 确认与补全 → 回到写作」的主路径中，
  本页承担「确认与补全」：审核大纲版本、整理篇章/剧情线归属、处理场景融合建议、为场景
  补齐目标/冲突等创作字段，再带着干净的场景细纲回写作页。
- **情绪收益**：作者「看得懂、改得安心」——结构资产的来源、状态、影响范围清楚，AI 建议
  始终待用户裁决，不误覆盖。
- **主要摩擦（当前）**：工作台密度偏高但反馈层级不统一；部分低频字段仍暴露内部 ID；
  「待处理」心智（融合建议队列）与 world 审核队列的视觉语言未对齐。
- **验证方式**：e2e 任务流（整理场景→融合→补全→去写作）完成率、场景字段补全率、融合
  建议处理/忽略比例（当前为产品假设，无真实数据）。

## 2. 现状问题清单（按严重度排序）

1. **已修复（2026-08-23）—Editorial 场景作用域漂移**：场景继续作为 outline 的 scenes
   子视图，主题统一使用共享 outline / scene-workbench 组件规则；已移除不存在的
   `[data-workspace-view="scene"]` 标记、独立页码装饰和对应死测试，不再维护第二套路由事实。
2. **已修复（2026-08-23）—「补全设定」聚焦目标**：fieldMap 已改为实际渲染的
   `scene-detail-core_conflict/must_happen/must_not_happen`，并在移动抽屉完成初始焦点后再聚焦
   第一项缺失字段，避免共享模态焦点管理覆盖目标字段。
3. **已修复（2026-08-23）—合并/拆分影响预览**：保持后端预览与确认契约不变，
   前端把章节映射、创作字段变化、关联数量和警告转译为「保留谁 / 谁移入历史 /
   哪些内容变化」的作者语言；拆分明确原场景与新场景的标题、章节去向及正文不修改，
   不再显示 raw JSON、操作枚举或场景 ID。
4. **已修复—窄屏断点一致**：JS 与 CSS 现均以 `760px` 为窄屏边界，边界值渲染移动详情抽屉。
5. **已修复（2026-08-23）—窄屏详情抽屉可访问性与防丢稿**：抽屉复用 `useModalDialog`，具备
   `role="dialog"` / `aria-modal`、Esc、焦点圈定、关闭后返回入口和可点遮罩；离开未保存修改前
   二次确认。保存时禁用字段与冲突操作，失败在表单内保留草稿并显示 `role="alert"`。
6. **已修复（2026-08-23）—信息推进时间线与旧入口落点**：有内容的剧情线默认展开，空剧情线
   保持折叠；同一 information movement 以「推进 N」归组，并用导轨、语义色点、章节与摘要形成
   时间层级。`?information=foreshadowing|reveals` 由 outline island 传入组件，滚动并聚焦包含对应
   内容的原生 `<details>`；无匹配内容时聚焦整个信息推进区，刷新、前进/后退和作品切换均不
   复用旧作品数据。
7. **已修复（2026-08-23）—场景页导航与操作层级**：四个子视图统一复用 `OutlineHeader`，
   场景标题、计数和作品名进入共享 header；浏览模式与唯一主操作「AI 创作细纲」独立于
   `.subnav`，正文整理与智能去重收入原生「整理工具」展开区。390px 下四个标签等宽完整可见，
   操作区另起一行，不再被横向滚动裁出视口。
8. **已修复（2026-08-23）—场景列表字阶与触控密度**：场景 meta 改用 `--text-xs`
   并以中点分隔，摘要、健康说明与分页分别归入 `--text-sm` / `--text-xs`；可操作健康提示
   桌面保持 28px、窄屏提升到 42px，`.scene-progress-filter` 统一为 44px 触控高度。
9. **已修复（2026-08-23）—剧情进度分段辨识**：当前、后续、已写过、未定位继续保留
   完整文字，并分别使用 accent、secondary、success、quaternary 色点和计数；筛选按钮同步
   `aria-pressed`，场景行使用同一套文字 + 色点语义，不再依赖同色 pill。
10. **已修复（2026-08-23）—场景详情视角人物**：复用共享 `referencePicker`
    按姓名或别名搜索已采用人物，以名称、摘要和作者状态消歧，选择后仅在
    内部草稿与保存 wire 保留 `pov_character_id`。无结果、加载失败和不可用旧引用
    均在字段内反馈，清空后显式提交 `null`。
11. **已修复（2026-08-23）—场景空态与局部刷新反馈**：四个子视图首次进入继续由共享
    `.loading-skeleton` 承担加载边界；Scene 初始空态提供「从正文整理场景」与「AI 创作细纲」，
    筛选空态提供「清除筛选」。列表局部刷新时保留当前内容并暂时禁用旧控件，失败后以内联
    `role="alert"` 说明内容仍被保留，同时提供原位重试，不再只依赖 toast。
12. **已修复（2026-08-23）—四层结构统一 AI 任务区**：story、threads、arcs、scenes
    均在共享标题下方使用 `.outline-task-status`，内部只复用 `WorkflowProgressCard`。并行任务
    等距纵向排列；章节范围、取消、关闭和查看建议均归入对应卡片，任务不会串到其他作品。
13. **已修复（2026-08-23）—剧情线与篇章操作主次**：标题区各只保留「新建」唯一主按钮与
    当前层级 AI 创作次按钮；AI 分析、从正文整理和智能去重收入原生「分析与整理」展开区。
    390px 下三项操作等宽单行排列，展开项保持 44px 触控高度；执行任一整理动作后菜单自动
    收起，不会在弹窗关闭后继续遮挡页面。所有原 data-action 与任务能力保留。
14. **已修复（2026-08-23）—剧情线与篇章筛选占据首屏**：两页筛选均改用原生
    `<details>`，默认只显示一行摘要及已启用条件数；状态、来源、注意原因与整理批次能力完整
    保留，应用或重置后收起并把焦点还给摘要。390px 下字段与按钮保持 44px 触控高度。
15. **已修复（2026-08-23）—故事总览首次进入重复且空洞**：无版本时只保留一个「先确定
    故事方向」入口，AI 可编辑预览为主操作、手工创建为次操作；不再重复介绍卡、emoji 空态和
    空历史卡。正常状态的重新加载收入「更多」，失败态仍原位提供重试并显示进行中反馈。
16. **已修复（2026-08-23）—故事总览已有版本卡片堆叠**：当前版本改为一篇连续阅读文档，
    故事核心使用无嵌套的定义列表，剧情线、推进和待决定问题使用有序条目；过往版本默认折叠，
    不再重复列出当前版本，查看与采用能力完整保留，查看弹窗沿用同一阅读层级。
17. **已修复（2026-08-23）—手工编辑是不可恢复的 JSON 长表单弹窗**：入口改为
    `outline/story-outline?edit=1` 独立页面，AI 预览与手工页共用结构化编辑字段，不再向作者暴露
    Markdown/JSON。未发布修改按项目暂存在本机，刷新、前后退和切换作品后可恢复；离开前确认，
    成功保存或明确放弃后清理。409 保留草稿并允许同步最新 revision 基准后重试。
18. **已修复（2026-08-23）—AI 生成设置把技术选项压在首屏**：表单先只询问故事方向、
    预计篇幅和本次规划范围；人物与世界资料收入默认折叠的可选区，不再显示 Top-K。
    缺失内容同时在字段与可聚焦的错误摘要中反馈，生成前明确说明不会自动采用。
19. **已修复（2026-08-23）—AI 预览编辑在刷新或冲突后丢失**：预览直接编辑同一份结构化状态，
    以项目 + 任务隔离暂存本机修改；刷新、返回和切换作品后可恢复。409 后禁止直接重试，
    显式同步最新基准时保留作者输入；只有成功采用或明确放弃才清理草稿。
20. **已修复（2026-08-23）—P20 当前层 AI 建议用整页 JSON 审核**：完成任务后进入
    `outline/threads?review=ai`、`outline/arcs?review=ai` 或 `outline/scenes?review=ai` 独立审阅页；剧情线按核心信息与推进节点，
    篇章按目标、冲突和关键转折，Scene 按章节范围、目标、冲突安排、情绪节拍、必须/禁止事件和叙事作用使用普通作者语言编辑。重叠、作者决策与总纲冲突渐进展开，不显示
    raw JSON、引用 ID 或置信分数。草稿按项目 + source task 隔离自动暂存，支持刷新、前后退和作品
    切换；409 冲突跨刷新锁定旧建议，采用成功或明确放弃才清理。Scene 的隐藏引用字段原样保留，作者可读选项只在提交前适配回既有 strict schema。
21. **已修复（2026-08-23）—Scene 筛选挤占首屏并丢失未应用输入**：筛选区改用原生
    `<details>` 默认收起，摘要同时显示已启用条件数与未应用修改；进一步的整理条件收入
    「更多筛选」，不向作者暴露 Phase 枚举。未应用输入按作品保存在当前浏览器会话，刷新、路由往返与
    作品切换后可恢复且不串用；应用或重置成功后收起并将焦点还给摘要，请求失败时保持展开以便修改。
22. **已修复（2026-08-23）—零选择时常驻整排批量工具**：批量条只在勾选场景后出现，
    用单一状态句说明选中数量和融合条件，并提供「退出选择」。单选只显示当前待办主操作；
    选中至少两个场景后才显示机械合并与 AI 融合。窄屏的选择区与批量按钮均为 44px，
    复选框与所属场景内容同行，不再独占一行。
23. **已修复（2026-08-23）—窄屏场景概况挤占列表首屏**：剧情进度与健康待办收入同一个
    原生 `<details>`；桌面端保持展开，窄屏默认只显示当前剧情段、数量最多的待办与其他类别数。
    作者已选筛选时摘要优先跟随当前条件。摘要可键盘展开，完整八个筛选仍保留 44px 触控高度。
24. **已修复（2026-09-02）—窄屏死钩子**：删除无 CSS 消费者的 `.is-narrow`
    class；实际窄屏行为仍由现有 `narrow` 状态控制场景概况和详情抽屉。
25. **组件归属错位（架构性说明，非视觉 bug）**：场景工作台组件在 `vue/views/scene/`
    （`SceneWorkbenchView.vue`、`useSceneWorkbench.js`、`sceneModalController.js`、
    `sceneAutoExtractManager.js` 等），但路由属 `outline/scenes`（`router.js:337-343` 将
    `view==="scene"` 归一化，`subView` 转 `?scene_id=`），由 `OutlineView.vue:7-18` 分派渲染。
    e2e 已锁定该事实（`e2e/outline-scenes.spec.js:29` 断言侧边栏无 `data-view="scene"`、
    `e2e/scene-workbench.spec.js:67` 断言场景页无 `#workspace-header`）。执行本规范时**不得**
    为消除错位而移动目录或改动路由——属目录归属整理时另行处理。
26. **已修复（2026-08-23）—未选场景时空详情栏占用三分之一宽度**：桌面端无
    `scene_id` 时不渲染详情栏，场景列表使用完整工作区；选中场景后才恢复 68/32 双栏编辑。
    后退到未选列表再次释放宽度，前进、刷新和旧深链仍按 `scene_id` 与后端分页恢复详情。
27. **已修复（2026-08-23）—Scene 详情长表单缺少返回、分组和可见保存状态**：桌面与窄屏详情都提供「返回列表」，
    字段用原生 `fieldset/legend` 分为「基本信息 / 创作要点」，章节与来源单独成节。操作栏在详情滚动区内吸底，
    未修改时显示并禁用「已保存」，改动后显示「保存修改」；未保存返回继续使用既有放弃确认。
    窄屏模态详情打开时暂时隐藏底部主导航，关闭后恢复，避免遮住保存栏或让背景导航可操作。
28. **已修复（2026-08-23）—详情操作栏把保存、当前待办、合并和拆分同时暴露**：操作栏只直接保留
    保存与当前待办，合并/拆分收入共享 ActionMenu 的「更多」结构操作。菜单在吸底栏上方展开，支持方向键、
    Home/End、Escape 和焦点恢复；窄屏使用 44px 触控入口。草稿未保存或正在保存时，当前待办和结构菜单使用原生
    `disabled` 禁用并说明先保存或放弃，避免结构刷新覆盖草稿。

## 3. 目标布局与信息层级

### 3.1 四个子视图共享骨架

- `OutlineHeader` 是 `.subnav` 四标签 + `.view-header__tail`（标题/计数/项目名 + 按子视图切换
  的操作组）的单一事实源。scenes 通过 actions slot 放入「普通/热点」toggle 与唯一主操作
  「AI 创作细纲」；剧情线/篇章保留「新建」与当前层级 AI 创作，AI 分析、正文整理、智能去重
  使用原生「分析与整理」`<details>` 渐进展开；场景的正文整理与智能去重使用「整理工具」。
- 信息层级：subnav（Primary 导航）→ 操作组（Primary 动作 ≤1）→ AI 进度卡（若有，统一
  WorkflowProgressCard 单一范式，位置固定于 header 正下方）→ 状态三件套 → 主内容。

### 3.2 story 故事总览

单列纵向流：任务进度卡（仅有任务时）→ 主操作区 → AI 预览编辑器（创作核心 4 文本域 +
剧情线/故事推进/待决定问题三个可排序列表）→ 当前版本连续阅读文档 → 默认收起的过往版本。
无版本时主操作区就是唯一首次进入空态；有版本时切换为「调整整体方向」，手工编辑为主操作，
AI 新方案为次操作。当前文档按版本与标题、故事核心、总览正文、主要剧情线、故事推进、待决定
问题顺序呈现，内部只用字阶、序号与分隔线；过往版本不重复当前版本，查看弹窗沿用同一阅读层级，
采用仍经二次确认创建新版本（主规范 §5.3）。

AI 设置是短任务弹窗：首屏只放三项作者问题，参考人物和世界资料使用原生
`<details>` 渐进展开。提交失败保留弹窗输入并聚焦错误摘要；生成成功才用新任务替换旧预览。
AI 预览作为页内连续编辑区，以项目 + source task 隔离本机草稿；刷新、返回或切换作品
不混入其他项目。CAS 409 保留当前内容和草稿，先同步最新 base revision 才重新开放采用。

手工入口进入同一子视图的 `?edit=1` 独立页面，顶部仍保持故事总览标签选中。编辑页复用 AI
预览的结构化字段，长正文与可排序列表连续排列，底部主操作固定可达；本地草稿键包含项目 ID，
路由离开和浏览器关闭前先持久化并确认。直接深链、刷新、前后退和切换作品均按项目恢复；保存
成功以 replace 返回总览并清理草稿，CAS 409 时只刷新 base revision，不替换作者当前输入。

### 3.3 arcs 篇章

筛选条（默认收起为一行摘要并显示已启用条件数；应用/重置后收起，URL 与未应用草稿语义不变）→
批量工具条（选中时出现，附着列表顶部）→ `.data-table` 七列 → 分页。行选中态用
`--bg-active` + 左侧 `--line-active`（§5.4）。

### 3.4 threads 剧情线（含伏笔揭示归并）

表格区同 arcs 结构；下方「信息推进」区是本页独有的**叙事时间线**，可读性层级：

1. 剧情线名 + 信息运动计数（区块标题档 `--text-md` 600）；
2. movement 分组节点（条目标题档 `--text-base` 600）；
3. 节点 badge「暗示/兑现」「局部/完整揭示」——用文字 + 6px 语义色点，不用彩色 pill（§5.8）；
4. 章节号与内容摘要（辅助说明档 `--text-sm` secondary）；
5. 时间线纵向用 1px `--line-subtle` 导轨 + 节点圆点串联，不画卡片框。

有信息运动的剧情线默认展开、空的折叠；旧伏笔/揭示深链会滚动定位、聚焦对应
`<details>` 并短暂以 `--accent-soft` 高亮。「未归入剧情线」details 保留就地归属下拉，
下拉具有按计划名称生成的可访问名称，归属操作完成后行内 toast 确认。

剧情线 AI 建议属于需要独立导航与恢复的长任务，使用 `?review=ai` 页面而非弹窗。页面按
提示/冲突 → 剧情线核心 → 人物认知与依据 → 信息推进与节点 → 单一采用主操作排列；复杂资料
使用原生 `<details>`。所有可编辑字段带可见 label，失败提交同时保留字段错误并聚焦顶部错误
摘要。离开和 `beforeunload` 先按项目 + source task 暂存；直接深链无可恢复任务时显示明确
返回动作，成功采用以 replace 返回列表，409 后旧建议保持只读采用锁并要求重新生成。

### 3.5 scenes 场景工作台

无 `scene_id` 时是单列 grid：筛选面板 → 场景概况（剧情进度 + 健康四维）→ 批量工具条 →
场景卡列表 → 分页。选中 Scene 后转为双栏：左列 68fr 保留主列表，右列 32fr 渲染
`<details class="workspace-rail">` 详情面板。详情面板始终提供「返回列表」，字段分区为：基本信息（标题/叙事标签/
状态/来源）→ 创作要点（目标/核心冲突/情感节奏/必须发生/禁止发生/视角人物）→ 章节与来源
（章节映射/来源注意/待处理/正文范围/重叠摘要）→ 吸底操作行（保存为 primary 并显示已保存/待保存状态，当前待办为次，合并/拆分收入「更多」）。

## 4. 逐区域标准

### 4.1 subnav（主规范 §5.5）

- 文字 tab + 底部 2px `--line-accent` 墨线指示；激活 `--text-primary` 600，未激活
  `--text-secondary`；Editorial 药丸覆写保留为材质层。
- 可点项一律 `button type="button"` 并按当前项设置 `aria-current="page"`；场景页不再保留
  非可点 span 例外。
- scenes 窄屏将四标签改为等宽四列，操作组移出 `.subnav` 行，保证入口完整可见。

### 4.2 story 总览时间线（历史版本）

- 版本条目：版本号/时间（`--text-xs` mono tertiary）+ 标题（条目标题档）+「查看/采用为
  新版本」`.btn-text`；当前版本用左侧 3px `--line-accent` 墨线标记，不用色块。
- AI 预览编辑器与当前版本只读卡之间必须有明确的「未采用预览」边界：`--accent-soft` 底 +
  一句人话说明 +「采用/放弃」操作行（§5.9 反馈闭环）。

### 4.3 arcs / threads 表格（§5.4）

- 表头 `--text-xs` + `--tracking-wide` secondary；行 padding 紧凑档；操作列右对齐
  `.btn-text`/ActionMenu。
- 状态列用文字 + 色点，来源列用中性描边胶囊；不新增彩色 pill。

### 4.4 scenes 筛选 + 列表 + 详情

- 筛选面板 `aria-label="场景筛选"`：默认收起为一行摘要（已启用条件数 + 未应用修改），高级诊断筛选
  （workflow_id 等）收进 `<details>` 次级入口，不常驻首屏（§5.10）。
- 场景卡列表行：选择 checkbox + 主按钮（meta/标题/摘要/正文范围）+ 健康 chip + ActionMenu。
  meta 五段改为 `--text-xs` tertiary + `·` 分隔；摘要升至 `--text-sm`（修 §2-8）；健康 chip
  改为文字 + 色点。重叠提示用 `--warning` 色点 + 文字，不整行染色。
- 剧情进度 chip 补四段配色：当前 `--accent`、后续 secondary、已写过 success、未定位
  quaternary，均用文字 + 色点形态（修 §2-9）。
- 健康四维条（未复核/未关联章节/缺设定/待整理）：计数用 mono；「待整理」属「需人工处理」
  语义，允许朱红计数角标（§2 朱红白名单第 2 条），其余三维用中性色。
- 剧情进度与健康四维共用「场景概况」`<details>`：桌面端展开完整内容，窄屏默认
  收起为一行摘要；摘要优先当前已应用条件，否则显示数量最多的待办，不改变任何筛选语义。
- 详情面板：label/控件/helper 统一缩进链（§5.2）；视角人物使用名称搜索器，显示
  人物名 + 摘要 + 状态，内部仍保存稳定 ID；不可用旧引用保留为「不可用人物」并允许清除；
  「补全设定」跳转的聚焦目标 id 修正为实际渲染 id（修 §2-2）。
- 详情长表单用原生 `fieldset/legend` 区分「基本信息」和「创作要点」，「章节与来源」为独立语义节；
  顶部始终可返回列表，底部操作栏在详情滚动区内吸底。保存按钮以「已保存 / 保存修改 / 保存中」说明真实状态，
  未修改时禁用；当前待办留在操作栏，合并/拆分收入向上展开的「更多」菜单。未保存时只允许继续编辑或保存，
  待办和结构操作禁用；返回、Esc 或切换仍须先确认。
- 桌面详情栏仅在已选 Scene 时渲染；未选列表不保留空占位列。选中、后退、前进和刷新
  继续以 URL `scene_id` 为恢复依据，详情栏的项目级折叠偏好不变。
- 融合/拆分影响预览：raw JSON 表格化——章节映射变化渲染为「第 N 章 → 场景名」行列表，
  字段变化渲染为「字段 / 原值 / 新值」三列；技术细节折叠（修 §2-3）。

### 4.5 批量操作条（§5.10）

- 零选择时不渲染批量条；勾选后才在列表顶部出现（非浮动条）：「已选 N」+ 操作组 + 退出。
- 单选时只保留该 Scene 的真实主动作，至少双选后才显示机械合并和 AI 融合；同类多选使用对应批量动作，混合多选按待办类型
  展示数量和动作，一次只处理一组，未处理组保持选中。
- 结构类“待整理”允许作者标记为“无需整理”，并在更多菜单提供“恢复整理提醒”；该裁决不
  连带清除正文定位或融合建议。
- 「待处理」心智统一：`.scene-fusion-queue` 横幅与 world 审核队列同语言——「N 条场景建议
  待处理」+ 朱红计数 + 主操作「逐条处理」，「忽略」为 `.btn-text` 三级操作（replacement 类
  不可忽略的规则保留）。横幅 `role="status"` 保留。

## 5. 状态覆盖清单

| 状态 | 标准要求 |
|---|---|
| 空态 | story 无版本时只显示「先确定故事方向」主操作区，提供 AI 可编辑预览与手工创建，不渲染空历史卡；arcs/threads 保留已有引导；scenes 初始空态提供「从正文整理场景」「AI 创作细纲」，筛选无结果时提供「清除筛选」 |
| 加载 | 四个子视图首次进入由共享 `.loading-skeleton` 覆盖；scene 非首屏刷新使用 `.scene-workbench-refresh[role="status"]`，保留当前内容并以原生 `inert` 暂停旧控件 |
| 失败 | 统一使用一句作者可理解的话和原位重试；scene 非首屏刷新失败显示 `.scene-workbench-refresh[role="alert"]` 并保留当前内容，首次加载失败继续使用现有错误卡 |
| AI 创作细纲生成中 | 入口按钮 busy 文案 + disabled；四个结构层统一在 `.outline-task-status` 中使用 `WorkflowProgressCard`，范围和可用操作位于展开卡内；完成后 `.outline-preview-ready`「查看并采用」→ 预览模态；前置校验失败（无故事总览当前版本）toast + 跳回 story-outline 的现有行为保留 |
| 从正文整理场景 | busy 文案「整理中...」保留；模态表单（章节范围 + 高质量 checkbox）+ 覆盖确认 `confirmAsync` 保留；去掉对后端 warning 的正则文本修补，改为后端返回人话文案（执行时核实后端契约）；跨会话恢复保留 |
| 伏笔揭示归并 | 见 §3.4：默认展开反转 + 深链滚动/高亮 + 归属操作行内 toast |
| 融合建议队列 | 横幅 `role="status"` 保留；逐条处理按类型分流（replacement→替换检查含「编辑后采用」/keep_separate→确认/merge→融合草稿）保留；废弃原场景二段确认保留 |
| 场景详情保存 | 无修改时显示并禁用「已保存」，有修改时改为「保存修改」，操作栏在详情滚动区内始终可达；未保存或保存中时禁用当前待办与「更多」结构操作，保存中同时禁用字段与离开；成功刷新当前场景，失败保留草稿并在详情内显示人话错误；切换场景、筛选、分页、模式、作品或路由以及窄屏关闭均不得静默丢弃未保存修改 |
| 窄屏 | JS 断点为 760px；无消费者的 `is-narrow` class 已删除；抽屉保持 `role="dialog"` + Esc + 焦点管理 + 可点遮罩 |

## 6. 响应式行为（四档）

- **Desktop ≥1440**：未选 Scene 时列表单列通栏；选中后双栏 68/32，rail 可收起至
  `--workspace-rail-collapsed:44px`；工作台不限宽。
- **Laptop 1100–1440**：默认形态，同 Desktop。
- **Tablet 760–1100**：rail 收窄且默认收起（`:has()` 塌缩现有行为保留）；筛选面板收为一行摘要。
- **Mobile ≤760**：单栏（grid 退化为 block 现有行为）；详情使用模态抽屉；场景概况默认收起为摘要；信息推进节点摘要
  换到类型/章节下一行，未归类计划与归属下拉改为单列；
  健康四维条 2 列、small 说明换行（spacing 契约已锁定，见 §7）；隐藏 `.scene-secondary-action`；
  触控目标 ≥42/44px，`.scene-progress-filter` 等 36px 控件抬升（修 §2-8）；390px 无页面级
  横向溢出（`e2e/scene-workbench.spec.js` 的窄屏详情与长列表用例覆盖）。
- 断点现已合并为 760px；后续调整必须同步 JS、CSS 与契约测试。

## 7. 必须保留的契约

**#id（scene）**：`#scene-filter-{q,chapter-from,chapter-to,status,source,needs-review}`、
`#scene-filter-{workflow-id,boundary-status,phase,confidence-band,phase1a-fallback}`、
`#scene-detail-{title,narrative_tag,status,source,goal,core_conflict,emotional_beat,must_happen,
must_not_happen,pov_character_id}`、`#scene-merge-reference-picker`、`#scene-split-{chapter-index,
partition,setup-error}`、`#scene-auto-extract-{start,end,high-quality}`、`#scene-fusion-{field}`、
`#scene-split-{0,1}-{field}`。
**#id（outline 其他）**：`#outline-filter-{status,source,needs-review,workflow-id}`、
`#outline-thread-information`、`#outline-layer-{mode,instruction,start,end}`、story 预览 7 个 id
（`#story-outline-intro-title` 等）、手工编辑 `#story-outline-manual-{title-input,premise,tone,engine,ending,markdown}`、`#create-thread-{name,type,desc}`、`#edit-thread-{name,type}`、
`#create-arc-{name,start,end,desc}`。

**data-action（scene）**：`nav-story-outline/nav-arcs/nav-threads/nav-scenes`、
`set-scene-view-mode[data-mode]`、`ai-create-planned-scene`、`scene-auto-extract`、
`show/dismiss-fusion-suggestions`、`retry-scene-workbench`、`toggle-advanced-scene-filters`、
`apply/reset-scene-filters`、`filter-progress-segment[data-segment]`、`filter-health[data-id]`、
`toggle-visible-fusion-selection`、`handle-selected-context-actions`、`start-selected-merge`、
`start-ai-fusion-draft`、`toggle-fusion-selection`、`select-workbench-scene`、
`handle-scene-health[data-health]`、`open-overlap-scene`、`edit-workbench-scene`、
`assign-unassigned-chapter[data-chapter]`、`prev/next-scene-page`、`close/save-scene-detail`、
`start-merge-scene`、`start-split-scene`；菜单项 `open-writing-scene/mark-scene-unreviewed/
restore-scene-organize/move-scene-to-history` 等；模态内 `filter-draft-review-differences`、`cancel/confirm-fusion-
deprecation`、`dismiss/cancel-scene-auto-extract`。
**data-action（outline）**：`create-thread/create-arc`、`ai-create-plot-thread/ai-create-outline-arc`、
`analyze-outline`、`plot-structure-auto-extract`、`apply/reset-outline-structure-filters`、
`retry-outline-load`、`nav-scenes`、`edit/mark-arc-reviewed/mark-thread-reviewed/delete-arc|thread`、`bulk-toggle-all/
bulk-toggle-one/bulk-run/bulk-clear`、`prev/next-outline-structure-page`、story 的
`edit/generate/reload/cancel/dismiss/apply/discard/view/restore-story-outline-*`、`close-story-outline-editor`、
`save-story-outline-revision`、`discard-story-outline-draft`、AI 卡
`cancel/dismiss-outline-analysis`、`view-outline-generate-preview`。

**语义 class**：`.subnav/.subnav-item/.active`、`.scene-workbench/.scene-workbench__organize/
.scene-workbench-list/.scene-workbench-row`、`.scene-fusion-queue`、`.scene-fusion-toolbar`、
`.scene-health-bar/.scene-health-filter/.scene-health-count-note`、`.scene-progress-panel/
.scene-progress-chip--{segment}`、`.scene-management-filters`、`.workspace-rail.scene-detail-rail`、
`.outline-information-progress/-timeline/-preview-section`、`#outline-thread-information` 内的
`outline-preview-section`、`.data-table.table-card-list`、`.outline-task-status`。
**注意**：`.scene-cockpit-switcher__item` 属写作页副驾驶的 Scene 快速切换区
（selectors.js `writingSceneLabel`），**不属于本模块，不得在本页使用或改动**。

**role / 可访问名称**：`aria-current="page"`（subnav 当前项）、`aria-label="场景筛选"/"场景
操作"/"场景浏览模式"/"剧情进度"/"场景批量操作"/"结构资产筛选"`、`aria-label="场景正文范围
(/重叠)"`、移动详情 `role="dialog"` + `aria-modal="true"`、信息推进区 `tabindex="-1"` +
`aria-labelledby="outline-thread-information-title"`、`role="status"`（融合队列、骨架）、
`role="alert"`（错误态与保存失败）、`role="note"`（健康去重说明）、ActionMenu trigger
`aria-label="{标题}的更多操作"`。改任何名称前全局 grep 同步
e2e 的 `getByRole({name})`。

**间距 token 契约（`tests/sceneWorkbenchSpacing.test.js:9-42` 正则断言）**：
`.outline-scene-layout > .outline-toolbar` 的 `gap: var(--space-2)` + `padding: var(--space-2)
var(--space-3)`；`.scene-management-filters/.scene-fusion-toolbar/.scene-health-filter/
.scene-workbench-row` 四处 `padding: var(--space-3) var(--space-4)`；`@media (max-width:720px)`
内 `.scene-health-filter` grid `minmax(0,1fr) auto` 且 `small` 换行 `grid-column:1/-1;
margin-left:0`；`.scene-health-count-note` 的 `margin:0` + `padding-inline: var(--space-4)`。
执行字号/密度修正（§2-8）时不得破坏这些断言；断点合并 760px 时同步更新测试。

**Editorial 主题作用域**：修 §2-1 时把三段 `[data-workspace-view="scene"]` 规则改锚
outline/scenes 可判定条件（如 `.outline-scene-layout` 存在性或 view+subView 复合属性），
并同步 `tests/editorialTheme.test.js:46` 的视图清单（执行时核实改法）。

## 8. 验收标准与验证命令

**验收标准**：
- §2 问题清单逐条关闭或显式标注「本轮不处理 + 理由」；
- 四子视图状态三件套（空/加载/失败）齐备，融合队列、AI 细纲、正文整理、伏笔归并的
  状态反馈符合 §5；
- 390px 无页面级横向溢出；subnav 键盘可达；窄屏抽屉满足对话框语义；
- 不暴露 raw JSON / 裸 ID；「待处理」计数语义与朱红白名单一致；
- §7 全部契约钩子保留（重命名视为破坏性变更，需同步全部 e2e/vitest）。

**验证命令**（均在 `frontend-console/` 下执行）：

```bash
# 单元/契约（间距 token、subnav 可访问性、editorial 主题、骨架屏）
npx vitest run tests/sceneWorkbenchSpacing.test.js tests/subnavAccessibility.test.js \
  tests/editorialTheme.test.js tests/loadingSkeleton.test.js

# 功能 e2e（subnav 归位与键盘往返、场景工作台全流程、伏笔揭示归并、threads/arcs CRUD）
npx playwright test --config=playwright.functional.config.js \
  e2e/outline-scenes.spec.js e2e/scene-workbench.spec.js \
  e2e/outline-foreshadowing-reveal.spec.js e2e/outline-threads-arcs.spec.js

# 视觉基线：三主题 × story/arcs/threads 共 9 张快照（scenes 子视图当前不在基线范围，
# visual-outline.spec.js:8 明示；本轮修复后应评估把 scenes 纳入基线）
npx playwright test --config=playwright.visual.config.js e2e/visual-outline.spec.js
# 基线更新（仅在确认视觉变更为预期后）
npm run test:e2e:visual:update -- e2e/visual-outline.spec.js

# 收尾门禁
make docs-check BASE_REF=origin/main
```
