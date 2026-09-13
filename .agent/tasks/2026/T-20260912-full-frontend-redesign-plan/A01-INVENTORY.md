# A01 文稿、作品、计划与导入入口清点

日期：2026-09-12。范围：正式 Vue 前端、写作21项评估、`prototypes/redesign/` 当前样板及 PLAN 阶段 A/C 对应要求。只读清点；本文件是设计归属证据，不是业务接回或功能验收。

## 结论

正式写作入口是 `writing` 路由下的 `WritingView`：它组合写作首页、章节树、正文编辑器、本章资料、工作流条、版本历史、冲突、导入审计和 Owner AI 抽屉。作品档案是独立 `project` 路由；文件导入是作品页内 `ImportDrawer`。作者计划实际复用 `writing?home=1&panel=tasks` 下的 `AuthorTasksView`，与后台工作流分开。世界书目录导入和写作页深度整理则是另外两条导入路径。

`WritingPreview.vue` 与 `WorkspacePreview.vue` 只是隔离视觉样板：使用《潮汐来信》虚构内存数据，不接正式 API、路由或真实存储。可复用其正文纸面、章节目录、状态提示、作品卡片、计划行和导入步骤；实际缺口是正式入口完整状态、返回上下文、候选/历史/正式身份区分，以及导入准备到审阅/处理记录的连续表达。

## 原入口与新设计归属

| 正式入口/子视图证据 | 对象与关键状态 | 新设计归属 | 返回位置 | 业务接回（另列） |
|---|---|---|---|---|
| `router.js` → `writing`；`WritingView.vue` | 当前作品/章节/版本；编辑、只读、候选、正式、历史；加载、空章节、保存失败、冲突、恢复 | **P01–P05**：文稿控制＋正文＋本章资料；版本/候选用共同审阅模式 | 回写作首页或原章节、选区、滚动；跨域打开后回原稿 | `useWritingWorkspace.js`、`editorController.js`、`writingSession.js`；保存/备份、CAS、版本、正式确认、导出、章节切换后续接回 |
| `WritingView` → `ChapterTree.vue` | 搜索、选择、创建、管理、多选删除；目录失败、无章节、未选章 | **P02**：目录内搜索与按需管理；空/失败各自表达 | 回当前章；管理失败保留选择 | `createChapter`、`deleteChapters`、加载/切换和 leave guard |
| `WritingView` → `WritingEditor.vue` | 标题/正文输入、工作稿；保存、版本、正式正文；AI建议、冲突检查、导出 | **P01/P03/P04**：同一纸面承载编辑/候选/历史；AI只承接生成审查返修 | 关闭菜单或结果回原稿和焦点 | `editorController` 自动保存/检查点/发布、候选回执、导出；标题保存语义保留 |
| `WritingView` → `VersionHistoryDialog.vue` | 版本列表、预览、任意两版比较、恢复、删除；published/candidate/deprecated/draft | **P04/P03**：历史只读、候选待决定、从此版继续、正式确认分开 | 关闭回原章节/版本；恢复后回当前工作稿 | `switchVersion`、`restoreVersion`、比较/删除及并发保护 |
| `WritingView` → `SceneCockpit`、`SceneLensSummary`、`ChapterMapDialog`、`OutlineFloat` | 当前场景、人物/地点、节拍、冲突、证据钉选、地图、结构浮窗 | **P05**：本章资料切换场景/人物/来源/结构/地图；复杂管理转 D08/D10/D14 | 回原章、选区、滚动；当前场景不能被光标或 AI 静默改写 | scene/map/outline/Evidence/冲突定位和权限接回；钉选不等于生成资料 |
| `WritingWorkflowBars`、`DeepImportAuditDialog`、`AutoExtractionDialog` | 发布/生成/冲突/深度导入；进行中、停止、失败、可恢复、审计 | **E02/E04/P08**：任务摘要与导入整理共用结果语言，作者计划仍独立 | 写作或首页任务入口重开同一任务；关闭不等于取消 | 工作流轮询、取消/恢复/放弃、候选审阅/查漏恢复服务 |
| `writing?home=1` → `WritingHomeView`/`TodayView` | 继续创作、字数、待决定、阶段成果、工作流、作者任务；首页加载/失败 | **P07**：创作概览、继续创作；待决定回领域审阅 | 继续创作回上次章节/工作稿；切换作品回档案 | `todayIsland.js` 汇总 continuation/attention/workflow；来源指纹与恢复接回 |
| `writing?home=1&panel=tasks` → `AuthorTasksView` | 作者主动任务；今天/收件箱/之后/已完成/已归档；创建、编辑、完成、归档、恢复；草稿暂存和来源失效 | **P07**：作者计划列表/详情/编辑；与后台任务分离 | 回写作首页；来源按钮回正文/世界/结构 | `useAuthorTasks` CRUD、source route、sessionStorage 草稿、409 和 leave guard |
| `router.js` → `project` → `ProjectView`/`ProjectCard` | 作品列表、当前作品、名称搜索、创建/编辑、筛选/管理、多选、回收站；失败、空作品、空搜索 | **P06**：对象优先作品档案；创建/编辑/危险操作按需展开 | 打开作品进入写作首页；取消回档案 | `projectIsland.js`、`loadProjectsIntoState`；owner/隔离、CRUD、回收站、确认 |
| `project` → `ImportDrawer.vue` | 当前作品导入、导入为新作品、txt/epub/html/htm ≤50MB、上传进度、导入历史；无项目、失败、无记录 | **P08**：导入准备→章节检查→资料审阅；历史/深度整理结果转 E04 | 关闭回作品档案；导入完成回新作品或写作入口 | `useImportUpload`、XHR进度、`imports.list`；文件边界、owner/novel_id、幂等 |
| `world/bible` → `WorldbookImportPanel.vue` | 目录选择、预览计数、创建/更新工作稿、冲突/缺源；Markdown/TXT/JSON/YAML | **D05/E04**：世界书导入归世界资料/整理，不复制作品上传页 | 关闭回世界书；应用后回工作稿/待核对项 | `previewFiles`/`applyImport`、draft/suggestion/adoption；成功不等于正式设定 |
| `project-settings` → `DeepImportFields.vue` | 深度、范围、自动采用/审阅等作品偏好 | **E04/F06**：导入流程渐进设置，账户/作品作用域清晰 | 回导入或写作原入口 | 设置契约、授权范围、任务快照、provider 配置；不新增参数语义 |

## 写作21项的最小归并

| 评估项 | 设计归属 | 正式实现与样板缺口 |
|---|---|---|
| 1 保存；5 失败恢复；9 版本状态 | P01 文稿控制/风险卡 | `WritingEditor`、`editorController` 已有保存菜单、状态、本地备份；样板只有通知，无输入保全 |
| 2 正式正文；3 标题；4 编辑器状态；7 空/加载失败 | P01 正文与身份 | 正式编辑器已有标题、只读、空/加载/失败/确认；样板正文是只读 article，无标题/正文输入 |
| 6 章节搜索管理 | P02 章节目录 | `ChapterTree` 已有 search、多选、创建、批量删除；样板只有六章选择和新建 |
| 8 加入计划 | P02/P07 章节菜单→作者计划 | `addChapterTask`、`AuthorTasksView` source/草稿/返回已存在；样板是静态计划行 |
| 10 版本操作 | P04 历史比较 | 正式版本对话框/比较已有；样板仅写死三行版本 |
| 11 AI工具；12 候选审查 | P03＋E01/E03 | 正式 AI 菜单、候选分支、OwnerAiDrawer 已有；样板无来源、审查覆盖和过期资格 |
| 13 自动整理；14 长任务；15 冲突 | E02/E04＋P01 | 正式工作流/导入/冲突对话框已有；样板未表达停止、恢复、任务重开 |
| 16 场景；17 Lens/证据；18 地图；19 大纲 | P05，复杂视图转 D08/D10/D14 | 正式入口均已有；样板仅静态当前场景/人物/灵感，无对象、选区、来源连续性 |
| 20 导出 | P01 文稿更多菜单 | 正式编辑器直接发出 export；样板没有导出及稿件身份/空内容/保全表达 |
| 21 手机写作壳 | G01 后续适配 | 正式页已有窄屏章节/资料抽屉和专注模式；样板是桌面布局，延期不等于删除 |

## 可复用点与实际缺口

- 可复用：样板正文纸面、章节侧栏、状态提示、继续创作、作品卡片、计划行、导入步骤；正式组件的状态词和操作边界作为语义来源。
- 可复用：router 的 `writing` 查询（`home=1`、`panel=tasks`、`scope`）和跨域查询参数；无需复制业务路由或暴露 raw ID。
- 缺口：样板正文不可编辑，标题/IME/撤销/选区/未保存输入没有表达；状态切换不保留同一输入。
- 缺口：`projects/tasks/import` 只在原型条件分支展示；作品编辑/回收、作者计划表单、导入历史/失败/章节拆分和真实返回未覆盖。
- 缺口：候选、工作稿、正式、历史和来源过期没有共同身份；比较/审阅/采用不能只是通用浮层按钮。
- 缺口：三条正式导入路径需分别标域归属，并连出准备、待决定、处理记录和终点；不能把导入当成无状态页面。
- 缺口：写作→查找/来源/地图/场景/结构/任务→回原章的选区、滚动和面板开合是接回耦合点；现有导航能带查询目标，原型尚未演示连续返回。

## 证据范围与限制

已读 PLAN 阶段A/C及第5节边界、SUBAGENT-EXECUTION-LUNA A01/P01–P08、WRITING-CAPABILITY-ASSESSMENT；正式 router、writingIsland、WritingView、写作组件/控制器、WritingHomeView、TodayView、AuthorTasksView、ProjectView、ImportDrawer、WorldbookImportPanel；原型 WritingPreview、WorkspacePreview、RedesignApp、data.js。

未做浏览器操作，未运行 API/真实数据库/模型，未声称视觉或业务验收通过；当前工作树有大量用户 WIP，未修改产品/原型代码。
