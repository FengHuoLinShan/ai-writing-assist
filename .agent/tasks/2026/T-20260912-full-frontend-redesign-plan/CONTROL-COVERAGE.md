# H01 控件覆盖补账

日期：2026-09-12。只读源码审视，未进行浏览器操作。扫描范围为当前 frontend-console/prototypes/redesign 下 25 个 SFC（其中 24 个含目标控件）；AST 明细共 472 个原生/复用控件声明（同一模板循环按声明位置登记，不乘实例数）。旧 CONTROL-INVENTORY 的 133 计数不作为当前覆盖数。

逐声明 AST 明细见 [CONTROL-DECLARATIONS.md](CONTROL-DECLARATIONS.md)，机器清单见 [CONTROL-COVERAGE.json](CONTROL-COVERAGE.json)。

动效规则沿用 MOTION-RULES.md：M01 操作按钮，M02 图标/关闭，M03 分段选择，M04 开关/checkbox/radio，M05 文本输入，M06 原生 select/range，M07 ActionMenu/details，M08 导航/章节/版本，M09 卡片/对象/任务，M10 地图标记，M11 阅读分支，M12 加载/失败/冲突/成功，M13 外观，M14 筛选，M15 dialog/抽屉，M16 正文与内容容器。

## 覆盖表

| 文件与行 | 控件声明/循环族 | 触发与当前动效 | 决定 | 中断/减效策略 | 证据 |
|---|---|---|---|---|---|
| AssistantPreview.vue:20-24 | 视图 tabs；scope select；快捷意图循环；prompt textarea；历史 details；任务停止/重试/进度；批次 checkbox/审阅；提醒 checkbox/查找 | tab/选择即时切换；任务按钮更新演示状态；progress 仅进行中；输入无内容动画 | M03/M05/M06/M08；快捷/任务 M01/M09；流程 M12 | 输入不重建；details 原生关闭；停止/失败保留输入和结果；减效直接切状态 | 源码已读；待浏览器检查任务进度、批次和焦点 |
| CandidateReview.vue:48,79,82-85,89-92 | stale 重查；审查状态 details；返修 details/input/状态按钮；关闭/返回/拒绝/采用 | 状态按钮即时；比较区静态；返修无计时器；disabled 采用由 review/stale 控制 | M01/M03/M05/M07/M12/M15 | 失败/过期保留比较；采用只发事件；details 可反向关闭；减效无循环 | P03a/P03b 测试通过；待浏览器嵌入 PreviewDialog |
| ExperiencePreview.vue:20-23 | 组件实验按钮；分段循环；switch、checkbox、radio；输入/选择；状态筛选；progress；dialog/抽屉/比较/通知入口 | 组件区手动切换；输入本体静态；progress 由手动阶段更新；复用 dialog | M01-M07/M12-M16 | 组件区已有减少动态控制；原生控件保留平台键盘；状态切换不自动完成 | 现有 motion validation 文档；源码未实看 |
| IdentityPreview.vue:13-14 | 身份选择；邮箱/验证码 input；form；发送/失败/继续按钮 | form 手动在发送与失败间切换；失败保留意图/输入；无真实发送 | M01/M05/M09/M12 | 原生 form 校验；失败提示即时；无动画任务 | 源码已读；浏览器/键盘焦点待验 |
| ImportPreview.vue:49,60-61,67,69,74,76-77,84-85,94,97,100 | 步骤；示例选择/取消；章节 checkbox 循环/清空/全选；范围 checkbox/select；整理工作流按钮；返回/准备/导入 | 步骤即时；checkbox/select 原生；工作流手动推进，无定时成功；失败/待决定 notice | M01/M03/M04/M06/M07/M12/M14 | 错误重试保留选择；失败重试不重置成功项；details/按钮可中断；减效直接状态 | P08/E04a/E04b 测试通过；待浏览器窄屏流程 |
| JourneyPreview.vue:19-21,23,25 | 页面标题/开启旅程；hero；发现卡循环；错误重试/空态入口 | 卡片 hover/轻反馈；hero/发现按钮直接导航；失败重试即时恢复 | M01/M09/M12 | 失败保留已有旅程；无自动生成；减效沿共享卡片规则 | F01-F02 测试通过；待浏览器 hero/空失败态 |
| JourneySetup.vue:28-29,33-34,38-39,41 | 来源 tabs；source 章节 select/确认 checkbox；整理中完成；世界/身份/开场 input/textarea；确认 checkbox；导入/进入阅读 | tabs/表单原生即时；整理中手动完成；进入 disabled 直到确认 | M03/M04/M05/M06/M09/M12 | 整理中不可进入；原生控件保留焦点；无模型/动画伪成功 | F01-F02 测试通过；待浏览器准备连续性 |
| MapPreview.vue:24,26,28,30-38 | 图层/视图 tabs；空态；地点搜索/标记循环；详情；结构表格/编辑；来源 select；变更审阅；时点 range；排演停止/完成 | tabs/地点即时；地图标记 M10；排演手动进行/停止/结果；图片失败 notice | M01/M03/M05/M06/M09/M10/M12/M14/M16 | 不依赖拖动；停止不产结果；失败保留资料；减效取消地图/结果动效 | 源码已读；待浏览器地图/窄屏 |
| PreviewDialog.vue:46-47 | 关闭面板图标按钮 | dialog 内焦点/关闭由组件控制；CSS 可反向过渡 | M02/M15 | Escape/关闭还原触发点；减效即时关闭 | 共享组件规则；浏览器由主代理 |
| PreviewNotice.vue:11,14 | state notice action；empty action | state key 变化入场；loading spinner；empty 直接显示 | M01/M12 | 状态替换不排队；减效由共享 motion 控制；action 不宣称真实成功 | 共享 M12 规则；源码已读 |
| ReaderPreview.vue:23-30 | 空态/错误/等待停止/重试；分支循环；自定义输入/反馈；回顾/来源 tabs；长期约定 textarea；资料 select/checkbox；details | 阅读静态；分支选中 M11；等待 spinner 仅手动 stage；details/辅助即时 | M01/M04/M05/M06/M07/M09/M11/M12/M15/M16 | 已读文本和输入保留；停止/超时不生成；辅助可关闭；减效停止 spinner | 源码已读；待浏览器键盘、滚动与焦点 |
| RedesignApp.vue:129-154,159-169,173-181 | 品牌/项目 ActionMenu；workspace ActionMenu；导航循环；主题/焦点/侧栏/助手；移动工作区菜单；页面切换；preview details/select；dialog slot | 导航/主题即时；ActionMenu/dialog CSS 过渡；子组件低频 vReveal；KeepAlive 保留 | M02/M03/M07/M08/M13/M15/M16 | Escape 关闭 dialog/专注；打开页聚焦 main；切换取消旧动效 | 源码已读；主壳连续路径待验 |
| SearchPreview.vue:43-55 | 搜索 form/input/button；方式/版本 select；高级范围 details/select/input；分类/结果循环；来源详情关闭/status；定位/钉选 | 输入无入场；分类 vReveal；来源详情 vReveal；select/details 原生 | M01/M03/M05/M06/M07/M08/M09/M14/M15/M16 | Escape 关闭详情还原触发；连续输入不播放逐字动画；减效取消淡化 | ROOT 评审已指出 version 过滤风险；待浏览器 |
| SettingsPreview.vue:24-30 | 设置 nav；名称 input；账户 details；模型/图片 select/password；连接按钮/progress；偏好 number/select/checkbox；导入偏好 details；主题循环/资源按钮；帮助/危险确认 | 设置/主题即时；连接验证手动进行/通过/失败；progress 仅验证中；危险确认 notice | M01/M03/M04/M05/M06/M07/M12/M13/M15 | 忙碌禁重复；危险可取消；凭据 disabled；减效原生静态 | 源码已读；待浏览器设置切换/焦点 |
| StructurePreview.vue:32-45 | loading/empty/error retry；结构 tabs；篇章/线索/场景循环；创建 form/input；场景 tabs/filter/select；剧本状态 select；排演按钮/progress；结构编辑 textarea | tab/筛选即时；vReveal 低频结构；排演手动开始/停止/结果；输入无逐字动画 | M01/M03/M05/M06/M08/M09/M12/M14/M16 | 停止/结果手动；表单取消；减效直接切换；error retry 需保持明确状态 | ROOT 评审发现 error retry 文案矛盾；源码未实看 |
| VersionReview.vue:24-28 | 版本行循环；比较切换；正式确认；左右版本 select；恢复/移入历史；确认/取消/结果 details | 版本选择/比较即时；确认结果手动；diff 静态 | M01/M03/M06/M08/M09/M12/M15/M16 | 取消保留版本；恢复/正式确认说明作品范围；后续整理独立 | 源码已读；待浏览器宽比较与焦点 |
| WorkspacePreview.vue:41-55 | 概览继续/计划/灵感；作品筛选/搜索/卡片循环；编辑详情 input/textarea；归档确认；任务 checkbox/编辑/来源；结构/地图/查找循环入口 | 卡片/列表 M09；搜索原生；编辑结果本地即时；地图标记/筛选沿对应族 | M01/M03/M04/M05/M06/M09/M10/M14/M15 | 归档 confirm；详情关闭；KeepAlive 保留局部状态；减效静态 | ROOT 评审已指出编辑对象切换可能丢草稿；源码未实看 |
| WorldConnections.vue:40,49 | 关系对象列表循环；地图/写作/来源导航 | 列表即时；SVG 图静态 | M08/M09/M10/M16 | 列表提供图谱非拖动路径；减效静态；审阅由 WorldReview 承接 | WORLD 修复后关系图/审阅分开；待浏览器 |
| WorldDetail.vue:64,71-72,85-88,98-103,110,114-117 | 详情关闭；编辑 role/note；图片 select/添加/替换；保存/取消；写作/来源；管理 details/归档确认 | 编辑/图片状态原生；图片 loading spinner；详情由父级低频切换 | M01/M02/M05/M06/M07/M09/M12/M15/M16 | 取消回滚；图片失败文字仍可读；归档先确认；减效停止 spinner | WORLD 修复后按 entry.id 保留草稿；待浏览器 |
| WorldImport.vue:55,58,64,75,78-79,83-85,88-89 | 世界书 tabs；错误重扫；目录扫描；工作稿/范围/审阅；文件循环详情；健康检查；历史筛选/恢复 | 扫描/健康/历史手动；失败重扫状态明确；tabs/筛选即时 | M01/M03/M06/M07/M09/M12/M14/M15 | 重扫收起错误；健康不等于通过；历史按状态回范围/失败步骤；减效直接状态 | WORLD 修复后测试通过；待浏览器 |
| WorldPreview.vue:79,91,98,107,114,117-118,123,131,148 | 空态/重试；分类循环；搜索；列表/卡片密度；关系图谱/审阅 tabs；条目循环；清除筛选 | 分类/密度即时；条目 vReveal；关系子视图 KeepAlive；搜索无逐字动画 | M01/M03/M05/M08/M09/M12/M14/M16 | 跨入口不清空 selected；关系审阅独立可达；减效直接切换 | WORLD 修复测试通过；待浏览器 |
| WorldReview.vue:79,85,87-88,96,112-114 | 搜索；全选/批量确认拒绝；待决定 checkbox/逐项决定；比较入口 | 筛选/选择即时；比较交主壳 CandidateReview；过期确认禁用 | M01/M03/M05/M09/M12/M14/M15 | 过期仍可拒绝；KeepAlive 保留决定；批量确认遇过期阻断；减效静态 | WORLD 修复后关系 kind 可达；待浏览器 |
| WritingPreview.vue:125-172 | 章节目录/搜索/管理 checkbox/删除恢复；正文标题/编辑；保存/成功/失败/冲突；稿件身份 select；资料 tabs；跨域入口 | 输入无回写；章节/资料低频 vReveal；保存与失败手动；select/details 原生 | M01-M09/M12/M14-M16 | 输入、选区、章节草稿保留；失败/双失败/冲突保全；只读身份禁写；减效取消正文过渡 | P01a/P01b 测试通过；主代理已浏览器验中文输入/Enter/Undo/换章明暗 |

## 当前可证实的漏项与风险

- Import/Journey/Candidate/World 新增控件已纳入本账，但尚无本报告自己的浏览器证据；主代理的截图/录屏应补到验证列。
- RedesignApp 通过 KeepAlive 和父级 motion 控制共享页面切换；子组件 vReveal 只应用于低频内容，输入本体未发现逐字动画或定时器成功逻辑。
- 关系审阅在 WorldPreview 修复后有独立可达 tab；图谱本身仍是静态辅助，必须以列表完成选择。
- 新页面样式均按组件根节点或现有共享命名空间限定；workspace-details.css 的嵌套写法属于既有共享样式，本次未改动。
- “控件声明存在”不等于动效、焦点、窄屏或连续路径已通过；真实结果须由主代理/独立验收报告补齐。

## 统计方法与限制

统计使用 ripgrep 对当前 SFC 的原生/复用控件开标签进行机械计数，循环按声明位置记录，无法代表运行时实例数。PreviewIcon 不计控件；slot 内由 RedesignApp 声明的 dialog 条件按声明行记录。未读取正式产品控件，也未运行浏览器、模型、API 或真实数据验证。
