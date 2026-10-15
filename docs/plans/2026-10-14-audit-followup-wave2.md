# 能力审计后续第二批计划（2026-10-14）

日期：2026-10-14。状态：**已基本落地（2026-10-15 核对：G6b/G6c 完成待入库，G7b 未启动，均转入
[第三批计划](2026-10-15-audit-followup-wave3.md)）；用户已于 2026-10-14 晚裁定 §5，执行者由用户自行安排**。上级计划：
[能力审计后续批次开发计划](2026-10-14-audit-followup-batch.md)（以下称“主计划”，G 编号、用户裁定与通用门禁以它为准）。

基线：origin/main **M** = `fdd3ec59886e29cc5c9189a1c0fefa225cdc997f`（含 G2 的 PR #225/#226/#228）；
首批 PR #227 评审时 head **P** = `5b5934262dc030e8202883931e7b5d4e5c16ec28`（含 G3①、G3③a、G4a、G8a）；补修 `d54498792`
后于 2026-10-14 晚经用户授权合入 main，合并提交 `0e572c75f`。泳道 B 从这之后的 main 开工。
本文件的现状与行号来自 2026-10-14 下午至晚间对 M、P 的四份只读核查，开工时须在新 HEAD 重核。本文件只规划，
不证明任何分支的实现或验收状态；任务记录见 `.agent/tasks/2026/T-20261014-audit-followup-batch/TASK.md`。

## 1. 首批进度核对

| 项 | 状态 | 证据 | 还剩什么 |
| --- | --- | --- | --- |
| G1 nightly 签收 | 完成 | run `38500624771`，287 passed | 无 |
| G2 Codex/Luna 运行时收敛 | **已合入 main** | PR #225 `e02137f79`、#226 `d904eb8d1`、#228 `fdd3ec598`；main 六个 push 工作流 success；[验收报告](https://github.com/FengHuoLinShan/ai-writing-assist/blob/fdd3ec59886e29cc5c9189a1c0fefa225cdc997f/docs/acceptance/2026-10-14-codex-luna-convergence.md) | 旧约 1.91 秒 unknown 原因未定；8 个旧运行时 worktree 仍保留；Guimi 全量 paused，旧 v2 快照无已验收续跑路径（§3.8） |
| G3① renderer 退役 | **已合入 main**（#227，`0e572c75f`） | 固定 IR 967 bytes、SHA256 不变；`d54498792` 同 head 18 项检查 success | 无 |
| G3③a 本机文字入口缩面 | 同上 | 开发库只读计数：旧文字 pending task/invocation/snapshot 均为 0 | 无 |
| G4a 服务器侧图片备份 | 同上 | 隔离无网络演练 7 图/2 桶恢复通过，RPO≈2.6–3.6s、RTO≈4.8–6.7s（小合成集） | 生产启用另需发布授权 |
| G8a 改章 → 地图册失效登记 | 同上 | 390px 浏览器、SAVEPOINT 降级、owner+novel 隔离均有证据 | 无 |
| PR #227 评审后补修 | **已随 #227 合入** `d54498792` | 15 文件：G4a mirror 逐行隔离、G8a 地图 port 的 DomainError 同样降级、写作提示改用作者语言；本地部署 316、后端 fast 7965、前端 2987 通过；同 head 18 项 CI 通过 | 无 |

三路 Sol/xhigh 独立审查对 P 无确认 P1/P2（`.agent/tasks/2026/T-20261014-audit-first-batch/REVIEW-XHIGH.md`）。
第二波各项均未开工。

### 1.1 主计划中已过时的前提

- “模型规则尚未进入主干”不再成立：规则已随 PR #225/#226 进入 main（`AGENTS.md` 运行时 LLM 节、`development-guide.md`
  开发阶段模型约定）。主工作树 `codex/guided-flow-borrowing` 上的本地提交 `b22f7334e`、`4116b657d` 已被取代，不再推送。
- “G3② 排在 G2 之后”的前置已满足：G2 对 `phase2_world_extraction.py` 只加 4 行并发绑定，与退役范围不冲突。
- “G6 开始条件：G2 合入后”已满足；G7 的真正前置是用户恢复决定（§3.8，已于 2026-10-14 晚裁定），不是 G2。

## 2. 下一批的排序原则

先让首批落地，再开依赖它的项；不依赖 #227 的零费用项现在就可以并行。需要真实模型、私有资料、默认开关或生产的部分
单独切出，等授权，不阻塞同包里的离线部分。

| 泳道 | 任务 | 基线 | 开工条件 | 规模 |
| --- | --- | --- | --- | --- |
| S0 | 首批落地：#227 补修提交 → 同 head CI → 合入 | P | **已完成**（`0e572c75f`） | XS |
| A（现在） | G3② window Phase2 退役 | M | 无 | S |
| A（现在） | G5a 编辑闭环合成 harness 与 E2E | M | 无 | M |
| A（现在） | G6a 评测模型合同迁移（离线） | M | 无 | M |
| A（现在） | G7a 导入扫描基线与长篇账本模板（零费用） | M | 无 | S |
| A（现在） | H3 Dependabot 评估 | M | 无 | S |
| B（#227 已合入） | H1 文档刷新成果集成 | `0e572c75f` 起的 main | 无 | M |
| B（#227 已合入） | G3③b+c 删前端文字审批 UI 与后端死分支 | `0e572c75f` 起的 main | 文档写入在 H1 之后 | M |
| B（#227 已合入） | G4b 作者手动导出图片包 | `0e572c75f` 起的 main | 文档在 H1 之后 | M–L |
| B（#227 已合入） | G8b 改图 → 写作冲突检查可核对 | `0e572c75f` 起的 main | 新 DI 键在 G3③b+c 之后（只因共享文件） | M |
| B（链式） | G3③d 删 LocalCLIClient、companion 文字路径与工具中继 | G3③c 合入后 | G3③c | S |
| C（已裁定） | G5b 闭环缺口修补、G5c 编辑台开关透传 | G5a 后 | G5a；生产开启另需发布授权 | S–M |
| C（已授权） | G6b 真实校准、G6c 新 holdout | G6a 后 | G6a | M |
| C（已授权） | G7b 诡秘前 60 章新 v3 全链 | G7a 后 | G7a；语义教师评分依赖 G6b | L |
| 暂不做 | G7c 代理作者试用 | — | 用户 2026-10-14 晚裁定暂不做 | M |

## 3. 任务包

### 3.1 G3② window Phase2 退役（泳道 A）

现状（M 与 P 相同）：`Phase2WorldExtractor` 在 `backend/modules/imports/phase2_world_extraction.py:88`，全文件 1304 行，
生产零实例化。唯一外部引用是 `backend/tools/prompt_contracts/probes.py:13-35` 的 probe（:196 注册），合同
`phase2_world_extraction.json:34` 为 `"probes": []`，从未执行。5 个 `phase2.world_*` 键在
`backend/shared/deep_import_settings.py:56-60,112-116,151` 与前端 `deepImport.js:83-87`；其中 `world_timeout_seconds`
已无专用读取点，另有 4 个 `PHASE2_WORLD_*` 环境变量只被该文件读取。`clean_deep_import_settings`（:159-176）会静默
丢弃旧键，旧设置和快照兼容。

做法：整文件删除；删 probe 及注册；删 5 个设置键和 4 个环境变量读取；测试删
`test_workflow.py` 的窗口用例（:1516-1601、:1696-1797，**保留 :1603-1694**）、`test_scene_phase_refactor.py:138-196`、
`test_chapter_loader.py:8` 导入与 :125-167 包装用例（`Mock` 导入仍被 :47/:81 使用，保留）。改写
`imports/README.md` 的 :323、:564-566，以及 G2 新增“Codex 工作流接纳”节 :570 中的“World窗口”。

保留：`llm_schemas.py:1031-1168` 的 `Phase2World*`、合同与 fixture（`evals/corpus.py:92`）、
`workflow_entity_phase.py` 对历史 artifact 键的读取、Scene Phase2 全链、`scene_fusion.py`、
`parser.py:271` 的 Prompt 字面量、`tools/deepseek_scene_probe/*`。

完成标准：imports 模块测试、`make prompt-contracts`、前端设置页 Vitest、`make lint`、`make repo-gates`
通过；依赖棘轮不变（被删文件只导入 imports/shared 内部）。估计约 8 个文件、净删约 1650 行。

### 3.2 G3③b+c 删前端文字审批 UI 与后端死分支（泳道 B，一个 PR、两个 commit）

合成一个 PR 的理由：前端消费的 API 响应字段 `local_agent`（`{kind, approved}`）要在后端删，前端必须同时或更早停止
消费。先 commit 前端，再 commit 后端，各自可回退。

**前端（原 G3③b，以 P 为准）**：`ProjectAssistant.vue`（模板 :20-27，`localReceipts`/`approveLocalRun`/
`loadLocalReceipts`）、`ForecastDock.vue`（:12-15、:84-92）、`CreativeExperiments.vue`（:7-10、:125-131）、
`InteractionForecast.vue`（:7-10、:86-96）、`InteractionView.vue`（:213-228、模板 :2279-2282 与 :2298-2301）、
`useStorySceneWorkspace.js:1076-1086`（每次排演多发一次 pending 请求，删后减少一次请求）。对应 Vitest 4 个文件约 80 行；
保留 `InteractionView.test.js` 中 G3③a 的回归用例。`api/localAgent.js:13` 的 `receipts` 包装删后无调用者，一并删，
后端 `task_receipts` 端点保留供历史读取。保留 `LocalRunApproval.vue` 与项目设置“本机 CLI 生图”区块。

**后端（原 G3③c）**，比主计划写的范围大，要点：

1. `is_local_agent` 判断在 `infrastructure/llm/agent_runtime.py:685`、`interaction/agent_runtime.py:540`、
   `interaction/proactive.py:253`、`story/simulation.py:299`、`assistant/teams/runner.py:428`；collaboration 没有该判断，
   但有 `_local_agent`/快照分支（`collaboration/cases.py`、`runtime.py`、`views.py`）。另有 `interaction/tasks.py:53-74`
   构造 `LocalCLIClient`、`story/rehearsals.py:171-180` 的死分支、`assistant/forecast/runtime.py` 的
   `local_task_meta`。死分支依据：`project/llm_runtime.py:222-225` 对含 `local_agent` 的快照一律拒绝，
   `local_task_meta` 对新快照恒为空。
2. **`open_task_snapshot_client` 不是本机专用。** collaboration（`runtime.py:303,310`）与 forecast（`runtime.py:468`）
   对所有 run 用它打开快照客户端。删除时改指 `modules.project.facade.open_project_snapshot_llm_client`；两者差异是
   后者多一次 `_bind_codex_authorization`，并带 `timeout_override`/`injected_client` 参数。这是行为替换，须补
   collaboration 与 forecast 快照恢复的测试。`task_snapshot_client` 是 G3③a 在 `local_agent/README.md:84-86` 明确
   保留的第二道失败关闭门，删除时同步 README 与 `test_text_retirement.py`，Project 恢复门的覆盖由
   `test_local_agent.py:333-351` 与 `project/tests/test_codex_runtime.py:318` 继续承担。
3. API 响应字段 `local_agent`：`interaction/schemas.py:308`、`journey_views.py:743-750`、`assistant/schemas.py:161`、
   `service.py:620-625`、`assistant/forecast/contracts.py:472`、`collaboration/views.py:113-115`。只有本仓库前端消费。
   `assistant/service.py` 中 `agent_executor` 的历史运行失败关闭守卫（:609、:861、:952）保留。
4. DI 键 `ASSISTANT_/INTERACTION_MARK_TASK_LOCAL_APPROVED`（`core/service_keys.py`）及 `app/bootstrap.py` 注册、
   `local_agent/api.py:451-457` 唯一调用、四处实现、`test_assistant_operation_registry.py:369`。
   `infrastructure/tasks/lifecycle.py` 与 `enqueuer.py` 的 `_local_agent/_local_ready/_local_approved` 服务图片任务，**不删**；
   `task_awaiting_local_approval` 被图片生成使用，**不删**。
5. 依赖棘轮必须按实测精确重算：`scripts/check_module_imports.py:86-93` 在 P 上为 65 边 / 9 双向 / 522 函数级，
   `test_governance_gates.py:537-548` 要求完全相等。预计 local_agent 的入边从 5 条降到 1 条（world 因图片保留），
   :683-686 的 `interaction/tasks.py:modules.local_agent.client` 豁免随之删除。ADR-0031 的 :60、:63、:97 同步。

文档：assistant README、`docs/modules/18_interaction.md`、`23_local_agent.md`、`12_infrastructure.md`、
`docs/00_整体设计.md`、`CONTEXT.md`、`development-guide.md`、`testing-guide.md`、`backend/infrastructure/llm/README.md`、
`backend/infrastructure/tasks/README.md`、`frontend-console/README.md`、`docs/01_数据库设计.md`、local_agent README。
这些与 H1 文档集成大量重叠，**文档 commit 在 H1 合入后写**。

完成标准：interaction/story/assistant/collaboration/local_agent 模块测试、`make test-postgresql-critical`、前端
Vitest 与 lint、受影响浏览器（助手、前瞻、RP、排演各一条正常流，MapAtlas/WorldEntityImage 批准流程不回归）、
`make repo-gates`；collaboration/forecast 快照恢复在 Key 轮换后仍可用。估计前端约 7 个文件、后端约 20 个生产文件，合计净删约 380–460 行。

### 3.3 G3③d 删本机文字客户端与工具中继（泳道 B，G3③c 后）

范围：`local_agent/client.py` 整文件（112 行，唯一生产调用方 `interaction/tasks.py` 在 G3③c 已删）；
`companion.py` 的 `_SHIM`、`_run_text_job`（:222-305）、`tool_main`（:421-447）及 `_job` 内文字分支，非图片 job 明确失败；
`local_agent/api.py` 的 `ToolRequest` 与 `/companion/jobs/{id}/tools` 两个端点（:578-644）。图片 invocation 的
`request_json` 带空 `tools`，中继对图片不可达。

**`backend/infrastructure/llm/cli_agent.py` 不动**：G2 的 Codex 文本适配在其中，`novelcraft-agent.pyz` 也随它分发。

测试：改写 `test_local_agent.py:153-231`（保留 heartbeat/finish/receipt 断言），删
`test_companion_image_job.py:150-196` 的文字用例与 e2e `test_companion_tool_round_trip_on_postgres`（约 138 行）；
`test_exhausted_tool_budget_ends_the_local_run` 直接测 `run_local_agent`，保留。

与 ADR-0029 的关系（默认假设，见 §5）：ADR-0029 :19-20 保留 `run_local_agent`“仅为日后按新 ADR 重新开放”。删中继端点后
它在代码中保留但无生产入口；重新开放本来就要新 ADR，届时一并恢复端点。在 ADR-0029 追加实施记录写明这一点。
`LocalAgentToolCall` 表与迁移不动。估计 6–7 个文件、净删约 550 行。

### 3.4 G4b 作者手动导出图片包（泳道 B）

G4a 已在 P 上实现包格式和恢复入口，不只是文档：`deploy/scripts/object_backup.py` 的 `read_manifest` 接受
`source_kind=author_export`（DB 三字段须为空），`unpack_package` 要求 ZIP 成员**恰好**是
`snapshots/<UTC 时间戳>/manifest.json`、`manifest.sha256` 和 `objects/<file>`，清单状态为 complete，每行 sha256、
`byte_size>0`、`status=ok`；`restore` 按行写 `content_type` 并回读比对，所以行必须带 content_type。
`restore_objects.sh` 单参数接收私有 ZIP，要求文件 0600 且 nlink=1。补修只动 `mirror`，没有改格式面。
核查时在 scratchpad 实验过：fflate 0.8.3 流式 `Zip` + `ZipPassThrough`（store）打出的含中文路径包，能通过 P 的
`unpack_package` 与 `read_manifest`；没有 UTF-8 标志位时中文名会被解成乱码。真实浏览器、大文件、Linux 文件名
字节上限都还没验证。

主计划 §6.4 有几处与代码不符，以本节为准：

- **现有端点拼不出清单。** 世界对象列表分页上限 50、默认排除归档对象，不返回 hash 与 size；地图没有“全部页”端点，
  要合并 `/atlas`、`/pages/history` 和 run 结果三类，且都不返回 object key（含 `attempts/{token}`）与 media_type；
  mask 没有任何读取端点。所以 G4b 要**新增一个 owner + novel_id 的只读导出清单端点**，再按清单经现有图片读取
  端点逐张拉取。
- **fflate 目前只用于解压**（`themeArchive.worker.js`），打包 API 只在 e2e 用过，且没有内置输出汇点；汇点、
  单包上限与分包要在设计里定。主线程流式 store 不需要改 Vite manifest 和 CSP，放 Worker 则要照主题 Worker 接入。
- **可读文件名只能放在 `objects/<file>`**，不能另附作者可读索引（成员集合精确比对）。世界对象名与地图页标题
  都没有唯一约束，命名要处理 NFC、非法字符、单段 ≤255 字节和大小写不敏感去重。
- 主计划“新增清单端点按 ADR-0013 不需要 operation_id”结论成立，但理由应是 ADR-0013 只管 AI 长任务。

范围：

1. world 新增只读导出清单端点，`allow_demo_readonly=False`，响应 no-store、不入日志。返回 author_export 行所需
   全部字段：地图页（全部 review 状态，含 attempts key、`image/png`、DB 中的 sha256 与 byte_size）、世界对象的
   full 与 thumbnail 两个变体（含归档对象，带 image_version，`image/webp`）、地图 mask（`map_mask`，同一门禁下新增
   窄读取）。可导出集合以此端点为准；G4a 的引用
   SQL 会计入 `uploaded` 瞬态页，但读取路由不放行，两者差异要写明。
2. 前端：`ProjectSettingsView.vue` 作者页签“导出作品”之后新增“导出图片包”区块（可拆组件），文案区分“导出作品是
   文字，服务端生成”和“图片包由浏览器生成，用于恢复”；打包器自算 sha256，写清单与 `manifest.sha256`；进度、取消、
   失败逐项列出、离开保护；`api/world.js` 加清单方法，`fetchMapAtlasImage` 补 signal。离开保护可参照
   `MapStructureEditor.vue` 的“确认已保留下载备份并离开”。
3. 浏览器生成的包在 Linux 容器隔离环境经 `restore_objects.sh` 恢复并对账；G4a 演练新增“浏览器产物”用例。
4. 文档：ADR-0010 补充段中“本轮 G4a 无导出 UI”改为 G4b 现状，并说明这是单项目 owner 导出，不是账号级全部项目
   导出；ADR-0034 :47、:51、:52 改为已实现描述；`deploy/README.md` 中“G4b 尚未实现”各处及 :350 的 key 口径；
   `docs/modules/12_infrastructure.md`；README 写明下载的 ZIP 恢复前须 `chmod 600`。

用户裁定（2026-10-14 晚，按推荐）：

- **key 暴露口径。** 主计划 §6.3 第 5 条与 P 的 `deploy/README.md:350` 原写“object key 不经任何 API 暴露给浏览器”，
  但浏览器打包的清单行必须含 key。改为“不对非 owner、不经通用 API 暴露；仅 owner + novel_id 的导出清单端点
  返回，no-store，不入日志”。主计划已改；`deploy/README.md:350` 由 G4b 在 H1 后同步。
- **mask 去向。** 包里没有 mask 时恢复不会报错（`require_target_references` 只查“清单 ⊆ 目标 DB 引用”），但地图
  再生成会失败（`map_atlas_workflow.py:2080-2090` 读 mask）。在清单端点同一门禁下新增窄 mask 读取，
  mask 进包，清单类别用 G4a 已有的 `map_mask`。
- **部分失败。** 失败项进不了包（行须 ok 且 `byte_size>0`）。先让作者重试失败项，仍失败时由作者确认生成
  不完整的包，界面与文件名标明缺几张，清单只含成功行。

默认假设：单包上限按实测峰值内存定，超出时顺序分包，每包有独立清单，可依次恢复。

依赖：功能上可以叠在 #227 分支上先做清单端点与打包骨架（格式已被实验接受）；但格式在补修提交前不算冻结，
ADR-0034、`deploy/README.md`、`12_infrastructure.md`、演练脚本都是 G4a 写入面，所以合入与集成验收在 S0 之后，
文档在 H1 之后。

完成标准：

- 浏览器真机产出的 ZIP（不是 Python 打包）在 Linux 容器内恢复并对账通过；文件名覆盖中文、emoji、同名、
  超过 255 字节和大小写冲突。
- 对账双向：包内行集合等于清单端点定义的可导出集合（含归档对象的 full + thumbnail、各状态地图页与 attempts
  key 与 mask）。
- 失败语义：0 字节、解码失败、hash 不符、网络失败都判失败且不入包；部分失败按裁定行为有测试；取消或离开后
  不留半成品下载。导出期间换图或新增页时，结果以清单快照为准或提示重新导出。
- 文案只说事实，例如“图片包已生成（N 张）”，不写“已备份”。“校验通过”只能指：地图页与 DB 的 hash、大小一致；
  世界图与 mask 为自算 sha256 且可解码，不声称与历史存储对账。
- 清单端点 owner + novel_id、匿名演示拒绝、跨项目不串、no-store；通过 `test_active_project_route_closure.py`。
- 空项目、只有地图、只有对象图、部分失败、大项目（接近配额）、390px、非安全上下文（缺 `crypto.subtle`）有降级提示。
- `make test-deploy` 与新演练用例通过。

### 3.5 G8b 改图 → 写作冲突检查可核对（泳道 B）

现状（以 M 为准）：冲突检查经 `world.list_adopted_map_continuity_facts` DI 键取地图事实
（`writing/service_support.py:167-174` → `conflict_check_service.py:826-848` `_load_map_facts`），创建时
`summary_json` 只写 `continuity_coverage` 字符串（:293-318），不记 revision 或 hash。事实里已有 node_id、revision_id、
revision_hash、source_hashes（`world/contracts.py:60-72`），不用改契约和表结构（`summary_json` 是 JSON 列）。

主计划 §7.4 需要补正的地方：

- **基线要记全部载入的事实**，不能只记触发规则的那几条：`space_route_not_declared` 靠“缺边”判定，没触发的事实
  也构成检查依据。按 (node_id, revision_id) 去重并限量（loader 本身 limit 200），对测试 fake loader 缺字段容错。
- **比较以 revision_id 为主。** `revision_hash` 就是 `geometry_hash`，计算时排除了 sources 与
  `generated_by_task_id`（`map_structure_geometry.py:32-48`），相同不代表同版本；source_hashes 作辅。节点被取消
  采用或删除也算“已变”。
- **比较结果只在响应里算，不入库。** `summary_json` 会进入发布快照（`repositories.py:1386-1412`）和 AI 复核的语义
  指纹（`conflict_ai.py:806-849`）；创建时写入、之后不变的基线不影响指纹，但“已变”结果写回就会让指纹漂移。
- **writing 不能 import world**（`check_module_imports.py` 中 writing 的允许边是 account/evidence/project/story），
  world 也没有按节点批量取当前 head 的出口。
- **不复用 G8a 的 `MapChapterConsumptionPort`。** 它的 Protocol 在 evolution，writing 不能依赖；语义是“改章 → 引用旧
  正文的地图”，和“节点集 → 当前 head”不是一回事，而且会回调 writing 重验来源，代价高。
- **要改前端**，不是纯后端：`ConflictDetailDialog.vue` 的降级提示只在 `status === 'degraded'` 时显示，completed
  需要新提示位；来源标签只认 `world.map` 前缀，而后端发的是 `continuity.map`，现在落进“部分来源”。

默认假设：world 新增只读“按 node_ids 批量取当前 head”出口与 DI 键，消费方 Protocol 定义在 writing 侧（同
`MapContinuityLoader` 模式），一次查询，按 ADR-0031 惯例补正常态与空态 port 测试。备选是复用既有事实键在读时
重算（较重，来源漂移也会判为变化），或在前端拿 `/atlas` 的 `current_revision_id` 比对（后端与 AI 复核看不到）。

范围：writing 创建时记基线、读时比较并声明响应字段（`_to_check_response` 是同步方法，批量 head 要在调用前预取）、
发布快照中的基线限量；world 出口与 DI 键；`ConflictDetailDialog.vue` 提示位与 `continuity.map` 标签，按需联动
`sceneAlerts.js` 的 check-stale；文档 `writing/README.md`、`docs/modules/11_writing.md`、`docs/modules/02_world.md`、
`world/README.md`。

和 G8a 提示共存：G8a 在写作保存回执（`InvalidationNotice`）说“章节改了，哪些地图还引用旧正文”；G8b 在冲突检查
详情说“检查依据的地图已更新”。文案分开：G8b 用“检查结果基于旧版地图，建议重新检查”，不复用 `mapCheckNote` 和
回执账本；跳转可复用 `getRouter()?.navigate('map', …)` 指向变化的节点。按 revision_id 比较，G8a 报“地图引用旧正文”
而地图本身没改时，G8b 不会误报。

依赖：功能上不依赖 #227。只因新 DI 键要写 `service_keys.py`、`bootstrap.py`、ADR-0031、`check_module_imports.py`
（单一写入者，§4），排在 G3③b+c 之后。

完成标准：

- 历史检查没有基线、`not_applicable` 和无事实的 `not_checked` 都不提示；跨项目不串；列表读取用批量 head 查询，
  不逐节点 `inspect_map_node`。
- 测试证明地图变更前后 AI 复核指纹不变，`public_conflict_summary` 不外泄内部键，发布快照基线限量。
- completed 状态也能显示“基于旧版地图”；来源标签正确；与 G8a 文案区分；390px。
- 新增 DI 键后函数级导入预算不增，`test_container`、`test_facade_public_api`、ADR-0031 同步；writing 不直接 import world。

### 3.6 G5 日常作者闭环

主路径（M 上已存在的入口）：保存正文（`useEditorialGuard` 保存前拦截）→“本章写完，交给编辑看”
（`WritingEditor.vue:8` → `markEditorialReady`）→ 编辑台审读（`EditorialDesk.vue` → `assistant/api.py` →
`editorial.py` worker）→ 作者处置（意见卡、recheck、BR-4 `editorial_bridge.py` → `writing_comment_run`）→
停止/继续与离开恢复。验收口径取 `docs/product/user-personas.md` 画像 A：不越权、不静默覆盖正文、切页刷新不丢进度、
长任务可离开并知道下一步（:35、:47-57、§4.2、§6）。

核实到的缺口：

- 浏览器 harness（`backend/tests/support/assistant_browser_app.py`）没有编辑审读与批注修订的脚本化回复；现有
  editorial/writing-comments E2E 都用 `page.route` 模拟，没有“真实 API/worker + 合成 provider”的闭环。
- “部分采用”没有统一定义：正文候选只能整体采用（`writing/README.md:316-317`），“部分”只存在于助手批次确认、
  编辑台多意见子集处置和骨架包条目取舍三处。
- 生产 `deploy/compose.production.yml:41-75` 没有透传 `ASSISTANT_EDITORIAL_ENABLED` 与
  `ASSISTANT_EDITORIAL_AUTOMATIC_ENABLED`，`.env.production.example` 也没有；compose 用显式 environment 键，
  所以生产目前无法打开编辑台。

切片：

- **G5a（泳道 A，零模型费用）**：harness 增加编辑审读、批注修订的脚本化回复；新增真实 API/worker/SQL + 合成
  provider 的闭环 E2E，覆盖首次进入、空态、审读失败、处置冲突（正文已变 stale）、离开恢复、停止后继续、390px；
  挂进现有 assistant 档位（`playwright.assistant.config.js`，库名含 `agent_e2e`）。不改默认值，不碰 compose。
  产出一份缺口清单，作为 G5b 输入。
- **G5b（泳道 C，已裁定）**：修补 G5a 暴露的缺口；“部分采用”限定为已有三类（助手批次确认、编辑台多意见子集
  处置、骨架包条目取舍），不做逐段正文采用。
  同步 assistant README 与 `docs/modules/14_frontend.md`。
- **G5c（泳道 C，已裁定透传）**：compose 与 `.env.production.example` 透传两个编辑台开关，默认仍关；首批开放建议：
  `ASSISTANT_ENABLED` + `ASSISTANT_EDITORIAL_ENABLED`，自动审读暂缓（会在后台产生模型用量且无真实质量证据）。
  生产开启另需发布授权。

真实意见质量不在 G5 测，并入 G7，评测包用现成的 `backend/evals/datasets/editorial/`（原创合成文本、正文 SHA 固定、
六项 0/1/2 评分）。任务记录复用 `T-20260924-editorial-assistant`，或新建主笔记并链接它。

### 3.7 G6 评测模型合同迁移与校准

更正主计划：Ask World 被测端已经走 Project facade（`backend/evals/ask_world.py:905`）。真正要迁的是独立
`CodexStructuredExecutor` 路径（教师、judge、review、scene-gold），它现在被 `backend/evals/codex_executor.py:29-35`
的暂停守卫一律拒绝。G2 没有改 `backend/evals/` 的这些路径，只新增了 `codex_luna.py`。

还要处理的漂移：`backend/evals/schemas.py:11-19` 仍是 `gpt-5.3-codex-spark` / `gpt-5.6-luna` / `gpt-5.6-terra` /
`deepseek-v4-flash`，产品侧是 `codex_provider.py:32-33` 的 `gpt-6-luna` / `max`；`datasets/README.md:10-45` 与
`Makefile:122,125` 的说明仍写旧合同；全库没有“与历史分数不可直接比较”的明确正文，只有
`testing-guide.md:27-30,638-641` 的近似表述。

切片：

用户裁定（2026-10-14 晚）：**教师与评分（judge）用 Sol/xhigh**；被测业务调用走 Luna，**不设调用次数上限**。
这改变了原计划“教师、judge 也迁 Luna/max”的方向：评测分两类执行器，教师/评分与被测端不同模型，也避免同模型自评。

- **G6a（泳道 A，离线）**：按调用点角色拆分 `ask_world.py` 与 `cli.py` 中的 `CodexStructuredExecutor` 调用。
  教师、judge/复核（reviewer、adjudicator）与 scene-gold 参考答案固定 Sol/xhigh（`gpt-6.1-sol`，沿用独立
  schema 守卫的 Codex 执行器）；被测业务生成以孤儿 seam `backend/evals/project_executor.py`
  （`ProjectStructuredExecutor`）经 Project facade 走 Luna/max。统一 `schemas.py` 模型常量，旧 spark/5.6/terra/
  DeepSeek 常量只作冻结元数据；`testing-guide.md:27-30` 的教师合同由 Sol/high 改为 Sol/xhigh，暂停守卫文案中的
  “recalibrate Luna/max”同步改写。更正 datasets README 与 Makefile 说明，在 `testing-guide.md` 与 datasets README
  新增“与历史分数不可直接比较”正文；离线测试用 autospec 替身。暂停守卫在 G6a 合入前继续拒绝新调用，由 G6b 开工时
  解除。DeepSeek 专用脚本（`rp_real_pairs.py`、`v4_live.py`、`creative_forecast_live.py`）标为冻结历史，不迁移（默认假设）。
- **G6b（泳道 C，已授权）**：以 Sol/xhigh 教师与评分重新校准，被测端经 owner 已验证的 Project 运行时走 Luna/max，
  不设调用次数上限；仍须保留完整账本（含失败与 unknown），开工前写明范围。
- **G6c（泳道 C）**：Ask World v3 holdout 已被 DeepSeek 运行消耗（`T-20261004-ask-world-quality/artifacts/`），
  必须新建数据集版本或新 family，走 FREEZE_CONFIG 与独占启动标记；封存九场、旧 holdout 证据按原模型保留，不改标。

### 3.8 G7 长篇质量验收

核实结论：旧诡秘 run 是 v2 包装，`backend/modules/project/llm_runtime.py:231-243` 要求快照的 `native_wrapper` 等于当前
`codex-text-v3`，否则拒绝恢复。先前获准的“保留缺口继续”（`T-20261012/RECOVERY-OPTIONS.md` 选择 B）建立在旧 run 上，
这条路已被 v3 门禁挡住。仓库里没有“合法版本/来源处理”的具体方案。

世界演化第四阶段的 P4-E（`docs/plans/2026-10-09-world-evolution-phase4.md:161-173`）是 G7 演化环节的子集；G7 还包含
导入、世界/结构、写作、dropped/omitted 分母。两者合并为一份账本，避免同一批真实调用记两次。

切片：

- **G7a（泳道 A，零费用）**：在专用 PG 上用合成长篇采集导入输入扫描基线（热点
  `evidence/compilation/services/import_activation.py:90-98` 每次 prepare 以 `limit=10_000` 读世界上下文与实体词项），
  记录 SQL 数、规模曲线与内存，供 C2 决策；不需要模型或私有稿件。同时定义 G7 指标与账本模板（分母含
  dropped/omitted，unknown 与作者处置单列），并在第四阶段计划中标注 P4-E 由 G7 承接。
- **G7b（泳道 C，已授权）**：**新任务、新 v3 run**，用户裁定由 G2 新接入的原生 Codex Luna 运行时
  （`codex-text-v3`，经 owner 已验证连接与 Project facade/snapshot）执行，**不设费用上限**。只复用单位定义
  （前 60 章、63 个来源、212868 字符、指标定义）；旧 v2 的 8/63 成功前缀、全部 unknown、账本和旧 worktree 只读保留，
  不拼接、不改 stamp、不重发、不沿用旧请求身份。不设上限不等于免记账：账本照常记全部请求、失败与 unknown。
  受版权原文的请求与输出留仓库外私有目录，仓库只提交去原文账本与审查结论。语义教师评分用 Sol/xhigh，依赖 G6b。
- **G7c（暂不做，用户 2026-10-14 晚裁定）**：代理作者试用（真实浏览器，`human_validated=false`）；委派与费用授权须重新确认，
  2026-10-09 对 P4-E 的授权不自动延续。

### 3.9 计划外收尾

- **H1 文档刷新成果集成（泳道 B）。** `T-20261014-codebase-docs-plan` 在 `codex/docs-refresh-luna`
  （基于 22bb49978）留有 34 个未提交文件，与 G2、#227 改过的正式文档大量重叠。#227 合入后从最新 main 建分支迁入，
  只重核受 #226/#227 影响的结论（local_agent、22_evolution、12_infrastructure、18_interaction、08_evidence、
  CONTEXT、开发/测试指南），共享文档由一个写入者合并。G3③c 的文档 commit 排在 H1 之后。
- **H2 Issue #209 结案（已完成）。** 2026-10-14 晚经用户同意，附 PR #211（`2fe442516`）证据关闭。
- **H3 Dependabot。** #224（openai 2.53 → 3.28 大版本）现在可评估：生产中 `infrastructure/llm/providers.py` 与
  `image_client.py` 直接用 openai SDK，须在隔离分支跑 provider/图片客户端测试并核对破坏性变更；#223（8 个小版本）
  与 #219（Actions）按常规 CI 审。PR 基于旧 main，评估前先 rebase。
- **H4 工作区收尾（已完成）。** 用户明确授权后，已核对并删除 `audit-first-batch`、`audit-g3-local-text`、
  `audit-g3-renderer`、`audit-g4-object-backup`、`audit-g8-atlas-invalidation` 五个 worktree 及本地分支。
  提交、差异与完整目录已备份到仓库外；`audit-followup-plan` 保留。G2 的 8 个旧运行时树由 T-20261012 持有，未清理。

## 4. 写入者与冲突

- 每项独立 worktree 与 `codex/<slug>` 分支，从开工时最新 origin/main 建立。
- `scripts/check_module_imports.py`、ADR-0031、`core/service_keys.py`、`app/bootstrap.py`：本批只由 G3③b+c 写；
  G8b 的新 DI 键（§3.5 默认路线）排在 G3③b+c 之后，在其合入后的基线上重算棘轮。
- 正式文档：H1 先写；G3③c、G4b、G8b 的文档改动在 H1 合入后基于新 main 写。`imports/README.md` 归 G3②；
  `testing-guide.md` 的评测段归 G6a；assistant README 先 G3③c 后 G5b。
- `backend/evals/` 归 G6a；G7a 的基线脚本放 `backend/evals/` 以外的新路径，或与 G6a 约定文件。
- `deploy/`、`init-minio.sh` 等 G4a 写入面若 G4b 需要改动，在 #227 合入后进行。

## 5. 用户裁定与默认假设

用户裁定（2026-10-14 晚）：

1. **S0**：同意提交并推送 #227 评审后补修（`d54498792`），随后授权合入，合并提交 `0e572c75f`；泳道 B 可开工。
2. **G7b**：新开 v3 run，由 G2 新接入的 Codex Luna 运行时执行，不设费用上限（§3.8）。
3. **G6b/G6c**：被测端 Luna 不设调用次数上限；教师与评分用 Sol/xhigh（§3.7）。
4. **G5b/G5c**：按推荐，“部分采用”限定为现有三类；编辑台开关透传到生产 compose，默认仍关，生产开启另需发布授权（§3.6）。
5. **G4b**：按推荐，key 仅经 owner 导出清单端点返回；mask 导出；部分失败重试后由作者确认生成标注缺项的包（§3.4）。
6. **H2/H4**：#209 已关闭；本次授权的五个 audit worktree 清理已完成，G2 的 8 个旧运行时树保留。
7. 执行者由用户自行安排，本计划不指派。

8. **G7c**：暂不做。

当前无待用户裁定项；H4 本次授权清理已完成。

本计划自行采用、证据相反时再改的默认假设：G3③b+c 同一 PR 删除 API 字段 `local_agent`（只有本仓库前端消费）；
G3③d 删除工具中继端点并在 ADR-0029 追加记录，`run_local_agent` 与表保留；DeepSeek 专用评测脚本冻结不迁移；
P4-E 并入 G7 单一账本；G7a 用合成长篇采集基线；G4b 超过单包上限时顺序分包；G8b 新增 world 批量 head 出口与
DI 键、以 revision_id 为主比较。

## 6. 验证门禁

沿用主计划 §10。补充：G3③b+c 必须实测重算依赖棘轮并跑 PG critical；G5a 新 E2E 进入 CI 的 assistant 档位；
G6a 合入前确认暂停守卫仍拒绝真实调用；真实模型切片开工前写明范围并保留完整账本（含失败与 unknown），
G6b、G7b 已获用户免除调用与费用上限，其他切片仍须写明上限。
