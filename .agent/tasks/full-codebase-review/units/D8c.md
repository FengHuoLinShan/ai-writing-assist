# D8c 槽位审查报告（R12：settings/interaction/project 视图 + 共享组件 + styles/themes/prototypes/views 遗留）

日期：2026-09-11。审查者：D8c 子代理（只读）。基线：`main` HEAD `e7d0b8d5b`，审查以工作树为准；`frontend-console/styles.css` 含他任务未提交 WIP（仅 2 行：`.world-review-candidate-cell` 的 `max-width:340px` 从容器移到子元素 `>p`，`git diff` 已核对，不影响本槽位结论，涉 styles.css 的发现注明"含 WIP"）。范围：slot-paths-W2.json "D8c" 全部 77 路径，逐文件语义阅读完成；styles.css 17679 行按节扫描（分节地图见共享事实 §1），未逐行。

## 覆盖行

CSV 片段（列：`path,审查状态,入口/消费者(可空),发现ID或无发现理由`）：

```csv
frontend-console/editorial-theme.css,已审,index.html:11 全局样式表（视觉权威层，见共享事实 §2）,无发现（:root 双定义 5/1091 为两层设计，--nc-primary 等引用均有定义）
frontend-console/favicon.svg,已审,index.html:8 rel=icon,无发现（41 字节空 SVG，占位防 /favicon.ico 404，有意设计）
frontend-console/prototypes/DesignSystem.vue,已审,prototypes/design-system.html 静态页专用（见共享事实 §3）,无发现（生产不可达；引用 WorkspaceDrawer/ThemePicker 属活组件的额外耦合面）
frontend-console/prototypes/README.md,已审,目录自述文档,无发现（自述"历史原型均已 superseded"与实际一致）
frontend-console/prototypes/design-system.html,已审,浏览器直开静态页（vite 构建无此入口）,无发现（引用 ../styles.css 相对路径仅工作区可用）
frontend-console/prototypes/design-system.js,已审,design-system.html 唯一 script,无发现
frontend-console/prototypes/mockup-style-a-minimal.png,已审,无代码引用（历史视觉探索图）,无发现（README 注册在案保留）
frontend-console/prototypes/mockup-style-b-warm.png,已审,无代码引用,无发现（同上）
frontend-console/prototypes/mockup-style-c-dark.png,已审,无代码引用,无发现（同上）
frontend-console/prototypes/world-card-mockup-filter.html,已审,无代码引用,无发现（历史原型）
frontend-console/prototypes/world-card-mockup-gallery.html,已审,无代码引用,无发现（历史原型）
frontend-console/prototypes/writing-mockup-style-a-minimal.html,已审,无代码引用,无发现（历史原型）
frontend-console/prototypes/writing-mockup-style-b-warm.html,已审,无代码引用,无发现（历史原型）
frontend-console/prototypes/writing-mockup-style-c-dark.html,已审,无代码引用,无发现（历史原型）
frontend-console/styles.css,已审,index.html:10 全局样式表（含 WIP，分节地图与重复区段见共享事实 §1）,D8c-1/D8c-2/D8c-6
frontend-console/theme-preload.js,已审,index.html:9 首个阻塞脚本（防主题闪烁）,无发现（白名单 hex 校验、无 CSS 插值、catch 兜底内置配色）
frontend-console/themes/quiet-library.nctheme.zip,已审,AppearanceSettings.vue:8 ?url 导入作可下载样例；e2e/themes.spec.js,无发现（生产活资产非死 zip）
frontend-console/themes/sample/LICENSE.txt,已审,quiet-library.zip 内同名文件源,无发现（Noto 字体 OFL 授权随包分发）
frontend-console/themes/sample/assets/book.png,已审,themes/sample/theme.json assets.book 源,无发现（zip 源文件；tests/themePackages.test.js 引用目录）
frontend-console/themes/sample/assets/noto-sans-sc.woff2,已审,theme.json assets.reading-font 源,无发现（10.7KB 子集字体）
frontend-console/themes/sample/assets/texture.png,已审,theme.json assets.paper-texture 源,无发现
frontend-console/themes/sample/theme.json,已审,quiet-library.zip 的 theme.json 源,无发现（与 themeTokens 校验规则一致）
frontend-console/themes/theme-package.schema.json,已审,AppearanceSettings.vue:9 ?url 下载,无发现（生产活资产）
frontend-console/views/writing/sceneAlerts.js,已审,vue/views/writing/useWritingWorkspace.js:19 生产 import,历史候选 A8-5/X1-9 见复核节（生产活代码）
frontend-console/views/writing/versionDiff.js,已审,useWritingWorkspace.js:20 生产 import,历史候选 A8-5/X1-9 见复核节（生产活代码）
frontend-console/vue/components/ActionMenu.vue,已审,WorkspaceToolCard 等 5 个消费者,无发现（visualViewport 定位、document 级监听 onBeforeUnmount 全清理、actionMenuCoordinator 单例互斥）
frontend-console/vue/components/AssistantReviewResult.vue,已审,ProjectAssistant.vue,无发现（覆盖声明措辞与 AGENTS.md"不宣称角色知识边界"一致）
frontend-console/vue/components/AssistantValue.vue,已审,OwnerAiDrawer 链 2 个消费者,无发现（labels/enums 巨型字面量每次 setup 重建，微瑕不立项）
frontend-console/vue/components/FocusedEvidencePanel.vue,已审,写作/大纲聚焦证据面板 2 消费者,无发现（contextKey watch 重载、alive+generation 卸载防护）
frontend-console/vue/components/ImportReviewResolutionPanel.vue,已审,导入审查 UI 1 消费者,无发现（epoch 卸载防护）
frontend-console/vue/components/OwnerAiDrawer.vue,已审,writing/world 视图抽屉 2 消费者,无发现（F3-3 交叉证据见复核节；代次/焦点恢复/query 同步完备）
frontend-console/vue/components/ProactiveCare.vue,已审,interaction/today 主动关怀 1 消费者,无发现（ACCOUNT_INVALIDATED_EVENT 订阅清理）
frontend-console/vue/components/ProjectAssistant.vue,已审,ShellApp 助手入口 1 消费者,无发现（assistant.dispose、matchMedia 清理）
frontend-console/vue/components/ProjectOrganizationHistory.vue,已审,项目组织历史 2 消费者,无发现（epoch+timer 清理）
frontend-console/vue/components/TargetedCompletionPanel.vue,已审,世界对象查漏补全 2 消费者,无发现（key watch 重置、alive+epoch）
frontend-console/vue/components/WorkflowProgressBody.vue,已审,WorkflowProgressCard 内嵌,无发现（taskId watch 重置详情展开）
frontend-console/vue/components/WorkflowProgressCard.vue,已审,11 个视图消费（工作流进度卡标准件）,无发现（ADR-0009 组件化，折叠持久化契约与 vanilla 一致）
frontend-console/vue/components/WorkspaceDrawer.vue,已审,WorkspaceToolCard/DesignSystem 等 3 消费者,无发现（useModalDialog 焦点陷阱）
frontend-console/vue/components/WorkspaceToolCard.vue,已审,6 个视图消费（工具卡标准件）,无发现（F3-4 挂载点提供方+workspace:content-rendered 派发方=cross-ref F3-4；freeze/unfreeze 焦点保持设计合理）
frontend-console/vue/components/actionMenuCoordinator.js,已审,ActionMenu.vue 唯一消费者,无发现（模块级单例 closer 互斥）
frontend-console/vue/components/progressUtils.js,已审,WorkflowProgressCard/Body、WritingWorkflowBars、DeepImportAuditDialog、测试,无发现（作者可读诊断映射纯函数）
frontend-console/vue/components/workspaceTools.js,已审,OutlineHeader/MapWorkspaceView 等 6+ 消费者,无发现（details 展开+focus 纯 helper）
frontend-console/vue/theme/themeArchive.worker.js,已审,themePackages.unpack 每次新建 Worker,无发现（zip 路径穿越/条目数/压缩方式/大小上限全校验，transferable 释放）
frontend-console/vue/theme/themePackages.js,已审,AppearanceSettings/useTheme,无发现（15s 解压超时+abort 传播；IndexedDB 幂等 put；图片重编码静态 WebP 且仅 PNG/JPEG/WEBP）
frontend-console/vue/theme/themeTokens.js,已审,themePackages/theme-preload 同词汇表/useTheme,无发现（对比度≥4.5:1 门禁、id 保留字拒绝、深冻结）
frontend-console/vue/views/interaction/HomeChoiceView.vue,已审,interactionIsland home 路由,无发现（lifecycleGeneration+disposed 双防护）
frontend-console/vue/views/interaction/InteractionView.vue,已审,interactionIsland interaction 路由,D8c-4/D8c-5
frontend-console/vue/views/interaction/JourneyListView.vue,已审,interactionIsland journeys 路由,无发现（reloadVersion/routeOwner 所有权防护、开场草稿 novel_ 前缀入账号清理）
frontend-console/vue/views/interaction/RpAdaptiveConfirmPopover.vue,已审,InteractionView/JourneyListView/RpSourceSetup,无发现（visualViewport 弹窗定位，全仓仅 3 处 visualViewport 使用之一）
frontend-console/vue/views/interaction/RpMarkdownContent.vue,已审,InteractionView 流式与消息渲染,D8c-4
frontend-console/vue/views/interaction/RpSourceSetup.vue,已审,JourneyListView 资料选择,无发现（sessionStorage 草稿键 rpSourceSetupDraft:v1 在账号 session 清理清单；破坏性导入双重确认）
frontend-console/vue/views/interaction/adaptivePopoverPlacement.js,已审,RpAdaptiveConfirmPopover,无发现（clamp/normalizeRect 纯函数）
frontend-console/vue/views/interaction/interactionErrors.js,已审,InteractionView/JourneyListView/HomeChoice 链,无发现（错误词表白名单化，provider 诊断文本仅用于有界本地映射不上屏）
frontend-console/vue/views/interaction/interactionSession.js,已审,InteractionView/JourneyListView,无发现（novel_rp_* 键均在 novel_ 前缀账号清理内；seeSeaGraceTimers 模块级 Map 有 cancel 配对）
frontend-console/vue/views/interaction/sourceLabels.js,已审,InteractionView/RpSourceSetup,无发现
frontend-console/vue/views/project/ProjectView.vue,已审,projectIsland project 路由,无发现（shared/bulkSelection 复用=reconcile 模式；批量删除二次确认+modal owner 检查）
frontend-console/vue/views/project/projectSession.js,已审,ProjectView/projectModals/recycleBin,无发现（reactive session 注释明确不按项目隔离=vanilla 语义）
frontend-console/vue/views/project/components/ImportDrawer.vue,已审,ProjectView,无发现（useImportUpload 进度+WorkflowProgressCard 契约）
frontend-console/vue/views/project/components/ProjectCard.vue,已审,ProjectView,无发现（纯展示 emit）
frontend-console/vue/views/project/logic/importHistory.js,已审,ImportDrawer,无发现（sanitizeTaskErrorMessage 复用+码点截断）
frontend-console/vue/views/project/logic/projectFilter.js,已审,ProjectView,无发现（zh-CN locale 排序/过滤纯函数）
frontend-console/vue/views/project/logic/projectModals.js,已审,ProjectView,无发现（esc() 拼装属 README 豁免模式；导入失败保留项目+选择不变才导航）
frontend-console/vue/views/project/logic/projectState.js,已审,ProjectView/projectModals/recycleBin,无发现
frontend-console/vue/views/project/logic/recycleBin.js,已审,ProjectView 回收站入口,无发现（永久删除双重确认、分页越界回跳、loadGeneration+ownsMutationResult 三重所有权）
frontend-console/vue/views/settings/AppearanceSettings.vue,已审,SettingsShellView section=appearance,无发现（disposed+abort+resources.dispose 三重清理；预览 modal 焦点管理）
frontend-console/vue/views/settings/GlobalSettingsView.vue,已审,SettingsShellView scope=account,无发现（connectionFormRevision 代次、submittedForm 防保存期间编辑误标 baseline、roving tabindex）
frontend-console/vue/views/settings/ProjectSettingsView.vue,已审,settingsIslands project-settings 路由,无发现（ownsProjectSettings 四条件防护、保存后 reconcile 失败降级 warning）
frontend-console/vue/views/settings/SettingsShellView.vue,已审,settingsIslands 两路由宿主,无发现
frontend-console/vue/views/settings/components/AuthorPreferencesForm.vue,已审,GlobalSettingsView/ProjectSettingsView,无发现
frontend-console/vue/views/settings/components/DeepImportFields.vue,已审,ProjectSettingsView,无发现（字段帮助按 key 语义分档，面向作者文案）
frontend-console/vue/views/settings/components/LlmFormFields.vue,已审,无生产消费者（唯一引用 tests/vue/settings/LlmFormFields.test.js）,D8c-3
frontend-console/vue/views/settings/components/SourceLabel.vue,已审,AuthorPreferencesForm（+LlmFormFields 死链）,无发现（组件活；两节点 fragment 注释说明契约）
frontend-console/vue/views/settings/logic/authorPreferences.js,已审,Global/ProjectSettingsView,无发现（前端硬默认与后端 AUTHOR_PREFS_DEFAULTS 对齐有注释声明）
frontend-console/vue/views/settings/logic/deepImport.js,已审,ProjectSettingsView/DeepImportFields,无发现（抽查 auto_merge_confidence=0.92 等默认值与后端 imports 一致；完整字段表对齐归 D5a/D5b 交叉）
frontend-console/vue/views/settings/logic/llmForm.js,已审,无生产消费者（仅 LlmFormFields.vue 与自身测试）,D8c-3
frontend-console/vue/views/settings/logic/sourceLabel.js,已审,SourceLabel.vue（活）,无发现
frontend-console/vue/views/settings/projectSettingsSession.js,已审,ProjectSettingsView,无发现
```

77/77 已审；无按生成源验证、不适用、受阻项。styles.css 补充：覆盖以分节扫描+成对 diff+选择器普查完成（方法与分节地图见共享事实 §1），D8c-1/D8c-2 定位到行级。

## 发现

### D8c-1 styles.css 三对成批逐字重复节（约 780 行纯冗余）

- **ID**：D8c-1
- **位置/符号**：`frontend-console/styles.css`（含 WIP 区段外）三组成对区段：
  - **Settings 对**：9445–9827（383 行）与 10435–10808（374 行）。diff 仅开头 9 行——第一份多 `.view-header--with-tabs .settings-tab-nav` 兼容规则与 `.settings-tab-content`，其余 374 行逐字相同（Tab 面板/操作按钮组/字段来源标记/按钮 loading/API Key 行/作者偏好复选框/空态/来源图例/全局 LLM 提示/深度导入来源提示/字段重置链接/空态容器/响应式）。引入提交 `58f4fdbb4`（"ui(polish): 全页面一致性与组件显示正确性打磨"）。
  - **world 统一组件对**：9830–9894（67 行）与 11832–11907（78 行，标题"world + map 视图统一组件"）。diff 16 行——第二份多 `.world-table-cell--ellipsis`、`.world-table--no-top-border` 两个选择器，其余逐字相同（分页/辅助文本/列表描述/表格单元格统一）。同一提交引入。
  - **review 工作台对**（列表头部操作区+自动提取面板+关系/别名待处理分组工作台）：10085–10434（350 行）与 11908–12249（342 行）。diff 9 行——第一份结尾多一个 `@media (min-width: 391px) #modal-overlay:has(.review-decision-layout)` 断点块，其余逐字相同。引入提交 `b2949afe9`。
  - 另有第四对部分重复：自动入库折叠区+世界书 12331–12879（549 行）与 12880–13502（623 行），diff 593 行、共同唯一行约 139——重复度低，不并入删除主张，收敛时顺带核对。
- **问题与触发**：两次"UI 一致性增补"提交把成批样式整段粘贴了第二份。CSS 后定义覆盖先定义，但两份内容逐字相同（差异仅为单侧多出的少量规则），第二份对层叠结果无任何影响，纯冗余。每次改这些节（如 bulk selection 清理批就动过 `.review-filter-chips` 相关行，即当前 WIP 所在区段 17595 附近不属于重复对）需要改两处，漏改一处不会报错但留下漂移隐患。
- **调用链证据**：`diff` 逐行对比（上述行号）；`git log -S "字段来源标记"`、`git log -S "自动入库折叠区"` → 58f4fdbb4；`git log -S "关系 / 别名待处理分组工作台"` → b2949afe9。两份重复的消费方同为 settings 视图（GlobalSettingsView/ProjectSettingsView）、world 视图、WorldReviewTab——类名相同，不存在"第二份服务不同结构"的可能。
- **现有契约**：§2 用户操作——纯 CSS 删除且删的是逐字副本，无渲染结果变化。
- **最小方案**：分三个独立提交，每对保留信息量较大的一份、删除另一份中的逐字重复部分（Settings 对建议保留第一份 9445–9827、删 10435–10808 并把第二份独有的无（其无独有内容）；world 对保留第二份 11832–11907（多 2 个活选择器）、删第一份 9830–9894；review 对保留第一份 10085–10434（多一个 @media 块）、删第二份 11908–12249；删除段留下的"Settings 视图 UI 一致性补充"重复标题注释一并清理）。
- **预期收益**：约 780 行冗余删除（styles.css 17679→约 16900 行）；样式维护单点；后续 UI 一致性调整不再需要双写。
- **风险**：低。若两份间曾存在"后写覆盖修复"意图，diff 已排除（内容逐字相同）；执行时按提交后截图/视觉冒烟兜底。
- **依赖**：与 D8c-2 同区段，建议同批（先删重复份使死选择器只剩单份，再删死选择器）。
- **验证命令/断言**：`cd frontend-console && npm run build`（含 verify-production-build）；`npm test`（183 文件基线）；`rg -c "^\.settings-actions" styles.css` 应为 1；`awk` 顶层选择器唯一性复查脚本无 ≥2 的 settings/review/world 族重复；浏览器冒烟设置两页+世界审查工作台。
- **回滚**：逐对独立提交，单提交 revert。
- **裁定**：实施候选。
- **优先级建议**：P2

### D8c-2 review-* 死选择器族 15 类全库零引用（随 D8c-1 重复翻倍）

- **ID**：D8c-2
- **位置/符号**：`frontend-console/styles.css`：`.review-badge`、`.review-badge--warning`、`.review-candidate-fieldset`、`.review-candidate-option`（含 `:has(input[type=checkbox]:checked)` 与子元素规则）、`.review-count`、`.review-decision-layout`、`.review-evidence-cell`、`.review-notice`、`.review-overview-card`、`.review-result-preview`（含 h4/p 子规则）、`.review-scene-quick-filter`、`.review-search-control`（含 `.form-input` 子规则）、`.review-sources`、`.review-suggestion-actions`、`.review-toolbar`。分布在重复对两侧：10273/10292/10300-10301/10388-10393/10398-10422 区段与 12096/12115/12123-12124/12211-12216 区段。
- **问题与触发**：这 15 个类在前端生产代码（vue/、views/、app.js、shared/、ui/、index.html）、测试、e2e 中全部零引用（已排除动态拼接：`review-` 模板字面量命中均为路由名 `review-aliases`/`review-batch-types-*` ID，非 CSS 类）。它们是 review 工作台早期版本的残留；现役 WorldReviewTab.vue 使用的 `review-member-row`/`review-group-card`/`review-decision` 等类不在其列。因 D8c-1 的成对重复，每条规则实际存在两份（约 28 条死规则）。
- **调用链证据**：`rg -o "review-[a-z-]+" styles.css | sort -u` 全族 63 类逐一 `rg -l "<cls>" -g '!node_modules' -g '!dist' -g '!styles.css' -g '!*.test.js' -g '!e2e/'` 计数，15 类为 0；动态拼接检查 `` `review-``/`review-${` 无类名拼接命中。
- **现有契约**：无（纯样式，无行为）。
- **最小方案**：与 D8c-1 同批执行——先删重复份，再删除死类规则及其专属注释。
- **预期收益**：约 28 条死规则删除；review 工作台样式面与实际 DOM 一致。
- **风险**：低。多类名选择器（如 `.review-decision-layout, .review-candidate-fieldset { }` 与活类共存时只删死部分）；`#modal-overlay:has(.review-decision-layout)` 断点块整体属死。
- **依赖**：D8c-1。
- **验证命令/断言**：`rg -n "review-(badge|candidate-fieldset|candidate-option|count|decision-layout|evidence-cell|notice|overview-card|result-preview|scene-quick-filter|search-control|sources|suggestion-actions|toolbar)" frontend-console/styles.css` 零命中；`npm run build`；e2e world-relations-aliases 冒烟。
- **回滚**：与 D8c-1 同提交或紧随其后独立提交。
- **裁定**：实施候选（并入 D8c-1 批次）。
- **优先级建议**：P3

### D8c-3 settings 死组件簇：LlmFormFields.vue + logic/llmForm.js

- **ID**：D8c-3
- **位置/符号**：`frontend-console/vue/views/settings/components/LlmFormFields.vue`（210 行）；`frontend-console/vue/views/settings/logic/llmForm.js`（175 行）；`frontend-console/tests/vue/settings/LlmFormFields.test.js`、`frontend-console/tests/vue/settings/llmForm.test.js`。
- **问题与触发**：全库（vue/、views/、app.js、index.html、e2e/、构建脚本）对 `LlmFormFields` 的唯一引用是其自身测试；`llmForm.js` 的唯一生产引用是 LlmFormFields.vue。现役账户设置页 GlobalSettingsView.vue 用内联 provider 卡片渲染连接（437–519 行），项目设置页用 DeepImportFields/AuthorPreferencesForm——该组件是旧 vanilla 账户设置页（LLM 连接表单+来源标记）迁移后未随删的死代码，文件头注释自述"对应原 llmFormFields.test.js 的 DOM 行为契约"，测试保留了对已不存在 UI 的断言。死链连带：LlmFormFields 引用的 SourceLabel 是活组件（AuthorPreferencesForm 也在用），不受影响。
- **调用链证据**：`rg -ln "LlmFormFields" -g '!node_modules' -g '!dist' .` 仅命中组件本体与一个测试文件；`rg -n "llmForm.js"` 仅命中 LlmFormFields.vue 与 llmForm.test.js。
- **现有契约**：无外部消费者；删除不影响任何用户操作。
- **最小方案**：删 LlmFormFields.vue、logic/llmForm.js 及两个对应测试文件；若 `logic/sourceLabel.js` 有导出仅被 llmForm.js 消费则顺带核对（sourceLabelClass/formatSourceValue 仍被活组件使用，保留）。
- **预期收益**：生产 385 行 + 2 个测试文件删除；settings 逻辑面与实际 UI 一致；消除"设置页还有一套 LLM 表单"的误导。
- **风险**：极低（零引用已实锤；无动态 import 字符串路径命中）。
- **依赖**：无。
- **验证命令/断言**：`rg -rn "LlmFormFields|logic/llmForm" frontend-console -g '!node_modules' -g '!dist'` 零命中；`cd frontend-console && npm run lint && npm test && npm run build`。
- **回滚**：单提交 revert。
- **裁定**：实施候选。
- **优先级建议**：P2

### D8c-4 RpMarkdownContent 流式渲染对累积文本全量重解析

- **ID**：D8c-4
- **位置/符号**：`frontend-console/vue/views/interaction/RpMarkdownContent.vue:342-351`（setup 渲染函数每次执行 `parseBlocks(parseInline 全文)`）；`frontend-console/vue/views/interaction/InteractionView.vue:580`（`streamText.value += event.data?.text`）与 `:2125-2128`（`<RpMarkdownContent :source="streamText">`）。
- **问题与触发**：RP 流式生成期间每个 SSE chunk 追加到 `streamText`，触发 RpMarkdownContent 重渲染，对**全部累积文本**重新跑正则解析器并重建整棵 VNode（含每段的 inline token 树）。单段故事文本越长，每 chunk 的解析+diff 成本越高，整体呈超线性。正常长度的段落（数百至数千字）在现代设备上大概率先于网络到达，无用户可感问题；数千字以上的单次生成段在低速设备上可能出现输入/滚动掉帧。收益需实测，不预支百分比。
- **调用链证据**：读 RpMarkdownContent setup 全文（无 memoization，props.source 直通 parseBlocks）；读 InteractionView followAttempt chunk 分支（无节流/分块渲染）。对比：非流式历史消息列表（`:2015/:2042`）仅在加载时渲染一次，不受影响。
- **现有契约**：§2 用户操作——流式输出行为（逐字出现、isNearBottom 跟随滚动）必须保持。
- **最小方案**：若实测确有瓶颈：对流式中的文本按"已稳定段落/正在增长的尾段"切分，仅尾段重解析（解析器已是块级、可在最后一个换行处切分）；或对 chunk 合并到 rAF 帧再更新。二选一，均为局部改动。
- **预期收益**：流式长文本的事件循环占用下降；收益待测（本槽位禁令未运行任何基准）。
- **风险**：低（解析器块切分边界需处理围栏代码块跨段情况——尾段起点回退到最后一个非围栏块边界即可）。
- **依赖**：先按计划 §5 P2 用性能隔离流程取基线；无基线不实施。
- **验证命令/断言**：实施前 `docs/diagnostics/performance.md` 隔离流程记录长段流式的帧耗时；实施后同输入对比；`npm test -- tests/vue/`（RpMarkdownContent/InteractionView 相关）。
- **回滚**：单提交 revert。
- **裁定**：补证据（先测再做）；无实测前不动。
- **优先级建议**：P3

### D8c-5 InteractionView.vue 单文件 2623 行承载 8 项职责（架构观察，默认保留）

- **ID**：D8c-5
- **位置/符号**：`frontend-console/vue/views/interaction/InteractionView.vue`（2623 行，全前端最大视图）：会话流式（followAttempt/heartbeat）、消息发送与幂等（startMutation 家族）、回顾编辑（overview 8 section+草稿+冲突）、分支树（tree*/branchCacheGeneration）、路径定位器（locator*/pathIndex）、来源资料抽屉（source*）、生成记录（generationRecords*）、主题跟随（themeFocusValue）。
- **问题与触发**：修改任一职责都在同一 2600 行文件内进行，定位成本高；但 8 项职责共享同一组代次防护（journeyRefreshVersion/overviewGeneration/branchCacheGeneration/disposed）与 journey epoch 乐观锁，状态耦合是有意设计而非失控——拆分需要先设计这些防护的归属。阅读结论：无竞态、无泄漏（onBeforeUnmount 清理 6 类监听/定时器/流/离开通知），是全前端防护最完备的视图之一。
- **调用链证据**：逐段读 1–1942 行 script 与模板关键段；监听器清单 rg 核对（1900–1941）。
- **现有契约**：§2 用户操作全量（RP 是核心交互面）。
- **最小方案**：默认保留现状。若后续 RP 功能继续膨胀，按"回顾编辑（overview* 约 500 行）"与"来源抽屉（source*）"两个低耦合块优先拆子组件，代次防护经 props/composable 传递；不与 D8c 其他批次捆绑。
- **预期收益**：维护定位成本下降；无运行时收益。
- **风险**：中——拆分触碰流式与 epoch 防护链，回归面大（RP 全功能+e2e）。
- **依赖**：无外部依赖；实施需单独批次与完整 RP 回归。
- **验证命令/断言**：`npm test -- tests/vue/`（interaction 相关）；`npm run test:e2e:functional`（RP 链）。
- **回滚**：独立提交序列按块回退。
- **裁定**：保留现状为默认；拆分列架构候选待 RP 需求驱动。
- **优先级建议**：P3

### D8c-6 styles.css 头部"视觉权威唯一在 editorial-theme.css"声明与三处有意硬编码区的张力

- **ID**：D8c-6
- **位置/符号**：`frontend-console/styles.css:1-6`（头注释："视觉表达（颜色/圆角/阴影/线条）唯一权威：editorial-theme.css"）对比：198–206（error-card/warning 硬编码红系）、5056–5090（project 页 `--project-paper/--project-ink` 等局部变量，含暗色变体 5090+）、14213 节起"入口与跑团模式：独立、纯白、低干扰界面"（约 35 处硬编码，节注释自述独立设计）、17500 区段零星 9 处。合计约 80 处（含 WIP 区段外）。
- **问题与触发**：三处硬编码区均为有意设计（错误反馈色、项目页纸张材质局部作用域、RP 独立纯白界面），不是漂移；但与头部"唯一权威"声明矛盾——后续维护者按声明把颜色上收到 editorial-theme 或主题包时会破坏这三个区的独立视觉。主题包（.nctheme.zip 只覆盖 --nc-* 15 色）切换时这三个区不跟随主题，属现状行为。
- **调用链证据**：硬编码分布按区段统计（0-500:5、5000 区:23、14000–16000:35、17500:9）；14213 节注释与 5056 局部变量作用域核对。
- **现有契约**：无用户可见契约变化；纯文档澄清。
- **最小方案**：修改 styles.css 头注释，声明"唯一权威 + 三处登记的例外区（error-card、--project-* 局部、RP 独立节）"；不改任何规则。
- **预期收益**：样式权威约定成文，防止未来"上收颜色"误改。
- **风险**：零（注释级）。
- **依赖**：无。
- **验证命令/断言**：`git diff --check`；注释与 ui-size-audit/设计标准 docs/frontend/uiux/design-standard.md 表述不冲突。
- **回滚**：单提交 revert。
- **裁定**：实施候选（顺手修改级）。
- **优先级建议**：P3

## 历史候选复核

- **A8-5 / X1-9（views/ 目录 2 文件迁 vue/views/writing 后删目录）——仍成立**。现状：`frontend-console/views/writing/sceneAlerts.js`（236 行）与 `versionDiff.js`（393 行）是生产活代码，被 `vue/views/writing/useWritingWorkspace.js:19-20` 以 `../../../views/writing/` 相对路径 import；`README.md:181` 仍记载该目录（"无 DOM 纯 helper"）；`tests/writing/sceneAlerts.test.js`、`tests/writing/versionDiff.test.js` 存在；`tests/api-contract.test.js:33-42` `productionJsFiles()` 的目录表 `["shared","ui","views"]` 递归扫描 views/——两文件迁入 `vue/views/` 后将脱离该测试扫描范围（测试侧同步归 E2 交叉：目录表需改为 vue/views 或删除 views 项并核对静态检查覆盖意图）。迁移本身=移动 2 文件+改 2 行 import+README 一行+测试 import 路径，纯 helper 无 DOM、无路径副作用，兼容面为零。删除后 `views/` 顶层目录消失（productionJsFiles 的 "views" 项需同步）。
- **A4-4 前端侧（world 资产双词汇，前端 raw status 判断渐进归入 worldAssetDisplay）——本槽位不适用，无残留**。D8c 的 77 路径逐一核对：settings/interaction/project 视图与共享组件中无 world 资产 raw status 映射（present 的状态词汇仅在 progressUtils（工作流域，与 world asset 无关）、importHistory（imports 域）、interactionErrors（RP 域）中以自有枚举出现，各有后端对端，不属 A4-4 范围）。A4-4 的前端归宿 `shared/assetDisplayState.js` 属 F3 面（F3 覆盖行已记"无发现（displayState 收敛点，A4-4 归宿）"），world 视图侧残留归 D8b。本槽位无需动作。
- **A8-10 / A8-11（audit 剔除项复核）——历史明细缺失，按现状重新取证关闭**。仓库内 A8 审查底稿未入库，`code-simplification-audit.md:92` 仅存一行剔除记录（"A8-10/11"无内容）；与 F3 对 A1-8 的处理一致，原命题无法取证。替代动作：本槽位对全部 77 路径做了独立审查，覆盖了原 A8（前端视图）区域在本槽位的部分——结论以 D8c-1～D8c-6 为准，无未登记的重大遗留。
- **F3-3 交叉（today/generate 死路由注册的视图侧影响）——D8c 侧证实，方案可行**。`vue/components/OwnerAiDrawer.vue:4` 静态 import `GenerateView.vue`、`:43-47` 动态 `import("../generateIsland.js")` 复用 `loadGenerate`——证实 F3-3"模块活、仅 renderer 注册死"的判断；删 `registerGenerateIsland`/`registerTodayIsland` 注册与 viewLoaders 两行不影响 OwnerAiDrawer（它不依赖注册面，直接 import 模块导出）。D8c 77 路径中无 today/generate 视图文件（TodayView/GenerateView 在 D8a），无额外视图侧阻碍。
- **A8-3（smartDedup split-brain）领域侧交叉——本槽位提供挂载点证据**：`vue/components/WorkspaceToolCard.vue:49` 是 `workspace:content-rendered` 派发方、`:92` 样式含 `[data-role="smart-dedup-action"]` 契约、`:57` Teleport 至 `#sidebar-context-slot`——F3-4 的 DOM 字符串契约在本组件完整在场。裁定维持 F3-4（Phase 5 架构候选，不重编号）；迁移时 WorkspaceToolCard 的 6 个消费者需逐一回归。
- **A8-6（bulkSelection 合并）领域侧交叉——D8c 侧确认 F3 复核结论**：ProjectView.vue:52-52/119-131 与 recycleBin.js:5 经 `shared/bulkSelection.js` 纯 helper 复用（getBulkSelection/reconcileBulkSelection/runBulkAction），projectSession `_bulkSelections` 为 reactive Set 宿主；无历史所述 vanilla 渲染器残留。

## 共享事实

### 1. styles.css 分节地图与重复区段（17679 行，含 WIP）

- **结构层（1–453）**：头注释（权威声明，见 D8c-6）→ `:root,.theme-preview` 字体三变量 → `:root` 字阶/行高/字间距/间距 8px 网格/圆角 full/缓动/布局尺寸（topbar 64px、sidebar 224px、workspace 分栏、rail 三档）。
- **壳层（453–1020）**：应用容器/顶部状态栏/主布局/左侧导航/主工作区/右侧留白/底部命令栏。
- **通用件（1020–5054）**：按钮→输入框（1155 起，延伸至 2418 前后）→内容优先工作区辅助栏（2418）→卡片（3607）→badge 兼容（3661）→Pill/状态指示器/模态框（3763，含 Vue 对话框补齐注释 3892）→AI 参考资料预检（3927）→Toast/快捷键帮助/表格/断点（4516）→空状态/错误卡片/骨架屏/行内操作菜单（4689）→折叠面板/子标签导航/编辑器区域（4930）→章节树（5011）。
- **页面节（5054–14212）**：项目页面（5054，含 --project-* 局部变量）→通用视图工具栏（6026）→统一视图头部（6087）→Markdown 预览（6309）→加载动画/工作流进度（6405–6743）→响应式（6743）→Scene 卡片/工作台/Story 辅助工作区（7171–8833）→叙事标签颜色/主题切换菜单/AI 续写 spinner/批量管理按钮（9053–9114）→**重复区段群**（见 D8c-1：9114 outline/scene 统一组件①、9366 Settings 补充①、9828 world 统一①、9895 outline/scene 统一②（内容不同仅标题同）、10085 review 工作台①、10435 Settings 补充②=①-9 行、10809 Generate&RAG 增补、11830 world+map 统一②=①+2 选择器、11908 review 工作台②=①-8 行、12331/12880 自动入库折叠区两份、12489/13155 世界书两份）→project 视图统一组件（13559）→writing polish（13734）→Smart dedup workbench（13766）→reference picker（14075）。
- **独立界面层（14213–末尾）**：入口与跑团模式·独立纯白界面（14213，约 1900 行 .rp-* 族）→RP 低频确认弹窗（16126，visualViewport）→Task-oriented shell 与 Today workspace（16251）→Progressive author-facing tools（16542）→Generate 视图收编（16899）→Owner-page AI entry（17205）→统一待定资料工作台（17542）→Phase 4 世界健康复核等（17644，当前 WIP 2 行位于 17595–17612 附近，不属重复区段）。
- **系统性死选择器方法**（供后续槽位复用）：①`awk` 提取规则选择器并区分顶层/@media，按出现次数排序；②对 ≥2 次的顶层重复按节标题成对 `diff` 定位逐字副本；③对可疑族（本次 review-*）用 `rg -o` 枚举全族类名逐一查生产/测试/e2e 引用并排除模板字面量拼接。抽查结果：review 族 63 类中 15 类死（D8c-2）；settings/world 族重复对内选择器全部在用。

### 2. 主题变量契约（styles.css ↔ editorial-theme.css ↔ themes/ ↔ vue/theme/）

- **三层变量**：editorial-theme.css:5 `:root` 定义 `--nc-*` 原语（唯一色值层：bg/surface/surface-muted/ink/body/dim/faint/ghost/accent/on-accent/accent-soft/hairline/hairline-strong/success/warning/error + :103/:137 `--nc-primary/--nc-on-primary` 明暗两份）→ `--archive-*` 兼容别名（仅转发，供 writing-desk.css 消费）→ 语义层（--bg-*/--text-*/--accent 等，styles.css 全部结构规则消费）。editorial-theme.css:1091 第二个 `:root`（Modern workspace 层，1090–1291）补 `--control-height/--theme-float-shadow/--theme-background/--theme-texture/--theme-empty-image` 与全局视觉语言（!important 少量、组件契约由 shell 提供只管视觉）。
- **主题包面**：`vue/theme/themeTokens.js` `COLOR_VARIABLES` 固定 15 个 `--nc-*` 键=主题包可覆盖全集；`variantVariables` 另产 radius 阶梯/--control-height/--theme-float-shadow。`themePackages.js`（zip 解包 15s 超时/资源校验/图片重编码静态 WebP/IndexedDB 存储）与 `themeArchive.worker.js`（路径穿越/条目数/压缩方式/分类型大小上限，transferable）为完整前端沙箱链，无服务端参与。`theme-preload.js` 在两份 CSS 前同步执行：明暗判定+bootstrap 颜色缓存白名单 `^#[\da-f]{6}$` 逐键 setProperty，无插值。
- **装载顺序（index.html:8-11）**：favicon.svg → theme-preload.js → styles.css → editorial-theme.css。
- **硬编码颜色例外区**（~80 处，有意设计）：error-card 红系（198–206）、--project-* 局部变量（5056–5090）、RP 独立纯白节（14213+）。主题包切换不覆盖这三区=现状行为（D8c-6）。
- **关联发现**：ui-size-audit.md（另一专项审查）记录的专注模式 workflow 通知右偏（--sidebar-width 在 editorial-theme.css:1274 ≥1100 写作页 :has 下被改 72px 不复原）、`.writing-form-hint` 类泄漏（styles.css:9908 只补 margin，基础样式在 writing-desk.css:1553 仅写作 island 加载）等 CSS 交互债归该 audit 与 D8a/D8b，本槽位不重复计数。

### 3. 遗留目录可达性结论

- **frontend-console/views/**（遗留 2 文件）：生产可达。`views/writing/sceneAlerts.js`/`versionDiff.js` 被 useWritingWorkspace.js:19-20 生产 import（详见历史候选复核 A8-5/X1-9）。
- **frontend-console/prototypes/**：生产不可达。vite 构建唯一 HTML 入口是 index.html（vite.config.js 无 prototypes/design-system 入口，build.manifest 产物不含之）；deploy 资产契约（validate_frontend_assets.py 校验 asset-manifest.json）只发 dist。design-system.html 为浏览器直开静态页（引用 `../styles.css` 相对路径，仅工作区/dev server 可用）；7 个 mockup HTML/PNG 无任何代码引用。目录 README 自述"历史原型均已 superseded"；audit"不建议简化"清单将其列为"注册在案"——维持保留现状，但注意 DesignSystem.vue 静态引用活组件 WorkspaceDrawer/ThemePicker：这两个组件改 props/事件时 prototypes 页会静默失配（无测试覆盖），属可接受风险。
- **frontend-console/themes/**：生产可达活资产。`quiet-library.nctheme.zip`（13.9KB）经 AppearanceSettings.vue:8 `?url` 导入为可下载样例包并作 e2e/themes.spec.js 固定样例；`theme-package.schema.json` 同为下载资产（:9）；`themes/sample/`（theme.json+LICENSE+3 assets）是 zip 的制作源文件，tests/themePackages.test.js 引用，README 记载——删 zip 前不可删 sample（zip 从 sample 构建）。
- **favicon.svg**：41 字节空 SVG，index.html:8 引用，占位防 404，有意设计。

### 4. 组件清单与复用面（vue/components 14 组件 + 3 js）

- **高复用标准件**：WorkflowProgressCard（11 消费者，含 ImportDrawer/各 workflow manager 视图；ADR-0009 组件化，DOM class/折叠 sessionStorage 契约与 vanilla progressRenderer 一致）、WorkspaceToolCard（6 消费者，Teleport 到 `#sidebar-context-slot` + mobile 抽屉降级 + ActionMenu "更多工具"）、ActionMenu（5 消费者，visualViewport/floating 定位）、WorkspaceDrawer（3，useModalDialog 焦点陷阱）、AssistantValue（2，递归键值渲染含巨型 labels/enums 字面量）。
- **单消费者业务件**：ProactiveCare（interaction/today 关怀）、ProjectAssistant（ShellApp 助手）、ImportReviewResolutionPanel、OwnerAiDrawer（writing/world 抽屉，内嵌 GenerateView/RagSearchView）、ProjectOrganizationHistory、TargetedCompletionPanel、FocusedEvidencePanel、AssistantReviewResult、WorkflowProgressBody（Card 内嵌）。
- **纯逻辑**：progressUtils（作者可读诊断/阶段标签，4+ 消费者）、workspaceTools（details+focus helper，6+ 消费者）、actionMenuCoordinator（ActionMenu 单例互斥）。
- **共性形态**：全部组件具备 `disposed/alive` 标志 + epoch/generation 代次防护 + onBeforeUnmount 监听/定时器清理；无 v-html/innerHTML（AGENTS.md XSS 约束合规）；scoped style 只用语义变量。零死组件（死组件在 settings 目录，见 D8c-3）。

### 5. settings/interaction/project 视图共性形态（后续槽位/实施可依赖）

- **竞态防护惯例**（三集群一致，可直接复用）：请求代次（`connectionFormRevision`/`loadGeneration`/`reloadVersion`/`journeyRefreshVersion`）+ `ownsXxx()` 闭包（disposed+路由/视图归属+epoch 或 revision）+ 迟到响应静默丢弃；GlobalSettings 的 `submittedForm` 快照防止保存期间继续编辑被误标为已保存基线。
- **保存反馈三态**：`kind: pending|success|error|warning` + `role=status` 文案 + toast + `useSaveButton`（loading/error 闪烁）；"已保存/已备份"仅在持久化确认后显示，失败保留输入并给重试焦点（GlobalSettingsView:231/315 显式 focus 回表单）。
- **离开守卫**：三集群全部 useLeaveGuard（canLeave 确认）+ beforeunload 双轨；守卫条件均为 JSON baseline 对比（dirty 计算）。
- **可访问性**：tab 族 roving tabindex+方向键/Home/End（GlobalSettingsView/ProjectSettingsView/OwnerAiDrawer 同型实现——三份同构 keydown 处理约 25 行×3，语义一致，收敛收益小、跨视图抽取反而增加耦合，不建议立项，记录备查）。
- **storage 边界**：全部持久化键落在 F3 共享事实 §3 的账号清理前缀内（novel_rp_*、novel_theme 例外保留、rpSourceSetupDraft:v1 session、projectSettingsSession 为内存态）。

## 受阻

- 无受阻项。按槽位禁令未运行任何测试/构建/基准：D8c-1/D8c-2/D8c-3 的验证命令为实施期执行项；D8c-4 明确"收益待测、先测再做"。两项交叉移交：(1) `deepImport.js` DEEP_IMPORT_GROUPS 字段表与后端 imports 默认值的逐字段对齐（已抽查 auto_merge_confidence=0.92 一致）归 D5a/D5b 交叉复核；(2) A8-5/X1-9 的 `tests/api-contract.test.js` productionJsFiles 目录表更新归 E2。
