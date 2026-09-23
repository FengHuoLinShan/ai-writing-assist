# NovelCraft V4 实施审查与续做（2026-09-22）

**有界真实模型纵切已通过；完整 G0–G8 未完成。** 本轮补齐了来源失效、持久理解、
独立任务真实消费、地图同源读取、推荐上下文边界与项目写入归属。连续两个 Scene 的
理解已实际进入新任务，保留理解又进入不同目标的第二任务和前瞻；改稿使这些旧结果
一起失效。E07 新增受控入口已支持连续读取、追加与恢复；Scene 自动准备已接并通过工程
验证；原真实端到端验收在第二场逐字引用校验处失败，后续显式修复运行已通过。
Scene 后缀重算已接工程路径，
对象/已有观察可定位保守后缀；细粒度依赖闭包和旧入口替代仍需续做，
E08 退役及完整质量/用户验收未通过。

2026-09-22 后续已补按已解析对象/已有观察选择核对目标，仍保守重算顺序依赖后缀；
写作入口复用现有弹窗并按项目 owner 展示可执行操作，旧历史按服务端归属禁用继续/重算，
查漏依据可只读回看。目标检索和预览零模型调用。本地跨栈门禁通过：后端 6223 passed / 15 skipped，覆盖率 85.96%；最终前端
2583 passed，原生 PG 23 passed，浏览器新入口 4 + 旧入口 9 passed。依赖审计、部署脚本
270 项、lint/build 与文档门禁通过。本轮无新增付费调用；此进展不核销旧入口完整替代或 E08。
[本次验收记录](../../../.agent/tasks/2026/T-20260921-novelcraft-v4-implementation/artifacts/v4-scope-entry-verification-20260922.json)。

独立状态复核后续修复：新运行的状态候选须经单独回读正文，复核结果与来源、父回执、
代际和全部候选绑定；未通过项保留待决定。采样和复核分别冻结费用，额度不足可暂停，
领域失败后恢复不重发请求，旧协议不会静默增加付费步骤。提交边界重新验证复核资格。
本次否定/条件/漏项/伪引文和并发恢复为工程门禁，真实模型语义质量尚未新增验收。
详细当前状态及失败证据见主任务记录；旧流程完整能力迁入仍在执行。

2026-09-22 22:02 交接时 `store.py` 的继承读取仍是未验证草稿。22:29 已贯通
workflow/消费者，增加 Scene 后缀重算与非法引用新授权路径；完整离线回归、
原生 PG 和浏览器合成 provider 已复测。其后又补了继承 Scene 的最新成功回执门禁，
模块与原生 PG 定向回归通过；完整全量数字仍属于该最后小改动之前的版本。
恢复步骤、失败项目、共同费用账本及未完成代码详见
[主任务交接记录](../../../.agent/tasks/2026/T-20260921-novelcraft-v4-implementation/TASK.md)。

当前分支 `codex/v4-audit-fixpack-1`，HEAD
`0efb1359d70af3bec92ad47d0493238d62bc7861`；本次成果和继承 WIP 均保留在工作树，
未提交、推送、合并或部署。依据是[总计划](plans/00-MASTER-v4.md)、
[追踪矩阵](plans/05-TRACEABILITY-ACCEPTANCE.md)、实际调用链和测试。标准/规格两个
只读复审分别核对关键修改，主代理修复及集成；自动化和模型评审不代表真实作者验收。

2026-09-23：新计划已接逐 Scene Phase1b 语义生成和独立复核，沿用同一来源、前序回执、
冻结结果和根预算。只自动充实未编辑自动草稿；低于 0.90、约束未决或复核阻断均保留候选。
工作台可单独确认边界（逐 Scene 预期指纹，变化拒绝）、保持 draft 后继续原运行；语义建议
显式填表后保存。两个并发锁问题已修复并经 28 项原生 PG 验证；浏览器 5 项通过。
最终 `make test-ci TEST_WORKERS=4` 通过：后端6237 passed/15 skipped、coverage86.00%，
部署270，前端203文件/2585项，lint/build与文档检查通过；这仅核销当前实现的工程门禁。

真实模型最后两场运行共7请求，完成顺序推进与候选保存，原失败和准备结果未改写。
两场语义置信0.60/0.78，未自动写入约束。代理发现过强否定约束后修复Prompt，
再对保留反例与收窄对照各执行一次独立审查：原反例被major阻断，对照通过；
对照为代理编辑的审查样本，不是重跑整条生成流程或人类质量结论。
共同ledger现99 settled请求，估算USD0.256509012，上界USD0.5287482，含全部失败。
临时测试凭据已移除；保护库未改动。详细证据在主任务记录与paid产物目录。

作者已明确授权本代理执行代理验收替代本次人工参与项；所有结果必须标记
**“代理验收，非人工试用”**。原长期人类效果目标仍保留，未部署或宣称长期真实使用。

## 逐包现状

| 范围 | 当前可证明的结果 | 剩余出口 |
|---|---|---|
| E00/G0 | 作者事件保护、共同 reducer 与入口副作用回归通过 | 完整计划总门禁仍独立 |
| E01–E04 | 精确多段来源、结构化模态、身份解析、阶段冻结、窄提交、前序屏障、预算及幂等回放 | 类型/逐字通过不证明语义蕴含；复杂作品质量待验 |
| E05/I02 | Writing 保存/发布/删除、助手/协作/导入采用与 Scene 生命周期实际接入索引和失效；旧 run 封锁、机器事件软失效 | 更大作品与长期负载验证 |
| E06 | 分页回放、检查点、世代栅栏已有 | 长期容量与 SLA 未验收 |
| E07 | 项目 owner/队列保护、固定模型/单请求预算；显式入口支持 bootstrap/append、自动准备、Scene 后缀 revise/scoped_recompute 与恢复；新路径 PG/浏览器合成回归通过 | 对象/观察已可定位后缀；细粒度闭包、旧 API 适配与完整验收未完成 |
| E08 | 退役清单已纠正，保留历史读取与旧编排 | 同源新旧对比、真实入口 canary、观察/回滚后才可默认替代和删码 |
| E09/G2 | 连续 Scene → Evidence → 独立 case → 持久理解 → 不同目标新 case/前瞻，以及地图/改稿失效，生产 handler 与真实 provider 有界纵切通过 | 短合成故事并非长篇真实性、等预算收益或完整 DoD |
| C01/C02、部分 C03/C05 | 独立 head/commit/record，显式保留、CAS/幂等/no_change、追加历史；作者修正/撤回/历史与草稿保护；传递来源重验 | 竞争解释、开放结构、合并和完整认知演化等 C 高级包未核销 |
| I01/I03 | World 地图真实 API 消费 Story，Evidence 把 Evo/C 实际装入模型输入；同源修改共同失效 | 全部消费者和长篇覆盖仍需逐项验收 |
| R00–R06 | 选区/光标/意图、四个身份键、单 feed、逐方向拒绝、过期保护、作者回顾理解与生成/审计一致 | R07 真实作者任务收益、安静策略长期表现未验收 |
| U00/U01 与部分 U02 | 入口清单、浮层/Escape/焦点；共享推荐状态、意图交接、理解编辑与窄屏已回归 | U02–U09 全功能等价矩阵与统一宿主完整流程未核销 |
| V/MI | 既有地图/媒体能力继续复用；新增 Scene 在场/最后出现/未知及来源一致性 | 条件路线、约束解释、视觉状态及完整空间智能未全部验收 |
| A/G4–G8 | 既有有界协作及此次规划/工作/审计根因修复可用 | 等预算比较、创意独立发散、长期认知、真实作者与发布观察未通过 |

未核销不等于现有产品没有同类功能；后续应复用实际能力并补足对应证据。

## 关键修复与边界

1. **来源与恢复。** 单 Scene 最多 16 段真实草稿范围，每段校验版本、码点偏移和
   逐字引用；跨章状态在末段生效。幂等与恢复核对 run/Scene/来源完整指纹，不复用
   另一请求。唯一准确引文的新采样允许宿主对齐模型偏移并留原值，歧义、缺失仍拒绝；
   已冻结的失败保留，恢复不能重新付费或悄悄修写。
2. **状态提交。** 全部引用的主体和模态必须支持目标状态，再通过 Story 物化 schema。
   knowledge 主体、稳定记录 ID 和关系端点由宿主验证；无依据提议进入 pending。
   未解析地点保留文字与空 ID，不能伪造地图位置。结构门仍不能替代语义评估。
3. **持久理解与消费。** C 独立于 case/run 生命周期；保留实际作者指令、工作输入、
   原始正文根、Evo/C 传递引用与查询凭据。Evidence 必须选中全部合法根，排除/版本/
   可见性变化失败关闭。新任务真正消费旧理解，不把结构化观察直接叫作持久认知。
4. **焦点和历史边界。** C 当前限定作者回顾，明确不是首次阅读证据；同章/后章、
   Scene 焦点、显式历史 cutoff、人物/读者路径不自动混入。Forecast 新旧协议冻结，
   恢复不偷偷追加新资料；生成器和知识审查收到同一组 C/正文根。选区绑定保存稿件，
   异步切稿/授权变化不能复用旧卡；修改/润色交接原助手而保留意图和选区。
5. **规划器实测缺陷。** recipe 限定实际可用能力；planner 和执行者读取相同授权正文，
   工作列表包含真实 proposal。规划理由不能当工作结果，无工作仍判 partial；未知可
   作为结论，不以换查询词循环耗费预算。作者追问不阻断已可独立执行的工作，包括恢复
   时遗留的 ready work。
6. **项目写入归属。** Project 独占锁、世代和最低 schema 约束两套 owner；排空或明确
   停止后才切换，取消队列及 lease，保留历史与预算。PG NOWAIT 解决旧 worker/心跳
   锁序；旧任务 v1 含 shadow 不能由旧二进制续写。现有 live 项目迁移为只读待核定，
   不猜测新归属或降回旧 schema。
7. **模型和费用。** 首次入队持久 `llm_snapshot_json`，后续 Scene/恢复经 Project
   snapshot seam 固定模型、读取当前轮换 Key；旧 run 缺快照只可重放冻结结果。
   生产采样禁结构化修复与隐式传输重试，一次 Scene 准入最多一次实际请求；失败仍
   留费用。回执使用真实 provider/model。Scene 次数预算不是美元预算；验收 runner
   另用持久累计 USD ledger，在 transport 前按峰价保守预留，未知用量封锁。
8. **受控作者入口。** 保存完整 Scene、来源版本和分段授权，预览零请求；确认指纹重验
   来源、模型与 owner，重复提交复用原任务，不加预算。已计划未采样的正文也会失效；
   下一 Scene 在原回执提交后入队，追加按实际已读来源定位。恢复旗标由独立租约检查点
   持久化，普通异常/服务器关闭均能复用已保存结果；费用未知、作者停止与旧租约不能
   自动重试。浏览器经实际 API/worker 连续推进、重载与暂停；合成 provider 不证明质量。

## 真实模型证据

用户授权默认已验证连接、累计 USD 5；随后明确要求默认模型对齐 V4.1 Flash。
已经账户 SettingsService 将旧 `deepseek-v4-flash` 对齐正式 `deepseek-flash`，其余
参数保留，runtime 回读确认。该操作只改账户默认设置；未更改受保护 Guimi 小说内容、
项目或凭据，也未重启、迁移保护库。回执见[默认模型对齐](../../../.agent/tasks/2026/T-20260921-novelcraft-v4-implementation/artifacts/paid-20260922/default-model-alignment.json)。

截至本次交接共 **84 次实际请求，估算 USD 0.234114432**，峰价无缓存保守上界 USD 0.4813248，
低于 USD 5。这是按 provider 用量及[官方费率](https://api-docs.deepseek.com/quick_start/pricing/)
计算的估算，非账户账单；重试、失败和前五次未过场景均计入同一 ledger。

- live-01：第二 Scene 引文偏移失败，冻结与费用保留。
- live-02：一次 WorkOutput 输出耗尽为空，planner 又提出配方未授权能力，被正确拒绝。
- live-03：重复查证/作者追问与未执行工作导致预算耗尽；修复真实调用链。
- live-04：规划理由冒充结果、没有工作产物，保留 partial。
- live-05：完全相同目标被判重复，第二 case 未形成工作，原结果保留。
- **live-06（scenario v2，61–78 次）**：第二 case 改为真正不同的条件创作任务，
  没有强填理解 ID 或删除有效断言。全部 11 项工程检查通过，实际 provider Prompt
  核对确认 Scene 2 收到前序模态、两次独立任务依次收到 Evo/C，Forecast 及其独立
  审计收到相同 C/原文根。真实改稿前 map/feed 非空，修改后旧项失效。

语义审查确认：青竹的封路说法仍是人物陈述；林舟的知识过度推断被留为待处理；地图只
显示白石城/渡口的出现证据，不发明中间路线、距离或时间；创作方向保持条件提案。
自由文本 claim 的引用偏移偶有标点差异，独立审计已标 minor，原输出保留；权威来源
引用仍由宿主绑定。**不声称输出完全无瑕疵，也不将短合成故事替代长书/真实作者验收。**

原文请求、响应、失败、用量和审查保存在任务的 `artifacts/paid-20260922/`；
[最终语义及 Prompt 核对](../../../.agent/tasks/2026/T-20260921-novelcraft-v4-implementation/artifacts/paid-20260922/live-06-review.json)。
模型快照/单请求约束是在 live-06 后补齐，另经 gateway 替身、原生 PG 与新入口真实验收：
`reading-live-01.json`（79–81 次）实际使用 `deepseek-flash`，第一场返回后注入提交异常，
恢复沿用原 attempt；两场连续完成后追加第三场，总共三次调用，费用 USD 0.004100724。
模态/前序/未知保留；第二场一条唯一引用校准了 end_offset，原值留档。本次没有预建世界
对象，所有状态提议因主体未解析而待决定，未检验 World 新对象建立或地图物化。
[输出与恢复审查](../../../.agent/tasks/2026/T-20260921-novelcraft-v4-implementation/artifacts/paid-20260922/reading-live-01-review.json)。
测试账户凭据在 runner 结束后移除，产物不含 Key/原始思维链。

## 自动场景准备补充

没有 Scene 或已有完整前缀后缺场景的正文末尾，现经 Imports 纯原语准备边界，仍由
Evolution 单一 owner 管理。每次切分/纠偏和后续理解共用根预算，保存请求/响应/用量，
中断免费重放；额度耗尽由作者显式追加，旧任务终态前拒绝追加，追加历史不覆盖旧回执。
宿主按原文位置排序并验证 Scene 顺序；整章 fallback、开放右边界、未解决左承接及
低置信结果留待确认，不能成为已理解前缀。人工确认后无需重复切分。边界来源与前章
尾部参考均固定版本并参加失效，结果落库沿 Project → run 锁序。

新增测试：Evolution/Imports/Story **1279 passed、12 skipped**，PG **21 passed**；
新浏览器从纯正文开始并验证预算追加 **4 passed**，390px 检查通过。入口/采样器最新
定向 **24 passed**。详见 `/tmp/v4-preparation-{regression,native-final,browser,unit-final}.log`。
零费用真实 worker 预演 `preparation-preflight-02.json` 通过；首轮预演为 eval 模块路径错误，
证据保留。`preparation-live-01.json` 真实边界切分与免费恢复通过，第一场理解已提交；第二场
观察把“也没有提起封锁”改为“他没有提起封锁”作引用，被来源门拒绝。因此该整条验收
**未通过**，原失败与冻结结果保留；没有放宽逐字校验或自动重采样。新请求已澄清 quote
与 predicate 的区别。随后在同一专库、同一来源对原失败项目零费用预览，继承第一场
原回执，仅重读第二场。第 85 次实际 `deepseek-flash` 请求使用精确 quote“也没有提起封锁”；
新 Worker done、两场 completed，旧 run 排空、旧无效冻结未改。实际消费返回旧第一场与
新第二场各自原始 run/attempt 身份且无遗漏；行程、封锁真伪和空间关系保留未知。
位置变更提案因主体未解析被宿主阻断，不能把此例算作 World/Story 位置落库验收。
这只是一次短篇修复证据，不能证明长篇可靠性或模型错误普遍消除。
[实际输出审查](../../../.agent/tasks/2026/T-20260921-novelcraft-v4-implementation/artifacts/paid-20260922/preparation-live-01-review.json)。
[新修复语义审查](../../../.agent/tasks/2026/T-20260921-novelcraft-v4-implementation/artifacts/paid-20260922/repair-live-01-review.json)
与[独立只读复核](../../../.agent/tasks/2026/T-20260921-novelcraft-v4-implementation/artifacts/paid-20260922/repair-live-01-postcheck.json)。
`repair-live-01.json` 标记失败是 Worker 成功后临时探针读取脱离 session 对象的报告错误；
原报告保留且没有重发。共同账本累计 **85 次 settled**，估算 USD **0.235453932**、
峰价无缓存上界 USD **0.4840038**，非账单。测试账户凭据已清理。旧任务历史
`can_resume` 旗标未追改；新失败路径标不可直接恢复，新 run 建立后旧 run 不再可恢复。

## 工程验证

| 检查 | 实际结果与证据 |
|---|---|
| 22:50 定向修复后全量回归 | 完整离线后端 **6221 passed / 15 skipped**、前端 **203 files / 2578 passed**、原生 PG **23 passed**；backend Ruff、frontend lint/build、文档影响检查和 diff-check 通过。`/tmp/v4-repair-{backend-full,frontend-full,native-pg,backend-lint,frontend-lint,frontend-build}.log`。另补修复后追加 Scene 的继承链断言。 |
| 22:31 接续 | 完整离线后端 **6220 passed / 15 skipped**、前端 **203 files / 2578 passed**、原生 PG **23 passed**、浏览器合成 provider **4 passed**；其后最新成功回执门禁改动的相关模块 **269 passed / 1 deselected**、原生 PG 定向 **2 passed**，浏览器定向复测见主任务记录。完整全量数字早于该最后小改动；真实模型单次定向修复见上。 |
| 全后端 | **6211 passed、15 skipped**；`/tmp/v4-reading-backend-full.log`，仅一个既有 pytest async-mark warning |
| 全前端 | **203 files、2577 passed**；`/tmp/v4-reading-frontend-full.log` |
| 最新模型快照/预算与消费者 | 179 passed/1 real deselected；receipt 两项另过；`/tmp/v4-model-snapshot-budget.log`、`/tmp/v4-model-receipt-test.log` |
| 原生 PostgreSQL | **16 passed**；来源失效、C 并发、单 owner、新旧 SQL/心跳/迁移、并发启动、真实 Worker 恢复/撤权；`/tmp/v4-reading-native-all.log` |
| 浏览器 | **4 passed**，实际 API/worker + 合成 provider；保存选区/意图/零费用刷新、理解修正/历史、试改/采用/恢复、逐场景理解；`/tmp/v4-reading-browser3.log`，390px 截图人工检查 |
| Lint/build | backend Ruff、frontend eslint/build 通过；`/tmp/v4-reading-ui-lint.log`、`/tmp/v4-reading-ui-build.log` |
| 文档/差异 | 新 API 前缀与架构说明已同步；文档影响检查使用显式无变更说明复核导入/开发/测试/维护指南，`/tmp/v4-reading-docs-final2.log`；diff-check 通过 |

全后端采用仓库测试配置：`ASSISTANT_ENABLED=false RERANKER_ENABLED=false
RAG_QUERY_PLANNER_ENABLED=false make test ARGS='-q -n 4 --dist=loadscope --tb=short'`。
早期 45 项失败已在原基线复现，后续定位到本机 `.env` 的测试开关污染及旧夹具假设；
保留早期证据，未修改真实配置、删除有效断言或削弱门禁。

仅使用任务专库 `ai_novel_agent_e2e_v4_resume_20260922`、
`ai_novel_agent_e2e_v4_live_20260922`，升级至 `20260922_evolution_reading`。
此前 20 Scene 确定性影子链与早期十幕真实模型证据保留作局部历史，不冒充本次完整验收。

## 旧入口与新入口能力对照（本次按实际调用链核对）

| 旧入口承诺 | 当前新入口 | 下一迁入条件 |
|---|---|---|
| `/imports/deep` 的起止章节、force、high_quality、采用及查漏授权 | 从完整可验证前缀到 end_chapter，单独 request_limit 与预览指纹；不接受旧参数冒充授权 | 逐项保留请求语义，尤其质量档位、覆盖保护、采用与费用确认 |
| Phase 0/1a 边界规划、切分、纠偏、精确提交 | 已复用相同 Imports 原语，并使用 Evolution 根预算和冻结恢复 | 继续对齐 Phase 1b 语义补全和高质量融合，不把边界完整当作语义完整 |
| Phase 2a 对象/Delta；2b 别名与关系；去重、候选和采用包 | 窄观察与已有身份解析，未解析主体待决定；没有上述完整资产整理 | 迁入可调用步骤，保持候选/人工确认、来源校验、结果引用及同根预算 |
| Phase 3 剧情线、人物弧、伏笔等结构候选及独立证据复核 | 没有等价结构整理 | 复用领域命令和证据复核，不能仅将观察标签映射成结构资产 |
| 原任务 checkpoint、费用、降级/查漏和取消清理 | 新阅读有冻结恢复、budget/reconciliation、继承前缀；旧记录独立保留 | 旧在途按版本分类续接；不可兼容时保留历史，不伪造同 task 继续 |
| 写作、世界页的整理历史与继续按钮 | 写作统一弹窗按 owner 选流；共用历史 can_continue；查漏只读详情 | 新旧资产语义等价及入口 canary/观察期后才能默认替代 |

依据：`modules/imports/api.py:DeepImportRequest`、`orchestrator.py` 的 start/run_stage_task、
Imports README 的 Phase 1–3 与采用契约；新实现为 `evolution/workflow.py` 与 `preparation.py`。
这张表记录当前差异，不是放宽原 V4 验收。当前 G2 短合成故事与 owner 并发门禁均不能
覆盖上述完整资产迁入要求。

## 继续顺序

1. **E07 完整入口**：已有 Scene 的 bootstrap/append、范围冻结、顺序推进与恢复已接线；
   自动 Scene 准备和 Scene 后缀 revise/scoped_recompute 已接同一 run/queue/budget；
   已可按对象/已有观察定位保守后缀。`/imports/deep` 仍承诺世界对象、结构资产、覆盖与采用语义，
   旧请求也没有新入口的调用上限与预览指纹；不能把现有仅做字典映射的
   `legacy_adapter` 直接接到 Scene-only 路径而静默丢弃这些契约。旧入口替代须在
   能保留上述语义与项目 canary 验证后接线。原写作页的旧完整整理/分阶段按钮已收敛到统一弹窗；统一宿主按当前归属
   显示可执行的新任务并处理旧操作的等价/不可用状态。当前写作弹窗已按 owner 接入
   ReadingFlow，旧世界/结构整理能力差异明确显示；历史继续/重算按 can_continue 禁用。
2. **同源比较与 canary**：相同冻结来源分别运行旧/新隔离流程，比较观察/状态/覆盖/成本；
   验证从实际入口排空、切换、继续、只读历史及回滚。观察期不满足前不删旧编排。
3. **U/V/R/C/A 余项**：按原追踪矩阵逐项证明已有能力/补缺，再做等预算和真实作者任务
   验证；完整高级能力和长期运营门禁保持未验收，不将其改名为可选优化。

任务继续 active。当前工程缺口可以继续实现；真实作者观察和发布另有边界，不是停止
所有工程工作的理由。
