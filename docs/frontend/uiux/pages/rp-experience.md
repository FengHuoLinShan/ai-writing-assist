# RP 沉浸路径 UI/UX 执行规范（home / journeys / interaction）

> 上游权威：`docs/frontend/uiux/design-standard.md`（下称主规范）与
> `docs/product/user-personas.md`（画像 B）。本文只规定 RP 沉浸路径三个页面的执行标准，
> 不改变主规范 token 体系；与主规范冲突处以主规范为准，本文的差异化裁定均已显式标注。
> 证据行号以撰写时源码为准，执行前若文件已变动需重新定位（标注「（执行时核实）」的条目必须核实）。

## 1. 页面定位与目标画像（画像 B；与作者工作台的刻意分离关系）

- 三页服务画像 B（RP 用户，user-personas.md:57-98）：不懂技术、以阅读与沉浸为主的用户。
  首屏只要求「世界、身份、开场愿望」，不得暴露 World/Schema/Prompt/token/内部枚举等作者后台概念。
- 与作者工作台是**刻意的双路径分离**（user-personas.md:110-121）：共享账号与模型连接，
  不共享首屏、业务心智和视觉密度。主规范 §0 的「工作台密度优先」在本路径让位于**阅读舒适度优先**：
  RP 保持低密度阅读排版，严禁把作者工作台的密度、表格心智、审核队列语言带入本路径。
- 技术外壳：`ShellApp.vue:63-72` 的 `showAuthorChrome` 对 `home / journeys / interaction`
  及带合法 `return_to` 的 `settings` 返回 `false`，Topbar/Sidebar 不渲染（`ShellApp.vue:7-11`），
  `#main-layout` 加 `.main-layout--immersive`。该分离逻辑是本路径的根基契约，不得削弱。
- RP 强调色（蓝 `--rp-accent:#2466d1` 系）按主规范 §1.5 收编为正式 token 块，**仅限 RP 路径**，
  禁止回流作者工作台页面。

## 2. 现状问题清单（按严重度排序，每条带 文件:行号 证据）

**P0 — 直接伤害阅读/恢复体验**

1. **已解决：流式段落可辨认**。流式卡显示「正在生成／未完成」、accent 左线与轻底色；
   `aria-busy` 保留，reduced-motion 下三点脉冲静止。
2. **两个视图无首屏加载骨架**：`loadJourneyList` / `loadInteraction` 完成前视图不挂载
   （interactionIsland.js:11-47、49-86），慢网络下路由切换后白屏，违反主规范 §5.9 Loading 归一。
3. **已解决：双入口跟随主题**。`.entry-choice` 与 journeys/story 共用 RP token，沉浸壳使用
   当前 `--bg-base`；卡片、标题、说明与边框均消费 RP 语义变量，不再在夜间主题闪白。

**P1 — 一致性与可用性缺陷**

4. **已解决：默认阅读行宽**。阅读列收敛到 640px，约 32-40 个中文字符；移动端仍使用视口减
   安全 padding。字号/行宽个性化继续作为需用户验证的产品假设，不先造设置。
5. **危险操作三种确认范式并存**：列表归档用原生 `confirm`（JourneyListView.vue:262）、
   永久删除用原生 `prompt` 输入完整标题（:283-286），而看海确认是定制
   RpAdaptiveConfirmPopover。原生对话框无 RP 视觉、无移动端适配。
6. **主题选择器两套实现不对等**：RP 内置版（InteractionView.vue:1584-1596）是纯 button 列表
   + `aria-pressed`，无 menu/menuitemradio 语义、无键盘导航、无 Escape 与焦点管理；
   Topbar ThemePicker 有完整实现。**裁定（有意保留双入口）**：沉浸路径隐藏 Topbar
   （ShellApp.vue:7-9），RP 侧**保留** InteractionView 内置入口，不属重复缺陷；
   但必须把两者的菜单视觉与可访问语义统一（见 §4.8）。
7. **已解决：流式滚动与 reduced-motion**。故事容器不再设置 smooth，逐 chunk 使用直接滚动；
   离散定位仍按系统 reduced-motion 选择 smooth/auto，入口卡与操作行过渡在减弱动效时停用。
8. **设置页是作者语言飞地**：RP 用户点「账户设置」进入的 GlobalSettingsView 用
   `.btn-primary`/`.form-input` 等 Editorial 类（GlobalSettingsView.vue:283-324），
   仅借用 `rp-icon-button` 返回箭头（:217-223）；`returningToRp` 只删减区块，无 RP 视觉适配。
9. **已解决：消息操作常见可见**。桌面使用跨主题可读的正文色常显，hover/focus 再以边框和
   底色强调；字号升至 13px、按钮最小高 32px，移动端继续使用 42px 触控高度。

**P2 — 反馈闭环与工程欠债**

10. **已解决：导出反馈闭环**。完整记录和故事正文下载触发后分别显示明确成功 toast；失败仍说明
    旅程内容未受影响。
11. **操作无按钮级 loading**：开场创建发送钮文本仅变「…」（JourneyListView.vue:358）；
    重新生成/停止/归档等仅布尔禁用 + 一行「正在停止…」（InteractionView.vue:1854），
    不满足主规范 §5.1 按钮 loading 状态矩阵。
12. **「重新生成」仅挂在最后一条 story 消息上**（InteractionView.vue:1662-1667），
    历史段落只能经分支树切换，路径深。
13. **定位轨可发现性低、触摸目标小**：34px 宽、ticks 12×3px（`styles.css` 的定位轨规则、
    定位轨 tick 规则），preview 仅 hover/focus 显示（定位轨 preview 规则）。
14. **RP token 与测试钩子欠债**：`--rp-*` 变量硬编码 hex（`styles.css` 的 RP token 块）未收编；
    `e2e/helpers/selectors.js` 无任何 RP 条目（已核实 grep），e2e 靠 class/aria 硬编码，
    本路径也无 `data-action` 约定，改样式类名即打碎 e2e。

## 3. 目标布局与信息层级

### 3.1 home（双入口，HomeChoiceView.vue，58 行）

- Primary：双入口卡片（`data-entry="author"` / `data-entry="rp"`）；RP 卡是画像 B 的主路径。
- Secondary：品牌行 `◆ NovelCraft` + h1「今天想怎样进入故事？」+ 副文案（:38-42）。
- Tertiary：无。本页不出现导航、设置、计数等任何第三层信息。
- 第一视觉焦点：h1 → RP 卡。两卡视觉权重相等，不得用色彩把 RP 卡做成「次入口」。
- 阅读路径：品牌 → 提问式 h1 → 副文案 → 双卡（横向并列，移动端纵向作者卡在上）。

### 3.2 journeys（旅程列表 + 开场创建）

- Primary：新旅程按「资料来源 → 作品/文件 → 整理与歧义 → 角色与开场」逐步展开；直接描述
  路径只需选择资料来源后即进入开场。
- Secondary：旅程目录（`role=tablist` 进行中/已归档 + 搜索 + 卡片列表 + 加载更多）。
- Tertiary：吸顶 header（返回箭头、「账户设置」）、模式开关行、字数/快捷键/数据告知小字。
- 第一视觉焦点：首次新旅程为资料来源选择，回到第 4 步才是开场 textarea；已有旅程时为第一张
  进行中旅程卡。
- 阅读路径：标题 → 当前一步 → 已完成步骤摘要/返回修改 → 开场；「账户设置」是次级出口，
  不得在视觉上与主操作竞争。

### 3.3 interaction（流式阅读/对话，InteractionView.vue，2063 行）

- Primary：消息流（`rp-story-scroll`，故事正文）。
- Secondary：底部 composer dock（继续旅程输入 + 发送/停止）。
- Tertiary：顶栏（返回、标题、更多菜单）、定位轨、新内容浮钮、冲突横幅、四个 drawer
  （回顾/生成记录/分支历史/内容与数据）。
- 第一视觉焦点：最新一段故事正文；进入时定位到上次阅读位置。
- 阅读路径：自上而下连续阅读 → 到底部 composer 就地继续；分支、回顾、导出等
  全部经由就地操作行或更多菜单渐进展开，不打断阅读流。

## 4. 逐区域标准

### 4.1 interaction · 消息流阅读排版

- 字号：默认 `--text-md` 16px（主规范 §3.2 长正文档），衬线 `--font-body`（现状
  `styles.css` 的故事正文规则已满足，保持）。不提供无限调节；如需个性化，仅以「阅读设置」
  次级入口提供字号 A−/A+ 与行宽窄/标准两档（P2，属产品假设，需真实用户验证）。
- 行宽：从 760px（≈47 字）收敛到 32-40 个中文字符（约 560-660px，精确值执行时核实），
  与主规范 §3.2 对齐；移动端 100% 视口宽减安全 padding。
- 行高：1.8-1.9（`--leading-loose` 档），段落间距 0.9em 保持（`styles.css` 的故事段落规则）。
- 用户消息气泡（右缩进 + 灰底圆角，用户消息规则）保留，颜色改走 RP token。
- 流式段落必须有专属视觉：行内光标或左边线呼吸指示 + 与已提交段落的可感知差异；
  `prefers-reduced-motion` 下全部降级为静态标记。
- 消息操作行：桌面和移动端均以 `--rp-text` 正文色常显，字号为 13px；hover/focus 只增加
  边框与底色提示，移动端触控高度保持 42px。
- 流式跟随滚动：去掉逐 chunk 的 smooth 滚动（`scroll-behavior:smooth` 不得作用于
  高频 `scrollTop` 赋值；仅在用户点击「继续查看生成 ↓」等离散动作时平滑）。

### 4.2 interaction · composer

- 保留现状能力：自适应 2-8 行（InteractionView.vue:232-246）、⌘/Ctrl+Enter 发送
  （:636-642）、10 万字上限 9 万起显计数（:199-200、:1855-1858）、连接告警（:1859-）、
  分支切换保留草稿并提示（:1816-1818）、编辑旧输入提示（:1812-1815）。
- 发送/停止按钮补 loading 态（spinner 替换图标、宽度不抖动，主规范 §5.1 状态矩阵），
  pending 期间禁用。
- 模式工具行（回顾/自主发展/行动选项 + 状态文案）移动端横向滚动且隐藏滚动条的现状
  （`styles.css` 的模式工具行移动规则）保留；触控目标 ≥42px。
- 未连接时 composer 保留草稿并可编辑，仅禁用发送（现状行为，保持）。

### 4.3 interaction · 分支选择

- 内联 `rp-branch-popover`（`role=group`「选择故事分支」，InteractionView.vue:1675-1693）
  保留：当前 + 最近 2 个内联，>3 个进「查看所有分支」drawer；移动端变底部 sheet
  （`styles.css` 的分支选择移动规则）保留。
- 「重新生成」从仅最后一条（:1662-1667）扩展为每条 story 消息操作行可达（P2，
  与分支切换同一视觉语义）。
- 切换分支时 composer 草稿保留 + 提示（:848-858）是有声契约，不得回归。

### 4.4 interaction · 回顾 drawer

- 7 个固定 section（InteractionView.vue:62-70）、`refreshing/failed/forming` 状态机
  （:1915-1919）、手动纠正 → textarea 编辑 → epoch 乐观锁保存、409 冲突双按钮
  （:1932-1940）全部保留。
- drawer 430px（`styles.css` 的 `.rp-drawer` 规则）、移动端全屏保留；
  视觉材质（表面、hairline、按钮）向 RP token 块收敛，与作者侧 drawer 不互相模仿。

### 4.5 journeys · 列表

- 卡片 grid `1fr auto`（`styles.css` 的 journey 卡片规则）与右侧 action 列（归档/恢复/永久删除）
  保留；移动端 action 列折行现状保留。
- **确认范式统一**：归档与永久删除废弃原生 `confirm`/`prompt`
  （JourneyListView.vue:262、283-286），统一走定制确认（复用 RpAdaptiveConfirmPopover
  或壳层 modal 服务）；永久删除的「输入完整标题」二次确认语义保留，仅换实现。
  确认按钮文案写动作本身（「永久删除」而非「确定」，主规范 §5.6）。
- see-sea 进行中旅程的 7px 脉冲点（JourneyListView.vue:455）补文字状态
  （如「正在生成 · 点入观看」），`aria-label="正在生成"` 保留并扩展为完整可访问名称。
- 空态三分支（搜索无结果/进行中为空/已归档为空，:445-447）保持用户语言。

### 4.6 journeys · 开场 composer

- `RpSourceSetup` 使用四步原生流程，只挂载当前步骤的复杂字段；已完成步骤显示作者可读摘要并可
  返回修改，未来步骤不可跳转。步骤号随原 `rpSourceSetupDraft:v1` 会话草稿恢复，不新增路由或
  状态层。作品选择、文件预览、整理任务、关键歧义、章节内剧情候选、章节+offset 可见边界和
  source revision/hash 均继续复用既有 API 与状态。
- 会话草稿属于当前账户的私有浏览器状态：同账户刷新可恢复，切换或退出账户必须清理。作品、
  revision、整理轮询、歧义确认和剧情匹配的晚到响应只能写回发起请求时的同一作品与版本；
  用户已切换来源时必须静默丢弃。
- textarea + 圆形发送钮 + 模式开关行 + 看海确认 popover + 字数/错误/快捷键/数据告知只在第 4 步
  展示；返回前一步不清空开场草稿。
- 自然语言剧情点匹配只显示候选，必须由用户点击才成为进入位置；作品未 ready 或未选择剧情点时
  不得提前展开身份/开场。
- 作品整理与故事生成明确说明使用用户在账户中连接的 AI 服务；请求经本站后端代理，Key 不进入
  浏览器或作品。不得使用暗示平台代付或浏览器持有 Key 的文案。
- 发送钮文本变「…」（:358）改为 spinner + disabled 的正式 loading 态。
- 看海确认继续用 RpAdaptiveConfirmPopover（visualViewport 定位、Teleport body、
  720px 下按钮 ≥44px），视觉随 RP token 块收敛。

### 4.7 home · 双入口

- 单屏居中双卡（`styles.css` 的 home 双入口规则：`min(960px,100%)`、卡片 min-height 260px、
  hover 上浮 2px）保留；720px 档转单列保留。
- **修复主题响应**：`.entry-choice` 纳入主题覆写范围，消除 dark 主题白屏闪烁（问题 3）。
- 作者卡打开失败回 `project` + toast（HomeChoiceView.vue:44-49）的降级路径保留。
- 大圆角卡片与圆形按钮等 RP 特有形态，作为「第二外观」收编为 RP 专有 token
  （如 `--rp-radius-card`），不套用作者工作台 `--radius-md` 卡片标准，也禁止回流作者侧。

### 4.8 沉浸外壳、主题入口与 return_to 往返

- `showAuthorChrome` 判定（ShellApp.vue:63-72）与 `.main-layout--immersive` 样式
  （`styles.css` 的 `.main-layout--immersive` 规则）保留；硬编码 `#fff` 收编 token（问题 14），
  Editorial 装饰抹除有测试锁定（tests/editorialTheme.test.js:73-77），改动须同步。
- **主题切换裁定**：沉浸路径隐藏 Topbar，RP 侧**保留** InteractionView 内置
  `rp-more-menu__themes`（:1584-1596），与 Topbar ThemePicker 的双入口是有意设计、
  不属重复缺陷；但必须统一两者语义——RP 版升级为 `role=menu`/`menuitemradio`、
  方向键导航、Escape 关闭与焦点管理，视觉与 ThemePicker 菜单对齐；两处继续共享
  `SHELL_THEMES`（useTheme.js:3-7）与 `shell-theme-request` 事件通道（ShellApp.vue:5）。
- return_to 白名单 `normalizeRpReturnTarget()`（navigation.js:23-31：
  `journeys`、`journeys:new`、`interaction:<uuid>`）不得放宽；发出方
  （JourneyListView.vue:243-246、InteractionView.vue:219-224）与接收方
  （GlobalSettingsView.vue:34-37、95-107、217-234、327）行为保留。
- 设置页 RP 往返态做最低限度视觉适配（返回箭头、隐藏区块现状保留），
  不引入作者侧完整视觉；完整 RP 化属 P2。

## 5. 状态覆盖清单（逐项现状缺口与目标形态）

| 状态 | 现状 | 缺口 | 目标形态 |
|---|---|---|---|
| 首屏加载（两视图） | island load 前置，白屏（interactionIsland.js:11-86） | 无骨架 | `.loading-skeleton` 骨架屏（主规范 §5.9），reduced-motion 禁动画 |
| journeys 空态 | 三分支空态（JourneyListView.vue:445-447） | 无 | 保持，文案维持用户语言 |
| 列表加载失败 | `role=alert` 卡片 + 重试（:320-324） | 散装样式 | 收敛 `.error-card` 基准（主规范 §5.9） |
| 开场创建中 | 发送钮文本变「…」（:358） | 无 spinner | spinner + disabled，宽度不抖动 |
| 新旅程设置 | 四步只展示当前决定；已完成步骤保留摘要和返回入口 | 无 | 刷新恢复步骤、作品 revision、剧情点与身份草稿；整理中可离开 |
| 创建失败 | 内联错误 + 按 action 跳连接（:395-402） | 无 | 保持 |
| 无模型连接 | 双入口 callout（:336-340、:410-413；InteractionView.vue:1859-） | 无 | 保持 |
| 流式中 | 「正在生成／未完成」文字 + 左线和轻底色 + `aria-busy` | 与已提交段落可区分 | 保持；reduced-motion 下停用可选动画 |
| 生成失败/取消 | `role=alert` 错误块按 action 分派（:1738-1756） | 重试无按钮 loading | 补按钮级 loading（问题 11） |
| 导出成功 | 下载后显示「故事正文已导出／完整记录已导出」toast | 无 | 保持；离页后的迟到响应不下载、不提示 |
| 窄屏 | 760px 档 + 底部 sheet + drawer 全屏（`styles.css` 的 RP 响应式规则） | 中间档阅读列与定位轨仍需复核；顶栏无 safe-area | 见 §6 |
| 已覆盖保持项 | preparing_context（:1720-1722）、断线重连/60 秒放弃（:1729、:531-558）、awaiting_continue 三键（:1732-1737）、选择冲突横幅（:1805-1809）、回顾失败/409 冲突（:1923-1940）、离开守卫（:1504-1513）、故事完结（:1757） | 无 | 保持现状行为与可访问语义，仅随 token 收编换视觉材质 |

## 6. 响应式行为（RP 以移动阅读为主，移动档优先）

- **移动档（<760px）是一等公民**：本路径设计从移动阅读出发，桌面是加宽版而非反之。
  断点随主规范 §6 从 720px 合并到 760px（改动时同步 e2e 的 390px 用例）。
- 触控目标：按钮 ≥42px、输入 ≥44px；定位轨 ticks 从 12×3px 加宽加大
  （现状 `styles.css` 的定位轨规则），轨体可保持收窄半透明。
- 底部 sheet（更多菜单、分支 popover）与 drawer 全屏现状保留；`safe-area-inset-bottom`
  已处理（分支选择移动规则），**补**顶栏与 composer dock 的 safe-area 处理。
- 中间档 760-1100px：阅读列按 §4.1 收敛后的行宽居中，不出现 760px 大留白；定位轨可隐藏。
- 390px 页面级横向溢出零容忍（e2e 已锁定，interaction.spec.js:193-238，保持）。
- 横屏/折叠屏不做专门布局，保证不溢出、composer 可达即可（执行时核实实际表现）。

## 7. 必须保留的契约（全部 #id、data-\*、role/可访问名称清单）

**#id**

- `#rp-opening-title`（JourneyListView.vue:333，开场卡 aria-labelledby 目标）
- `#rp-new-journey-see-sea-confirm`（JourneyListView.vue:386，popover id + aria-controls）
- `#rp-story-see-sea-confirm`（InteractionView.vue:1900，同）
- `${id}-title` / `${id}-message`（RpAdaptiveConfirmPopover.vue:152-153）
- 壳层：`#main-layout`、`#contextual-notes`（ShellApp.vue:10、13）

**data-\***

- `data-entry="author|rp"`（HomeChoiceView.vue:44、50）
- `data-rp-message-id`（InteractionView.vue:1616、1645；定位/恢复滚动/e2e 依赖）
- `data-placement`（RpAdaptiveConfirmPopover.vue:139）
- `data-provider-id`（GlobalSettingsView.vue:255）
- 现状**无** `data-action` / `data-testid`；新增语义钩子前先沉淀
  `e2e/helpers/selectors.js` RP 条目，e2e 禁止继续硬编码 class。

**role / 可访问名称（按视图）**

- HomeChoiceView：`aria-label="选择使用方式"`（:43）。
- JourneyListView：返回钮动态 label「返回旅程列表/返回使用方式」（:310）；`role=alert`
  加载失败（:320）；开场卡 `aria-labelledby`（:329）；textarea「旅程开场」（:347）；
  发送「开始旅程」（:356）；看海钮 `aria-pressed/haspopup=dialog/expanded/controls`
  （:370-373）；`role=alert` 创建错误（:395）；`role=tablist`「旅程状态」+ `role=tab`
  （:415-417）；搜索框「搜索旅程」（:433）；`role=status` 空态（:445）；
  生成点「正在生成」（:455）；「归档旅程：{title}」「恢复旅程：{title}」
  「永久删除旅程：{title}」（:488-491）。
- RpSourceSetup：`aria-label="新旅程设置进度"`；当前项 `aria-current="step"`；已完成步骤为原生
  返回按钮；当前步骤标题可程序聚焦；资料方式、作品/文件、剧情点候选、身份字段继续使用原生
  fieldset、label、button 和 select。
- InteractionView：「返回旅程列表」（:1558）；summary「更多操作」（:1564）；
  「关闭更多操作」×2（:1568、1574）；主题区 `aria-label="主题"` + `aria-pressed`
  （:1584-1592，升级 menu 语义时保持可访问名称不变）；分支 popover `role=group`
  「选择故事分支」（:1675）；「行动建议」（:1703）；流式 `aria-busy`（:1718）；
  `role=status`「正在整理最近剧情…」（:1720）；流式错误动态 role（:1729）；
  `role=alert` 失败块（:1738）；定位轨 nav「快速定位生成段落」（:1771）+ range 动态
  label「第 n 段，共 m 段：…」（:1797）；`role=alert` 冲突横幅（:1805）；
  textarea「继续旅程」（:1825）；「停止生成」（:1834）；「发送消息」（:1849-1850）；
  四个 drawer `aria-label`「当前回顾/生成记录/分支历史/内容与数据」+ 各自「关闭…」
  （:1911、1921、1976、1982、1999、2002、2046、2049）；失败页 `role=alert`（:2060）。
- RpAdaptiveConfirmPopover：`role=alertdialog`、`aria-modal="false"`、Esc 关闭（:146-150）。

改任何可访问名称必须全局 grep 同步 e2e 的 `getByRole({name})` / `getByText`（主规范 §9）。

## 8. 验收标准 + 验证命令

**验收标准**

- §7 全部 `#id` / `data-*` / role / 可访问名称不变（改动需逐项说明并同步 e2e）。
- 问题 1-3（流式视觉、首屏骨架、home 主题闪烁）修复后可人工复验；问题 5、6、10、11
  有对应实现与测试。
- 390px 无横向溢出；760px 断点合并后移动档行为不回归；reduced-motion 下流式指示、
  骨架、脉冲全部降级。
- RP token 块（含 `--rp-accent` 系与 RP 专有圆角）收编完成，作者工作台页面零引用
  （grep 验证）。
- `selectors.js` 新增 RP 条目，interaction/home e2e 改为引用选择器而非硬编码 class。
- `make docs-check BASE_REF=origin/main` 无漂移，或逐项说明无文档影响。

**验证命令**

```bash
# 仓库根：架构文档清单
make docs-check BASE_REF=origin/main

# 前端单测（token / 骨架 / 主题契约）
cd frontend-console
npx vitest run tests/editorialTheme.test.js tests/typographyTokens.test.js tests/loadingSkeleton.test.js

# RP 路径 e2e（双入口、390px 不横溢、底部 sheet、主题切换、看海 popover）
npm run test:e2e:functional -- e2e/home.spec.js e2e/interaction.spec.js
```
