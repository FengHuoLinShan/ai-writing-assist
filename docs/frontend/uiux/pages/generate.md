# Generate 高级生成 UI/UX 执行规范

> 上级标准：`../design-standard.md`（Editorial Archive 唯一权威，下称「主规范」，§x 均指该文件）。本文只做分页落地，不重复定义 token。
> 覆盖 `#workbench/<id>/generate` 的四个 tab：world（世界设定聊天）、pov_prose（角色视角正文）、task（上下文编译）、preview（上下文预览）。

## 1. 页面定位与目标画像

- **定位**：画像 A（长期创作作家）的高级生成工作台——用自然语言与世界书共建设定草稿、按角色视角试写正文、审计 AI 实际使用的上下文。topbar 自我定位为「面向高级用法的生成与上下文工具」（`vue/shell/ShellApp.vue:83`）。
- **目标画像**：画像 A 中的进阶用户。**豁免边界**：本页允许暴露 token 预算、Tier/section、revision/hash 等技术概念（task/preview tab 的审计语义需要），但仅限明确的诊断区域；world 聊天和 pov 正文是创作面，文案必须用作者语言（不得出现 raw ID、内部枚举、prompt 术语）。
- **用户任务**：聊天共建世界设定草稿 → 审阅/采纳提案；选章节+视角试写正文 → 落入写作页；编译并审计上下文 → 导出或注入聊天。
- **喜欢它的理由**：生成结果始终是「建议/草稿」不静默写入正史；上下文可审计、可导出；复杂配置渐进展开。
- **主要摩擦**：四 tab 形态割裂、生成进度反馈弱、弹窗与全局样式耦合（见 §2）。

## 2. 现状问题清单（按严重度排序）

| # | 严重度 | 问题 | 证据 |
|---|---|---|---|
| 1 | 高 | 非 scoped 全局样式块：`<style>` 无 `scoped`，约 60+ 条规则压缩在单行，全局注入且组件卸载后不移除；`.topbar-generate-note` 与 styles.css 重复定义（双份来源）；内联 `@media(max-width:900px)` 与 editorial-theme 窄屏块断点分散 | `frontend-console/vue/views/generate/GenerateView.vue:271-273`；`styles.css:413-424`；`editorial-theme.css:1280-1371` |
| 2 | 高 | 弹窗耦合约束：模板编辑器、章节选择器、上下文查看三处弹窗 HTML 由 `showModalHtml` 注入字符串，依赖上述全局类，直接改 `scoped` 会破坏弹窗样式——收编必须先迁移样式再改弹窗 | `GenerateView.vue:255, 265-266`（弹窗 HTML 字符串） |
| 3 | 高 | 生成进度反馈弱：world 聊天仅「正在思考...」占位；建议生成仅按钮 disabled + 「正在生成…」；task 编译无进度——仅 pov 有百分比轮询，违反主规范 §7「不允许只有 spinner 超过 2s」 | `GenerateView.vue:199, 235`；`components/WorldWorkspace.vue:95`；`components/TaskContextTab.vue:28`；`components/PovProseTab.vue:63` |
| 4 | 中 | tab 间形态割裂：world 78/22 聊天+持久栏、pov 72/28 双栏表单、task 22/78 预设卡左置、preview 单卡只读；栅格方向三个；editorial 主题只给 world 的 chat-panel 做了墨线/档案角标，其余三 tab 无主题特征 | `GenerateView.vue:272`（内联栅格）；`editorial-theme.css:1111-1150` |
| 5 | 中 | header 操作区不稳定：随 tab 从 1 个膨胀到 4 个按钮（task 的编译/预览/渲染/应用到聊天全挤 header，主次不分），preview tab 为空，高度跳动 | `GenerateView.vue:8-21` |
| 6 | 中 | 技术术语外露越过豁免边界：pov 的「逐事实可见性过滤链」提示、task 表单「上下文预算 (tokens)」「揭示模式」直接露出；ContextBundleView 的 Tier/Section/Tokens/Truncated 表属审计豁免区，但列名可加人话辅助 | `components/PovProseTab.vue:25`；`TaskContextTab.vue:18-19`；`ContextBundleView.vue:9-17` |
| 7 | 中 | `#gen-task-output` 在 task 与 preview 两个 tab 各定义一次，互斥渲染所以不冲突，但钩子语义含混、两处维护 | `TaskContextTab.vue:27`；`ContextPreviewTab.vue:12` |
| 8 | 低 | composer 发送按钮绝对定位压 textarea（`position:relative` + `padding-right:76px`），textarea 被 resize 拉高时按钮不动；窄屏 composer 无单独处理 | `GenerateView.vue:272`（`.generate-composer` 内联规则）（执行时核实最终位置） |
| 9 | 低 | world tab chatbox 固定 `height:calc(100vh - 180px); min-height:480px`，矮窗口（<660px 高）溢出；解除高度的媒体查询只按宽度触发 | `GenerateView.vue:272` |
| 10 | 低 | 同名语义两处维护：`#generate-include-world-synopsis`（world）与 `#gen-include-world-synopsis`（task）并存 | `WorldWorkspace.vue:78`；`TaskContextTab.vue:20` |
| 11 | 低 | 视觉体系两套并存：world/pov 用 `generate-*` 内联体系，task/preview 混入全局 `.form-group`/`.data-table`/`.gen-form-section` vanilla 遗留类，控件规格不一致 | `TaskContextTab.vue`、`ContextPreviewTab.vue` 模板（执行时逐类核实） |
| 12 | 低 | generate 页在 `e2e/helpers/selectors.js` 无任何条目，e2e 全靠 role/label 语义钩子；新增 data 钩子需同步 `generate.spec.js` 现有约定 | `e2e/helpers/selectors.js`；`e2e/generate.spec.js` |

### GenerateView.vue:271 收编方案（问题 1/2 的落地路径）

1. 将 272 行单行样式块整体迁出 SFC，格式化后按「结构 vs 材质」拆分：布局/尺寸/栅格规则并入 `styles.css` 的 generate 结构段；颜色/圆角/阴影引用 token 后放入 `editorial-theme.css` 的 generate 段。
2. **类名全部保持 `generate-*` 不变**（全局类），因为三处弹窗 HTML 字符串（`GenerateView.vue:255, 265-266`）无法被 scoped 样式覆盖；待弹窗改造为组件化模板后，非弹窗规则才可降级为 scoped——分两期，不在一次改动里做。
3. 删除 `.topbar-generate-note` 双份来源中的一份（保留 styles.css 或 editorial 单侧，grep 确认后裁定）（执行时核实保留侧）。
4. 内联 `@media(max-width:900px)` 断点并入主规范 §6 的 760px 档叙事，与 editorial-theme.css:1280-1371 的窄屏块合并到一处。

## 3. 目标布局与信息层级

- **tab 栏**：`.subnav.generate-subtabs` 保持 `role="tablist"` + 胶囊样式（editorial 已对齐，现状良好）。
- **header 操作区**：每 tab 至多 1 个 primary；task 的四个操作收敛为「编译上下文」主按钮 + 其余收进面板内次级位置（预览/渲染/导出属于输出区动作，不属于页头）。
- **world**：聊天为主对象（主栏），「上下文与结果」为可折叠 rail——形态保留，但栅格比例向 `--workspace-main-share` 契约靠拢（执行时核实 78/22 与 64/68% 的取舍，rail 不低于 `--workspace-rail-right-min`）。
- **pov**：左表单右结果，表单为主；结果卡 pending/成功/空态分层清晰。
- **task**：预设卡 + 参数表单 + 输出，输出区内的预览/渲染/复制/导出操作就地放置。
- **preview**：单卡只读预览 + 操作行，保持简单；视为 task 输出的展示面，不做独立信息层级。

## 4. 逐区域标准

### 4.1 world 聊天 composer（`WorldWorkspace.vue`）

- 消息区 `#generate-chat-messages`：气泡区分 user/assistant，正文 `--text-base` / `--leading-normal`；空态引导文案保留（:41）。
- composer：`#generate-chat-input` + `data-action="send-chat-message"`；发送按钮从绝对定位改为 flex 行内跟随（消除 resize 错位）；Cmd/Ctrl+Enter 发送与 IME 组合保护保留（:145-151）。
- 生成中：占位消息 + 发送按钮 loading/disabled，超过 2s 需有进度或阶段文案（对齐主规范 §7）。
- 右侧 rail：`<details>` 折叠 + sessionStorage 持久化保留；栏内上下文设置卡控件遵循 §5.2 表单结构；结果卡 `#generate-result` 的提案编辑器（WorldResult）保持「建议→采纳」语义，`data-action="apply-world-page-draft"` 为主操作。
- 收编约束：chatbox 高度改用 `min-height` + 视口计算的下限保护，矮窗口不溢出（问题 9）；`:has()` 折叠切换保留。

### 4.2 POV 正文（`PovProseTab.vue`）

- 三列表单（章节/场景/视角角色）+ 作者指令，label 在上、helper 在下（§5.2）。
- 「逐事实可见性过滤链」提示条改写为作者语言（如「将按该角色在剧情中实际知道的内容过滤设定」），技术名收进 title 或次级说明。
- 进度：百分比轮询保留（本页唯一达标的进度反馈，可作为其他 tab 的参照）；成功卡 `data-action="open-generated-destination"` 一跳到写作页，路径保留。
- 空态链路（加载中/加载失败/无章节含去写作/返回世界两个行动）保留，文案按空态三件套核对。

### 4.3 上下文编译 task（`TaskContextTab.vue`）

- 预设卡 `role="group"`「任务预设」+ `aria-pressed` 保留。
- 「高级设置」`<details>` 渐进展开保留；「上下文预算 (tokens)」加 helper 说明量级含义（属诊断豁免区，但要可读）；ReferencePickerAdapter 多选控件遵循 §5.2。
- 编译/预览/渲染/应用到聊天四个操作从 header 下沉到本 tab：编译为主按钮（header 保留唯一 primary 或面板内），预览/渲染/导出放输出卡操作行。
- 编译中加进度或阶段提示，不得无反馈等待。
- 输出 `ContextBundleView` 表格保留（审计豁免区），列头可加人话辅助文案；技术词汇不出现在表单默认视图。

### 4.4 预览 preview（`ContextPreviewTab.vue`）

- 单卡：来源行 + 操作行（渲染/复制/导出 + 返回）+ 内容区，结构保留。
- `#gen-task-output` id 与 task tab 重复的问题：两 tab 各自改用语义化 id（如 `gen-task-output` 归 task、`gen-preview-output` 归 preview），同步 `generate.spec.js` 与任何桥接代码（执行时核实引用点）。
- markdown `<pre>` 等宽、可滚动、行高可读；空态文案「还未执行任何 AI 生成或上下文编译…」保留并补一个「去编译上下文」行动。

## 5. 状态覆盖清单

| 状态 | 锚点 | 标准 |
|---|---|---|
| 聊天空态 | `#generate-chat-messages` 空态提示（WorldWorkspace.vue:41） | 引导文案 + 来源条说明当前生成目标 |
| 生成中（world/pov/task） | 占位消息 / `.loading N%` / 无 | 全部给进度或阶段文案；按钮 pending 期禁用 |
| 生成失败 | `.generate-error-text` 等散装错误 | 向 `.error-card` 收敛（主规范 §5.9）：人话说明 + 重试；技术细节折叠 |
| pov 无章节/加载失败 | PovProseTab.vue:2-14 | 空态三件套 + 两个出路按钮，已达标保持 |
| task 输出空态 | TaskContextTab.vue:33 | 引导先选预设/写描述再编译 |
| preview 空态 | ContextPreviewTab.vue:14 | 补「去编译上下文」行动 |
| 弹窗（模板/章节/上下文查看） | `showModalHtml` 注入 | 焦点陷阱/ESC 由 `ui/modal.js` 保证，收编样式时不得破坏 |
| 窄屏 <760 | 内联媒体查询 | 见 §6；subtabs 两列 wrap 现状保留 |

## 6. 响应式行为（四档）

断点以主规范 §6 终态为准（760/1100）；本页内联 900px 断点归入 760 档（执行时核实 editorial-theme.css:1280+ 窄屏块的实际断点后合并）。

- **Desktop ≥1440**：各 tab 双栏栅格默认形态；chatbox 视口高度固定但加矮窗口保护。
- **Laptop 1100-1440**：同 Desktop 默认形态。
- **Tablet 760-1100**：rail 收窄可折叠（world 的 `:has()` 折叠保留）；pov/task 双栏比例收紧但不并栏。
- **Mobile <760**：全部降单列、解除固定高度；subtabs 两列 wrap（editorial-theme.css:1334-1348 现状保留）；触控目标 ≥42/44px；composer 发送按钮行内可达；390px 零横向溢出。

## 7. 必须保留的契约

### #id

`generate-mode-tab-<key>` / `generate-mode-panel-<key>`（key ∈ world/pov_prose/task/preview）；`generate-template-editor-select/name/prompt`、`generate-template-history-load`、`generate-template-history`；`generate-chapter-<index>`；`generate-template-row`、`generate-new-page-type`、`generate-new-page-template`；`generate-chat-messages`、`generate-chat-input`；`generate-quality-pro`、`generate-include-world-synopsis`、`generate-activation-profile`；`generate-chat-context-usage`、`generate-selected-chapters`；`generate-world-scene/threads/characters/entities`；`generate-result`；`generate-pov-chapter/scene/character/instruction`、`generate-pov-result`；`gen-task`、`gen-scope`、`gen-entities(-picker)`、`gen-characters(-picker)`、`gen-chapter`、`gen-scene(-picker)`、`gen-budget(-hint)`、`gen-reveal`、`gen-include-world-synopsis`、`gen-world-synopsis-visibility-hint`、`gen-viewpoint-character(-group,-picker)`、`gen-task-output`（拆分后见 §4.4，拆分须同步测试）；`generate-page-title/type/free-text/sections/assets`。

### data-action / data 钩子

`switch-generate-subtab`（带 `data-subtab`）、`generate-world-suggestion`、`generate-pov-prose`、`run-task`、`preview-task-context`、`render-task-md`、`apply-to-chat`、`select-world-target`、`select-object-template`、`edit-object-templates`、`return-world-bible`、`send-chat-message`、`view-generation-context`、`select-source-chapters`、`open-generated-destination`、`continue-chat`、`generate-another`、`apply-world-page-draft`、`open-writing-from-pov-empty`、`return-world-from-pov-empty`、`select-task-preset`（带 `data-preset`）、`copy-task-md`、`export-task-md`；`data-workspace-rail-key`、`data-state="recovered-page-proposal"`、`data-section="advanced-page-data"`。

### role / 可访问名称

`role="tablist"`（aria-label「生成模式」）、`role="tab"` ×4（aria-selected/aria-controls/roving tabindex/方向键导航）、`role="tabpanel"` ×4；`role="group"` aria-label「生成目标」/「任务预设」；目标/模板/预设按钮 `aria-pressed`；rail summary `aria-label="收起/展开上下文与结果"`。e2e 走 `getByRole("tab")`/`getByLabel`，改任何可访问名称必须全局 grep 同步 `generate.spec.js`（主规范 §9）。

## 8. 验收标准 + 验证命令

验收标准：

1. GenerateView.vue 内联样式块迁出并格式化，`.topbar-generate-note` 单份来源；三处弹窗样式在新位置下视觉无回归（截图对比）。
2. 四个 tab 生成中均有进度或阶段反馈；失败态向 `.error-card` 收敛。
3. header 操作区每 tab ≤1 个 primary；task 次级操作下沉面板。
4. `#gen-task-output` 重复 id 消除（或经核实确认无引用后维持并注释原因）。
5. composer 发送按钮不再随 textarea resize 错位；矮窗口 chatbox 不溢出。
6. 390px 无页面级横向溢出；subtabs 窄屏 wrap 不破。

验证命令（在 `frontend-console/` 下执行）：

```bash
npm run test:e2e -- e2e/generate.spec.js     # 功能契约（tab 导航、聊天、提案、pov、task 编译）
npm run test                                 # vitest 单测（含 editorialTheme/typographyTokens 契约，样式迁移后必跑）
```

generate 页暂无独立视觉快照基线；样式收编完成后建议补建四 tab × 三主题快照（参照 visual-project-rag 模式），纳入 `test:e2e:visual`（执行时核实 config 是否限定 spec 清单）。
