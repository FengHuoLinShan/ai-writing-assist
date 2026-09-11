# 前端尺寸/宽度设置审查报告

日期：2026-09-11。范围：`frontend-console/` 全部页面样式（styles.css 17679 行、editorial-theme.css、writing-desk.css、全部 Vue 视图/组件的 `<style>`、内联样式与 JS 尺寸计算；不含 prototypes/dist/tests）。方法：10 个并行只读审查，按统一场景维度判定；关键论断已抽查源码验证。

> **核对记录（2026-09-11 二轮）**：全部 71 条论断已由 7 组并行核对逐条对照源码复核。约六成完全属实；10 条修正或收窄（下文已就地更正）；1 条推翻（四.4 flex-wrap"被覆盖"）、1 条撤销（一.1 表 outline-information-unassigned，实有 ≤760 单列兜底）；2 条比原报告更严重（审校弹窗仅剩 2px 余量、ProjectAssistant 801–900px 段更窄）。行号均已按实测校准。
>
> **独立核对（2026-09-11 三轮）**：再次按当前工作树追踪样式级联、Vue/旧渲染器入口，并用 Chromium 对关键几何做最小复现。主体问题成立，但需覆盖二轮结论的 7 点：审校行在 640px 弹窗内不是“剩 2px”，而是实测产生约 14px 横向溢出；项目空态在 768px 壳层内实测约溢出 32px、约 801px 已恢复；手机横屏的通用 `.generate-chatbox` 已被 ≤900px 规则解除固定高度，只有 owner 抽屉在 >900px 矮窗的高特异度冲突成立；workflow 通知在 761/768/800/900/901/1000/1099/1100/1280px 实测均与工作区中心重合；z-index 顺序本身不能证明穿插 bug；SVG 标签仅是最小字号钳制下的条件风险；版本对比只能统一 Vue 的 `data-side` 为“左/右”，不能反改共享 CSS，因为旧渲染器仍输出“左/右”。以下修复计划以本轮结论为准。
>
> **执行记录（2026-09-11）**：四批行为修复已完成。项目助手在 ≤1100px 改为覆盖面板；宽表格、回收站、RP 菜单和各列表由局部容器承担滚动；中档网格、地图/世界书局部断点、长 token、深层目录、弹窗 `dvh`、底栏安全区、矮窗 owner 聊天区和 RP“回到最新”已按计划落地；缺失类复用现有 toolbar/list 或补最小共享样式；已证明等价的 Settings 重复块、重复审校媒体规则、Auth 几何双源及旧 `.chapter-tree`/MapSourcePicker 死声明已清理。z-index 与 SVG 条件风险未复现确定性故障，不为其新增实现。其余“近似重复”CSS 未机械删除，因声明并非逐条等价，与本次尺寸修复混删无法证明行为不变。
>
> **验证记录（2026-09-11）**：前端 ESLint、184 个 Vitest 文件 / 2485 项断言、生产构建与默认文档门禁通过。Chromium 实际应用在 390×844、768×900、900×800、1024×768、1440×900、844×390 和 1000×500 无页面级横向溢出；390×520 账号弹窗展开后关闭与末项可达，1000×500 回收站弹窗完整落在视口内。构造长内容复现证明 20 项回收站末项可滚达、宽表格仅局部滚动、审校行和长 URL 溢出均为 0、RP 浮标不与输入区重叠。`make docs-check BASE_REF=origin/main` 仍被本任务外已有的 Imports 改动要求复核 `backend/modules/imports/README.md` 和 `docs/modules/13_imports.md`；本次受影响的前端文档已同步，未改写该外部 WIP。

场景代号：A 窄屏溢出 / B 中档(761–1099px)断点缝隙 / C 长内容裁切或撑破 / D 缩放与大字号 / E 移动端 vh·键盘·安全区 / F 小于12px字号 / G 固定 basis 不收缩 / I 弹层尺寸 / J 大 gap 挤压。

---

## 一、系统性问题（跨页面，同一根因）

### 1. 761–1099px 中档断点缝隙（B/G，最大系统性风险）
全局断点主档为 760/1100；而侧栏 224px + `#workspace` 左右 40px 边距把内容区压到约 480–720px 时，桌面布局仍然生效。受影响设置（已核对校准）：

| 位置 | 设置 | 后果 |
|---|---|---|
| styles.css:4344 + OutlineArcsTab.vue:114 | 大纲 7 列表格；行内编辑一格两个 `width:100%` number 输入（.form-input width:100% @1157） | 761–1024px 溢出被 `#main-layout/#workspace` overflow:hidden 硬裁（可滚兜底仅 ≤760 的 display:block，styles.css:7157） |
| styles.css:7686 + 7430 + 7537 + 7633 | 场景详情栏 `minmax(0,68fr) minmax(280px,32fr)`；角色卡 auto-fit 280px；模拟区左列 220px（声明在 7535–7538）；工具菜单 min-width:220px（16606 有 190px 基础覆盖，不改结论） | 761–1000px 开详情栏时列表压到 ~160px，卡片/菜单溢出被裁；scene-* 全部断点在 8834/8845 块内，761–1099 无档 |
| writing-desk.css:2267 + styles.css:6749 | 稿纸 `max-width:800px; padding:32px 40px` + 两栏 `minmax(176px,24fr) minmax(0,76fr)`（声明在 6749，块起 6744） | 761–900px 时主列 ~261px、正文 ~10–17 字/行（18px 字号） |
| styles.css:5236 | `.project-catalog-state` 两列下限 520px | 当前壳层下 768px 视口实测内容区约 488px、横溢约 32px；约 801px 已恢复，主要缺口是 761–800px |
| styles.css:1897 | `.world-card-filters` 4 列下限 ~620px | 761–900px 筛选行溢出；WorldBibleTab.vue:1900 的 ≤760 单列覆写救不到 |
| styles.css:1451–1519 | `.world-object-table__identity` min-width:220px + 操作列 width:1%+nowrap；表格外层无滚动包装（WorldEntityCollection.vue:16） | 761px 起右侧按钮被硬裁，功能不可达（≤760 卡片化兜底在 6901–6925） |
| styles.css:10321 + 12144 + 12033 | `.review-member-row` 三列下限 574px（含 gap）；审校弹窗 `width:min(640px,92vw)`，modal-body 左右 padding 32px×2（styles.css:3909，--space-8） | Chromium 最小复现实测行 `clientWidth=576`、`scrollWidth=590`，约 14px 横向溢出；`overflow-y:auto` 会把横轴计算为 auto，因此表现是弹窗正文横向滚动，不是不可滚的硬裁 |
| styles.css:11452–11457 | `.rag-rebuild-fields` 下限 476px | **核对更正**：有 ≤760 单列兜底（16843），但 761–1099 无中档 → 761–800px 临界溢出仍成立 |
| styles.css:17007 | `.generate-convergence-items label` 第二列 minmax(132px,180px)；≤900 单列兜底 17160 | **核对收窄**：组件位于 WorldWorkspace 78fr 主列，901–1100px 文本列实为 ~200–420px，是"挤压"而非"不可用"；机制（第二列固定吃宽）属实 |
| styles.css:17477 | `.author-preferences-form .form-row` 固定 3 列且无 gap；≤760 单列在 17520 | 761–900px 每列 ~150–170px 且零间距，下拉截断、复选文案竖排 |
| ProjectAssistant.vue:105 | `flex:0 0 min(25rem,36vw)` 永不收缩；JS matchMedia 800（:99）；≤800 转全屏（:126） | 801–1099px 打开助手时主区内容仅 **~210–400px**（801px 处最窄，比原估更严重） |
| MapWorkspaceView.vue:975 | `.atlas-run` 三列 `minmax(220px,1fr) minmax(160px,2fr) auto` + 按钮组 981 行 ≤760 才加 wrap（≤900 已单列） | **核对收窄**：溢出仅在 ~901–930px 一带（~25px 轻微），950 以上放得下 |
| WorldBibleTab.vue:1881 | `.world-library-browse` 固定 232px 目录列，本地断点 960（1886–1888） | 961–1099px 主列 ~450px，布局失衡 |
| MapStructureEditor.vue:993 | 检查器 `minmax(240px,320px)`，≤900 单列 | 901px 视口画布列 ~265px（且 .map-canvas min-width:320px @998 会反向溢出），1000px 处 ~400px |

正面样板（核对补充）：`.world-bible-layout` 在 styles.css:13245–13253 有真正的 761–1100 中档兜底（同 6749 写法），是少数中档无缝隙的布局，修复其他条目时可参照。

### 2. 移动端 vh / 键盘 / 安全区（E）
- styles.css:6927–6950（#sidebar fixed 底栏 height:64px @6933）+ 16475（.sidebar-mobile-nav 64px）：均无 `env(safe-area-inset-bottom)` → iPhone 全面屏 Home 条遮挡按钮。全文件 safe-area 仅 9 处，均与 sidebar 无关。
- modal 体系：`#modal-content` max-height:80vh（styles.css:3801）；92vh 仅 `--full`（3817）与 scene-fusion 特化（8530）；审校弹窗 100vh 在 12260（12258 是 width 行）；≤390 分支 100vh/100vw 在 12297/12299；大纲生成弹窗 90vh（16633）→ 移动端地址栏/键盘遮底部按钮。**核对更正**：并非全无 dvh——ai-ref-modal ≤640 已用 100dvh（4201–4202），rp-more-menu 移动端已有 `min(70dvh,540px)`+safe-area 范式（16037–16040），仓内有正确范式可对照。
- ~~styles.css:16926 的通用 `.generate-chatbox` 会在手机横屏保留 `100vh/min-height:480px`~~ **三轮推翻**：17158 的 ≤900px 规则后置且同特异度，已把通用 chatbox 改为 `height:auto;min-height:0;overflow:visible`；手机横屏不受该固定高度影响。真正问题仅是下一条 owner 抽屉的高特异度覆盖。
- styles.css:16927 vs 17178：owner-ai 抽屉内 `.owner-ai-drawer .generate-chatbox`（0-2-0）的 `min-height:420px` 与 `height:calc(100dvh-330px)` 均压过兜底 `.generate-chatbox{height:auto;min-height:0}`（0-1-0）→ 矮宽窗口（>900px 宽、≤660px 高）聊天区撑破。
- writing-desk.css:2301–2306：移动 AI 工具菜单 `bottom:calc(76px + env(safe-area-inset-bottom)); max-height:65dvh`；对照 editorial-theme.css:1247 `#workspace-content` 底部预留 `88px + safe-area`。两数定位对象不同（前者让位写作页底部工具条、后者为 64px 底部导航），但数值确实未统一。
- AuthGate.vue:134：`.auth-page{min-height:100vh}` —— 经全仓 grep 核实为唯一无 dvh 兜底的全屏 100vh 布局（`#app` 在 460–461 有 vh→dvh 双声明；其余 100vh 均为 max-height 用途）。
- 互动页：`.rp-story-page` height:100% 在 14985、overflow:hidden 在 14987；输入坞与浮标无 visualViewport 适配（visualViewport 全仓仅 RpAdaptiveConfirmPopover、adaptivePopoverPlacement.js、ActionMenu.vue 三处使用）。immersive 模式（ShellApp.vue:11/75，无侧栏）下：`#workspace padding-bottom:72px`（6949）残留且其服务的底栏并不渲染；同时 14219–14224 `#workspace-content{padding:0}` 把 editorial 1247 的 88px+safe-area 一并清掉——两个 padding 的残留方向与直觉相反，修复时一并处理（参照 writing-desk.css:1988–1991 focus 模式的 `padding-bottom:0` 写法）。
- styles.css:9017–9026：`.scene-workbench-drawer` ≤760 `inset:64px 0 0 0` 硬编码，与 `--topbar-height:64px`（styles.css:59）双源。
- WorldQuickOpen.vue:207：列表 `max-height:46vh`，移动端软键盘弹出时下半被遮。

### 3. 溢出被 `#main-layout{overflow:hidden}`（styles.css:654；`#workspace:770` 同）硬裁——不可见且不可滚
- WorldAliasesTab.vue:58（9 列表）/ WorldRelationsTab.vue:56（8 列表）：761–950px 右侧列被裁；styles.css:17679 `td[data-label]{min-width:8em; overflow-wrap:normal}` 显式禁折行加剧；两表外层无任何 overflow-x 包装，≤760 卡片化保护在 17625–17627。
- styles.css:15040–15051：`.rp-more-menu>div` 桌面 width:180px 无 max-height/overflow；菜单 11 个操作项 + 主题区 3 项 ≈15 行，估高 ~550–620px，视口高 <~650px 或 150% 缩放时底部（归档等）不可达。**核对补充**：桌面矮视口（17177 的矮窗查询只管 generate 聊天区）同样无保护；≤760 已转 bottom-sheet（16026 起，max-height 16037–16038，overflow 16041）。
- styles.css:8886（≤760 `.scene-workbench` overflow-x:hidden）+ 1035（`.btn` nowrap）：操作列"查看「场景名」"按钮（SceneWorkbenchView.vue:156/158）长场景名手机被裁。
- 上述 ProjectAssistant / atlas-run 打开时同理。

### 4. 小于 12px 固定字号群（F，中文浏览器最小字号 ~12px 会强制放大）
- 项目页最集中（实测）：5171/5513/5574/5605/5608/5617/5704 等 9px + nowrap（5334/5605/5608）、5676–5679 `.project-stats dt` **8px**+nowrap、5287 10px；另有 5199/5359/5690 nowrap。
- 其余：styles.css:593 `.save-state` 8px；2679 `.chapter-row__meta` 10px；3478/3509 驾驶舱 11/10px；**3599** `.person-status/.place-desc` 11px（3589 是 person-name，原行号有误）；7308–7311 `.scene-runtime-tab small` 10px；12365 `.world-hot-type` 11px（**12907 有一份重复定义，改一处另一处仍生效**）；15574 `.rp-locator-rail > span` 9px+nowrap（34px 轨道为桌面值 @15513，窄屏已覆盖 44px @16092）；16489 `.sidebar-mobile-nav button` 10px × 5 列（@16473）；editorial-theme.css:598 label 11px、780 表头 10px、375 tab 固定 `12px/1.2` 行高。
- 关联：styles.css:10120 `.world-extract-panel__input` width:50px，3 位数被裁；writing-desk.css:1196–1197 版本选择器 `min-width:104px; max-width:132px`（11px 字号来自基础规则 1168–1170，select 无省略）→ 版本文字显示不全；1386–1394 冲突紧凑条 `flex:0 1 180px; min-width:128px; max-width:210px; overflow:hidden` + 子级 nowrap → 摘要全省略号。

---

## 二、重点问题清单（12 条；其中 10 条确认、2 条降级）

1. **版本对比整行级高亮永不渲染**：VersionHistoryDialog.vue:68/74 渲染 `data-side="版本 A"/"版本 B"`，而 styles.css:2969、2989–2992（及移动端 14057/14071）全部匹配 `"左"/"右"` → 单元格行背景（delete/insert/move）与 B 列左边框永不渲染。**核对收窄**：字符级 `<mark>` 增删高亮（styles.css:3001–3016）不依赖 data-side，仍然生效。
2. **`.collapsible-body max-height:2000px`**（styles.css:4871/4877）：全仓（含全部 .vue style 块）无任何覆写兜底；影响面 7 处：WorkflowProgressCard、OutlineGenerateProgressCard、OutlineAnalysisProgressCard、PlotAutoExtractProgressCard、SceneAutoExtractProgressCard、SceneWorkbenchView(:28)、WritingWorkflowBars，展开内容 >2000px 即被静默裁切。
3. **回收站桌面端无滚动**（styles.css:13646–13659）：`#modal-content:has(.recycle-bin)` max-height:92vh + overflow:hidden，且 13657 的 `#modal-body overflow:hidden` **覆盖了 3867 基础的 overflow-y:auto**；`.recycle-bin__list` 仅 min-height:0 无 overflow；分页 PAGE_SIZE=20（recycleBin.js:18）双列 10 行，长名换行增高后桌面必裁。≤760 兜底在 13721–13725。
4. **`.smart-dedup-layout` min-height:520px 与 max-height:min(72vh,760px) 冲突**（styles.css:13786–13792）：视口高 <~722px（宽 >760px）时 min 胜出。**核对修正症状**：容器自身无 overflow，父级 modal 可滚 → 实际表现为"模态整体超长需滚动、底部推出可视区"，且连带 `.smart-dedup-queue` 的内部 `overflow-y:auto` 失效（grid 行高不受容器高度约束）；≤760 兜底 max-height:none 在 14006–14010。
5. **generate 聊天气泡断行缺失**（styles.css:16962 仅 pre-wrap，无 overflow-wrap）：**核对修正症状**：长 URL 溢出气泡边框后，终点是消息滚动容器 `.generate-chat-messages`（~16949）的横向滚动条，并非被 16929–16930 的 hidden 裁掉（该两层在滚动容器外侧）——移动端长消息需横向拖动才可读，体验破损成立。
6. **今日页任务标题溢出**（TodayView.vue:540 strong 无 overflow-wrap；对照 16394 attention-row 有 anywhere）：中列 minmax(0,1fr) 可换行，触发条件限于长不可断串（URL/长英文），中文标题不受影响。
7. **主题选择弹窗深层撑破**（WorldTopicPickerDialog.vue:41 每层缩进 +18px，样式区 button flex 无 min-width:0）：depth≥6 → 缩进 ≥116px，长名溢出按钮框并触发模态内横向滚动。
8. **账号对话框无高度上限**（AccountDialog.vue:172–173）：overlay fixed grid place-items:center padding:20px 无 overflow（z-index:1200），dialog `width:min(100%,440px)` 无 max-height → 矮视口展开删除账号表单时上下溢出且不可滚。
9. **"回到最新"浮标压输入区**（styles.css:15495–15506 桌面 bottom:142px z-22；16114–16117 移动端 bottom:158px）：textarea 15px/1.65 字号下 max-height 精确 214px（15462–15466，与 InteractionView.vue:292–306 JS 一致），输入约 3 行后 dock 总高超过浮标 bottom，z-22 > dock z-18 → 压住输入区与工具行。
10. **z-index 交互待实测，不能按确定性 bug 处理**：theme-preview/workspace-drawer overlay z-1100（editorial-theme.css:1214）< AccountDialog z-1200 < modal 遮罩 z-1300（styles.css:3774，另 11690 一处）< toast 2000（4250）。嵌套 modal 高于发起它的抽屉通常是正确行为；只有证明存在两个可同时操作的浮层、焦点逃逸或错误遮罩归属时才调整。
11. **项目名徽标省略号失效**（styles.css:6055–6065）：`display:inline-flex` + ellipsis 在同一元素、文本为直接文本节点（无子 span 承载）→ text-overflow 对 flex 容器无效，长项目名硬切无 "…"（WorldView.vue:17、OutlineHeader.vue:20–24、GenerateView.vue:10 三处使用）。
12. **SVG 标签字号与避让不一致（条件风险，移出确定性 bug）**（MapStructureEditor.vue:98 fontSize=`14*mapUnit`px vs :344 按字数×14×unit 估宽）：仅当浏览器钳制最小字号时，unit<0.86 段避让框可能偏小；页面缩放不触发。字符数估宽对全角/半角混排也只有近似精度，应先在目标浏览器复现再决定是否改为 SVG 实测宽度。

---

## 三、模板引用了不存在的 CSS 类（6 组，全部核实）

| 类 | 引用位置 | 表现 |
|---|---|---|
| `.form-grid.form-grid--2` | StoryOutlineEditorFields.vue:15,55,73,89；**核对补充：outlineAiOps.js:317 同样使用；且基类 `.form-grid` 也无定义** | 连 grid 容器都不是，子元素按普通块级堆叠 |
| `.writing-form-hint` | OutlineThreadsTab.vue:150,153,182,185,**202**；**核对补充泄漏面：outlineAiOps.js:109,120,327、场景工作台（useSceneWorkbench.js:519、sceneModalController.js:320）、world island（WorldObjectsTab.vue:12、worldEntityOps.js:1237）同样加载不到** | 类只定义在 writing-desk.css:1553，唯一引入点是 WritingView.vue:336（writing island chunk）；styles.css:9908 的组合选择器只覆盖 margin 不提供基础样式 → 直进大纲/场景/world 路由提示样式永久丢失 |
| `.rp-public-research` | InteractionView.vue:2314 | 原生 details 默认三角 + 无宽度约束说明块撑破工具行 |
| `.story-structure-import` / `.structure-choice` | OutlineStoryEditorPage.vue:42,47 | 裸 details 外观，且丢失 modal 版复选列表的滚动约束（对照 `.story-outline-generate .checkbox-list` max-height:180px 在 styles.css:16628） |
| `.outline-assignment-bulk` | OutlineThreadsTab.vue:191 | 批量归类工具条竖排堆叠 |
| `.worldbook-import-ignored` | WorldbookImportPanel.vue:35 | 忽略列表无 max-height（兄弟类 `.worldbook-import-items` 有 min(42vh,28rem) 约束 @12757），大目录导入页面被无限拉长 |

---

## 四、双源定义 / 死代码 / 级联陷阱（9 条，已核对）

- `.auth-card` 双源同特异性（editorial-theme.css:1175 `.auth-card.auth-card` (0,2,0) padding:40px/radius 12px vs AuthGate.vue:135 scoped (0,2,0) padding:36px/radius 18px）：当前入口中 `styles.css`、`editorial-theme.css` 为固定 link 顺序，组件 scoped 样式由 Vite 后注入，胜者稳定为 36/18px；这是所有权重复和维护债，不是“不同构建随机漂移”的现行 bug。
- editorial-theme.css `.view-header` `!important` 级联：L312（顶层）、L966（≤760）、L1119（顶层无条件 `0 0 20px`）、L1248（≤760 bottom:16px）。**核对补充：不止 L966 死——L312 的 padding 与 margin-bottom 同被更晚的 L1119 压死，第一代整块 padding/margin 全死**（仅未被 L1119 声明的属性存活）。
- editorial-theme.css 输入框压制：L1282–1284 选择器 `input:not([type=checkbox])...` 实测特异度 (0,4,1)，压制 styles.css:1157 `.form-input` 的 background/border/padding；**核对补充：L1128–1129 还有第二条同特异度规则**（border-radius、min-height:var(--control-height)）。控件高度三档：38px（L404，已被 L1122 的 var(--control-height) 压死）→ 40px（--control-height @1092）→ `.btn-primary` 44px（@1285），同排按钮差 4px。
- styles.css 重复定义（抽样坐实）：Settings 块 9366–9825 ≈ 10435–10806（如 `.account-provider-card` 9719/10700）；world/review 块 9828–10433 ≈ 11830+（`.review-search-bar` 10175/11998 等）；`.review-member-row` ≤760 媒体 12265–12278 与 12690–12703 逐字相同；world-batch/bible 两段 36 个相同选择器（12332/12881、12490/13156 等）。
- ~~12719 flex-wrap 被 13269 覆盖~~ **核对推翻**：后份未声明 flex-wrap，CSS 按属性级联，wrap 仍生效——真实问题是整段重复定义 + 后份遗漏该属性的维护隐患，非现行 bug。
- writing-desk.css 两代规则：第一代 padding:30px 59px 34px（L176）、min-height:58vh（L191）被第二代 L2267–2268（32px 40px、52dvh）同特异度后置覆盖；≤760 折叠手柄 L877–886（width:100%，(0,3,0)）被 L2319 `.chapter-tree-shell.is-collapsed …`（同 (0,3,0) 更晚）反杀成 44px 方块（WritingView.vue:94–104 证实两祖先类同时成立）。
- MapSourcePicker.vue:131 `.map-source-overlay>.map-source-picker`（编译后 (0,3,0)）width:min(680px,100vw) vs L133 `.map-source-picker`（(0,2,0)）width:min(44rem,…) —— 后者为死代码。
- 死代码两处无害：editorial-theme.css:1144 `.settings-shell max-width:1080`（styles.css:17273 width:min(100%,1040) 更严）；L1160 `.entry-choice gap:48px + justify-content`（容器无任何 display 声明，默认 block，gap/jc 均无效）。
- 断点不一致：styles.css:17662 用 max-width:**768px**（全局规范 760），WorldHealthPanel.vue:890 用 ≤760 强制单列 → 761–768 共 8px 窗口出两列缝隙。
- styles.css:5012–5018 `.chapter-tree{width:200px}`：全仓模板/JS 零引用，确认为旧版残留死代码。

---

## 五、受保护的理论风险（保护来源已逐一核实）

- 写作台三栏（styles.css:2519–2536 顶层规则，无自身媒体查询）兜底共**四处**：6744 块（6749 双列）、6795 块（6804–6810 单列）、7063–7065（≤760）、**writing-desk.css:2284（组件级 display:block）**——结构性耦合，任一被调即退化。
- `.llm-template-list`(2251)/`.deep-import-group .form-row`(2349)/`.llm-preset-list`(2354)：三选择器全文件各仅一处、无媒体查询 → <500px 视口 560px 弹窗内溢出。
- `.scene-simulation-content`(7535–7537) 单列兜底确在 ≤760（8871–8873，挂 8845 块）而非 900；WorldWorkspace rail：收起态 min-height:132px+vertical-rl（2492–2505 顶层），横排恢复在 6820–6832（≤760 块），17152 `grid-column:1/-1`（≤900 块）；WorldWorkspace.vue:456 `railOpen = !matchMedia("(max-width:900px)").matches` → 761–900px 默认收起 + 全宽竖排标题条成立（有 sessionStorage 存储值时除外）。
- WorldResult.vue:163 dd 三列 `minmax(0,1fr) auto minmax(0,1fr)`；164 行 @media 600 只降 dl，dd 未降级 → 窄屏长英文值互相溢出。
- adaptivePopoverPlacement.js:93–94 `height=Math.min(popover.height, availableHeight)`，118 行 maxHeight 可为 0，全文件无下限（对照 ActionMenu.vue:82 有 `Math.max(44,…)` 下限，未混淆）。
- `.scene-detail-grid`（8336–8338 顶层）≤375 仍两列；8834 的 ≤560 块只作用 impact dl；16955 `min-height:0` + 16998 `flex:0 1 48vh` + 17159 ≤900 解除——高缩放下消息区可被压没。
- `#modal-body` padding:0 var(--space-8)（3867–3868，--space-8:32px @45）：通用 modal 无小屏 padding 特化；:has 特化共 5 处——4207（ai-ref，≤640）、12304（review-decision，≤390）、13655（recycle-bin）、16634 与 16821（story-outline-generate）。
- ~~workflow 通知按 `--sidebar-width` 推导会右偏~~ **三轮推翻**：该公式是在视口中心上补偿实际侧栏/上下文栏占位；Chromium 在 761、768、800、900、901、1000、1099、1100、1280px 逐点测量，通知中心与 `#workspace` 中心差均为 0。现有 `writing.spec.js` 也已有同类几何断言，不应修改。
- ≤760 `.world-review-workbench .bulk-toolbar__actions` repeat(3,minmax(0,1fr)) 在 **17637**（17634 是 overview__cards）+ `.btn` nowrap 在 **1035** → 375px 每格 ~105–110px，按钮文字溢出重叠。
- `.settings-account-model-notice`（9772–9783，**10753 有一份重复定义**，各自 ≤640 纵向兜底在 9821/10802）：文本无 overflow-wrap → 长无空格模型名挤按钮。
- 其余核实无误：6243 导入列表 80/120px 固定列兜底 6284（≤760）；6465 workflow nowrap 兜底 6784（≤900）；11698 证据抽屉 `width:min(560px,calc(100vw-48px)); height:100dvh` + ≤760 全屏（11808）+ safe-area-top（11820）——正面样板。

---

## 六、分批修复计划（按三轮核对结论更新）

### 第一批：确定性且可小改闭环

1. **版本对比**：只把 `VersionHistoryDialog.vue:68/74` 的 `data-side` 改为“左/右”；可见列名继续显示“版本 A/B”。共享 CSS 和仍在单测使用的 `renderVersionDiff()` 保持不动。给 Vue 对话框契约测试补 data-side 与行级背景断言。
2. **回收站**：给 `.recycle-bin__list` 增加 `flex:1; overflow-y:auto`，让工具栏与分页固定、仅列表滚动；用 20 个超长项目名在 1000×500 和 1000×700 验证最后一项与分页可达。
3. **长 token**：给 `.generate-chat-bubble`、`.today-author-task-row strong`、`.settings-account-model-notice` 的文本承载项补 `min-width:0;overflow-wrap:anywhere`；不对普通中文正文使用 `word-break:break-all`。
4. **账号弹窗**：`.account-dialog` 使用 `max-height:calc(100dvh - 40px);overflow-y:auto`，保留 overlay 的 20px 安全边距；验收 390×520 展开删除账号表单、键盘焦点与关闭按钮可达。
5. **内容高度冲突**：`.smart-dedup-layout` 去掉 520px 硬下限，改用可收缩的明确高度，保留左右队列内部滚动；`.collapsible.open .collapsible-body` 直接解除 max-height 上限，接受取消高度动画，不引入额外包装或 JS 测高。

### 第二批：修滚动归属与中档布局

1. **项目助手**：把现有抽屉/对话框模式的 CSS 与 `matchMedia` 阈值从 800 提到 1100；复用现成窄屏焦点约束，不再让固定 25rem 助手与 224px 侧栏同时挤压主区。
2. **宽表格**：不要删除 `#main-layout/#workspace` 的 `overflow:hidden`。在 761–1100 档让 `.data-table.table-card-list` 自身成为横向滚动区；≤760 继续卡片化，桌面继续表格。优先覆盖 outline arcs、world objects、aliases、relations，并验证最后一列按钮可通过触控、触控板和键盘聚焦到达。
3. **固定下限网格**：复用已有 `@media (min-width:761px) and (max-width:1099px)`，按组件改为可读的两列或单列：review-member-row、project-catalog-state、world-card-filters、rag-rebuild-fields、author-preferences-form。scene 工作台已有 container query 范式，受助手/详情栏影响的 scene 与 map 组件优先按容器宽度降级，避免继续猜视口宽度。
4. **局部断点**：MapStructureEditor、WorldBible 目录和 atlas-run 只把现有 900/960 阈值校准到实际最小内容宽度；不新增第三套全局断点。

### 第三批：移动视口与浮层

1. 给固定底栏的高度、`.sidebar-mobile-nav`、`#workspace` 底部预留、owner 抽屉底边和移动 sheet 偏移统一补 `env(safe-area-inset-bottom)`；immersive 外壳显式清除不存在底栏时的 `#workspace` padding。
2. 通用 modal 保留 vh 回退并增加 dvh 覆盖；输入型弹窗验证软键盘后正文和 footer 仍可滚达。scene drawer 的 `64px` 改用已有 `--topbar-height`。
3. owner 抽屉的固定 chatbox 规则增加 `min-height:661px` 条件，使 >900px 矮窗落回现有矮窗兜底；不改已正确工作的手机横屏通用规则。
4. `.rp-more-menu>div` 桌面补 `max-height:min(...,calc(100dvh - ...));overflow-y:auto`。`rp-new-content` 改为覆盖在故事滚动行底部的 grid item，而不是用固定 `bottom:142/158px` 猜输入坞高度。

### 第四批：缺失样式、字号与清理

1. `.form-grid/.form-grid--2` 补一个共享 grid 定义和 ≤760 单列；`.writing-form-hint` 在 `styles.css` 补基础说明文字样式，写作岛保留其增强外观。
2. 能复用现成类时不新增 CSS：`.outline-assignment-bulk` 同时使用 `.bulk-toolbar`；`.worldbook-import-ignored` 同时使用 `.worldbook-import-items`。`rp-public-research`、story structure import/choice 仅补各自最小布局与滚动约束。
3. 小于 12px 的说明文字按组件逐组升到 `--text-xs`，同时调整对应 nowrap/固定轨道；不要一次全局替换后让徽标、底栏和统计再次溢出。
4. 重复块、死声明、`.auth-card` 双源和旧 `.chapter-tree` 放在行为修复之后单独删除，并用视觉快照证明等价；不与响应式修复混成一次难审查的 CSS 大改。

### 验收矩阵

- 视口：390×844、768×900、900×800、1024×768、1440×900；另测 844×390 横屏、1000×500 矮窗和浏览器 150%/200% 缩放。
- 内容：20 项长名称、无空格 URL/英文串、8 层目录、展开式账号表单、最大高度 RP 输入、助手打开/关闭、表格最后一列操作。
- 断言：页面级无横向溢出；允许的局部滚动区可见且末项可达；焦点不被遮挡；弹窗 footer、底栏与安全区不重叠；草稿与页面状态不因布局切换重建。
- 自动化：复用 `e2e/helpers/responsive.js` 和现有 writing/assistant/interaction/world/outline/project/smart-dedup 场景，只补能复现本批缺陷的断言；完成后运行前端 lint、Vitest、生产构建、相关功能与视觉 Playwright、`make docs-check BASE_REF=origin/main` 和 `git diff --check`。
