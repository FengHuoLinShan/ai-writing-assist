---
id: T-20261018-author-workspaces-ai-redesign
title: 写作台、世界对象与 AI 协作统一改造
status: active
created: 2026-10-18T16:32:21+08:00
updated: 2026-10-19T01:37:07+08:00
---

# 写作台、世界对象与 AI 协作统一改造

## 恢复快照

- 同步 main 出现后续 #256（`a991a22db`，本地桌面应用），PR 转为冲突。本轮合并仅八处文档/索引追加冲突，逐块保留双方内容；Codex provider 的平台身份读取和 Writing 的 editorial-ready 更新自动合并后保留两边行为。写作视图86项、LLM基础设施493项、Ruff/全量ESLint与文档门禁通过。旧head `f016dbb65` 的远端后端9293/2 skipped、完整PG417/7 deselected、浏览器分片2 170/2 skipped与原历史用例均已通过，但不能冒充同步后head验收；同步提交推送后须等全套CI。

- PR CI 定位：旧 head 的浏览器分片2为169 passed/2 skipped/1 failed，唯一失败 `world.spec.js` 对象历史闭环点击隐藏的“改动历史”。详情改造后需先进入“经历与来源”；本轮只补该公开入口，全部备注/恢复/深链高亮/返回筛选断言保留。确切专用E2E库本地实际浏览器复验1 passed（11.8s，`/tmp/pr257-local-browser.log`），该文件ESLint通过；分片1及其余CI全部通过。合并前同步 main 的 #254（含PG历史失败测试修复与全PG门禁），随后推送本轮修复，等待当前SHA全部检查通过。

- 2026-10-19T01:37:07+08:00 用户要求检查 PR #257、修复失败 CI，并在全部通过后合并，已授权本轮修复/推送与条件合并；不含部署。当前 PR head=`0fe067f696fc526c9d908907b764631bbe8bb72b`，工作区原本干净。CI Backend quality、PostgreSQL critical、前端 unit、架构/镜像/安全与 repo-gates 已通过；functional browser shard 2 失败，shard 1 仍运行。正在取 shard 2 具体日志，下一步定位失败并复现根因；不得绕过失败或直接合并。

- 2026-10-19T01:20:59+08:00 当前分支完整实现已提交并推送，业务提交 `be537fbf8`；[PR #257](https://github.com/FengHuoLinShan/ai-writing-assist/pull/257) 已创建并附加当前聊天，目标 main，未合并/部署。提交后 repo-gates（0 二进制变化、76 个生产文件、发布证据、模块导入/依赖方向）与 secret hygiene、docs-check、diff 检查通过；Goal service 4653 行为非阻断提示。PR 已明确最新 3320 前端/1925 后端/14 WebKit 通过、既有 PG 基线失败及未验边界；远端 CI 刚触发，需按 PR 当前 SHA 核实，不宣称通过。此条交付记录另作纯文档提交并推送，后续合并或发布仍须授权。

- 2026-10-19T01:19:55+08:00 用户明确要求“此分支提交，开pr”，授权当前主题分支完整改动的提交、推送和创建 PR；不含合并或部署。已 fetch origin/main=`083843474e9880252fe4bfca1b1a7132262dc9b6`，当前 HEAD 落后其一条 CI 提交，保留分支名。暂存完整作者工作台实现、两轮评审修复及研究/任务文档，193 文件；secret hygiene 与提交后 repo-gates 在交付流程中核验。PR 将明确本地验证、既有 PG 基线失败、真实设备/作者验收边界，随后记录远端 PR。

- 2026-10-19T01:19:00+08:00 用户授权的第二轮整改 F1–F3 已完成，F4 不动。共享选择器保焦点/销毁清理、审批草稿恢复顺序、关系响应省略完整历史均已修复并有回归。完整前端 267 文件/3320 passed，World+Assistant 1925 passed，完整 WebKit 14 passed（含 click/tap 新用例）；Ruff、全量 ESLint、docs-check 与 diff 空白检查通过。详见 [REVIEW-FIXES-20261019.md](REVIEW-FIXES-20261019.md)。仅本地工程交付，原 WIP 保留；未提交/推送/合并/部署、未调用真实模型，真机 Safari/作者体验未验。下一步如获后续交付授权，按该记录核对工作区、提交后的门禁与评审；本轮无剩余实现项。
- 2026-10-19T01:04:00+08:00 第二轮独立评审（Claude Sonnet 5.5，只读，未改业务代码）因 1 项必修回归重新打开本任务：F1 为 Safari/WebKit 下共享引用选择器点选不中结果，已用真实 WebKit 复现并验证一行修复；另有低风险 F2（恢复讨论时审批请求被清空）、F3（关系修改历史无上限且随列表带出），F4 仅为不要求处理的加固说明。整改尚未开始，`active` 只表示整改工作开放，当前无人在执行。下一步：按 [REVIEW-HANDOFF-20261019.md](REVIEW-HANDOFF-20261019.md) 第 8 节先核对工作区指纹，再做 F1。本条不授权提交、推送、合并、部署、真实模型或子代理，整改须用户明确要求；下方 R1–R7 与前次交付的结论仍是各自时点的事实，保留不改。
- 用户要求修复的 R1–R7 已全部完成，扩大门禁发现的能力/路由/固定预算治理遗漏与清单 novel_id 索引也已补齐。完整快速后端 9291 passed / 2 skipped，覆盖率85.32%；前端267文件/3318 passed；针对性PG24、浏览器8项通过。PG critical最终105 passed / 3个已确认历史失败；全仓format剩余167个全部是干净HEAD基线，无新增。最终lint、docs-check BASE_REF=origin/main与diff空白检查通过，本地修复交付关闭。详见[REVIEW.md](REVIEW.md)、[ENGINEERING-BASELINE.md](ENGINEERING-BASELINE.md)。
- 2026-10-18T23:26:00+08:00 审查确认7项新增P2并触发任务重新打开；用户随后明确要求修复。原始失败和本次整改证据均保留；前次completed不覆盖本次新发现。本轮未新增真实模型、共享库、提交或发布操作。
- 前次交付：HANDOFF六批本地实现、当时适用工程和浏览器验收完成；批准判断指定模型完整校准18/18通过。2026-10-18T23:09:36+08:00 曾按此关闭平台goal；详细历史证据见[ACCEPTANCE.md](ACCEPTANCE.md)、[CALIBRATION.md](CALIBRATION.md)。本次审查发现及当前未完成项以上方事实纠正和REVIEW为准。
- 工作区：原分支`codex/writing-workbench-ai-research`，HEAD `98598127f933782f26019ca0e9970c53849c2a97`，全部改动仅本地未提交，保留原WIP；无推送/合并/远端CI/部署。主Agent未委派。
- 历史工程和跨流浏览器证据保留在ACCEPTANCE；本轮增加暂停/预算/创建产物的自动批准、关系原空值恢复、迟到保存跨页草稿、编辑撤回后刷新、修改组终态后重新选择的回归。真实API/PG/worker，模型IO合成；全量ESLint、Ruff lint及修复文件format通过，既有全PG24项基线仍不宣称全绿。
- 新索引 head=`20261018_review_scope_index` 只升级本任务两套专用测试库；原 Guimi/G7b/校准库未动。本轮主Agent实施，未委派、未重跑真实模型。
- 用户指定G7b v3 evolution `06f08dc3-7b61-449a-b754-95f9de84a118` / Codex / 仅Luna，覆盖下方旧默认guimi推断。此前选早了的DeepSeek17/18和G7b部分7请求均只作失败历史，不拼接最终成绩。
- G7b新完整校准：明确新授权18请求/262144 token，Luna/low经Project；18/18正确、falseallow0/falseblock0、18settled/0unknown、完整175726token，无重试。额外授权的1次Luna/max正常连接验证已完成。新指纹绑定schema保留执行端复验；副本当前只读availability=true，其他作品未获回执。
- 原G7b库`guimi60-v3-pg-20261015` / `agent_e2e_guimi60_v3`未迁移/写入/续跑。私有父目录`/Users/tywww/.codex/private/author-workspaces-luna-calibration-20261018-224122`；完整备份3391585bytes、父目录0700/文件0600，最终`live-calibration-bound-v1`账本和`completion-verification.json`保留。原库与副本120条writing_drafts全字段指纹校准后仍同为`3b0060f5e6a8a6c3406fc0e0a4940616`。
- 隔离测试容器`ai-writing-assist-author-workspaces-e2e-20261018` / loopback64659；functional/PG第一库`ai_writing_assist_e2e_test`，assistant/creative第二库`author_workspaces_agent_e2e_test`，校准副本`author_workspaces_luna_calibration_20261018`不启动worker。无在途模型请求，禁止恢复旧失败账本自动重试。
- 后续：本轮修复无剩余实现项；提交/合并/部署或扩展真实生成、证据利用和文学质量实验仍须遵守相应授权与验证边界。真实作者体验、文学质量、非Chromium与真实软键盘未验，不以工程绿色冒充。

## 目标与验收

- 目标：按 HANDOFF 落地两个作者工作台的完整体验重组、关键能力扩展及统一自动修改模式。
- 完成条件：六批交付、接口兼容及相关工程与浏览器验收完成；模型质量和作者体验单列实际证据，不以自动化测试代替。
- 用户明确要求“设定目标为全部做完 HANDOFF.md”；六批交付与验收现已完成，不把阶段性代码切片视为完成。
- 校准按最新 G7b / Codex / Luna 专项授权和预算执行（详见恢复快照），仅无正文合成判断；不扩大到稿件/其他业务模型实验、原评测续跑、提交/推送/合并/部署。历史工程环境授权与模型决定见下方检查点。

## 上下文与边界

- 完整产品决定、批准模式、模型选择、接口变化与验收以 [HANDOFF.md](HANDOFF.md) 为本任务计划的单一来源。
- 研究依据：[写作台研究](../T-20261018-writing-workbench-ai-research/RESEARCH.md)、[世界对象研究](../T-20261018-world-object-ai-research/RESEARCH.md)。研究中的未决方案已由本轮用户选择收敛，不能恢复旧选项覆盖新决定。
- 任务记录本身不新增授权；用户授权专用隔离E2E环境及上述限定G7b/Luna合成校准，不授权真实稿件外发、原评测续跑、发布或默认库写入。测试按当前testing-guide使用专用容器。
- 与既有助手操作底座、档案／导演任务存在共享代码；恢复时核对其最新进展，不复制重建。

## 里程碑与进度

- [x] 第二轮独立评审整改 F1–F3（F4 不要求）：本地实现与适用单测、完整前端/World/Assistant/WebKit 门禁通过，真机验收单列；见 REVIEW-FIXES-20261019.md。
- [x] 审查整改 R1–R7及扩大门禁遗漏：本地实现、完整快速层/受影响浏览器/PG及基线分类完成，最终文档检查收口。
- [x] 汇总两份研究及用户已确认的产品决定。
- [x] 形成可独立阅读的实施 handoff。
- [x] 批次 1：统一上下文与恢复（精确焦点/有限集合/临时正文/隔离备份/固定摘要/返回定位已交付，相关工程与真实浏览器通过；真实模型与作者体验单列）。
- [x] 批次 2：两个工作台重组（四路径、固定对象/前文、按需助手、详情四分区及搜索关系端点；工程与浏览器通过，后续完整跨流验收仍属批次 6）。
- [x] 批次 3：统一批准机制（共享授权/判断/撤回/执行回执与并发门禁，指定G7b/Luna/low固定18案例全通过）。
- [x] 批次 4：精细修改闭环（选组派生重审/采用/继续手改、关系版本维护与恢复已通过工程及合成浏览器；真实质量单列）。
- [x] 批次 5：复杂任务与全库整理（服务器冻结版本清单、分页处置/恢复、精确依赖身份/目标/版本和 PG 并发通过，复用既有预算/部分成功回执）。
- [x] 批次 6：整体验收与收尾（完整适用工程/浏览器/操作帮助与文档，模型和作者质量分列实际边界）。

## 决策、发现与失败

- 2026-10-18：用户要求完整重设计并同时纳入世界对象研究；选择资料保留、助手按需，重组与能力扩展都做，直接按选定布局实施而非先做原型对照。
- 2026-10-18：用户要求共用 Approve for me 模式，指定配置中的轻量模型以 low 档判断；明确允许在任务范围内代批正文采用与已采用设定修改，保留领域人工确认事项。
- 2026-10-18：用户先要求将计划写成 handoff；随后明确要求执行，主任务状态转为 active 并开始批次 1。
- 2026-10-19：第二轮独立评审重新打开本任务。依据：本任务自己声明“非 Chromium 未验”，评审用真实 WebKit 复现了 20:17 检查点新增的 focusout 关闭使共享引用选择器点选失效（HEAD 选中 1 项，工作区 0 项）；复现数字、其余发现与已验证范围见 REVIEW-HANDOFF-20261019.md。

## 验证证据

- 2026-10-18：`make docs-check BASE_REF=origin/main` 通过；无架构敏感源码变化。
- 2026-10-18：本任务两份新文档的 26 个相对链接全部可达，逐行空白检查通过；另运行 `git diff --check` 检查已跟踪索引改动。
- 第 6 轮：`make test TESTS="modules/assistant/tests modules/world/tests/test_assistant_focus.py tests/unit/test_facade_public_api.py" ARGS="-q"` → 309 passed；受影响前端 5 文件 Vitest → 65 passed。角色扮演只重放可证明的 RP 回合，拒绝缺失/非法上下文、作者回合和带焦点回合（含相同 confirmation）；关系摘录覆盖类别、详细类型、方向、零强度、采用状态、有限/无界生效范围和截断后仍保留作者警告。
- 同对象刷新最小组件用例先红（档案编辑器被卸载），修正 Vue watch 为独立身份 sources 后绿。新增 `frontend-console/e2e/world-workspace-recovery.spec.js`：两种宽度均验证对象本机持久化→刷新恢复、服务器正文未被改写、不串另一对象、新档案刷新恢复/显式保存、已有档案修订草稿恢复；保留严格 browserErrors 断言。fixture 经正常 CSRF 头预建真实空模板，避免把合法的“模板不存在”404 当运行错误。
- 浏览器命令共用显式 `DATABASE_URL`、`E2E_DATABASE_URL`、`PW_REUSE_EXISTING_SERVER=0`、`BACKEND_PORT`、`FRONTEND_PORT`、`API_HOST`、`API_PROXY_TARGET`；凭据只经进程环境，不写入仓库。普通功能使用首个库、8029/8089；`npx playwright test --config playwright.functional.config.js world-workspace-recovery.spec.js --output test-results/workspace-recovery` → 2 passed。助手使用第二个库、8028/8088；`npx playwright test --config playwright.assistant.config.js --output test-results/author-assistant` → 5 passed，真实 API/worker + 合成模型 IO。
- 浏览器环境失败已收敛：缺 Chromium 时安装与当前锁定 Playwright 匹配的 browser；并行套件最初共用根 test-results 导致 trace ENOENT（4 passed/1 teardown failed），隔离输出目录后助手 5 passed。不得把首次缺浏览器或产物冲突当产品失败，也不得删除有效断言。
- 完整 `make test-e2e` 的作业 `bash-0f4f3ea8a1be481c` 已收集：384 passed、24 failed、7 deselected（约 375s），包含并发/超时、`understanding_owner` 的合成 provider_id KeyError 等，尚未串行分类复核，不能认定纯环境或既有失败。
- 本轮 Ruff、format check、受影响 ESLint、`make docs-check BASE_REF=origin/main` 与 `git diff --check` 通过。没有真实模型或作者体验研究证据；工程测试不证明文学质量。

## 交付结果

- 已交付：HANDOFF.md 与任务进度记录；世界对象/档案草稿本机恢复；写作临时正文上下文；对象、档案修订、关系焦点版本校验及经 Evidence 的精确资料物化/回答前复核；相关契约与行为文档。
- 2026-10-19 审查整改R1–R7及扩大门禁遗漏全部本地完成，见REVIEW。未新增作者体验、文学质量、生产/远端CI及非Chromium/真实软键盘验收。完整PG24项已证实基线失败保留，本轮critical仍有其中3项；全仓format167项既有失败，不宣称全绿。
- 交付边界：所有改动仅本地未提交；没有推送、合并、部署或业务数据写入。
- 接手者只需恢复本 TASK.md 与 HANDOFF.md；研究、源码和权威契约按文档中的条件指针读取。

## 本轮检查点（2026-10-18T19:46:22+08:00）

- 用户明确设定全部完成的持续目标。主 Agent 续用原 WIP 分支，未委派；复用已运行的确切专用 PG 容器，未读写其他库。
- 新增 `RunResponse.context`：只投影冻结的提交上下文，不返回私有运行配置；界面明确区分正在选择的下一轮参考与本轮固定目标，旧任务不借当前页面补目标。
- 新增按账户/作品/对象隔离的本标签页返回位置（只存正文 hash 与 UTF-16 选区，不复制正文）；复用写作恢复后核对内容，变化则保留并提示。
- 写作页四条任务路径与资料栏按需显示已接入，保持原编辑器和表单实例；新增关键词查对象，只读本作品前 20 个匹配，不宣称名称命中是依赖证明。
- 验证：初轮受影响前端 4 文件 115 passed；工作台及编辑器后续 4 文件 104 passed；新后端投影测试 1 passed。Vitest 测试结束有已有 localhost:3000 请求拒绝日志，测试全过但该后台请求尚未归因。
- 浏览器：首轮新返回用例因未选章失败（准备已修）；随后发现真正的滚动时序 bug，选区正确而原段不在视口，已修复为定位前同步镜像尺寸并滚动编辑容器；1280px 合成材料完整返回用例 1 passed，保留实际可见断言。待平板/手机复验。原对象/档案恢复两用例本轮仍通过。
- 无真实模型调用、真实作品、提交、推送、合并、部署。全部六批仍未完成；24 个 PG E2E 失败仍不能归因为纯基线。

## 本轮模型选择补充（2026-10-18T20:01:09+08:00）

- 用户直接指定 DeepSeek/Codex 中的轻量模型为 `deepseek-flash`/Luna；采用 provider 内固定映射，批准判断 low 专用，生成/审查沿用原约定。该答复没有提供付费测试、真实作品或发布的新授权。
- 官方文档只核对了 Luna reasoning 支持 low 及 DeepSeek chat completion 的 low 结构参数；这不是当前连接核验或判断器实测通过证据。

## 实施检查点（2026-10-18T20:17:31+08:00）

- 用户选择的 low 模型已经在 Project seam 实现 `purpose="approval_judgment"`：固定当前已验证连接的 `deepseek-flash`/`gpt-6-luna`，普通用途不变；冻结 secret-free purpose、精确模型、low、能力和连接哈希；恢复使用当前凭据并重验 Codex owner 连接。专用 client 在预留/I/O 前拒绝模型/effort漂移、工具、非结构化和 high_quality 覆盖，禁成本路由。只是专用模型底座，尚非代批功能开放。
- Project 全模块 + infrastructure/llm 全模块最终 682 passed、2 deselected（22.44s）。新增 low 原生命令、普通 low 拒绝、快照轮换/漂移/跨 provider 和 Codex 每请求连接重验。更新 ADR-0038 增补、development-guide、Project/LLM 权威文档及 ADR 索引。
- 回归中修复测试工厂通过 __new__ 构造 client/provider 时缺新用途状态；传输守卫旧测试受 ambient proxy 影响，曾用固定 fixture-key 发出 /models 请求并得 401（无真实密钥/作品/模型生成）。现测试显式关闭代理且用 MockTransport 作为网络兜底，不再允许网络 I/O；原守卫断言保留并通过。
- 关系搜索器在切换输入焦点时原结果会残留/迟到重开：修复共享 referencePicker 的 focusout 取消及关闭，新增异步回归；既有新建关系→人工删除真实浏览器通过。
- 写作固定参考只在本机记录引用身份，正文不入参考备份；前文字面查询限定当前章之前的已保存工作稿，Read Evidence 重验来源。备份失败保留当前参考并提示，失效引用保留待重查。固定资料不会直接送给助手或授予修改权限。1280/390 深色浏览器完整查询/固定/刷新/经历入口 2 passed，实际查看手机截图。
- WorkContext 新增本页所选对象集合：1–20 个精确版本、拒重复/混合焦点/RP；提交与 worker 核验归属和版本，inspect_current 每次五项，遗漏与下一页如实返回；集合外/聚合操作和检索拒绝，引用不得带回未选对象；历史回放绑定集合。旧默认 None 不改变请求幂等哈希。列表“讨论所选对象”与固定摘要接入。组件新增用例通过；本页所选对象真实 API/worker（合成模型IO）浏览器 1 passed。后端全助手+焦点+公共facade 312 passed（随后增加集合历史用例与 early search guard 需收尾重验）。
- 当前所有已运行浏览器/测试作业已结束，专用 PG 保留。下一步先完成最新选择集合及共享 UI 改动收尾检查，再批次 3 统一批准机制（持久任务授权/撤回/独立判断/共享 ActionBatch+Goal/根预算/回执），然后批次 4–6。整个目标仍 active，未虚报后续批次或模型/作者验收。

## 批次 3 实施检查点（2026-10-18T20:41:00+08:00）

- 前两批最终收尾：工作台恢复/返回/深色固定参考与经历/档案响应式组合浏览器 9 passed（38.9s）；World 全模块及 Story 时间线 1570 passed、1 deselected（66.91s）；Assistant+精确焦点+公共 facade 313 passed；前端全量 262 文件/3290 passed。最新受影响 Ruff、ESLint、docs-check 与 diff 空白检查通过（新增批准代码仍需本批收尾检查）。
- 新增 assistant_approval_grants 与 assistant_approval_calibrations，兼容增量 head 20261018_assistant_approval。确切两个专用测试库均已迁移；首库 alembic check 零 schema 差异，不触碰默认数据库。
- 任务授权冻结 owner/项目/run、有限对象/章节/创建槽、作者目标、保留项、判断次数/时限及父预算，独立行版本撤回。判断器 low、无工具、零自动重试，只读 allow/ask/deny；I/O 前持久 pending，未知不重发，判断后核验授权与用量。具体批准绑定完整预览及操作版本，原领域执行事务锁定授权，并重验现有 Evidence、CAS、审查和幂等。
- ActionBatch 在原 worker 剩余根预算内判断完整预览，通过原 decide_batch 执行，客户端没有机器批准字段。Goal 在显式批准计划时创建同一授权，旧 auto_r2 不升级；逐步判断、执行前复核，回执归原根账本。全库/新对象依赖范围的扩展仍属批次 5，尚未实现。
- 离线批准用例从 10 项增至 15 项全部通过：三态、重放只计费一次、越界/人工保留项、缺父预算、撤回期间判断、超时/无效/指纹错误不重发、改预览拒绝、真实 World 字段写入与判断后作者并发修改保留；Goal 三态共享判断且请求数为原计划 2 + 判断 1。旧 Goal/批次/根信封相关 48 passed；之前全 Assistant 315 passed（后续 Goal 接入及 API 新增后需重跑）。
- 固定 16 个纯合成判断案例已冻结，尚无模型实测回执。生产自动模式仍不可创建授权；测试只在隔离 fixture 插入校准替身，不当作真实校准证据。公开能力说明未校准原因；只读授权与撤回 API 已接入，界面与校准运行器尚未完成。
- 当前作业：PG 并发/迁移检查 session 20846，日志 /tmp/author-workspaces-approval-pg.log；仅确切专用首库。下一步收集结果并补模式与撤回界面，再补固定模型校准工具及本批收尾；全部目标仍 active。


## 批次 3 收尾检查点（2026-10-18T21:08:00+08:00）

- 共用批准设置/任务回执与独立撤回界面已接入普通助手和 Goal；低频设置折叠，手机回执位于记录滚动区，不遮住输入。实际 API/worker/领域数据库、合成模型 I/O 的完整助手浏览器套件 10 passed（1.8m）；其中手机自动执行及等待判断时撤回 2 passed（27.9s），查看过两张渲染截图。日志 `/tmp/author-workspaces-approval-full-browser.log`。一项 editorial schema 错误是套件验证降级路径，最终全部断言通过，不是未处理失败。
- 新增固定 16 案例的显式校准函数，逐次 pending/账本/用量核验、零自动重试、严格 false allow/false block；只匹配全部正确且当前模型/策略/案例指纹相同的回执才开放。离线新增校准正反例和焦点回归 42 passed（3.75s）。尚未实际调用指定模型，不将合成 fixture 当作实测。
- PostgreSQL 新授权并发 2 passed（1.08s）：撤回先取得授权锁则禁止写入；领域事务先持锁则撤回等待写入及回执提交后生效。新用例加旧并发/迁移路径共 5 passed（16.19s）。两个确切测试库均迁移到 `20261018_assistant_approval`，首库 schema 零漂移。
- 架构方向门禁发现新增 assistant→world 边及函数内导入数增长，改为既有 Evidence facade 与新注册 World 精确焦点 DI port；指标回到基线 61 边/9 双向/0 顶层环/517 函数内导入，不提升豁免基线。三个旧投影测试已迁移到实际 DI seam，保留全部有效断言。
- 前端全量 263 文件/3295 passed（32.63s），之后手机布局相关 4 文件 44 passed。后端广回归 1053 passed/2 failed/2 deselected，两失败均为已修复的架构门禁，正在重新收集助手/焦点/公共 facade/架构验证。原 PG 全量 24 项基线失败仍单列。
- Goal 自动计划提交断线时保留授权查询/撤回入口（不把请求失败解释为服务器未生效），正在补回归。批次 3 仍待最后门禁与模型实测，批次 4–6 尚未交付。下一步开始局部修改组的服务端完整候选组成与重新审查；旧批准/审查不得沿用。
- 未调用业务模型、未操作真实作品，全部本地未提交、未推送/合并/部署；目标仍 active。


## 批次 4 局部修改组检查点（2026-10-18T21:23:00+08:00）

- 新增 Writing candidate_selection.py、GET revision-groups / POST revision-selections：精确读取已保存基线/补丁，按组组成完整正文，未选范围保持基线；缺可靠补丁/分组时只支持整组。模型输出可选 groups，默认全部成组；共用 finding 的补丁由服务端合组。
- 复用 writing_comment_run 的 Project 快照、根预算、operation 幂等和 never_retry。新 writing_selected_revision 保存父候选/hash/选择/工作稿基线，清除旧审查，重新治理与独立审查，保留原 confirmation、角色知识、Scene 和人工世界审查排除范围。最终章节锁下重验。采用沿原 CAS/审查/知识门禁及 copy-on-adopt；部分选择不误触发原候选全部 editorial_issue_ids 的改后复核。原稿、原候选和独立世界提案保留。
- 新组件 WritingRevisionGroups 按需展示原文/修改后，选组后暂停原候选采用；新候选在原编辑器打开。选择、未知提交 operation ID 和任务引用按账户/作品/候选隔离备份；刷新核对原请求/任务，不重开未知任务；跨项目迟到结果丢弃，备份失败明示。打开状态切新候选会重新读取差异。
- 新后端 5 passed（0.58s）；完整 Writing + 批准判断 + 治理门禁 455 passed（29.97s）。相关前端 5 文件 116 passed（5.68s），含 Goal 自动计划提交断线仍可撤回。助手/焦点/公共 facade 最终 330 passed（26.57s）。
- 新完整浏览器两宽度 2 passed（22.0s），日志 /tmp/author-workspaces-selection-final-browser.log：原批注生成两组→仅选第二组→组成完整候选→重新治理与审查→刷新恢复→打开新候选→原二次确认采用→继续手改保存→API 核对。实际查看桌面/手机差异截图及桌面派生候选截图。模型全部合成 I/O；不证明文学质量。
- 测试修正仅为 chapter_index 参数、原采用二次确认和公开 API 响应解包；手机 waitWritingReady(chapter) 会主动打开抽屉，改用 editor 等待，不改产品以绕过测试。
- 原批注另行发起的世界提案任务因合成 fixture 返回不适用操作而失败，失败回执保留；选组候选不声称该世界提案完成。后续可给纯正文 fixture 补无提案回应，不能抹掉实际失败。
- Ruff、受影响 ESLint、docs-check BASE_REF=origin/main 与 git diff --check 已通过；新增共享 finding 合组/全 provenance 指纹后仍需最终复验。更广前端全量目前仍为此前 3295 passed，尚未含选组组件。架构总览、图源/HTML、CLAUDE 导航指针、testing-guide、维护文档均同步，未修改权限规则或豁免基线。
- 尚未完成：批次 4 关系助手修改/结束有效期/移除/恢复、采用后历史恢复的本轮跨流验证；批次 5–6；指定模型真实校准和作者体验。自动模式仍不对未实测配置开放。未调用业务模型、未动真实作品、未提交/推送/合并/部署。下一步复用 EntityRelationService、validity、review_meta 和执行指纹补关系 prepare/apply/恢复，删除保留人工确认。


## 关系维护实施中（2026-10-18T21:37:00+08:00）

- 新 World relation_changes.py：edit/end/remove/restore 共用具体预览、原 EntityRelationService 校验/写入、entity-first/relation-second 行锁、执行指纹、operation 幂等回执；历史 flat before/after 写入现有 review_meta.author_change_history，不新增事实表。结束保持 canonical 并设置稳定锚点，移除为 deprecated 且保存恢复前快照，恢复先显示当前差异；旧无快照记录不猜恢复。恢复不得借 deprecated 历史伪装移除。
- 新 world.maintain_relation(R3)、world.remove_relation(R4)、world.relation_history(R0/分页) 目录操作；精确焦点/所选对象/确认排除范围均经原操作范围检查。新增操作不进入旧冻结目录，目录兼容测试已同步新增集合。尚未将 maintain_relation 加入自动模式白名单，当前仍人工；后续需补有限 relation 授权、判断案例与校准指纹，remove 永远保留人工。
- 新 World API change-preview/changes/change-history；确认 required true，版本过期保当前，重复 operation 返回原回执。对象关系列表新增显式 include_removed，默认旧语义不变，为刷新后恢复保留入口。新 WorldRelationMaintenance Vue 组件（按需读取，预览/本人确认/历史比较恢复，本机隔离备份与未知请求原键核对）已接对象详情。列表级关系工作台尚未接本组件。
- 初轮领域+目录 16 passed；加原有效期测试 19 passed；加治理门禁 66 passed（14.75s）。相关前端 3 文件 52 passed。首浏览器发现确认端嵌套默认 None 在 model_dump 往返时被当显式空值；已给 RelationEdit 添加只序列化显式字段的 serializer，保留显式 null 校验，新增真实 HTTP 确认/重放/路径/确认门禁回归。正在收集该回归，并重跑两宽度浏览器 `/tmp/author-workspaces-relation-roundtrip-browser.log`（session 需用工具最新返回核对）。
- 当前尚未跑新关系 PG 并发；待浏览器后补专用首库双会话 CAS 竞争测试，不能与 functional 浏览器并行用同库。关系权威文档/目录说明和本批完整回归仍待收尾。新 Writing 最后来源/语义回归 37 passed；docs-check 与 Writing/Goal 前端收尾门禁已通过。
- 仍未完成六批，未调用真实模型、未提交/推送/合并/部署；原 PG 全量 24 个已证实基线失败不变。继续本批关系 UI/域调用闭环，再进入批次 5。


## 批次 5–6 工程检查点（2026-10-18T22:10:00+08:00）

- World 冻结清单已新增 `world_entity_review_scopes` 与增量迁移 20261018_world_review_scope，专用两库已迁移当前 head。POST 冻结匹配的身份/版本（最多一万项，超限不截断）、GET 最近十份与固定 20 项分页、POST decisions 显式人工核对/暂缓/pending 进度 CAS。重复冻结 operation 返回原清单，PG savepoint 捕获并发唯一竞争；新增对象不加入，已变对象从核对计数移除。服务器只保存版本清单，不复制事实；实际修改沿用原批准与领域回执。
- WorldReviewScope 按账户/作品备份清单、页码、未确认冻结请求和页内勾选，刷新恢复；本页可取消勾选已变对象继续其他项，缺本地存储仍能读服务器最近清单。讨论仅传原版本的明确勾选对象，不把已读、人工核对和模型检查混同。同名仅线索。资料库更多工具与对象工具接入，未加入自动全库写入。
- 新 PostgreSQL 并发清单重放/CAS 与原关系竞争共 2 passed（0.61s，/tmp/author-workspaces-relation-pg.log）；新清单单元/API 与 Goal/目录/facade 46 passed（5.58s）。冻结→分页核对→暂缓→刷新恢复→后续编辑/新增→原清单仍 23 项/失效一项，两宽度浏览器 2 passed（14.4s，review-scope-final）；此前漏传原实体编辑 CAS 的测试请求已修正，产品保护未削弱。
- Goal 发现目标检查缺少 source_id/relation_id，已补这两个实际参数；新测试证明不能声明一个目标操作另一个。新建真实 World 对象的回执经显式引用解析后，关系 prepare 回读真实身份，端点后续变化使 apply 拒绝旧预览。复用既有预算、依赖、部分成功/未知和恢复机制，没有新通用工作流。
- 新版本化产品帮助（author-workspaces-2026-10-18.1）：API capabilities 返回，助手按需展示实际入口、步骤与条件，模型不可用仍可阅读；新讨论冻结说明快照，旧讨论不回填。新增两个受控导航目的地（对象清单/关系）。提醒沿用既有统一来源和问题身份，无新后台轮询。
- 影响查询保留声明关联/字面待核实/未覆盖区分，来源版本核验后可带章节/草稿/hash/码点偏移回到原文；单元 171 passed（相关 4 文件，5.27s），桌面/手机新浏览器 2 passed（11.9s，help-impact-final）。首轮失败只因测试用了候选编辑器 ID，已按实际‘章节正文’可访问名称定位。仍需核对 emoji 偏移与长稿滚动。
- 真实校准 CLI 已实现：默认只读核验 owner/Project 已验证连接；显式 --execute 才发送固定 18 合成案例。新仓库外 0700 目录和 0600 原子根/预算/结果账本，18 请求/65536 token/10 分钟，不覆盖 provider/model、不复用目录、不自动重试。CLI/判断/依赖相关 22 passed（1.10s）；--help 可用。已询问用户用于真实校准的测试作品，等待定位信息；尚未真实调用，不以 mock 填校准回执。
- 最新完整前端 267 文件/3305 passed（39.83s）；Assistant 全模块+新 World 边界+目录/契约/facade 391 passed（60.85s）；前端全量 ESLint 与 production build 均通过。build 有既有 bundle size 提示，不影响构建验证。docs-check BASE_REF=origin/main 和 diff --check 通过。
- 当前正在跑：65 条作者工作台功能浏览器（writing/world/recovery/dossier/relations/comments/conflict/dedup）、独立 synthetic API/worker 创作跨流浏览器。两个 DB 分离，勿再并行第一库 PG/functional。下一步收集结果、修复新增或受影响问题，核验来源 emoji 定位，完成收尾文档。全部本地未提交；没有真实数据、模型、推送、合并或部署。


## 跨流验收发现与修复（2026-10-18T22:13:00+08:00）

- 65 条功能浏览器首轮 64 passed、1 failed（2.8m）；唯一失败是批注任务恢复后界面默认切回资料查找，恢复候选仍存在但不能直接看到。修复为按账户/作品/章节保存当前资料/批注/前瞻工作面，刷新/切章读回；本轮专项重跑进行中。不删除候选恢复或轮询上限断言。
- 独立 synthetic API/worker 创作跨流 9 passed（2.0m，/tmp/author-workspaces-creative-crossflows-browser.log），包含前瞻与两种试改、保存保护、确认/恢复/窄屏、世界提案历史、三方比较和中途作者修改。日志中的冲突与删除合成测试项目后索引失败属于有意失败路径/清理，不据此宣称模型质量。
- 影响来源的码点偏移进入 textarea 时发现非 BMP 转换缺失，已在共享 editorController 转换 UTF16；写作页在核对当前实际内容 hash 后复用现有 marker 滚动定位。跨章/版本变化不定位，保留当前正文；restoreObjectPosition 增加迟到内容检查。新增单元与长稿 emoji 浏览器断言正在验证。
- 65 项治理/架构测试通过（13.97s），未变更豁免基线。真实校准等待用户指定测试作品，自动模式仍关闭。

## 整体交付与首轮真实校准（2026-10-18T22:36:00+08:00）

- 新前瞻“存为参考”完整真实 API/worker 路径 1 passed（34.1s）：预览→本人确认→未采用资料工作稿→成果导航→回写作→原稍后任务→两版试改/采用→刷新；正文直到本人采用前保持原值。首轮导入遗漏已修；第二轮测试误把仍打开的助手关闭已修定位，未改产品避验。完整创作两文件 9 passed（2.3m），新增组件 1 passed，最终相关后端 28 passed（4.69s）。实际查看存参考成果截图。
- 最终 ESLint、Ruff、production build（14 引用/59 bundle/98 路径）、docs-check BASE_REF=origin/main 与 diff --check 通过；新增汇总文档后再复验。整体证据汇总见 ACCEPTANCE.md。
- 只读核对 guimi：旧旗舰 TASK 第 21 行明确默认 ai_novel_acceptance_guimi 库/标准项目 ID；因此环境澄清已由现有权威记录消歧，没有选择 G7b v3/恢复原评测。Project seam 实际解析当前已验证 DeepSeek / deepseek-flash / low。
- 原库备份 `/Users/tywww/.codex/private/author-workspaces-guimi-backup-20261018-223202/guimi-before-calibration.dump`，49809485 bytes，SHA256 28d60b3f67edc0c6b25e6ac6d0ab40bc022c0aabb6f5b5d6ce45b065292aac19，权限 0600/父目录0700。原库未迁移/未写入。
- 本任务确切专用容器新增副本 `author_workspaces_guimi_calibration_20261018`，本地37项兼容迁移到head成功；全部60条 writing_drafts 全字段逐行聚合指纹与原库一致 667fe5294aca17bfae2e5d9a3bc6d1e8。无worker、无原评测续跑；之前 commentary 62 条是笔误，已更正60。
- 首轮真实校准在该副本运行：18 started/settled，0 unknown，完整用量 prompt8724/completion3990/total12714，零重试；私有 `live-calibration/report.json` 与根/预算/日志在上述私有父目录，首轮失败证据不覆盖。17/18 正确、false_allow=0/false_block=0，unreviewed_adoption 原应ask而判deny，严格校准未通过，自动模式关闭。去原文结果见 CALIBRATION.md。
- 修复判断说明：缺来源/独立审查/可恢复证据或回执未知时ask，违反授权和人工保留项仍deny；未改案例/期望/通过门槛。calibration_fingerprint 因说明变动失效旧回执。20相关单元/CLI测试1.02s及Ruff通过。
- 原18请求已用完，已发第二轮同连接/同案例18请求/65536token的新预算授权问题；仅此部分等待，不能把无回复视作授权。平台goal仍active，批次3模型验收和最终关闭未完成，不声明全部完成。


## 最终离线收尾与新轮授权（2026-10-18T23:04:00+08:00）

- 临时正文讨论1280/390浏览器2 passed（20.4s，temporary-discussion-settled）：延迟真实保存请求，核对服务器仍原稿、无正式确认方案；讨论后释放保存，重新绑定保存稿/hash；旧轮上下文保持临时身份。此前测试失败来自未选择章节及未等待路由处理结束，已修测试同步，不放宽断言。实际查看手机截图。
- 补查发现临时上下文普通确认链缺少确定性门禁，现于prepare_actions及decide_batch拒绝临时稿正式修改，空动作讨论仍正常。新增DB用例验证无预览/无执行/无授权回执；正在跑受影响域测试。
- 完整前端267文件/3308 passed（33.46s，delivery-frontend-final）；全量ESLint及production build通过（delivery-lint-final/build-final）。助手全模块/公共facade/目录348 passed（33.80s，assistant-backend-final，随后上述临时门禁须复验）；docs-check BASE_REF=origin/main通过。
- 当前助手完整14项与写作适用浏览器回归仍运行，专用两库分开；Luna新轮使用独立无worker校准副本，无环境混用。
- 用户已授权新轮18/262144，实际调用仅Luna/low；连接检查已成功，不重跑。新账本及日志保留旧轮旁边，全部通过前不开放自动模式、不关闭平台goal。

- 离线收尾终态：临时门禁后的完整助手/公共契约349 passed（32.07s），临时讨论2 passed（23.4s），完整助手14 passed（2.2m），写作33 passed（1.5m）及409/412冲突2 passed（15.5s）。新门禁首次测试遗漏confirmed字段，修正测试后全通过；没有修改产品确认要求。Ruff、最新docs-check和diff空白检查通过。具体日志见ACCEPTANCE。


## 最终验收关闭（2026-10-18T23:09:36+08:00）

- 完整指定模型校准18/18通过，175726/262144 token、18已结算/0未知；只读核对同配置availability=true。未开自动任务、未碰原库，旧失败完整保留。逐例与指纹见CALIBRATION。
- 六批实现及适用工程/浏览器回归均已完成；限制和基线失败逐项列入ACCEPTANCE。平台goal只按本地交付关闭，不代表提交、发布、作者或文学质量验收。
