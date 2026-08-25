# Generate 高级生成 UI/UX 执行规范

> 上级标准：`../design-standard.md`（Editorial Archive 唯一权威，下称「主规范」，§x 均指该文件）。本文只做分页落地，不重复定义 token。
> 覆盖旧 `#workbench/<id>/generate` 深链承接到所属页面 AI 抽屉后的四个模式：world（世界设定聊天）、pov_prose（角色视角正文）、task（参考资料整理）、preview（完整参考资料）。

## 1. 页面定位与目标画像

- **定位**：画像 A（长期创作作家）的高级生成工作台——用自然语言与世界书共建设定草稿、按角色视角试写正文、审计 AI 实际使用的上下文。topbar 自我定位为「面向高级用法的生成与上下文工具」（`vue/shell/ShellApp.vue:83`）。
- **目标画像**：画像 A 中的进阶用户。**豁免边界**：本页允许暴露 token 预算、Tier/section、revision/hash 等技术概念（task/preview tab 的审计语义需要），但仅限明确的诊断区域；world 聊天和 pov 正文是创作面，文案必须用作者语言（不得出现 raw ID、内部枚举、prompt 术语）。
- **用户任务**：聊天共建世界设定草稿 → 审阅/采纳提案；选章节+视角试写正文 → 落入写作页；编译并审计上下文 → 导出或注入聊天。
- **喜欢它的理由**：生成结果始终是「建议/草稿」不静默写入正史；上下文可审计、可导出；复杂配置渐进展开。
- **主要摩擦**：四 tab 形态割裂、生成进度反馈弱、弹窗与全局样式耦合（见 §2）。

## 2. 现状问题清单（按严重度排序）

| # | 严重度 | 问题 | 证据 |
|---|---|---|---|
| 1 | 已修复 | `GenerateView.vue` 不再包含全局 `<style>`；布局、收束、探索、视觉简报与窄屏规则统一收编到 `styles.css` 的 Generate 段，`.topbar-generate-note` 保持单份来源 | `frontend-console/styles.css` 的 Generate 视图段；`frontend-console/vue/views/generate/GenerateView.vue` 无 `<style>` |
| 2 | 高 | 弹窗耦合约束：模板编辑器、章节选择器、上下文查看三处弹窗 HTML 由 `showModalHtml` 注入字符串，依赖上述全局类，直接改 `scoped` 会破坏弹窗样式——收编必须先迁移样式再改弹窗 | `GenerateView.vue:255, 265-266`（弹窗 HTML 字符串） |
| 3 | 已修复 | task、world 与 pov 均有分阶段/百分比等待、聚焦的原位错误与重试；失败时保留作者输入，pov 加载失败也可在原位重试 | `components/TaskContextTab.vue`；`components/WorldWorkspace.vue`；`components/PovProseTab.vue` |
| 4 | 中／部分修复 | task 与 pov 已统一为作者表单/结果双栏、窄屏降单列且主操作留在表单内；preview 已复用 task 的资料审阅层，world 仍保留独立聊天布局 | `components/TaskContextTab.vue`；`components/ContextPreviewTab.vue`；`components/PovProseTab.vue`；`styles.css` 的 Generate 段 |
| 5 | 已修复 | task 页头重复操作已移除；表单只保留「整理参考资料」主操作，Markdown、复制、导出与带到对话均位于结果区 | `GenerateView.vue`；`components/TaskContextTab.vue` |
| 6 | 已修复 | task、preview 与 pov 创作面使用作者语言；上下文主视图显示资料标题、采用状态、加入理由和可核对来源，内部分区、估算长度与裁剪记录只在折叠诊断区出现 | `components/TaskContextTab.vue`；`components/ContextPreviewTab.vue`；`components/ContextBundleView.vue`；`components/PovProseTab.vue` |
| 7 | 已修复 | task 输出使用 `#gen-task-output`，独立 Markdown 预览使用 `#gen-preview-output` | `TaskContextTab.vue`；`ContextPreviewTab.vue` |
| 8 | 已修复 | composer 改为原生表单，发送按钮位于 textarea 外的 footer；390px 下按钮整行展示，拖高 textarea 不再发生覆盖 | `components/WorldWorkspace.vue`；`styles.css` 的 `.generate-composer*` 规则 |
| 9 | 已修复 | world chatbox 在高度不超过 660px 的桌面/横屏窗口解除固定高度与嵌套裁切，消息区保留有界滚动，页面主滚动可到达全部操作 | `styles.css` 的 Generate 矮窗口媒体查询 |
| 10 | 低 | 同名语义两处维护：`#generate-include-world-synopsis`（world）与 `#gen-include-world-synopsis`（task）并存 | `WorldWorkspace.vue:78`；`TaskContextTab.vue:20` |
| 11 | 低／部分修复 | task/preview 的资料审阅、错误、空态和操作密度已统一为 `generate-*` 结构；task 表单仍复用全局 `.form-group` / `.gen-form-section` 基础控件 | `TaskContextTab.vue`、`ContextPreviewTab.vue`、`ContextBundleView.vue` |
| 12 | 低 | generate 页在 `e2e/helpers/selectors.js` 无任何条目，e2e 全靠 role/label 语义钩子；新增 data 钩子需同步 `generate.spec.js` 现有约定 | `e2e/helpers/selectors.js`；`e2e/generate.spec.js` |

### GenerateView 样式收编状态（问题 1/2）

1. 已将 SFC 单行样式整体迁出并格式化到 `styles.css` 的 Generate 结构段；材质继续引用现有 token。
2. **类名保持 `generate-*` 不变**（全局类），因为三处弹窗 HTML 字符串仍需使用这些类；待弹窗组件化后再评估 scoped 化。
3. `.topbar-generate-note` 已保留单份来源；900px/390px 组件级断点与 Generate 规则放在同一结构段。

## 3. 目标布局与信息层级

- **tab 栏**：owner 页只显示一层「设定共创／写作建议／整理资料／查找资料」类别导航，嵌入的 Generate 不再重复渲染模式栏；独立兼容页面仍保留 `.subnav.generate-subtabs`，旧深链跨「人物与世界／写作」归属时替换到正确 owner 页，刷新不读错会话。
- **header 操作区**：每 tab 至多 1 个 primary；task 页头不放操作，表单内只保留「整理参考资料」，输出动作在结果区就地完成。
- **world**：聊天为主对象；来源下方只用一行「本轮方向」摘要定位当前目标，3 个互斥目标、对象类型和页面模板收进原生 `details`。生成建议与发送都留在输入区，生成后的建议优先于方向设置、在聊天工作区上方使用完整主栏宽度审阅。右侧 rail 只管理「本轮参考资料」；窄屏把主创作区放在资料栏之前，避免展开资料后找不到输入位置。
- **pov**：左表单右结果，表单为主；结果卡 pending/成功/空态分层清晰。
- **task**：常用任务作为表单内的可选原生选择器，只负责预填下方任务；任务输入与唯一主操作优先出现，本次参考资料留在同一流程。整理成功前不提前显示结果动作；成功后只突出「查看完整资料」，「带到世界设定对话」保持次级，复制与导出只在完整资料页出现。
- **preview**：沿用同一份作者可读资料审阅，再渐进展开可复制完整文本；主视图不展示 raw key、ID、token 或内部枚举。

## 4. 逐区域标准

### 4.1 world 聊天 composer（`WorldWorkspace.vue`）

- 消息区 `#generate-chat-messages`：气泡区分 user/assistant，正文 `--text-base` / `--leading-normal`；空态引导文案保留（:41）。
- composer：使用原生 `<form>`，`#generate-chat-input` 有可见 label 与持久提示，`data-action="send-chat-message"` 位于 textarea 外的 footer；Cmd/Ctrl+Enter 发送与 IME 组合保护保留。未发送内容继续保存到当前浏览器。
- 生成中：助手占位依次显示“理解目标 → 核对设定和前文 → 组织回复”，发送按钮 loading/disabled；只有作者本轮发送才强制滚到最新消息，晚到回复不会抢走正在阅读的历史位置。
- 生成失败：错误气泡使用 `role="alert"`，聚焦 `data-action="retry-chat-message"`；重试复用原作者消息，不重复插入。世界建议使用骨架等待和 `data-action="retry-world-suggestion"` 原位重试，失败不销毁已有可编辑提案。
- 右侧 rail：`<details>` 折叠 + 按项目 sessionStorage 持久化保留；只显示本轮参考资料摘要，高频的复核、简介和正文选择常驻，精确资料与已发布创作规则渐进展开。窄屏首次进入默认折叠并排在主创作区之后，显式开合偏好仍按项目恢复。
- 结果：空态不占用额外卡片；生成中、失败或已有建议时，`#generate-result` 在 chatbox 前使用完整主栏宽度。提案编辑器（WorldResult）保持「建议→采纳」语义，`data-action="apply-world-page-draft"` 仍为主操作；失败保留上一份可编辑提案，刷新恢复与离开确认不变。
- 收束结果中的地图事实来源统一打开一级 Map 工作区的概览态，不进入兼容的 `world/map` 子路由。
- 收编约束：常规桌面保留视口内消息工作区；高度不超过 660px 时解除 chatbox 固定高度与裁切，页面可滚动到完整 composer 和 rail；`:has()` 折叠切换保留。

### 4.2 POV 正文（`PovProseTab.vue`）

- 使用原生 `<form>`：章节、场景、「由谁来感受这一场」和作者指令在同一卡片完成；`data-action="generate-pov-prose"` 是表单内唯一主操作，不再脱离必填项放在页头。
- 保护规则使用作者语言「角色只会知道自己应当知道的事」；不在创作面展示「逐事实可见性过滤链」「结构化 POV 面板」或 raw 角色 ID。
- 进度保留百分比与原生 `<progress>`；取消失败不伪装成已停止。失败卡使用 `role="alert"`、自动聚焦，并以 `data-action="retry-pov-prose"` 按当前选择重试。
- 成功卡明确「不会自动覆盖正文」，`data-action="open-generated-destination"` 一跳到精确写作候选；作者到写作台核对知识越界后再采用。
- 加载中、加载失败、无章节和场景失败分开：整体加载失败可 `retry-pov-options`，场景失败可 `retry-pov-scenes`；表单和作者指令不因失败、弹窗取消或任务取消清空。
- 章节、场景、角色和作者指令进入既有有界 Generate 会话，按项目隔离；owner 类别、刷新、前进/后退和项目切换恢复同一流程，旧会话缺字段仍兼容。

### 4.3 上下文编译 task（`TaskContextTab.vue`）

- 常用任务使用有可见 label 和说明的原生 `<select id="gen-task-preset">`，选择只填入适合作者理解的任务模板，作者仍可继续改写。
- 使用原生 `<form>`；目标、范围与主要上下文保持可见，章节、场景、资料长度等低频条件收进「更多条件」原生 `<details>`。
- 「整理参考资料」是唯一主操作；完成后 `ContextBundleView` 留在当前任务中，按「资料总览 → 会交给 AI 的资料 → 仅供作者约束」显示标题、来源、状态、加入理由、裁剪与遗漏，只有作者显式点击才进入完整文本或带到对话。
- 编译中显示阶段骨架；失败时聚焦原位错误卡并提供精确重试，不清空作者输入，也不销毁上一次成功的资料摘要。服务端错误细节不直接暴露给作者。
- 任务描述、预设和条件保存到既有、有界、按项目隔离的 Generate 会话；URL 同步外层 AI 类别，刷新、前进/后退和项目切换不串稿。该会话不产生服务端内容写入。

### 4.4 完整参考资料 preview（`ContextPreviewTab.vue`）

- 来源、范围、采用状态、加入理由、摘要和来源标签始终先于完整文本显示；技术诊断收进默认关闭的原生 `<details>`。
- 只有作者点击「查看完整资料／准备可复制文本」才请求 Markdown。准备失败时保留资料摘要，聚焦错误卡并只重试 render，不重复 compile。
- Markdown 放入次级原生 `<details>`；复制、导出只在文本可用时出现，操作区最多一个主按钮。空态提供「去整理参考资料」返回行动。
- `#gen-preview-output`、当前模式和按项目隔离的预览进入当前标签页的有界会话存储；刷新、返回和项目切换保持正确资料。超过 512 KiB 时刷新仅恢复资料摘要，完整文本可重新准备。

## 5. 状态覆盖清单

| 状态 | 锚点 | 标准 |
|---|---|---|
| 聊天空态 | `#generate-chat-messages` 空态提示（WorldWorkspace.vue:41） | 引导文案 + 来源条说明当前生成目标 |
| 生成中（world/pov/task） | world/task 阶段提示 / `.loading N%` | 三种模式均有阶段或百分比反馈；按钮 pending 期禁用 |
| 生成失败 | world 错误气泡/`.generate-result-error`；task `.error-card`；pov `.generate-pov-error` | 三种模式均使用人话说明 + 聚焦重试并保留输入；取消与失败语义分开 |
| pov 无章节/加载失败 | `PovProseTab.vue` | 无章节为空态三件套 + 两个出路；整体/场景加载失败均原位重试 |
| task 输出空态 | `TaskContextTab.vue` | 引导先选预设/写描述再整理；成功结果与后续失败可同时保留 |
| preview 空态 | `ContextPreviewTab.vue` | 说明不会修改作品，并提供「去整理参考资料」行动 |
| preview 准备失败 | `.generate-task-error` | 保留资料摘要、自动聚焦并精确重试完整文本，不重复整理资料 |
| 弹窗（模板/章节/上下文查看） | `showModalHtml` 注入 | 焦点陷阱/ESC 由 `ui/modal.js` 保证，收编样式时不得破坏 |
| 窄屏 <760 | Generate 响应式规则 | 见 §6；owner 页只保留一层 3 列类别导航；发送按钮可滚动到固定底栏上方 |

## 6. 响应式行为（四档）

断点以主规范 §6 终态为准（760/1100）；本页内联 900px 断点归入 760 档（执行时核实 editorial-theme.css:1280+ 窄屏块的实际断点后合并）。

- **Desktop ≥1440**：各 tab 双栏栅格默认形态；chatbox 视口高度固定但加矮窗口保护。
- **Laptop 1100-1440**：同 Desktop 默认形态。
- **Tablet 760-1100**：rail 收窄可折叠（world 的 `:has()` 折叠保留）；pov/task 双栏比例收紧但不并栏。
- **Mobile <760**：全部降单列、解除固定高度；owner 的单层类别导航为 3 个等宽入口且触控高度 ≥44px，独立兼容页的 subtabs 才使用两列 wrap；世界目标保留 3 个按钮，对象模板使用原生选择器。composer、pov 与 preview 操作栏纵向排列，主操作整行且可滚动到固定底栏上方；资料来源标签换行，诊断表格在抽屉内折行，零页面级横向溢出。

## 7. 必须保留的契约

### #id

`owner-ai-tab-<key>` / `owner-ai-panel-<key>`（key ∈ world/writing/task/evidence）；`generate-mode-tab-<key>` / `generate-mode-panel-<key>`（key ∈ world/pov_prose/task/preview，独立兼容页面与旧深链保留）；`generate-object-template` / `generate-object-template-hint`；`generate-template-editor-select/name/prompt`、`generate-template-history-load`、`generate-template-history`；`generate-chapter-<index>`；`generate-template-row`、`generate-new-page-type`、`generate-new-page-template`；`generate-chat-messages`、`generate-chat-input`；`generate-quality-pro`、`generate-include-world-synopsis`、`generate-activation-profile`；`generate-chat-context-usage`、`generate-selected-chapters`；`generate-world-scene/threads/characters/entities`；`generate-result`；`generate-pov-chapter/scene/character/instruction`、`generate-pov-result`；`gen-task-preset(-hint)`、`gen-task`、`gen-scope`、`gen-entities(-picker)`、`gen-characters(-picker)`、`gen-chapter`、`gen-scene(-picker)`、`gen-budget(-hint)`、`gen-reveal`、`gen-include-world-synopsis`、`gen-world-synopsis-visibility-hint`、`gen-viewpoint-character(-group,-picker)`、`gen-task-output`、`gen-preview-output`；`generate-page-title/type/free-text/sections/assets`。

### data-action / data 钩子

`owner-world-generation`、`owner-writing-generation`、`owner-writing-pov-workbench`、`owner-task-context`、`owner-evidence`；`switch-generate-subtab`（带 `data-subtab`，独立兼容页）、`generate-world-suggestion`、`generate-pov-prose`、`retry-pov-prose`、`retry-pov-options`、`retry-pov-scenes`、`run-task`、`retry-task-context`、`render-task-md`、`retry-context-preview`、`start-context-preview`、`apply-to-chat`、`select-world-target`、`select-object-template`、`edit-object-templates`、`return-world-bible`、`send-chat-message`、`retry-chat-message`、`retry-world-suggestion`、`view-generation-context`、`select-source-chapters`、`open-generated-destination`、`continue-chat`、`generate-another`、`apply-world-page-draft`、`open-writing-from-pov-empty`、`return-world-from-pov-empty`、`select-task-preset`（带 `data-preset`）、`copy-task-md`、`export-task-md`；`data-workspace-rail-key`、`data-state="recovered-page-proposal"`、`data-section="advanced-page-data"`。

### role / 可访问名称

owner 页使用 `role="tablist"`（aria-label「AI 工具类别」）、相连的 `role="tab"` / `role="tabpanel"`、roving tabindex 与方向键/Home/End 导航；嵌入的 Generate 面板不再嵌套第二组 tabpanel。独立兼容页继续保留 aria-label「生成模式」的四组 tab/tabpanel。`role="group"` 使用 aria-label「生成目标」；世界目标保留 `aria-pressed`，对象模板和常用任务使用有可见 label 与 `aria-describedby` 的原生 `<select>`；rail summary 保留 `aria-label="收起/展开本轮参考资料"`。world composer 保留可见 label、提示的 `aria-describedby`、等待 `role="status"` 和错误 `role="alert"`；pov 失败使用 `role="alert"` 并聚焦重试卡。e2e 走 `getByRole`/`getByLabel`，改任何可访问名称必须全局 grep 同步 `generate.spec.js`（主规范 §9）。

## 8. 验收标准 + 验证命令

验收标准：

1. GenerateView.vue 内联样式块迁出并格式化，`.topbar-generate-note` 单份来源；三处弹窗样式在新位置下视觉无回归（截图对比）。
2. 四个 tab 生成中均有进度或阶段反馈；失败态向 `.error-card` 收敛。
3. header 操作区每 tab ≤1 个 primary；task 次级操作下沉面板。
4. `#gen-task-output` 重复 id 消除（或经核实确认无引用后维持并注释原因）。
5. composer 发送按钮不再随 textarea resize 错位；矮窗口 chatbox 不溢出。
6. 375px 无页面级横向溢出；owner 类别导航保持单层、三入口完整可见且触控高度不低于 44px。
7. task 草稿在刷新、前进/后退和切换 AI 类别后恢复；切换项目不串用，会话中的晚到响应不得覆盖新项目。
8. task 失败原位显示、聚焦并可重试；完成后结果留在当前任务，只有显式动作才进入 Markdown 预览。
9. world 聊天失败聚焦原位重试，重试不重复作者消息；建议失败保留已有可编辑提案。
10. 390×844 与 812×375 下 composer 无横向溢出，发送按钮不覆盖 textarea，且可避开固定底栏。
11. pov 主操作位于原生表单内；加载失败和生成失败均可原位重试，失败焦点可达，弹窗取消不清空表单。
12. pov 的 owner 类别、章节/场景/角色/作者指令在刷新、前进/后退和项目切换后恢复，且不同项目不串稿。
13. task/preview 主视图不暴露 raw key、ID、token 或内部枚举；重复来源/提示不产生 Vue key 错误，动态摘要按文本转义。
14. preview 刷新后恢复当前资料和 URL 位置，返回后任务仍在；切换项目不串用资料，render 失败只重试 render。
15. owner 类别导航与其 panel 正确关联；嵌入 Generate 不重复显示「生成模式」，写作建议可进入角色视角正文并明确返回。

验证命令（在 `frontend-console/` 下执行）：

```bash
npm run test:e2e:functional -- e2e/generate.spec.js     # 功能契约（tab 导航、聊天、提案、pov、task 编译）
npm run test                                 # vitest 单测（含 editorialTheme/typographyTokens 契约，样式迁移后必跑）
```

task 页已有 sticky／night／ink 三主题桌面快照及 night 手机快照；world composer 另有 sticky 桌面、night 手机与 sticky 矮窗口快照；pov 有 sticky 桌面与 night 390px 手机快照；AI 参考资料审阅另有 sticky 桌面与 night 390px 手机快照。均位于 `e2e/visual-generate.spec.js-snapshots/`。使用 `npm run test:e2e:visual -- e2e/visual-generate.spec.js` 校验，需要确认视觉变化时才加 `--update-snapshots`。
