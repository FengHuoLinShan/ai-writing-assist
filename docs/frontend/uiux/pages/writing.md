# 写作编辑器 UI/UX 执行规范

> 路由：`writing` 工作台视图（`#workspace-content[data-workspace-view="writing"]`）。
> 唯一权威：本文件是 writing 页的页面级执行规范，遵循 `docs/frontend/uiux/design-standard.md`
>（下称主规范）的内容优先契约 §4、长正文排版 §3.2、Loading 归一 §5.9。
> 事实来源：`frontend-console/vue/views/writing/` 源码与 `e2e/writing.spec.js`、
> `e2e/visual-writing.spec.js`。所有行号以调研时点的源码为准，漂移时以源码为准并回改本文件。

## 1. 页面定位与目标画像

- **定位**：全产品停留时间最长的页面，是画像 A「安心继续创作」核心任务的承载页；也是唯一在全局
  顶栏拥有字数仪表盘（`#topbar-wordcount`）的路由（`vue/shell/components/Topbar.vue:14-18`）。
- **目标画像**：画像 A（长期创作的作家）。本页不为画像 B 服务；RP 用户走独立路径（见
  `pages/rp-experience.md`）。
- **用户任务与情绪收益**：作者打开本页时的心理状态是「继续写」，不是「管理作品」。页面必须让作者
  3 秒内确认：写到哪一章、上次保存是否安全、当前场景有哪些相关设定——然后立刻能开始打字。
- **用户会喜欢的理由**（对应 `user-personas.md` §画像 A）：
  - 写作时就地查看人物/地点/警报（副驾驶 rail），不离开当前思路；
  - 草稿三层保护（会话快照 + localStorage 备份 + 离开守卫），页面切换不丢稿；
  - AI 候选只进「待处理」，采用/拒绝由作者决定，不静默覆盖正文。
- **主要摩擦（现状）**：编辑器头部控件过密、保存失败无重试路径、切章节无加载反馈、
  移动端速记与桌面编辑器能力割裂。详见 §2。
- **验证方式**：e2e 场景化验收（§8）；「喜欢」为产品假设，待真实行为数据修正。

## 2. 现状问题清单（按严重度排序）

### P0 — 直接影响写作安全感

1. **保存失败无恢复路径**：`saveError` 只改徽标文案 + toast（`controllers/editorController.js:352-353`），
   `#writing-save-status` 徽标不可点击、无重试按钮；「已保留本地备份」对作者不可验证。
2. **正文加载无反馈**：`loadChapter` 期间无 skeleton/遮罩，切章节时旧正文残留到新数据到达
   （`controllers/editorController.js:184-220`）；`editorState.loadError`（:215）无任何组件消费，
   只在 toast 闪现。违反主规范 §5.9 Loading/Error 归一。
3. **保存徽标只读态语义错误**：徽标默认 `::before` 绿点（`writing-desk.css:69-76`），
   `saveBadgeClass` 无 readonly 分支（`components/WritingEditor.vue:141-145`），只读章节也显示绿色「已保存」观感。
4. **`visual-writing.spec.js:113` 测试债**：用例找按钮名「聚焦模式」，现 UI 文案为「进入专注」
   （`WritingView.vue:13`）/「专注模式」（`WritingEditor.vue:48`），全仓库无「聚焦模式」按钮——
   该视觉用例按现状必然失败，改文案前必须先解决。（已核实：2026-08 读源码确认。）

### P1 — 信息层级与视觉一致性

5. **编辑器头部三行拥挤**：标题组（19px 标题 + 两 chip）→ 主按钮行（发布 + 提示 + 3 个 details 菜单）
   → context 行（版本选择 + 冲突条，flex-basis 330px，`writing-desk.css:145-156`），桌面中栏内塞 10+ 控件；
   ≤760px 时 context 行再折行（desk:1642-1649），头部总高 >120px，稿纸首屏被压缩。
   证据：`WritingEditor.vue:3-57`、`writing-desk.css:97-156`。
6. **三层 CSS 重复/冲突 12 处**（结构层 `styles.css` → 主题层 `editorial-theme.css` → 页面层
   `writing-desk.css`，后者最后加载胜出）：
   - `.novel-editor` 三重定义（styles.css:2066-2085 → editorial-theme.css:749-760 → desk:196-211），
     **editorial 层对 `.novel-editor` 的覆写是死代码**（其 focus 红色顶线被 desk `border:0` 作废）；
   - `.writing-title-input` 三层（styles.css:2034-2064 → editorial:725-734 → desk:183-194），
     desk 与 editorial 的 focus 样式内容相同、重复定义；
   - `.writing-version-badge/.writing-save-badge`：styles.css:3799-3816 pill 造型被 desk:51-94 整体推翻；
   - `.chapter-row`/`.chapter-status`：styles.css:1957-2000（34px 行高、7px 圆形状态点）vs
     desk:489-521（40px、8px 描边「方形」但未重置 `border-radius:50%`，styles.css:1995——实际仍是圆形），
     draft 态背景色靠加载顺序决胜负（styles.css:1999 vs desk:509）；
   - `.writing-wordcount-bar` 对齐方向反转（styles.css:1890-1893 space-between vs desk:218-228 flex-start）；
   - `.writing-conflict-strip` 外边距方向反转（styles.css:2541-2545 `0 0 8px` vs desk:1019 `10px 0 0`）；
   - `.writing-tools-menu__body` 三处共管（styles.css:2528-2539 + 3818-3822、editorial:794、desk:338-344）；
   - `.scene-cockpit` 三层（styles.css:2669-2679 → editorial:795 → desk:557-560），
     `max-height` 在 styles.css:1859-1861 与 2675 重复定义；
   - `.outline-float-*` 双主题并存（styles.css:2442-2512 accent 蓝 vs desk:1106-1157 朱红）；
   - `.cockpit-tab` 激活色沿用基础层 accent 蓝（styles.css:2764-2767），desk 层未覆写
     `.cockpit-tab.active`——与页面朱红索引语言不一致（editorial-theme.css:493 有覆写，执行时核实其实际值）；
   - 专注模式双写：styles.css:2432-2440 `.novel-editor--focus`（max-width 760px）vs
     desk:1585-1601 `.focus-mode-active .writing-sheet`（860px），形成 860px 纸、760px 芯双层居中；
   - 移动端媒体查询分裂：同一组件移动态分散在 styles.css:6186-6189（600px）、desk:1626-1636（760px）、
     desk:597-622（rail 760px）三个断点两个文件。
7. **死样式/死 class**：`.writing-empty-hint`（4 处使用、全仓库 0 处 CSS 定义，裸文本 role=alert，
   `WritingView.vue:123`）、`.writing-empty-icon--warning`（`ChapterTree.vue:21`，无定义）、
   body `.force-desktop`（`useWritingWorkspace.js:1115`，无 CSS 规则，纯标记）、
   `.chapter-tree`（styles.css:4046，组件实际用 `.chapter-tree-card`）、
   `.writing-editor-buttons__group`（desk:124-143 无对应 DOM，现结构是 `__menus` + `__context`）、
   `.wc-bar-left/.wc-bar-right/.wc-divider`（styles.css:1881-1882/2109，无对应 DOM——执行时核实）。
8. **重复 id 隐患**：`#writing-conflict-strip` 有两个渲染源（`WritingView.vue:108` 与
   `WritingWorkflowBars.vue:58`），当前靠 `:show-conflict="false"` 硬编码回避（`WritingView.vue:128`）；
   打开开关即产生重复 id。
9. **候选采纳 UI 与正文抢层级**：`.writing-candidate-review-panel` 朱红边卡插在标题与正文之间
   （`WritingEditor.vue:84-95`），此时 textarea 只读但仅 `color: text-secondary`（desk:213-215）区分；
   采用/拒绝用原生 `confirm`（editorController.js:422,441），与全局 `confirmAsync` 模态体系混用。

### P2 — 响应式与模式完整性

10. **600–760px 断档 + 双断点体系**：JS `mobileMode` 阈值 600px（`useWritingWorkspace.js:157,1109`），
    CSS 布局断点 760/900/1099px；600–760px 区间用户得到「桌面编辑器 + 单列布局」。视口硬编码共 4 处
    （useWritingWorkspace.js:157,1109；WritingView.vue:241-242；SceneCockpit.vue:157 `innerHeight < 760`）。
11. **专注模式不完整**：仅隐藏两栏 rail + 居中稿纸；顶栏/view-header/字数条全部保留；无键盘快捷键、
    无状态持久化（`appState._focusMode` 仅存内存，useWritingWorkspace.js:288）；两个入口文案不一致
    （「进入专注」WritingView.vue:13 vs「专注模式」WritingEditor.vue:48）。
12. **移动速记能力割裂**：mobileMode 下丢失标题编辑（MobileQuickNote 无 title input，
    editorController.js:127-131 专门兜底）、无字数目标、无版本/冲突入口；「保存工作稿」按钮文案与桌面
    一致但语义是 `createIfMissing` 首存（useWritingWorkspace.js:706-708）；操作区现随工作区剩余高度
    布局并保持在移动底栏上方，不再重复硬编码底栏高度。
13. **密度断层**：正文 17px/1.9 宽松稿纸 vs 章节树 10-12px mono 与 copilot 10-13px 高密度索引，
    同屏对比强烈；章节树三层行内信息在 176px 最小 rail 宽下标题必然截断
    （省略号在 `.chapter-title-text`，styles.css:2020-2025）。
14. **details 菜单无障碍缺陷**：三个 `.writing-tools-menu` 与 `.writing-page-menu` 用原生 `<details>`，
    无点击外部关闭、无 `aria-expanded` 同步；弹层 `z-index:10`（styles.css:2530）低于移动端 sticky
    编辑器头 `z-index:15`（desk:1611），有叠层冲突风险。
15. **空态无插图/icon 体系**：三处空态齐全（ChapterTree.vue:25-28、WritingEditor.vue:59-61、
    SceneCockpit.vue:17-19,27）但均未使用 `.empty-state .empty-icon`。

## 3. 目标布局与信息层级

**三栏布局（桌面，≥1100px）**，grid 列宽 `minmax(176px,18fr) / minmax(0,64fr) / minmax(190px,18fr)`，
gap 20px（`styles.css:1819-1827`，变量 styles.css:114-118）：

```
┌──────────────────────────────────────────────────────────┐
│ Topbar（全局）：#topbar-chapter ｜ #topbar-wordcount 仪表盘 │
├──────────────────────────────────────────────────────────┤
│ view-header.writing-toolbar：写作 · 共 N 章 ［新建章节］▾  │
├─────────┬──────────────────────────────┬─────────────────┤
│ 章节树   │  编辑器（第一视觉焦点）        │  副驾驶          │
│ rail    │  · 编辑器头（标题+保存+版本）   │  SceneCockpit   │
│ (左,18fr)│  · 稿纸 .writing-sheet       │  (右,18fr,sticky)│
│         │  · 字数条                     │                 │
├─────────┴──────────────────────────────┴─────────────────┤
│ 浮窗层：OutlineFloat 抽屉 / 各模态                         │
└──────────────────────────────────────────────────────────┘
```

- **第一视觉焦点 = 正文编辑区**。章节树与副驾驶是「索引与参照」，视觉重量（字号、色对比、边框强度）
  必须低于稿纸。稿纸是页面唯一允许有独特构图的区域（顶 3px 墨线 + 朱红页边线，desk:162-211），保留。
- **主对象 64–68% 契约的落实**（主规范 §4，`docs/modules/14_frontend.md:149-158`）：中栏 64fr 即
  `--workspace-main-share:64fr`，左右 rail 各 18fr 且不低于 `--workspace-rail-left-min:176px` /
  `--workspace-rail-right-min:190px`（styles.css:114-118）。不得为「呼吸感」加宽 rail 或压缩中栏；
  稿纸内行宽另受 §4.2 排版契约约束（32-40 中文字符）。
- **专注模式**：进入后两栏 rail `display:none`、稿纸单列居中（≤860px 纸宽）、编辑器 min-height 82vh；
  顶栏保留（字数仪表盘是全局契约），view-header 保留但折叠为单行。
  目标态修正：统一双写断点（§2-6 第 11 条），入口文案统一为「专注模式/退出专注」，
  状态持久化到 sessionStorage（沿用 rail 开合的 `workspace-rail:{pid}:writing:*` 键族模式，
  `WritingView.vue:235-248`）。（快捷键是否增加为产品决定，执行时核实。）
- **信息层级**：Primary = 稿纸正文 + 主按钮「发布」（每屏唯一 primary）；Secondary = 章节树当前章、
  副驾驶当前 tab、保存状态；Tertiary = 版本条、字数条、菜单项。层级靠字阶与留白，不新增卡片边框
  （主规范 §0、§4 分隔优先级）。

## 4. 逐区域标准

### 4.1 章节树 rail（左，`aside.writing-tree-rail`，aria-label="章节"）

- 结构：`#writing-tree-container` → `ChapterTree.vue`（`.card.chapter-tree-card`：头部
  `.chapter-tree-header`（折叠 toggle + 上/下章/新建）→ `.chapter-tree-list`（按场景分组
  `.scene-tree-node`）→ 底部批量工具栏）。
- 视觉：rail 面板 = paper-raised + `--line-subtle`，无阴影（主规范 §5.3）；当前章 =
  `--bg-active` + 左侧 `--line-active`（3px 朱红），与全局选中态一致。
- 字阶：章节标题 = 条目标题档（`--text-base` 14/600）为上限；章号/字数 = 元数据档
  （`--text-xs` 11 mono，`--tracking-wide`）。现状 12px 标题/10px 字数（desk:489-538）低于
  主规范字阶下限 11px，执行时向 `--text-xs/--text-sm` 归并；rail 收窄到 176px 时允许标题截断
  省略号，但必须保留完整 title 提示。
- 状态点：章状态用文字 + 6px 色点（主规范 §5.8），消除 §2-6 圆形/方形未重置的冲突；
  draft 态背景色只能有一处定义。
- 空态：「尚无章节 + 创建第一章」（ChapterTree.vue:25-28）复用 `.empty-state` + `.empty-state-cta`
  （主规范 §5.9）；列表加载失败保留 rail 内 `role=alert`，样式归并入 `.error-card` 基准。
- 映射主规范：§5.3 Card、§5.8 状态点、§5.9 Empty/Error。

### 4.2 编辑器（中栏，`main#writing-editor-container`）

**编辑器头**（`.writing-editor-header`，WritingEditor.vue:3-57）：

- 收敛为两行：第一行 = `#writing-chapter-title` + `#writing-version-info` + `#writing-save-status`
  + 主按钮 `#btn-publish`；第二行 = context 插槽（`#writing-versions-container` 版本条 +
  `#writing-conflict-strip` 冲突条）。三个 details 菜单（工作稿与版本 / AI 写作助手 / 更多）保留，
  但弹层样式收敛到单一权威层（消除 §2-6 第 7 条三处共管），并补点击外部关闭。
- 章节标题 19px/700 + 朱红菱形 ::before（desk:29-48）保留——这是页面允许的「区块标题+索引点缀」，
  朱红用量在主规范 §2 白名单第 5 条内。
- **每屏至多一个 primary**：`#btn-publish` 是中栏唯一 `.btn-primary`；「新建章节」在 view-header，
  降为 `.btn-sm` 非 primary 或保持现状但执行时全局核对 primary 计数（执行时核实与 view-header 的
  同屏关系）。

**正文排版（稿纸 `.writing-sheet`）—— 契约值**：

| 属性 | 目标值（主规范 §3.2） | 现状（writing-desk.css） | 差异处理 |
|---|---|---|---|
| 字族 | `--font-body`（Noto Serif SC 衬线） | 继承全局，一致 | 保持 |
| 正文字号 | `--text-md` 16px | 17px（desk:205） | **收编为 16px**；17px 是游离值，不在字阶上 |
| 行高 | `--leading-loose` 1.8 | 1.9（desk:206） | **收编为 1.8** |
| 行宽 | 32–40 个中文字符 | 由稿纸 padding 间接决定，无显式约束 | 稿纸内 padding 改为以行宽为目标推导（16px 字 ≈ 512–640px 文本列），并加注释说明推导 |
| min-height | 页面级自定 | 58vh（desk:204） | 保留为页面级值，注释语义 |
| 稿纸 padding | `--space-*` token | `6px clamp(18px,4.5%,44px) 14px`（desk:171） | 垂直方向归 token；水平 clamp 与行宽推导合并处理 |
| 页边线 | 朱红 1px，34px 处 | desk:201（`archive-red` 17%） | 保留，属索引性点缀白名单 |
| 只读区分 | 可编辑/只读必须可区分（主规范 §5.2） | 仅 `color: text-secondary`（desk:213-215） | 候选/只读态增加 `--bg-panel` 沉底 + 光标 `not-allowed`，不靠颜色单通道 |

**自动保存指示**：五态徽标（`#writing-save-status`，文案源 useWritingWorkspace.js:182-190）+
顶栏 ◆ 点（`#topbar-save-state`）双指示保留。目标修正：
- 补只读态分支（无绿点，文案「只读」，§2-3）；
- 保存失败态徽标变为可点击重试按钮（动作 = 重试 autosave），失败文案保留「已保留本地备份」但
  须可验证——点击可展开「查看本地备份」入口或明确提示备份位置（交互细节执行时定，语义是
  「承诺必须可验证」）；
- 状态表达 = 文字 + 色点，不引入彩色 pill（主规范 §5.8）。

**候选采纳 UI**（`.pov-candidate-panel.writing-candidate-review-panel`，仅 status==='candidate'
渲染，WritingEditor.vue:84-95）：
- 保留「标题与正文之间」的就地位置（符合作者不离开思路的诉求），但视觉降半级：朱红边卡改为
  `--warning` 系左边线 + paper-raised 底，「待处理」计数语义才允许朱红（主规范 §2 白名单第 2 条）；
- 采用/拒绝确认从原生 `confirm` 迁入全局 `confirmAsync` 模态（主规范 §5.6），按钮文案写动作本身
  （「采用到工作稿」「拒绝建议」已是好文案，保留）；
- 候选态正文只读区分见上表。

**字数条**（`#writing-wordcount-bar`）：元数据档（`--text-xs` mono 可选 + `--tracking-wide`），
含字数/段数/阅读时长/日目标进度 `.wc-goal-progress`；对齐方向只能有一处定义（消除 §2-6 第 5 条）。
日目标进度条属行内轻量进度，不引入 `.workflow-progress`（那是后台长任务语义，主规范 §5.9）。

**工作流条**（`WritingWorkflowBars.vue`：发布进度卡 / 深度导入进度卡 / 冲突条）：后台工作流统一走
`.workflow-progress*`（主规范 §5.9）；版本加载失败 `.writing-empty-hint`（裸文本，§2-7）迁入
`.error-card` 基准样式或补定义（执行时核实其 4 处使用点逐一收口）。

映射主规范：§3.2 长正文、§5.1 Button、§5.2 输入（只读区分）、§5.6 Modal、§5.7 Toast（保存成功）、
§5.8 状态、§5.9 Loading/Error。

### 4.3 副驾驶 rail（右，`aside.writing-panel-rail`，aria-label="写作副驾驶"）

- 结构：`#writing-panel-container`（sticky，styles.css:1847-1857）→ `SceneCockpit.vue`
  （`.scene-cockpit`：标题栏 + 警报摘要 `.scene-alert-summary` + 5 个 role=tab：
  警报/人物/地点/设定/地图）。
- 视觉：模块头 mono 11px/700（desk:769-786）保留（元数据档）；模块正文 12.5px/1.75（desk:816-822）
  收编到 `--text-sm` 13 / `--leading-relaxed` 1.6（执行时核对密度损失）。
- **tab 激活色必须进入页面朱红/墨线索引体系**：按主规范 §5.5，激活 tab = `--text-primary` 600 +
  底部 2px `--line-accent` 墨线；消除 §2-6 第 10 条 accent 蓝残留。仅「警报」tab 允许红点计数
  （待处理语义）。
- 场景感知联动（光标 150ms 防抖 → `findCurrentScene` → 切场景，editorController.js:240-265）是
  本 rail 的核心价值，任何重构不得破坏；tab 内容加载中行内等待用 `.loading` dots（主规范 §5.9），
  「警报加载中…」「地图摘要加载中...」文案统一省略号风格（执行时核实）。
- 空态两句（SceneCockpit.vue:17-19,27）复用 `.empty-state` 简式（短句 + 引导，无 CTA 时不放按钮）。
- 映射主规范：§5.5 Tabs、§5.8 Badge/计数、§5.9 Empty/Loading。

### 4.4 顶栏字数仪表盘（全局 Topbar，`#topbar-wordcount`）

- 结构：`#topbar-chapter-wc` / `#topbar-today-wc` / `#topbar-save-state`（◆ 点，class
  saving/unsaved/saved）+ `#topbar-chapter`（Topbar.vue:9,14-18）；数据经 window 事件
  `writing:dashboard-update` 推送（useWritingWorkspace.js:314-324 → useWordcountDashboard.js:21）。
- 视觉：mono 元数据档 + `--tracking-wide`（主规范 §3.1 mono 分工：字数仪表盘是 mono 的正牌用途）。
- 状态点三态语义色：saving = `--warning`、unsaved = `--text-tertiary`、saved = `--success`
  （执行时核实现色值归属）；与 §4.2 保存徽标状态机保持一致，同态同色。
- 本页是顶栏仪表盘的唯一数据源路由；离开 writing 路由时仪表盘退出由 Topbar 全局负责，
  本页规范不约束。

### 4.5 浮窗与模态

- **OutlineFloat**（`#outline-float-panel`，fixed 右侧抽屉，aria-label="大纲浮窗"）：
  双主题并存（§2-6 第 9 条）必须收敛到一套——保留 desk 朱红索引版，styles.css:2442-2512 的
  accent 蓝 `.current` 删除。抽屉 = radius `--radius-lg` + `--shadow-float`（浮层才用阴影，
  主规范 §1.4）。加载中用 `.loading` dots（现「加载中...」文案可归一）。z-index 归全局浮层档位。
- **模态五件**（AutoExtractionDialog / ConflictOptionsDialog / ConflictDetailDialog /
  DeepImportAuditDialog / VersionHistoryDialog）：统一走 `useModalDialog` + 全局
  `.modal-overlay/.modal-content`（现状已是，保持）。宽度按主规范 §5.6 三档：确认 400 /
  表单 560 / 复杂内容 720——版本历史 diff 网格（role=table）归 720 档，冲突详情归 560 档
  （执行时核实现状宽度）。焦点陷阱/Esc/inert 由全局 modal 保证，页面不得自行实现。
- **候选采用/拒绝的原生 confirm**（§2-9）迁入全局确认模态，文案写动作本身。
- 映射主规范：§5.6 Modal、§5.7 Toast、§1.4 阴影只用于浮层。

## 5. 状态覆盖清单

| 状态 | 目标行为 | 现状差距 |
|---|---|---|
| 无章节空态 | 章节树 `.empty-state` + 「创建第一章」CTA；编辑器区 `.writing-editor-empty`（「文」水印保留）；副驾驶引导句 | 齐全，仅缺 icon 体系（§2-15），可后续补 |
| 有章节未选中 | 编辑器区「请从左侧选择章节开始写作」（WritingEditor.vue:59-61） | 达标 |
| 章节加载中 | `.loading-skeleton` 稿纸骨架（主规范 §5.9，reduced-motion 禁动画） | **缺失**（§2-2），需新增 |
| 章节加载失败 | `.error-card`：人话说明 + 重试按钮，就地渲染在中栏 | **缺失**（`loadError` 无消费者，§2-2），需新增 |
| 保存中 | 徽标「正在保存」+ 顶栏 ◆ saving；输入不打断 | 达标 |
| 已保存 | 徽标「已保存到工作稿」+ toast + 顶栏 ◆ saved | 达标 |
| 保存失败 | 徽标变错色 + toast + **可点击重试** + 本地备份可验证入口 | 缺重试与可验证性（§2-1） |
| 只读（候选/正式正文） | 徽标无绿点、文案「只读」；正文视觉只读区分（§4.2 表） | 绿点语义错（§2-3）、区分弱（§2-9） |
| 仅排版差异 | 「排版修改已保留在本地」，不请求后端（editorController.js:294-297） | 达标，文案保留 |
| AI 生成中 | 按钮「生成中…」禁用态（loading 宽度不抖动，主规范 §5.1）；流式输出遵守 reduced-motion | 基本达标（执行时核实流式动画降级） |
| 候选待处理 | 见 §4.2 候选采纳 UI | 视觉降级 + confirm 归一（§2-9） |
| 离开恢复 | 三层：路由守卫 confirm + `beforeunload` + 会话快照免确认恢复 / localStorage 跨会话 confirm 恢复 | 达标（机制在，§2 无此项问题），重构不得破坏 |
| 冲突/并发 | 乐观锁 autosave；发布冲突走全局 `#modal-overlay` | 达标 |
| 专注模式 | §3 目标态：rail 隐藏、稿纸居中、文案统一、状态持久化 | 见 §2-11 |
| 窄屏 <600 | 整页替换 MobileQuickNote（已选章且非只读时） | 达标，断点归一见 §6 |

## 6. 响应式行为（四档）

| 档位 | 宽度 | 行为 |
|---|---|---|
| Desktop | ≥1440 | 工作台不限宽（主规范 §6），三栏全形态；rail 默认开 |
| Laptop | 1100–1440 | 默认形态；右 rail 默认开（`innerWidth > 1099`，WritingView.vue:242） |
| Tablet | 760–1100 | 右 rail 掉到整行或默认收起；左 rail 可折叠；单栏主区保持行宽契约 |
| Mobile | <760 | 单栏、触控目标 ≥42/44px；**MobileQuickNote 整页替换的边界**见下 |

- **MobileQuickNote 切换边界（目标态）**：统一到主规范 §6 的 760px 主断点——JS `isNarrow` 阈值
  从 600 改为 760（现状 `useWritingWorkspace.js:157,1109`），消除 600–760px 死区（§2-10）。
  切换条件保持四元：`isNarrow && !forceDesktop && 已选章 && 非只读`。
  **此为行为变更，执行时需产品确认并同步 e2e**（390px 快照不受影响；600–760px 区间行为改变）。
- **桌面模式回切**：「完整编辑器」按钮置 `forceDesktop=true`（useWritingWorkspace.js:1092）并加
  body `.force-desktop` class（:1115）。目标：① 该 class 目前无 CSS 规则（§2-7），回切后布局依赖
  既有 ≤760px 单栏 CSS，须验证可用；② `forceDesktop` 选择应持久化（sessionStorage），避免每次
  进页重选（执行时核实产品意图）。
- **断点归并**：rail 折叠 760px（desk:597-622）、正文移动态（styles.css:6186-6189 的 600px）随
  JS 阈值一并归入 760；900px cockpit max-height（styles.css:5954）与 1099px 归 1100 档
  （主规范 §6：长尾断点逐个审查，可归入两档的归入）。4 处硬编码视口判断（§2-10）收编为共享
  composable 或 CSS 单一来源（执行时定实现）。
- 600px 以下 topbar 压缩、章节树 max-height 42vh 等局部自适应（styles.css:6113-6223、
  desk:1661-1693）保留，逐行注释理由。
- 390px 页面级横向溢出零容忍（主规范 §6），由 `writing-mobile-390-minimal.png` 快照守住。

## 7. 必须保留的契约

以下语义钩子是 e2e 与全局基建的硬依赖，**重命名/删除前必须全局 grep 并同步测试**
（主规范 §9）。统计口径：`e2e/writing.spec.js` 全文 `#id` 选择器共 121 处、16 个不同 id
（2026-08 实测 `grep -o` 结果）。

**#id（writing.spec.js 实测命中次数）**：

| id | 命中 | 所在 |
|---|---|---|
| `#writing-editor` | 38 | 正文 textarea（`.novel-editor`，aria-label="章节正文"） |
| `#btn-autosave` | 15 | 保存工作稿按钮 |
| `#modal-footer` | 10 | 全局确认框（全局契约） |
| `#btn-publish` | 9 | 发布主按钮 |
| `#writing-title-input` | 7 | 章节标题输入 |
| `#writing-save-status` | 7 | 保存状态徽标 |
| `#version-selector` | 7 | 版本下拉（aria-label="选择章节版本"） |
| `#modal-overlay` | 7 | 全局模态遮罩（全局契约） |
| `#btn-conflict-check` | 5 | 冲突检查按钮 |
| `#writing-tree-container` / `#writing-panel-container` / `#writing-editor-container` / `#workspace-content` | 各 3 | 三栏与页面挂载点 |
| `#btn-checkpoint-version` | 2 | 检查点按钮 |
| `#modal-content` / `#mobile-note-editor` | 各 1 | 全局模态体 / 移动速记正文 |

**未在 writing.spec.js 命中但属公共契约，同样不得擅动**：
`#writing-chapter-title`、`#writing-version-info`、`#writing-editor-buttons`、`#writing-wordcount-bar`、
`#writing-versions-container`、`#publish-status-dot`、`#writing-conflict-strip`（注意双渲染源，§2-8）、
`#writing-publish-bar-container`、`#writing-deep-import-bar-container`、`#outline-float-panel`、
`#outline-float-body`、`#mobile-note-wc`、`#auto-extraction-dialog-label` 等 sr-only 标签，
以及顶栏 `#topbar-wordcount` / `#topbar-chapter-wc` / `#topbar-today-wc` / `#topbar-save-state` /
`#topbar-chapter`。

**data-action**：`toggle-outline-float`（WritingView.vue:14）、`writing-ai-menu`、
`writing-more-menu`（WritingEditor.vue:24,42）、`deep-import-map-next`（WritingWorkflowBars.vue:44）、
`conflict-ai-review` 及 ConflictDetailDialog 内 8 个行动态 action
（`copy-conflict-suggestion` / `apply-conflict-suggestion` / `locate-conflict` / `open-conflict-source` /
`resolve-conflict` / `ignore-conflict` / `later-conflict` / `generate-conflict-suggestion`，
ConflictDetailDialog.vue:196-230）、`data-conflict-item-id`（:211）、
`data-scene-cockpit-project`（SceneCockpit.vue:2）、`data-cockpit-module`（:79）、`data-panel`、
`data-version` / `data-latest`（WritingView.vue:97-98）。

**role / 可访问名称**（e2e `getByRole({name})` 直接依赖，改文案必须同步测试）：

- 按钮名：「新建章节」「创建第一章」「打开第 N 章…」（ChapterRow 动态 aria-label，
  ChapterTree.vue:113）、「上一章」「下一章」「历史」「比较」「展开章节/收起章节」
  「收起写作副驾驶/展开」（动态）、「打开第 N 章」（OutlineFloat）、「专注模式」「保存工作稿」
  「保存为新工作稿」「放弃未设为正式正文的更改」「设为正式正文」「继续设为正式正文」「确认恢复」
  「基于此版本创建」「预览」「定位正文/无正文定位」「打开来源/无可打开来源」「生成 AI 修复建议」
  「补充 AI 软冲突判断」「稍后」「完整编辑器」。
- dialog 名：「自动提取」「剧情设定冲突检查选项」「剧情设定冲突检查」「版本历史」
  「深度导入快照状态」；aria-label：「章节正文」「移动端速记正文」「选择章节版本」
  「写作字数仪表盘」「左侧版本/右侧版本」；rail：「章节」「写作副驾驶」。
- tab：「警报/人物/地点/设定/地图」（role=tab，`.active` class 断言）。
- 结构 role：`role=tablist`（`.cockpit-tabs`）、`role=alert`（章节列表失败、版本加载失败）、
  `role=status`（`.mobile-note-status`、冲突条无 latest 时）、`role=table`（版本 diff 网格）、
  冲突条 `role=button`（有 latest 时，WritingView.vue:110）。

**class 契约**：`.writing-toolbar`（`waitWritingReady` 入口，helpers/workbench.js:120）、
`.writing-workspace-layout`、`.writing-tree-rail` / `.writing-panel-rail` + `.is-collapsed`、
`.scene-tree-label`、`.scene-cockpit`、`.cockpit-panel`、`.writing-version-history-item`、
`.writing-conflict-item`、`.mobile-quick-note`、body `.focus-mode-active`、
`details.writing-tools-menu` 结构（被 `openWritingToolMenu` 依赖，writing.spec.js:36-45）。
集中登记处：`e2e/helpers/selectors.js:76-92`。

**writing-desk.css（1707 行）归并策略**：

- **上移全局（editorial-theme.css 视觉权威层）**：所有颜色/圆角/阴影类规则——chip 档案签条
  （desk:51-94）、工具菜单弹层材质（desk:338-344）、cockpit 材质（desk:557-560 起）、
  outline-float 朱红主题（desk:1106-1157，收敛后唯一权威）。同时删除 styles.css 侧被推翻的
  对应基础定义（§2-6 逐条列出的 12 处）。
- **上移全局（styles.css 结构层）**：rail 折叠结构（desk:597-622）若与其他工作台页共用；
  专注模式结构（desk:1585-1601 与 styles.css:2432-2440 双写归一到一处）。
- **保留页面级**：稿纸独特构图（desk:162-228，顶墨线/页边线/错位阴影——页面第一焦点允许独特
  构图，主规范 §0）、章节树行密度（desk:452-538）、cockpit 模块密度（desk:646-822）、
  MobileQuickNote 布局（desk:1528-1582，执行时补媒体查询或注释说明依赖 mobileMode 条件渲染）。
- **删除**：`.writing-editor-buttons__group`（desk:124-143，无 DOM）、其余 §2-7 死样式。

## 8. 验收标准 + 验证命令

**验收标准**：

1. §5 状态覆盖清单逐条可走通，特别是新增的加载骨架、加载失败 error-card、保存失败重试。
2. 正文排版 = `--text-md` 16 / `--leading-loose` 1.8 / 行宽 32-40 中文字符，数值落在字阶 token 上，
   无游离 px 字号（新触碰代码）。
3. 三层 CSS 冲突 12 处（§2-6）逐项消解：每个 class 的视觉规则只剩一个权威层；
   `.novel-editor` 的 editorial 死代码删除。
4. 主对象 64–68% 契约不回退：1440px 下中栏 grid 份额不变；390px 无横向溢出。
5. §7 全部契约钩子在位：`#id` 16 个、data-action、role/可访问名称零意外变更；
   文案改动（如专注模式统一）已全局同步 e2e。
6. `visual-writing.spec.js:113`「聚焦模式」测试债已解决（改测试名或改 UI 文案，二选一并记录）。
7. 主规范 §8 无障碍：触控档按钮 ≥42px、focus-visible 朱红环不被 desk 层 `outline/box-shadow` 覆写
   （desk:209-211 的 `:focus { box-shadow: none }` 执行时核实是否吃掉全局焦点环）。

**验证命令**（工作目录 `frontend-console/`）：

```bash
# 功能 e2e（writing 页主契约，1002 行）
npx playwright test e2e/writing.spec.js

# 视觉基线（仅 darwin 有基线；共 3 个用例 5 张快照：
# writing-desk-{minimal,warm,dark}.png、writing-focus-minimal.png、writing-mobile-390-minimal.png）
npx playwright test e2e/visual-writing.spec.js

# 全局基建回归（主题 token / 排版 token / 骨架屏 / 模态无障碍，受 desk 归并影响时必跑）
npx vitest run tests/editorialTheme.test.js tests/typographyTokens.test.js \
  tests/loadingSkeleton.test.js tests/modalAccessibility.test.js   # 文件名执行时核实

# 文档漂移门禁（仓库根目录）
make docs-check BASE_REF=origin/main
```

改动样式后视觉快照需 `--update-snapshots` 重建 darwin 基线并在 PR 中说明；非 darwin 平台按
`VISUAL_BASELINE=1` 流程生成本地快照核对（visual-writing.spec.js:76-79）。
