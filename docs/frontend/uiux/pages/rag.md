# RAG 查找 UI/UX 执行规范

> 上级标准：`../design-standard.md`（Editorial Archive 唯一权威，下称「主规范」，§x 均指该文件）。本文只做分页落地，不重复定义 token。
> 覆盖 `#workbench/<id>/rag` 的两个路由子页，以及写作/人物与世界页 AI 抽屉内复用的 search：
> search（查找）是默认任务页，不设置内容级 tab；status（修复查找）只从降级修复入口或深链进入，
> 并在修复卡内返回查找。

## 1. 页面定位与目标画像

- **定位**：作者（画像 A）的「作品记忆检索台」——在正文、世界设定、大纲中按语义或字面查找资料，
  并通过证据抽屉核对「这条资料出自哪一章、为什么可信」。证据抽屉是产品信任链的关键一环：
  用户对 AI/检索结果的采纳意愿取决于能否就地溯源。
- **目标画像**：画像 A（长期创作作家）。RP 用户路径（画像 B）不进入本页，本页复杂度不得外溢到 RP。
- **用户任务**：写作中就地核对设定/前史 → 找到资料 → 验证来源 → 跳回正文继续写。
- **喜欢它的理由**：检索方式可理解（智能/字面两档）、命中给出出处片段、索引损坏时明确告知「手写不受影响」并可自助修复。
- **主要摩擦**：高级筛选（视角可见性/章节范围）理解成本高，需渐进展开 + 人话说明；修复页目前是诊断面板堆叠，需分层。

## 2. 现状问题清单（按严重度排序）

| # | 状态 / 严重度 | 问题 | 证据 |
|---|---|---|---|
| 1 | 已处理 | search 顶部单项「查找」subnav 重复一级导航与页面标题，没有提供额外选择 | `frontend-console/vue/views/rag/RagView.vue` |
| 2 | 已处理 | 证据抽屉已补齐 dialog 语义、ESC/遮罩关闭、焦点锁定与回归；共享头部保证 loading/error 形态始终有关闭入口 | `components/RagEvidenceDrawer.vue`；`useModalDialog.js` |
| 3 | 已处理 | 视觉回归分别从 search/status 深链进入，不依赖不存在的常设子标签 | `frontend-console/e2e/visual-project-rag.spec.js` |
| 4 | 已处理 | 抽屉已提升为结果列表的稳定平级节点，并 Teleport 到 body，结果分支切换与全局堆叠上下文不再销毁或遮挡它 | `RagSearchView.vue`、`components/RagEvidenceDrawer.vue` |
| 5 | 已处理 | 修复范围、概览、质量与任务进度已直接可见；页面只保留一个「返回查找」，技术指标、记录、维护工具和片段表渐进收进诊断详情 | `components/RagStatusPanel.vue`、`ragSearchSession.js` |
| 6 | 已处理 | 结果卡已按「条目标题 → 匹配内容 → 来源元信息 → 剧情关联」重排；标题/正文恢复正常字号，匹配度补充「仅用于本次排序」解释，未关联剧情收进 meta 行 | `components/RagResultList.vue`；`styles.css` 的 `.rag-result-*` 规则 |
| 7 | 已处理 | 搜索列表已改为稳定卡片骨架，使用 `role="status"` / `aria-busy`，并沿用全局 reduced-motion 禁用动画规则 | `components/RagResultList.vue`；`styles.css` |
| 8 | 已处理 | 查询卡已重排为主查询、常用条件和「更多条件」三层；待处理世界设定改为带禁用原因的可见说明，视角专用字段只在需要时出现 | `components/RagSearchPanel.vue`；`styles.css` 的 `.rag-search-*` 规则 |
| 9 | 已处理 | 抽屉已收敛为无圆角侧边层，使用共享 surface、border 与 shadow token | `styles.css` 的 `.rag-evidence-*` 规则 |
| 10 | 已处理 | Owner AI 抽屉不再从视口顶部伸到固定导航下方：标题与关闭按钮避开应用顶栏，手机内容停在底栏上方；打开时焦点进入关闭按钮，ESC/显式关闭后回到触发入口 | `OwnerAiDrawer.vue`；`styles.css` 的 `.owner-ai-drawer*` 规则 |
| 11 | 已处理 | AI 抽屉内提交查找不再覆盖 `owner_ai`、当前 owner 模式和写作位置；搜索后抽屉保持打开，刷新恢复同一结果，项目变化时先清空共享 RAG 会话 | `RagSearchView.vue`；`ragSearchSession.js` |

## 3. 目标布局与信息层级

search 子页信息层级（自上而下）：

1. **Primary**：查询输入 + 「查找资料」主按钮（每屏唯一 primary）+ 次级「问世界」。
2. **Secondary**：常驻筛选（查找方式、正文版本），每项就地解释用途。
3. **Tertiary**：「更多条件」折叠区（默认收起，生效时摘要可见）；降级通知条（仅 `statusDegraded`）。
4. **结果区**：计数行 → 结果卡列表（条目标题档标题 + 命中片段 + meta 行）→ 渐进加载。
5. **浮层**：证据抽屉（右浮层，最高层级，见 §4.3）。

status 子页信息层级：

1. **Primary**：修复 hero 卡（状态标题 + 「修复查找功能」主按钮 + 重建范围表单——范围必须提升到主操作旁边，不再埋入折叠区）。
2. **Secondary**：重建进度（WorkflowProgressCard）与概览指标卡（查找资料概览 / 查找质量）。
3. **Tertiary**：诊断详情 details（技术信息、检索记录、低频维护工具、最近片段宽表）。

## 4. 逐区域标准

### 4.1 查询表单（`RagSearchPanel.vue`）

- 卡片保留但使用原生 `<form>` 分层：主行是带可见标签的查询输入、「查找资料」唯一主按钮和次级「问世界」；常驻筛选独占一行；「更多条件」保持 `<details>` 渐进展开。
- 控件遵循主规范 §5.2：label 在上、helper 在下；查找方式、正文版本和待处理范围都用 `aria-describedby` 关联可见说明。章节范围错误保持 `role="alert"` + `aria-invalid`/`aria-describedby`。
- 更多条件分成「从哪里查」和「按谁能看到的内容查」两个 `fieldset`；作者视角只显示视角选择，读者/角色视角才显示截止章、场景等必要字段。
- 「同时查找待处理的世界设定」只有选择世界设定后才可用，并始终显示当前禁用原因或「尚未采用、需要确认」说明，不得只靠 title。
- literal 模式锁定 manuscript 并禁用其他 scope 的逻辑保留，禁用时给出 helper 说明原因。
- 高级筛选有生效条件或章节范围错误时自动展开、修正后不自动收起的现有行为保留。
- 嵌入 Owner AI 抽屉时只复用同一表单和结果，不复制检索实现；回写 URL 时替换 RAG 查询字段，
  但保留 `owner_ai=1`、`owner_ai_mode=evidence` 与当前写作位置，使查找后抽屉不关闭，刷新可恢复。
  组件挂载时必须先按 `projectId` 约束共享会话，项目切换不得显示旧作品的搜索词或结果。

### 4.2 结果列表（`RagResultList.vue`）

- 结果卡层级修正：标题回到条目标题档（`--text-base` 600），命中片段正文档，meta 行 `--text-xs` tertiary；删除把标题压到 xs 的覆层（`styles.css` 的 `.rag-result-*` 规则）。
- 相关度百分比加一句人话解释（如「相关度」label 或 title+可见辅助文案），不裸显数字。
- 分页保持每页 20（`RAG_RESULT_PAGE_SIZE`，`logic/routeState.js:6`）+ `data-action="load-more-results"` 渐进加载 + 底部余量提示 + 服务端上限提示（`.rag-search-limit-note`）。
- 加载态改为 `.loading-skeleton` 骨架屏（主规范 §5.9），reduced-motion 下禁动画。
- 检索错误卡保持 `role="alert"` + 保留条件文案 + 两个重试 action（`retry-search` / `retry-literal-search`），视觉向 `.error-card` 基准收敛。
- 降级警告卡（「本次结果可能不准确」）在空结果与有结果分支都要出现（现有双分支行为保留），文案保持「手写不受影响」的安抚口径。

### 4.3 证据抽屉（`RagEvidenceDrawer.vue`）——信任链关键区域

抽屉是「这条资料为什么可信」的唯一呈现处，可读性标准直接决定用户是否敢采纳检索结果。

- **层级**：通过 Vue `Teleport` 挂到 body 的全视口浮层（z-index 1300），避免顶栏或业务岛的堆叠上下文遮挡；桌面宽 `min(560px, 100vw-48px)`，窄屏全屏（见 §6）。
- **可访问性**：容器使用 `role="dialog"` + `aria-modal="true"` + `aria-labelledby`；ESC、遮罩与显式按钮均可关闭；打开后焦点进入关闭按钮，关闭后还原到触发按钮；背景由共享 `useModalDialog` 设为 inert。
- **四种形态的可读性**：
  - chapter（原文证据）：标题（章节名，条目标题档）→ 元信息行（第 N 章 · 版本，`--text-xs` tertiary）→ before/**mark**/after 正文用 `--font-body` 衬线、`--leading-relaxed`，`<mark>` 用 `--archive-red-soft` 底强调命中词 → 跳转/追踪按钮组。命中词必须在上下文中一眼可辨。
  - object（对象）：只展示摘要、公开信息、隐藏真相、目标、核心冲突、人物所知与别名等作者可读字段，不展示 raw JSON/ID；「追踪原文证据（N）」保留计数。
  - trace（证据链）：每条证据分条展示，来源章号 + 「精确位置/相关片段」作者语言；空证据说明文案保留。
  - error：共享标题与关闭按钮始终可用，错误文案说明关闭后重新打开，不返回底层异常文本。
- **加载态**：「读取中/追踪中」使用 `role="status"` 骨架；关闭时取消在途请求的现有三重校验（abort + generation + projectId）保留。
- **挂载位置**：抽屉组件与结果列表平级，实际 DOM Teleport 到 body；加载/错误/空结果切换不会销毁抽屉。
- **视觉**：全高侧边层，无额外圆角；使用共享 background、border、shadow token 与半透明 blur scrim。

### 4.4 status 修复查找子页（`RagStatusPanel.vue`）

- **入口**：search 不设置内容级 tab；status 仅由 search 的降级通知条「查看并修复」或
  `rag/status` 深链进入，不提升为常设入口。
- **修复范围**：`.rag-rebuild-form` 位于修复 hero 卡内；两端只填一项、非正整数或倒置范围就地显示 `role="alert"`，错误时禁用提交。范围在同一作品的查找/修复路由往返中保留，切换作品时清空。
- **返回**：status 正常形态只保留一个 `nav-search`「返回查找」，历史后退与深链刷新仍有效。
- **诊断分层**：概览、查找质量、状态警告与任务进度直接可见；技术信息、检索记录、重新连接、失败片段重试和最近片段宽表收在「诊断详情」内。维度漂移/预热警告会自动展开，清除警告后不抢回作者的开合选择。
- **重建进度**：`WorkflowProgressCard` + `role="progressbar"` + `retry-task` 保留，活动任务可跨刷新恢复，符合主规范 §7。
- **断网**：显示「暂时无法连接查找服务」，说明正文不受影响，并提供 `retry-rag-status` 与返回查找两个行动。

## 5. 状态覆盖清单

| 状态 | 现有锚点 | 标准 |
|---|---|---|
| 未搜索空态 | 「从作品中找回需要的资料」 | 已补充人物/地点/事件/原文片段的输入引导 |
| 搜索加载 | `.loading-skeleton` + `role="status"` + `aria-busy` | 已处理；reduced-motion 下骨架无动画 |
| 无结果 | 「没有找到匹配资料」 | 已补充缩短关键词建议与「用字面搜索重试」就地操作；降级警告卡仍同显 |
| 校验失败 | 「请完善可见性条件」（:56-58） | 指明哪个字段，焦点移到出错字段 |
| 检索错误 | `.rag-search-error` `role="alert"`（:60-68） | 向 `.error-card` 收敛，双重试按钮保留 |
| 索引降级 | `.rag-search-repair-notice` `role="status"`（RagView.vue:123-126） | 保留；修复页 hero 卡同步状态文案 |
| 重建范围错误 | `#rag-rebuild-range-error` | 就地说明 + 两端 `aria-invalid` + 禁用主操作 |
| 重建进行中 | WorkflowProgressCard + `retry-task` | 进度条直接可见 + 可离开可刷新恢复 |
| 抽屉读取/追踪中 | 「读取中/追踪中」 | 骨架或 dots，ESC 可关 |
| 断网（status） | 「暂时无法连接查找服务」 | 说明正文不受影响 + 重新连接 + 返回查找 |
| 窄屏 375px / 横屏 | e2e 已覆盖 | 全屏抽屉、44px 关闭按钮、页面级零横向溢出 |

## 6. 响应式行为（四档）

断点以主规范 §6 终态为准（760/1100），本页现存 720px 抽屉断点归入 760px。

- **Desktop ≥1440**：search 单列限宽居中；抽屉 560px 右浮层。status 指标卡五格横排。
- **Laptop 1100-1440**：默认形态，同 Desktop。
- **Tablet 760-1100**：常驻筛选 `auto-fit minmax(150px,1fr)` 自适应换行（现状保留）；抽屉宽度不变，注意与内容并存时的可读性。
- **Mobile <760**：主查询单列、两个常用筛选可在空间允许时并排；输入、按钮与折叠摘要触控目标均 ≥44px；Owner AI 抽屉从应用顶栏下方开始并停在 64px 手机主导航上方，关闭与收回控件不低于 44px；证据抽屉使用 `100vw × 100dvh` 全屏并尊重 safe-area；chunk 宽表横向滚动保留；375px 竖屏与横屏零横向溢出。

## 7. 必须保留的契约

### #id

`rag-search-input`、`rag-search-kind`、`rag-search-kind-help`、`rag-content-mode`、`rag-content-mode-help`、`rag-search-scope-label`、`rag-include-pending`、`rag-include-pending-help`、`rag-visibility-mode`、`rag-chapter-from`、`rag-chapter-to`、`rag-cutoff-field`、`rag-cutoff-chapter`、`rag-cutoff-scene-field`、`rag-cutoff-scene-id`、`rag-cutoff-offset-field`、`rag-cutoff-offset`、`rag-character-field`、`rag-character-id`、`rag-chapter-range-error`、`rag-results`、`rag-evidence-drawer`、`rag-diagnostics`、`rag-rebuild-progress`、`rag-rebuild-content-mode`、`rag-rebuild-start`、`rag-rebuild-end`、`rag-rebuild-range-help`、`rag-rebuild-range-error`

### data-action / data-role / data 钩子

`nav-search`（仅 status）、`nav-status`（仅 search 降级通知条）、`do-search`、`retry-search`、`retry-literal-search`、`open-scene-context`、`open-hit`（带 `data-hit-index`）、`load-more-results`、`close-drawer`、`navigate-chapter-ref`、`trace-drawer-ref`（带 `data-ref-index`）、`navigate-scene-ref`、`navigate-object-ref`、`rebuild-index`、`retry-rag-status`、`prewarm-rag`、`retry-embeddings`、`load-retrieval-traces`、`retry-task`（带 `data-task-id`）；`data-role="rag-advanced-filters"` / `data-role="rag-advanced-summary"`；`data-search-scope="manuscript|world|outline"`；`data-rag-advanced-filter`。

### role / 可访问名称

原生 `<form>` 与关联的可见查询标签；`role="status"`（降级通知条、结果加载/空态、抽屉加载）；`#rag-results[aria-busy]`（检索进行中）；`role="alert"`（检索错误卡、章节范围错误、抽屉错误）；`aria-label="检索关键词"`；`aria-label="近期检索记录"`；常用筛选与待处理范围的 `aria-describedby`；章节范围 `aria-invalid`/`aria-describedby`；`role="progressbar"`（WorkflowProgressCard）；抽屉 `role="dialog"` + `aria-modal` + `aria-labelledby`。

## 8. 验收标准 + 验证命令

验收标准：

1. search 首屏无内容级 tab；降级通知条可进入 status，status 修复卡可返回 search，两个深链和浏览器历史均有效。
2. 抽屉具备 dialog 语义、ESC 关闭、焦点还原、遮罩/外部点击关闭，error 形态有关闭按钮。
3. 抽屉在加载/错误/空结果分支切换时不销毁。
4. 修复范围表单与主操作同区可见，范围错误就地反馈；同作品路由往返保留输入，切换作品清空，正常形态只有一个返回入口。
5. 结果卡标题恢复条目标题档；搜索加载为骨架屏。
6. 375px 竖屏与横屏无页面级横向溢出，抽屉关闭按钮不低于 44px。
7. 查询卡只有一个主操作；常用条件有可见说明，更多条件默认收起且分组清楚；作者视角不显示读者/角色专用输入，待处理世界设定在选择范围前不可用并说明原因。
8. Owner AI 抽屉中的查找不会被顶栏/底栏遮挡；提交后抽屉、owner 模式与写作位置仍在 URL 中，刷新恢复结果，关闭不在刷新后自动重开，项目切换清空旧检索会话。

验证命令（在 `frontend-console/` 下执行）：

```bash
npm run test:e2e:functional -- e2e/rag.spec.js      # 功能契约（钩子、分页、375px/横屏响应式）
npm run test:e2e:visual -- e2e/visual-project-rag.spec.js   # 三主题页面快照 + 证据抽屉桌面/手机快照（darwin 限定）
npm run test:e2e:visual:update -- e2e/visual-project-rag.spec.js   # 改版后重建基线，须人工核对 diff
```

改版时以 `e2e/visual-project-rag.spec.js-snapshots/` 下 sticky/night/ink 页面基线、`rag-search-mobile-night` 手机结果基线、`rag-search-filters-mobile-night` 更多条件基线与证据抽屉桌面/手机基线做前后对比锚点；任何快照更新必须在 PR 中附说明。
