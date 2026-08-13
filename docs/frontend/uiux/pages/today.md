# 首页（today）UI/UX 执行规范

> 上游标准：`docs/frontend/uiux/design-standard.md`（下称「主规范」），本节号引用均指主规范。
> 实现锚点：`frontend-console/vue/views/today/TodayView.vue`（172 行）、`frontend-console/styles.css`（`.today-*` 规则）。
> 命名：按主规范 §9 裁定，本页统一称「首页」（侧边栏 label 已是「首页」，vue/shell/navigation.js:2）；
> router 标题「今日工作」（router.js:18）与页内 eyebrow「今日工作」（TodayView.vue:117）随本次执行统一，
> view-header 允许保留「欢迎回来」语义化问候（§9 第 2 行）。

## 1. 页面定位与目标画像

- **目标画像**：画像 A（长期创作的专业或业余作家，`docs/product/user-personas.md` §「画像 A」）。
  本页不服务画像 B；RP 用户不经过作者工作台。
- **核心任务**（对应画像 A 核心任务与「他们会喜欢什么」第 1、6 条）：
  1. 用最低成本回到上次停下的章节继续写作——这是本页存在的理由，对应画像文档 §5 优先级
     第 3 条「降低继续写作时的上下文恢复成本」；
  2. 集中看清「有哪些事需要我决定」（待审核候选、别名、关系、场景、地图资料），并一键去处理；
  3. 感知后台整理任务的进度与失败，且「长任务可离开、恢复并知道下一步」。
- **设计取向**：本页是作者的「今日桌面」，不是仪表盘。信息层级必须服从「继续写作 > 待决定 >
  后台任务」，任何装饰、统计、问候文案都不得抢过「继续写作」主按钮（主规范 §0 决策优先级 1-2）。

## 2. 现状问题清单（按严重度排序）

1. **【高】summary 加载失败时「需要你决定」整区消失**：`v-if="summary"`（TodayView.vue:146）
   使错误态下 5 类待办入口全部不可达，只剩一行 inline warning（:141-144），用户失去处理待办
   的路径。
2. **【高】视图内无加载态**：summary 请求在 island onEnter 内 await（todayIsland.js:48-50），
   「重新加载」按钮（TodayView.vue:143）触发同视图 refresh 时旧内容直接闪没、无骨架；router 骨架
   只在路由切换时出现（router.js:574-581）。违反主规范 §5.9 Loading 归一。
3. **【高】「从首页隐藏」无确认、不可撤销**：dismissWorkflow 直接 clearActiveWorkflow + refresh
   （TodayView.vue:103-106），按钮在 :166。失败任务被隐藏后只能到目标页内找回，属于误操作无
   保护。
4. **【中】resume 主卡视觉语言违反 Editorial 契约**：字面 `border-radius: 28px`（`.today-resume`）
   vs 主题 `--radius-xl: 5px`（editorial-theme.css:57）；静态卡带 `box-shadow: var(--shadow-md)`
   （同一规则），违反主规范 §1.4「阴影只用于浮层」；同页 attention/workflow 卡均用 token
   圆角（`.today-attention-card` / `.today-workflow-card`），同页视觉断裂。
5. **【中】页头 H1 与 resume H2 争夺第一视觉焦点**：`.today-heading h1` 为 clamp(28px,4vw,44px)
   （`.today-heading h1`），达到甚至超过 resume H2 的 clamp(26px,4vw,40px)（`.today-resume h2`）；违反主规范
   §3.2 字阶矩阵「页面标题 = --text-xl 24」与「一页内字阶跨度 ≤ 4 级」。
6. **【中】attention 总数胶囊未用朱红计数角标**：`.today-count` 为 `--accent-soft` 底 + `--accent`
   墨色文字的 pill（`.today-count`）；「待处理计数」属主规范 §2 朱红白名单第 2 条，应为朱红
   小圆点/数字形态（§5.8），而非中性墨色 pill。
7. **【中】无待处理时无正向收束**：总数为 0 仍渲染 5 张「暂无待处理」占位卡（TodayView.vue:149、
   :153），占位大、无「全部已处理」文案；且值为 0 的卡仍是可点 button，空点击无收益（:152-154）。
8. **【低】硬编码值残留**：attention 大数字 `font-size: 30px` 直写（`.today-attention-card strong`）；eyebrow
   `letter-spacing: .14em`、resume label `.12em` 直写（`.today-heading` / `.today-resume`），未用 §1.3 tracking token；
   attention hover `translateY(-1px)` + `box-shadow: var(--shadow-sm)`（`.today-attention-card`）阴影违例（§1.4）。
9. **【低】页头「切换作品」按钮无 `data-action`**（TodayView.vue:121），不受壳层快捷键与 e2e
   钩子体系覆盖，与其余按钮风格不一致。
10. **【低】断点漂移**：today 使用 900px 的局部卡片布局微调与 760px 的移动档（`.today-*` 响应式规则），主规范 §6
    的全局断点为 760/1100；无 ≤460px 档，390px 下 attention 2 列卡约 170px 宽、三行内容偏挤
    。
11. **【低】无 today 页视觉基线**：`e2e/visual-*.spec.js` 现有 project/world/outline/writing/settings
    五组三主题基线，无 visual-today（执行时核实是否在本次新增）。

## 3. 目标布局与信息层级

- **Primary**：resume 主卡「接着上次写」+「继续写作」主按钮。这是第一视觉焦点，也是唯一允许
  独特构图的区域（主规范 §0 反模式第 4 条明确豁免）。主按钮是全屏唯一 `.btn-primary`（§5.1）。
- **Secondary**：「需要你决定」attention 区——5 类待办计数 + 跳转入口，语义是「这些不会自动
  成为正式设定，需要作者裁决」，呼应画像 A「AI 不越权」。
- **Tertiary**：「正在进行的整理」workflow 区——后台任务进度与失败处理，密度优先、不展开细节。
- **页头**：降级为标准 view-header（H1 = `--text-xl` 24px 衬线，§3.2），只承担「我在哪部作品的
  首页」的定位作用；「切换作品」为 `.btn-ghost` 三级操作，不竞争焦点。
- **第一视觉焦点与阅读路径**：进入页面 → 视线落在 resume 卡（大标题 + 朱红 focus 环可及的
  48px 主按钮）→ 下移扫过 attention 计数（有朱红角标时自然被吸引）→ 最后扫 workflow 列表。
- **对齐主规范 §4 内容优先契约**：本页是单栏阅读型页面，非 64/18 分栏工作台；保留
  `min(1120px, 100%)` 限宽居中（`.today-workspace`），垂直节奏：页头→resume 间隔 `--space-6`，
  区块间隔 `--space-8`（`.today-section` 现状已合规），区块内条目间隔 `--space-3`（`.today-attention-grid`）。

## 4. 逐区域标准

### 4.1 view-header（.today-heading，TodayView.vue:115-122）

- 结构：左「eyebrow + H1 + 一句副文案」，右「切换作品」`.btn-ghost`。H1 是全页唯一 h1（§8）。
- 字号角色：eyebrow = 元数据档（`--text-xs` + `--tracking-caps`，主规范 §1.3 修正后）；
  H1 = 页面标题档 `--text-xl` 24px / 700 / 衬线（§3.2），**删除 clamp(28-44px)**；
  副文案 = helper 档 `--text-sm` `--text-secondary`，最多一句。
- 间距：margin-bottom `--space-6`（现状合规）；eyebrow 与 H1 间距 `--space-2`。
- 「切换作品」补 `data-action="switch-project"`，文案保持「切换作品」。

### 4.2 resume 主卡（.today-resume，:124-139）——第一视觉焦点

- 结构（保持）：左侧 `label「接着上次写」` + H2 章节标题 + 状态行（第 N 章 · 保存状态，:128-133）
  + 统计行「N 章 · N 字」（:134）；右侧主按钮 `data-action="continue-writing"`（:136）。
- 视觉修正（问题 4）：圆角 28px → `--radius-xl`（5px）；删除 `box-shadow`，层级靠渐变底 +
  hairline 边表达；渐变保留（第一焦点豁免），但收编为主题内可覆写的表达，禁止新增字面色值。
- 字号角色：H2 允许突破 §3.2 矩阵（独特构图豁免），上限 clamp(26px,4vw,40px) 保留；
  label = eyebrow 档；状态行/统计行 = helper 档（`--text-sm` secondary），统计数字可用 mono（§3.1）。
- 主按钮：`.btn-primary`，高度 ≥48px 保留（`.today-resume__action`），三态文案「继续写作 / 继续整理 / 开始第一章」
  （:28-32）保持——注意与 project 卡片「继续创作」的措辞统一裁定见 project.md §2。
- 状态行三态语义保持：有 continuation → 章节 + 保存状态；有 deep_import → 整理中提示；
  否则 → 首次引导句（:128-133）。

### 4.3 内联错误条（.today-inline-warning，:141-144）

- 映射主规范 §5.9 Error 统一：保留 `role="alert"` 与「重新加载」按钮；视觉收敛到 `.error-card`
  基准（错误色 + 一句人话 + 可执行动作），不再自定义 `border: 1px solid var(--warning)` 散装样式
  （`.today-inline-warning`）。圆角 `--radius-xl` 已合规。
- **行为修正（问题 1）**：summary 失败时 attention 区不得整区消失——改为渲染骨架/降级的 5 个
  入口卡（值显示「—」，点击仍可达目标页），错误条仅提示「概览未更新」。

### 4.4 「需要你决定」attention 区（:146-156）

- 区块标题 = 区块标题档 `--text-md` 16px/600（§3.2），现状 `--text-xl`（`.today-section h2`）需下调；
  说明句「这些内容不会自动成为正式设定」= helper 档，保留。
- **总数计数映射朱红白名单第 2 条**（问题 6）：`.today-count` 改为朱红计数角标——
  `--archive-red` 数字（mono）+ 朱红小圆点或 `--archive-red-soft` 底，仅当 total > 0 时呈现朱红；
  total = 0 时角标隐藏，配合正向收束文案（见 §5 空态）。
- attention 卡：保持 button 元素 + 5 列 grid（`.today-attention-grid`）。卡内三层：大数字（条目标题以上一级，
  30px 直写改为 token 化字阶，如 `--text-xl` 或 `--text-2xl`，执行时与字阶矩阵核对）、label
  （条目标题档 14px/600）、hint「去处理」（元数据档 `--text-xs` tertiary）。
- 卡片视觉：paper-raised + `--line-subtle`，圆角 `--radius-xl`（现状 `--bg-panel` + token 圆角
  基本合规）；hover 只保留「边加深或 `--bg-hover` 淡入」（§5.3），**删除 translateY 与阴影**
  （`.today-attention-card:hover`）。
- 值为 0 的卡：disabled 或 aria-disabled + `--text-quaternary` 数字（§5.1 disabled 档），不可点击；
  hint 不再显示「暂无待处理」斜位文案（:153 的 `<i>` 元素改为 `<span>`，样式已由 `.today-attention-card` 设为 normal）。

### 4.5 「正在进行的整理」workflow 区（:158-170）——映射 WorkflowProgressCard 标准

- 现状卡片 `.today-workflow-card`（grid：copy | progress | actions）在语义上与共享组件
  `vue/components/WorkflowProgressCard.vue`（variant="card"）重复。目标：**本区任务卡统一映射
  WorkflowProgressCard 的卡片形态标准**：
  - 标题 = progress.label（即 WORKFLOW_COPY 用户语言文案，:41-54，保持）；
  - 状态句 = progress.message（workflowStatus 三态，:82-87，保持）；
  - 进度 = 组件内 `<progress>`，`aria-label` 保留（:163）；
  - 失败/状态未知 → 组件 `attentionRequired` 语义（自动展开 + 警示边），替代手写 `.is-warning`
    （`.today-workflow-card.is-warning`）；
  - 操作区经组件默认 slot 注入：「查看 / 打开并处理」（`.btn-sm`）+「从首页隐藏」（`.btn-ghost`）。
  - 若直接复用组件成本过高，允许保留现有 DOM，但类名、折叠行为、警示样式必须与
    WorkflowProgressCard variant="card" 逐项对齐，并在代码注释标明对齐关系（执行时核实取舍）。
- 「从首页隐藏」加确认（问题 3）：点击后经 `getConfirmAction()` 二次确认（文案说明「可在对应
  页面找回该任务」），或提供 undo toast；二选一，禁止静默清除。

### 4.6 浮层

- 本页自身无浮层；唯一的浮层需求是「从首页隐藏」的确认 modal（§5.6 Modal：确认档 400px，
  主按钮文案写动作本身，如「从首页隐藏」而非「确定」）。

## 5. 状态覆盖清单（映射主规范 §5.9）

| 状态 | 现状 | 缺口 | 目标形态 |
|---|---|---|---|
| 首次进入（新项目无章节） | resume 卡回退「开始第一章」+ 引导句（:23-27、:133） | 无 | 保持；resume 即首次引导，不再加独立空态 |
| 空态-无待处理 | 5 张全 0 卡 + 胶囊 0（:149、:153） | 无正向反馈、0 值卡可空点 | 角标隐藏；卡区收束为一行「全部已处理，没有需要你决定的内容」+ 保留入口（或 0 值卡 disabled），二选一 |
| 空态-无进行中任务 | 整区 v-if 移除（:158） | 可接受 | 保持移除；不加占位 |
| 加载 | 无视图内骨架（todayIsland.js:48-50） | 违反 §5.9 | refresh 期间渲染 `.loading-skeleton`（resume 卡 + attention 卡位骨架），reduced-motion 禁动画 |
| 失败 | inline-warning + 重试（:141-144） | attention 区整区消失（问题 1） | 错误条 + attention 降级渲染（值「—」可跳转）；resume 卡始终可用 |
| 冲突 | 不适用（本页无编辑） | — | — |
| 保存反馈 | 不适用（本页无写入，「隐藏」见下） | 「从首页隐藏」无反馈闭环 | 确认后 toast「已从首页隐藏」；成功后卡片以 `--dur-base` 退场 |
| 离开恢复 | workflow 离开不中断（:159 文案承诺） | 「隐藏」不可恢复（问题 3） | 确认文案说明找回路径；进度卡折叠态经 sessionStorage 持久化（WorkflowProgressCard 既有契约） |
| 窄屏 | 760px 档 resume 纵向、按钮全宽（`.today-resume` 响应式规则） | 390px 密度仍需复核（问题 10） | 见 §6 |

## 6. 响应式行为（对齐主规范 §6 四档）

- **≥1440（Desktop）**：内容限宽 1120px 居中；attention 5 列；resume 横排（左文案右按钮）。
- **1100-1440（Laptop）**：默认形态，同上。
- **760-1100（Tablet）**：attention 5→2 列（现 900px 断点并入此档）；workflow 卡 grid 改单列
  （现有 `.today-workflow-card` 响应式行为保留，断点值改 760 或 1100，执行时按 §6 归并并注释理由）。
- **<760（Mobile）**：resume 改纵向、主按钮全宽 ≥42px 高（§5.1
  触控档）、页头按钮与标题同行、页 padding 收窄；attention 保持 2 列但
  min-height 116px 需复核 390px 不横向溢出（§6 零容忍）；壳层底部导航行为
  不变（属 shell 范畴，不在本页改）。

## 7. 必须保留的契约

| 契约 | 位置 | 用途 |
|---|---|---|
| `#today-title` | TodayView.vue:118 | `<main aria-labelledby>` 锚点（:114） |
| `#today-resume-title` | :127 | resume section aria-labelledby（:124） |
| `#today-attention-title` | :148 | attention section aria-labelledby（:146） |
| `#today-workflows-title` | :159 | workflow section aria-labelledby（:158） |
| `data-action="continue-writing"` | :136 | 主按钮；e2e/快捷键钩子，跨页同名动作（project 卡片 :106） |
| `role="alert"` 于 `.today-inline-warning` | :141 | 错误播报 |
| `<progress aria-label>` | :163 | 进度可访问名称 |
| `role="button" tabindex="0"` 键盘三键 | 占位卡不适用本页 | — |

新增契约（本次执行引入，需同步 e2e selectors）：「切换作品」补 `data-action="switch-project"`；
「从首页隐藏」确认 modal 复用 `getConfirmAction` 既有钩子，不新增 id。

## 8. 验收标准 + 验证命令

- [ ] resume 卡是第一视觉焦点：页头 H1 = 24px，resume H2 > 页头 H1；主按钮为全屏唯一 primary。
- [ ] resume 卡圆角 = `--radius-xl`，无 box-shadow；渐变保留且无新增字面色值。
- [ ] attention 总数 > 0 时呈朱红计数角标（§2 白名单第 2 条），= 0 时隐藏并出现正向收束。
- [ ] summary 加载失败：错误条出现且 attention 5 入口仍可达（值「—」）。
- [ ] 同视图 refresh（重新加载）期间出现 `.loading-skeleton`，无内容闪没。
- [ ] 值为 0 的 attention 卡不可点击（disabled/aria-disabled）。
- [ ] 「从首页隐藏」需二次确认，确认后 toast 反馈，文案说明找回路径。
- [ ] workflow 卡与 WorkflowProgressCard variant="card" 标准对齐（复用或逐项对齐，注释标明）。
- [ ] 命名统一：侧边栏/router/页内不再出现「今日工作」与「首页」混用（按 §9 裁定落地范围）。
- [ ] 390px 宽度无页面级横向溢出；<760 档主按钮全宽且高 ≥42px。
- [ ] 全部 §7 契约存在且可被 `getByRole`/`data-action` 选中。

验证命令（在 `frontend-console/` 下）：

```bash
npm test -- tests/vue/todayIsland.test.js        # island 加载/错误/空态单测
npm test -- tests/editorialTheme.test.js tests/typographyTokens.test.js   # token 契约
npm run test:e2e:functional -- e2e/author-workspace.spec.js e2e/home.spec.js  # 进入 today 的功能流
npm run test:e2e:visual -- e2e/visual-today.spec.js                       # 新增三主题基线（执行时核实）
```
