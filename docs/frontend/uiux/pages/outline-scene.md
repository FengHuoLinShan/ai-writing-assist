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
- **主要摩擦（当前）**：工作台密度偏高但反馈层级不统一；部分操作暴露 raw JSON / 内部 ID；
  「待处理」心智（融合建议队列）与 world 审核队列的视觉语言未对齐；窄屏抽屉可达性差。
- **验证方式**：e2e 任务流（整理场景→融合→补全→去写作）完成率、场景字段补全率、融合
  建议处理/忽略比例（当前为产品假设，无真实数据）。

## 2. 现状问题清单（按严重度排序）

1. **Editorial 主题的 scene 作用域整体失效**：`editorial-theme.css:313-317`（「06 景」页眉标记）、
   `:1084`（工作台顶线）、`:1090-1092`（rail 墨色 inset）锚定 `[data-workspace-view="scene"]`，
   但顶层 scene 路由已归一化为 outline（`router.js:337-343`），场景工作台永远显示「05 纲」，
   三段规则为死代码；`tests/editorialTheme.test.js:46` 仍把 "scene" 留在视图清单里固化漂移。
2. **「补全设定」聚焦目标 id 拼错**：`useSceneWorkbench.js:321-326` 的 fieldMap 指向
   `scene-detail-conflict/must/must-not`，实际渲染 id 是 `scene-detail-core_conflict/must_happen/
   must_not_happen`（`SceneWorkbenchView.vue:295-298`）——除 goal 外 `getElementById` 全部落空，
   `?.focus()` 静默无效，用户点「补全设定」无反馈。
3. **合并/拆分影响预览暴露 raw JSON**：`sceneModalController.js:88-89` 直接
   `<pre>JSON.stringify(chapter_mapping_change / field_changes)`；拆分预览摘要同样机器化
   （`:474-477`）。违反 AGENTS.md「不暴露 raw ID、JSON」与主规范 §0 清晰度优先级。
4. **窄屏断点不一致**：JS `window.innerWidth < 720`（`useSceneWorkbench.js:74`，resize 监听 :509-511）
   vs CSS `@media (max-width: 760px)`（`.scene-workbench` 响应式规则）——边界值时 grid 已塌成 block，
   但 `narrow=false` 仍渲染右栏 rail 而非抽屉。
5. **窄屏详情抽屉不是对话框**：`SceneWorkbenchView.vue:135` 为裸 div——无 `role="dialog"`/
   `aria-modal`、无 Esc 关闭、无焦点管理，唯一出口是「关闭」按钮（:301）；遮罩用
   `box-shadow: 0 0 0 100vmax`（`.scene-detail-panel` 窄屏规则）实现且不可点。
6. **信息推进区（伏笔揭示归并产物）完全无样式 + 默认展开逻辑反转**：
   `.outline-information-progress/-timeline/-node/-unassigned/-preview-section` 在全部 CSS 中零命中，
   叙事时间线退化为默认 `<ol>`；且 `<details :open="plans.length === 0">`
   （`OutlineThreadsTab.vue:135`）——有内容的剧情线默认折叠、空的反而展开；`?information=`
   深链参数设置后无人消费（全仓库 grep 无 `query.get("information")`），不滚动不高亮。
7. **场景页 subnav 双事实源 + 信息层级拥挤**：`SceneWorkbenchView.vue:4-7` 与
   `OutlineHeader.vue:9-12` 各写一份四标签文案；场景页一行挤 4 个导航项 + 模式 toggle +
   2 个 AI 操作 + dedup 插槽（:3-17），`.subnav` 横向滚动（`styles.css` 的 `.subnav` 规则）在窄屏会把
   操作区裁出视口；scene 页无标题/计数 header（页面标题只在 topbar `#topbar-module`）。
8. **密度与字号低于主规范矩阵**：行 meta 11px 五段无分隔（`styles.css` 的 scene 列表 meta 规则）、
   摘要 12px、健康 chip 11px、健康条 small 10px、分页信息 12px；`.scene-progress-filter`
   min-height 36px（:6512）低于 44px 触控基准且不是 `.btn`，editorial 窄屏触控抬升规则
   （`editorial-theme.css:1294-1303`）覆盖不到。
9. **剧情进度 chip 无分段配色**：模板输出 `scene-progress-chip--{segment}`
   （`SceneWorkbenchView.vue:101`），CSS 只有基类（`styles.css` 的 `.scene-progress-chip` 规则）——
   当前/后续/已写过/未定位四态同色，热点模式失去分段辨识度。
10. **视角人物字段是裸 ID 文本框**：SceneDetailPanel 用 free-text input 收 `pov_character_id`
    （`SceneWorkbenchView.vue:304`），直接向用户暴露内部 ID 心智模型。
11. **状态覆盖缺口**：story/arcs/threads 无视图内加载态（靠 island 预取，期间停留旧内容或
    白屏）；scene 列表空态（`SceneWorkbenchView.vue:121`）无 CTA；scene 非首屏刷新无
    subtler 加载指示，只靠 toast 报错（`useSceneWorkbench.js:161-163`）。
12. **AI 进度卡三种范式并存**：threads/arcs 的 `.outline-toolbar-status` 三卡横排
    （`OutlineView.vue:22-29`）、scenes 的 `[data-outline-generate-slot]` + 独立 auto-extract 卡、
    story 的内嵌 WorkflowProgressCard——同一产品区进度反馈位置/样式不统一。
13. **`is-narrow` class 是死钩子**：`SceneWorkbenchView.vue:47` 设置但全仓库 CSS/测试无
    `.is-narrow` 规则。
14. **组件归属错位（架构性说明，非视觉 bug）**：场景工作台组件在 `vue/views/scene/`
    （`SceneWorkbenchView.vue`、`useSceneWorkbench.js`、`sceneModalController.js`、
    `sceneAutoExtractManager.js` 等），但路由属 `outline/scenes`（`router.js:337-343` 将
    `view==="scene"` 归一化，`subView` 转 `?scene_id=`），由 `OutlineView.vue:7-18` 分派渲染。
    e2e 已锁定该事实（`e2e/outline-scenes.spec.js:29` 断言侧边栏无 `data-view="scene"`、
    `e2e/scene-workbench.spec.js:67` 断言场景页无 `#workspace-header`）。执行本规范时**不得**
    为消除错位而移动目录或改动路由——属目录归属整理时另行处理。

## 3. 目标布局与信息层级

### 3.1 四个子视图共享骨架

- 统一 `OutlineHeader` 单事实源：`.subnav` 四标签 + `.view-header__tail`（标题/计数/项目名 +
  按子视图切换的操作组）。**scenes 子视图撤掉自带 subnav，改用同一 OutlineHeader**（消除
  §2-7 双事实源）；「普通/热点」toggle 与「AI 创作细纲」「从正文整理场景」作为 scenes 的
  操作组进入 tail，主操作（每屏至多一个 `.btn-primary`）为当前模式下的第一动作。
- 信息层级：subnav（Primary 导航）→ 操作组（Primary 动作 ≤1）→ AI 进度卡（若有，统一
  WorkflowProgressCard 单一范式，位置固定于 header 正下方）→ 状态三件套 → 主内容。

### 3.2 story 故事总览

单列纵向卡片流，保持现状结构：介绍卡（主操作：编辑为新版本 / AI 生成）→ 任务进度卡 →
AI 预览编辑器（创作核心 4 文本域 + 剧情线/故事推进/待决定问题三个可排序列表）→ 当前版本
只读卡 → 历史版本列表。层级靠字阶与留白分节，不新增卡片套壳（主规范 §5.3）。

### 3.3 arcs 篇章

筛选条（默认收起为一行摘要，主规范 §5.10）→ 批量工具条（选中时出现，附着列表顶部）→
`.data-table` 七列 → 分页。行选中态用 `--bg-active` + 左侧 `--line-active`（§5.4）。

### 3.4 threads 剧情线（含伏笔揭示归并）

表格区同 arcs 结构；下方「信息推进」区是本页独有的**叙事时间线**，可读性层级：

1. 剧情线名 + 信息运动计数（区块标题档 `--text-md` 600）；
2. movement 分组节点（条目标题档 `--text-base` 600）；
3. 节点 badge「暗示/兑现」「局部/完整揭示」——用文字 + 6px 语义色点，不用彩色 pill（§5.8）；
4. 章节号与内容摘要（辅助说明档 `--text-sm` secondary）；
5. 时间线纵向用 1px `--line-subtle` 导轨 + 节点圆点串联，不画卡片框。

默认展开规则反转：有信息运动的剧情线默认展开、空的折叠（修 §2-6）；`?information=`
深链落地为滚动定位 + 对应 `<details>` 展开 + 短暂 `--accent-soft` 高亮。「未归入剧情线」
details 保留就地归属下拉，归属操作完成后行内 toast 确认。

### 3.5 scenes 场景工作台

双栏 grid：左列（68fr，主对象）筛选面板 → 剧情进度面板（热点模式专属）→ 健康四维条 →
批量工具条 → 场景卡列表 → 分页；右栏（32fr）`<details class="workspace-rail">` 详情面板。
主对象占比符合内容优先布局契约（64–68%）。详情面板字段分区：基本信息（标题/叙事标签/
状态/来源）→ 创作要素（目标/核心冲突/情感节奏/必须发生/禁止发生/视角人物）→ 映射与来源
（章节映射/来源注意/待处理/正文范围/重叠摘要）→ 操作行（保存为 primary，合并/拆分为次）。

## 4. 逐区域标准

### 4.1 subnav（主规范 §5.5）

- 文字 tab + 底部 2px `--line-accent` 墨线指示；激活 `--text-primary` 600，未激活
  `--text-secondary`；Editorial 药丸覆写保留为材质层。
- 可点项一律 `button type="button"`，仅当前项允许非可点 span + `aria-current="page"`
  （subnavAccessibility.test.js 契约）；统一 OutlineHeader 后场景页的 span 例外随双事实源
  消除而退役，契约测试同步更新。
- 窄屏横向滚动保留，但操作组移出 `.subnav` 行，保证四个导航项始终完整可见（修 §2-7）。

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

- 筛选面板 `aria-label="场景筛选"`：默认收起为一行摘要（「N 个筛选生效」），高级诊断筛选
  （workflow_id 等）收进 `<details>` 次级入口，不常驻首屏（§5.10）。
- 场景卡列表行：选择 checkbox + 主按钮（meta/标题/摘要/正文范围）+ 健康 chip + ActionMenu。
  meta 五段改为 `--text-xs` tertiary + `·` 分隔；摘要升至 `--text-sm`（修 §2-8）；健康 chip
  改为文字 + 色点。重叠提示用 `--warning` 色点 + 文字，不整行染色。
- 剧情进度 chip 补四段配色：当前 `--accent`、后续 secondary、已写过 success、未定位
  quaternary，均用文字 + 色点形态（修 §2-9）。
- 健康四维条（未复核/未关联章节/缺设定/待整理）：计数用 mono；「待整理」属「需人工处理」
  语义，允许朱红计数角标（§2 朱红白名单第 2 条），其余三维用中性色。
- 详情面板：label/控件/helper 统一缩进链（§5.2）；`pov_character_id` 改人物选择器（显示
  人物名，内部存 ID），不再裸 ID 输入（修 §2-10）；「补全设定」跳转的聚焦目标 id 修正为
  实际渲染 id（修 §2-2）。
- 融合/拆分影响预览：raw JSON 表格化——章节映射变化渲染为「第 N 章 → 场景名」行列表，
  字段变化渲染为「字段 / 原值 / 新值」三列；技术细节折叠（修 §2-3）。

### 4.5 批量操作条（§5.10）

- 选中时出现在列表顶部（非浮动条）：「已选 N」+ 操作组（上下文动作/合并/AI 融合）+ 退出。
- 单选时上下文按钮使用该 Scene 的真实动作；同类多选使用对应批量动作；混合多选按待办类型
  展示数量和动作，一次只处理一组，未处理组保持选中。
- 结构类“待整理”允许作者标记为“无需整理”，并在更多菜单提供“恢复整理提醒”；该裁决不
  连带清除正文定位或融合建议。
- 「待处理」心智统一：`.scene-fusion-queue` 横幅与 world 审核队列同语言——「N 条场景建议
  待处理」+ 朱红计数 + 主操作「逐条处理」，「忽略」为 `.btn-text` 三级操作（replacement 类
  不可忽略的规则保留）。横幅 `role="status"` 保留。

## 5. 状态覆盖清单

| 状态 | 标准要求 |
|---|---|
| 空态 | 四子视图统一 `.empty-state` + 引导句 + `.empty-state-cta`：story 无版本时 CTA「AI 生成故事总览」；arcs/threads 已有 CTA 保留；scenes 空态补「AI 创作细纲」「从正文整理场景」双 CTA（修 §2-11） |
| 加载 | scenes 首屏骨架保留；story/arcs/threads 补 `.loading-skeleton` 视图骨架，消除预取期间白屏；scene 非首屏刷新给列表加 `.loading` 行内指示，不清空现有内容 |
| 失败 | 统一 `.error-card`：一句人话 + 重试；scenes 现有 `role="alert"` 错误态保留并对齐 error-card 视觉 |
| AI 创作细纲生成中 | 入口按钮 busy 文案 + disabled；进度卡统一 WorkflowProgressCard 范式（修 §2-12），可取消/关闭；完成后 `.outline-preview-ready`「查看并采用」→ 预览模态；前置校验失败（无故事总览当前版本）toast + 跳回 story-outline 的现有行为保留 |
| 从正文整理场景 | busy 文案「整理中...」保留；模态表单（章节范围 + 高质量 checkbox）+ 覆盖确认 `confirmAsync` 保留；去掉对后端 warning 的正则文本修补，改为后端返回人话文案（执行时核实后端契约）；跨会话恢复保留 |
| 伏笔揭示归并 | 见 §3.4：默认展开反转 + 深链滚动/高亮 + 归属操作行内 toast |
| 融合建议队列 | 横幅 `role="status"` 保留；逐条处理按类型分流（replacement→替换检查含「编辑后采用」/keep_separate→确认/merge→融合草稿）保留；废弃原场景二段确认保留 |
| 窄屏 is-narrow | 断点 JS/CSS 统一（随主规范 §6 合并到 760px 时同步改）；`is-narrow` class 死钩子删除或实际接线（修 §2-13）；抽屉补 `role="dialog"` + Esc + 焦点管理 + 可点遮罩（修 §2-5） |

## 6. 响应式行为（四档）

- **Desktop ≥1440**：双栏 68/32，rail 可收起至 `--workspace-rail-collapsed:44px`；工作台不限宽。
- **Laptop 1100–1440**：默认形态，同 Desktop。
- **Tablet 760–1100**：rail 收窄且默认收起（`:has()` 塌缩现有行为保留）；筛选面板收为一行摘要。
- **Mobile <760**：单栏（grid 退化为 block 现有行为）；详情改全屏抽屉（修 §2-5 后达标）；
  健康四维条 2 列、small 说明换行（spacing 契约已锁定，见 §7）；隐藏 `.scene-secondary-action`；
  触控目标 ≥42/44px，`.scene-progress-filter` 等 36px 控件抬升（修 §2-8）；390px 无页面级
  横向溢出（`e2e/scene-workbench.spec.js:703-731` 覆盖）。
- 断点合并：本页 720px 随主规范 §6 全局合并到 760px 时一次性改 JS + CSS + 契约测试。

## 7. 必须保留的契约

**#id（scene）**：`#scene-filter-{q,chapter-from,chapter-to,status,source,needs-review}`、
`#scene-filter-{workflow-id,boundary-status,phase,confidence-band,phase1a-fallback}`、
`#scene-detail-{title,narrative_tag,status,source,goal,core_conflict,emotional_beat,must_happen,
must_not_happen,pov_character_id}`、`#scene-merge-reference-picker`、`#scene-split-{chapter-index,
partition,setup-error}`、`#scene-auto-extract-{start,end,high-quality}`、`#scene-fusion-{field}`、
`#scene-split-{0,1}-{field}`。
**#id（outline 其他）**：`#outline-filter-{status,source,needs-review,workflow-id}`、
`#outline-thread-information`、`#outline-layer-{mode,instruction,start,end}`、story 预览 7 个 id
（`#story-outline-intro-title` 等）、`#create-thread-{name,type,desc}`、`#edit-thread-{name,type}`、
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
`edit/generate/reload/cancel/dismiss/apply/discard/view/restore-story-outline-*`、AI 卡
`cancel/dismiss-outline-analysis`、`view-outline-generate-preview`。

**语义 class**：`.subnav/.subnav-item/.active`、`.scene-workbench/.scene-workbench__organize/
.scene-workbench-list/.scene-workbench-row`、`.scene-fusion-queue`、`.scene-fusion-toolbar`、
`.scene-health-bar/.scene-health-filter/.scene-health-count-note`、`.scene-progress-panel/
.scene-progress-chip--{segment}`、`.scene-management-filters`、`.workspace-rail.scene-detail-rail`、
`.outline-information-progress/-timeline/-preview-section`、`#outline-thread-information` 内的
`outline-preview-section`、`.data-table.table-card-list`、`.outline-toolbar-status`。
**注意**：`.scene-cockpit-switcher__item` 属写作页副驾驶的 Scene 快速切换区
（selectors.js `writingSceneLabel`），**不属于本模块，不得在本页使用或改动**。

**role / 可访问名称**：`aria-current="page"`（subnav 当前项）、`aria-label="场景筛选"/"场景
操作"/"场景浏览模式"/"剧情进度"/"场景批量操作"/"结构资产筛选"`、`aria-label="场景正文范围
(/重叠)"`、`role="status"`（融合队列、骨架）、`role="alert"`（错误态）、`role="note"`（健康
去重说明）、ActionMenu trigger `aria-label="{标题}的更多操作"`。改任何名称前全局 grep 同步
e2e 的 `getByRole({name})`。

**间距 token 契约（`tests/sceneWorkbenchSpacing.test.js:9-42` 正则断言）**：
`.outline-scene-layout > .subnav` 的 `gap: var(--space-2)` + `padding: var(--space-2)
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
