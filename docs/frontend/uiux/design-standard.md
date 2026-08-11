# NovelCraft 前端设计标准（Editorial Archive 提纯版）

> 本文件是全站 UI/UX 的唯一权威设计标准。分页执行规范见 `pages/` 目录。
> 定位：不是重新设计，而是把已生效的「Editorial Archive」主题语言（`frontend-console/editorial-theme.css`）
> 提纯为唯一事实层，消除三层 token 间接、补丁式样式与断点漂移。
> 权威背景：`docs/modules/14_frontend.md`「内容优先布局契约」（styles.css 管结构、
> editorial-theme.css 管视觉表达、主对象占分栏宽 64–68%）。本标准与该契约一致，不推翻它。

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
- Badge/Pill 泛滥 —— 计数角标只给「待处理」语义（见 §2 朱红白名单），状态用文字+色点，不用彩色 pill 堆叠。
- 每个标题前加装饰 icon —— 图标只在导航、按钮动作、状态指示出现。
- 每个 Section 长得一样 —— 页面第一焦点区域允许有独特构图（如 today 的 resume 卡）。
- 降低密度换"呼吸感" —— 审核队列、表格、列表保持工作台密度；安静感靠节奏不靠放大。

## 1. Token 目标体系（终态）

### 1.1 分层契约（保持现有两文件分工，消除第三层）

| 文件 | 职责 | 拥有哪些 token |
|---|---|---|
| `styles.css` | 结构与排版 | 字体族、字阶、行高、字间距、间距、缓动、布局尺寸、`--radius-full` |
| `editorial-theme.css` | 视觉表达（唯一权威） | 全部颜色（背景/文字/强调/语义/边框/线条）、圆角档位、阴影 |

执行要点：

- 删除 `styles.css:8-138` `:root`、`:141-199` dark、`:268-500` warm 中**所有颜色/圆角/阴影定义**（死代码，全部被覆层改写）；保留字体/字阶/间距/缓动/布局尺寸。
- 删除 `styles.css:4` 对不存在的《NovelCraft_设计规范文档_v2.0.md》的引用，头部注释改为指向本文件。
- 修正 `[data-theme="warm"]` 块错位（styles.css:268 插在 topbar 与布局章节之间）——随死代码删除自然消解。
- 兼容别名层（styles.css:120-137、184-198）逐个 grep 引用后处理：仍被引用的别名**迁移到 editorial-theme.css 的 `:root`**（该层已在 49-53 行定义了 `--panel/--panel-alt/--selected/--hover/--hover-bg`），未被引用的一律删除。
- 同步更新契约测试：`frontend-console/tests/editorialTheme.test.js`、`typographyTokens.test.js`。

### 1.2 颜色 token（值 = editorial-theme.css 现行值，提纯不改色）

**Archive 基底（仅 editorial-theme.css 定义，业务样式不直接引用，经下方语义层消费）：**

| Token | minimal | warm | dark | 角色 |
|---|---|---|---|---|
| `--archive-paper` | `#f2efe6` | `#f4eadc` | `#17232a` | 页面纸面 |
| `--archive-paper-raised` | `#fbf8ef` | `#fff8ed` | `#1e2d34` | 抬升表面（卡片/面板/顶栏） |
| `--archive-paper-muted` | `#e7e3d8` | `#e8d8c5` | `#26373e` | 沉底表面（轨道/禁用/分隔带） |
| `--archive-ink` | `#152e3e` | `#283c47` | `#e6e0d4` | 主墨色/结构色 |
| `--archive-ink-soft` | `#345060` | `#5b6670` | `#b7b5ad` | 次墨色 |
| `--archive-red` | `#a63b2f` | `#a44835` | `#d46a59` | 朱红索引（限量，见 §2） |
| `--archive-red-soft` | `rgba(166,59,47,.12)` | 同左派生 | `rgba(212,106,89,.15)` | 朱红底 |
| `--archive-rule` | ink 28% | 27% | 25% | 结构线 |
| `--archive-rule-strong` | ink 58% | 56% | 52% | 强结构线（顶栏下沿等） |
| `--archive-grid` | ink 3.5% | red 3% | 2.5% | 纸面网格纹理 |

**语义层（业务样式唯一入口）：**

| 语义 | Token | minimal 值 |
|---|---|---|
| 背景 | `--bg-base / --bg-panel / --bg-elevated / --bg-hover / --bg-active` | paper / paper-raised / `#fffdf7` / ink 6.5% / ink 10.5% |
| 文字 | `--text-primary / --text-body / --text-secondary / --text-tertiary / --text-quaternary` | ink / `#243943` / `#5e6c70` / `#8b918e` / `#c9c7bd` |
| 强调 | `--accent / --accent-hover / --accent-soft / --accent-glow` | ink / `#0b202d` / ink 9% / red 17% |
| 语义色 | `--success(-soft)` `#356a55`、`--warning(-soft)` `#9a651d`、`--error(-soft)`=red、`--info(-soft)`=ink | dark 主题分别为 `#7db399 / #d3a963 / red` |
| 边框 | `--border / --border-light / --border-dim` | rule / ink 16% / ink 12% |
| 线条 | `--line-subtle / --line-default / --line-accent / --line-active` | 1px light / 1px rule / 2px ink / 3px red |

### 1.3 排版 token（styles.css 保留）

| 类别 | Token 与值 | 说明 |
|---|---|---|
| 字体族 | `--font-ui` 系统无衬线栈；`--font-body` Noto Serif SC 衬线栈；`--font-mono` JetBrains Mono | 分工见 §3 |
| 字阶 | `--text-xs:11 / -sm:13 / -base:14 / -md:16 / -lg:20 / -xl:24 / -2xl:36 / -3xl:48 / -4xl:56` | 使用矩阵见 §3，`2xl+` 仅限营销式入口页（home） |
| 行高 | `--leading-tight:1.1 / -snug:1.3 / -normal:1.5 / -relaxed:1.6 / -loose:1.8` | |
| 字间距 | 现状 `--tracking-tight/-normal` 均为 0（形存实亡）。**修正**：`--tracking-tight:-0.01em`（大标题）、`--tracking-normal:0`、`--tracking-wide:0.045em`（mono 元数据/顶栏仪表盘沿用）、新增 `--tracking-caps:0.08em`（logo/全大写标签） | 同步改 `typographyTokens.test.js` |

### 1.4 间距 / 圆角 / 阴影 / 缓动 / 布局尺寸

- 间距：`--space-1:4 → --space-24:96`（4px 基数），**组件样式只允许引用 `--space-*`，禁止直写像素**（1px  hairline 与触控目标 ≥42/44px 除外）。现存 ~1644 处直写像素随页面执行逐步归 token，新增/触碰的代码必须归 token。
- 圆角（editorial-theme 权威）：`--radius-sm:2 / -md:3 / -lg:4 / -xl:5 / -2xl:6 / -full:9999px`（full 仅用于头像/色点）。组件默认 `sm/md`；卡片 `md`；模态/抽屉 `lg`。styles.css 的 6-20px 与 dark 的 8-28px 定义删除。
- 阴影（editorial-theme 权威）：`--shadow-sm`（1px 沉线）→ `--shadow-xl/--shadow-float`。**阴影只用于浮层**（模态/抽屉/下拉/toast/浮动面板）；静态卡片用 `--line-subtle` + paper-raised，不用阴影。
- 缓动：`--ease-default / -out / -in-out / -spring`；过渡时长新增 token `--dur-fast:120ms / --dur-base:200ms / --dur-slow:320ms`（定义在 styles.css），替换散落的硬编码 ms。
- 布局尺寸（styles.css）：`--topbar-height:56px`、`--sidebar-width:184px`、`--workspace-main-share:64fr`、`--workspace-side-share:18fr`、`--workspace-rail-left-min:176px`、`--workspace-rail-right-min:190px`、`--workspace-rail-collapsed:44px`。

### 1.5 RP 路径专有 token

`--rp-accent:#2466d1`、`--rp-accent-soft:#eef4ff`、`--rp-confirm-*`（styles.css:12320-12326、13994-13996、12626、13582 等）是 RP 沉浸路径的游离蓝色系，与 Archive 体系无关。**处置**：保留 RP 路径可使用独立强调色（它是刻意的第二外观），但收编为正式 token 块并注释语义（"RP 沉浸路径强调色"），禁止在作者工作台页面出现。详见 `pages/rp-experience.md`。

## 2. 色彩策略

- **表面三层**：paper（页底）→ paper-raised（卡片/面板）→ paper-muted（沉底/轨道）。层级靠表面明度差 + hairline，不靠阴影。
- **朱红白名单**（`--archive-red` / `--error` 以外的使用需新增时回改本表）：
  1. 主操作按钮（每屏至多一个 primary，见 §5.1 Button）
  2. 「待处理」计数角标（today attention、world review、sidebar badge）
  3. focus-visible 描边（全站统一，editorial-theme.css:155-158）
  4. 危险/错误语义
  5. 索引性点缀（logo-mark、topbar 章节分隔、选中态 `--line-active`）
- **语义色**：success `#356a55` / warning `#9a651d` / error=朱红 / info=ink。状态表达优先"文字 + 左侧 2-3px 线或色点"，不用整面彩色填充。
- **硬编码 hex 清除对照**（styles.css 内 167 处）：`#2466d1/#215cc6/#eef4ff/#d8e4f8` → RP token（§1.5）；`#f59e0b/#d97706/#efcf87` → `--warning` 系；`#b4232b/#a53a2c/#ef4444` → `--error` 系；`#fff` → `--bg-elevated` 或语境对应表面；旧主题残留（`#36454f/#352d4e/#2e2545/#f8f9fa/#e9ecef/#f1f3f5/#fff3cd/#f8d7da/#fcd34d/#fca5a5/#f4a900`）随死代码删除。凡 `!important` 压上去的色（styles.css:12565-12566、12656）优先重构成正常层叠。

## 3. Typography 标准

### 3.1 字族分工

| 字族 | 用于 | 禁止用于 |
|---|---|---|
| `--font-ui`（无衬线） | 全部界面控件、标签、表单、列表、导航 | 长正文 |
| `--font-body`（衬线） | 页面标题、作品标题、正文阅读（writing 编辑区、interaction 消息流）、logo | 按钮/表单/元数据 |
| `--font-mono` | 字数仪表盘、计数、ID 类元数据、顶栏技术信息 | 正文、标题 |

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
- 长正文阅读（writing/interaction）：`--text-md` 16 / `--leading-loose` 1.8 / 行宽 32-40 个中文字符。
- 标题不加装饰 icon（导航与按钮动作除外）。

## 4. Spacing 与布局标准

- **节奏**：垂直节奏以 `--space-4`(16) 为基准单位；区块间隔 `--space-8`(32)；区块内条目间隔 `--space-3`(12) 或 `--space-4`；紧凑表格/队列 `--space-2`(8)。
- **padding 三档**（收敛目标）：紧凑（表格行、队列条目）`--space-2 --space-3`；默认（卡片、面板）`--space-4`；宽松（模态、空态、表单区块）`--space-6`。新增/触碰代码不允许第 4 档。
- **分隔优先级**：留白 > 字层级 > hairline（`--line-subtle`）> 表面差。禁止"留白 + 分割线 + 卡片边框"三重叠加。
- **内容优先布局契约**（docs/modules/14_frontend.md:149-158）：工作台页主对象占分栏宽 64-68%（`--workspace-main-share:64fr`），左右 rail 不低于 `--workspace-rail-*-min`；720px→760px 合并后单栏；390px 不允许页面级横向溢出。
- **对齐**：同一列的控件左对齐到同一栅格线；表单 label/控件/helper 使用统一缩进链；数字右对齐或等宽。

## 5. 组件标准

> 现状：无组件库，组件 = styles.css 全局 class（"定义"）+ editorial-theme.css 覆写（"材质"）两步。
> 目标：每个组件的**视觉规则收敛到 editorial-theme.css 一处**，styles.css 只留结构尺寸；
> 消除 40 处 `!important` 中可消除的部分；以下为各组件的终态标准与现有 class 锚点。

### 5.1 Button（`.btn` 族，styles.css:884-1017 / editorial-theme.css:505-608）

| 变体 | 语义 | 视觉 |
|---|---|---|
| `.btn-primary` | 每屏至多一个的主操作 | 深墨实心（`--accent` 底 / paper 字），不用朱红实心大块；朱红只给 focus 环与索引点缀 |
| `.btn-ghost` | 次操作 | 透明底 + `--line-default` 边 |
| `.btn-text` | 三级/行内操作 | 无边无底色，hover 出 `--bg-hover` |
| `.btn-danger` / `.btn-warning` | 破坏性/警示 | 文字/边框用 `--error`/`--warning`，非实心填充（确认模态中的最终破坏按钮除外） |
| `.btn-sm` | 表格/队列行内 | 高度 28px（桌面） |
| `.btn-icon` | 纯图标 | 32px 方，图标必须带 aria-label |

状态矩阵（全部按钮必须具备）：hover（`--bg-hover` 或加深）/ active（`--bg-active`）/ focus-visible（2px 朱红环，editorial-theme.css:155-158 已全局覆盖，不得移除）/ disabled（`--text-quaternary` + 禁止 pointer，不只做颜色变淡）/ loading（spinner 替换图标，宽度不抖动）。

规则：一行按钮组最多 1 个 primary；破坏操作不放在顺手位置（列表行尾、模态右下角的预期位置是"确认"非"删除"）；触控档（≤760px）按钮高 ≥42px。

### 5.2 输入（`.input-field` 等，styles.css:1018-1722 / editorial-theme.css:609-779）

- 结构：label（`--text-sm` secondary，控件上方 `--space-1`）→ 控件 → helper/error（`--text-xs`，error 用 `--error`）。
- 控件：底 `--bg-elevated`、边 `--line-default`、radius `--radius-sm`、高 36px（桌面）/ ≥44px（触控）。
- 状态：hover 边加深 → focus 边 `--archive-ink` + 朱红环 → disabled 底 `--archive-paper-muted` → error 边 `--error` + helper 变错文。
- 可编辑区域与只读内容必须可区分（editorial「以红线标出可操作区域」的意图保留：输入控件有明确边界，只读文本无框）。
- 该区块 700 行偏大，执行时按"结构留 styles.css、材质留 editorial"归并重复规则。

### 5.3 Card（`.card` 族，styles.css:2966-3019 / editorial-theme.css:780-884）

- 只用于"可独立移动的条目"（项目卡、审核候选、任务卡）；**不做页面分区容器**——分区用留白 + 区块标题。
- 结构：padding `--space-4`；标题（条目标题档）→ 内容 → meta 行（`--text-xs` tertiary）；操作放右上或底部 meta 行内。
- 视觉：paper-raised + `--line-subtle`，无阴影；hover 仅可点击卡片有反馈（边加深或 `--bg-hover` 淡入），静态卡不做 hover 浮起。
- 禁止 Card 套 Card；卡内需要子分区时用 `--line-subtle` hairline。

### 5.4 Table（styles.css:3383-3616 / editorial-theme.css:885-1081）

- 表头：`--text-xs` + `--tracking-wide` + secondary 色 + 底 hairline；不加底色块。
- 行高紧凑（`--space-2 --space-3` padding）；行分隔用 `--line-subtle`，不用斑马纹（archive 纸面自带纹理）。
- 行 hover `--bg-hover`；选中行 `--bg-active` + 左侧 `--line-active`（3px 朱红）。
- 数字列右对齐等宽；操作列右对齐，行内操作用 `.btn-text`/`.btn-icon`。

### 5.5 Tabs / subnav（`.subnav` 族，styles.css:3915-3963）

- 形态：文字 tab + 底部指示（激活 2px `--line-accent` 墨线；仅"需处理"语义 tab 允许红点计数）。
- 激活 tab：`--text-primary` + 600；未激活：`--text-secondary`，hover 转 body 色。
- 一级视图导航（sidebar）与页面内 subnav 视觉分级明确，不互相模仿。

### 5.6 Modal（`.modal-*`，styles.css:3122-3285；`ui/modal.js` 命令式服务）

- 宽度三档：确认 400px / 表单 560px / 复杂内容 720px；radius `--radius-lg`；阴影 `--shadow-float`。
- 结构：标题（区块标题档）→ 内容 → 按钮行（右对齐，主右次左）；破坏确认的主按钮文案写动作本身（"删除作品"而非"确定"）。
- 焦点陷阱、inert 背景、Esc 关闭由 `ui/modal.js` 保证（modalAccessibility.test.js 契约），视觉改动不得破坏。

### 5.7 Toast（`.toast`，styles.css:3286-3318；`ui/toast.js`）

- 4 类型（success/info/warning/error），左 3px 语义色线 + paper-raised 底；最多 3 条可见。
- 保存反馈用 toast（"已保存"），成功操作不弹模态。

### 5.8 Badge / 计数 / 状态点

- 待处理计数：朱红小圆点 + 数字（mono），只用于「需要人工处理」语义（review 队列、attention）。
- 状态（草稿/已采纳/进行中…）：文字 + `--text-secondary`，必要时前置 6px 色点（语义色）；不用彩色 pill 底。
- 标签（分类/体裁）：`--line-subtle` 描边小胶囊，中性色，不染色。

### 5.9 Empty / Loading / Error（状态三件套）

- **Empty**：`.empty-state`（styles.css:3617-3656，复用良好，保持）——图标或短句 + 一句引导 + 主行动按钮（`.empty-state-cta`）。首次进入页必须有引导型空态，不允许裸空白。
- **Loading 归一**：区块加载 = `.loading-skeleton`（骨架屏，reduced-motion 下禁动画，loadingSkeleton.test.js 契约）；行内等待 = `.loading`（dots）；后台工作流 = `.workflow-progress*` / `WorkflowProgressCard.vue`。新代码不得发明第四种。
- **Error 统一**：以 `.error-card`（styles.css:3657-3676）为基准收敛视图级散装错误样式（`.generate-error-text` 等）：错误图标/色 + 一句人话说明 + 可执行动作（重试/返回），技术细节折叠到次级。

### 5.10 搜索 / 筛选栏 / 批量操作条

- 搜索框：页面内容区顶部左对齐，宽 240-320px，带清空按钮；结果计数紧随。
- 筛选面板：默认收起为一行摘要（"3 个筛选生效"），展开为面板；不常驻占据首屏。
- 批量操作条：选中时出现，附着于列表顶部（不是浮动悬浮条），显示"已选 N" + 操作组 + 退出。

## 6. 响应式标准

- **断点终态**：`760px`（主，触控/单栏切换，与文档承诺一致）、`1100px`（桌面密排/宽松切换）。`720px` 全部合并到 `760px`；长尾断点（390/460/480/560/600/640/900/980/1180 等）逐个审查：可归入两档的归入，确属局部组件自适应的保留并在该行注释理由。
- **四档行为**：Desktop（≥1440 内容区限宽居中，工作台不限宽）/ Laptop（1100-1440 默认形态）/ Tablet（760-1100 收窄 rail，可折叠）/ Mobile（<760 单栏、底栏导航、触控目标 ≥42/44px）。
- 移动端不是桌面缩小：writing → MobileQuickNote；map → 只读浏览 + 编辑转交桌面；其余页至少保证单栏不溢出、主操作可达。
- 页面级横向溢出零容忍（390px）。

## 7. 交互与动效标准

- 所有可点元素具备 hover/focus-visible/active/disabled 四态；反馈时长 `--dur-fast`（hover）/ `--dur-base`（面板开合）/ `--dur-slow`（模态）。
- 缓动：入场 `--ease-out`，退场 `--ease-in-out`，弹性仅用于轻量提示（`--ease-spring` 不用于大面板）。
- `prefers-reduced-motion`：骨架屏/流式/进度动画全部降级（现有 7 处已实现，新增动画必须补）。
- 长任务必须有进度反馈（workflow-progress），不允许只有 spinner 超过 2s。
- 操作反馈闭环：点击 → 立即视觉反馈（active/disabled+loading）→ 结果（toast/内容更新）；异步操作按钮在 pending 期间禁用。

## 8. 无障碍标准

- 对比度：正文 ≥ 4.5:1（`--text-body` on paper 满足）；辅助文字 ≥ 4.5:1（`--text-secondary` on paper 需逐主题核验，dark 主题 `#b4b4ad` on `#17232a` 满足）；`--text-tertiary` 仅用于非必要元数据；`--text-quaternary` 仅占位/禁用。
- focus-visible 朱红环全站统一，不得 `outline: none` 而无替代。
- 触控/点击目标：桌面 ≥28px，触控 ≥42px（按钮）/44px（输入）。
- 语义结构：每页单一 h1（view-header），区块 h2；列表用 ul/li 或 role=list；图标按钮必有 aria-label（subnavAccessibility.test.js 等契约）。
- 键盘：模态焦点陷阱、Esc 关闭、表单可全程键盘完成。

## 9. 文案与命名一致

| 现状冲突 | 位置 | 裁定 |
|---|---|---|
| project 页 =「作品档案」（router.js:15）vs「导入与整理」（shell/navigation.js:18） | 路由标题 vs 侧边栏更多菜单 | 统一为「作品档案」；侧边栏项改为「作品档案与导入」 |
| today =「今日工作」（router）vs「首页」（navigation.js） | 同上 | 统一为「首页」，view-header 显示「今天」语义化问候可保留 |
| `data-workspace-view` 仅作样式钩子 | docs/modules/14_frontend.md:151-152 | 维持，不得被业务/测试依赖 |

改可访问名称必须全局 grep 同步 e2e 的 `getByRole({name})` / `getByText`。

## 10. 死代码与清理清单（执行时逐项核对）

1. styles.css 三套旧主题色板（:8-138 颜色部分、:141-199、:268-500）——删除。
2. 兼容别名层（:120-137、:184-198）——grep 后迁移或删除。
3. styles.css:4 失效文档引用——改指本文件。
4. 孤儿文件 `frontend-console/shared/assetDisplayState 2.js`——确认无引用后删除。
5. 非 scoped SFC 内联样式 9 处（CommandPalette.vue:107、ThemePicker.vue:121、ShellApp.vue:140、GenerateView.vue:271、InteractionView.vue 等）——收编全局或改 scoped；`#theme-toggle` 三方争抢（editorial-theme.css:193-198 的 4 个 `!important`）重构为单一规则。
6. 尾部补丁层（styles.css:8801/9041/9502/10019/11502/11677/14106/14300 起的 8 个"一致性补充"区块）——随各页面执行逐步归并入组件主规则，不单独一次性大搬移。
7. `!important` 40 处（styles.css 26 + editorial-theme 14）——每处评估，能靠层叠解决的全部消除。
8. 假命令 `:save`/`:export`（commands.js:188-196，只 toast 不执行）——**记录上报产品决定，不在 UI 执行范围内擅自处理**。
