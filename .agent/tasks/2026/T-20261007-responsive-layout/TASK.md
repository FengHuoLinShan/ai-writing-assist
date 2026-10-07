---
id: T-20261007-responsive-layout
title: 全站屏幕自适应布局与回归测试深化
status: active
created: 2026-10-07T14:08:09+09:00
updated: 2026-10-07T16:27:52+09:00
---

# 全站屏幕自适应布局与回归测试深化

## 恢复快照

- 实际完成：响应式实现、三处 P2 和上传同根遗漏已修复；完整本地质量门禁通过，Standards/Spec 独立复查无剩余 findings。
- 当前里程碑：Backend 7142 passed/3 skipped，coverage 86.31%；Vitest 2795；deployment 272；lint、build、依赖审计通过。最终浏览器与固定 head PR 合并进行中。
- 下一步：核对最终 WebKit 与完整 Chromium 结果，提交创建 PR 并附加到当前任务；确认固定 head 全部必需检查和主干基线后合并，独立核对 merge SHA 的 main CI。
- 阻塞：无。匹配 Playwright 1.63 的 WebKit 已安装；本机浏览器启动需沙箱外执行。
- 工作区：`/Users/tywww/.codex/worktrees/responsive-layout/ai-writing-assist`，`codex/responsive-layout`，基线 `85fb1c7be35ae687f949863d179f5fd63c53f3c0`。主工作区未跟踪文件全部保留；用户已授权修复、提交/推送 PR 及合并；没有部署或其他工作树清理授权。
- 最后核实：2026-10-07T16:27:52+09:00

## 目标与验收

- 全站现有任务可在手机、平板、桌面、宽屏、横屏和矮窗口完成；自动收纳不丢草稿、选区、章节、分支和阅读状态。
- 共享布局和页面特例修复；地图非拖动调整入口；Chromium 全套与移动 WebKit 核心行为回归；CI 失败关闭及权威文档同步。
- 全站基础：320×740、390×844、768×900、1280×800、1920×1080。写作/审核/地图/RP 扩展：900×800、1024×768、1440×900、2560×1440、844×390、1000×500；断点两侧与连续尺寸切换。
- 实机键盘、安全区和真实 Safari/浏览器缩放单列，不能由模拟测试冒充；不新增业务 API、数据库迁移、依赖、第二套手机控制器、像素/CSS 源码门禁。

## 上下文与边界

- 复用 WorkspaceDrawer、useModalDialog、ActionMenu、RP visualViewport 测量、现有 API 和持久化控制器。
- 用户确认：手机全部现有任务可操作；Chromium + 移动 WebKit 核心流程。
- 自动化只使用本任务可丢弃 PostgreSQL 与合成素材，不运行付费模型，不接触 `ai_novel_acceptance_guimi`。
- 主工作区的旧 Vite 代理问题已在 origin/main 修复，不重复修改；旧 untracked ADR 副本影响主目录 docs-check，仅干净工作树验证本任务。

## 里程碑与进度

- [x] 基线浏览器复现证据与专用环境
- [x] 共享滚动/浮层/视口及作者布局、状态保留
- [ ] 地图触控替代：实现及原测试完成，review 发现未保存预览和键盘误定位问题待修复
- [ ] RP 矮屏适配与长篇阅读锚点：长回复中段 resize 跳回开头待修复
- [x] 响应式矩阵、移动 WebKit、CI/文档
- [ ] lint、完整 Vitest/build/功能浏览器/辅助套件/文档门禁已通过；独立审查三项 findings 尚未关闭

## 决策、发现与失败

- 现有 responsive helper 两个视口且无消费者；尺寸用例分散，需共享行为检查而非截图门。
- 地图图片标注拖动受 ≤900px 和 pointer:fine 限制，缺少同等非拖动入口；复用带 expected_updated_at 的更新接口。
- 作品页内部 grid/flex min-content 裁切不增加 document.scrollWidth，必须检查实际控件边界和点击命中；768px 基线截图 `/private/tmp/responsive-baseline-project-main-768.png`。
- WorkspaceDrawer 原条件分支重建 slot，导致次级未保存表单丢失；保留单一 slot 并用 Teleport/v-show 收纳，旧测试改为不可见断言，仍验证分页/切换/执行。
- 使用全新 `ai_writing_responsive_20261007_agent_e2e_test`、独立受限 MinIO buckets；配置仅在 `/private/tmp/responsive-e2e-env.sh`，不记录凭证。节点依赖和 Python venv 链接原工作区，运行时 UV_NO_SYNC=1，禁止依赖同步。
- 长篇 RP 暴露窗口重排后阅读锚点离开视野，复用已有 session 锚点在 resize 后定位；WebKit 的 scroll-margin 亚像素误差还导致锚点误识别上一段，位置比较容许 1px。移动关闭写作资料后主动恢复真实打开按钮；不靠测试强制聚焦通过。
- 移除手机隐藏 PNG 蒙版文件控件的规则；复用现有修改/费用确认，不在响应式测试中发起模型调用。
- 完整功能回归的空项目用例受到最早走查夹具残留影响（标题“响应式走查：一部需要在各种尺寸下安心继续创作的长标题作品”，ID `74021c32-adfe-4d61-a739-297e784d9d2d`）。已核对唯一身份并用原清理 API 严格删除该合成项目，不清理当前其他用例；需在全套结束后重新验证空态，保留首次失败记录。
- 世界书摘要超时的 worker 输出证明两个旧 `rag_index_chapter` 及 `publish_chapter` 任务均属于该走查夹具，16 秒本地 BGE 冷启动阻塞摘要排队；没有修改任务超时或业务语义，清理后重跑验证。
- 辅助套件隔离在新建 `ai_writing_responsive_aux_20261007_agent_e2e_test`，backend 18310/frontend 18390，主功能仍为 18300/18380。只运行合成模型 harness/feature flags，不运行付费模型。
- 首轮写作响应式旧用例仅在 ≤760px 打开资料，900px 原内联“展开”入口收纳后不再可见；迁移到真实“本章资料”按钮，保留唯一摘要与触控断言，不恢复固定布局。

## 验证证据

- 干净基线 `make docs-check` 通过；计划阶段主工作区相关4个 Vitest文件107项通过（历史基线证据）。
- 实现中针对性 Vitest 78 项通过；首轮完整 2792 项中 3 个旧断言受 Teleport/v-show 改动影响，已保留行为断言并修正定位，需复验。
- 后端 CI 安全与 browser aggregation 43 项通过，Ruff 通过；新增完成标记测试证明完整首分片缺少 WebKit 标记会失败，smoke/第二分片不误要求。
- Chromium 新增全站路由/尺寸矩阵 20 项与核心 9 项全部通过；此前地图/公共阅读器/RP 失败已修正并跨引擎通过。
- 最终移动 WebKit 10 项通过（9 个新增核心场景 + 既有 RP SSE 重复/缺口快照恢复）；证据 `/private/tmp/responsive-webkit-final.log`。中间失败均已复现修复，未用重试掩盖。
- 补强登录错误/协议链接和蒙版五档断言后，最终移动 WebKit 10 项再次通过；证据 `/private/tmp/responsive-webkit-checked.log`。
- 完整 Chromium 复验 333 项通过、0 失败（workers=1、retries=0，9.1 分钟），包括三个首轮失败路径；证据 `/private/tmp/responsive-functional-final.log`。原两个 100/1000 份资料性能专项按 `RUN_WORLD_LIBRARY_PERF` 原门禁跳过，不算功能用例通过。
- 辅助 Chromium assistant 1、creative 6、editorial 1 项通过，证据 `/private/tmp/responsive-{assistant,creative,editorial}.log`。
- 最终 lint、完整 Vitest 222 文件/2792 项通过；证据 `/private/tmp/responsive-vitest-checked.log`。最终生产构建及产物验证通过：16 引用、59 JS bundles、95 assets；证据 `/private/tmp/responsive-build-checked.log`。
- `make docs-check`、`make docs-check BASE_REF=origin/main`、`git diff --check` 通过；文档已同步设计规范、写作/地图、前端模块、README 和测试指南。
- `make secret-hygiene`、受影响 Python Ruff check/format 通过；最后修改的 E2E 文件 ESLint 通过。本地 Node 22.22.3，CI 保留仓库锁定版本。

## 覆盖映射

| 场景 | 自动化入口与证据 |
| --- | --- |
| 作者作品、写作、世界资料/对象/关系/别名/决定、故事总纲/篇章/剧情线/场景、检索、地图、AI owner 入口、账户/作品偏好 | responsive-layout 17 路由，基础五档；写作/审核/地图十一档 |
| 写作首页、计划新建/保存、场景详情、作品长标题/长来源和列表末项 | responsive-layout；计划输入跨尺寸保留，列表真实点击 |
| 首页、旅程列表、故事阅读 | responsive-layout；RP 十一档 |
| 正文/选区/未保存批注/桌面栏偏好、保存失败重试与刷新 | responsive-core，Chromium + WebKit；保存读回真实专用库 |
| 759/760/761、899/900/901、1099/1100/1101、1149/1150/1151 和 320px 重排、两倍控件字体 | responsive-core；字体注入是放大模拟，非真实浏览器缩放 |
| 地图触控点选/取消/方向微调、绑定标注拒绝、409 保留并重读版本、蒙版文件保留 | responsive-core，Chromium + WebKit；仅合成 PNG/接口 mock |
| 长篇 RP 当前发展/输入/阅读锚点跨尺寸与刷新、矮屏回顾、SSE 持久恢复 | responsive-core + interaction 原流式用例，Chromium + WebKit |
| 登录、只读公开演示切章与作者接口不访问 | responsive-core，Chromium + WebKit |
| populated 世界政策编辑器及保存入口十一档 | world-review-phase4；完整功能套件复用原真实保存断言 |
| 视口键盘收缩/偏移/捏合放大/释放、抽屉跨模式草稿及 inert 清理 | visualViewport / WorkspaceDrawer 单元测试 |
| CI WebKit 完成标记/全套首分片/无条件聚合失败关闭 | repository_security_automation + browser_gate_aggregation 43 项 |

视觉检查：768px 写作双栏、世界资料页实图已查看，未见必要内容裁切；诊断截图位于未跟踪 test-results，不作为像素门禁。

## 交付结果

- 已交付：实现、对应测试、CI 完成标记门禁、权威文档及可复现的本地验证记录；审查确认保留保存/隔离/绑定图元/CAS 边界，无新增依赖或业务 API/schema。
- 未交付：真实 iOS/Android 软键盘、安全区与浏览器缩放验收；显式大库性能专项；远端 CI 和发布。
- 交付边界：仅本地工作树；实机未验证；未提交/推送/合并/部署。


## 2026-10-07 独立 review

- 范围：基线/HEAD `85fb1c7be35ae687f949863d179f5fd63c53f3c0`，`codex/responsive-layout` 的 40 个未提交文件（含 untracked）；冻结 diff、文件副本和 SHA256 manifest 在 `/private/tmp/responsive-review-20261007/`。Standards/Spec 两条线独立审查，主 Agent 复核触发路径。review 不修改产品代码，不接触真实数据或模型。
- Standards P2：`frontend-console/vue/views/map/MapWorkspaceView.vue:989` 的 watcher 在 tab 切换时无条件清除 annotationEdit。已保存结构地图上调整独立图片标注后点击“添加地图画面”，`startRun` 在参考资料确认前切换 tab，未走离开保护；取消确认也无法找回预览。违反 AGENTS.md:63 和 design-standard.md:69 未保存输入保护。建议先走统一离开保护，并保留后续确认取消时的编辑状态。
- Standards P2：同文件 :164 新 click 绑定在编辑期间把键盘按钮激活交给 :541 坐标处理。原生 Enter/Space click 的 clientX/clientY 为 0，当前位置被错误夹到 (0,0)，后续可误保存。违反 AGENTS.md:59 基本可访问性。建议区分键盘激活与指针点选，验证编辑期间焦点+Enter/Space。
- Spec P2：`frontend-console/vue/views/interaction/InteractionView.vue:1970` 的新增 resize 处理只定位消息开头，没有保留消息内部阅读偏移，违反目标“自动收纳不丢…阅读状态”。合成 90 段回复中读到第 45 段，390×844 → 390×640 后 scrollTop 3431 → 219，第 45 段离开视野；宽度改变同样跳回回复起始。Chromium/WebKit 均复现；仅禁用新增 listener，height-only resize 保留 scrollTop 3431 和原段落。建议保留消息内阅读锚点/偏移，补中段连续 resize 检查。
- 证据：`node /private/tmp/responsive-review-20261007/standards-probes.cjs` 主 Agent 复跑通过断言，输出 cancelled generation annotationEdit=null/discardConfirmCalls=0 和 keyboard position=(0,0)；它使用冻结源函数及 Vue watch，不是完整地图浏览器 E2E。原生 Chromium 按钮 Enter 另证实 click 坐标为 0。
- RP 全页浏览器 mock 探针：`/private/tmp/responsive-review-20261007/rp-resize-probe.mjs` 与 `rp-resize-results.json`，两引擎均无 pageerrors/unhandled API；没有后台/真实数据库/模型调用。专用 review Vite :18480 已停止。
- 本次 review 交付边界：只纠正任务状态和记录 findings；未修复、未提交、未推送、未合并、未部署。原测试绿色不能证明上述路径满足验收，当前不建议合入。


## 2026-10-07 review 修复与合并

- 用户追加授权：“修复，然后合并”。当前任务推进到固定 head PR 合并及独立主干 CI 核对；保留所有其他工作树/未跟踪文件和真实 Guimi 库，不运行付费模型、不部署。
- 根因修复：startRun/derivePage 复用 canLeaveStructure；结构生成延后到服务端确认创建成功才切 tab，取消或失败保留当前标注。坐标定位拒绝 detail=0 的键盘 click，指针/触控点选继续有效。
- RP 使用现有 session 阅读存储追加当前回复内 blockIndex 与 anchorOffset，resize/刷新走同一恢复函数；旧存储无偏移时继续按消息锚点恢复，加载窗口失败仍保留数字 scrollTop fallback。
- 地图/RP 定向 Vitest 113 项通过；新地图测试首次使用错误 class 定位，已改为实际控件并通过，没有降低断言。证据 `/private/tmp/responsive-fix-targeted.log`。
- 前端 lint 通过；移动 WebKit 11 项通过，包括原生 Enter/Space 与段落中段跨尺寸/刷新。证据 `/private/tmp/responsive-fix-{lint,webkit}.log`。

- 独立复查发现上传成功换图同样会丢预览；已将 submitUpload、archivePage、restorePage、reviewPage、retryPage、resumeRun、saveNodePosition 接入已有 canLeaveStructure。拒绝上传不发请求，允许后上传失败仍保留标注、文件与标题；同时防止重复上传。Standards/Spec 再次只读复查均无剩余 findings。
- 完整 `UV_NO_SYNC=1 make test-ci TEST_WORKERS=2` 通过：Backend 7142 passed/3 skipped，coverage 86.31%，前端 222 文件/2795 项，deployment 272，以及文档、secret hygiene、后端 lint、双端依赖审计；有 12 个非 RuntimeWarning 的既有诊断警告。证据 `/private/tmp/responsive-fix-test-ci.log`。
- build 验证 16 local references / 59 JS bundles / 95 assets；lint 通过。证据 `/private/tmp/responsive-fix-{build,lint-final}.log`。
- 新上传 WebKit 用例首轮漏打开“图片与底图”，按真实入口定位修正，保留取消不发送/失败保留两份草稿的断言。证据保留 `/private/tmp/responsive-fix-webkit-final.log`；其余 11 项通过，最终 12 项复验中。
- 为验证最终修复版本，停止补齐上传 guard 前的中间 Chromium 全套，保留 `/private/tmp/responsive-fix-functional.log`，该中止结果不作为完整通过。

- 最终移动 WebKit 12 项全部通过，33.8 秒，workers=1/retries=0；新上传/移出取消与上传失败草稿保留的原生弹窗路径通过。证据 `/private/tmp/responsive-fix-webkit-checked.log`。完整 Chromium 对最终版本运行中。
