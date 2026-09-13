---
id: T-20260912-desktop-redesign
title: 全站桌面视觉与组件预览
status: completed
created: 2026-09-12T13:59:49+08:00
updated: 2026-09-12T15:02:20+08:00
---

## 目标与交付

已实现用户确认的全站桌面视觉/组件演示：`/prototypes/redesign.html`，默认写作；macOS精细层级、鲜明语义色、浅深色与功能动效。正式业务后续接回，本轮不接真实保存/生成/采用，不做移动端，不提交/合并/推送/部署。

## 恢复快照

- 工作区：`/Users/tywww/Desktop/项目/ai-writing-assist`，`codex/redesign-regression`。前两轮143个tracked文件WIP保留，初始补丁在 `/tmp/novelcraft-preview-initial.patch`；本轮前后按文件diff核对，除两份授权设计/入口文档与任务索引外，原tracked差异完全相同。
- 已完成：全部样板与子视图、组件状态、浏览器检查、动效录制、单测/lint/build/docs。
- 本地预览运行于 `http://localhost:8097/prototypes/redesign.html`，Vite exec session 28038，保留服务与浏览器交付页供用户查看。重启：`cd frontend-console && FRONTEND_PORT=8097 npm run dev`。
- 下一步：用户查看预览后按反馈细化设计；业务接回需另行范围确认，不自动推进到正式产品。
- 阻塞：无。

## 实现与决定

- 原型位于 `frontend-console/prototypes/redesign/`，使用Vue组件、CSS、统一虚构《潮汐来信》数据。入口沿用现有开发原型模式，不进入生产dist。
- 复用既有NavIcon与ActionMenu；采用原生dialog和CSS过渡，未新增依赖、测试平台、业务模拟服务或适配抽象。
- 样式限定在redesign-root，不加载正式CSS、账户、主题controller、bridge、API或存储。刷新恢复默认示例。底栏明确演示身份；业务按钮展示标记示例的反馈，不冒充真正保存。
- 蓝操作、紫候选、绿完成、橙待决定/可恢复问题、红阻断风险。作品、人物、地图、故事线用内容色彩；正文保持安静，重要提示就近呈现。
- 连续AI→比较面板保留最初焦点；专注/侧栏支持反向切换；原生dialog开关有过渡，减少运动/透明度有回退。
- 概览待决定及作品菜单偏好直达对应分区；切页刷新演示视图的滚动/分组，避免上页位置遗留。

## 覆盖与证据

详见 [COVERAGE.md](COVERAGE.md)。精选截图：[写作浅色](artifacts/writing-light.png)、[写作深色](artifacts/writing-dark.png)、[创作概览](artifacts/today-light.png)。
实际浏览器帧合成的 [动效录像](artifacts/writing-motion.mp4) 共3.77秒，包含专注、建议/比较浮层、关闭、概览和主题切换，仅缩短录制前闲置。
完整原始截图与记录在 `/tmp/novelcraft-redesign-evidence/`。

## 实际验证

- 前置 `make docs-check` 通过。
- 最终完整Vitest：177文件 / **2388 passed**，30.83秒；含4个新增预览行为/数据隔离检查。日志 `/tmp/novelcraft-preview-vitest-full.log`。
- 前端lint通过；生产构建通过，14本地引用、53 JS bundles、81发布资源路径；正式产品bundle未改变。日志 `/tmp/novelcraft-preview-lint-final.log`、`/tmp/novelcraft-preview-build-final.log`。
- Chromium真实浏览器：全站主页面；10个主要页面×3桌面宽度=30组合，另检12个资料/故事子视图、4个设置分区、身份/阅读/组件；无页面级横向溢出。写作5种反馈及正常状态可切换。
- 键盘菜单、dialog Tab/Shift+Tab与Escape、连续浮层原触发器焦点恢复、专注退出正常。
- 减少运动/透明度实测spinner animation=none与toolbar blur=none；模拟验证后清除，临时viewport已reset。
- 核心正文/辅助文字与语义色共17组对比检查全部≥4.5:1（最低4.73:1），见 [contrast.json](artifacts/contrast.json)。这是核心色对检查，不宣称完整WCAG认证。
- 网络记录22个本地资源请求，0业务API、0外部请求，无事件截断；浏览器无warn/error。存储getItem/setItem和IndexedDB open在单测中阻断并确认无访问，代码检查无业务/持久存储调用。
- `make docs-check BASE_REF=origin/main`、`git diff --check`通过。

## 修正与限制

- 初次隔离单测发现happy-dom未提供indexedDB，改用抛错全局替身验证无访问，未引入数据库模拟依赖。
- 浏览器不支持注入存储拦截脚本；改由真实网络记录+组件行为单测+进口调用检查验证隔离，没有声称浏览器已安装该拦截脚本。
- 演示不证明真实保存、恢复、生成、采用、模型质量、移动端或Safari/Firefox体验。这些明确属于后续业务接回/移动精修。
- 未创建数据库、修改对象存储、读取用户文件或真实账户数据；未提交、合并、推送、部署。

## 迭代2（用户授权持续改进与独立评审）

- 上一轮取得进展：7个Apple产品对照与独立评审形成10项具体问题；本轮据此修改，目标仍是全站Apple原生感的桌面视觉样板。
- 保留独立预览/无业务与无真实数据访问边界；不提交或部署。
- 优先：共享浮层离场布局、非模态上下文、文档单工具层、专注状态与焦点、标题/图标/提醒/阅读。
- 修改前样板副本：/tmp/novelcraft-redesign-before-iteration-2。
- 下一步：修改后真实浏览器复验，再由独立子代理评审，不以绿色测试替代审美。


## 迭代2最终恢复快照与完成审计

用户授权的改进—独立评审—修正—复验已收敛。旧10项问题、本轮新增4项问题以及3项轻微精修均已处理。
独立评审者最后复验无待修项，原始报告及修复证据保留在 [ITERATION-2-REVIEW.md](ITERATION-2-REVIEW.md)。

| 要求 | 当前证据 |
|---|---|
| 文档式写作层级 | 全站入口收进作品菜单、顶部合并工具组；正文18px，目录/资料按需；iteration-2-evidence/writing-light.png |
| 动效精工 | drawer基础布局保留、非模态正确右侧定位；独立当前退出录帧通过；iteration-2-evidence/motion.mp4 |
| 专注连续性 | 不改变字号、阅读位置保留；仅显示有效控件；Escape回同一触发器；独立浏览器与单测通过 |
| 上下文资料/建议 | 原生show非模态，正文可读可操作；比较并排；上下文面板和创建模态间切换焦点正确 |
| 高价值颜色 | 概览待决定橙色强调、导航类别色、稳定正文与候选语义色；深浅主题均检查 |
| 全站精修 | 高频页简短标题、SVG图标、紧凑世界条目/详情单列、清除重复脚部；设置对齐；阅读独立控件与行宽 |
| 组件与状态 | 创建仅一组动作、取消左主要右、首焦点名称；状态菜单从左下设计预览打开；6种状态可达 |
| 业务与真实数据边界 | 仅prototypes与测试/文档变更；不接后端、不读写真实账户/作品；存储与API阻断替身测试通过 |
| 独立评审 | 同一子代理两阶段复查，本轮最后3项再抽查，无待修项；未由实现者单独宣称视觉通过 |
| 验证/交付 | 以下最终命令与实际截图；未提交、推送、合并或部署，8097本地预览保留 |

### 最终验证（迭代2）

- 最终完整Vitest：177文件、**2392 passed**，31.73秒；/tmp/novelcraft-iteration2-final-all-tests.log。
- 8项预览行为检查包括全部入口、刷新重置、主题/专注内容保留、失败/冲突显示、无API/Storage/IndexedDB访问、非模态与文档控制、专注焦点、阅读隔离和外部触发任务的焦点来源。
- 最终lint、生产build通过；仍为14本地引用、53JS bundles、81发布资源；/tmp/novelcraft-iteration2-final-lint.log、/tmp/novelcraft-iteration2-final-build.log。
- 主Agent浏览器复验：10页面×1200浅色/1440深色=20组合，无页面级横向溢出；另17个世界/故事/设置子视图、组件6种状态、创建首焦点；新截图与JSON在iteration-2-evidence。
- 独立评审额外覆盖1200/1440阅读、非模态转模态焦点、世界详情单列、动作顺序、最后SVG/输入聚焦；证据在iteration-2-review-evidence。
- 系统减少运动/透明度：animation=none、blur=none，设置验证后清除。
- 本轮较早Network事件窗口发生截断；重新启用后该工具未捕获到预期静态资源事件，故不把后续空列表当成“浏览器零请求”的证明。数据隔离结论基于本轮有效行为单测与导入/调用链检查，保留工具观察局限；浏览器console无warn/error。
- CSS辅助格式化脚本曾因缺少循环索引更新空转，已终止本任务对应父/子进程，未写入文件；保留既有代码布局，只应用必要样式修正，最终验证在终止后重新运行。
- 文档门禁和diff检查见/tmp/novelcraft-iteration2-docs-final.log。

### 当前交付

入口仍为 http://localhost:8097/prototypes/redesign.html 。[最新写作截图](iteration-2-evidence/writing-light.png)、
[非模态比较](iteration-2-evidence/comparison-light.png)、[动效录像](iteration-2-evidence/motion.mp4)。

专业独立视觉评审判断已具有明显Apple式文档应用熟悉感；未进行真人5秒盲评，不将此声称为所有用户的识别结论。
业务接回、移动端、真实保存/生成和发布仍保持原计划的后续范围。下一步仅根据用户新反馈继续精修。
