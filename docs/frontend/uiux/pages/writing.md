# 写作编辑器 UI/UX 执行规范

> 路由：`writing` 工作台视图（`#workspace-content[data-workspace-view="writing"]`）。
> 唯一权威：本文件是 writing 页的页面级执行规范，遵循 `docs/frontend/uiux/design-standard.md`
>（下称主规范）的内容优先契约 §4、长正文排版 §3.2、Loading 归一 §5.9、点缀系统 §2。
> 事实来源：`frontend-console/vue/views/writing/` 源码（含 `writing-desk.css` 与
> `writing-decorations.css`）与 `e2e/writing.spec.js`、`e2e/visual-writing.spec.js`。
> 所有行号以调研时点的源码为准，漂移时以源码为准并回改本文件。
> 2026-08 三主题改造（sticky/night/ink 换肤，功能行为零变化）已落地：固定三栏、底部状态栏、
> 点缀系统均为当前事实；§2 问题清单内逐条标注了本轮后的状态。

## 1. 页面定位与目标画像

- **定位**：全产品停留时间最长的页面，是画像 A「安心继续创作」核心任务的承载页；也是唯一在全局
  顶栏拥有字数仪表盘（`#topbar-wordcount`）的路由（`vue/shell/components/Topbar.vue`）。
- **目标画像**：画像 A（长期创作的作家）。本页不为画像 B 服务；RP 用户走独立路径（见
  `pages/rp-experience.md`）。
- **用户任务与情绪收益**：作者打开本页时的心理状态是「继续写」，不是「管理作品」。页面必须让作者
  3 秒内确认：写到哪一章、上次保存是否安全、当前场景有哪些相关设定——然后立刻能开始打字。
- **用户会喜欢的理由**（对应 `user-personas.md` §画像 A）：
  - 写作时就地查看人物/地点/警报（副驾驶 rail），不离开当前思路；
  - 草稿三层保护（会话快照 + localStorage 备份 + 离开守卫），页面切换不丢稿；
  - AI 候选只进「待处理」，采用/拒绝由作者决定，不静默覆盖正文。
- **主要摩擦（现状）**：保存失败无重试路径、切章节无加载反馈、移动端速记与桌面编辑器能力割裂。
  编辑器头部拥挤问题已随底部状态栏落地缓解（§2-5）。详见 §2。
- **验证方式**：e2e 场景化验收（§8）；「喜欢」为产品假设，待真实行为数据修正。

## 2. 现状问题清单（按严重度排序）

> 2026-08 三主题改造后复核：样式类条目（5、6、7、13）大部分随 `writing-desk.css` 重写与
> `editorial-theme.css` 瘦身消解，条目内旧行号全部失效；功能类条目（1–4、8–12、14、15）
> 本轮未涉及，保持原状。各条目内标注最新状态。

### P0 — 直接影响写作安全感

1. **保存失败无恢复路径**：`saveError` 只改徽标文案 + toast（`controllers/editorController.js`），
   `#writing-save-status` 徽标不可点击、无重试按钮；「已保留本地备份」对作者不可验证。（本轮未涉及。）
2. **正文加载无反馈**：`loadChapter` 期间无 skeleton/遮罩，切章节时旧正文残留到新数据到达；
   `editorState.loadError` 无任何组件消费，只在 toast 闪现。违反主规范 §5.9 Loading/Error 归一。
   （本轮未涉及。）
3. **保存徽标只读态语义错误**：徽标默认 `::before` 绿点，`saveBadgeClass` 无 readonly 分支
   （`components/WritingEditor.vue`），只读章节也显示绿色「已保存」观感。（本轮未涉及；
   徽标 DOM 已平移至底部状态栏，id 不变。）
4. **「聚焦模式」测试债**：旧视觉用例找按钮名「聚焦模式」，UI 文案为「进入专注」/「专注模式」。
   2026-08 状态：视觉快照基线正按三主题重录（`writing-desk-{sticky,night,ink}.png` 等，见 §8）；
   专注按钮现位于底部状态栏右侧；用例名与 UI 文案的一致性问题改文案前必须先解决。

### P1 — 信息层级与视觉一致性

5. **编辑器头部三行拥挤**：**大部分消解**。字数条、保存/版本状态徽标、字体循环切换与专注按钮
   已移入 38px 底部状态栏（`.writing-statusbar`）；版本选择条保留在编辑器上方工具区。
   编辑器头收敛为标题组 + 主按钮行 + context 行（版本条 + 冲突条）；≤760px 折行表现执行时复核。
6. **三层 CSS 重复/冲突**：**大部分消解**。`writing-desk.css` 已按新设计语言整体重写，
   `editorial-theme.css` 瘦身（旧 Editorial Archive 装饰与死覆写移除）。原 12 处冲突清单的行号
   全部失效，已确认消解的代表项：`.cockpit-tab` 激活色统一为 `--nc-accent` 2px 下划线（accent 蓝
   残留消除）、稿纸顶 3px 墨线与朱红页边线随旧设计语言移除、专注模式稿纸居中双写收敛为
   `.focus-mode-active .writing-sheet`（max-width 860px）一处。残留冲突执行时按源码重新清点，
   权威层分工见主规范 §1.1。
7. **死样式/死 class**：旧清单（`.writing-empty-hint`、`.writing-editor-buttons__group`、
   `.wc-bar-left/.wc-bar-right` 等）基于重写前源码，行号与存活状态全部失效；执行时按源码
   重新清点。`.writing-empty-hint` 的 4 处使用点收口与 `.error-card` 归并仍是有效目标。
8. **重复 id 隐患**：`#writing-conflict-strip` 有两个渲染源（`WritingView.vue` 与
   `WritingWorkflowBars.vue`），当前靠 `:show-conflict="false"` 硬编码回避；打开开关即产生重复 id。
   （本轮未涉及。）
9. **候选采纳 UI 与正文抢层级**：`.writing-candidate-review-panel` 插在标题与正文之间，此时
   textarea 只读但仅 `color: text-secondary` 区分；采用/拒绝用原生 `confirm`，与全局
   `confirmAsync` 模态体系混用。（本轮未涉及；视觉降级目标见 §4.2。）

### P2 — 响应式与模式完整性

10. **600–760px 断档 + 双断点体系**：JS `mobileMode` 阈值 600px（`useWritingWorkspace.js`），
    CSS 布局断点 760/900/1099px；600–760px 区间用户得到「桌面编辑器 + 单列布局」。（本轮未涉及。）
11. **专注模式不完整**：仅隐藏两栏 rail + 居中稿纸；顶栏/view-header 保留；无键盘快捷键、
    无状态持久化（`appState._focusMode` 仅存内存）。2026-08 状态：入口移至底部状态栏右侧
    「专注模式」按钮；`body.focus-mode-active` 下点缀一律隐藏（新增，主规范 §2 点缀系统）；
    持久化与快捷键仍为待办。
12. **移动速记能力割裂**：mobileMode 下丢失标题编辑、无字数目标、无版本/冲突入口；操作条吸底
    现随工作区剩余高度布局并保持在移动底栏上方，不再重复硬编码底栏高度。
13. **密度断层**：正文由 17px/1.9 调整为 14px/行高 2.0（§4.2），与章节树（12px 标题/10-11px
    元数据）、copilot 高密度的对比有所缓解；10px 元数据低于主规范字阶下限 11px，仍待归并。
14. **details 菜单无障碍缺陷**：`.writing-tools-menu` 与 `.writing-page-menu` 用原生 `<details>`；
    点击外部关闭已补齐，`aria-expanded` 同步仍待处理。
15. **空态无插图/icon 体系**：三处空态齐全（ChapterTree / WritingEditor / SceneCockpit）但均未
    使用 `.empty-state .empty-icon`。（本轮未涉及。）

## 3. 目标布局与信息层级

**三栏布局（桌面，≥1100px）**：写作页不使用共享 fr 份额，grid 固定为
`238px / minmax(0,1fr) / 257px`，gap 20px（`.writing-workspace-layout`，styles.css）；
rail 折叠后对应列变为 `--workspace-rail-collapsed` 44px。底部状态栏通栏（grid-column 1/-1）：

```
┌──────────────────────────────────────────────────────────┐
│ Topbar（全局，57px）：#topbar-chapter ｜ #topbar-wordcount ｜ 主题三点切换器 │
├──────────────────────────────────────────────────────────┤
│ view-header.writing-toolbar：写作 · 共 N 章 ［新建章节］▾  │
├─────────┬──────────────────────────────┬─────────────────┤
│ 章节树   │  编辑器（第一视觉焦点）        │  副驾驶          │
│ 238px   │  · 编辑器头（标题+菜单+版本条）  │  SceneCockpit   │
│ (左)    │  · 稿纸 .writing-sheet       │  257px(右,sticky)│
├─────────┴──────────────────────────────┴─────────────────┤
│ .writing-statusbar（38px 通栏）：字数进度/段落/阅读时长 · 字体/专注/保存徽标 │
├──────────────────────────────────────────────────────────┤
│ 浮窗层：OutlineFloat 抽屉 / 各模态                         │
└──────────────────────────────────────────────────────────┘
```

- **第一视觉焦点 = 正文编辑区**。章节树与副驾驶是「索引与参照」，视觉重量（字号、色对比、边框强度）
  必须低于稿纸。稿纸是页面唯一允许有独特构图的区域：1px `--nc-hairline` 边框 + `--nc-surface` 底 +
  主题点缀（§4.2）；旧 Editorial Archive 的顶 3px 墨线与朱红页边线已移除。
- **主对象契约的落实**（主规范 §4）：写作页以固定三栏（238 / 弹性 / 257）替代 64fr/18fr 份额，
  主对象仍是弹性中栏；共享 `--workspace-main-share:64fr` 契约对其他工作台页不变。
  不得为「呼吸感」加宽 rail 或压缩中栏。
- **专注模式**：进入后两栏 rail `display:none`、稿纸单列居中（≤860px 纸宽）、编辑器 min-height
  82vh（≥761px）；顶栏保留（字数仪表盘是全局契约），view-header 保留但折叠为单行；
  **点缀一律隐藏**（主规范 §2）。入口 = 底部状态栏右侧「专注模式」按钮。
  待办：状态持久化到 sessionStorage（沿用 rail 开合的 `workspace-rail:{pid}:writing:*` 键族模式）、
  键盘快捷键（产品决定）。
- **信息层级**：Primary = 稿纸正文 + 主按钮「设为正式正文」（每屏唯一 primary）；Secondary = 章节树
  当前章、副驾驶当前 tab、保存状态；Tertiary = 版本条、状态栏读数、菜单项。层级靠字阶与留白，
  不新增卡片边框（主规范 §0、§4 分隔优先级）。

## 4. 逐区域标准

### 4.1 章节树 rail（左，`aside.writing-tree-rail`，aria-label="章节"）

- 结构：`#writing-tree-container` → `ChapterTree.vue`（`.card.chapter-tree-card`：头部
  `.chapter-tree-header` → `.chapter-tree-list`（按场景分组 `.scene-tree-node`）→ 底部批量工具栏）。
- 头部文案：「章节 · 共 N 章」+「+ 新章」按钮（折叠时只显示「章节」）。
- 视觉：rail 面板 = `--nc-surface` + `--line-subtle`，无阴影（主规范 §5.3）；当前章 =
  `--nc-surface` 底 + `--nc-ink` 加粗（700），其余行 `--nc-dim`，hover `--bg-hover`——选中态靠
  表面差与字重表达，不再使用左侧 3px 索引线。
- 字阶：章节标题 12px（`--font-body`）、章号 11px mono `--nc-dim`、meta 10px；10px 低于主规范
  字阶下限 11px，执行时向 `--text-xs` 归并（§2-13）。rail 收窄时允许标题截断省略号，但必须保留
  完整 title 提示。
- 状态点：章状态 = 文字 + 小色点/描边点（draft = `--warning` 描边、published = `--success` 实心），
  语义不变；造型以源码为准（主规范 §5.8）。
- 空态：「尚无章节 + 创建第一章」复用 `.empty-state` + `.empty-state-cta`（主规范 §5.9）；列表加载
  失败保留 rail 内 `role=alert`，样式归并入 `.error-card` 基准。
- 映射主规范：§5.3 Card、§5.8 状态点、§5.9 Empty/Error。

### 4.2 编辑器（中栏，`main#writing-editor-container`）

**编辑器头**（`.writing-editor-header`）：

- 第一行 = `#writing-chapter-title` / `#writing-title-input` + 主按钮 `#btn-publish` +
  三个 details 菜单（工作稿与版本 / AI 写作助手 / 更多）；第二行 = context 插槽
  （`#writing-versions-container` 版本选择条 + `#writing-conflict-strip` 冲突条）。
  版本选择条保留在编辑器上方工具区，不随状态栏平移。
- 保存/版本状态徽标（`#writing-save-status`、`#writing-version-info`）与字数条已平移至底部状态栏
  （见下），id 不变，e2e 契约不破。
- **每屏至多一个 primary**：`#btn-publish` 是中栏唯一 `.btn-primary`；「新建章节」在 view-header，
  执行时全局核对 primary 计数。

**正文排版（稿纸 `.writing-sheet`）—— 当前值**：

| 属性 | 当前值 | 说明 |
|---|---|---|
| 字族 | `--font-body`（ink 主题为 LXGW Bright/WenKai 栈，主规范 §1.3） | 状态栏字体循环可在会话内临时 override，不写偏好存储 |
| 正文字号 | 14px | 页面级值（writing-desk.css），与主规范「正文/控件」档一致 |
| 行高 | 2.0 | 页面级值（稿纸阅读节奏） |
| 行宽 | 正常态无 max-width；由编辑区左右 padding 59px 收边 | 旧「32–40 中文字符」目标不再以 max-width 实现；专注模式稿纸 ≤860px |
| min-height | 58vh（专注模式 ≥761px 时 82vh） | 页面级值 |
| 稿纸 padding | `30px 59px 34px` | 页面级值 |
| 边框/焦点 | 1px `--nc-hairline`；focus-within 边 `--nc-hairline-strong` + `--nc-accent-soft` 光晕 | 旧顶 3px 墨线、朱红页边线已移除 |
| 只读区分 | 仅 `color: text-secondary`（现状保持） | 主规范 §5.2 的强化区分（沉底 + not-allowed 光标）仍为待办（§2-9） |
| 点缀/水印 | 编辑区右上 + 正文下方各 1 组；ink 主题水印字 = `data-watermark`（当前章标题首字） | 硬规则见主规范 §2 点缀系统；实现 `writing-decorations.css` |

**底部状态栏**（`.writing-statusbar`，38px，sticky bottom，通栏 grid-column 1/-1，mono 11px）：

- 正文下方出现发布、生成、冲突检查或深度导入反馈时，状态栏回到正常文档流，避免遮挡工作流卡；反馈消失后恢复吸底。
- 左：`#writing-wordcount-bar`——字数进度「1,240 / 3,000 字」+ 3px accent 进度条
  （`.wc-goal-progress`）、段落数、预计阅读时长（字数 / 400 向上取整，`WritingView.vue`
  `statusReadMinutes`）。日目标进度属行内轻量进度，不引入 `.workflow-progress`（主规范 §5.9）。
- 右：字体循环切换（会话内临时 override，不写偏好存储）→ 专注模式按钮 → 保存/版本状态徽标
  （`#writing-save-status` / `#writing-version-info`）。
- 上述 DOM 自 WritingEditor 头部平移，id 全部不变（§7 契约）；保存徽标五态语义与重试/只读修正
  目标不变（§2-1、§2-3）：
  - 补只读态分支（无绿点，文案「只读」）；
  - 保存失败态徽标变为可点击重试按钮，失败文案保留「已保留本地备份」但须可验证；
  - 状态表达 = 文字 + 色点，不引入彩色 pill（主规范 §5.8）。

**自动保存指示**：五态徽标 + 顶栏 ◆ 点（`#topbar-save-state`）双指示保留，同态同色（§4.4）。

**候选采纳 UI**（`.pov-candidate-panel.writing-candidate-review-panel`，仅 status==='candidate'
渲染）：
- 保留「标题与正文之间」的就地位置（符合作者不离开思路的诉求），但视觉降半级：改为 `--warning`
  系左边线 + `--nc-surface` 底，「待处理」计数语义才允许 accent（主规范 §2 强调色使用约束第 2 条）；
- 采用/拒绝确认从原生 `confirm` 迁入全局 `confirmAsync` 模态（主规范 §5.6），按钮文案写动作本身
  （「采用到工作稿」「拒绝建议」已是好文案，保留）；
- 候选态正文只读区分见上表。

**工作流条**（`WritingWorkflowBars.vue`：发布进度卡 / 深度导入进度卡 / 冲突条）：后台工作流统一走
`.workflow-progress*`（主规范 §5.9）；版本加载失败 `.writing-empty-hint`（裸文本，§2-7）迁入
`.error-card` 基准样式或补定义（执行时核实其使用点逐一收口）。

映射主规范：§3.2 长正文、§5.1 Button、§5.2 输入（只读区分）、§5.6 Modal、§5.7 Toast（保存成功）、
§5.8 状态、§5.9 Loading/Error。

### 4.3 副驾驶 rail（右，`aside.writing-panel-rail`，aria-label="写作副驾驶"）

- 结构：`#writing-panel-container`（sticky）→ `SceneCockpit.vue`（`.scene-cockpit`：标题栏 +
  警报摘要 + 5 个 role=tab：警报/人物/地点/设定/地图）。
- 警报卡：`--nc-alert-bg` 底 + `--nc-alert-ink` 标题 + 右上「查看 →」按钮（`.scene-alert-card`），
  语义色分工见主规范 §2。
- 页签：激活 tab = `--text-primary` + 底部 2px `--nc-accent` 下划线（inset），accent 蓝残留已消解
  （§2-6）。仅「警报」tab 允许 accent 色点计数（待处理语义）。
- 实体行：头像块 4px 圆角（ink 主题圆形 50%）；在场状态纯文字，不用色块/pill。
- 模块头 mono 11px/700 保留（元数据档）；模块正文密度向 `--text-sm` 13 / `--leading-relaxed` 1.6
  归并（执行时核对密度损失）。
- 场景感知联动（光标 150ms 防抖 → `findCurrentScene` → 切场景）是本 rail 的核心价值，任何重构
  不得破坏；tab 内容加载中行内等待用 `.loading` dots（主规范 §5.9）。
- 空态两句复用 `.empty-state` 简式（短句 + 引导，无 CTA 时不放按钮）。
- 映射主规范：§5.5 Tabs、§5.8 Badge/计数、§5.9 Empty/Loading。

### 4.4 顶栏字数仪表盘（全局 Topbar，`#topbar-wordcount`）

- 结构：`#topbar-chapter-wc` / `#topbar-today-wc` / `#topbar-save-state`（◆ 点，class
  saving/unsaved/saved）+ `#topbar-chapter`；数据经 window 事件 `writing:dashboard-update` 推送
  （`useWritingWorkspace.js` → `useWordcountDashboard.js`）。
- 视觉：mono 元数据档 + `--tracking-wide`（主规范 §3.1 mono 分工：字数仪表盘是 mono 的正牌用途）。
- 状态点三态语义色：saving = `--warning`、unsaved = `--text-tertiary`、saved = `--success`
  （执行时核实现色值归属）；与 §4.2 保存徽标状态机保持一致，同态同色。
- 顶栏右侧另有全局主题三点切换器（`.topbar-theme`，主规范 §1.5），非本页独有。
- 本页是顶栏仪表盘的唯一数据源路由；离开 writing 路由时仪表盘退出由 Topbar 全局负责，
  本页规范不约束。

### 4.5 浮窗与模态

- **OutlineFloat**（`#outline-float-panel`，fixed 右侧抽屉，aria-label="大纲浮窗"）：
  抽屉 = radius `--radius-lg` + `--shadow-float`（浮层才用阴影，主规范 §1.4）。加载中用
  `.loading` dots。z-index 归全局浮层档位。旧双主题并存问题随样式重写行号失效，执行时按源码
  核实收敛状态。
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
| 无章节空态 | 章节树 `.empty-state` + 「创建第一章」CTA；编辑器区 `.writing-editor-empty`；副驾驶引导句 | 齐全，仅缺 icon 体系（§2-15）。旧「文」水印已随 Editorial Archive 移除；ink 主题水印字 = 当前章标题首字（`data-watermark`，主规范 §2 点缀系统） |
| 有章节未选中 | 编辑器区「请从左侧选择章节开始写作」 | 达标 |
| 章节加载中 | `.loading-skeleton` 稿纸骨架（主规范 §5.9，reduced-motion 禁动画） | **缺失**（§2-2），需新增 |
| 章节加载失败 | `.error-card`：人话说明 + 重试按钮，就地渲染在中栏 | **缺失**（`loadError` 无消费者，§2-2），需新增 |
| 保存中 | 徽标「正在保存」（底部状态栏）+ 顶栏 ◆ saving；输入不打断 | 达标 |
| 已保存 | 徽标「已保存到工作稿」+ toast + 顶栏 ◆ saved | 达标 |
| 保存失败 | 徽标变错色 + toast + **可点击重试** + 本地备份可验证入口 | 缺重试与可验证性（§2-1） |
| 只读（候选/正式正文） | 徽标无绿点、文案「只读」；正文视觉只读区分（§4.2 表） | 绿点语义错（§2-3）、区分弱（§2-9） |
| 仅排版差异 | 「排版修改已保留在本地」，不请求后端 | 达标，文案保留 |
| AI 生成中 | 按钮「生成中…」禁用态（loading 宽度不抖动，主规范 §5.1）；流式输出遵守 reduced-motion | 基本达标（执行时核实流式动画降级） |
| 候选待处理 | 见 §4.2 候选采纳 UI | 视觉降级 + confirm 归一（§2-9） |
| 离开恢复 | 三层：路由守卫 confirm + `beforeunload` + 会话快照免确认恢复 / localStorage 跨会话 confirm 恢复 | 达标（机制在，§2 无此项问题），重构不得破坏 |
| 冲突/并发 | 乐观锁 autosave；发布冲突走全局 `#modal-overlay` | 达标 |
| 专注模式 | §3 目标态：rail 隐藏、稿纸居中、**点缀一律隐藏**、入口在底部状态栏 | 状态持久化与快捷键仍缺（§2-11） |
| 窄屏 <600 | 整页替换 MobileQuickNote（已选章且非只读时） | 达标，断点归一见 §6 |

## 6. 响应式行为（四档）

| 档位 | 宽度 | 行为 |
|---|---|---|
| Desktop | ≥1440 | 工作台不限宽（主规范 §6），三栏全形态；rail 默认开 |
| Laptop | 1100–1440 | 默认形态；右 rail 默认开（`innerWidth > 1099`） |
| Tablet | 760–1100 | 右 rail 掉到整行或默认收起；左 rail 可折叠；单栏主区保持排版契约 |
| Mobile | <760 | 单栏、触控目标 ≥42/44px；**MobileQuickNote 整页替换的边界**见下 |

- **MobileQuickNote 切换边界（目标态）**：统一到主规范 §6 的 760px 主断点——JS `isNarrow` 阈值
  从 600 改为 760，消除 600–760px 死区（§2-10）。切换条件保持四元：
  `isNarrow && !forceDesktop && 已选章 && 非只读`。
  **此为行为变更，执行时需产品确认并同步 e2e**（390px 快照不受影响；600–760px 区间行为改变）。
- **桌面模式回切**：「完整编辑器」按钮置 `forceDesktop=true` 并加 body `.force-desktop` class。
  目标：① 该 class 目前无 CSS 规则，回切后布局依赖既有 ≤760px 单栏 CSS，须验证可用；
  ② `forceDesktop` 选择应持久化（sessionStorage），避免每次进页重选（执行时核实产品意图）。
- **断点归并**：rail 折叠 760px、正文移动态随 JS 阈值一并归入 760；900px cockpit max-height 与
  1099px 归 1100 档（主规范 §6：长尾断点逐个审查）。硬编码视口判断（§2-10）收编为共享
  composable 或 CSS 单一来源（执行时定实现）。
- 600px 以下 topbar 压缩、章节树 max-height 42vh 等局部自适应保留，逐行注释理由。
- 点缀系统 ≤760px 一律隐藏（主规范 §2 点缀系统）。
- 390px 页面级横向溢出零容忍（主规范 §6），由 `writing-mobile-390-sticky.png` 快照守住。

## 7. 必须保留的契约

以下语义钩子是 e2e 与全局基建的硬依赖，**重命名/删除前必须全局 grep 并同步测试**
（主规范 §9）。统计口径：`e2e/writing.spec.js` 全文 `#id` 选择器共 121 处、16 个不同 id
（2026-08 实测 `grep -o` 结果）。三主题改造只平移 DOM 位置（编辑器头 → 底部状态栏），
id 与可访问名称不变。

**#id（writing.spec.js 实测命中次数）**：

| id | 命中 | 所在 |
|---|---|---|
| `#writing-editor` | 38 | 正文 textarea（`.novel-editor`，aria-label="章节正文"） |
| `#btn-autosave` | 15 | 保存工作稿按钮 |
| `#modal-footer` | 10 | 全局确认框（全局契约） |
| `#btn-publish` | 9 | 发布主按钮 |
| `#writing-title-input` | 7 | 章节标题输入 |
| `#writing-save-status` | 7 | 保存状态徽标（现位于底部状态栏右侧） |
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

**data-action**：`toggle-outline-float`、`writing-ai-menu`、`writing-more-menu`、
`deep-import-map-next`、`conflict-ai-review` 及 ConflictDetailDialog 内 8 个行动态 action
（`copy-conflict-suggestion` / `apply-conflict-suggestion` / `locate-conflict` / `open-conflict-source` /
`resolve-conflict` / `ignore-conflict` / `later-conflict` / `generate-conflict-suggestion`）、
`data-conflict-item-id`、`data-scene-cockpit-project`、`data-cockpit-module`、`data-panel`、
`data-version` / `data-latest`。

**role / 可访问名称**（e2e `getByRole({name})` 直接依赖，改文案必须同步测试）：

- 按钮名：「新建章节」「创建第一章」「打开第 N 章…」（ChapterRow 动态 aria-label）、「上一章」
  「下一章」「历史」「比较」「展开章节/收起章节」「收起写作副驾驶/展开」（动态）、「打开第 N 章」
  （OutlineFloat）、「专注模式」「保存工作稿」「保存为新工作稿」「放弃未设为正式正文的更改」
  「设为正式正文」「继续设为正式正文」「确认恢复」「基于此版本创建」「预览」「定位正文/无正文定位」
  「打开来源/无可打开来源」「生成 AI 修复建议」「补充 AI 软冲突判断」「稍后」「完整编辑器」。
- dialog 名：「自动提取」「剧情设定冲突检查选项」「剧情设定冲突检查」「版本历史」
  「深度导入快照状态」；aria-label：「章节正文」「移动端速记正文」「选择章节版本」
  「写作字数仪表盘」「左侧版本/右侧版本」；rail：「章节」「写作副驾驶」。
- tab：「警报/人物/地点/设定/地图」（role=tab，`.active` class 断言）。
- 结构 role：`role=tablist`（`.cockpit-tabs`）、`role=alert`（章节列表失败、版本加载失败）、
  `role=status`（`.mobile-note-status`、冲突条无 latest 时）、`role=table`（版本 diff 网格）、
  冲突条 `role=button`（有 latest 时）。

**class 契约**：`.writing-toolbar`（`waitWritingReady` 入口，helpers/workbench.js）、
`.writing-workspace-layout`、`.writing-tree-rail` / `.writing-panel-rail` + `.is-collapsed`、
`.scene-tree-label`、`.scene-cockpit`、`.cockpit-panel`、`.writing-version-history-item`、
`.writing-conflict-item`、`.mobile-quick-note`、body `.focus-mode-active`、
`details.writing-tools-menu` 结构（被 `openWritingToolMenu` 依赖）。
三主题改造新增：`.writing-statusbar` / `.writing-statusbar__right` / `.writing-statusbar__font` /
`.writing-statusbar__focus`（状态栏）；shell 级 `.topbar-theme` / `button.theme-dot[data-theme-value]`
（主题三点切换器，视觉快照经 `SEL.themeOption(theme)` 消费）。
集中登记处：`e2e/helpers/selectors.js`。

**样式文件现状（三主题改造后）**：

- `writing-desk.css` 已按新设计语言整体重写，继续承担写作页页面级样式（章节树行密度、稿纸构图、
  状态栏、cockpit 模块密度、MobileQuickNote 布局）；旧「归并策略」所列行号全部失效，残留归并项
  执行时按源码重新清点。
- 新增 `writing-decorations.css`：编辑区点缀与 ink 水印字，硬规则见主规范 §2 点缀系统；
  shell 级点缀（顶栏品牌区、左栏导航底部）在 `editorial-theme.css` 末尾分节。
- 全局视觉权威层分工（颜色/圆角/阴影归 editorial-theme.css，结构归 styles.css）不变，
  见主规范 §1.1。

## 8. 验收标准 + 验证命令

**验收标准**：

1. §5 状态覆盖清单逐条可走通，特别是待新增的加载骨架、加载失败 error-card、保存失败重试。
2. 正文排版 = 14px / 行高 2.0 / 编辑区左右 padding 59px，页面级值有注释说明，无游离 px 字号
   （新触碰代码）。
3. 每个 class 的视觉规则只剩一个权威层（主规范 §1.1）；旧三层冲突清单（§2-6）残留项按源码
   清点消解。
4. 主对象契约不回退：三栏固定 238 / 弹性 / 257；390px 无横向溢出。
5. §7 全部契约钩子在位：`#id` 16 个、data-action、role/可访问名称零意外变更；
   文案改动（如专注模式入口）已全局同步 e2e。
6. 「聚焦模式」测试债已解决（改测试名或改 UI 文案，二选一并记录）；三主题视觉基线已重录。
7. 主规范 §8 无障碍：触控档按钮 ≥42px、focus-visible 2px accent 环不被 desk 层
   `outline/box-shadow` 覆写（`.writing-sheet .novel-editor:focus { box-shadow: none }` 只清
   稿纸光晕、不动全局 outline 环，执行时核实）。

**验证命令**（工作目录 `frontend-console/`）：

```bash
# 功能 e2e（writing 页主契约）
npx playwright test e2e/writing.spec.js

# 视觉基线（仅 darwin 有基线；共 3 个用例 5 张快照：
# writing-desk-{sticky,night,ink}.png、writing-focus-sticky.png、writing-mobile-390-sticky.png）
npx playwright test e2e/visual-writing.spec.js

# 全局基建回归（主题 token / 排版 token / 骨架屏 / 模态无障碍，受样式归并影响时必跑）
npx vitest run tests/editorialTheme.test.js tests/typographyTokens.test.js \
  tests/loadingSkeleton.test.js tests/modalAccessibility.test.js   # 文件名执行时核实

# 文档漂移门禁（仓库根目录）
make docs-check BASE_REF=origin/main
```

改动样式后视觉快照需 `--update-snapshots` 重建 darwin 基线并在 PR 中说明；非 darwin 平台按
`VISUAL_BASELINE=1` 流程生成本地快照核对（visual-writing.spec.js）。
