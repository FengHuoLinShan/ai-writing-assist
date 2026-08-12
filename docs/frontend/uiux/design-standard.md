# NovelCraft 前端设计标准（三主题体系）

> 本文件是全站 UI/UX 的唯一权威设计标准。分页执行规范见 `pages/` 目录。
> 当前生效的是三主题换肤体系：`sticky`（晨光便签，浅色默认）/ `night`（暗夜书房，深色）/
> `ink`（水墨写意，纸色），经 `<html data-theme="…">` 换肤，`:root` 即 sticky。
> 视觉表达唯一权威仍是 `frontend-console/editorial-theme.css`：全部色值集中在 `--nc-*`
> 原语层，语义层与 `--archive-*` 兼容别名只做转发，业务样式不直写色值。
> 权威背景：`docs/modules/14_frontend.md`「内容优先布局契约」（styles.css 管结构、
> editorial-theme.css 管视觉表达、主对象占分栏宽 64–68%）。本标准与该契约一致，不推翻它。
> 旧「Editorial Archive」设计语言（folio 页码、章字水印、网格纸底、藏青侧栏、3px 顶条、
> first-letter 朱红等）已随三主题改造移除，本文不再描述；历史方案见归档报告，不作当前依据。

## 0. 设计原则与决策优先级

决策优先级（冲突时从上往下让路）：

1. UX（操作路径短、反馈明确）
2. 信息层级（Primary/Secondary/Tertiary 一眼可辨）
3. 清晰度（作者/读者语言，不暴露 raw ID、JSON、内部枚举）
4. 一致性（相同语义 = 相同视觉语言）
5. 使用效率（工作台密度优先，不为"现代感"稀释信息）
6. 视觉质量
7. 动效与装饰

建立高级感的手段排序：**Typography + Spacing + Alignment > 色彩对比 > 边框/分割线 > 阴影 > 装饰**。

### AI UI 反模式（本产品适用判断）

本产品无渐变/glow/glassmorphism/蓝紫 SaaS 模板问题，需警惕的是：

- Card 套 Card、所有区块都套卡 —— 用留白与字层级分节，卡片只给"可独立移动的条目"（项目卡、审核候选、任务卡）。
- Badge/Pill 泛滥 —— 计数角标只给「待处理」语义（见 §2 强调色使用约束），状态用文字+色点，不用彩色 pill 堆叠。
- 每个标题前加装饰 icon —— 图标只在导航、按钮动作、状态指示出现。
- 每个 Section 长得一样 —— 页面第一焦点区域允许有独特构图。
- 降低密度换"呼吸感" —— 审核队列、表格、列表保持工作台密度；安静感靠节奏不靠放大。

## 1. Token 体系

### 1.1 分层契约

| 文件 | 职责 | 拥有哪些 token / 规则 |
|---|---|---|
| `styles.css` | 结构与排版 | 字体族、字阶、行高、字间距、间距、缓动、布局尺寸、`--radius-full`；ink 主题的字体族覆写也在这里（只覆写字体，不写色值） |
| `editorial-theme.css` | 视觉表达（唯一权威） | 全部颜色（`--nc-*` 原语 + 语义层 + `--archive-*` 别名）、圆角档位、阴影、线条；shell 级点缀分节 |
| `vue/views/writing/writing-desk.css` | 写作页页面级样式 | 写作页三栏内的组件结构与页面材质（章节树、稿纸、状态栏、副驾驶密度） |
| `vue/views/writing/writing-decorations.css` | 写作页点缀 | 编辑区点缀与水印字，硬规则见 §2「点缀系统」 |

关键纪律：

- `--nc-*` 原语层是唯一允许写色值的一层；`:root` 承载 sticky 默认值，
  `[data-theme="night"]` / `[data-theme="ink"]` 只覆写 `--nc-*`。
- 语义层（`--bg-*` / `--text-*` / `--accent` / `--border` / `--line-*` 等）全部从 `--nc-*` 转发，
  是业务样式的唯一入口。
- `--archive-*` 保留为转发别名（writing-desk.css 等仍在消费），不再承载独立色值；
  新增代码一律直接用语义层，不再新增 `--archive-*` 引用。
- 契约测试：`frontend-console/tests/editorialTheme.test.js`、`typographyTokens.test.js`。

### 1.2 颜色 token

**`--nc-*` 原语层（三主题值表，sticky = `:root` 默认）：**

| Token | sticky 晨光便签 | night 暗夜书房 | ink 水墨写意 | 角色 |
|---|---|---|---|---|
| `--nc-bg` | `#FFFFFF` | `#111114` | `#F7F3EA` | 页面底 |
| `--nc-surface` | `#FAFAF9` | `#1A1A1F` | `#FDFBF4` | 抬升表面（卡片/面板/顶栏/稿纸） |
| `--nc-surface-muted` | `#F2F2F0` | `#26262C` | `#EAE5D6` | 沉底表面（轨道/禁用/分隔带） |
| `--nc-ink` | `#37352F` | `#E5E2DC` | `#1F2321` | 主墨色/强调文字 |
| `--nc-body` | `#55534F` | `#C6C2BB` | `#3C413E` | 正文文字 |
| `--nc-dim` | `#9B9A97` | `#8A8680` | `#93A09A` | 辅助文字 |
| `--nc-faint` | `#B9B7B2` | `#5A5852` | `#B4AEA0` | 非必要元数据 |
| `--nc-ghost` | `#D8D7D2` | `#3E3C38` | `#CFC8B8` | 占位/禁用 |
| `--nc-accent` | `#2383E2` | `#D9A441` | `#C03F2B` | 主题强调色（蓝/金/朱砂） |
| `--nc-accent-soft` | accent 10% | accent 12% | accent 10% | 强调色底 |
| `--nc-hairline` | `#E9E9E7` | `#26262A` | `#D8D2CC` | 结构线（1px） |
| `--nc-hairline-strong` | `#D9D9D6` | `#3A3A41` | `#C4BCB0` | 强结构线（1px） |
| `--nc-alert-bg` | `#FBE4E4` | `#221B10` | `#F3EDE0` | 警示条底（副驾驶警报卡等） |
| `--nc-alert-ink` | `#D64F47` | `#D9A441` | `#C03F2B` | 警示条文字 |
| `--nc-deco` | `#F2F2F0` | `#26262C` | `#E7E1D2` | 点缀近底色（§2 点缀系统） |
| `--nc-success(-soft)` | `#3A7D5C` | `#7DB399` | `#4A7A5C` | 成功 |
| `--nc-warning(-soft)` | `#B07A1E` | `#D9A441` | `#9A6B1F` | 警告 |
| `--nc-error(-soft)` | `#D64F47` | `#D4715F` | `#C03F2B` | 错误/危险 |

**语义层（业务样式唯一入口，全部转发自 `--nc-*`）：**

| 语义 | Token | 转发来源 |
|---|---|---|
| 背景 | `--bg-base / --bg-panel / --bg-elevated / --bg-hover / --bg-active` | nc-bg / nc-surface / nc-surface / nc-ink 5% / nc-ink 9% |
| 文字 | `--text-primary / --text-body / --text-secondary / --text-tertiary / --text-quaternary` | nc-ink / nc-body / nc-dim / nc-faint / nc-ghost |
| 强调 | `--accent / --accent-hover / --accent-soft / --accent-glow` | nc-accent / accent 85%+ink / nc-accent-soft / nc-accent-soft |
| 语义色 | `--success(-soft)`、`--warning(-soft)`、`--error(-soft)`、`--info(-soft)` | 对应 `--nc-*`；info = nc-accent |
| 边框 | `--border / --border-light / --border-dim` | 均 = nc-hairline |
| 线条 | `--line-subtle / --line-default / --line-accent / --line-active` | 1px hairline / 1px hairline-strong / 1px accent / 1px accent |

**1px hairline 纪律**：全站线条一律 1px（含选中态 `--line-active` 与页签激活下划线），
禁止 2px/3px 边线表达层级；层级靠表面明度差、字阶与留白，阴影克制（§1.4）。

### 1.3 排版 token（styles.css 保留）

| 类别 | Token 与值 | 说明 |
|---|---|---|
| 字体族 | `--font-ui` 系统无衬线栈（栈首 `"MiSans"`）；`--font-body` Noto Serif SC 衬线栈；`--font-mono` JetBrains Mono 首位不变 | 分工见 §3；只引系统字体栈，不打包 webfont |
| ink 主题字体覆写 | `[data-theme="ink"]`：`--font-body: "LXGW Bright","LXGW WenKai","Noto Serif SC","Source Han Serif SC",…`；`--font-ui` 以 PingFang SC 栈首 | 系统未装时优雅回退；只覆写字体族 |
| 字阶 | `--text-xs:11 / -sm:13 / -base:14 / -md:16 / -lg:20 / -xl:24 / -2xl:36 / -3xl:48 / -4xl:56` | 使用矩阵见 §3，`2xl+` 仅限营销式入口页（home） |
| 行高 | `--leading-tight:1.1 / -snug:1.3 / -normal:1.5 / -relaxed:1.6 / -loose:1.8` | |
| 字间距 | `--tracking-tight:-0.01em`（大标题）、`--tracking-normal:0`、`--tracking-wide:0.045em`（mono 元数据/顶栏仪表盘）、`--tracking-caps:0.08em`（logo/全大写标签） | |

### 1.4 间距 / 圆角 / 阴影 / 缓动 / 布局尺寸

- 间距：`--space-1:4 → --space-24:96`（4px 基数），**组件样式只允许引用 `--space-*`，禁止直写像素**（1px hairline 与触控目标 ≥42/44px 除外）。存量直写像素随页面执行逐步归 token，新增/触碰的代码必须归 token。
- 圆角（editorial-theme 权威）：`--radius-sm:2 / -md:3 / -lg:4 / -xl:5 / -2xl:6 / -full:9999px`（full 仅用于头像/色点）。组件默认 `sm/md`；卡片 `md`；模态/抽屉 `lg`。
- 阴影（editorial-theme 权威）：`--shadow-sm`（1px 沉线）→ `--shadow-xl/--shadow-float`。**阴影只用于浮层**（模态/抽屉/下拉/toast/浮动面板）；静态卡片用 `--line-subtle` + surface，不用阴影。
- 缓动：`--ease-default / -out / -in-out / -spring`；过渡时长 `--dur-fast:120ms / --dur-base:200ms / --dur-slow:320ms`（styles.css）。
- 布局尺寸（styles.css）：`--topbar-height:57px`、`--sidebar-width:211px`、`--workspace-main-share:64fr`、`--workspace-side-share:18fr`、`--workspace-rail-left-min:176px`、`--workspace-rail-right-min:190px`、`--workspace-rail-collapsed:44px`。写作页不使用 fr 份额，固定三栏：章节树 238px / 正文弹性 / 写作副驾驶 257px（详见 `pages/writing.md`）。

### 1.5 主题切换与持久化

- 主题控制器：`vue/shell/composables/useTheme.js`；持久化 key 为 `nc-theme`（localStorage）。
  首次启动从旧 key `novel_theme` 迁移并删除旧 key；legacy 值映射：`light/minimal→sticky`、
  `dark/dark-soft→night`、`paper/warm→ink`。
- 无任何存储时跟随系统 `prefers-color-scheme`（dark → night，其余 → sticky），此时不落存储。
- 切换入口：顶栏三点切换器（`ThemePicker.vue`，`.topbar-theme` radiogroup +
  `button.theme-dot[data-theme-value]`，白/黑/朱砂三个圆点，active 描边环，支持方向键切换）。
- 换肤过渡：`background-color` / `color` / `border-color` 250ms；`prefers-reduced-motion` 下全部关闭。

### 1.6 RP 路径专有 token

`--rp-accent:#2466d1`、`--rp-accent-soft:#eef4ff`、`--rp-confirm-*`（styles.css）是 RP 沉浸路径的
独立强调色系，与三主题体系无关。**处置**：RP 路径保留独立强调色（它是刻意的第二外观），
作为正式 token 块并注释语义（"RP 沉浸路径强调色"），禁止在作者工作台页面出现。
详见 `pages/rp-experience.md`。

## 2. 色彩策略

- **表面三层**：`--nc-bg`（页底）→ `--nc-surface`（卡片/面板/稿纸）→ `--nc-surface-muted`
  （沉底/轨道）。层级靠表面明度差 + 1px hairline，不靠阴影。
- **强调色使用约束**（原「朱红白名单」；各主题 accent 不同——sticky 蓝 / night 金 / ink 朱砂；
  以下用途之外新增使用需回改本表）：
  1. 主操作按钮（每屏至多一个 primary，accent 实心 + 白字，见 §5.1 Button）
  2. 「待处理」计数角标（today attention、world review、sidebar badge）
  3. focus-visible 描边（2px accent 环，全站统一，editorial-theme.css 全局覆盖，不得移除）
  4. 危险/错误语义（`--nc-error` 系）
  5. 索引性点缀（logo-mark、topbar 章节分隔、选中态 `--line-active`、页签激活 2px 下划线）
- **警示条**：`--nc-alert-bg` 底 + `--nc-alert-ink` 文字（如写作副驾驶警报卡），
  与 accent 分工明确，不互相替代。
- **语义色**：success / warning / error 各主题值见 §1.2 表。状态表达优先"文字 + 色点或
  1px 边线"，不用整面彩色填充。
- **硬编码 hex**：业务样式不直写色值（唯一例外是 `--nc-*` 原语层本身与 RP 路径 token 块，
  §1.6）；存量 hex 随页面执行逐步归 token。

### 点缀系统（装饰纪律）

点缀是唯一允许的纯装饰，规则为硬约束（实现：`writing-decorations.css` 编辑区部分 +
`editorial-theme.css` 末尾 shell 级分节）：

- **落点只有三处**：顶栏品牌区；写作页编辑区（右上 1 组 + 正文下方 1 组）；左栏导航底部。
  单屏封顶 = 编辑区上 1 组 + 下 1 组 + 左栏 1 组。数据区（表格、列表、表单、卡片内容）零装饰。
- **近底色**：一律取 `--nc-deco` / `--nc-surface-muted` 系，不使用 accent 或语义色。
- **不干扰交互**：全部 `pointer-events:none`，z-index 低于内容。
- **自动隐藏**：`body.focus-mode-active` 与 ≤760px 一律隐藏。
- 各主题母题：sticky = 横条纹×3 / 点阵稿纸角 / 小便签 / 便签堆；night = 弯月 / 微星≤3 /
  地平线 1px 微光 / 孤星；ink = 墨痕淡叶 / 水印字（`#writing-editor-container` 的
  `data-watermark` 属性 = 当前章标题首字，`::after` 渲染）/ 朱砂印章×1 / 小墨枝 / 隶字「墨」。

## 3. Typography 标准

### 3.1 字族分工

| 字族 | 用于 | 禁止用于 |
|---|---|---|
| `--font-ui`（无衬线） | 全部界面控件、标签、表单、列表、导航 | 长正文 |
| `--font-body`（衬线） | 页面标题、作品标题、正文阅读（writing 编辑区、interaction 消息流）、logo | 按钮/表单/元数据 |
| `--font-mono` | 字数仪表盘、计数、ID 类元数据、顶栏技术信息、写作页状态栏 | 正文、标题 |

### 3.2 字阶使用矩阵（层级靠字，不靠边框和卡）

| 角色 | size | weight | leading | tracking | color |
|---|---|---|---|---|---|
| 页面标题（view-header） | `--text-xl` 24 | 700 衬线 | snug | tight | `--text-primary` |
| 区块标题（section） | `--text-md` 16 | 600 | snug | normal | `--text-primary` |
| 条目标题（卡片/列表行主文案） | `--text-base` 14 | 600 | normal | normal | `--text-primary` |
| 正文/控件 | `--text-base` 14 | 400 | normal | normal | `--text-body` |
| 辅助说明（helper） | `--text-sm` 13 | 400 | normal | normal | `--text-secondary` |
| 元数据（时间/计数/标签） | `--text-xs` 11 | 400/500 mono 可选 | normal | wide | `--text-tertiary` |
| 占位/禁用 | `--text-sm` 13 | 400 | normal | normal | `--text-quaternary` |

规则：

- 一页内字阶跨度 ≤ 4 级；标题下不再有"副标题+说明+注释"三级小字堆叠，至多两级。
- 长正文阅读：writing 编辑区 14px / 行高 2.0（页面级值，见 `pages/writing.md` §4.2）；
  interaction 消息流沿用 `--text-md` 16 / `--leading-loose` 1.8。
- 标题不加装饰 icon（导航与按钮动作除外）。

## 4. Spacing 与布局标准

- **节奏**：垂直节奏以 `--space-4`(16) 为基准单位；区块间隔 `--space-8`(32)；区块内条目间隔 `--space-3`(12) 或 `--space-4`；紧凑表格/队列 `--space-2`(8)。
- **padding 三档**（收敛目标）：紧凑（表格行、队列条目）`--space-2 --space-3`；默认（卡片、面板）`--space-4`；宽松（模态、空态、表单区块）`--space-6`。新增/触碰代码不允许第 4 档。
- **分隔优先级**：留白 > 字层级 > 1px hairline（`--line-subtle`）> 表面差。禁止"留白 + 分割线 + 卡片边框"三重叠加。
- **内容优先布局契约**（docs/modules/14_frontend.md「内容优先布局契约」）：工作台页主对象占分栏宽 64-68%（`--workspace-main-share:64fr`），左右 rail 不低于 `--workspace-rail-*-min`；写作页例外地使用固定三栏（238px / 弹性 / 257px），主对象仍为弹性中栏；720px→760px 合并后单栏；390px 不允许页面级横向溢出。
- **对齐**：同一列的控件左对齐到同一栅格线；表单 label/控件/helper 使用统一缩进链；数字右对齐或等宽。

## 5. 组件标准

> 现状：无组件库，组件 = styles.css 全局 class（"定义"）+ editorial-theme.css 覆写（"材质"）两步；
> 写作页组件另有 writing-desk.css 页面级规则。
> 目标：每个组件的**视觉规则收敛到 editorial-theme.css 一处**，styles.css 只留结构尺寸；
> 以下为各组件的终态标准与 class 锚点（行号随样式文件演进而漂移，以源码为准）。

### 5.1 Button（`.btn` 族）

| 变体 | 语义 | 视觉 |
|---|---|---|
| `.btn-primary` | 每屏至多一个的主操作 | 主题 accent 实心 + 白字，hover 加深（`--accent-hover`） |
| `.btn-ghost` | 次操作 | 透明底 + `--line-default` 边 |
| `.btn-text` | 三级/行内操作 | 无边无底色，hover 出 `--bg-hover` |
| `.btn-danger` / `.btn-warning` | 破坏性/警示 | 文字/边框用 `--error`/`--warning`，非实心填充（确认模态中的最终破坏按钮除外） |
| `.btn-sm` | 表格/队列行内 | 高度 28px（桌面） |
| `.btn-icon` | 纯图标 | 32px 方，图标必须带 aria-label |

状态矩阵（全部按钮必须具备）：hover（`--bg-hover` 或加深）/ active（`--bg-active`）/ focus-visible（2px accent 环，editorial-theme.css 已全局覆盖，不得移除）/ disabled（`--text-quaternary` + 禁止 pointer，不只做颜色变淡）/ loading（spinner 替换图标，宽度不抖动）。

规则：一行按钮组最多 1 个 primary；破坏操作不放在顺手位置（列表行尾、模态右下角的预期位置是"确认"非"删除"）；触控档（≤760px）按钮高 ≥42px。

### 5.2 输入（`.input-field` 等）

- 结构：label（`--text-sm` secondary，控件上方 `--space-1`）→ 控件 → helper/error（`--text-xs`，error 用 `--error`）。
- 控件：底 `--bg-elevated`、边 `--line-default`、radius `--radius-sm`、高 36px（桌面）/ ≥44px（触控）。
- 状态：hover 边加深 → focus 边 `--nc-ink` + accent 环 → disabled 底 `--nc-surface-muted` → error 边 `--error` + helper 变错文。
- 可编辑区域与只读内容必须可区分（输入控件有明确边界，只读文本无框）。

### 5.3 Card（`.card` 族）

- 只用于"可独立移动的条目"（项目卡、审核候选、任务卡）；**不做页面分区容器**——分区用留白 + 区块标题。
- 结构：padding `--space-4`；标题（条目标题档）→ 内容 → meta 行（`--text-xs` tertiary）；操作放右上或底部 meta 行内。
- 视觉：`--nc-surface` + `--line-subtle`，无阴影；hover 仅可点击卡片有反馈（边加深或 `--bg-hover` 淡入），静态卡不做 hover 浮起。
- 禁止 Card 套 Card；卡内需要子分区时用 `--line-subtle` hairline。

### 5.4 Table

- 表头：`--text-xs` + `--tracking-wide` + secondary 色 + 底 hairline；不加底色块。
- 行高紧凑（`--space-2 --space-3` padding）；行分隔用 `--line-subtle`，不用斑马纹。
- 行 hover `--bg-hover`；选中行 `--bg-active` + 左侧 `--line-active`（1px accent）。
- 数字列右对齐等宽；操作列右对齐，行内操作用 `.btn-text`/`.btn-icon`。

### 5.5 Tabs / subnav（`.subnav` 族）

- 形态：文字 tab + 底部指示（激活 2px accent 下划线；仅"需处理"语义 tab 允许 accent 色点计数）。
- 激活 tab：`--text-primary` + 600；未激活：`--text-secondary`，hover 转 body 色。
- 一级视图导航（sidebar）与页面内 subnav 视觉分级明确，不互相模仿。

### 5.6 Modal（`.modal-*`；`ui/modal.js` 命令式服务）

- 宽度三档：确认 400px / 表单 560px / 复杂内容 720px；radius `--radius-lg`；阴影 `--shadow-float`。
- 结构：标题（区块标题档）→ 内容 → 按钮行（右对齐，主右次左）；破坏确认的主按钮文案写动作本身（"删除作品"而非"确定"）。
- 焦点陷阱、inert 背景、Esc 关闭由 `ui/modal.js` 保证（modalAccessibility.test.js 契约），视觉改动不得破坏。

### 5.7 Toast（`.toast`；`ui/toast.js`）

- 4 类型（success/info/warning/error），左 3px 语义色线 + `--nc-surface` 底；最多 3 条可见。
- 保存反馈用 toast（"已保存"），成功操作不弹模态。

### 5.8 Badge / 计数 / 状态点

- 待处理计数：accent 小圆点 + 数字（mono），只用于「需要人工处理」语义（review 队列、attention）。
- 状态（草稿/已采纳/进行中…）：文字 + `--text-secondary`，必要时前置 6px 色点（语义色）；不用彩色 pill 底。
- 标签（分类/体裁）：`--line-subtle` 描边小胶囊，中性色，不染色。

### 5.9 Empty / Loading / Error（状态三件套）

- **Empty**：`.empty-state`——图标或短句 + 一句引导 + 主行动按钮（`.empty-state-cta`）。首次进入页必须有引导型空态，不允许裸空白。
- **Loading 归一**：区块加载 = `.loading-skeleton`（骨架屏，reduced-motion 下禁动画，loadingSkeleton.test.js 契约）；行内等待 = `.loading`（dots）；后台工作流 = `.workflow-progress*` / `WorkflowProgressCard.vue`。新代码不得发明第四种。
- **Error 统一**：以 `.error-card` 为基准收敛视图级散装错误样式：错误图标/色 + 一句人话说明 + 可执行动作（重试/返回），技术细节折叠到次级。

### 5.10 搜索 / 筛选栏 / 批量操作条

- 搜索框：页面内容区顶部左对齐，宽 240-320px，带清空按钮；结果计数紧随。
- 筛选面板：默认收起为一行摘要（"3 个筛选生效"），展开为面板；不常驻占据首屏。
- 批量操作条：选中时出现，附着于列表顶部（不是浮动悬浮条），显示"已选 N" + 操作组 + 退出。

## 6. 响应式标准

- **断点终态**：`760px`（主，触控/单栏切换，与文档承诺一致）、`1100px`（桌面密排/宽松切换）。`720px` 全部合并到 `760px`；长尾断点（390/460/480/560/600/640/900/980/1180 等）逐个审查：可归入两档的归入，确属局部组件自适应的保留并在该行注释理由。
- **四档行为**：Desktop（≥1440 内容区限宽居中，工作台不限宽）/ Laptop（1100-1440 默认形态）/ Tablet（760-1100 收窄 rail，可折叠）/ Mobile（<760 单栏、底栏导航、触控目标 ≥42/44px）。
- 移动端不是桌面缩小：writing → MobileQuickNote；map → 只读浏览 + 编辑转交桌面；其余页至少保证单栏不溢出、主操作可达。
- 页面级横向溢出零容忍（390px）。
- 点缀系统 ≤760px 一律隐藏（§2 点缀系统）。

## 7. 交互与动效标准

- 所有可点元素具备 hover/focus-visible/active/disabled 四态；反馈时长 `--dur-fast`（hover）/ `--dur-base`（面板开合）/ `--dur-slow`（模态）。
- 缓动：入场 `--ease-out`，退场 `--ease-in-out`，弹性仅用于轻量提示（`--ease-spring` 不用于大面板）。
- `prefers-reduced-motion`：骨架屏/流式/进度/主题切换过渡全部降级，新增动画必须补。
- 长任务必须有进度反馈（workflow-progress），不允许只有 spinner 超过 2s。
- 操作反馈闭环：点击 → 立即视觉反馈（active/disabled+loading）→ 结果（toast/内容更新）；异步操作按钮在 pending 期间禁用。

## 8. 无障碍标准

- 对比度：正文 ≥ 4.5:1；辅助文字（`--text-secondary` = `--nc-dim`）≥ 4.5:1 需逐主题核验；
  `--text-tertiary` 仅用于非必要元数据；`--text-quaternary` 仅占位/禁用。更换或新增主题色值时
  必须重核三主题全部文字/底色组合。
- focus-visible 2px accent 环全站统一，不得 `outline: none` 而无替代。
- 触控/点击目标：桌面 ≥28px，触控 ≥42px（按钮）/44px（输入）。
- 语义结构：每页单一 h1（view-header），区块 h2；列表用 ul/li 或 role=list；图标按钮必有 aria-label（subnavAccessibility.test.js 等契约）。
- 键盘：模态焦点陷阱、Esc 关闭、表单可全程键盘完成；主题三点切换器支持方向键。

## 9. 文案与命名一致

| 现状冲突 | 位置 | 裁定 |
|---|---|---|
| project 页 =「作品档案」vs「导入与整理」 | 路由标题 vs 侧边栏更多菜单 | 统一为「作品档案」；侧边栏项改为「作品档案与导入」 |
| today =「今日工作」vs「首页」 | 同上 | 统一为「首页」，view-header 显示「今天」语义化问候可保留 |
| `data-workspace-view` 仅作样式钩子 | docs/modules/14_frontend.md | 维持，不得被业务/测试依赖 |

改可访问名称必须全局 grep 同步 e2e 的 `getByRole({name})` / `getByText`。

## 10. 死代码与清理清单（执行时逐项核对）

本轮三主题改造已完成：styles.css 三套旧主题色板死代码删除；兼容别名层收敛为
`--archive-*` 转发别名；styles.css 头部失效文档引用改指本文件；旧 Editorial Archive
装饰（folio 页码、章字水印、网格纸底、藏青侧栏、3px 顶条、first-letter 朱红、settings ⚙︎
装饰）随 editorial-theme.css 瘦身移除。仍待处理（均与主题无关）：

1. 孤儿文件 `frontend-console/shared/assetDisplayState 2.js`——确认无引用后删除。
2. 非 scoped SFC 内联样式（CommandPalette.vue、ShellApp.vue、GenerateView.vue、
   InteractionView.vue 等，执行时重新清点）——收编全局或改 scoped。
3. 尾部补丁层（styles.css 若干"一致性补充"区块）——随各页面执行逐步归并入组件主规则，
   不单独一次性大搬移。
4. 存量 `!important`——每处评估，能靠层叠解决的全部消除。
5. 假命令 `:save`/`:export`（commands.js，只 toast 不执行）——**记录上报产品决定，不在
   UI 执行范围内擅自处理**。
