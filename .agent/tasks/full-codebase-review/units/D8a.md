# D8a 槽位审查报告（R12 前端页面：写作/大纲/Scene/生成/今日视图集群）

日期：2026-09-11。审查者：D8a 子代理（只读）。基线：`main` HEAD `e7d0b8d5b` 工作树。范围：slot-paths-W2.json "D8a" 全部 77 路径（generate 14、outline 23、scene 13、today 1、writing 26），逐文件语义阅读完成，无抽样。另有 cross 核实：workflowManager.js 工厂、workflowProgress.js、accountStorage.js（只读引用，不属本槽位）。

## 覆盖行

CSV 片段（列：`path,审查状态,入口/消费者(可空),发现ID或无发现理由`）：

```csv
frontend-console/vue/views/generate/GenerateView.vue,已审,generateIsland loadGenerate→OwnerAiDrawer 动态挂载 + writingIsland home 模式 owner_ai,D8a-1/D8a-3/D8a-5
frontend-console/vue/views/generate/components/CocreationHistory.vue,已审,GenerateView 历史会话抽屉,无发现（generation 守卫与 open 门控完备）
frontend-console/vue/views/generate/components/ContextBundleView.vue,已审,TaskContextTab/ContextPreviewTab,无发现
frontend-console/vue/views/generate/components/ContextPreviewTab.vue,已审,GenerateView preview tab,无发现
frontend-console/vue/views/generate/components/PovProseTab.vue,已审,GenerateView pov_prose tab,无发现
frontend-console/vue/views/generate/components/ReferencePickerAdapter.vue,已审,TaskContextTab/SceneWorkbenchView 场景详情,无发现（syncGeneration+destroy 防泄漏）
frontend-console/vue/views/generate/components/TaskContextTab.vue,已审,GenerateView task tab,无发现
frontend-console/vue/views/generate/components/WorldDesignPanel.vue,已审,GenerateView worldCore 面板 + CocreationHistory 只读复用,无发现
frontend-console/vue/views/generate/components/WorldResult.vue,已审,WorldWorkspace 结果区,无发现
frontend-console/vue/views/generate/components/WorldWorkspace.vue,已审,GenerateView world tab 主体,无发现（IMD 输入/composition 守卫/滚动锚定完备）
frontend-console/vue/views/generate/generateSession.js,已审,GenerateView/TodayView 会话存储层,D8a-1（context preview 键为 sessionStorage 且分段合理；主体键 generate_world_workspace_state_v2_ 已在清理清单）
frontend-console/vue/views/generate/logic/generateLogic.js,已审,GenerateView 全部 payload/渲染纯函数,无发现
frontend-console/vue/views/generate/pageProposalSession.js,已审,GenerateView/WorldResult 提案草稿 schema,无发现
frontend-console/vue/views/generate/requestOwner.js,已审,GenerateView 异步所有权（generation+AbortController）,无发现（本集群竞态防护核心，记共享事实）
frontend-console/vue/views/outline/OutlineView.vue,已审,outlineIsland viewLoaders 根组件,A8-3（smartDedup 派发点，归 F3-4）
frontend-console/vue/views/outline/ai/OutlineAnalysisProgressCard.vue,已审,OutlineView/OutlineStoryTab,无发现
frontend-console/vue/views/outline/ai/OutlineAnalysisResultCard.vue,已审,OutlineView/OutlineStoryTab,无发现
frontend-console/vue/views/outline/ai/OutlineArcPreviewPage.vue,已审,OutlineView arcs review 路由,D8a-1/D8a-4
frontend-console/vue/views/outline/ai/OutlineGenerateProgressCard.vue,已审,OutlineView/SceneWorkbenchView,无发现
frontend-console/vue/views/outline/ai/OutlineScenePreviewPage.vue,已审,OutlineView scenes review 路由,D8a-1/D8a-4（grep 核实骨架与 arc/thread 同构）
frontend-console/vue/views/outline/ai/OutlineThreadPreviewPage.vue,已审,OutlineView threads review 路由,D8a-1/D8a-4
frontend-console/vue/views/outline/ai/PlotAutoExtractProgressCard.vue,已审,OutlineView,无发现
frontend-console/vue/views/outline/ai/outlineAiOps.js,已审,OutlineHeader/OutlineStoryTab/SceneWorkbenchView AI 入口,无发现（提交前后 projectId 双检、operationId 幂等）
frontend-console/vue/views/outline/ai/outlineWorkflowManagers.js,已审,OutlineView 进度卡与预览页,无发现（工厂三实例，matchesActiveScope 按 target 防串）
frontend-console/vue/views/outline/components/OutlineArcsTab.vue,已审,OutlineView arcs,无发现（与 ThreadsTab 同构属 D8a-4 同族，单独收敛收益低，见发现内说明）
frontend-console/vue/views/outline/components/OutlineBulkToolbar.vue,已审,OutlineThreadsTab/OutlineArcsTab,无发现
frontend-console/vue/views/outline/components/OutlineHeader.vue,已审,OutlineView 全部子视图,无发现（A8-3 挂载点，归 F3-4）
frontend-console/vue/views/outline/components/OutlineThreadsTab.vue,已审,OutlineView threads,无发现（行内草稿键带 novel_ 前缀+账号分段，正确）
frontend-console/vue/views/outline/logic/outlineBulkSelection.js,已审,OutlineTabs/outlineAiOps,无发现（scopeBulkSelectionsToProject 防跨项目污染）
frontend-console/vue/views/outline/logic/outlineStructure.js,已审,OutlineView 预取与 URL codec,无发现
frontend-console/vue/views/outline/logic/outlineStructureOps.js,已审,OutlineTabs/OutlineHeader CRUD,微项：showCreateRevealForm 硬编码零 UUID target_id（见 D8a-7 附注）
frontend-console/vue/views/outline/story/OutlineStoryEditorPage.vue,已审,OutlineView story-outline edit=1,D8a-1
frontend-console/vue/views/outline/story/OutlineStoryTab.vue,已审,OutlineView story-outline,D8a-1（manualDraftExists 读同前缀键）
frontend-console/vue/views/outline/story/StoryListActions.vue,已审,StoryOutlineEditorFields,无发现
frontend-console/vue/views/outline/story/StoryOutlineEditorFields.vue,已审,OutlineStoryTab/OutlineStoryEditorPage,无发现
frontend-console/vue/views/outline/story/storyOutlineData.js,已审,storyOutlineIsland 预取 + manager,无发现（D8a-6 手写 manager 之一）
frontend-console/vue/views/outline/story/useStoryOutline.js,已审,OutlineStoryTab composable,D8a-1
frontend-console/vue/views/scene/CharacterCardsPanel.vue,已审,SceneWorkbenchView characters tab,无发现
frontend-console/vue/views/scene/SceneAutoExtractProgressCard.vue,已审,SceneWorkbenchView,无发现
frontend-console/vue/views/scene/SceneRuntimeTabs.vue,已审,SceneWorkbenchView,无发现
frontend-console/vue/views/scene/SceneScriptsPanel.vue,已审,SceneWorkbenchView script tab,无发现
frontend-console/vue/views/scene/SceneSimulationPanel.vue,已审,SceneWorkbenchView simulation tab,无发现
frontend-console/vue/views/scene/SceneWorkbenchView.vue,已审,OutlineView scenes 分支（异步 lazy）,无发现（A8-3 派发点归 F3-4；leaveGuard 双草稿合并保护完备）
frontend-console/vue/views/scene/sceneAutoExtractManager.js,已审,useSceneWorkbench/SceneWorkbenchView,A8-2（手写 manager，D8a-6）
frontend-console/vue/views/scene/sceneModalController.js,已审,useSceneWorkbench 模态编排,无发现（owns 三重守卫一致；融合任务 recover 完备）
frontend-console/vue/views/scene/sceneModel.js,已审,sceneSession/query/label 纯函数层,无发现
frontend-console/vue/views/scene/sceneRuntimeManager.js,已审,useStorySceneWorkspace,A8-2（手写 manager，D8a-6）
frontend-console/vue/views/scene/sceneRuntimeSession.js,已审,useStorySceneWorkspace 草稿层,D8a-1/D8a-2 记录见共享事实（256KB 逐级降级完备）
frontend-console/vue/views/scene/useSceneWorkbench.js,已审,SceneWorkbenchView composable,无发现
frontend-console/vue/views/scene/useStorySceneWorkspace.js,已审,SceneWorkbenchView 人物卡/推演/剧本 composable,无发现（owns 含 currentView/SubView 校验；terminal 订阅卸载退订）
frontend-console/vue/views/today/TodayView.vue,已审,writingIsland home 模式 + todayIsland（归一化后经 writing home）,无发现（componentGeneration 守卫完备）
frontend-console/vue/views/writing/WritingView.vue,已审,writingIsland 根组件,微项：OwnerAiDrawer 两分支重复绑定（记 D8a-7 附注）
frontend-console/vue/views/writing/components/AutoExtractionDialog.vue,已审,WritingView,无发现
frontend-console/vue/views/writing/components/ChapterMapDialog.vue,已审,WritingView,无发现（generation+props 全等守卫）
frontend-console/vue/views/writing/components/ChapterTree.vue,已审,WritingView 左栏,无发现（无虚拟滚动，千章级 DOM 量可控，记共享事实）
frontend-console/vue/views/writing/components/ConflictDetailDialog.vue,已审,WritingView,无发现（suggestionDrafts watch 清理完备）
frontend-console/vue/views/writing/components/ConflictOptionsDialog.vue,已审,WritingView,无发现
frontend-console/vue/views/writing/components/DeepImportAuditDialog.vue,已审,WritingView,无发现
frontend-console/vue/views/writing/components/OutlineFloat.vue,已审,WritingView,无发现
frontend-console/vue/views/writing/components/SceneCockpit.vue,已审,WritingView 右栏,无发现
frontend-console/vue/views/writing/components/SceneLensSummary.vue,已审,SceneCockpit,无发现
frontend-console/vue/views/writing/components/VersionHistoryDialog.vue,已审,WritingView,A4-3（isActive，D8a-2）
frontend-console/vue/views/writing/components/WritingEditor.vue,已审,WritingView 编辑器,无发现
frontend-console/vue/views/writing/components/WritingWorkflowBars.vue,已审,WritingView 任务通知区,无发现（自动消隐 timer 卸载清理完备）
frontend-console/vue/views/writing/controllers/conflictController.js,已审,useWritingWorkspace,D8a-5（waitForTask 无退避）
frontend-console/vue/views/writing/controllers/deepImportController.js,已审,useWritingWorkspace,无发现（有退避表+finalized 防复活；storage 参数缺省与 F3 键清单一致性记共享事实）
frontend-console/vue/views/writing/controllers/editorController.js,已审,useWritingWorkspace 核心编辑控制器,D8a-2（activeVersion）
frontend-console/vue/views/writing/controllers/writingCommandController.js,已审,useWritingWorkspace,D8a-5（waitForDraft/waitForManagedTask 无退避）
frontend-console/vue/views/writing/home/AuthorTaskForm.vue,已审,AuthorTasksView,无发现
frontend-console/vue/views/writing/home/AuthorTasksView.vue,已审,writing home panel=tasks,无发现（sessionStorage 草稿带 novel_ 前缀，正确）
frontend-console/vue/views/writing/home/WritingHomeView.vue,已审,writingIsland home 模式,无发现
frontend-console/vue/views/writing/home/authorTaskSource.js,已审,TodayView/AuthorTasksView/SceneWorkbenchView,无发现
frontend-console/vue/views/writing/home/useAuthorTasks.js,已审,AuthorTasksView,无发现（409 冲突跨 scope 重取基线，防误覆盖）
frontend-console/vue/views/writing/sceneLensModel.js,已审,SceneLensSummary,无发现
frontend-console/vue/views/writing/useWritingWorkspace.js,已审,WritingView composable,A4-3×6/D8a-7（saveStatus 全文正则）
frontend-console/vue/views/writing/writing-desk.css,已审,WritingView import,无发现（纯视觉层，分节注释清晰，313 选择器）
frontend-console/vue/views/writing/writingSession.js,已审,useWritingWorkspace/editorController 会话层,无发现（unsafe 快照不驱逐，保护到位）
```

全部 77 路径状态=已审；无按生成源验证、不适用、受阻项。

## 发现

### D8a-1 六个 localStorage 草稿键前缀未登记进账号清理清单

- **ID**：D8a-1
- **位置/符号**：`frontend-console/vue/views/scene/sceneRuntimeSession.js:13`（`scene_runtime_draft:v1:`）；`frontend-console/vue/views/writing/home/../OutlineStoryEditorPage.vue:96` 与 `OutlineStoryTab.vue:294`（`story-outline-editor-draft:`）；`frontend-console/vue/views/outline/story/useStoryOutline.js:73`（`story-outline-preview-draft:`）；`OutlineThreadPreviewPage.vue:267`、`OutlineArcPreviewPage.vue:201`、`OutlineScenePreviewPage.vue:229`（`novel_outline_thread_preview:` / `novel_outline_arc_preview:` / `novel_outline_scene_preview:`）；对照 `frontend-console/shared/accountStorage.js:5-15`（LOCAL_STORAGE_PREFIXES 不含上述前缀）
- **问题与触发**：账号切换/失效时 `scopeBrowserStorageToAccount`/`invalidateAccountBrowserState` 按前缀清理本地存储，这六个前缀全部不在清单中，草稿跨账号残留在浏览器。`scene_runtime_draft:v1:` 每个 scene 一个键（每键上限 256KB）且无数量上限，长期使用可在 localStorage 积累大量残留；story-outline 与 outline 预览键保存总纲/剧情线/篇章/细纲正文草稿，属用户内容残留。键均含 projectId，另一账号的项目 id 不同，无功能冲突或跨项目读取路径——风险是设备上的内容残留与 F3 共享事实声明的"新增前端持久化键必须落入上述前缀或在 accountStorage 登记"约定被绕过。正确的对照样本就在本槽位内：`novel_outline_thread_edits`/`novel_outline_arc_edits`（OutlineThreadsTab.vue:265、OutlineArcsTab.vue:195）带 `novel_` 前缀且主动读 `ACCOUNT_MARKER_KEY` 做账号分段。
- **调用链证据**：`rg -n "scene_runtime_draft|story-outline-editor-draft|story-outline-preview-draft|novel_outline_(thread|arc|scene)_preview" frontend-console` 全部命中即上述文件；`rg -n "LOCAL_STORAGE_PREFIXES" frontend-console/shared/accountStorage.js` 无这些前缀。
- **现有契约**：§3 数据保护（账号边界）；不改任何运行行为，仅补登记。
- **最小方案**：把六个前缀加入 `accountStorage.js` 的 `LOCAL_STORAGE_PREFIXES`（`novel_outline_*_preview` 三个也可用单条前缀 `novel_outline_` 覆盖，但会扩大清出面，建议逐条登记）；scene 键另加一个数量上限（如 20 个场景）防止无界增长，属可选强化。
- **预期收益**：账号边界约定一致；用户内容不再跨账号残留。
- **风险**：低。清理后用户在旧账号未保存的草稿不可恢复——这正是清理语义的本意；同账号不受影响（清理仅发生在账号切换/失效）。
- **依赖**：无。
- **验证命令/断言**：`npm test -- tests/`（accountStorage 相关单测补充断言：写入上述前缀键后调用 `clearAccountScopedBrowserStorage` 应清除）；`rg -n "scene_runtime_draft" frontend-console/shared/accountStorage.js` 命中。
- **回滚**：单提交 revert。
- **裁定**：实施候选。
- **优先级建议**：P2

### D8a-2 前端 version active 判定 8 处重复（历史 A4-3，仍成立，定位更新）

- **ID**：D8a-2
- **位置/符号**：同语义表达式 `version.display_state ? version.display_state === "active" : !["candidate", "deprecated"].includes(version.status)` 出现在：`useWritingWorkspace.js:226-227`（activeVersions）、`:232-233`（candidateComparisonAvailable）、`:754`（switchVersion）、`:789-790`（compareCandidateWithWorkingDraft）、`:805`（restoreVersion）、`:824`（deleteVersion）；`controllers/editorController.js:14-18`（activeVersion，无 display_state 分支名相同）；`components/VersionHistoryDialog.vue:101`（isActive）。
- **问题与触发**：版本"活跃/可编辑"判定是写作侧最关键的状态词汇之一（决定版本选择器、比较基线、可删除集合），8 处手写意味着 display_state 语义演进（如新增 display_state 值）时需要同步 8 点，漏一处即出现"选择器可切换但历史页不允许恢复"类不一致。当前 8 处语义逐字一致（已逐一比对，包括 editorController 省略 display_state 时同样落到 status 判断）。
- **调用链证据**：见上方 rg census（`display_state \? .*=== \"active\"|!\[\"candidate\", \"deprecated\"\]\.includes` 在 vue/views+vue/shared+shared 内全部命中已列）。
- **现有契约**：§2 持久化兼容面——判定语义必须保持，收敛是纯提取。
- **最小方案**：在 `frontend-console/vue/views/writing/`（或 shared）导出 `isVersionActive(version)`，8 处替换；useWritingWorkspace 内 6 处同时合并为基于同一 computed/filter 的调用。
- **预期收益**：状态词汇单点定义；消除 8 处漂移面。
- **风险**：极低（同语义提取；VersionHistoryDialog 是子组件，经 props/导入可用）。
- **依赖**：无。
- **验证命令/断言**：`npm test -- tests/vue/`（writing 相关）；`rg -c "candidate\", \"deprecated\"" frontend-console/vue/views/writing` 收敛后应仅命中 helper 一处。
- **回滚**：单提交 revert。
- **裁定**：实施候选（顺手修改级）。
- **优先级建议**：P3

### D8a-3 GenerateView 会话持久化无节流：每键全量序列化 + 同步 localStorage 写

- **ID**：D8a-3
- **位置/符号**：`frontend-console/vue/views/generate/GenerateView.vue:284`（`watch(session, persist, { deep: true })`）、`:285`（`watch(composer, () => { if (persist()) rememberGenerateContinuation() })`）、`:202-207`（persist→writeGenerateSession）；`frontend-console/vue/views/generate/generateSession.js:449-474`（serializeGenerateSession：全量 `JSON.stringify` + `byteLength`=TextEncoder 全量编码）、`:476-511`（writeGenerateSession：`storage.setItem` 同步 + quota 时 `storageEntries` 全表扫描）。
- **问题与触发**：输入框每敲一个字符触发一次 persist：整份会话（最多 40 条消息、收束草稿 cards、视觉简报、外部回包历史，上限 512KB）全量 stringify → TextEncoder 编码测长（超限时再 stringify 多次）→ 同步 setItem。长会话下这是每次键入数百 KB 级的同步序列化+IO。对照组在同仓库内：writing 的 editorController 以 `LOCAL_PERSIST_DELAY = 250` 节流（editorController.js:8、188-194）；outline 预览页同为 250ms debounce（OutlineThreadPreviewPage.vue:288）。generate 侧是集群中唯一无节流的持久化热路径。收益待测（未做性能取证），但机制与同仓对照明确。
- **调用链证据**：读 GenerateView watch 声明全文；composer v-model 经 WorldWorkspace（WorldWorkspace.vue:282）直连；session deep watch 覆盖 messages/disposition 点击等全部变更。
- **现有契约**：§2 用户操作——"已备份"语义必须保持：persist 失败时 sessionBackupFailed 与离开保护已存在，节流不得破坏"离开/刷新前 flush"。
- **最小方案**：persist 外包 250ms trailing debounce（沿用 editorController 模式）；`onBeforeUnmount`（GenerateView.vue:1567 已有 persist()）、useLeaveGuard（:319）与 protectDesignBeforeUnload（:323）处改为同步 flush（现有调用点已经直调 persist，只需确保 debounce 计时器在 flush 前取消并立即执行）。
- **预期收益**：长会话输入路径去除每键全量序列化；行为与 writing/outline 一致。
- **风险**：低。窗口在 debounce 间隔内被强杀会丢最后一拍——与 writing 现状一致，且 beforeunload 仍有同步 flush。
- **依赖**：无。
- **验证命令/断言**：`npm test -- tests/vue/generate`（generateSession 单测）；手动断言输入时 Performance 面板无每键 stringify（实施期取证，满足计划"性能候选有前后可比证据"要求）。
- **回滚**：单提交 revert。
- **裁定**：实施候选。
- **优先级建议**：P3

### D8a-4 outline 三个 AI 预览页约九成骨架重复

- **ID**：D8a-4
- **位置/符号**：`frontend-console/vue/views/outline/ai/OutlineThreadPreviewPage.vue`（535 行）、`OutlineArcPreviewPage.vue`（433 行）、`OutlineScenePreviewPage.vue`（461 行）。同构部分：`storageKey`/`saveDraft`/`clearDraft`/`initializeDraft`/`saveState`/`validateDraft` 骨架/`normalizeDraft` 骨架/`apply`/`restoreOriginal`/`discard`/`closeReview`/`localRef`/`needsCheck`/`clone`/`moveItem`、`useLeaveGuard`+`beforeunload` 双保险、三个 watch（initialize/保存 250ms debounce/409 conflict）——仅字段集、校验文案、target 标识与 storageKey 前缀不同。
- **问题与触发**：三页合计约 1430 行，其中约 900 行是逐字或近逐字重复的生命周期骨架。修复骨架级 bug（如 409 处理、debounce、恢复校验）需三处同步；新增 target 类型（如未来 planned_scene 之外的层级）要再复制一份。
- **调用链证据**：三文件逐段比对；`applyOutlineGeneratePreview`/`resetOutlineGenerateState`/`clearOutlineGenerateWorkflowsForTarget` 共享自 outlineAiOps/outlineWorkflowManagers，差异仅在 draft 字段。
- **现有契约**：§2 用户操作——三页 DOM id/data-action 与 e2e 契约保留；localStorage 键格式不变。
- **最小方案**：抽 `useOutlineGeneratePreviewDraft({ target, fields, validate, normalize })` composable 承载存储/恢复/离开保护/apply 流程，三页只留字段模板与文案。量力分步：先抽 thread/arc（同构度最高），scene 页第二步。
- **预期收益**：约 600-900 行重复消除；骨架修复单点化。
- **风险**：中。三页各自有细微差异（thread 有 movements/nodes 嵌套校验、arc 有 moveArc 重排序、scene 页细节未逐行读），抽取消融需逐页回归 AI 建议采用全流程。
- **依赖**：无（建议排在 A8-4 契约迁移批次之外独立做）。
- **验证命令/断言**：`npm test -- tests/vue/`；e2e 结构建议采用链（`npm run test:e2e:functional` 专项）。
- **回滚**：逐页切换、可部分回滚。
- **裁定**：实施候选（维护收益明确，优先级让位于 D8a-1/D8a-2）。
- **优先级建议**：P3

### D8a-5 五处手写任务轮询循环缺失败退避（与 F3-7 同族）

- **ID**：D8a-5
- **位置/符号**：`frontend-console/vue/views/writing/controllers/writingCommandController.js:97-130`（waitForDraft，非 404 错误固定 `wait(1500)` 无上限）、`:132-159`（waitForManagedTask，同型）；`frontend-console/vue/views/writing/controllers/conflictController.js:56-76`（waitForTask，`wait(token, projectId)` 默认 1000ms 无上限）；`frontend-console/vue/views/generate/GenerateView.vue:1369`（waitForPovTask，1.5s 无上限）；对照已有退避的 `deepImportController.js:18`（`POLL_RETRY_DELAYS_MS = [3000, 6000, 12000, 24000, 30000]`）与共享 `workflowProgress.js` pollTaskProgress（F3-7 已记录其 catch 分支无退避）。
- **问题与触发**：任务提交后进入轮询等待；后端抖动/不可用时（非 404 错误），这四处以固定 1-1.5s 间隔无限重试，直到任务终态/用户离开。writing 的正文生成任务可运行数十分钟，期间后端短暂不可用即造成持续无效打点；多视图叠加时与 F3-7 的共享轮询器同量级放大。无泄漏（generation/dispose 守卫齐备），纯请求量问题。
- **调用链证据**：读四处循环全文；确认全部仅在 `status===404` 或终态时退出，catch 分支一律 `await wait(...); continue`。
- **现有契约**：§5 异步任务兼容面——进度刷新语义、404 处理、取消语义全部保持；只改失败重试节奏。
- **最小方案**：把 deepImportController 的退避表提取为共享 helper（或直接改用带退避的 pollTaskProgress 回调形态），五处（含 F3-7 的 workflowProgress 本体）统一"连续失败 N 次后倍增、成功即复位"。
- **预期收益**：后端不可用期间无效请求量大幅下降；与 F3-7 合并为一个批次。
- **风险**：低。退避状态下恢复感知变慢（状态本就 unknown）；需保留 abort/取消路径即时性。
- **依赖**：F3-7（同一机制，建议同一批次实施）。
- **验证命令/断言**：`npm test -- tests/`（workflowProgress/writing controller 相关，fake timers 加退避断言）。
- **回滚**：单提交 revert。
- **裁定**：实施候选。
- **优先级建议**：P3

### D8a-6 A8-2 剩余手写 workflow manager 现状核实与工厂差距清单

- **ID**：D8a-6
- **位置/符号**：手写 manager 三处：`frontend-console/vue/views/scene/sceneAutoExtractManager.js`（202 行，直用 pollTaskProgress，项目单作用域）；`frontend-console/vue/views/scene/sceneRuntimeManager.js`（241 行，直用 pollTaskProgress，project+scene 双作用域 + stage 维度 + setResult）；`frontend-console/vue/views/outline/story/storyOutlineData.js:219-449`（storyOutlineTaskManager，含 `_taskMatches` 任务身份校验与 `lastTerminal` 终态重放）。另有三处 controller 级手写轮询（writingCommandController、conflictController、GenerateView waitForPovTask，见 D8a-5），不属历史清单但是同族。工厂：`frontend-console/vue/shared/workflowManager.js`（155 行，F3 已核）。
- **问题与触发**：工厂缺手写三处依赖的能力：(1) `cancel`（停轮询→tasks.cancel→失败恢复轮询，三处各自实现且语义一致）；(2) `dismiss`；(3) 动态单槽 terminal 订阅（`subscribeTerminal` 返回退订函数，工厂是构造期固定 `onTerminal`）；(4) scene 级作用域（工厂仅 ownerProjectId + matchesActiveScope 谓词）；(5) storyOutline 的任务身份校验（恢复的 task 必须 task_type/meta.action/meta.novel_id 全匹配，否则 `_rejectRecoveredTask` 停止并清收据——这是防"恢复错任务"的关键守卫）与 lastTerminal 重放（组件重挂载窗口内终态不丢）。直接收编会丢语义，历史候选"净删 ~250 行"按当前形态评估需先扩展工厂，实际净收益估计 300-400 行但实施风险中。
- **调用链证据**：三 manager 与工厂逐函数比对；sceneRuntimeManager.recover 的 sceneId 过滤、storyOutlineData.js:308-315 `_taskMatches`、`:236-246` setOnTerminal 重放。
- **现有契约**：§2 异步任务兼容面——恢复、取消、终态通知行为全部保持。
- **最小方案**：分两步——(a) 工厂扩展 `cancel/dismiss`（三处逐字同构，低风险）；(b) `ownerScope` 谓词参数 + `matchesRecoveredTask` 身份校验参数 + terminal 单槽订阅钩子，随后逐 manager 迁移（storyOutline 最后迁，重放语义需专门测试）。controller 级三处（D8a-5）是否收编单独裁定——它们是"等待单个请求完成"形态，与 manager 的"持续任务态"不同构，改造成 pollTaskProgress+退避即可，不必进工厂。
- **预期收益**：消除 6 份 poller 生命周期/恢复样板；取消语义单点化。
- **风险**：中。storyOutline 的身份校验与重放迁移需逐条保留，否则出现恢复错项目任务或终态丢失（作者感知为"生成结果消失"）。
- **依赖**：D8a-5（共享退避 helper 先行）。
- **验证命令/断言**：`npm test -- tests/vue/`；恢复/取消场景 vitest + e2e 冒烟（提交任务→刷新→恢复→取消）。
- **回滚**：逐 manager 迁移、可部分回滚。
- **裁定**：实施候选（P3；与历史 A8-2 结论一致，补充工厂差距清单作为实施前提）。
- **优先级建议**：P3

### D8a-7 输入热路径全文重算与小项汇总

- **ID**：D8a-7
- **位置/符号**：`frontend-console/vue/views/writing/useWritingWorkspace.js:235-248`（saveStatus computed 内 `substantiveWritingText(editorState.content)` 与 `substantiveWritingText(editorState.lastSavedContent)`——全文 `replace(/\s/gu,"")`，editorController.js:10）；`WritingView.vue:416-418`（statusWordCount/statusParagraphCount/statusReadMinutes 依赖 content，每渲染 tick 重算 split/filter）；对照已有 rAF 节流的 dispatchDashboardUpdate/refreshSceneAlerts（useWritingWorkspace.js:459-467）。附注小项（不单独立项）：(1) `outlineStructureOps.js:308` showCreateRevealForm 硬编码 `target_id: "00000000-0000-0000-0000-000000000000"` 零 UUID 占位，语义靠后端默认兜底，建议注释绑定或后端改 optional；(2) `WritingView.vue:4-20` 与 `:298-313` OwnerAiDrawer 两分支逐字重复 16 行 props 绑定；(3) ChapterTree 无虚拟滚动，千章级列表约数千 DOM 节点，现状可控，如未来出现卡顿再立项。
- **问题与触发**：30 万字级章节每次输入 tick（Vue 批处理后）触发约 4 次全文正则扫描（saveStatus×2、substantiveWritingText 在 autosave 判断处另有调用、段落计数×1）。单次 O(n) 正则约 1-2ms 量级，输入延迟影响待测；与 D8a-3 同属"输入路径重算"族但量级更小。收益待测。
- **调用链证据**：computed 依赖图：editorState.content 变更 → saveStatus/statusParagraphCount 失效 → 每次渲染重算。
- **现有契约**：§2 用户操作——保存状态文案与字数统计输出不变。
- **最小方案**：把 substantiveWritingText 比较改为脏标记下的增量字数（input 事件已知道插入/删除长度时可维护 stripped 长度近似）或至少把 saveStatus 的比较移入 250ms 节流路径（与 D8a-3 同法）。附注小项随批次顺手处理。
- **预期收益**：大文档输入路径 CPU 下降；收益待测（按计划不承诺百分比）。
- **风险**：低。
- **依赖**：无。
- **验证命令/断言**：`npm test -- tests/vue/`；性能取证按 `docs/diagnostics/performance.md` 隔离流程，代表性大小文档前后对比输入 tick 耗时。
- **回滚**：单提交 revert。
- **裁定**：补证据后实施（先测后改；附注小项可直接做）。
- **优先级建议**：P3

## 历史候选复核

- **A8-2（scene 三处手写 workflow manager → createWorkflowManager 工厂）——仍成立（范围与前提更新）**。F3 已核工厂机制成熟（155 行，已被 assistant/world/outline 三域使用）；本槽位核实三处手写现状全部在位：scene/sceneAutoExtractManager.js（202 行）、scene/sceneRuntimeManager.js（241 行，双作用域）、outline/story/storyOutlineData.js storyOutlineTaskManager（约 230 行，含任务身份校验与终态重放）。工厂能力差距（cancel/dismiss/动态订阅/作用域/身份校验）已列入 D8a-6 作为实施前提；storyOutline 的守卫语义迁移时必须逐条保留。另发现三处 controller 级手写轮询（writingCommand/conflict/pov）为同族扩展项，形态不同（单请求等待），建议以退避统一（D8a-5）而非进工厂。
- **A4-3（前端 isVersionActive helper 8 处）——仍成立（精确复核 8 处）**。useWritingWorkspace.js 6 处内联 + editorController.js activeVersion + VersionHistoryDialog.vue isActive，语义逐字一致，无漂移。见 D8a-2。
- **A8-9（历史剔除项 ~15 行微）——维持剔除（明细不可考）**。audit 原文仅记录"A8-9（~15 行微）"被 Reviewer 裁定剔除，无位置明细可查；本槽位全文审读未发现需要重启的对应微项。按"剔除维持"关闭。
- **audit 其余落在写作/大纲/生成视图的项**：(1) A8-4（api.js 契约迁移收尾）——F3-1 主责；本槽位交叉确认 generate/outline 视图调用的 `world.cocreation*`、`outline.*` 全部经 api.js 手写方法，视图侧无新增契约失配，无需在 D8a 重复立项。(2) A5-4（writing conflict 同步端点前端零调用）——视图侧反向核实成立：`frontend-console/api.js:2211-2235` writing 冲突面仅暴露 createConflictCheck/listConflictChecks/getConflictCheck/updateConflictItem/enqueueConflictAiReview/enqueueConflictAiSuggestion 六方法（前三后二走契约），全部异步队列或查询；视图层（useWritingWorkspace/conflictController）无同步 AI 调用点。D4 结论在视图侧确认。(3) A8-3（smartDedup split-brain）——D8a 侧挂载/派发点清点：OutlineView.vue:180（onMounted 派发 `workspace:content-rendered`）、OutlineHeader.vue:9（`data-role="smart-dedup-action"` 挂载点）、SceneWorkbenchView.vue:4（挂载点）与 :334（onMounted 派发），与 F3-4 清单一致，领域侧迁移时这三处 Vue 侧触点需同步改造。
- **A8-6（bulkSelection store 合并）——维持 F3 复核结论**。本槽位 outlineBulkSelection.js（84 行）即 F3 所述"outline 侧 ~20 行模板封装"，scopeBulkSelectionsToProject 是防污染语义非重复，不再立项。

## 共享事实（供 W3 链 8"编辑器→本地备份/服务端保存→离开/切章/刷新→冲突保留与恢复"使用）

### 1. writing 草稿/备份/恢复机制地图（三层 + 双指针）

- **存储层（writingSession.js，纯内存+localStorage 指针）**：模块级 `sessions` Map（project→session，上限 5 项目×5 章快照，LRU 触发 `trimProjects/trimChapters`；`dirty && !backupComplete` 的"不安全"快照永不被驱逐）。持久化指针 `writing_resume_pointer:v1:{projectId}`（localStorage，含 chapter/draftId/draftVersion/draftUpdatedAt/sceneId/cursorOffset/focusMode，`validPointer` 全字段校验）。快照含 lastSaved* 与 restore* 全套 CAS 字段。
- **备份层（editorController.js）**：localStorage `draft_backup_{projectId}_{chapter}_{draftId|new}`（encodeURIComponent），输入 250ms debounce 写（`LOCAL_PERSIST_DELAY`）；写失败 `backupComplete=false` 并在 saveStatus/错误卡/离开确认三处明示（AGENTS.md"本地备份不可用须明示"契约落地处）；legacy 键 `draft_backup_{p}_{c}` 首次恢复时迁移到新键并删除旧键。`state.backupComplete=null` 表示输入后未测定（不误报）。
- **服务端层（autosave/checkpoint/discard/publish）**：3s debounce autosave；`savePromise` 链式去重（在途时新调用 await 后按 dirty 递归一次）；CAS 用 `expected_version`+`expected_updated_at`；晚到响应守卫 = disposed+lifecycle+load 双代次+projectId+chapter+sourceDraftId 六条件，旧工作稿的保存结果不得覆盖新载入版本（editorController.js:463-473 注释明示）；"排版修改仅本地"分支（keepsLocalFormatting）服务端 published 覆盖后回放本地空白差异。
- **恢复顺序（loadChapter）**：`flushLocalPersistence` → API 取稿（draftId 直取或版本历史取最新 active）→ `novel_id` 不匹配 fail-closed → `restoreSession`（仅 overlay 同一 draftId 的会话快照；draftId 不一致直接拒绝，防止把 A 章草稿贴到 B 版本）→ 不命中再 `restoreBackup`（draftId 全等才恢复 + confirm 询问；内容与当前一致则不动）→ `restoreCursor`（pointer 的 draftId+draftVersion+draftUpdatedAt 三元全匹配才恢复光标）。`allowMissingPointerFallback` 处理指针指向已删稿：404→清指针→回退最新 active。
- **离开/刷新保护**：`useLeaveGuard`（未保存→persist→confirm，按 backupComplete 分文案）；`beforeunload`（未保存且非 readonly→persist+preventDefault）；`pagehide`（persist）；readonly 时不拦截（只读无新修改）。`dispose()` 先 persist 再失效全部代次。
- **切章保护**：`selectChapter` 切换前 `editor.autosave()`，保存失败（saveError）则中止切换（"保存成功前不会切换章节"）；每日字数 `novel_daily_wc_{date}_{projectId}`（novel_ 前缀，高水位算法，删字不倒退）。
- **入口恢复**：loadWritingProps 优先级 URL query > session 指针（带 allowBackupRestore）> viewStates；导入回执 `import_task_id` query 触发 deepImport.recover 并自动开审计。

### 2. 其他集群的草稿/恢复机制（链 8 对照面）

- **scene（sceneRuntimeSession.js）**：localStorage `scene_runtime_draft:v1:{project}:{scene}`（键名经 encodeURIComponent），256KB 上限逐级降级（清 scriptDrafts→清 simulation→清 preview→清 notes→截断主稿），按 scene 隔离恢复；backupComplete 语义与 writing 一致。剧本草稿上限 200000 字符（MAX_SCRIPT_LENGTH 双端截断）。
- **outline**：story-outline 手工编辑 `story-outline-editor-draft:{project}`（base_revision_id + stale 标记 + 409 conflict→rebase 流程）；AI 预览 `story-outline-preview-draft:{project}`（task 绑定 + idempotency_key + lastApplyFingerprint）；三个层级预览 `novel_outline_{thread|arc|scene}_preview:{project}:{taskId}`（conflict 标记持久化）；结构行内编辑 `novel_outline_{thread|arc}_edits:{account}:{project}`（主动账号分段，正确样本）。全部配 leaveGuard+beforeunload 双保护，冲突时不直接丢弃、要求同步最新版本后重试。
- **generate**：`generate_world_workspace_state_v2_{...}`（512KB 上限、5 项目 LRU 驱逐、超限逐级降级：裁对话至 40 条→压缩收束卡→放弃并明示）；**pending 气泡持久化即转为终态错误消息**（generateSession.js:302-307 注释：快照故意终态化，防刷新后作者消息看似未答或隐式重试）——这是"防重复提交"的关键设计；任务收据走 sessionStorage（receiptStorage），刷新同标签页可恢复，跨标签不重复恢复。`novel_creative_continuation_v1:{project}` 续写指针带 schema_version+destination 白名单校验。
- **未登记键**：见 D8a-1（scene_runtime_draft 等 6 前缀不在账号清理清单）。

### 3. 竞态防护现状（集群一致性盘点）

- **通用模式**：闭包 generation 计数 + `disposed` 标志 + `getAppState().currentProjectId` 实时校验三件套，全部集群一致（writing 5 个代次、scene useSceneWorkbench/useStorySceneWorkspace/sceneModalController 各自 generation、outline preview 页 projectId+taskId 绑定、today componentGeneration）。响应写入前统一 `ownsRequest()` 判定。
- **AbortController**：仅 generate 集群使用（requestOwner.js 的 begin/finish/invalidate，信号传入 api 调用）；writing/outline/scene 不传 signal，靠代次判丢弃（晚到响应仍消耗带宽但不落状态）。两模式并存且各自完备，收敛无紧迫性。
- **重入防护**：saving/submitting/busy 标志 + beginSubmission/endSubmission token（scene 双 manager、deepImport）；editorState.saving 期间禁发布/切换。
- **轮询器清单**：共享 pollTaskProgress——sceneAutoExtractManager、sceneRuntimeManager、storyOutlineTaskManager、sceneModalController.fusionPoller、GenerateView worldTaskPoller/turnTaskPoller；手写循环——writingCommand×2、conflictController、GenerateView.waitForPovTask；自建——deepImportController（有退避）。island onLeave 停线契约：outline island 包装停 6 条（含 scene 两 manager 与 storyOutline）；writing 组件卸载 dispose 全部 controller；GenerateView onBeforeUnmount 停两 poller+owner.dispose。
- **收据存储分层（现状记录，非缺陷）**：writing 正文/冲突任务用 sessionStorage（会话级恢复）；deepImport/scene/outline 工作流用 localStorage 默认（deepImportController 与 scene manager 调 persistActiveWorkflow/clearActiveWorkflow 均不传 storage 参数，落 localStorage；writingCommand/conflict 显式传 sessionStorage）。deep import 长任务跨会话恢复与正文任务仅本会话恢复是可解释的有意分层，但 shared/workflowProgress.js 默认参数是 localStorage，两个 controller 的显式传参差异值得在收编（D8a-6）时显式化为工厂参数，避免后续误传。
- **与手写 workflow manager 的生命周期（D8a-6 详表）**：三处手写 manager 均为"模块级单例 reactive state + poller 句柄 + beginSubmission 防重入 + recover 从 receipt 恢复 + subscribeTerminal 单槽订阅（返回退订）"。storyOutlineTaskManager 额外持有 lastTerminal 快照做重挂载窗口的终态重放，并校验恢复任务身份（task_type+meta.action+meta.novel_id）；sceneRuntimeManager 按 project+scene 双键 ownership；工厂 createWorkflowManager 具备 ownerProjectId+matchesActiveScope+skipRecover+prepare，缺 cancel/dismiss/订阅式 terminal/身份校验。

### 4. 其他交叉事实

- **F3 接缝的 D8a 侧写入点**：`appState._current*` 与 `viewStates.writing` 的唯一写入方是 useWritingWorkspace.syncLegacyState（:354-391）与 onBeforeUnmount（:1539-1550）；`#writing-editor` textarea 由 WritingEditor.vue 渲染、editorController.attach 接管。重构保持字段名与形状即可不破坏 bridge/assistantContext。
- **smartDedup 挂载点（F3-4 配套）**：OutlineHeader.vue:9、SceneWorkbenchView.vue:4 提供挂载点；OutlineView.vue:180、SceneWorkbenchView.vue:334 onMounted 派发 `workspace:content-rendered`。
- **conflict 前端调用面**：仅 create/list/get/update-item + 两个 enqueue（api.js:2211-2235），无同步 AI 端点调用（A5-4 视图侧复核成立）。
- **writing-desk.css**：纯视觉覆盖层（分节注释、313 顶层选择器、CSS 变量适配三主题），声明"只覆盖视觉；id/class/aria 测试钩子不变"，无逻辑发现。
- **ChapterTree/大纲表格均无虚拟滚动**：当前规模（章节树按钮行、outline 50/页分页、scene 20/页）下 DOM 量可控；outline/scene 已分页，writing 章节树是唯一不分页列表，千章级约数千节点，记录在案不立项。

## 受阻

无。补充两点移交（非受阻）：(1) `outlineStructureOps.js` 零 UUID target_id 的后端合法性归 D3a/D3b 核实（前端侧已记录）；(2) D8a-3/D8a-7 的性能收益按计划 §5 需实施前做隔离取证，本槽位未运行任何测试/构建/性能探针。
