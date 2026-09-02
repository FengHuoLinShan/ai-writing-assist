# 首页（today）UI/UX 执行规范

> 上游标准：`docs/frontend/uiux/design-standard.md`（下称「主规范」），本节号引用均指主规范。
> 实现锚点：`frontend-console/vue/views/today/TodayView.vue` 与 `frontend-console/styles.css` 的 `.today-*` 规则。
> 命名：页面与 router 统一称「写作首页」；主导航使用任务名「写作」，
> view-header 保留「欢迎回来」语义化问候（§9 第 2 行）。

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

## 2. 本轮处理与剩余项

1. **已处理：摘要失败降级**。错误态不再误判为空项目；主操作仍进入写作，
   「需要你决定」保留四个可达领域入口，未知数量显示「—」而非假装为 0。
2. **已核实：刷新加载态**。`router.refresh()` 在重跑 island `onEnter` 前渲染共享
   `.loading-skeleton`，且恢复当前路由。
3. **已处理：隐藏任务误操作**。「从首页隐藏」使用既有 `getConfirmAction()` 二次确认，
   明示找回路径，确认后给出 toast 反馈；Escape 取消保留卡片并恢复焦点。
4. **已处理：首屏层级与视觉契约**。页头 H1 收敛到 `--text-xl`，resume H2 保持第一
   视觉焦点；主卡改用 `--radius-xl`、去除静态阴影，计数使用朱红 token。
5. **已处理：空态与硬编码表达**。投影空列表使用正向收束；兼容旧计数投影时，
   0 值卡片为原生 disabled。字阶、tracking、颜色与圆角均复用现有 token，hover 不再浮起或加阴影。
6. **已处理：钩子与窄屏**。「切换作品」提供 `data-action="switch-project"`；≤460px 提供
   独立密度与 44px 触控档，唯一主操作保持 48px。
7. **剩余项**：任务卡尚未直接复用 `WorkflowProgressCard`，且 today 尚无独立的三主题提交基线；
   当任务卡继续增长或视觉回归需要长期门禁时再补，不为本轮额外造抽象或 spec。

## 3. 目标布局与信息层级

- **Primary**：resume 主卡「接着上次写」+「继续写作」主按钮。这是第一视觉焦点，也是唯一允许
  独特构图的区域（主规范 §0 反模式第 4 条明确豁免）。主按钮是全屏唯一 `.btn-primary`（§5.1）。
- **Secondary**：「需要你决定」attention 区——具体待决事项与 4 个领域降级入口，语义是「这些不会自动
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

### 4.1 view-header（`.today-heading`）

- 结构：左「eyebrow + H1 + 一句副文案」，右「切换作品」`.btn-ghost`。H1 是全页唯一 h1（§8）。
- 字号角色：eyebrow = 元数据档（`--text-xs` + `--tracking-caps`，主规范 §1.3 修正后）；
  H1 = 页面标题档 `--text-xl` 24px / 700 / 衬线（§3.2），**删除 clamp(28-44px)**；
  副文案 = helper 档 `--text-sm` `--text-secondary`，最多一句。
- 间距：margin-bottom `--space-6`（现状合规）；eyebrow 与 H1 间距 `--space-2`。
- 「切换作品」补 `data-action="switch-project"`，文案保持「切换作品」。

### 4.2 resume 主卡（`.today-resume`）——第一视觉焦点

- 结构（保持）：左侧 `label「接着上次写」` + H2 章节标题 + 状态行（第 N 章 · 保存状态，:128-133）
  + 统计行「N 章 · N 字」（:134）；右侧主按钮 `data-action="continue-writing"`（:136）。
- 视觉修正（问题 4）：圆角 28px → `--radius-xl`（5px）；删除 `box-shadow`，层级靠渐变底 +
  hairline 边表达；渐变保留（第一焦点豁免），但收编为主题内可覆写的表达，禁止新增字面色值。
- 字号角色：H2 允许突破 §3.2 矩阵（独特构图豁免），上限 clamp(26px,4vw,40px) 保留；
  label = eyebrow 档；状态行/统计行 = helper 档（`--text-sm` secondary），统计数字可用 mono（§3.1）。
- 主按钮：`.btn-primary`，高度 ≥48px 保留（`.today-resume__action`），三态文案「继续写作 / 继续整理 / 开始第一章」。空白作品的主操作始终进入正文工作台，不依赖模型连接；「先整理世界观」作为同组次操作复用现有 World Core。
- 状态行三态语义保持：有 continuation → 章节 + 保存状态；有 deep_import → 整理中提示；
  否则 → 首次引导句（:128-133）。

### 4.3 内联错误条（`.today-inline-warning`）

- 映射主规范 §5.9 Error 统一：保留 `role="alert"` 与「重新加载」按钮；视觉收敛到 `.error-card`
  基准（错误色 + 一句人话 + 可执行动作），不再自定义 `border: 1px solid var(--warning)` 散装样式
  （`.today-inline-warning`）。圆角 `--radius-xl` 已合规。
- **行为修正（问题 1）**：summary 失败时 attention 区不得整区消失——改为渲染降级的 4 个
  入口卡（值显示「—」，点击仍可达目标页），错误条仅提示「概览未更新」。

### 4.4 「需要你决定」attention 区

- 区块标题 = 区块标题档 `--text-md` 16px/600（§3.2），现状 `--text-xl`（`.today-section h2`）需下调；
  说明句「这些内容不会自动成为正式设定」= helper 档，保留。
- **总数计数映射朱红白名单第 2 条**（问题 6）：`.today-count` 改为朱红计数角标——
  `--archive-red` 数字（mono）+ 朱红小圆点或 `--archive-red-soft` 底，仅当 total > 0 时呈现朱红；
  total = 0 时角标隐藏，配合正向收束文案（见 §5 空态）。
- attention 卡：保持 button 元素 + 4 列 grid（`.today-attention-grid`）。卡内三层：大数字（条目标题以上一级，
  30px 直写改为 token 化字阶，如 `--text-xl` 或 `--text-2xl`，执行时与字阶矩阵核对）、label
  （条目标题档 14px/600）、hint「去处理」（元数据档 `--text-xs` tertiary）。
- 卡片视觉：paper-raised + `--line-subtle`，圆角 `--radius-xl`（现状 `--bg-panel` + token 圆角
  基本合规）；hover 只保留「边加深或 `--bg-hover` 淡入」（§5.3），**删除 translateY 与阴影**
  （`.today-attention-card:hover`）。
- 值为 0 的卡：disabled 或 aria-disabled + `--text-quaternary` 数字（§5.1 disabled 档），不可点击；
  hint 不再显示「暂无待处理」斜位文案（:153 的 `<i>` 元素改为 `<span>`，样式已由 `.today-attention-card` 设为 normal）。

### 4.5 「正在进行的整理」workflow 区——映射 WorkflowProgressCard 标准

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

| 状态 | 当前形态 | 本轮证据 | 后续边界 |
|---|---|---|---|
| 首次进入（新项目无章节） | resume 卡以「开始第一章」进入正文，世界观整理为次操作 | TodayView 单测 | 不要求作者先连接模型 |
| 空态-无待处理 | 投影列表显示「当前没有需要你决定的内容」；旧计数投影的 0 值卡 disabled | TodayView 单测 | 不为空值提供无效跳转 |
| 空态-无进行中任务 | 整区不渲染 | 现有 `v-if` | 不加占位 |
| 加载 | 强制刷新时使用 router 共享 `.loading-skeleton` | 真实浏览器延迟摘要请求验证 | 保持 reduced-motion 契约 |
| 失败 | `.error-card` 错误条 + 4 个值为「—」的可达领域入口；主操作显示「进入写作」 | 503 拦截下的 390px 真实浏览器流程 | 未知数据不伪装成空项目 |
| 冲突 | 不适用（本页无编辑） | — | — |
| 保存反馈 | 本页不写作品；隐藏本地恢复记录前二次确认，成功后 toast | 真实确认/Escape 流程与单测 | 任务仍可在对应页面找回 |
| 离开恢复 | workflow 离开不中断；确认文案说明找回路径 | 浏览器前进/后退/刷新验证 | 任务卡折叠持久化随共享组件后续复用时引入 |
| 窄屏 | 760px 档 resume 纵向；≤460px 收紧密度，普通按钮≥44px、主操作 48px | 390×844 无横向溢出 | 壳层底栏不在本页改动 |

## 6. 响应式行为（对齐主规范 §6 四档）

- **≥1440（Desktop）**：内容限宽 1120px 居中；attention 降级入口 4 列；resume 横排（左文案右按钮）。
- **1100-1440（Laptop）**：默认形态，同上。
- **760-1100（Tablet）**：workflow 卡改为单列；attention 降级入口保持四列。
- **<760（Mobile）**：resume 改纵向、主按钮全宽 48px 高，页头按钮与标题同行、页 padding 收窄；
  attention 降级入口为 2 列；壳层底部导航行为
  不变（属 shell 范畴，不在本页改）。

## 7. 必须保留的契约

| 契约 | 位置 | 用途 |
|---|---|---|
| `#today-title` | `TodayView` 模板 | `<main aria-labelledby>` 锚点 |
| `#today-resume-title` | `TodayView` 模板 | resume section `aria-labelledby` |
| `#today-attention-title` | `TodayView` 模板 | attention section `aria-labelledby` |
| `#today-workflows-title` | `TodayView` 模板 | workflow section `aria-labelledby` |
| `data-action="continue-writing"` | resume 主按钮 | e2e/快捷键钩子，跨页同名动作 |
| `role="alert"` 于 `.today-inline-warning` | 摘要错误条 | 错误播报 |
| `<progress aria-label>` | workflow 卡 | 进度可访问名称 |
| `role="button" tabindex="0"` 键盘三键 | 占位卡不适用本页 | — |

新增契约（本次执行引入，需同步 e2e selectors）：「切换作品」补 `data-action="switch-project"`；
「从首页隐藏」确认 modal 复用 `getConfirmAction` 既有钩子，不新增 id。

## 8. 验收标准 + 验证命令

- [x] resume 卡是第一视觉焦点：页头 H1 = 24px，resume H2 > 页头 H1；主按钮为全屏唯一 primary。
- [x] resume 卡圆角 = `--radius-xl`，无 box-shadow；渐变保留且无新增字面色值。
- [x] attention 总数 > 0 时呈朱红计数角标（§2 白名单第 2 条），= 0 时隐藏并出现正向收束。
- [x] summary 加载失败：错误条出现且 attention 4 入口仍可达（值「—」）。
- [x] 同视图 refresh（重新加载）期间出现 `.loading-skeleton`。
- [x] 值为 0 的 attention 卡不可点击（disabled/aria-disabled）。
- [x] 「从首页隐藏」需二次确认，确认后 toast 反馈，文案说明找回路径。
- [ ] workflow 卡与 WorkflowProgressCard variant="card" 标准对齐（复用或逐项对齐，注释标明）。
- [x] 命名统一：router/页内为「写作首页」，主导航使用任务名「写作」。
- [x] 390px 宽度无页面级横向溢出；<760 档主按钮全宽且高 48px。
- [x] 全部 §7 契约存在且可被 `getByRole`/`data-action` 选中。

验证命令（在 `frontend-console/` 下）：

```bash
npm test -- tests/vue/todayIsland.test.js        # island 加载/错误/空态单测
npm test -- tests/editorialTheme.test.js tests/typographyTokens.test.js   # token 契约
npm run test:e2e:functional -- e2e/author-workspace.spec.js e2e/home.spec.js  # 进入 today 的功能流
# 本轮使用受控 Playwright 会话对比桌面/移动与三主题截图；独立提交基线尚未引入。
```
