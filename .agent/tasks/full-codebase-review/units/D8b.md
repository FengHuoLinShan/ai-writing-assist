# D8b 槽位审查报告（R12 前端页面：世界/地图/RAG/资料库视图集群）

日期：2026-09-11。审查者：D8b 子代理（只读）。基线：`main` HEAD `e7d0b8d5b` 工作树
（未提交 WIP：imports api/test、styles.css、任务记录，与本槽位 67 路径无交集）。
范围：slot-paths-W2.json `D8b` 全部 67 路径（world 46、map 7、rag 14），逐文件语义阅读
完成，无抽样。只读扩展核对：`shared/assetDisplayState.js`、`shared/smartDedup.js`、
`shared/bulkSelection.js`、`app.js`（smartDedup 桥接半边）、`api.js`（契约方法归属）、
`backend/modules/world/services/worldbuilding/world_validation_service.py`（accept-warnings
契约反验）、`backend/modules/world/api.py`（上传边界）。未运行测试/构建/make/npm，
无网络，未读密钥。

## 覆盖行

```csv
frontend-console/vue/views/world/WorldView.vue,已审,island world 路由根组件（worldIsland 加载；Tab 分派+URL 导航）,无发现（onMounted 派发 workspace:content-rendered 属 F3-4 smartDedup 桥接契约；URL 为筛选事实源）
frontend-console/vue/views/world/worldSession.js,已审,WorldView 及全部 world 子组件的会话单例（reactive 模块）,无发现（reconcileWorldEntry 完整进入/query-only 区分；跨项目清 bible 会话正确）
frontend-console/vue/views/world/workflowManagers.js,已审,WorldObjectsTab/WorldReviewTab 经 autoExtractManager/fusionManager 消费,无发现（已用 createWorkflowManager 工厂；A8-2 world 面已收编）
frontend-console/vue/views/world/logic/worldQuery.js,已审,worldIsland load() 解码与各 tab 编码（URL↔filters 纯函数）,无发现（legacy status→display_state 映射单点；queryPageSkip/filtersEqual 与 vanilla 对齐）
frontend-console/vue/views/world/logic/worldBulkSelection.js,已审,WorldBulkToolbar/WorldSelectionInput/各 tab 复用,无发现（56 行薄封装复用 shared/bulkSelection；A8-6 复核一致）
frontend-console/vue/views/world/logic/worldTypeCatalog.js,已审,审查/关系/别名表单的类型分类目录（fallback+catalog 合并）,无发现（esc 由调用方注入，option 值均转义）
frontend-console/vue/views/world/logic/worldEntityHelpers.js,已审,objects/review/relations+aliases tabs 与 worldEntityOps 共用纯函数,A4-4 相关：isAliasTargetEntity/isMergeTargetEntity/suggestionId 用 raw status 属写资格判定（有意语义，非展示词汇），见共享事实；无缺陷
frontend-console/vue/views/world/logic/worldEntityOps.js,已审,实体/候选全部模态操作（新建/编辑/删除/采用/合并/回滚/知识/融合/批量）,D8b-1 相关（registry seam 设计合理）；showEntityCreateForm 409 相似对象二次确认链完整
frontend-console/vue/views/world/logic/worldRelationsAliasesOps.js,已审,关系/别名创建/删除/批量/编辑模态 + canonical 列表 inline 证据,D8b-1/D8b-2/D8b-6/D8b-7
frontend-console/vue/views/world/logic/useWorldReview.js,已审,WorldReviewTab 三队列逻辑层（分组/证据/草稿/批量复核/导航）,D8b-1/D8b-6/D8b-7；execution_fingerprint 草稿失效与 stale 拒绝链完整
frontend-console/vue/views/world/bible/WorldBibleTab.vue,已审,bible tab 根组件（gallery/editor/filter/graph 四模式+资料库浏览+决策模态宿主）,D8b-9（观察：模板重复调用 worldAssetDisplay/typeMeta，收益待测）
frontend-console/vue/views/world/bible/useWorldBible.js,已审,bible 全部状态与操作（编辑器基线/自动保存/本机备份/发布/投影/简介/建议/冲突/分类/模板/历史）,D8b-4/D8b-5/D8b-10；所有权守卫（ownsProject/ownsPage/ownsEditor/ownsModalOwner+generation）核实完备
frontend-console/vue/views/world/bible/WorldHealthPanel.vue,已审,世界健康校验面板（run/policy/findings 分页/签收/查漏）,无发现（acceptWarnings 的 finding_ids 与后端 set 相等契约核实吻合：run 响应 findings 为全量未分页数组，前端全量过滤 warning 提交）
frontend-console/vue/views/world/bible/WorldbookImportPanel.vue,已审,世界书目录导入（选择/预览/应用）,无发现（2MiB/25MiB/2000 文件前端预检与后端一致；generation 守卫完备）
frontend-console/vue/views/world/bible/worldCards.js,已审,资料卡读模型（filters↔query 编解码、客户端/服务端双路建卡）,无发现（cardState 归 worldAssetDisplay，draft 优先；q 过滤对 entity 行跳过有注释与依据）
frontend-console/vue/views/world/components/WorldObjectsTab.vue,已审,world/objects 对象库 tab（筛选/热点/批次分组/分页）,无发现（filterForm 草稿经 routeSignature 恢复，未应用条件跨重挂载保留）
frontend-console/vue/views/world/components/WorldEntityCollection.vue,已审,对象表格/卡片集合（缩略图加载/图片上传/批量/行菜单）,D8b-3（worldAssetDisplay 归一化变体之一）；图片链与 D2b 契约核对一致（PNG/JPEG、6MiB、XHR、AbortController）
frontend-console/vue/views/world/components/WorldRelationsTab.vue,已审,canonical 关系列表（搜索/批量/分页/证据展示）,D8b-3（归一化变体之二）
frontend-console/vue/views/world/components/WorldAliasesTab.vue,已审,canonical 别名列表（分组 rowspan/批量/分页）,D8b-3（归一化变体之三，语义有意的 needs_review→待处理）
frontend-console/vue/views/world/components/WorldBulkToolbar.vue,已审,批量工具条（选择计数/动作按钮）,无发现（count 读 reactive Set.size 正确订阅）
frontend-console/vue/views/world/components/WorldCandidateActions.vue,已审,候选行内动作（可见性由 candidateActionVisibility 决定）,无发现
frontend-console/vue/views/world/components/WorldCandidateGroupItem.vue,已审,候选分组条目（相似名分组/定向别名组）,无发现
frontend-console/vue/views/world/components/WorldEntityImage.vue,已审,实体详情页图片上传/加载,无发现（6MiB+PNG/JPEG 前端预检与后端一致；generation+abort 守卫完备）
frontend-console/vue/views/world/components/WorldEvidenceSummary.vue,已审,复核证据摘要块（原文回读/诊断复制）,无发现（readEvidence 409/404 文案区分；missingAliasEvidence 判定防置信度替代证据）
frontend-console/vue/views/world/components/WorldFilterPanel.vue,已审,筛选面板外壳（开合状态持久化）,无发现
frontend-console/vue/views/world/components/WorldInlineEvidence.vue,已审,行内证据键值对+诊断分离,无发现
frontend-console/vue/views/world/components/WorldPager.vue,已审,分页条（单页只显示总数）,无发现
frontend-console/vue/views/world/components/WorldReviewBatch.vue,已审,就地批量核对（别名归属/关系方向逐行准备）,无发现（fingerprint 失效重建 rows；搜索结果 status 三值过滤与后端一致）
frontend-console/vue/views/world/components/WorldReviewFilterChips.vue,已审,已激活筛选 chips（点击移除=navigate 写 query）,无发现
frontend-console/vue/views/world/components/WorldReviewTab.vue,已审,待处理资料三队列 UI（候选/别名/关系 + 决策区 + URL review_item 同步）,无发现（乐观镜像+快照恢复、依赖 blocker 预检、焦点管理核实完备）
frontend-console/vue/views/world/components/WorldSelectionInput.vue,已审,批量选择复选框（one/all 模式）,无发现
frontend-console/vue/views/world/components/WorldSidebarToolCard.vue,已审,侧栏工具卡（smartDedup 挂载点提供方）,F3-4（挂载点 [data-role=smart-dedup-action]；A8-3 前端挂载半边）
frontend-console/vue/views/world/components/WorldToolDialog.vue,已审,资料工具对话框（useModalDialog 焦点管理）,无发现
frontend-console/vue/views/world/library/WorldEntityDetail.vue,已审,实体详情（就地编辑+409 冲突对照/人物档案/关系/历史/图片）,无发现（basicConflict 采用服务器版/保留本地两路径均可恢复保存）
frontend-console/vue/views/world/library/WorldLibraryCards.vue,已审,资料卡网格视图,无发现
frontend-console/vue/views/world/library/WorldLibraryDirectory.vue,已审,资料目录（主题树/类型/收藏/未归类导航）,无发现（mql 监听未 detach，组件卸载随 island 卸载，无泄漏窗口）
frontend-console/vue/views/world/library/WorldLibraryHome.vue,已审,资料库首页（继续编辑/最近/收藏/主题/类型）,D8b-8（toCards 恒等 map）
frontend-console/vue/views/world/library/WorldLibraryList.vue,已审,资料列表视图,无发现
frontend-console/vue/views/world/library/WorldLibraryTypeGrid.vue,已审,常用类型卡网格,无发现
frontend-console/vue/views/world/library/WorldPageReader.vue,已审,资料页阅读态（TOC/分区折叠/wiki 引用解析）,无发现（openWikiReference 精确同名匹配+多候选消歧模态）
frontend-console/vue/views/world/library/WorldQuickOpen.vue,已审,快速打开资料（shell:quickopen-request 宿主）,D8b-8（KIND_LABELS_STATE 与 worldCards 重复）
frontend-console/vue/views/world/library/WorldTopicPickerDialog.vue,已审,加入主题对话框,无发现
frontend-console/vue/views/world/pages/WorldBibleKnowledgeGraph.vue,已审,关联图（SVG 辅助+键盘可达列表+关系依据）,无发现（generation+owner 守卫；节点 40/边 80 截断有明示）
frontend-console/vue/views/world/pages/worldBiblePageEditor.js,已审,编辑器 payload 纯函数（源键/规范化/引用解析）,无发现
frontend-console/vue/views/world/pages/worldBiblePresentation.js,已审,分类预设/页面类型元数据/关联图确定性布局,无发现
frontend-console/vue/views/world/pages/worldBiblePublishing.js,已审,发布影响预演/检查回执 HTML（esc 注入）,无发现（全部插值经 esc；omission 语义如实标注）
frontend-console/vue/views/map/MapWorkspaceView.vue,已审,地图工作区根（层级树/候选审查/生图 run/上传/画面说明检查/标注拖拽）,无发现（与 D2b 逐点核对：上传 <50MB 严格、prompt/page/annotation expected_updated_at CAS、retry_requires_confirmation 双确认、error_code→中文映射全覆盖）
frontend-console/vue/views/map/MapStructureEditor.vue,已审,空间地图编辑器（画布/撤销重做/本机备份/冲突/候选采用/底图校准/阅读预览）,无发现（与 D2b CAS 契约吻合：save 带 base_revision_id→409→conflict 面板；观察：save() 冲突识别的 `/更新|版本|409/` 消息正则回退可能对含"版本"的非 409 错误误亮冲突横幅，兜底路径安全不立项）
frontend-console/vue/views/map/mapStructureEditor.js,已审,地图纯逻辑（diff/来源引用校验/路线排演/几何签名）,无发现（mapSourceRangeKey 严格校验 source_ref 完整性；mapChangeDetails 只读服务端文档不构建采用 payload，注释声明与实现一致）
frontend-console/vue/views/map/MapSourcePicker.vue,已审,正文依据选择（searchEvidence→readEvidence 预览→回传 source_range）,无发现（回读后 source_ref 指纹复验不等即 409 文案，与 D2b"来源 digest 重验"吻合；上限 8 条双侧校验）
frontend-console/vue/views/map/MapBindAcrossMaps.vue,已审,跨地图地点关联（逐图 CAS 保存）,无发现（base_revision_id 逐张保存+epoch 守卫；替换原关联有明示）
frontend-console/vue/views/map/MapChangeReview.vue,已审,候选差异列表（勾选采用/定位）,无发现
frontend-console/vue/views/map/MapRehearsalPanel.vue,已审,路线排演面板（只看明确道路）,无发现
frontend-console/vue/views/rag/RagView.vue,已审,rag 路由根（search/status 分支+状态预取应用+预热结果回写）,无发现
frontend-console/vue/views/rag/RagSearchView.vue,已审,检索子视图编排（表单/提交/路由恢复/问世界/引用打开/保存建议）,无发现（URL 为检索条件事实源；lastExecutedRouteSignature 防往返重搜；confirmAiReference+AbortController 全链守卫）
frontend-console/vue/views/rag/components/RagEvidenceDrawer.vue,已审,证据抽屉 UI（原文/对象/追踪三态）,无发现（纯插值渲染无 v-html）
frontend-console/vue/views/rag/components/RagResultList.vue,已审,检索结果列表（高亮/渐进加载/降级警告/空态）,无发现（highlightParts 三段 <mark> 遵守 v-html 禁令；观察：每 hit 调 3 次 highlightParts，量级可忽略）
frontend-console/vue/views/rag/components/RagSearchPanel.vue,已审,检索面板（表单+高级筛选+字面锁定范围）,无发现（字面搜索强制 manuscript+关 includePending 与后端语义一致）
frontend-console/vue/views/rag/components/RagStatusPanel.vue,已审,索引维护页（重建表单/进度/质量/诊断/最近片段）,无发现（authorStatusText 把内部告警词翻译为作者语言，诊断收敛在 details 内）
frontend-console/vue/views/rag/logic/routeState.js,已审,URL query↔检索状态纯函数,无发现（枚举白名单解析；scope 多值去重）
frontend-console/vue/views/rag/logic/searchPayload.js,已审,payload 构造/结果归一/高亮/文案纯函数,无发现（visibility 截止校验失败 fail-closed；normalizeEvidenceHit 对旧字段形态归一）
frontend-console/vue/views/rag/logic/statusView.js,已审,状态页展示纯函数,无发现（chunkStatusLabel 双词汇 succeeded/done、pending/pending_vectorization 归一属后端历史状态兼容映射）
frontend-console/vue/views/rag/prewarmManager.js,已审,按项目一次性预热（模块级管理）,无发现（项目键控去重+abort 旧项目；HTTP 成功即回写含非 ready）
frontend-console/vue/views/rag/ragSearchSession.js,已审,rag 会话单例（结果/表单草稿/重建进度/预热）,无发现（scopeRagSessionToProject 项目切换全清理）
frontend-console/vue/views/rag/useEvidenceDrawer.js,已审,证据抽屉编排（readEvidence/inspectEvidence/traceEvidence+跳转）,无发现（abort+generation+projectId 三重门禁；navigateChapterRef 写 viewStates.writing 后导航与 F3 接缝契约一致）
frontend-console/vue/views/rag/useRagSearch.js,已审,检索执行 composable（字面/智能分路+三重门禁）,无发现（grepEvidence 参数拆解保持 visibility/chapter 语义；bge_onnx 未就绪提示有 metrics 预检）
frontend-console/vue/views/rag/useRagWorkflow.js,已审,索引工作流 composable（重建/重试/恢复+轮询）,无发现（创建写请求不随视图取消避免丢 task_id；begin/endSubmission 防重入）
```

67/67 覆盖，全部"已审"；无按生成源验证、不适用、受阻项。

## 发现

汇总：P0=0，P1=0，P2=1，P3=9（其中 2 条为"记录观察/不立项"性质，字段内裁定注明）。

### D8b-1 同名双实现 + 生产零引用的 review 操作死代码簇（~280 行）

- **ID**：D8b-1
- **位置/符号**：`frontend-console/vue/views/world/logic/useWorldReview.js:631-709`（`showAliasReviewEditForm`）、`:725-820`（`showRelationReviewEditForm`）及私有 `:823-840`（`relationEntityOptionsHtml`，仅被后者使用）；`frontend-console/vue/views/world/logic/worldRelationsAliasesOps.js:469-569`（`markRelationReviewed`/`markRelationUnreviewed`/`markAliasReviewed`/`markAliasUnreviewed`）
- **问题与触发**：五组导出在生产代码零消费者，仅各自单测引用（`tests/vue/world/useWorldReview.test.js:33`、`tests/vue/world/worldRelationsAliasesOps.test.js:11-12`）。其中 `showRelationReviewEditForm` 存在两份同名实现：worldRelationsAliasesOps 版（referencePicker 挂载，被 `WorldRelationsTab.vue:124` 与 `WorldEntityDetail.vue:6` 生产消费）与 useWorldReview 版（registry 纯 `<select>`，仅测试），二者已实质漂移——生产走 picker 版，测试锁定的是 select 版，测试对生产行为的保障为假。`aliasKey` 同名双份进一步加剧混淆（见 D8b-7）。历史来源是 vanilla→Vue 迁移期间的备份式保留。
- **调用链证据**：`rg "showAliasReviewEditForm|markRelationReviewed|markRelationUnreviewed|markAliasUnreviewed|markAliasReviewed" --glob '!node_modules'` 仅命中两个 logic 定义文件与两个测试文件；`rg "showRelationReviewEditForm"` 生产命中均在 WorldRelationsTab/WorldEntityDetail 且 import 自 worldRelationsAliasesOps。
- **现有契约**：无外部消费者（模块内部导出）；删除属内部清理，不触及 §2 任何兼容面。
- **最小方案**：删除 useWorldReview.js 的 `showAliasReviewEditForm`、`showRelationReviewEditForm`、`relationEntityOptionsHtml`（连带 `getCloseModal`、`reviewEvidenceSummary` 中仅被死代码使用的导入逐项核对）与 worldRelationsAliasesOps.js 的 4 个 `mark*Reviewed/Unreviewed`；同步删改两个测试文件对应 describe 块（迁移不得删有效断言——这些断言锁定的实现已死，应随实现一并删除并保留活跃实现的断言）；在 `showAliasReviewEditForm` 位置保留一行注释说明生产入口为 useWorldReview 的决策区 + worldRelationsAliasesOps 的 picker 版。
- **预期收益**：消除 ~280 行双实现漂移源；测试套件不再为死路径付费；后续 review 表单改动不会改错文件。
- **风险**：低；若存在仓外脚本按符号 import（无证据），grep 已限定仓内。
- **依赖**：无。
- **验证命令/断言**：`cd frontend-console && rg -n "showAliasReviewEditForm|relationEntityOptionsHtml|markRelationReviewed|markAliasReviewed" -g '!node_modules'` 零命中；`npm test -- tests/vue/world/useWorldReview.test.js tests/vue/world/worldRelationsAliasesOps.test.js`；`npm run lint && npm run build`。
- **回滚**：单提交 revert。
- **裁定**：实施候选（零引用候选按 §4 经全仓 grep 证实，非删除证据推定）。
- **优先级建议**：P2

### D8b-2 新建关系/别名下拉向作者暴露内部状态枚举原文

- **ID**：D8b-2
- **位置/符号**：`frontend-console/vue/views/world/logic/worldRelationsAliasesOps.js:106-109`（`fetchEntityOptionsHtml` 的 option 文案 `${esc(item.name || "未命名对象")} · ${esc(item.entity_type || "-")} · ${esc(item.status || "-")}`）
- **问题与触发**：作者打开"新建关系"或"新建别名"模态时，对象下拉选项显示 `名称 · 类型 · canonical` / `draft` / `candidate` 等英文原始状态值。违反 AGENTS.md 产品边界（不暴露内部枚举；状态词汇应走 `worldAssetDisplay` 的 已采用/待处理/历史 映射）。该列表已经 `["canonical","draft","candidate"].includes(item.status)` 过滤，status 必然存在，原文必然可见。
- **调用链证据**：`showRelationCreateForm`（:126）与 `showAliasCreateForm`（:219）均经 `entitySelectHtml`→`fetchEntityOptionsHtml` 渲染；`shared/assetDisplayState.js` 已有现成映射（`worldAssetDisplay({status}).label`：canonical→已采用、draft/candidate→待处理）。
- **现有契约**：展示文案变更不影响 API/持久化；选项 value（实体 id）不变。
- **最小方案**：option 文案第三段改为 `worldAssetDisplay(item).label`（import 自 `shared/assetDisplayState.js`），或最少映射 `{canonical:"已采用", draft:"待处理", candidate:"待处理"}`。
- **预期收益**：作者界面不再出现内部枚举；与同模态其它位置的中文状态一致。
- **风险**：极低（纯文案）。
- **依赖**：无。
- **验证命令/断言**：`npm test -- tests/vue/world/worldRelationsAliasesOps.test.js`；手动断言新建关系/别名下拉无英文状态词。
- **回滚**：单提交 revert。
- **裁定**：实施候选（顺手改）。
- **优先级建议**：P3

### D8b-3 worldAssetDisplay 调用侧归一化三份散落变体（A4-4 前端散落点实证清单）

- **ID**：D8b-3
- **位置/符号**：`WorldEntityCollection.vue:327`（`worldAssetDisplay({ ...entity, status: entity.status || "canonical" })`）、`WorldRelationsTab.vue:192-199`（同型 ×2，函数内各调一次）、`WorldAliasesTab.vue:225-237`（第三变体：`a.status === "candidate" || a.needs_review ? "candidate" : (a.status || (a.display_state ? undefined : "canonical"))`）
- **问题与触发**：同一"调用 worldAssetDisplay 前如何补默认 status"的问题在三个组件内三种写法。实体/关系版把缺失 status 当 canonical（列表数据本身来自 active 查询，兜底合理）；别名版额外把 `needs_review` 提升为"待处理"并尊重已存在的 display_state——这是有意语义（canonical 别名可带 needs_review 标记，须显示待处理），不能与另外两版盲目合并。当前无行为缺陷；风险是后续在任一处修改兜底时其余两处漂移，以及每处都在渲染路径内做对象展开+完整 display 计算（含 attentionReasons）。
- **调用链证据**：`rg "worldAssetDisplay\(\{" vue/views/world` 命中上述三处；无第四处同型（useWorldBible.statusLabel 是另一种单字段调用，属展示标签用途）。
- **现有契约**：三种现状展示行为必须逐一保持（含别名 needs_review 优先级）。
- **最小方案**：在 `shared/assetDisplayState.js`（A4-4 指定归宿）旁新增两个薄封装：`worldEntityDisplay(entity)`（status||canonical 兜底，返回 display）与 `worldAliasDisplay(alias)`（candidate/needs_review→candidate 变体），三处组件改调用；不新增自建映射、不合并两种语义。顺带清理 `WorldBibleTab.vue:1688/1694` 搜索结果里恒为 false 的 `unavailable: item?.status !== "canonical"`（上游已过滤 canonical）。
- **预期收益**：displayState 兜底语义单点定义；A4-4"渐进归入 worldAssetDisplay"在视图侧落点闭合。
- **风险**：低；别名变体若被误合并会改变待处理标记展示——以两封装分开命名规避。
- **依赖**：无。
- **验证命令/断言**：`npm test -- tests/vue/world`；手动断言：别名列表中 needs_review 的 canonical 别名仍显示"待处理"。
- **回滚**：单提交 revert。
- **裁定**：实施候选。
- **优先级建议**：P3

### D8b-4 useWorldBible.inspectCurrentPage 冗余双重三元（两分支恒等）

- **ID**：D8b-4
- **位置/符号**：`frontend-console/vue/views/world/bible/useWorldBible.js:2165-2170`
- **问题与触发**：`const draft = activeDraft.value?.page_id === page.id ? activeDraft.value : activeDraft.value?.page_id === page.id ? activeDraft.value : null` —— 外层真/假分支的内层条件与外层完全相同，内层三元恒等于外层真分支；净效果就是 `page_id 匹配 ? activeDraft : null`。迁移残留死分支，读者需心算两层条件才能确认无行为差异。
- **调用链证据**：直接读码；`inspectCurrentPage` 为唯一消费者。
- **现有契约**：行为恒等（page 匹配时用当前工作稿决定 pinned_refs/selected_world_bible_draft_ids）。
- **最小方案**：改写为 `const draft = activeDraft.value?.page_id === page.id ? activeDraft.value : null`。
- **预期收益**：可读性；消除"两分支看似不同"的误读风险。
- **风险**：无（行为恒等）。
- **依赖**：无。
- **验证命令/断言**：`npm test -- tests/vue/world`（useWorldBible 相关）。
- **回滚**：单提交 revert。
- **裁定**：实施候选（顺手改）。
- **优先级建议**：P3

### D8b-5 bible 编辑器 DOM payload 六字段构造三份内联重复

- **ID**：D8b-5
- **位置/符号**：`frontend-console/vue/views/world/bible/useWorldBible.js:531-537`（`editorHasUnsavedChanges`）、`:612-618`（`savePage`）、`:895-906`（`readEditorPayloadFromDom`）
- **问题与触发**：`{title: getElementById("bible-title")…, page_type: …, free_text: …, sort_order: Number(…), linked_asset_refs_json: parseAssetRefs(…), sections_json: readSectionsFromDom()}` 六字段 DOM 读取块逐字重复三份。新增编辑字段（如页面级新属性）需同步三处，漏一处即"保存成功但基线判定不一致"类缺陷。
- **调用链证据**：三段逐行比对字段与取值方式一致；差异仅错误语义（`readEditorPayloadFromDom` 非 lenient 时对空标题 throw，`savePage` 需 toast、`editorHasUnsavedChanges` 在异常时保守返回 true）。
- **现有契约**：三处输入/输出形态必须一致；空标题时 savePage 显示 warning、unsaved 判定保守 true、自动保存跳过（注释声明"标题为空的中间状态不自动保存"）。
- **最小方案**：`savePage` 改为 `try { payload = readEditorPayloadFromDom() } catch { toast("标题不能为空","warning"); return false }`；`editorHasUnsavedChanges` 的 DOM 分支改用 `readEditorPayloadFromDom({ lenient: true })`（外层 try/catch 语义不变）。
- **预期收益**：编辑器字段单点维护；三处读取永不漂移。
- **风险**：低；`savePage` 原实现对 `parseAssetRefs`/`readSectionsFromDom` 的异常未捕获（会走外层 catch 显示"保存失败"），改造后这两类异常 message 会以 warning 呈现——如需完全保持，可在 helper 内保留原 throw、savePage catch 只对标题空文案特判。按最小 diff 实施时以现有测试锚定。
- **依赖**：无。
- **验证命令/断言**：`npm test -- tests/vue/world`（bible 编辑器/自动保存用例）；手动断言空标题保存提示与现状一致。
- **回滚**：单提交 revert。
- **裁定**：实施候选。
- **优先级建议**：P3

### D8b-6 world 视图操作作用域/modal 所有权助手双份逐字重复

- **ID**：D8b-6
- **位置/符号**：`worldEntityOps.js:248-266`（`captureWorldOperationScope`/`ownsWorldOperationScope`）与 `worldRelationsAliasesOps.js:42-60`（逐字相同 ~20 行）；`worldRelationsAliasesOps.js:62-77`（`captureModalOwner`/`ownsModalOwner` 简版）与 `useWorldBible.js:196-218`（富版含 `owner.open` 与 node.isConnected 细化）；另 `useWorldReview.js:862-917/1155-1205` 内联第三种 `{projectId, view[, subView]}` owner 检查变体
- **问题与触发**：同一"异步回写前校验仍在原项目/视图"的不变量三套实现。简版 `ownsModalOwner` 不检查 `owner.open`，语义与富版有差（模态已关时简版仍要求 node isConnected 且 overlay 未隐藏——恰好等价失败，故行为殊途同归，但维护者无法确认这是设计还是巧合）。
- **调用链证据**：两文件读码比对；`useWorldReview.acceptAliasReviewDecision`/`applyAliasReviewBatch` 的 `ownsRequest` 为第三种写法。
- **现有契约**：守卫语义必须保持（尤其富版对 `owner.open=false` 的分支）。
- **最小方案**：把 `captureWorldOperationScope`/`ownsWorldOperationScope`/`captureModalOwner`/`ownsModalOwner` 收敛到 world logic 下单文件（如 `worldScopeGuards.js`），三处 import；富版为权威实现，简版消费方（worldRelationsAliasesOps）核实其调用点模态均为打开态后切换富版。`useWorldReview` 的内联 owner 属批处理专用形状，可保留但注释指向共享助手。
- **预期收益**：所有权不变量单点；消除"两份 ownsModalOwner 语义是否一致"的审计成本。
- **风险**：低；纯移动+一处简版→富版的行为核实。
- **依赖**：无。
- **验证命令/断言**：`npm test -- tests/vue/world/`；手动回归：新建别名模态中切换项目后保存不落库。
- **回滚**：单提交 revert。
- **裁定**：实施候选。
- **优先级建议**：P3

### D8b-7 aliasKey 双份逐字重复 + inlineRelationEvidencePairs 双份实现漂移（含死代码）

- **ID**：D8b-7
- **位置/符号**：`worldRelationsAliasesOps.js:459-462` 与 `useWorldReview.js:85-88`（`aliasKey` 逐字相同）；`worldRelationsAliasesOps.js:441-454` 与 `useWorldReview.js:336-362`（`inlineRelationEvidencePairs` 两份不同实现）；`useWorldReview.js:342-343`（`const sceneLabel = […].filter(Boolean).join("（")` 单元素数组 join + `const normalizedSceneLabel = sceneLabel` 恒等赋值）
- **问题与触发**：aliasKey 是批量选择/草稿键的事实源，两份实现当前一致，但任何一侧改动（如加 entity 版本）即造成 review 队列与 canonical 列表选中态分裂。两份 `inlineRelationEvidencePairs` 名称相同、产出不同（review 版多"证据"字段、来源标签用 `reviewSourceLabel` 而 ops 版内联三元），同名异义是漂移温床；`join("（")` 与恒等赋值是残留死代码。
- **调用链证据**：`aliasKey` 消费方：WorldAliasesTab←ops 版、WorldReviewTab/WorldReviewBatch←useWorldReview 版；`inlineRelationEvidencePairs`：WorldRelationsTab←ops 版（re-export 消费）、useWorldReview 内部不再使用 review 版? —— review 版仅被自身文件 `showRelationReviewEditForm`（D8b-1 死代码）引用，随 D8b-1 删除后 ops 版即唯一实现。
- **现有契约**：键格式 `entity_id::alias` 与证据键值对渲染不变。
- **最小方案**：aliasKey 收敛单点（建议留 useWorldReview 或移 worldEntityHelpers，ops 版 re-export）；`inlineRelationEvidencePairs` 随 D8b-1 删除 review 版；删除 `join("（")`/`normalizedSceneLabel` 死代码。
- **预期收益**：选中态/草稿键单点；同名异义消除。
- **风险**：低（有 D8b-1 前置时几乎为零）。
- **依赖**：D8b-1（删除顺序）。
- **验证命令/断言**：`npm test -- tests/vue/world/`；`rg -n "function aliasKey" vue/views/world` 单命中。
- **回滚**：单提交 revert。
- **裁定**：实施候选。
- **优先级建议**：P3

### D8b-8 资料状态标签映射重复与恒等变换

- **ID**：D8b-8
- **位置/符号**：`WorldQuickOpen.vue:26`（`KIND_LABELS_STATE = { active: "已采用", review: "待完善", archived: "已归档" }`）与 `worldCards.js:99`（`LIBRARY_STATE_LABELS` 同映射）；`WorldLibraryHome.vue:13-18`（`toCards` 的 `.map((card) => ({...card, stateLabel: card.stateLabel}))` 恒等变换）
- **问题与触发**：统一资料条目的状态→作者文案映射维护在两处；`toCards` 的 map 不产生任何变化，徒增一次数组物化与读者困惑。
- **调用链证据**：直接读码比对。
- **现有契约**：文案不变（"待完善"非 assetDisplayState 的"待处理"，属统一资料列表有意词汇，不并入 assetDisplayState）。
- **最小方案**：worldCards.js 导出 `LIBRARY_STATE_LABELS`，WorldQuickOpen 改 import；删除 `toCards`（直接 `cardsFromLibraryItems(...)`）。
- **预期收益**：映射单点；删 4 行死变换。
- **风险**：极低。
- **依赖**：无。
- **验证命令/断言**：`npm test -- tests/vue/world`；`npm run lint`。
- **回滚**：单提交 revert。
- **裁定**：实施候选（顺手改）。
- **优先级建议**：P3

### D8b-9 大列表渲染观察：bible 全量页/草稿客户端建卡与模板重复计算（不立项，收益待测）

- **ID**：D8b-9
- **位置/符号**：`WorldBibleTab.vue:122/295`（模板每卡片调用 `worldAssetDisplay(page)` ×2）、`:113/121/286` 等处 `typeMeta(page.page_type)` 每卡 ≥3 次（每次 `categories.value.find` 线性查）、`:896-904` `unifiedCards` 在非服务端路径对全部 `pages+drafts+entities(≤50)` 逐卡执行 `buildWorldCards`（含 `searchableText` 全文拼接）；gallery/filter 模式 `galleryPages`/`filterPages` 无虚拟化全量渲染
- **问题与触发**：资料库页数达数百、单页分区较多时，gallery 渲染与 unifiedCards 重算成本随页数线性增长；`worldAssetDisplay` 内含 attentionReasons 聚合，每卡 2 次为纯重复。
- **调用链证据**：读码；服务端路径（`usesServerLibrary`+`libraryItems`）已覆盖搜索/筛选/翻页态，客户端全量建卡仅在默认浏览态触发；entities 侧有 50 条截断明示。
- **现有契约**：展示结果不变；URL 为筛选事实源（服务端分页已就位）。
- **最小方案**（若实测成立后）：模板改为 `v-for` 内经 computed 预映射一次（card 流水线统一产出 display/meta）；必要时把 gallery 卡片列表加虚拟化或分批渲染。**先按计划 §5 用 `docs/diagnostics/performance.md` 隔离流程取代表性数据集基线，无实测瓶颈不动。**
- **预期收益**：待测（百页级项目 gallery 首帧与筛选切换耗时）。
- **风险**：中——模板改造触及 e2e DOM 契约（data-action/data-page-id 须逐节点保留）。
- **依赖**：性能基线（P2 链交叉复核统一排期）。
- **验证命令/断言**：改造前后同一数据集渲染耗时对比；`npm run test:e2e:functional`（world bible 契约）。
- **回滚**：独立提交序列可部分回滚。
- **裁定**：保留现状（记录观察；证据充分再立项）。
- **优先级建议**：P3

### D8b-10 errorLog._lastApiError 单槽通道的真实消费方登记（cross-ref F3-9，不单独立项）

- **ID**：D8b-10
- **位置/符号**：`frontend-console/vue/views/world/bible/useWorldBible.js:1427-1431`（`refreshProjection` 读 `errorLog._lastApiError` 并在 409 分支消费后置 null）、`:1521-1531`（`extractFinishedTaskId` 从 `apiErr.response` 正则/JSON 双路解析 `task_id`）
- **问题与触发**：投影刷新 409 时，前端依赖 api.js 写入的全局单槽 `_lastApiError` 取回被拒任务的 task_id，实现"上次刷新已结束，可强制刷新"的恢复路径。这是 F3-9（单槽覆盖竞态）在本槽位的唯一**功能性**消费点：若两请求间窗口内另一失败覆盖槽位，降级为普通 409 文案（功能仍可用，仅失去自动找回 task_id）。
- **调用链证据**：读码 + F3-9 已记录写入侧；`rg "_lastApiError" vue/views` 本槽位仅此一处消费。
- **现有契约**：恢复语义现状可用（降级安全）。
- **最小方案**：不单独改；F3-9 若实施（队列化/带 requestId），此消费点必须同步适配并保留 JSON 解析回退。
- **预期收益**：登记耦合点，防 F3-9 改动破坏投影恢复。
- **风险**：无（本条不动代码）。
- **依赖**：F3-9。
- **验证命令/断言**：若 F3-9 实施：手动断言并发两个失败请求后投影 409 仍能找回 task_id。
- **回滚**：不适用。
- **裁定**：保留现状（cross-ref 登记）。
- **优先级建议**：P3

## 历史候选复核

- **A8-3（smartDedup split-brain：领域本体侧）——仍成立，本体结构与 F3-4 桥接半边互相印证**。`shared/smartDedup.js`（1336 行，较历史 1238 行增长）本体审查（只读扩展，文件属 F3 槽位）：v2 组工作台为主路径——`openTask` 校验 `task.task_type==="smart_dedup_scan"`+novel_id 归属、组级 `expected_source/target_execution_fingerprint` 随组 payload 提交、apply 前 `structuredClone` 冻结 payload、分批 apply 且 `stillOwnsRequest()`（项目/路由/modal/批次四重）失守即对未回执组补 `receipt_missing` 失败（fail-closed）；草稿经 sessionStorage 按项目键持久化、结果回执按 `group_receipts` 恢复。v1 旧协议残留于第二处 `applySmartDedup`（:1312，suggestions 路径）。world 视图挂载点核实：`WorldSidebarToolCard.vue` 提供 `[data-role="smart-dedup-action"]`、`WorldView.vue:287` 与 `WorldBibleTab.vue:1783` onMounted 派发 `workspace:content-rendered`、app.js `:233/255-265/238` 委托+innerHTML 注入，与 F3-4 描述一致。结论：本体本身防护链完整无缺陷，split-brain 成本在桥接层与双协议残留，维持 F3-4"Phase 5 架构候选（需授权）"裁定，本体不单独动。
- **A4-4（world 资产双词汇渐进归入 worldAssetDisplay；前端 raw status 判断普查）——部分仍成立（收敛点已建，散落点即 D8b-3 清单）**。`shared/assetDisplayState.js` 已是成熟归宿（worldAssetDisplay/structureAssetDisplay/writingAssetDisplay/displayStateBadgeClass）。本槽位散落点普查结果：(1) 展示路径 12 处已统一走 `worldAssetDisplay`/`displayStateBadgeClass`（worldCards/EntityCollection/Relations/Aliases/EntityDetail/PageReader/QuickOpen/LibraryCards+List+Home/BibleTab/useWorldBible.statusLabel）；(2) 调用侧 status 兜底三变体=D8b-3（收敛候选）；(3) `worldRelationsAliasesOps.fetchEntityOptionsHtml:108` 把 raw status 直接拼进作者可见文案=D8b-2（词汇泄漏，历史候选未点名、本轮新增）；(4) `worldEntityHelpers.isAliasTargetEntity/isMergeTargetEntity/suggestionId` 与 `WorldEntityCollection.canPromote/canMerge`、`worldRelationsAliasesOps.showRelationReviewEditForm:670` 的 raw status 判定为**写资格/业务规则**（draft/candidate 可采用、canonical 可合并），非展示词汇，按"禁新模块自建映射"的原意不纳入收敛；(5) `worldQuery.js:202-207` legacy `?status=` URL→display_state 映射为兼容层，保留。判定：候选仍成立，剩余工作即 D8b-2/D8b-3 两小批。
- **A4-3（前端 isVersionActive helper 8 处）——已解决/符号不存在（本槽位复核）**。`rg isVersionActive` 在 frontend-console 生产/测试零命中（与 D2b 结论一致）；地图历史/候选的"版本是否当前"判断已由 `candidateView.id === revision?.id`、`base_revision_id !== revision?.id` 等显式比较承担（MapStructureEditor），无双词汇问题。
- **A8-2（三处手写 workflow manager → createWorkflowManager 工厂）——world 面已解决**。本槽位 `world/workflowManagers.js` 的 autoExtractManager/fusionManager 已用工厂（prepare/restartActiveOnRecover/matchRecovered/onTerminal 全配置化）；其余手写 poller（scene/story/smartDedup）不在本槽位，与 F3 复核结论一致。useWorldBible 的投影/简介/校验三条 `pollTaskProgress` 为页面内任务（非 workflow manager 语义），worldSession 键控+generation 守卫完整，收编收益低，不建议立项。
- **A8-6（bulkSelection store 合并 ~50 行）——已解决（本槽位面）**。`worldBulkSelection.js` 仅 56 行：Set 状态存 worldSession（reactive，query-only 重挂载存活）+ 复用 `shared/bulkSelection.js` 的 runBulkAction/bulkResultMessage/selectedItemsFrom。与 outline 侧"各 ~20 行模板封装"的残留一致，进一步合并有作用域语义分叉（worldSession vs outlineSession），维持 F3"不再立项"结论。
- **A8-4（api.js 契约迁移收尾）——视图侧无独立工作，与 F3-1 呼应**。本槽位视图全部经 `api.*` 方法调用（未直连契约表）；地图侧 `confirmMapAtlasPrompts/updateMapAtlasNode/uploadMapAtlasPage` 消费的正是 F3-1 指认的三条"已定义未接线"契约的手写方法，cocreation 相关同。视图侧无需改动；处置归 F3-1 的 (a)/(b) 分支。uploadMapAtlasPage 走 XHR 进度/取消属 F3 已注明的 multipart 有意例外。
- **A4-1/X1-7（DomainError 全局 handler）——前端不适用，与 D2b"已解决"一致**。world/map/rag 视图的错误处理统一依赖 `err.status/err.body.error/err.body.detail.code`（api.js 错误契约），无本地异常兜底 handler 需要收敛；map 的 `friendlyError`（MapWorkspaceView:837-852）是 error_code→作者文案的有意映射表，非转发层。
- **audit「不建议简化」smartDedup 领域逻辑条（1238 行保留）——维持排除**。本体审查（见 A8-3 条）确认其防护链（指纹重验/冻结 payload/回执 fail-closed/所有权守卫）是资产合并写入路径的安全边界，不属于简化对象。
- **X1-6（TaskStatus 裸字符串收敛）前端对端——观察，不立项**。本槽位的状态标签（`useWorldBible.taskStatusLabel`、`WorldHealthPanel.runStatusLabel`、map `runStatusLabel/historyStatusLabel`、rag `chunkStatusLabel/statusView`）全部是展示层作者文案映射，输入已由 `normalizeTaskProgress`（F3 权威映射）归一；X1-6 收敛后端枚举时这些映射无需联动，仅 `isTerminalTask`（done/failed/cancelled）等 3 处字面量需对齐新枚举导出，已在共享事实登记。

净复核计数：9 项次（A8-3、A4-4、A4-3、A8-2、A8-6、A8-4、A4-1/X1-7、audit 安全边界条、X1-6 前端对端）。

## 共享事实（供 W3 链 3/链 5 前端段使用）

### 1. 地图前端编辑链图（对应 P2 链 5 前端段；后端语义引自 D2b，前端逐点核对一致）

```
MapWorkspaceView（map 路由根；URL query 承载 node_id/page_id/atlas_view/feature_id/revision_id/run_id，commitCurrentQuery('replace')）
  ├─ loadAll()：getMapAtlas + getLatestMapAtlasRun + getMapAtlasPageHistory + [getMapAtlasRun(run_id)] + getMapCapabilities
  │    └─ run 活动（planning/generating）→ 2.5s setTimeout 自轮询 refreshRun（dataEpoch/项目守卫；错误即停）
  ├─ 结构编辑：MapStructureEditor（:key=projectId:nodeId 重挂隔离）
  │    ├─ 本机草稿：localStorage `novel_map_draft:{accountMarker}:{projectId}:{nodeId}`
  │    │    写前校验 ACCOUNT_MARKER_KEY 未变（换账号抛错不写）、写后回读比对；视图态另存 novel_map_view:*
  │    ├─ save()：POST saveMapRevision{base_revision_id: revision.id, document}
  │    │    → 409（status/statusCode 判定）→ conflict 面板：MapChangeReview 差异（serverRevision vs doc）
  │    │      「使用服务器版」（install(server)）／「用我的编辑创建新版」（rebase：revision=server 后再保存）
  │    ├─ 候选采用：viewCandidate→previewMapRevision（只读比较）→ 勾选 change_keys
  │    │    → previewMapReview{base_revision_id, action:'adopt', change_keys}
  │    │      校验 applied/expanded_change_keys 与本地 diff 键一致，不一致 fail-closed
  │    │    → reviewMapRevision('adopt'|'reject'|'restore', {base_revision_id, change_keys})
  │    │      后端 required_change_keys → 前端 explainRequiredChanges 提示补勾关联修改
  │    ├─ 来源依据：MapSourcePicker = context.searchEvidence(manuscript/canonical)
  │    │    → context.readEvidence 回读并复验 mapSourceRangeKey(source_ref) 指纹（不等→409 文案，不自动替换）
  │    │    → 产出 {kind:'source_range', id:draft_id, source_hash, source_ref, quote} 存入 feature.sources（≤8 双侧校验）
  │    ├─ 空间整理：confirmAiReference(action=world.map_atlas.structure, pinned_refs=[evidenceRefs+mapSourceSelections])
  │    │    → generateMapStructure{operation_id, base_revision_id, context_confirmation_id, location_ids/feature_ids}
  │    │    → 任务产 candidate 不动 head（对齐 D2b）；结果面板展示 discarded/truncated 计数
  │    └─ 底图/配图：layoutMap 预览（候选图元放置）→ 保存随 document；底图 stale 判定=geometrySignature(doc) 与 checkedGeometry 比对
  ├─ 图片生成（atlas run）：createMapAtlasRun{source_map_revision_id, context_confirmation_id, full_rebuild, target_node_id, ...options}
  │    ├─ prompt_review 态：画面说明逐页编辑（updateMapAtlasPagePrompt 带 expected_updated_at CAS，800ms 防抖+单请求排队；
  │    │    冲突→promptConflict「已在别处更新」）→ confirmMapAtlasPrompts（每页 expected_updated_at）
  │    ├─ 页审查：reviewMapAtlasPage('adopt'|'reject'|'archive'|'restore', {expected_updated_at})——CAS 409→setError
  │    ├─ 费用确认：generation_status=retry_requires_confirmation → resume/retry 前原生 confirm「可能重复扣费」（对齐 D2b 双确认）
  │    ├─ 派生：editMapAtlasPage（instruction+参考图≤7+PNG 蒙版）/regenerateMapAtlasPage → 新 run 候选，来源图不变
  │    └─ 标注：拖拽结束 updateMapAtlasAnnotation{position_x/y, expected_updated_at} CAS
  ├─ 上传：uploadMapAtlasPage（XHR multipart 进度/取消）前端预检 PNG/JPEG 且 size<50MB 严格（与后端 413 边界一致）
  ├─ 图片读取：fetchMapAtlasImage / fetchReaderMapImage（blob+ObjectURL，page 维度去重/释放；reader 按章键控）
  └─ 离开保护：useLeaveGuard（结构 canLeave→未保存则 <dialog> 保存/保留草稿/下载三选）+ beforeunload（prompt/upload/结构 dirty）
```

与 D2b 契约核对结论：上传边界、三层 CAS（结构 base_revision_id / page·prompt·annotation expected_updated_at / 图片 generation_status claim）、
retry_requires_confirmation 双确认、来源 digest 回读重验、cleanup 不触及——前端侧全部按契约实现，无错配。地图读取路径零业务写入（与 D2b §3 一致）。

### 2. 双词汇（raw status vs display_state）散落点清单（A4-4 视图侧全景）

- **已收敛（展示路径，12 处）**：worldCards.cardState、WorldEntityCollection.displayOf、WorldRelationsTab.statusLabelOf/StatusBadgeClass、WorldAliasesTab.statusLabelOf/StatusBadgeClass、WorldEntityDetail.display、WorldPageReader.display、WorldQuickOpen 行状态、WorldLibraryCards/List/Home 徽标、WorldBibleTab 页卡徽标、useWorldBible.statusLabel —— 全部经 `worldAssetDisplay`/`displayStateBadgeClass`。
- **待收敛（D8b-3）**：调用侧 status 兜底三变体（EntityCollection/Relations：`status||"canonical"`；Aliases：needs_review→candidate 且尊重 display_state 的第三变体）。
- **词汇泄漏（D8b-2）**：fetchEntityOptionsHtml 把 raw status 拼进作者可见 option 文案（唯一一处 raw 值直接示人）。
- **有意的 raw status 业务判定（不收敛）**：isAliasTargetEntity（draft/canonical/candidate）、isMergeTargetEntity（canonical）、suggestionId（draft/candidate+compatibility_shadow）、canPromote/canMerge（WorldEntityCollection）、WorldReviewBatch 搜索结果三值过滤、WorldHealthPanel canPublish（archived 排除）、worldCards cardState 的 draft→working 优先、bulk resolution 的 `status!=='canonical'` 拒绝——均为写资格/规则语义。
- **兼容层**：worldQuery.objectFiltersFromQuery 的 legacy `?status=` → display_state 映射；worldCards `LIBRARY_STATE_LABELS`（active→已采用/review→待完善/archived→已归档）是统一资料条目独立词汇（与 assetDisplayState 的"待处理"用词不同，有意区分）。
- **地图/rag 的状态词汇是各自领域状态机**（run: planning/generating/prompt_review/paused/partial/failed；page: review_status adopted/rejected/deprecated/candidate + generation_status；chunk embedding_status 双词 succeeded/done、pending/pending_vectorization 归一），与 world 资产双词汇无关，勿混入收敛批次。

### 3. smartDedup 领域本体结构摘要（A8-3 领域侧；文件属 F3 槽位，本体审查按任务指派在此补记）

- **形态**：`createSmartDedupManager({api,router,toast,modal,esc,onRenderActions,getCurrentProjectId,getCurrentRouteKey})` 工厂，唯一实例由 `app.js` 持有（`App._smartDedup`）；状态不进 Vue，UI 为字符串模板 + 全局 modal。
- **入口**：(1) `bridge.openSmartDedupTask(taskId)`→`openTask`（校验 task_type=novel 归属，恢复 `group_receipts`，非终态续轮询）；(2) 扫描提交 `startSmartDedupScan`（:214，projects.smart-dedup/scan）；(3) `handleAction`（app.js document 级 data-action 委托分发）。
- **v2 组工作台（主路径）**：组以 `group_id` 键控；每成员边带 `expected_source/target_execution_fingerprint`，提交 payload 经 `structuredClone` 冻结（:895）；分批 apply（`projects.smart-dedup/apply`，:907）每批后核对 `stillOwnsRequest()`（项目/路由/modal/在途批次四重），失守或 `receipt_missing` 即对未回执组落失败（已完成组保留）——写路径 fail-closed；草稿与回执 sessionStorage 按项目持久化（:111-137）。
- **v1 残留**：第二处 `applySmartDedup`（:1312）与 suggestions 分页/手动主体选择（referencePicker `_manualPrimaryPickers`）属旧路径，仍可达。
- **轮询**：自有 `pollTaskProgress` 封装（:301，workflowType=smart_dedup_scan），终态 `showProgress` + `_notifyRender`（回调 `onRenderActions`→app.js 重渲染按钮进挂载点）。
- **world 视图挂载点**：提供方 `WorldSidebarToolCard.vue`（`data-role="smart-dedup-action"`，WorldView relations 子视图与 WorldBibleTab `show-smart-dedup` 启用）；重渲染信号 `workspace:content-rendered` 由 `WorldView.vue:287`、`WorldBibleTab.vue:1783` onMounted 派发（该事件另有非 smartDedup 消费者，见 F3 共享事实 3）。
- **迁移注意（若 Phase 5 立项）**：指纹/冻结/回执三重防护与 `receipt_missing` 语义必须逐条平移；`workspace:content-rendered` 的 smartDedup 专用派发点仅上述两处 onMounted，其余派发点属 WorkspaceToolCard 等其他用途。

### 4. 其他横切事实（链 3/链 5 相关）

- **world 视图 URL 事实源矩阵**：objects（worldQuery 编解码 + `view`/`mode` 附加键）、review 三队列（各自 QUERY_KEYS + `kind` + `review_item` 选中态经 commitCurrentQuery 同步）、bible 资料库（worldCardQuery：q/kind/type/state/layout/sort/topic_id/fav/unclassified/skip）、关系/别名列表（q+page，状态在 worldSession.relationListFilters/aliasListFilters）。displayMode/activeCategory/筛选面板开合为 localStorage 偏好（键 `worldBible:{projectId}:*`、`novel_world_filter_panels:{projectId}`、`novel_view_mode:*:world-objects` 均在 F3 accountStorage 清理前缀内）。
- **世界采用/失效链前端触点（链 3）**：建议采用（useWorldBible.confirmSuggestion / useWorldReview 批量复核）均带 `expected_execution_fingerprint`，stale 拒绝并提示重核；发布 `publishBibleDraft` 前置 `previewBibleDraftPublishImpact`（expected_impact_scope_hash）+ 可选 validation run id；`applyAdoptionPackage` 带 expected_preview_hash + full 校验；409 统一文案指向"世界健康重新校验"。前端不直接写失效标记，失效感知靠 router.refresh 重取（与 D2b §3 后端失效传播衔接）。
- **编辑器保存/恢复语义（与链 8 相邻事实）**：bible 工作稿自动保存单请求排队+基线（expected_updated_at）+晚到响应不推进基线；本机备份 `world_draft_backup_*`（accountStorage 前缀内）；备份基线不符时强制走"核对服务器版本"流程；服务器+本机双失败有明示 toast（AGENTS 保存反馈要求达成）。
- **大列表现状**：world objects/review 全部分页 20/50；bible 客户端建卡路径仅默认浏览态（D8b-9 观察项）；rag 结果一次性 fetch ≤100、渐进渲染每页 +20；map 层级树/页列表无虚拟化但量级为节点数。
- **本槽位零 P0/P1 结论依据**：所有写路径具备项目归属校验入口（currentProjectId 随请求携带，服务端为权威门禁）、CAS/指纹字段随写提交、离开/失败路径有草稿或回执恢复、XSS 面全部走 `{{ }}`/esc 注入（仅 useWorldBible/WorldBibleTab 模态 HTML 经 esc 全量转义，抽查未发现裸插值）。

## 受阻

无。说明两点范围外登记：(1) `shared/smartDedup.js`、`shared/assetDisplayState.js`、`app.js`、`api.js` 的本体/桥接审查归属 F3（本报告按任务指派只读扩展核对并产出共享事实，发现分别记 F3-4/F3-1/D8b-3）；(2) D8b-9 性能观察需 P2 链统一排期的实测基线，本槽位按禁令未运行任何测试/构建。
