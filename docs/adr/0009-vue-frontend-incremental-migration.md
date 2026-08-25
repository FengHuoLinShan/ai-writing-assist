# ADR-0009 — 前端栈迁移：Vue 3 渐进替换 Vanilla JS（island 模式）

- **状态**: Accepted
- **日期**: 2026-07-18
- **背景**: 用户明确要求"前端升级为 Vue 框架"；AGENTS.md「默认栈为 …Vanilla JS。新增…前端栈…须用户确认或 ADR」——用户指令已确认，本 ADR 记录决策与边界。

## 2026-07-19 实施结论

原路线图标记的 Phase 1–6 已全部完成。下文“外壳保持 vanilla”、“本阶段不涉及
keep-alive”与“后续批次”等措辞仅保留 2026-07-18 的决策过程，不再描述当前代码
所有权。当前裁定为：

- Vue shell 拥有 topbar、sidebar、命令栏、主题、快捷键和 toast/modal 的静态 host；
  所有一级业务页面的主 DOM 均由 Vue SFC 拥有。
- 现有 hash router 保留为窄的命令式 route-host seam，继续拥有 URL、兼容别名、项目元数据
  同步和 `#workspace-content` 子树。外壳收口时已评估 Vue Router：当前不引入，以避免
  新增依赖、双路由状态和 URL/wire 迁移；所有实际业务页的主 DOM 仍由 Vue 拥有。
- router 已删除 DocumentFragment keep-alive。所有视图离开时卸载，写作会话以项目隔离的
  显式 snapshot 恢复；详见附录 A。
- Leaflet/Canvas 的 `mapView` 保留为 Vue `MapViewportAdapter` 下的窄 viewport controller；
  toast/modal、hash router、API 和 Proxy state 是集中式基础设施 seam，不拥有业务页主 DOM。
- Writing 只通过 Vue `mapQuickCreateBridge` 调用 `mapQuickCreateView`，并复用
  `sceneAlerts` / `versionDiff` 纯 helper；没有其他 `views/writing/` 运行时依赖。
- 动态用户、AI 与 API 内容继续禁止 `v-html`；命令式 modal 或 Canvas seam 必须集中、可释放，
  且字符串内容显式转义。
- 当前实现不再保留无 store 的 Pinia 预置状态层；状态继续使用组件内
  `ref/reactive` 与既有 bridge，待出现真实共享 store 需求时再评估引入。
- 本次迁移是前端内部所有权调整；HTTP API、数据库 schema 和前端 wire shape 保持不变。

## 背景与问题

`frontend-console/` 原为 53k 行零框架 Vanilla JS（87 个生产文件）：视图是返回 HTML 字符串的
普通对象，经自建 hash router 以 `innerHTML` 注入；`state/api/router/esc/toast` 以
`window` 全局或全局词法绑定存在，ESM 视图直接引用裸全局；36k 行 vitest 单测与
Playwright e2e 深度绑定这套"HTML 字符串 + 全局变量"契约。

整体一次性重写风险高（30 个视图、地图/编辑器等命令式子系统、并行维护两套）。需要一条
**新旧共存、逐视图替换、每步可交付**的渐进路径，且迁移期间不破坏现有 e2e 与视觉契约。

## 原始决策（历史记录）

> 本节保留渐进迁移启动时的分批设计。其中“外壳保持 vanilla”、
> “待外壳 Vue 化”和 DocumentFragment 延后设计均已被上文实施结论取代。

### 1. 引入 Vue 3（SFC + Composition API），以 island 模式渐进替换

- 新增运行时依赖 `vue@^3.5`、`pinia@^4`；开发依赖 `@vitejs/plugin-vue@^6`、
  `@vue/test-utils@^2`（与既有 vite 8 / vitest 4 配套）。
- 外壳（topbar/sidebar/router/命令栏/快捷键）保持 vanilla。每个被迁移的视图通过
  `vue/mountIsland.js` 包装成 vanilla router 的既有视图契约
  （`{onEnter, render, onRendered, onLeave}`），Vue 应用作为"岛屿"挂载进
  `#workspace-content`；`render()` 只返回挂载点 div。
- 数据预取发生在 island 的 `onEnter`（router 会 await），结果作为 props 传给根组件，
  保持 vanilla"先取数后渲染"的首屏节奏。
- 卸载语义：导航离开（`onLeave`）卸载；同视图 `forceRefresh` 不触发 `onLeave`，
  island 在 `onRendered` 前先卸载残留实例再挂载新实例。keep-alive 视图
  （writing/outline）本阶段不涉及，其 DocumentFragment 缓存策略留待对应阶段设计。

### 2. bridge 层收口全局依赖

`vue/bridge/index.js` 是 Vue 组件访问 vanilla 基建的唯一入口
（`getApi/getRouter/getAppState/getToast/getConfirm/useStateKey`），内部读
`window.*` 全局；Vue 组件禁止引用裸全局。单测经 `setBridgeOverrides()` 注入替身，
符合仓库"测试替身通过 DI"的约束。`useStateKey(key)` 把 `appState` 单键桥接为随
`onStateChange` 同步的只读 ref。

### 3. 本阶段不引入 Vue Router；Pinia 仅注册不建模

- 导航仍归现有 hash router（含 `#/llm` 兼容别名），island 是无路由挂载单元；
  待外壳 Vue 化时再评估 Vue Router。
- Pinia 在每个 island `createApp` 时注册，作为后续视图共享状态的统一入口；
  本阶段 settings 表单状态均为组件内 `ref/reactive`，不预建全局 store
  （避免 pass-through seam，同 AGENTS.md deletion test 精神）。

### 4. XSS 约束的映射

Vue 模板 `{{ }}` 自动转义即满足 AGENTS.md 的 `esc()` 纪律。**禁止对动态
用户/AI/API 内容使用 `v-html`**；旧代码中产出 HTML 字符串的渲染器
（如 `llmFormFields.js`）迁移时改写为模板 + `v-model`。CSP 不变：
`@vitejs/plugin-vue` 构建期预编译模板，运行时无编译器、无 `eval`，
`script-src 'self'` 继续成立。

### 5. 视觉与 DOM 契约

- `styles.css` / `editorial-theme.css` 不改；Vue 组件复用现有语义化 class，不写
  scoped style；模板输出的 DOM 结构/class/id 与旧 HTML 字符串逐节点对齐。
- `e2e/visual-settings.spec.js` 在迁移前对 settings 两页 × 三主题建立像素基线
  （提交于 `e2e/visual-settings.spec.js-snapshots/`），迁移后同一 spec 做像素对比，
  动态内容（随机 UUID 列表、toast）mask。基线确定性依赖两条约束：`beforeAll` 显式重置
  后端全局 LLM 默认与作者偏好（其他 E2E 会持久化修改它们），以及平台门禁——基线仅按
  平台提交（当前 darwin），其他平台默认跳过，需显式生成并提交本平台基线后启用。
  后续每批视图迁移沿用同一机制。

### 6. 首阶段范围与后续路线图（历史，已全部完成）

首阶段（本 ADR 随附实现）：迁移 `views/settings/` 全部 1,338 行（全局设置 +
项目设置三个 Tab），`index.html` 移除对应 vanilla 脚本，由 `app.js` import
`vue/settingsIslands.js` 注册。

后续批次（各阶段独立交付，不在本 ADR 展开）：
Phase 2 project/rag → Phase 3 outline/world → Phase 4 generate/writing/scene
（编辑器与命令式子系统接缝）→ Phase 5 map（Leaflet 封装）→ Phase 6 外壳 Vue 化并
评估 Vue Router、移除 vanilla 基建。

## 原始影响（历史记录）

- `frontend-console/package.json` 新增 dependencies；`vite.config.js` /
  `vitest.config.js` 注册 vue 插件；新增 `npm run build`（`vite build`，仅冒烟验证，
  生产构建部署不在本阶段范围）。
- `frontend-console/index.html` CSP 不变；`app.js` 增加一行 island 注册 import。
- `views/settings/`（2 视图 + tabs + shared）与对应旧单测删除；新代码位于
  `frontend-console/vue/`（bridge / mountIsland / composables / views），新单测位于
  `tests/vue/`。
- e2e：`e2e/fixtures.js` 增加 auto fixture 为所有页面注入 `API_HOST`（与
  `helpers/workbench.js` 既有模式一致），支持非默认端口运行；既有 spec 文件未改动。
- AGENTS.md 的前端栈确认门禁保持不变；本 ADR 与用户明确指令构成引入 Vue 的确认记录，
  具体 island/bridge/v-html 约定由本 ADR 和前端模块文档维护。

## 备选方案（拒绝）

### A. 一次性全量重写

**拒绝理由**：53k 行、8 个 2.5k+ 行巨型视图、地图与编辑器等命令式子系统；重写期
新旧两套并行维护，返工风险高，且无法分步验证视觉/行为契约。

### B. Web Components 渐进

**拒绝理由**：同样能做岛屿共存，但生态、模板能力、团队心智与招聘面均弱于 Vue；
且仍需自建响应式与组件模型胶水。

### C. React

**拒绝理由**：能力等价；Vue 的模板 + 自动转义与现有"语义化 class + 表单"形态更贴近，
SFC 迁移成本更低；无其他决定性差异值得引入第二生态。
