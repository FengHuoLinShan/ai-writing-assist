# 前端过度设计审查报告

- 日期：2026-08-13
- 审查范围：`frontend-console/` 全部生产源码（约 8.5k 行 JS + 15.6k 行 CSS；含 `shared/`、`ui/`、`vue/`、`vue/views/`、`vue/components/`、`vue/composables/`）
- 排除范围：`dist/`、`node_modules/`、`prototypes/`、`tests/`、`e2e/`、playwright/vite/vitest 配置
- 方法：4 个并行审查 agent，分别从 Reuse / Simplification / Efficiency / Altitude 四角度审查；59 条原始发现，跨角度去重后约 32 个独立问题
- 结论：不找正确性 bug，只报告过度设计（重复、死代码、伪抽象、错层、效率浪费）
- 当前状态：仅审查存档，未实施修复

---

## 总体判断

前端架构本身合理（island + bridge + 单页壳）。过度设计集中在三处：

1. **CSS 复制粘贴**：`styles.css` 约 800-1000 行逐字重复（占全文件 3.6%+）
2. **安全/共享逻辑双实现**：脱敏、进度卡、分页、query 解析各有多份拷贝
3. **死状态与死通道**：state 8 个死字段、契约层半覆盖、两套死路由别名

修复总量预估可删 **1500-2000 行**，并显著降低样式与安全逻辑的漂移风险。

---

## 🔴 高优先级（漂移风险 / 性能 / 架构级）

### 1. styles.css 整段重复（约 800-1000 行）

- **位置**：styles.css:7918-8434 与 9260-9889
- **问题**：「Generate & RAG 视图 UI 一致性增补」517 行（7918-8434）是 9260-9889 同名段（630 行）的严格子集；全文件另有约 255 组「选择器+声明体」完全相同的规则对，集中在 7456-9259 与 9260-9889 两个重复带；9890-11371「world + map 统一组件」段内部还有约 35 条逐字重复规则；14072 与 14090 的 `.today-attention-grid` 同段 18 行内重复声明
- **成本**：删后一份即可减约 500-800 行；后续改样式必然「改了一处漏一处」漂移
- **建议**：删除 7918-8434 整段（后续段已含全部规则且级联顺序不变）；重复规则对去重为单一事实源

### 2. 凭据脱敏逻辑双实现（安全相关）

- **位置**：api.js:187-238 与 errorLogger.js:21-62
- **问题**：`_isSensitiveDiagnosticKey`/`_redactDiagnosticText`/`_redactDiagnosticValue` 与 `_isSensitiveLogKey`/`_redactLogValue` 是同一组函数的逐字重复（约 44 行 × 2），密钥清单与正则完全一致，仅命名不同
- **成本**：安全敏感逻辑双处演进必会分叉；新增 API Key 脱敏规则时改一处漏一处的漂移风险
- **建议**：抽到 `shared/redact.js` 单点维护，两处共同消费

### 3. 工作流管理器三套实现

- **位置**：vue/views/world/workflowManagers.js:27、vue/views/outline/ai/outlineWorkflowManagers.js:65、vue/views/scene/sceneAutoExtractManager.js
- **问题**：`createWorkflowManager`（2 个消费者）与 `createOutlineWorkflowManager`（3 个消费者）约 150 行 body 只差 `clearOnDone`/`useNovelId`/`matchesActiveScope`/`onScopeReset` 四个可参数化选项；scene 又以手写单例重复同一套 stop/resetMemory/beginSubmission/adopt/recover/startPolling 骨架（第 3 份）。6 个 manager 都只依赖 shared/workflowProgress.js 的 pollTaskProgress，却各自重写上层生命周期
- **建议**：工厂下沉到 shared/workflowProgress.js（紧挨 pollTaskProgress），三个文件各留 20 行配置

### 4. 「分页拉全量」循环复制 4 次 + listItems 归一化 3-4 份

- **位置**：vue/ragIsland.js:15-37（loadAllCharacters）、vue/todayIsland.js:60-87（loadPendingSuggestions）、vue/generateIsland.js:18-30（loadAll）、vue/generateIsland.js:72-85（findSuggestion）；listItems 定义于 vue/views/generate/logic/generateLogic.js:63、vue/todayIsland.js:15、vue/views/writing/useWritingWorkspace.js:982（内联）、ragIsland.js:25（内联）
- **问题**：`fetchPage(skip) → items.push → total 判停 → skip += page.length` 的 while 循环四处复制；`Array.isArray(v) ? v : v?.items || []` 归一化三处定义
- **成本**：约 80 行重复；且这些翻页链是下条「串行请求」的主因
- **建议**：shared 提供 `fetchAllPages(fetchPage, {pageSize, stopOnTotal, findId})` 与 `listItems`，四处各缩为 1-2 行调用

### 5. 视图入口串行请求

- **位置**：vue/worldIsland.js:171-204、vue/ragIsland.js:51-89、vue/generateIsland.js:137-163
- **问题**：
  - world 视图入口把 5 个互相独立的请求拆成 3 个串行波次；objects 子标签下又有第二个串行对（entities→batches）。每次进入视图或切换任意子标签都是 5-6 个 RTT 之和，子标签切换是高频操作
  - rag 视图入口把 status、evidenceHealth、全量人物翻页、scenes 四个独立请求组完全串行 await；大项目角色几百条时一次进入就是十几个串行 RTT
  - generate 视图先串行 await 模板/档案，再启动 8 请求并行批，其中含两轮全表逐页扫描
- **建议**：各入口独立请求合并为一个 Promise.all（generate 用 Promise.allSettled，模板/档案失败本就降级处理）；全量翻页先取首页后并行抓剩余页

### 6. 契约层半覆盖双轨

- **位置**：apiContracts.js（约 90 个方法走 contractFetch/contractJson）与 api.js（约 110 个方法用 request/withQuery 手拼路径）；apiContracts.js:396-416 的 6 个 map 契约定义零消费（api.js:1406-1458 用裸 request() 实现了同一批端点）
- **问题**：同一端点「契约表 + 裸实现」双轨各写一遍（如 world.listEntityTypes 与相邻的 listEntities 分属两套），契约的必填参数校验因此不统一；apiContracts.js:70-88 的 `timeoutKind` 字段贯穿约 35 处 define() 但全仓零读取
- **建议**：要么全部端点收编进契约（单一 URL 事实源），要么删除契约层把校验内联进 api.js；删掉 timeoutKind 字段

### 7. state 死字段 + createStateController 伪抽象

- **位置**：state.js:32-68、stateSlices.js:48-66
- **问题**：`mode`/`commandInput`/`rightPanel`/`toast`/`loading`/`cache`/`error`/`_toastTimer` 8 个字段生产代码零读取或只写（searchQuery 仅写后立即读）；`createStateController` 只有 state.js 一个消费者，把 applyStateSideEffects/notifyStateListeners/syncStateDom 三个函数包成同名对象，syncStateDom 还是逐参数透传（updateUIForState 已在闭包内还当参数传）；拆文件的唯一理由是「Vitest 导入副作用」
- **成本**：appState 近一半字段是死状态，每次 Proxy set 做无效通知与副作用分支
- **建议**：stateSlices 合并回 state.js（或只留 projectStorageSummary 一个真实共享函数）；删死字段

### 8. toast 三跳链路

- **位置**：ui/toast.js:64-66、state.js:127-136
- **问题**：toast() 经 `window.appState.toast` 写入 → Proxy set → updateUIForState → showToastNotification 三跳链路，而 state.toast 字段从无读取（两个消费方都收参数而非读字段）；state.error 分支死代码（state.error 全仓零写入）
- **建议**：toast() 直接调 showToastNotification；删 error 分支与 error 字段

---

## 🟡 中优先级（样板复制 / 死通道 / 效率）

### 9. island 注册样板复制 9-10 份

- **位置**：outlineIsland.js:94-98、interactionIsland.js:89-93、writingIsland.js:16-20、projectIsland.js:15-19、settingsIslands.js:74-78、ragIsland.js:95-99、todayIsland.js:201-205、mapIsland.js:15-19、worldIsland.js:329-333（另 generateIsland.js:217 用可选链静默跳过守卫，两种形态并存）
- **问题**：`const router = getRouter(); if (!router) { console.error(...); return }` + 自调用注册样板逐字复制
- **建议**：viewLoaders.js 提供 `registerIsland(viewName, {component, load})` 统一守卫+mountIsland+注册，island 变一行

### 10. 空态/错误页 DOM 构建手写 5 处

- **位置**：app.js:204-215、app.js:295-309、router.js:177-226、router.js:793-836、router.js:941-953
- **问题**：「div.empty-state + empty-icon + 标题 p + 说明 p(+actions)」的 createElement 拼装模式 5 处各写一遍
- **建议**：抽 `renderEmptyState(host, {icon, title, message, actions})` 共享 helper，省约 50 行

### 11. 工作流进度卡双套实现

- **位置**：shared/progressRenderer.js 与 vue/components/progressUtils.js
- **问题**：同一套「工作流进度卡」展示逻辑维护两套并行实现——progressRenderer.js 渲染 HTML 字符串（smartDedup.js 仍用），progressUtils.js 是 Vue 移植版；约 15 个函数两两对应，标签表已在漂移（progressUtils 多了 phase1c_scene_fusion/entity_extraction 等 key）
- **建议**：progressUtils 从 progressRenderer 提取共享纯逻辑（label/状态映射）或反之

### 12. shared/viewHelper.js 孤儿模块 + 骨架屏重复

- **位置**：shared/viewHelper.js（142 行）、router.js:151-175
- **问题**：viewHelper.js 全库 0 处引用（bindDelegation 等无任何 import，仅靠测试维持存活）；router.js 的 `_showRouteLoadingSkeleton` 用 createElement 重建了 viewHelper 的 `renderLoadingSkeleton()` 已生成的完全相同骨架屏
- **建议**：按 deletion test 标准删除 viewHelper.js（如确有测试依赖，把断言迁移到真实消费方），router 复用 renderLoadingSkeleton

### 13. llm/scene 死路由别名

- **位置**：router.js:22（routes.scene）、router.js:26（routes.llm）、settingsIslands.js:93-105
- **问题**：`_normalizeRoute` 在查 routes 表之前就把 scene/llm 重定向（router.js:343-348、364-369），settingsIslands 注册的 "llm" renderer 永远不会被渲染；真实调用方 RagSearchView.vue:304 navigate("scene") 走重定向通道
- **建议**：删 routes.scene/routes.llm 条目与 llm renderer，只留 normalize 重定向

### 14. island 卸载不释放 loadedProps（内存滞留）

- **位置**：vue/mountIsland.js:40-47、router.js:62-65
- **问题**：unmount() 只清 app/leaveGuard，不清 loadedProps；island 注册进 router 的 viewRenderers Map 后应用生命周期内不会移除，于是 rag 的全量人物数组、world 的 bible 页/实体全量、generate 的模板+角色表等最后一份 props 快照被长生命周期对象持有，直到整页刷新
- **建议**：unmount() 里把 loadedProps/loadedQuery 置 null；onRendered 的 query 漂移检测只需保留 loadedQuery

### 15. 死 API 成员

- **位置**：api.js:1054-1068（api.memory 三方法）、api.js:1731-1737（generate.validatePromptTemplate/previewPromptTemplate）、api.js:2082-2092（tasks.getStatus，11 处调用全走 get 别名）
- **建议**：删除约 25 行；get 与 getStatus 合并

### 16. `_setCache` 全表扫描（死工作量）

- **位置**：api.js:177-179
- **问题**：每个可缓存 GET 响应写缓存时 O(n) 遍历全部缓存项删除过期条目；该淘汰已被 `_getCached`（165-168）读取时惰性删除和容量 while 循环（182-184）双重覆盖，此扫描不改变任何行为
- **建议**：直接删掉该 for 循环，行为不变

### 17. errorLogger 启动路径全表扫描

- **位置**：errorLogger.js:239-251（调用点 512）
- **问题**：模块顶层初始化同步扫描全部 localStorage key 并逐个 JSON.parse+深脱敏+重序列化；项目多/日志多时阻塞启动
- **建议**：只扫描 `_errorLog:` 前缀键；延迟到 requestIdleCallback 或首次打开面板时执行

### 18. query 解析表达式内联复制 7 次

- **位置**：outlineIsland.js:44、worldIsland.js:101、generateIsland.js:93、vue/views/scene/sceneModel.js:84、vue/views/writing/useWritingWorkspace.js:56、vue/mountIsland.js:53、68
- **问题**：`new URLSearchParams(router?.getCurrentQuery?.()?.toString() || "")` 内联复制，还有 `|| ""` 与 `?? null` 两种变体；bridge/index.js 明确定义为「Vue 访问既有基建的唯一入口」却不提供该 helper
- **建议**：bridge 加 `getCurrentQueryParams()`

### 19. bridge getter 样板 10 份

- **位置**：vue/bridge/index.js:25-116
- **问题**：getApi/getRouter/getToast/getConfirm/getPrompt/getShowModalHtml/getConfirmAction/getCloseModal/getEsc/getErrorLog 都是同一句 `_overrides.x ?? globalThis.x` 模式逐字复制
- **建议**：抽 `getGlobal(name, fallback)` 工厂 + 导出别名，省约 40 行样板

### 20. buildQueryString 与 queryString 双份

- **位置**：api.js:508-516、apiContracts.js:31-39
- **问题**：同一个「过滤空值→encodeURIComponent 拼 ?a=b&c=d」函数逐字复制，且 api.js 已加载 apiContracts
- **建议**：删 api.js 里的副本，复用 apiContracts.queryString

### 21. `_projectStorageSummary` 双份 + 双保险回退

- **位置**：app.js:264-271、stateSlices.js:8-17
- **问题**：函数体逐字相同，且 app.js:281 写成 `globalThis.projectStorageSummary?.(parsed) || this._projectStorageSummary(parsed)` 双保险
- **建议**：删 app.js 私有副本直接使用全局（state.js:143 已挂载）

### 22. useShellState 镜像死键

- **位置**：vue/shell/composables/useShellState.js:4-6
- **问题**：SHELL_STATE_KEYS 镜像 mode/loading/selectedItem 三个键，但 shell 全层只写不读（CommandPalette 的 mode 是派生 computed，selectedItem 由 shellServices 直读全局）
- **建议**：删 3 个死键，useShellState 只剩 5 个真读键

---

## 🟢 低优先级（小清理）

- **useWorkflowPolling 单一消费者**：vue/composables/useWorkflowPolling.js 只有 1 个真实消费者（useRagWorkflow.js:28）；useWorldBible.js:6 注释声称使用它但实际直接调 pollTaskProgress——注释与代码脱节；可并入第 3 条的共享工厂
- **`:export`/`:save` 假命令**：commands.js:188-196 只弹 toast 无任何导出/保存行为，帮助文本却宣称可用；顺带 window.commands.register(199) 导出零外部消费者
- **renderCurrentView 零消费者**：router.js:1205 导出全仓零使用
- **editorial-theme.css 死选择器**：editorial-theme.css:888-891 `[data-workspace-view="scene"]` 规则死——scene 视图已并入 outline，workspace-view 标记永远不可能是 "scene"
- **CSS 设计 token 空壳**：styles.css:23-64 与 editorial-theme.css:74-77 的 11 个 token（--text-4xl/--leading-snug/--space-16/--space-24/--ease-in-out/--ease-spring/--dur-fast/--dur-slow/--dur-base/--line-default/--line-active）定义后零 var() 消费者，删掉避免后人误当规范
- **`_pruneFixedStartupErrors` 硬编码补丁**：errorLogger.js:209 把「bulkSelection.js does not provide an export named」这一条具体历史缺陷硬编码进通用日志器并动态 import 探测；应改为一次性迁移脚本或测试
- **api.js 内嵌模态框 UI**：api.js:47-93 `_requestAccessToken` 直接拼 modal HTML 并依赖 showModalHtml + MutationObserver 监听 overlay，传输层反向依赖 UI 层；应改为可注入的 token-prompt 回调
- **uploadImportFile 重复构造凭据头**：api.js:547-600 用裸 XHR 重复 request() 的 CSRF/Authorization/X-Requested-With 头构造（对比 api.js:346-354、388）；api.js:1807-1815 的 imports.upload 还因此重写了既有 uploadImportFile（少能力：无进度回调/401 处理）
- **globalSettingsCache 死机制**：state.js:68 + stateSlices.js:68-78 的跨标签 storage 失效监听器完整机制，字段除置 null 外从无读取——纯写空缓存，连同 installGlobalSettingsCacheStorageHandler/dispose 一起删
- **viewLoaders 为测试参数化**：viewLoaders.js:30-35 的两个可选参数只服务测试注入，生产唯一调用点 app.js:20 传默认值
- **worldIsland 同形参数构造器**：worldIsland.js:42-91 的 entityListParams/candidateListParams/reviewGroupParams 三个构造器同形，reviewGroupParams 已通用化，另两个可并入
- **formatDate 双份**：vue/views/outline/story/OutlineStoryTab.vue:332-338 与 storyOutlineData.js:165-171 逐字相同
- **相对时间双份**：vue/views/project/logic/projectFilter.js:80-96 与 vue/views/world/logic/worldEntityHelpers.js:128-155 各自实现「刚刚/x 分钟前/x 小时前/昨天/年月日」渲染，可抽参数化 helper
- **useWorldBible 守卫复制 6 处**：useWorldBible.js:303-343 六处 `editorHasUnsavedChanges() && !confirm(...)` 守卫仅文案不同
- **esc 三份实现**：全局 esc()（规范）、shared/progressRenderer.js:1-10 escapeHtml、shared/viewHelper.js:55-63 _escapeHtml（甚至不回退到 esc）；两处都直接调 globalThis.esc（esc.js 先于所有 module 加载，无时序风险）
- **toast 错误处理重复**：ui/modal.js:393-396 与 shared/viewHelper.js:39-42 逐字相同（err.message 兜底 + toast「操作失败」），共用 toastOperationError(err)
- **restoreSuggestion 串行翻两遍**：generateIsland.js:72-85 对 pending 和 rejected 两组建议各做一次逐页串行扫描，可并行

---

## 修复优先级建议（供后续排期）

**第一批（高收益低风险，各含回归验证）：**
1. 脱敏逻辑合并到 shared/redact.js（#2）
2. styles.css 重复段去重（#1）
3. toast 三跳链路改直调（#8）
4. 分页循环抽 shared 助手 + listItems（#4）
5. 视图入口并行化（#5）

**第二批（架构调整，需测试配合）：**
6. workflow manager 工厂下沉（#3）
7. state 死字段清理 + stateSlices 合并（#7）
8. 契约层二选一收口（#6）
9. island 注册样板统一（#9）

**第三批（死代码清理，随时可做）：**
10. 死 API 成员、死路由别名、孤儿模块、CSS token、假命令等（#12/#13/#15/#16/#17/#20/#21/#22 + 低优先级清单）
