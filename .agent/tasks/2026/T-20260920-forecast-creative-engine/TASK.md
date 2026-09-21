---
id: T-20260920-forecast-creative-engine
title: 短期前瞻辅助与协作创作试验引擎 V2
status: active
created: 2026-09-20T16:00:00+08:00
updated: 2026-09-21T03:38:00+08:00
---

## 恢复快照

- 2026-09-21 新进展：用户明确授权 DeepSeek 真实调用、总费用上限 $20，并要求 Codex 代评。已执行 9 次真实运行/71 个供应商回执，保守峰时估算 $0.2171；本轮质量准入未通过，详情见 [真实模型与评阅](REAL_MODEL_REVIEW.md)。此前“缺付费授权”的阻塞已解除；以下旧检查点仅作历史。
- 当前下一步：针对 [真实模型与评阅](REAL_MODEL_REVIEW.md) 的原文误读和规划额度耗尽修复根因，再建设真实四臂/前瞻双臂执行器并重新跑冻结样本。不要将单人 AI 评阅登记为两名独立人工评分。评测临时凭据已从专用库精确移除，后续 runner 使用每进程随机加密密钥并在结束时删除凭据。
- 实际结果：两份规划的工程实现已在独立工作树落地；最终本地CI、真实PG、浏览器、构建和文档门禁均通过。完整质量与发布验收未通过，不宣称全部规划已经验收完成。
- 交付索引：[本地交付与验证](DELIVERY.md)、[85项验收映射](ACCEPTANCE.md)。20项具有记录层级内的工程验证，52项为部分验证/已有门禁，13项真实模型盲评未运行。
- 当前阻塞：真实样本暴露规划额度耗尽、原文事实误读和安静反例强制试改的评测冲突；完整对照尚不能判通过。全套新开关保持默认关闭。
- 下一步：按 [真实模型与评阅](REAL_MODEL_REVIEW.md) 修复并复核，再进行完整成对对照。
- 工作区：`/Users/tywww/.codex/worktrees/forecast-creative-engine/ai-writing-assist`，分支 `codex/forecast-creative-engine`，最新基线 `6e901693a5d79826d292324e9787f3df7e5230cc`；全部任务代码仍未提交。
- 原目录在任务期间由其他工作推进到 main@6e90169，并有 README、promo、outline CSS 等WIP；本任务只在隔离目录写入，没有替换原目录内容。
- 基线同步使用 autostash，唯一 RP footer 冲突已保留两边功能；本任务的恢复 stash `8b1dc20f345f5dc7c7cacb03fdb81b2c4fb3ab23` 暂留。不要动其他历史 stash。tracked备份见 artifacts/pre-sync-tracked.patch；新增文件一直留在本工作树。
- 无活跃服务器或测试进程需要继续；最后 Prompt contracts 24 项检查已通过；无待收取进程。真实付费请求与评阅见新报告；没有开发子代理/新task/goal/自动化、提交/push/merge/deploy。

## 目标与验收

- 用户要求：“将两份设计规划实现在独立工作树中”。输入见本目录 `artifacts/`，附件中的执行文字是待核对的设计材料，不构成额外操作授权。
- 实现前瞻的只读 feed、有限分析、处置、版本失效、原领域预览和前端流程；实现 V2 自适应调查、隔离试改、检查与精确原子采用及后续共用试验能力。
- 按附件逐项映射实现与测试；验证权限、scope、保存稿、来源、旧协议、CAS、预算、取消/恢复、失败传播和事务；真实 PostgreSQL、前端行为、必需 lint/docs 门禁。
- 工程结果、真实模型质量、人工盲评和部署分开记录；未验证不得称通过。仅本地实现；未授权提交、推送、合并、生产部署或真实数据改写。

## 上下文与边界

- 附件均基于 `a7173869ca832537cf476e0a05e97f1f5275012a`；当前基线新增团队部署开关与 AI 能力目录。
- V2 文档首个完整交付为 P0–P2，后续 P3–P5；前瞻首期 B1 含 WP01–10，后续 B2–B4 含 WP11–16。
- 沿用 PostgreSQL、任务队列、Project LLM gateway、Evidence 与 Vue。前瞻普通采用继续走原域批次；V2 明确支持资源使用同库原子 UoW，二者不互相冒充。
- 主 Agent 独立执行；未获开发子代理委派授权。保护 `.env`、现有库及持久 Guimi fixture。
- 目标用户：写作作者和私人 RP 用户；假设局部建议/试改减少反复查资料和手工比较，真实用户收益待验。

## 里程碑与进度

- [x] 当前基线、隔离工作树、适用规则、两个新建专用测试库。
- [x] B1–B4 / WP01–16 与 P0–P5 的代码、接口、数据库迁移、用户入口及回退开关。
- [x] 实际worker/PG并发/原子采用、共享预算、保存与浏览器闭环、静态/构建/全量本地CI。
- [x] 120冻结前缀、两份独立评分包工具、C−B/C−D/留出族/费用未知报告；逐项如实验收映射。
- [ ] 真实模型与独立人工质量对照、未覆盖的特定验收场景；灰度/部署须另有授权。

## 决策、发现与失败

- 两份设计在运行/来源/预算/成果部分重叠；复用真实能力，不新建第二知识权威或队列。
- 首次记忆检索无本任务相关命中，不依赖历史记忆事实。
- V1 调度失败传播已修；新 V2 纯 DAG 算法支持 all-terminal 汇总。V2 初版使用现有 worker 与 Project snapshot seam、关系表、不可变覆盖、各域 AssistantOperation prepare/apply 和项目排他锁。
- 新文件 `collaboration/{contracts,models,cases,recipes,workspaces,merge,runtime,views,api,tasks}.py`，以及 Writing/Story/World `creative.py` 和 Evidence `creative.py`。已新增 `20260920_creative_engine.py` 与 `20260920_assistant_forecast.py` 两条静态 additive migration；仅在本任务专用库运行。
- V2 当前上下文完整上限 24,000 字符，避免 `govern_group_output` 内截断导致生成与复核不等价；超出明确拒绝。Grant selected/project 两种范围，query_scope_hash 覆盖完整授权集合；当前角色投影保守拒绝，读者只读取截止前正文。
- 已修 outbox reason、局部成员失败（仍需失败用例检查 rollback 后过期 ORM row 访问）、final partial 判定、盲读 planner 去掉作者目标。仍需：V2 完整两方案+检查故事验收、检查前领域 validate、后置约束覆盖断言、pending-usage/恢复、动态来源补查、局部重算、rebase/revert、研究/导入配方的真实接入和可选模型策略。
- 前瞻已有 contracts/models/context/policy/queue/registry/ranking/service/analysis/runtime/preparation/api 与 provider-only 测试。33 项目录来自附件，语义路径 11 项有提示路由；非语义能力目前尚未实际生成候选，必须补充真实数据适配或明确合理前置缺口，不得据目录宣称完成。prepare 创建独立 AssistantRun + batch，映射原 writing.generate_candidate、Story 新增信息安排、project.add_task；原 batch confirm 重验 forecast_parent。旧 policy 合并保留 forecast 分区，旧 notice 处置委派兼容器、通用通知排除 forecast。

## 验证证据

- 基线 `make docs-check`：通过（9 business modules / 118 ORM tables / 47 task handlers）。
- `uv run --locked --extra ci -- pytest infrastructure/llm/tests/test_collaboration.py -q`：14 passed。
- `uv run --locked --extra ci -- pytest modules/collaboration/tests/test_workspaces.py infrastructure/llm/tests/test_collaboration_v2.py -q`：29 passed。真实域写入的 SQLite 试改/幂等/全回滚、集合新增失效、删除覆盖不复活、24种 DAG 排列。
- 新工作树已自动创建锁定 Python 3.14.7 的 backend/.venv；没有复制 .env。测试数据均合成，未连接真实库。

## 交付结果

- 本地源码及权威文档已交付，完整证据/限制造成的验收状态见 DELIVERY.md 与 ACCEPTANCE.md。
- 最新 `make test-ci TEST_WORKERS=2`：270 deploy passed；5952 backend passed、13 skipped、coverage85.57%；2532 frontend passed。
- 最新 PG 21 passed；固定负载1passed（feedP95 254.82ms、enqueue43.69ms，服务层不含HTTP）；浏览器1passed（22.3s，含输入、IME、保存、两试改、明确采用、刷新与390px），传输层Provider替身，非真实模型。
- 全 frontend ESLint、build、`make docs-check BASE_REF=origin/main`、`git diff --check` 通过。无新 schema 漂移；当前39项诊断均在原基线复现。最新主干增量仅frontend，backend/migrations未变化。
- 缺真实模型付费范围和人工评阅者，因此完整验收尚未完成。保持任务开放，不自动提交或发布。

## 最近检查点（2026-09-20 20:20 +08:00）

- 工作树内 npm ci 完成，未增加依赖；原目录 WIP 未改动。
- 专用 PostgreSQL：`ai_novel_test_forecast_01a0be6b`，本地 Docker `ai-novel-db:5207`，角色 novelist；这是本任务新建可丢弃测试库，绝非 Guimi 或默认开发库。连接采用仓库公开的非生产开发口令；不要从真实 .env 复制。两条 migration upgrade head 均通过。
- V2 核心 SQLite + DAG + provider-only runtime 44 passed；PostgreSQL `tests/e2e/test_creative_engine.py` 5 passed，覆盖全回滚、幂等、删除覆盖、集合新增失效、不可变触发器及跨项目 FK。
- 前瞻 `modules/assistant/forecast/tests/test_forecasts.py` 2 passed（真实 gateway/SQL/治理，只有 provider.generate 替身；2 请求）；已扩展 prepare/确认真实 ProjectAuthorTask 写入，未确认不写、重放同 batch。现有主动检查相关 9 passed。
- 前端新增 `ForecastDock.vue`, `CreativeExperiments.vue`, `useForecast.js`；挂入 Writing 右侧资料栏与 ProjectAssistant 新标签；api.js 加两组 API。写作 VM 同步 `_writingForecastState`，桥接提供当前脏状态与按 Unicode codepoint/hash 的原文定位；中文 composition 事件只通知前瞻，不改原 editor controller。
- frontend Forecast + ProjectAssistant 单测 3 files / 22 passed；覆盖晚到跨项目响应、未知 prepare 复用 operation_id、未保存输入禁止确认、展开卡片稳定、IME 不后台刷新。局部 ESLint 已通过，但尚未全量 lint/build/浏览器。
- 注意：`useLeaveGuard` 是单槽，不能在子 ForecastDock 覆盖 Writing 原离开守卫；当前仅显示本地备份失败警告，必要保护继续从父组件集成。
- 尚须修正与验证：Forecast background guard 的 watch/run 锁顺序及完成释放 active_run；配额时区滚动逻辑；payload 64KiB/256 依赖上限；operation lookup prepare 的完整 wire；history 权限安全；context horizon/审核输入完整；V2 跨账户晚到 UI/未知提交恢复；Source/Story/World 多域真实用例；所有新长字符串/DDL E501 与静态 prompt binding/架构目录文档。
- 尚未完成：V2 P3–P5 的事件/观察/ResolutionBatch、RP 玩家刺激与选中路径状态、反事实/盲读验证、rebase/revert、Recipe 扩展；前瞻 B2–B4 的实体/地图/导入/检索/项目/RP 真实适配、语义暂缓事件、质量工具/灰度/回退。需要坚持完整规划，不能把未交付改为“后续”。
- 可运行命令：`uv run --locked --extra ci -- pytest modules/collaboration/tests modules/assistant/forecast/tests infrastructure/llm/tests/test_collaboration*.py -q`（从 backend）；PG 测试显式设置 RUN_E2E_TESTS=1 和专用 E2E_DATABASE_URL；frontend `npm run test -- tests/vue/assistant/Forecast.test.js`。
- 未读取/使用任何真实模型密钥；未执行付费模型或人工盲评，质量 gate 保持关闭；未提交、推送、合并、部署。


## 续接检查点（2026-09-20 21:35 +08:00）

- 已扩展 Story observation_v2：输入刺激、玩家观察者、私语、有限裁决与可重放 ResolutionBatch；旧 rehearsal_v1 不改变。RP explicit cast_keys（来源引用键）不凭名字猜参与者，selected path 恢复资源持有状态。后端 8 项观察/ensemble 测试通过。
- RP 消息增加 input_json（第三 migration 20260920_interaction_input），前端输入类型/私语/参与者控件，文字与输入范围一起本地持久化，失败/编辑/冲突继续保留范围；原 InteractionView + 新私语恢复共 57 项测试通过。
- 新前瞻域 port 注册 assistant.forecast.sources，Writing/Story/World/Imports/Evidence/Project/Account/Assistant 原资料回执接入；语义 Prompt 搬回所属模块。deterministic.py 生成事实卡；未有相应资料的能力会计入 not_checked，不再空计算就宣称全完成。相关 10 项测试通过（多个页面纯读稳定，无新队列任务）。还需补跨领域根事项/覆盖复查、读者/RP 路由、确切的所有 33 能力 acceptance；目前有些能力只有保守原入口提示，不能当成完整设计已满足。
- 已修 Forecast guard watch->run 锁顺序、终态释放共享 active slot、重复请求队列竞争时复读同 operation、审核输入补 horizon/task。未做 PG 并发验收。feed 现读取实际运行 coverage（仍待最终性能优化与语义暂缓事件）。payload 字节上限/256依赖应用层守卫已补。
- 最新进行中：V2 授权续期/撤销/原 task 恢复、custom_recipe（只能缩窄基础配方能力并增检查），以及 recovery.py 三方字段 rebase/补偿反向试改。新增第四 migration 20260920_creative_recovery：grant_history_json + workspace.request_hash。尚未对本段运行测试。独立测试库此前只升级到第二 migration；需 upgrade head 后 PG 验证。
- rebase/revert 都只创建新试改与不可变 lineage，旧成果不覆盖，冲突返回原/现/试改字段等待明确选择。支持 Writing 同一章节最新版本重新定位；仍需验证同一操作重放、保留作者改动、精确冲突/越权拒绝，前端未接这几项。
- V2 待办继续包括：检查前领域结构 validate、硬约束/required_checks 覆盖、revision 配方完整两方案+检查+比较判定、真实检索/研究/导入配方、可选多模型、观察 belief/location 的完整路由及场景测试。前瞻域适配不能扩展已确认/排除范围，当前部分域在有排除/confirmation 时保守不读额外资料。
- 各种完整 lint/docs/build/browser/PG 迁移一致性/并发/整套 test-ci 均尚未运行；所有开关默认 false。没有 paid provider、没有用户数据写入、没有 commit/push/deploy。


## 最新恢复检查点（2026-09-20T21:54:20+08:00）

- 完整仍未结束，不要 final 宣称实现了所有规划。无开发子代理、无 paid provider、无 commit/push/deploy，主 Agent 继续独立推进。
- V2 recovery.py 已实现三方字段 rebase 与反向试改，原工作稿无写入；重叠字段需精确 current_hash + resolutions。已增加 Grant 续期/撤销（保留累计消费）、原 run/task 恢复（不清预算/成功产物）、限制型 custom_recipe。Case 有 grant_history_json，Workspace 有 request_hash，第四 migration 已应用于本任务专用库。
- V2 check_workspace 先跑原域 validate，检查整个原稿+试改（合计 24k 字符上限）、精确 constraints/completed_checks；遗漏不签 passed。revision/world_stress 完成要求两种不同方案+各自检查+compare，否则 partial。member rollback 后不再引用过期 row 对象。case/workspace/run 锁顺序已调整，但尚缺 PG 真实并发/lease 验收。
- 新完整 provider-only test_runtime 测试：16 次模拟 provider 调用走调查→2 方案→2 检查→比较→明确确认后 Writing 原写入，累计用量 16。旧调查测试明确换为 deep_review 配方（该测试不要求试改）。Collaboration + Forecast + RP + observations 最新组合 24 passed。
- PG tests/e2e/test_creative_engine.py 当前 8 passed：包括原全回滚/幂等/删除覆盖/新增来源失效，以及 rebase/revert/续期、不可变 trigger/跨项目 FK。四条迁移已 upgrade head：20260920_creative_engine / assistant_forecast / interaction_input / creative_recovery。
- 前瞻已接入八个 author domain port（加 RP 共九域），并增加跨域同源根事项与明确 prior_forecast_run_id 的覆盖复查。未有资料的能力标 not_checked。部分领域目前只是保守原入口提示，需逐项对照 WP11/WP12/33能力，不能据目录宣称真实深层适配都完成。capabilities.json 仍 proposed；正式 readiness/quality gates 待实现。
- RP 前瞻：modules/interaction/forecast.py + forecast_api.py；路径 /api/interactions/journeys/{journey_id}/forecasts。服务端解析隐藏 novel，额外拒绝匿名/demo；选择路径/selection/source/overview epoch 绑定；只使用近十二条已选正式消息+有效回顾，不给未来原作/未选分支/全知摘要。固定 source 失效失败关闭；active/unresolved attempt 拒绝；prefill 返回文字而不发送。Root Assistant 共用 runtime/service 增 persona 参数，默认 author，RP 由 DI 注入 authorize/materialize。ForecastContext/公共 schema 经 modules.assistant.contracts 导出，跨域只走 facade/contracts。
- RP provider-only test_forecast.py：纯读不建任务、作者 API 不接受隐藏项目、未选兄弟分支不进模型、2 请求、prefill 不写消息、来源 epoch 变化后拒绝旧预填，1 passed。更多 anonymous/demo/跨账户/overview/future/cancel/unknown operation 边界用例仍待补。
- 前端新增 CreativeTrialEditor（手改/原操作恢复/冲突字段选择/rebase/revert），InteractionForecast（独立 suggestion feed、手动分析与预填，不接看海步骤）；CreativeExperiments 加恢复/续期/缺项说明。原 InteractionView 与新 TrialEditor/RPForecast 共 60 tests passed；Forecast+ProjectAssistant 22 passed；这些是 Vue 单测，不是浏览器验收。
- UI 待修风险：CreativeTrialEditor 本地旧修订草稿暂只报文字备份仍保留，未提供完整恢复 UI，随后 backup 可能覆盖旧备份；子组件 backup 失败离开保护需与父级单槽 leave guard 合作，不能各自覆盖；CreativeExperiments trialUpdated 的跨项目晚到 guard、case 切换/merge unknown 仍需独立审查；RP 新组件源变化时旧未知提交恢复细节、设置按钮待完善。No browser/server launched yet。
- 已同步代码与架构文档，新增 docs/modules/21_collaboration.md 与 collaboration README；表/任务/前缀注册、核心设计、跨域说明、Vue说明、Prompt说明、drawio/html图、开发/测试/维护指南。最新 make docs-check BASE_REF=origin/main 通过：10 modules,128 tables,50 tasks。CLAUDE.md 仅增加模块导航，AGENTS 未改。新图还需视觉 QA。
- 应用了 writing-for-agents skill（已阅读并告知）来维护 CLAUDE 入口导航。此前 ponytail、frontend-design 已读取。未用平台记忆事实，无 memory citation。
- Ruff 对本任务 Python 进行了 format/安全 fix；剩余长行已主要处理，当前局部 check 通过。注意 Ruff 曾删除 Story contract 的重命名 re-export，已恢复 ActionIntentContract/InputStimulusContract + F401 说明，并重跑 RP ensemble/forecast/observations 9 passed。不要再次删除这两个公开导出。新迁移 SQL 被格式化为相邻字符串，运行值未改变，建议最终整理可读性。
- 未完成：完整架构边界静态门禁/Prompt binding inventory、全部 lint/build/test-ci、跨模块回归、PG 并发、真实浏览器功能与窄屏/截图、评测材料和成本/盲评工具、灰度/回退/保留删除任务；这些都须继续。不可将真实模型/人工质量 gate 的未验写成通过。
- Prompt binding 入口 backend/tools/prompt_contracts/capability_bindings.py，新增 runtime 调用文件尚未登记。原 capability registry 已加入 collaboration.run/plan/investigate/revise/check 与 assistant.forecast/interaction.forecast。Forecast 声明 manual_resume 但当前没有专用 resume API/实现，需补同预算/检查点恢复。
- 下一步有用的读取：附件 V2 §13–14 与 ZIP tests/work-packages.yaml / acceptance-cases.yaml；17? 实际文档 16 WP、85cases。P3 环境/location/belief、World scene test、P4 changes→Case、P5 research/import/custom/multi-model/quality 在范围内，不得悄悄变为未来计划。


## P3–P5 与后续整合检查点（2026-09-20T23:11:24+08:00）

- P3 新增 `ObservationIntent`（保持旧 ActionIntent 不变）、带自身 observation event_id 的私有 BeliefChange、locations/location_catalog/routes 与 SimulationSeed。移动到未声明/不连通地点保持 uncertain，场景公开观察按地点分开，belief 不进入 resolver/public events。StoryOneClickTaskRequest 仅 observation_v2 可携带 simulation_seed，初始物品/位置明确为作者试验假设；seed 进入 source_hash/replay。SceneRehearsalPanel 支持新记录方式、唯一物品/地点条件和无模型 replay；旧协议分叉保留协议与条件。最新相关 backend 12 passed，局部 Scene eslint 通过。仍须真实 Story queue/Scene UI 与资源初始状态的完整验收，RP 玩家自由文本物品动作尚未有结构化提取，RP 已知资源初始化/位置完整路径仍需补。
- P5：Project.build_project_llm_execution_snapshot 新增可选 provider_id，继续只能取 owner 已验证连接。Grant.model_connections 分 plan/member/check；run.llm_snapshot_json 新格式 primary/roles，runtime AsyncExitStack 开多个原 gateway client，所有角色共用 budget，audit 使用 check client。主预算仍是唯一执行账本。未配置模型连接拒绝入队测试通过；实际两个不同已验证连接的 provider-only 交叉验证尚未补。
- P1 查证：Evidence.collect_creative_manifest 的 project 授权现在保存完整授权集合 query_scope_hash，但初始只将显式资源放进模型包；WorkProposal.search_query 可有界字面回读最多三处，额外 Snapshot 带 read_range/range_hash，仅有读权限。新增 test_project_query... 通过，排除项不进结果。查询范围上限 5000，输入资源 200，模型文本仍 24k。已补按旧 Writing draft 映射逻辑章节排除，防新版本带回排除项。
- 修了原确认范围潜在外扩：Forecast 先 rematerialize 原 confirmation，带确认时不追加原始章末/目标对象的全文，只用已确认文本；焦点 draft 必须在原 selected/source_manifest 且不被排除。V2 完整资源试改若字符串字段不在原确认渲染文本中则拒绝，要求完整选材。还需专门负例（同章后序 Scene、short hidden fact、预算排除、原确认 action）验证，不可因保守拒绝宣称支持所有片段改写。
- P5 research：`collaboration/research.py` 沿现有 searxng/web public read 与私有文字/标题 egress guard，仅允许明确 Grant + author + investigate/countercheck；盲读不联网。调用前持久化 web budget，页内容和 hash/time/range 保存不可变 research_sources artifact，重复同 query+manifest 复用；已读外部 reference 永不进入可编辑 Grant。传输替身测试通过（此测试不是 provider-only），绑定端点变化/SSRF 等原 infra 门禁仍需适用回归。read_source 单页前 2000 字为明确范围；额度不足保留已读，仍需查看 resume/崩溃/未知回执路径。
- P5 import_consult：新增 Imports.ImportConsultScope / consultation.py + facade；读取原 freeze_resolution（repair_scenes=False，不授权采用）和 exact source refs，绑定选中组、fingerprint 与原稿。Grant.import_scope 必须有 expected_hash，不能混用 confirmation/exclusions；import_consult 只允许这些原组，不接任意编辑资源。SourceSnapshot 增只读 import_review_group / external_reference 类型。实际 SQL test_consultation 通过，1组未扩大、无任务/采用、改组后拒绝。
- 前端 CreativeExperiments 已加入补查范围、三角色已连接 provider 选择、默认关闭联网、自定义问题/附加检查、原导入组选择+先拿具体 fingerprint 再创建 Case。未知提交暂不切目标，确定性 4xx 才清 pending。方法 publicUrl 只链接实际回读 HTTP(S) 来源；run_view 增 safe evidence excerpts。UI 更多功能还需新测试和浏览器，不要只按组件存在计完成。
- 前瞻重复/恢复：增加同任务 `/runs/{id}/resume` 与 can_resume（实际 task lifecycle/source/剩余额度合格才可）；保留 proposal/budget，unknown usage 拒绝。原 operation lookup prepare 现在符合完整 OperationView，含 child RunView；PreparationReceipt 带保存 draft_id/hash，原确认场景的前端脏稿保护不再因缺文字 ref 而误阻断。writing 原生成预览已有 fallback confirmation，仍需前瞻→真实写作 task 的完整测试。RunView 重复 can_resume 字段已去掉。
- 前瞻 cache 只复用五分钟内的同 compute_key，避免过期候选永远空回放。新 payload.anchor + host 字符对齐可继承同章节同物理事项的 issue_key，模型 question_kind 不再控制身份；非 Writing 用稳定 source identity。需补“改写后明确拒绝不重开”和不同事项不合并的真正测试。相同继承 key 去重记录 merged count。Scene activation/章节完成/object reappearance 暂缓事件尚未接入。
- P4 自动跟进：Grant.follow_changes 默认 false，后台联网另需 allow_background_web（默认 false）；拒绝带原 confirmation/精确导入组的自动重选材。`collaboration/proactive.py` 检查授权 Case、来源实质 hash、同章节版本重定位，沿累计预算提交。`assistant/creative_queue.py` 在原 Watch policy/dirty 分区登记，45s 稳定/10min 冷却，原 schedule_due 与 review/forecast 按 due 共用 slot 与日额度。没有新增 queue/table/执行器。
- 自动 Case Run 的 AssistantRun 是同 ID、同 task_id 的纯读投影（protocol creative_projection_v2 / authority collaboration_run）；真正执行、预算/lease 只在 CollaborationRun，终态/取消同步投影并释放原 active_run。Case 的锁顺序增加原 Watch→Case→Run/Workspace，避免反向锁。权限收窄（关闭自动跟进）允许在旧来源失效时先停，不要求重新选材。已完成 test_explicit_case_grant...：稳定等待无任务、占共享slot、只有一份任务、重复调度0、取消释放，1 passed。更完整 PG 并发/公平/配额/投影不可误恢复仍须验证。
- 最新常规回归：collaboration+forecast+原 proactive 共30 passed；随后新增自动 Case 单测1 passed。Imports consultation+web receipts2 passed；Scene/RP observation12 passed；前端新TrialEditor+ProjectAssistant3 passed（早前RP/InteractionView60、Forec/Assistant22不重复相加）。prompt_contracts 已修6个缺绑定（含基线遗留V1 runner/blind_reader/WorldStress/simulation）并通过24 contracts。
- 待同步 docs：上次 docs-check 曾通过，但本检查点新增 P3 seed/读范围/研究/导入/模型/自动Case说明尚未同步。新长行/import也还需 Ruff format/check。核心已有doc与图不用重写一遍，追加当前事实并更新过时边界即可。
- 仍必须做：World 同一Scenario在基线/试改重测，盲读按前缀冻结问题的真正公共路径；上述 RP 资源输入实际解析/原状态初始化；前瞻各域原 controlled preparation 尤其 Imports group/World impact 操作以及 semantic wake；真实PG并发/CAS/lease/rollback；质量120prefix/12family、A/B/C/D对照/成本/人工双盲材料工具和灰度/保留清理/告警回退；全 lint/test-ci/build/真实浏览器/截图。未做真实模型/人工质量，不得自动开启灰度或声称正式通过。
- 开发原工作区、真实数据库、Guimi fixture、真实 .env 都未改动；所有代码仍在独立 worktree，尚未 commit/push/merge/deploy。请持续完成完整规划，不要用总结结束部分任务。


## 完整实现续接检查点（2026-09-21T00:30:32+08:00）

- 仍是同一完整范围任务，尚未收尾。只在本工作树修改；没有提交/推送/合并/部署、真实付费模型或开发子代理。不要将工程材料当作真实质量门通过。
- World scenario 同基线/候选重测已接入真实 V2 检查；最多八个，超出明确拒绝，不静默截断；来源工作被 supersede 后不再沿用旧情境/检查。Story/World snapshot 的时区序列化修正了 SQLite reload 假 stale。相关 World + runtime 测试已通过。
- 新 `collaboration/blind_reading.py` 与 Grant.reading_stops：最多八个按章节/字符停点的逐段盲读，每点只看此前冻结认知和本段正文，写不可变 reading_point 后才解锁下一段。Story ReadingNode 被 V1/V2 共享。新增 provider-only test_runtime 已证明最早节点不含后序揭示和作者秘密，4 passed（该文件）。
- Recipe.strategy 增 adaptive/single，single 使用同一根预算与工作区/检查能力、共享本轮工作记录；custom_recipe 仍以基础 recipe.id 为准，只缩权限、增加检查。最新补 active output 过滤：planner/single record/完整交付计数不把 superseded 产物当当前成果。此最后过滤尚待回归。
- RP 新 `ensemble_input.py` 使用原 budget/gateway + Evidence 审核解释玩家动作；首次 V2 仅从选中路径正式 assistant story 回读已有物品，排除用户自称、未选分支和 setup。严格出处、持有人、已知地点校验，回执在 attempt checkpoint 重用，正文确认前不写 ActorState。捕获 ORM 值后再做会 expire_all 的 checkpoint。未知动作标 unresolved；host 即使收到 succeeded 也降为 uncertain。不可跨地点/离场持有人夺物；私有观察保留最近128条，遗漏标明，旧不可变 revisions 仍可追溯。需要新的 provider-only 完整 action/跨轮测试，目前主要旧 RP held stream/observation 回归通过。
- 前瞻 Imports 具体组 preparations 已映射原 resolve_review/accept_review/resume，章节范围和 fingerprint 严格保持；Evidence 增原 focused_search 的 prepare/confirm 操作（沿原任务、选材和 manifest，原 confirmation/excluded 不扩权）；World 选择可预览将方案文字记入原工作稿，明确未发布。原 focused_tasks 抽出 prepare_focused_search，submit 仍同入口。适用局部20 tests已通过。
- 前瞻 wake.py + activity 写入口（feed仍纯读）：Scene 激活、章稿完成、到时、已同步对象后续章节再出现；同章编辑不醒、缺来源保留 unavailable 说明。尚须实际 wake 用例和 UI 条件选择（目前 UI 仅 manual_reopen）。对象更细的 Scene 内再出现目前不支持，文档已如实注明后续章节。
- 配额现在同时核用户时区日历日和滚动24小时，not_before 防止普通保存刷新覆盖配额冷却；活跃 import/run 推迟30秒避免占据扫描前十导致饥饿。scheduler 已改为先项目 share 再 Watch skip_locked，避免与 merge(Project exclusive→Watch)锁序相反。新的 quota/timezone/公平和共享槽并发需补。
- 维护：新增 forecast/maintenance.py 标 expired（保留不可变评估、来源与采用引用到项目删除），diagnostics 24h上限1000回执输出未知用量/队列告警。collaboration/maintenance.py 在原 worker tick 取消过期/关闭/禁用配方的未完成执行，保留预算/回执；Grant expiry序列化UTC使SQL过滤可靠。现有 service.expire_run_histories 调这些，无新外部队列或常驻服务。需补关闭/过期维护实测。
- 配置：默认关闭5个新开关，Compose shared runtime 已接。新增 FORECAST_PROJECT_ALLOWLIST、FORECAST_DISABLED_CAPABILITIES、CREATIVE_DISABLED_RECIPES；运行中 guard 每次检查当前灰度资格；原 prepare batch 也重验，完成的历史仍可读。尚未加V2逐项目allowlist；若需要可沿相同设置补。
- 恢复：Case require_run(lock) 用真实 Task 终态修正被中断的 running/pending，视图只计算状态不写；同Case新提交不被死运行永久阻塞。背景 resume 重新占原共享slot并同步只读 AssistantRun投影。generic Assistant get/resume 对投影改为读原根/拒绝错误入口，未开第二执行根。Forecast view/resume 同样从 Task 计算终态，并检查原预算剩余时间。需专项 lease/crash/未知用量测试。
- UI：CreativeTrialEditor 保留旧修订本地文字并可显式载入；跨项目 trialUpdated 加 fence；router 注册辅助 leave guards（独立集合，不覆盖原 island guard），备份失败离开/关闭/切标签保护；Writing 监听采用回执，仍clean则通过原editor安全reload，晚到新输入保留并标冲突。增加真实资源目录 GET /collaboration/resources 与更多章节/领域选择，盲读停点可配置。最新相关前端4 files /45 tests通过，但新增资源/留存/路由门需要新用例。盲读 reading_point 的认知明细 UI 尚需展示。
- 质量材料：`evals/creative_forecast.py` + 原创 families.json（12种不同因果机制，120prefix，48安静反例，8dev/4holdout），corpus/blind/report命令纯离线；两套CSV/HTML保持独立评阅，私有arm映射不发评阅者；creative A/B/C/D工具公平门、forecast静态A/语义B，族聚类区间、失败/未知用量/成本保留。单测1passed。还需补 C-D对照/结果导出绑定实际gateway provenance、用例/质量阈值审阅及生成实际交付材料，不能称真实评测已完成。
- docs已同步新版21_collaboration、20_assistant、02_world、13_imports、15_map及开发/测试指南。最新 make docs-check BASE_REF=origin/main 通过（10模块128表50任务16route35ADR）。图视觉 QA 仍待做。最新 Ruff 全库曾通过，之后active artifact过滤可能须format。
- 新PG并发 tests/e2e/test_forecast_creative_concurrency.py 实际独立sessions：Case同operation并发、merge同确认并发、forecast同operation并发、notice CAS、Project硬删除级联均通过1test。前两次失败仅测试fixture返回类型/horizon遗漏，已修；第一次无-m被deselect，不算验收。原8 PG仍需与新变更一起回归；尚缺真实worker/lease/cancel/source-edit races。
- 浏览器专用第二库已新建并从空库完整迁移成功：ai_novel_agent_e2e_forecast_01a0be6b（同PG17 Docker ai-novel-db端口5207，公开dev口令）。绝非原Guimi/default库。新 `playwright.creative.config.js` + `e2e/creative-forecast.spec.js`，沿现有 tests.support.assistant_browser_app 的真实API/worker，仅替换Provider传输；helper creative_browser_provider.py 输出16请求的两方案流程。初次浏览器失败是缺Chromium二进制；正在install，session 35153。测试进程已退出，服务已停止；迁移已到head。浏览器测试要重跑，按钮名与 getLatestDraft.content 已按真实代码修正但未运行。
- 当前后台命令：make test-ci TEST_WORKERS=2 session5962 正在deploy270test阶段，docs/secrets/deps audit/Ruff此前通过；backend audit报告langchain-community archived但无已知漏洞。Playwright install chromium session35153 已下载Chrome182MB，headless94MB还在下载。没有functions.exec yielded cells。最新PG session92543完成1passed。
- 下一步：等待浏览器安装，重跑端口8133/8134的独立browser；检查CI最终结果并修；补高价值PG worker/lease、操作/源/权限负例、配额/wake、UI旧草稿/晚到；整体frontend lint/build与prompt contract，最终schema parity/原WIP核对/85cases映射和文档交付。不能现在结束为部分完成。


## 最新恢复检查点（2026-09-21T01:52:03+08:00）

- 00:30 后已完成的主要修正：共享根 capability 必须 `collaboration.run` / `assistant.forecast`，子步骤身份保留在 step_name；未削弱 AIRunEnvelope。真实 worker PG 7项覆盖成功、取消、来源变化、shutdown、超时、未知用量、partial续算，同一个run/task不刷预算。加既有PG组共21项通过。
- `make test-ci TEST_WORKERS=2` 已有完整绿色：270 deploy、5943 backend（13 skipped, coverage85.5%）、2532 frontend；docs/secrets/Ruff/依赖审计通过。之后的最新改动尚需最终回归，不能用旧绿色代替。日志 artifacts/test-ci.log。Prompt contracts24passed。
- 正向多模型新增测试暴露 Evidence 审查省略 request.model 时仍沿用 schema 默认 deepseek-flash。已在 LLMClient.resolve_request_defaults 按 model_fields_set 继承实际客户端模型，显式模型优先；129项 client/knowledge/runtime 测试通过，包括两个已验证连接共用Case预算。测试局部打开Kimi兼容开关，生产默认不变。
- Case策略single/adaptive、定向反证、研究/导入真实工具、自定义配方缩权、多连接、盲读逐段冻结、World同场景前后比较均已实现；禁止superseded成果签新检查；planner须显式finish，否则有限轮数结束partial；grant修改和资源重新选择不刷累计消费。
- 前瞻 explicit_decisions 冻结作者拒绝/普通细节到下轮输入、缓存key与执行guard；同物理段落跨稿对齐且相似quote，完全不同替换不复用旧拒绝。语义不同question_kind不合并，相关输入/摘要不增加锚点支持分数。新断言已通过；重新格式后待组合回归。
- wake条件/时区+24h滚动额度2项；维护shutdown/expiry保留试改和累计消费2项；真实project gateway仅替换provider传输的RP物品bootstrap/本轮action/冻结回执复用1项；作者跨账户/demo/匿名/待删除与缺XHR5项通过。
- 真实浏览器曾通过完整原流程（真实API/SQL/worker，仅Provider传输替身）：前瞻→原待办预览确认→Case两方案→检查→精确merge→编辑器刷新→390px。发现merge后缓存旧稿，已在共用api层对跨域确认清理全部GET缓存及late-fill代次，apiCache新测试通过。截图 artifacts/creative-desktop.png、creative-mobile.png、architecture.png均已视觉检查。
- 最新浏览器扩展编辑+IME后发现独立面板读取桥接快照不响应dirty，已用useStateKey修复并同步composition状态。第二轮显示保存产生新draft ID但面板还持旧ID；focusFrom在无原confirmation时跟随当前编辑器draft/scene，原confirmation仍保留其边界。对应session26368在跑；前端session37583在跑。最后一轮之前Forecast单测因初始composing阻止初始化失败，已允许首次读取capabilities，composition期间仍不刷新feed。还未收取最终结果。
- 两个任务专用PG库：ai_novel_test_forecast_01a0be6b、ai_novel_agent_e2e_forecast_01a0be6b（Docker PG17，5207）；四条additive migration从空库通过。schema check当前39个诊断全部基线复现；同DB/同alembic配置基线66项（含期望新表移除），current-minus-baseline=[]。证据 schema-current.log、schema-baseline.log、schema-comparison.json。不是全库schema无差异。
- eval工具生成12原创故事族/120前缀/48安静反例/8dev+4holdout，离线盲评包与报告不调provider；新增C-D比较与holdout族区间。无真实付费调用、无人工评阅。85用例与WP01–16/P0–5映射还须写，不能据测试数量宣称内容质量通过。
- 剩余：固定负载性能；前端异步/最新browser；范围确认与来源负例；最后lint/docs/build/PG与CI；文档交付和capabilities状态；原工作树WIP对照。无commit/push/merge/deploy/子代理/新自动化。

## 最终工程检查点（2026-09-21T02:13:00+08:00）

- 新浏览器输入用例揭示并修复三个真实问题：独立面板不订阅dirty/composition；保存新版本后用旧draft ID；切“试改”仍沿用打开面板时的未确认快照。使用既有useStateKey，原confirmation不自动扩权；刷新只发生在composition之外。最新主干上浏览器成功，截图已更新并视觉核对。
- 发现此前检查点对RP canonical capability修复的描述不准确；现已实际修改 runtime.generate 到 canonical `assistant.forecast`，step_name/知识政策仍区分RP，并在RP测试加真实AIRunEnvelope确认2请求正确记账。相关组合40passed，最终CI包含此修复。
- 最后补强旧评估不复活用例：先通过原CAS重开notice，保留旧A有效，只将最新B失效，feed仍为空；10个Forecast tests通过。全量门禁均在这个最终状态通过。
- 完成能力目录implemented_gated状态（不是质量pass）、C−D及holdout比较、文档性能复现命令；付费/人工授权问题已发出但尚无回复。勿据已完成工程推断该授权。
