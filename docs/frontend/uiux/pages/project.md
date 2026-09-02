# 作品档案（project）UI/UX 执行规范

> 上游标准：`docs/frontend/uiux/design-standard.md`（下称「主规范」），本节号引用均指主规范。
> 实现锚点：`frontend-console/vue/views/project/ProjectView.vue`（304 行）、
> `components/ProjectCard.vue`（113 行）、`components/ImportDrawer.vue`（175 行）、
> `logic/recycleBin.js`、`logic/projectModals.js`、`logic/projectFilter.js`、
> `frontend-console/styles.css` 的 `.project-*` 规则与 hero 覆层。
> 命名：按主规范 §9 裁定，本页统一称「作品档案」；侧边栏「更多」菜单项由「导入与整理」
> （vue/shell/navigation.js:18）改为「作品档案与导入」。topbar 标题（router.js:15）、页内 H1
> （ProjectView.vue:156）、路由失败页按钮「返回作品档案」（router.js:234）已是「作品档案」，不动。

## 1. 页面定位与目标画像

- **目标画像**：画像 A（长期创作的专业或业余作家，`docs/product/user-personas.md` §「画像 A」）。
  本页不服务画像 B。
- **核心任务**：
  1. 在多部作品之间切换上下文——找到要继续的作品并进入写作（对应画像 A「找得到」与
     高频动作短路径）；
  2. 新建空白作品、导入已有正文（对应画像文档 §5 优先级第 1 条「缩短导入 → 看见可用世界
     结构的首次价值时间」）；
  3. 低频管理：编辑元信息、批量整理、回收站恢复/永久删除（对应「改得安心」——误操作可
     撤销/回滚）。
- **设计取向**：本页是「档案柜索引」，主对象是作品卡片网格；批量编辑和删除渐进展开，回收站
  作为恢复入口常驻次级操作，不得干扰高频的「找到并继续」路径（主规范 §0 决策优先级 1-2、5）。

## 2. 现状问题清单（按严重度排序）

1. **【已修复】作品卡键盘入口**：卡片保持 `<article>`，另设不包裹复选框或操作按钮的原生
   `.project-card__open` 按钮；浏览器原生提供 Tab、Enter 与 Space 语义。
2. **【已修复】回收站恢复路径**：入口常驻 hero 次级操作；首次加载失败在 modal 内显示原因与
   可禁用的原位重试按钮，同时保留 toast 提醒。
3. **【已修复】命名一致性**：topbar、页内 H1 与侧边栏统一使用「作品档案」语言；侧边栏入口为
   「作品档案与导入」，设置入口为「作品偏好」。
4. **【已核对无效】hero folio 年份**：当前模板没有 folio、`NC` 或硬编码年份，旧报告引用的
   DOM 已不存在，不为已删除界面补兼容代码。
5. **【已修复】hero H1 字号**：作品档案标题在桌面与窄屏统一消费 `--text-xl`。
6. **【已修复】继续动作统一**：作品卡与写作首页均使用「继续写作」。
7. **【已修复】统计缺省真实表达**：缺少统计时显示「暂无」，title 明确为「暂无字数/章节统计」，
   不再暴露内部接入状态。
8. **【已修复】导入提示**：当前对象统一称「作品」，空选择提示不再引用旧表格行交互。
9. **【已修复】导入记录状态**：复用现有状态色点并显示普通文字，删除冗余 pill 映射。
10. **【已核对】局部断点**：900/460 只做组件级网格微调且有注释；全局行为仍以 760/1100 为准。
11. **【已修复】E2E 契约**：操作按钮由管理模式控制，测试不再描述或执行无效 hover 前置动作。
12. **【已修复】导入动作提示**：无作品时按钮明确为「导入文件并新建作品」；有作品时才显示
    「导入已有作品／收起导入」，保留原有短路径而不增加一次点击。

## 3. 目标布局与信息层级

- **Primary**：项目卡片网格——当前项目 lead 卡（8 列横排，`.project-card--lead`）是自然
  第一视觉焦点；其余卡 4 列跟排，末尾恒有占位卡（ProjectView.vue:280-300）。
- **Secondary**：hero 操作区——「新建空白作品」（唯一 primary）与「导入已有作品」；hero 的
  装饰性（folio/几何图形）服务于档案氛围，不得压过网格。
- **Tertiary**：搜索/筛选条、批量管理条、导入抽屉、回收站——按需展开的管理层，默认不占
  首屏注意力（主规范 §5.10「筛选不常驻首屏」同理念）。
- **阅读路径**：hero（我在「作品档案」、当前项目是谁、能做什么）→ index-bar（搜索/管理）→
  网格（lead 卡 → 其余卡 → 占位卡）。
- **对齐主规范 §4 内容优先契约**：项目卡是「可独立移动的条目」，用卡合法（§5.3）；页面分区
  （hero / index-bar / 网格）靠留白 + 区块间隔，不套分区容器卡。grid gap clamp(12-22px)
  （`.project-catalog`）归入 `--space-3 ~ --space-5` token 档。排序逻辑（当前置顶 → 最近更新倒序
  → 名称 zh-CN，projectFilter.js:18-28）保持不动。

## 4. 逐区域标准

### 4.1 hero（.project-archive-hero，ProjectView.vue:144-176）

- **命名裁定落地**：页内 H1「作品档案」保持（:156）；侧边栏项改「作品档案与导入」
  （navigation.js:18），改可访问名称后全局 grep 同步 e2e 的 `getByRole({name})`/`getByText`
  （主规范 §9 末行）；project.spec.js:8 的 topbar「作品档案」断言不变。
- folio（:145-149）：`NC` 与 `2026` 两处硬编码删除或动态化——中间格已是项目总数（:147），
  裁定第三格改为当前年份动态值或直接移除（执行时核实视觉基线后二选一）；folio 保持
  `aria-hidden`。
- H1 字号收敛到 `--text-xl` 24px（问题 5）；kicker「STORY ARCHIVE · 全部项目」为元数据档
  `--text-xs` + `--tracking-caps`；副文案一句、helper 档（:157）。
- summary 区（:159-165）：「N 个项目」与「CURRENT / 当前」为 mono 元数据档；
  `data-role="project-total-count"`（:161）契约保留。
- 操作组（:166-171）：「新建空白作品」= 全屏唯一 `.btn-primary`（:167）；「导入已有作品」
  「管理作品」= `.btn-ghost`；「回收站」**移出 manageMode 条件**、常驻末位 ghost（问题 2），
  与「管理作品」解耦——manage 模式只管选择/批量，回收站是独立入口。
- 几何装饰（:173-175）保持 `aria-hidden`；窄档逐步隐藏（现状 900px 档隐藏 2 个，保留行为）。

### 4.2 index-bar（:211-255）——映射主规范 §5.10

- 搜索工具条：保持内容区顶部左对齐；输入框宽 240-320px、带清空按钮、结果计数紧随
  （`data-role="project-filter-count"` + `aria-live="polite"`，:228-230）；`role="search"` +
  aria-label（:212）保留。
- 排序提示「当前项目优先 · 其余按最近更新排序」（:231）保留，helper 档 `--text-sm` tertiary。
- 批量工具条（:233-255）：保持「manage 模式内、附着列表顶部」形态（§5.10）；「管理作品」
  toggle 在有已选项时追加计数提示（如「管理作品 · 2 已选」），消除「退出 manage 后选择集仍
  留在 session」的不可见状态（projectSession.js:15-19，执行时核实）；「批量移入回收站」保持
  `.btn-danger` 非实心（§5.1）+ 二次确认（ProjectView.vue:114-125）。

### 4.3 项目卡（ProjectCard.vue）——标题 / 元数据 / 操作三区

整卡信息收敛为三区，区内层级不变、区间用留白 + hairline 分隔（§5.3）：

1. **标题区**（:62-88）：masthead（manage 选择框 :63-75 + 状态点「进行中/已归档」:76-79 +
   CURRENT 徽章 :80）→ eyebrow（genre · stage，:82-86）→ H2 标题（:87，条目标题档
   `--text-base` 14/600；现状更大，执行时按字阶矩阵核实收敛）→ 简介（:88，helper 档，
   ≤2 行截断）。
2. **元数据区**（:89-102）：`dl.project-stats` 三项 WORDS/CHAPTERS/UPDATED——元数据档
   `--text-xs`、mono 等宽、数字右对齐（§3.2、§4 对齐规则）；「待接入」改为「暂无统计」或
   三项全缺时整行隐藏（问题 7，二选一，推荐改文案）。`aria-label="项目统计"`（:89）保留。
3. **操作区**（:103-110）：footer = 创建日期（meta，:104）+ 按钮组；主操作文案
   「继续创作」→「继续写作」（问题 6），`.btn-sm .btn-primary` 保持；「编辑」「删除」仍仅
   manage 模式（:107-108）。

其他卡片规则：

- 整卡鼠标区域由空内容原生 `.project-card__open` 按钮覆盖，按钮与复选框、继续/编辑/删除操作互为
  兄弟节点，禁止嵌套交互元素；`aria-current` 保留在 `<article>`。
- visual 区（:54-60）：`aria-hidden` 保留；168px 高度与 `index % 4` 四色变体（:41、
  `.project-card` 规则）保留为本页系列感表达，但颜色必须走主题 token，不新增字面色值。
- 静态视觉：paper-raised + `--line-subtle`，无阴影；hover 仅边加深或 `--bg-hover` 淡入（§5.3）。
- 占位卡（ProjectView.vue:280-300）：与项目卡同构（visual + copy），`role="button"`
  契约保留；NEW FILE 编号（:296）为元数据档。

### 4.4 导入抽屉（ImportDrawer.vue，挂于 ProjectView.vue:178-180）

- 定位：hero 之下的内联面板（非浮层），同一时刻只服务一个意图：导入到当前项目，或
  「导入为新项目」（:137）。
- hint 修正（问题 8）：:117 改为「先在下方选择一部作品，再导入文件」类用户语言；无项目时
  文件输入与上传按钮 disabled 的现状（:127、:134）保持。
- 表单映射 §5.2：label（`--text-sm` secondary）→ 控件 → helper（accept 白名单说明 :121
  保留为 helper 文案）。
- 按钮层级：「上传并导入」使用默认 `.btn`，同屏唯一 primary 仍是 hero「新建空白作品」；
  「导入为新作品」保持 ghost。
- 上传进度：复用 WorkflowProgressCard（:140-145）——§5.9 Loading 归一的正例，保持。
- 导入记录（:147-173）：`role="region"` + `aria-busy`（:149）保留；加载/空/失败/刷新四态
  文案（:150-158）保留；状态 pill（:164）改为「色点 + 文字」（色点 :162 已有，删 pill 底色，
  问题 9）；失败原因行（:168-170）helper 档；重试按钮（:155）保留。

### 4.5 回收站（recycleBin.js，外壳 modal 内 HTML 字符串子界面）

- 定位：危险操作区；映射 §5.6 Modal 复杂内容档（720px，`{ size: "large" }` 现状对应）。
- 入口：随 §4.1 常驻 hero 末位；modal 标题「回收站」保持。
- 结构标准（recycleBin.js:40-83）：toolbar（「回收站项目 · 共 N 个」+ 全选当前页 + 批量恢复 +
  批量永久删除，:42-48）→ 列表行（checkbox + 名称 + 「删除于 日期」+ 单项恢复/永久删除，
  :53-73）→ 分页（20/页，上一页/下一页 + 「第 X / Y 页」，:76-80）。
- 按钮语义：「批量恢复」使用默认 `.btn`；「永久删除」保持 `.btn-danger`；批量/单项永久删除的
  二次确认保留，确认主按钮文案写动作本身（§5.6）。
- 加载失败补重试（问题 2）：catch 后不只 toast（:86-88），在 modal 内渲染 `.error-card`
  形态（一句人话 + 「重试」按钮），对齐 §5.9。
- 技术债标注：HTML 字符串渲染 + getElementById 手动绑定（:91-201）本次 UI 执行不改架构，
  但任何样式调整不得加深对字符串 DOM 的依赖（执行时核实是否随 Vue 化另行处理）。

### 4.6 新建 / 编辑 modal（projectModals.js）

- 映射 §5.6 表单档 560px；字段 label/控件/helper 缩进链按 §5.2。
- 创建成功直接跳 writing（projectModals.js:199）保持——符合「新建即开始」短路径。
- 单项删除确认（:119-134）保持。

## 5. 状态覆盖清单（映射主规范 §5.9）

| 状态 | 现状 | 缺口 | 目标形态 |
|---|---|---|---|
| 首次进入（无项目） | 引导空态「开始你的第一部小说」，同屏 hero 保留新建与导入入口 | 无 | 不复制第二组 CTA |
| 空态-搜索无结果 | ✅ :258-264，含「清除搜索」CTA | 无 | 保持 |
| 加载 | router 在 island 完成前显示共享 `.loading-skeleton` | 无 | 保持共享加载反馈 |
| 失败-全失败 | ✅ role="alert" 空态 + 重新连接（:182-192） | 无 | 保持，视觉对齐 `.error-card` |
| 失败-部分失败 | ✅ alert + 重试（:207-210），保留旧数据 | 无 | 保持 |
| 失败-回收站加载 | modal 内原因 + 禁用中的重试按钮，并补充 toast | 无 | 保持 |
| 冲突-批量部分失败 | toast 报告失败项（ProjectView.vue:119-121） | 无 | 保持 |
| 保存/操作反馈 | 切换项目 toast（:90）；删除确认后刷新（:123-124） | 无 | 保持 |
| 离开恢复 | 搜索词存 session（projectSession）✅；manageMode 是本地 ref（:69）离开即丢，但选择集残留 session | 重新进入时选择集不可见地生效 | 进入页面时 reconcile 并提示或自动清空（执行时核实，与 §4.2 toggle 计数提示配套） |
| 误操作保护 | 单项/批量移入回收站、永久删除均二次确认 ✅ | 无 | 保持 |
| 窄屏 | 760/460 两档有适配（`.project-*` 响应式规则） | 460px 为组件级微调 | 见 §6 |

## 6. 响应式行为（对齐主规范 §6 四档）

- **≥1440（Desktop）**：12 列 grid；lead 卡 8 列横排 + 普通卡 4 列；hero 三段
  （folio/copy/summary，hero 覆层规则）全展示。
- **1100-1440（Laptop）**：默认形态，同上；grid gap 取 clamp 下档。
- **760-1100（Tablet）**：现 1180 档并入——普通卡 span 6（两列）、lead 全宽
  （`.project-catalog` 的 1100px 规则）；900px 组件级微调中 hero 改 2 列、几何装饰隐藏 2 个。
- **<760（Mobile）**：现有移动档中卡全部 span 12、hero 单列、folio 转横排、批量按钮
  全宽；搜索工具条再压缩、CURRENT 徽章截断；按钮高 ≥42px
  （§5.1 触控档）；390px 无页面级横向溢出（§6 零容忍）。断点归并后在样式行注释保留理由（§6）。

## 7. 必须保留的契约

**ProjectView.vue**

| 契约 | 位置 | 用途 |
|---|---|---|
| `#project-catalog-title` | :156 | section aria-labelledby（:143） |
| `data-role="project-total-count"` | :161 | 项目总数断言 |
| `data-action="new"` | :167 | 新建入口（快捷键 n 触发，vue/shell/composables/useShellShortcuts.js:77-80） |
| `data-action="toggle-import"` / `manage-projects` / `recycle-bin` | :168-170 | hero 操作 |
| `data-action="retry-projects"` | :189、:209 | 全失败/部分失败重试 |
| `role="search"` + `aria-label="搜索作品"` | :212 | 搜索区语义 |
| `#project-search-input` + `data-role="project-search"` | :217-226 | 搜索输入 |
| `data-action="clear-project-search"` | :227、:262 | 清空（工具条 + 搜索空态） |
| `data-role="project-filter-count"` + `aria-live="polite"` | :228 | 结果计数播报 |
| `data-action="select-visible-projects"`（动态 aria-label） | :234 | 全选可见 |
| `.bulk-toolbar[data-scope="project-cards"]` | :235 | 批量条作用域 |
| `data-action="bulk-run"` + `data-scope` + `data-bulk-action="delete-projects"` + `data-bulk-static-disabled` | :242-250 | 批量删除 |
| `data-action="bulk-clear"` | :251 | 清空选择 |
| `data-role="project-search-empty"` | :258 | 搜索空态 |
| 占位卡 `.project-card-placeholder` + `data-action="new"` + `role="button"` + `tabindex="0"` + `aria-label="创建新作品"` | :280-300 | 新建占位 |

**ProjectCard.vue**

| 契约 | 位置 | 用途 |
|---|---|---|
| `.project-card[data-id][aria-current]` + 原生 `button.project-card__open[data-action="open-project"][data-id]` | :47-60 | 卡片容器与独立打开动作 |
| `data-action="bulk-toggle-one"` + `data-scope="project-cards"` + data-id（sr-only label） | :67-73 | 单项选择 |
| `dl.project-stats` + `aria-label="作品统计"` | :89 | 统计区 |
| `data-action="continue-writing"` / `edit-project` / `delete-project`（各带 data-id） | :106-108 | 卡内操作 |

**ImportDrawer.vue**：`#pv-import-file`（accept 白名单，:122-129）、`data-action="upload-file"`
（:133）、`data-action="import"`（:137）、`#pv-upload-progress`（:139）、`#import-list-body`
（role=region + aria-busy，:149）、`data-action="retry-import-history"`（:155）。

**回收站（recycleBin.js）**：`#recycle-select-all` / `#recycle-bulk-restore` /
`#recycle-bulk-delete`（:45-47）、`#recycle-retry`（失败态）、`.recycle-project-checkbox[data-id]`（:60）、
`.restore-project-btn[data-id]` / `.perm-delete-project-btn[data-id]`（:68-69）、
`#recycle-prev-page` / `#recycle-next-page` + 分页 `aria-label="回收站分页"`（:77-79）。

**新建/编辑 modal（projectModals.js）**：`#create-title` / `#create-genre` / `#create-language` /
`#create-tone`（:141-170）；`#edit-title` / `genre` / `tone` / `target-length` / `stage`（:34-64）。

**e2e selectors.js:34-48 对应条目**：`projectCard(id)`、`projectCreatePlaceholder`、
`projectSelectVisible`、`projectImportToggle/File/Submit/NewProject/History/HistoryRetry`、
`projectRecycleBin/SelectAll/BulkRestore/BulkDelete/Checkbox`——以上契约改名必须同步此文件。

## 8. 验收标准 + 验证命令

- [x] 命名统一：侧边栏项为「作品档案与导入」，topbar/页内/e2e 断言同步通过（§9 grep 闭环）。
- [x] 作品卡使用独立原生打开按钮，Tab、Enter 与 Space 由浏览器原生处理；占位卡行为不变。
- [x] 「回收站」按钮非 manage 模式也可见；回收站加载失败出现重试 UI。
- [x] 统计缺省不再出现「待接入」；按钮文案为「继续写作」。
- [x] hero 无硬编码年份；H1 = `--text-xl` 24px；全屏唯一 primary 为「新建空白作品」
  （抽屉打开时上传按钮非 primary）。
- [x] 导入抽屉 hint 与卡片网格现状一致；导入记录无彩色 pill（色点 + 文字）。
- [x] 「管理作品」toggle 在有已选项时显示计数；批量删除二次确认保持。
- [x] 首次空态直接复用仍在同屏的 hero 新建/导入入口，不复制 CTA；路由切换使用 router 共享骨架。
- [x] 全局断点保持 760/1100，900/460 仅作有注释的组件级网格微调；390px E2E 覆盖无横向溢出。
- [x] §7 契约与 selectors.js 已核对；改动只更新可见文案和既有 action 的语义。

验证命令（在 `frontend-console/` 下）：

```bash
npm test -- tests/vue/project tests/vue/projectIsland.test.js   # 视图/island 单测
npm test -- tests/editorialTheme.test.js tests/typographyTokens.test.js
npm run test:e2e:functional -- e2e/project.spec.js e2e/import.spec.js e2e/import-errors.spec.js
npm run test:e2e:functional -- e2e/home.spec.js                 # 壳层快捷键 n → data-action="new"
npm run test:e2e:visual -- e2e/visual-project-rag.spec.js       # project-catalog 三主题基线
```
