# RAG 查找 UI/UX 执行规范

> 上级标准：`../design-standard.md`（Editorial Archive 唯一权威，下称「主规范」，§x 均指该文件）。本文只做分页落地，不重复定义 token。
> 覆盖 `#workbench/<id>/rag` 的两个子页：search（查找）与 status（索引修复）。

## 1. 页面定位与目标画像

- **定位**：作者（画像 A）的「作品记忆检索台」——在正文、世界设定、大纲中按语义或字面查找资料，
  并通过证据抽屉核对「这条资料出自哪一章、为什么可信」。证据抽屉是产品信任链的关键一环：
  用户对 AI/检索结果的采纳意愿取决于能否就地溯源。
- **目标画像**：画像 A（长期创作作家）。RP 用户路径（画像 B）不进入本页，本页复杂度不得外溢到 RP。
- **用户任务**：写作中就地核对设定/前史 → 找到资料 → 验证来源 → 跳回正文继续写。
- **喜欢它的理由**：检索方式可理解（智能/字面两档）、命中给出出处片段、索引损坏时明确告知「手写不受影响」并可自助修复。
- **主要摩擦**：高级筛选（视角可见性/章节范围）理解成本高，需渐进展开 + 人话说明；修复页目前是诊断面板堆叠，需分层。

## 2. 现状问题清单（按严重度排序）

| # | 严重度 | 问题 | 证据 |
|---|---|---|---|
| 1 | 高 | status（索引修复）子页无常设入口：subnav 只有「查找/返回查找」一个按钮，非降级时只能从降级通知条或直达 URL 进入 | `frontend-console/vue/views/rag/RagView.vue:118-120`、`:123-126` |
| 2 | 高 | 证据抽屉可访问性缺失：无 `role="dialog"`/aria-modal、无 ESC 关闭、无焦点管理、无遮罩；error 形态连关闭按钮都没有 | `components/RagEvidenceDrawer.vue:32`、`:77-79`；`styles.css:9962-9975` |
| 3 | 高 | 视觉回归测试钩子失效：`visual-project-rag.spec.js:77` 断言 `[data-action="nav-status"]` 带 active class，现行模板中该按钮只在 search 子页渲染且无 active 类，匹配 0 个元素 | `frontend-console/e2e/visual-project-rag.spec.js:77` 对照 `RagView.vue:119-125` |
| 4 | 中 | 抽屉挂载位置脆弱：drawer 经 slot 注入结果列表「有结果」分支内，加载/错误/空结果分支中抽屉 DOM 不存在；打开抽屉时触发重搜索会导致内容突变 | `components/RagResultList.vue:129`（slot 注入处）、`RagSearchView.vue:148-159` |
| 5 | 中 | status 页信息埋藏过深：重建范围表单（`#rag-rebuild-content-mode/start/end`）藏在「诊断详情」details 底部，主操作「修复查找功能」在 details 外，点修复时使用哪个范围不可见；「返回查找」按钮重复出现两次 | `components/RagStatusPanel.vue:281-294`、`:125-126`、`:293` |
| 6 | 中 | 结果卡信息层级扁平：rag 覆层把卡片标题压到 `text-xs`，标题/计数/正文/元信息同档，仅靠「命中依据」小标签分区；相关度「xx%」无含义解释 | `styles.css:9791-9797`；`components/RagResultList.vue:90,114` |
| 7 | 中 | 加载态粗糙：「搜索中/读取中/追踪中」均为纯文本 `.loading`，无骨架、无进度指示，违反主规范 §5.9 Loading 归一 | `components/RagResultList.vue:54`；`components/RagEvidenceDrawer.vue:33` |
| 8 | 低 | 查询表单层级拥挤：两个常驻下拉 + 说明行 + details 高级筛选 + 范围 checkbox 全挤一张卡；「包含待处理世界对象」只有 title 提示，说明不可见 | `components/RagSearchPanel.vue:70-141`、`:137` |
| 9 | 低 | 抽屉圆角 14px + 深阴影与 Editorial Archive 低圆角体系（2-4px，浮层 lg=4px）不一致 | `styles.css:9962-9975`（约 :9972）对照主规范 §1.4 |
| 10 | 低 | subnav 单按钮恒为 `active` + `aria-current="page"`，在 status 页上语义失真（「返回查找」被声明为当前页） | `RagView.vue:119` |

## 3. 目标布局与信息层级

search 子页信息层级（自上而下）：

1. **Primary**：查询输入 + 查找主按钮（每屏唯一 primary）。
2. **Secondary**：常驻筛选（检索方式、正文版本）+ 一行方式说明。
3. **Tertiary**：高级筛选折叠区（默认收起，生效时摘要可见）；降级通知条（仅 `statusDegraded`）。
4. **结果区**：计数行 → 结果卡列表（条目标题档标题 + 命中片段 + meta 行）→ 渐进加载。
5. **浮层**：证据抽屉（右浮层，最高层级，见 §4.3）。

status 子页信息层级：

1. **Primary**：修复 hero 卡（状态标题 + 「修复查找功能」主按钮 + 重建范围表单——范围必须提升到主操作旁边，不再埋入折叠区）。
2. **Secondary**：概览指标卡（查找资料概览 / 创作证据健康）、重建进度（WorkflowProgressCard）。
3. **Tertiary**：诊断详情 details（技术信息、检索记录、最近片段宽表）。

## 4. 逐区域标准

### 4.1 查询表单（`RagSearchPanel.vue`）

- 卡片保留但内部按 §3 分层：主行（输入 + 主按钮）一行；常驻筛选一行；高级筛选保持 `<details>` 渐进展开。
- 控件遵循主规范 §5.2：label 在上、helper 在下；章节范围错误保持 `role="alert"` + `aria-invalid`/`aria-describedby`（现有契约，不得破坏）。
- 「包含待处理世界对象」的说明改为可见 helper 文本（`--text-xs` secondary），不得只靠 title。
- literal 模式锁定 manuscript 并禁用其他 scope 的逻辑保留，禁用时给出 helper 说明原因。
- 高级筛选有生效条件或章节范围错误时自动展开、修正后不自动收起的现有行为保留。

### 4.2 结果列表（`RagResultList.vue`）

- 结果卡层级修正：标题回到条目标题档（`--text-base` 600），命中片段正文档，meta 行 `--text-xs` tertiary；删除把标题压到 xs 的覆层（`styles.css:9791-9797`）。
- 相关度百分比加一句人话解释（如「相关度」label 或 title+可见辅助文案），不裸显数字。
- 分页保持每页 20（`RAG_RESULT_PAGE_SIZE`，`logic/routeState.js:6`）+ `data-action="load-more-results"` 渐进加载 + 底部余量提示 + 服务端上限提示（`.rag-search-limit-note`）。
- 加载态改为 `.loading-skeleton` 骨架屏（主规范 §5.9），reduced-motion 下禁动画。
- 检索错误卡保持 `role="alert"` + 保留条件文案 + 两个重试 action（`retry-search` / `retry-literal-search`），视觉向 `.error-card` 基准收敛。
- 降级警告卡（「本次结果可能不准确」）在空结果与有结果分支都要出现（现有双分支行为保留），文案保持「手写不受影响」的安抚口径。

### 4.3 证据抽屉（`RagEvidenceDrawer.vue`）——信任链关键区域

抽屉是「这条资料为什么可信」的唯一呈现处，可读性标准直接决定用户是否敢采纳检索结果。

- **层级**：页面最高浮层（现 z-index 80 保留），fixed 右侧浮层；宽 `min(560px, 100vw-48px)` 现状保留，窄屏近全屏行为保留（见 §6）。
- **可访问性（必须补齐）**：容器加 `role="dialog"` + `aria-modal="true"` + `aria-label`（如「来源证据」）；ESC 关闭；打开时焦点移入、关闭时还原到触发按钮；error 形态补关闭按钮（`RagEvidenceDrawer.vue:77-79`）。遮罩：加半透明遮罩或至少点击外部关闭，现状「无遮罩且点击外部不关闭」必须修正。
- **四种形态的可读性**：
  - chapter（原文证据）：标题（章节名，条目标题档）→ 元信息行（第 N 章 · 版本，`--text-xs` tertiary）→ before/**mark**/after 正文用 `--font-body` 衬线、`--leading-relaxed`，`<mark>` 用 `--archive-red-soft` 底强调命中词 → 跳转/追踪按钮组。命中词必须在上下文中一眼可辨。
  - object（对象）：`<pre>` JSON 是内部数据结构外露，属本页高级定位的有限豁免，但必须等宽字体 + 可横向滚动 + 行高可读；「追踪原文证据（N）」按钮文案保留计数。
  - trace（证据链）：每条证据卡片式分条，来源章号 + 精度用 meta 档；空证据说明文案保留（「该对象暂未建立……」）。
  - error：单行错误升级为标准错误区（错误说明 + 关闭/重试），不得裸文本。
- **加载态**：「读取中/追踪中」从纯文本改为骨架或行内 `.loading` dots + 文案，关闭时取消在途请求的现有三重校验（abort + generation + projectId，`useEvidenceDrawer.js:20-34`）保留。
- **挂载位置**：抽屉节点提升到与结果列表平级（不再 slot 进「有结果」分支），保证加载/错误/空结果切换时抽屉状态不被销毁。
- **视觉**：圆角收编到 `--radius-lg`（4px），阴影用 `--shadow-float` token，删除 14px 硬编码。

### 4.4 status 索引修复子页（`RagStatusPanel.vue`）

- **常设入口**：subnav 恢复「查找 / 索引修复」双项（或等价的常设入口），当前子页正确设置 active + `aria-current`；降级通知条保留作为额外引导而非唯一入口。
- **重建范围表单上移**：`.rag-rebuild-form` 从「诊断详情」details 底部移到修复 hero 卡内主按钮旁（或紧邻），用户点「修复查找功能」前必须看得见将使用的范围；表单字段与 id 不变（§7）。
- **去重**：删除 details 内重复的「返回查找」按钮（`RagStatusPanel.vue:293`），顶部保留一个。
- **诊断分层**：指标卡（概览/证据健康）可直接可见；技术信息八格、检索记录、最近片段九列宽表继续收在「诊断详情」details 内——这是高级诊断，符合渐进展开；维度漂移/预热警告自动展开行为保留。
- **重建进度**：`WorkflowProgressCard` + `role="progressbar"` + `retry-task` 保留，符合主规范 §7 长任务进度要求。
- 断网空态「与服务器连接断开」保留，按 §5.9 空态三件套检查（图标/短句 + 引导 + 行动）。

## 5. 状态覆盖清单

| 状态 | 现有锚点 | 标准 |
|---|---|---|
| 未搜索空态 | 「输入关键词后搜索。」（RagResultList.vue:75-77） | 保留引导文案，可加一句检索方式提示 |
| 搜索加载 | `.loading`（:54） | 改 `.loading-skeleton` 骨架 |
| 无结果 | 「未找到匹配结果」（:75-77） | 空态三件套：短句 + 建议（换关键词/切检索方式）+ 降级警告卡同显 |
| 校验失败 | 「请完善可见性条件」（:56-58） | 指明哪个字段，焦点移到出错字段 |
| 检索错误 | `.rag-search-error` `role="alert"`（:60-68） | 向 `.error-card` 收敛，双重试按钮保留 |
| 索引降级 | `.rag-search-repair-notice` `role="status"`（RagView.vue:123-126） | 保留；修复页 hero 卡同步状态文案 |
| 重建进行中 | WorkflowProgressCard + `retry-task` | 进度条 + 可离开可恢复（island load 预取现状保留） |
| 抽屉读取/追踪中 | 「读取中/追踪中」 | 骨架或 dots，ESC 可关 |
| 断网（status） | 「与服务器连接断开」（RagStatusPanel.vue:112-116） | 空态三件套 |
| 窄屏 390px | e2e 已覆盖 | 见 §6，页面级零横向溢出 |

## 6. 响应式行为（四档）

断点以主规范 §6 终态为准（760/1100），本页现存 720px 抽屉断点归入 760px。

- **Desktop ≥1440**：search 单列限宽居中；抽屉 560px 右浮层。status 指标卡五格横排。
- **Laptop 1100-1440**：默认形态，同 Desktop。
- **Tablet 760-1100**：常驻筛选 `auto-fit minmax(150px,1fr)` 自适应换行（现状保留）；抽屉宽度不变，注意与内容并存时的可读性。
- **Mobile <760**：表单单列，输入与按钮触控目标 ≥42/44px；抽屉近全屏（现 `inset:64px 10px 10px` 行为保留，断点改 760）；chunk 宽表横向滚动保留；390px 零横向溢出（rag.spec.js:59-71 契约）。

## 7. 必须保留的契约

### #id

`rag-search-input`、`rag-search-kind`、`rag-content-mode`、`rag-search-kind-help`、`rag-visibility-mode`、`rag-chapter-from`、`rag-chapter-to`、`rag-cutoff-field`、`rag-cutoff-chapter`、`rag-cutoff-scene-field`、`rag-cutoff-scene-id`、`rag-cutoff-offset-field`、`rag-cutoff-offset`、`rag-character-field`、`rag-character-id`、`rag-include-pending`、`rag-chapter-range-error`、`rag-results`、`rag-evidence-drawer`、`rag-diagnostics`、`rag-rebuild-progress`、`rag-rebuild-content-mode`、`rag-rebuild-start`、`rag-rebuild-end`

### data-action / data-role / data 钩子

`nav-search`、`nav-status`、`do-search`、`retry-search`、`retry-literal-search`、`open-scene-context`、`open-hit`（带 `data-hit-index`）、`load-more-results`、`close-drawer`、`navigate-chapter-ref`、`trace-drawer-ref`（带 `data-ref-index`）、`navigate-scene-ref`、`navigate-object-ref`、`rebuild-index`、`load-retrieval-traces`、`retry-task`（带 `data-task-id`）；`data-role="rag-advanced-filters"` / `data-role="rag-advanced-summary"`；`data-search-scope="manuscript|world|outline"`；`data-rag-advanced-filter`。

### role / 可访问名称

`role="status"`（降级通知条）；`role="alert"`（检索错误卡、章节范围错误）；`aria-label="检索关键词"`；`aria-label="近期检索记录"`；章节范围 `aria-invalid`/`aria-describedby`；`aria-current="page"`（subnav 当前项）；`role="progressbar"`（WorkflowProgressCard）。**新增**：抽屉 `role="dialog"` + `aria-modal` + `aria-label`。

## 8. 验收标准 + 验证命令

验收标准：

1. status 子页存在常设 UI 入口，且 `visual-project-rag.spec.js:77` 的断言恢复有效（或按新入口同步更新该断言与快照）。
2. 抽屉具备 dialog 语义、ESC 关闭、焦点还原、遮罩/外部点击关闭，error 形态有关闭按钮。
3. 抽屉在加载/错误/空结果分支切换时不销毁。
4. 重建范围表单在「修复查找功能」按钮旁可见；重复的「返回查找」只剩一处。
5. 结果卡标题恢复条目标题档；搜索加载为骨架屏。
6. 390px 无页面级横向溢出。

验证命令（在 `frontend-console/` 下执行）：

```bash
npm run test:e2e:functional -- e2e/rag.spec.js      # 功能契约（钩子、分页、390px 响应式）
npm run test:e2e:visual -- e2e/visual-project-rag.spec.js   # 三主题快照：rag-status-{minimal,warm,dark}.png、rag-search-{minimal,warm,dark}.png（darwin 限定）
npm run test:e2e:visual:update -- e2e/visual-project-rag.spec.js   # 改版后重建基线，须人工核对 diff
```

改版时以 `e2e/visual-project-rag.spec.js-snapshots/` 下现有 6 张基线做前后对比锚点；任何快照更新必须在 PR 中附说明。
