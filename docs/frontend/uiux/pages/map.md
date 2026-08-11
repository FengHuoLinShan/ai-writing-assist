# 地图 UI/UX 执行规范

> 上级标准：`../design-standard.md`（Editorial Archive 唯一权威，下称「主规范」，§x 均指该文件）。
> 范围与边界：本页执行范围**仅限表层样式对齐**（class / 材质 / 间距 / 状态容器 / 文案）。
> **不动 `frontend-console/views/mapView.js`（6326 行 vanilla 引擎）与 `mapEditPanel.js` 的内部
> 架构、渲染逻辑、事件编排与数据流**；允许的最深改动是把交互 `<span>` 换成 `<button>` 一类
> 等价标签替换（不改变渲染结构与 data 钩子）。
> 权威依据：`docs/frontend/uiux/design-standard.md`（下称「主规范」，§ 号均指该文）。
> 证据来源：2026-08 页面级调研 + 源码抽查核实；路径相对 `frontend-console/`。

## 1. 页面定位与目标画像

- **目标画像：画像 A（长期创作的作家）**。地图是「世界长期记忆」的空间视图，对应画像任务
  「以时间、关系、地图直观回顾发生了什么」。画像 B（RP 用户）不进入本页，本页不做阅读向简化。
- **双态心智**：总览态 = 工作台目录（继续上次工作、分流 AI 待处理建议、从正文补充资料）；
  沉浸画布态 = 空间审阅与编辑（视图模式 + 图层 + 动态摘要 rail）。
- **用户会喜欢的理由**（产品假设，未经用户验证）：「继续最近地图」英雄卡缩短上下文恢复成本；
  「地图收件箱」把 AI 建议挡在正史之外，符合「AI 不越权」承诺。
- **主要摩擦（现状）**：首屏假空态闪烁、目录加载失败静默、画布头部拥挤、窄屏 handoff 样式断档。

## 2. 现状问题清单（按严重度排序）

### P0 —— 状态缺失 / 断档

1. **总览目录无加载/错误态**：`reloadCatalog()` 无 loading 标记且无 try/catch
   （`vue/views/map/useMapWorkspace.js:261-273`），模板无对应分支 —— 首屏先闪现
   「为故事创建第一张地图」假空态英雄卡（`MapWorkspaceView.vue:40-42`），目录请求失败
   完全静默（对比：inbox 有 error + 重试，`MapWorkspaceView.vue:65`）。
2. **移动端 handoff 样式断档**：`.map-mobile-edit-handoff` 在 ≤760px 即渲染
   （`views/mapView.js:3658-3662` 判定，`:946-951` 输出），但其边框/内边距/背景只写在
   `@media (max-width: 390px)`（`styles.css:11424-11434`）——391–760px（平板/竖屏）
   得到一条无样式的裸文本。

### P1 —— 层级与可达性

3. **画布态头部过度拥挤**：视图模式组 + 低动效 + 7 个图层开关 + 快速创建/编辑历史全塞在
   一行（`MapWorkspaceView.vue:20-25`），中层宽度下无渐进收纳（grep 未见
   `.map-view-controls` 的换行/折叠样式）。
4. **`.map-filter-bar` 用 `<span>` 做交互过滤器**（`mapView.js:954-957`）：
   `data-action="map-filter"` 无 `role="button"`/`tabindex`，键盘不可达，违反主规范 §8；
   且仅「全部/地点」两项，与头部 7 个图层开关功能重叠。
5. **图层开关两处重复**：头部 `.map-layer-toggle`（`MapWorkspaceView.vue:24`）与
   「地图结构与图层」折叠区（`:70`）渲染同一组开关，视觉权重相同，难辨哪边是「真」控制。
6. **语义气泡基于硬编码视口**：`buildMapLayout({ viewport: { width: 720, height: 360 } })`
   （`MapWorkspaceView.vue:139`）+ inline px 定位（`:76`），不随真实画布尺寸重算，
   非 720px 宽主区时气泡可能与画布对象错位。

### P2 —— 材质与死信息

7. **「空间总览」卡片是死信息**（`MapWorkspaceView.vue:69`）：只重复头部已有的
   「N 张 · N 个」计数（`:7`），无链接无操作，白占一个网格位。
8. **`#map-search-results` 无容器样式**（`MapWorkspaceView.vue:29`）：一排裸按钮直接插在
   alert 与网格之间；grep 确认 `map-search-results` 在 styles.css 无任何规则命中，
   长结果列表会把网格顶下去且无分组标题。
9. **`.map-overview-more` 下拉无 ESC/外点关闭**：`<details>` 实现，
   `styles.css:14303-14329` 只管定位，打开后点其他区域不收起，需再次点 summary。
10. **editorial-theme 轨道顶影漏掉地图**：`.workspace-rail` 的 `inset 0 3px` 墨色顶影只给了
    writing/scene（`editorial-theme.css:1089-1092`），`.map-dynamic-rail` 同为
    `.workspace-rail` 却无此处理，三视图视觉不一致（若属刻意需注释说明，选择器写法像遗漏）。

## 3. 目标布局与信息层级

### 3.1 总览态

- **信息层级**：P1 英雄卡「继续地图工作」（整行，本屏唯一 primary，允许渐变独特构图，
  主规范 §0）→ P2「地图收件箱」（待处理分流，工作台密度不稀释）→ P3 渐进展开区
  （「从正文补充地图资料」「地图结构与图层」默认收起，`<details>` 渐进披露符合画像 A
  「复杂能力渐进展开」）。
- **头部**：页面标题（§3.2 view-header 档）+ mono 计数 + 搜索 + 「管理地图」下拉；
  「空间总览」死卡移除（计数头部已有），e2e 是否断言该卡文案（执行时核实）。
- **首屏顺序**：加载骨架 → 英雄卡 → 收件箱；目录数据未就绪前不渲染任何空态文案。

### 3.2 沉浸画布态

- **信息层级**：P1 画布（`.map-leaflet`，主对象占分栏宽 64–68%，主规范 §4 内容优先契约；
  `.map-dynamic-rail` 不低于 `--workspace-rail-right-min:190px`）→ P2 工具条
  （面包屑 + 编辑/设置）与动态摘要 rail → P3 详情面板 / 编辑面板（随上下文出现）。
- **头部降权顺序**（一行放不下时）：视图模式组 > 主操作（快速创建）> 编辑历史 > 图层开关
  （折叠为「图层」下拉或换行，二选一，保持 `data-action` 与 aria 钩子不变）。
- **编辑态**（`is-map-editing`）：维持现状语义 —— 隐藏语义气泡带与动态摘要 rail
  （`styles.css:11383-11386`），编辑面板限高滚动（`:8218-8228`），仅做材质对齐。

## 4. 逐区域标准（映射主规范 §5 组件条目）

### 4.1 总览

- **卡片网格** → §5.3 Card：paper-raised + `--line-subtle`，无阴影；卡片只给「可独立移动的
  条目」，分区用留白 + 区块标题；禁止 Card 套 Card（`map-progressive-section` 内嵌 section
  仅用 hairline 分隔）。
- **搜索** → §5.10：宽 240–320px、带清空按钮、结果计数紧随；`#map-search-results` 补容器
  规则（间距归 `--space-*` token、分组标题、超长结果限高滚动）。
- **继续最近地图 / 创建第一张地图** → §5.1 Button：本屏唯一 `.btn-primary`（深墨实心，
  朱红只给 focus 环）；触控档高 ≥42px（现状 ≤600px 已 44px，`styles.css:14366-14373`）。
- **管理地图下拉** → §5.1 状态矩阵四态补齐；补 ESC/外点关闭（Vue 壳层指令，不动引擎）。

### 4.2 画布

- **工具条**（引擎 `.map-toolbar` 与 Vue 头部）→ §5.1：全部按钮具备
  hover/active/focus-visible/disabled 四态；`.map-view-mode.is-active` 用 `--bg-active` +
  600 字重表达选中，不用彩色填充块。
- **图层开关** → §5.2 输入控件：触控尺寸达标；两处重复副本二选一保留（建议保留头部、
  折叠区移除副本），受影响测试断言（执行时核实）。
- **`.map-filter-bar`**：`<span>` 改 `<button class="btn btn-text">`（等价标签替换，
  `data-action="map-filter"` 保留）或补 `role="button" tabindex="0"` + 键盘事件
  —— 前者优先；若与图层开关确认重复，可整组 `display:none` 隐藏而不删 DOM。
- **编辑面板**（`.map-edit-panel` / `.map-edit-section`）→ §5.3/§5.2：面板 padding
  `--space-4`，分区用留白 + `--line-subtle`，inline `style="display:none"` 的 section 切换
  属引擎逻辑、不动。
- **动态摘要 rail / 收件箱列表** → §5.4 行密度：`--space-2 --space-3` 紧凑 padding，
  状态用「文字 + 色点」，不用彩色 pill；`is-danger/is-warning` 用左 2–3px 语义色线（§2）。

## 5. 状态覆盖清单

| 状态 | 现状 | 缺口与目标形态 |
|---|---|---|
| 首次进入（无地图） | 英雄卡文案切换「为故事创建第一张地图」+ 引导按钮 ✓（`MapWorkspaceView.vue:40-42`） | 消除假空态闪烁后保留为引导型空态（§5.9） |
| 总览目录加载 | **缺失**（`useMapWorkspace.js:261-273`） | 补 `.loading-skeleton` 骨架（§5.9，reduced-motion 降级） |
| 总览目录失败 | **缺失、静默** | 补 `.error-card`：一句人话 + 重试按钮（§5.9），与 inbox 错误形态一致 |
| 收件箱加载/失败/空 | 均有（`MapWorkspaceView.vue:65`）✓ | 保持 |
| 引擎 Leaflet 加载失败 | `_renderLeafletLoadFailure`（`mapView.js:1230-1253`）`.empty-state` + 重试 ✓ | 保持，材质对齐 §5.9 |
| 动态摘要加载/失败/空 | 均有（`MapWorkspaceView.vue:80`）✓ | 保持 |
| 编辑中（is-map-editing） | 隐藏气泡带与 rail ✓ | 保持 |
| 窄屏只读 | handoff note + 禁编辑 ✓ 但样式断档（P0-2） | 见 §6 |
| enrichment 长任务 | `role="status"` 进度卡（`MapWorkspaceView.vue:55`）✓ | 保持，符合 §7 长任务进度要求 |
| 离开保护 | `viewport.canLeave()` 守卫（`useMapWorkspace.js:374-376`）✓ | 保持 |

## 6. 响应式行为（四档，主规范 §6）

- **Desktop ≥1440 / Laptop 1100–1440**：默认形态；≥1101px 编辑态单列 + 面板限高
  （`styles.css:8218-8228`）保持。
- **Tablet 760–1100**：`.map-container` 纵排、编辑/详情面板全宽（`styles.css:8376-8396`）
  保持；画布头部按 §3.2 降权收纳。
- **Mobile <760**：**既有「只读浏览 + 编辑转交桌面」策略必须保持** —— 编辑按钮替换为
  「请在桌面端编辑」（`mapView.js:890-891`）、编辑面板不渲染（`:904`）、编辑入口早退
  （`:2290,2543,2628,3613`）、handoff note（`:946-951`）均不动。
- **本页唯一响应式修复**：`.map-mobile-edit-handoff` 的样式块从 `@media (max-width: 390px)`
  （`styles.css:11424-11434`）提升到 ≤760px 档，与 `_isCompactViewport()` 判定对齐；
  触控目标 ≥42/44px 不变。
- **断点归并**：本页涉及的 390/560/600 长尾断点按主规范 §6 逐个审查，可归入 760 的归入，
  确需保留的在该行注释理由；页面级横向溢出零容忍（390px）。

## 7. 必须保留的契约

以下全部是测试与引擎的消费钩子，**改名/删除/改结构前必须全局 grep 同步**（主规范 §9）：

- **`data-testid`（全项目产品代码仅 2 处，其一在本页）**：
  `canvas[data-testid="map-canvas"]`（写入 `mapView.js:1187`；消费 `e2e/helpers/selectors.js:104`、
  `e2e/map.spec.js:68,:950`）；另一处 `data-testid="scene-memory-repair"`
  （`vue/views/map/components/SceneMemoryRepairPanel.vue:2`）属本页子组件，同样保留。
- **引擎 `#id`**（mapView.js / mapEditPanel.js）：`#map-leaflet`、`#map-detail-panel`、
  `#map-scene-pick-select`、`#map-marker-*`、`#map-terrain-select`、`#map-overlay-*`、
  `#map-path-*`、`#map-bind-select/center`、`#map-territory-faction/color`、
  `#map-layer-group-*`、`#map-layer-node-*`、`#map-create-*`、`#map-detail-*`、
  `#map-settings-*`（完整清单以 `mapView.js` / `mapEditPanel.js` 源码为准，逐 id 不得在样式对齐中触碰）。
- **Vue 壳 `#id`**：`#map-search-results`、`#map-enrichment-start/end/high-quality`、
  `#map-enrichment-progress`（`MapWorkspaceView.vue:29,49-51,55`）及对话框内
  `#map-quick-name` 等（`map.spec.js:244-315` 消费）。
- **`data-action`**：Vue 壳 `map-overview / map-quick-create / map-create-world /
  map-toggle-archived / map-open-recent / map-enrichment-start / map-visual-history /
  map-clear-lens-focus / map-focus-entity / map-open-dynamic-item`；引擎 shell
  `map-back-list / map-settings / map-enter-edit / map-exit-edit / map-mobile-edit-handoff /
  map-breadcrumb / map-filter / map-detail-*` 等；编辑面板 `map-layer-* / map-editor-layer /
  map-tool-* / map-overlay-* / map-path-* / map-location-lock`（mapEditPanel.js:40-276）。
- **role / 可访问名称**：`role="group" aria-label="地图视图"` + `.map-view-mode[aria-pressed]`；
  `role="note"`（handoff，`mapView.js:947`）；`role="alert"`（引擎加载失败，`:1234`）；
  `summary[aria-label="展开/收起动态摘要"]`；inbox 筛选组 `aria-label="地图收件箱筛选"` 及各
  select aria-label；对话框名称「快速创建地图」「修改地图对象」「分配地图待处理项」「确认操作」
  「恢复归档地图」；quick-create 内「向右移动地点 X」「扩大地点 X 的半径」「锁定地点 X」与
  预览画布 label「地点布局画布」。改动任一可访问名称必须同步 e2e 的 `getByRole/getByLabel`。

## 8. 验收标准 + 验证命令

**验收标准**：

1. §2 中 P0 两项修复，P1 至少完成 3、4 两项；每条修复对应 §5/§6 目标形态。
2. §7 全部契约钩子逐一 grep 确认仍在且消费方不破坏。
3. 390px 无页面级横向溢出；handoff 在 391–760px 有完整样式。
4. 目录加载/失败新状态符合 §5.9 三件套，reduced-motion 下骨架无动画。
5. `make docs-check BASE_REF=origin/main` 通过，本文与主规范无术语冲突。

**验证命令**（`frontend-console/` 下）：

```bash
# 地图功能回归四件套（package.json 已内置同名脚本，覆盖 map.spec.js、
# map-path-mobile.spec.js、map-dynamic-timeline.spec.js、world-dynamics-map-chaos.spec.js）
npm run test:e2e:map

# 单元/契约测试（editorialTheme、typographyTokens、loadingSkeleton 等）
npm test

# 视性能回归（样式改动涉及画布区域时执行；是否必需视改动面，执行时核实）
npm run test:e2e:map-perf
```

**重点守护断言**：`map-path-mobile.spec.js` 三项（390px 只读 handoff 可见、无编辑按钮/面板、
后端 `editor_revision`/tiles/bindings/territories 零变化；quick-create 触控尺寸 ≥40/44px；
势力编辑转交桌面）必须继续全绿 —— 它们就是「只读浏览 + 编辑转交桌面」策略的机器契约。
