---
id: T-20260921-novelcraft-v4-implementation
title: NovelCraft V4 演化式小说整体引擎长期计划实施
status: superseded
created: 2026-09-21T00:00:00+08:00
updated: 2026-09-23T02:30:00+08:00
---

## 2026-09-23 目标变更与未完成代码快照

用户以现有 guimi 旗舰演示升级替换当前执行主线；V4 相关能力成为后继任务的实施依赖，完整旧计划未完成。最新明确禁止擅自合并、上线、公开发布，覆盖此前完成后合并清理的安排。原工作树与 WIP 保留，不再追求 DS Flash 完美输出。

后继：[T-20260923-guimi-flagship](../T-20260923-guimi-flagship/TASK.md)。隔离分支 codex/guimi-flagship，工作树 /Users/tywww/.codex/worktrees/guimi-flagship/ai-writing-assist；继承 243 个未提交文件的私有逐文件 hash 与源码备份在 /Users/tywww/.codex/artifacts/guimi-flagship-20260923/。

Phase3 新纯 Story 端口、Evolution structure runtime/queue、候选来源采用保护仍未默认启用、未接 UI；最后定向 33 passed。只读复审发现待修：正式 start_reading 重建计划丢 structure_version/structure；生成/复核 model 空字符串覆盖冻结配置；候选摘要复核只看前4000字却物化全文；能力注册缺 imports.structure_analysis。不得宣称结构迁移已完成。此前全CI 6257后端/2586前端/270部署在这些草稿前，不验证最新草稿。

费用：124请求、123 settled、请求124 CancelledError/usage_unknown。用户已授权按预留最高额 USD0.0443025 计入预算后继续新实测，不重试原请求；实际用量仍未知。保守累计USD0.6728103、原总上限USD5不重置，沿用原paid-calls.json。待加入可审计的最高额结算记录与测试后再调用。后续验收标记代理验收，非人工试用。

## 2026-09-23 分支整理与 PR 交付

用户指令「整理分支进度，逐个提pr」后执行：工作树 243 文件 WIP 固化为单快照提交
c4e9a7ba1（分支 codex/v4-phase3-wip），fixpack 两个 commit 拆为独立分支。三分支已推送
并建 PR：#165 fixpack 1 → main；#166 fixpack 2 → base #165；#167 draft Phase-3 WIP 快照
→ base #166（未完成勿合，转正前须修上文 4+1 项并跑 docs-check BASE_REF=origin/main）。
仅创建 PR，未合并、未部署；合并仍需用户授权。原「未提交、推送」表述自此作废，
其余快照记录（缺陷清单、费用、验证口径）仍有效。



# NovelCraft V4 长期计划实施

## 当前恢复点（2026-09-23，02:30）

- World v2 工程本轮完整CI通过：后端6257/15skip、coverage85.99%，前端2586，部署270（/tmp/v4-lineage-ci.log）；PG31、浏览器6、四模块2101。只核销本切片，不代表全计划完成。
- 真实模型两轮均未通过，旧输出/冻结/费用保留。world-identity-live-20260923.json 8请求：医生被误记别名，审查阻断；world-identity-live-02-20260923.json 6请求：职业别名已修，但无前例→首次建立关系的推断被阻断；第二Scene Phase2a请求超时。两份review.json已保存，不能写成真实在场验收通过。
- **付费暂停**：ledger第124次usage_unknown（CancelledError），最高预留USD0.0443025。124总请求，123settled；已知估算USD0.303284172，含未知预留的保守总额USD0.6728103。已通过异步问题询问用户是否按最高预留额计入原USD5总额继续新实测，或等实际账单；没有答案前不发任何新付费请求，不重试原冻结调用。独立工程继续。临时凭据runner finally删除，尚待独立核对数量0。
- Prompt已澄清职业≠称呼、空关系记录≠历史首次建立；World审查已说明实体aliases为空是分阶段占位而非与关系阶段alias矛盾。最后两项无新真实验收。
- 已开始Phase3接线准备：Story facade新增build_reading_structure_request/prepare_reading_structure_review/materialize_reading_structure_review，复用原parser/schema；原复核提取纯prepare/apply/materialize，补缺项/重复/外来candidate_id与跨文本分片借引文的失败关闭。17项定向通过（/tmp/v4-structure-ports.log）。**只有纯端口，尚未接生产pipeline、根预算、结构持久化/采用；不宣称Phase3完成。**
- 下一步：将Phase3接到已有reading owner/queue/root budget，必须分批冻结、来源复验、费用未知禁止重发、结果已存免费恢复；已有preparation.py的reading_plan.calls模式可复用。结构生成不得读取后文或当前可变World作为前史，review需原始逐Scene正文，领域持久化复用Story现有strict persister并保留作者资产和来源采用门禁。随后高质量融合、定向completion/review生命周期、细粒度依赖、地图/高级能力、E08和完整G0–G8代理验收全部仍在范围内。
- 全计划仍active；用户已授权计划全部完成后提交/推送/PR/合并/本任务分支清理，尚未执行这些Git交付动作，未部署。保护Guimi和无关worktree未动。

## 最新接续（2026-09-23，同场身份与关系历史）

- 新授权改为 world_version=2；旧1/0恢复或append保留。先World审查，再以冻结候选UUID绑定本场新身份并独立状态审查；候选/状态/物化/回执原子提交，回滚免费恢复。公共创建schema未开放预留ID，仅内部candidate路径可用。
- 规格复审复现“两个同名新人物→一个ID”，已修为不给身份/关系ref、保持待决定；完整handler反例通过，规格轴只读复核关闭。标准轴本次无新增确证阻断，两轴均不代表完整计划验收。
- 关系历史取本run或明确继承的真实已提交回执world_materialization，按端点筛选最近64个相关场景，保留范围；当前World后续描述不回流。changed/ended有真实previous_ref，但仍待作者采用、不自动改写旧行。关系变更采用生命周期仍须继续。
- 验证：World20 passed（/tmp/v4-lineage-identity-final.log）；相关四模块2101 passed（/tmp/v4-lineage-modules.log）；原生PG31 passed（/tmp/v4-lineage-native.log，含相同handler断言在PG跑首场回滚/免费恢复/历史继承与JSON查询）；随后仅更新报告identity_outcomes为最终绑定及新增时间事件Prompt说明/真实eval用例。
- world-identity-preflight-20260923.json 原生worker合成模型10调用通过：S0白石城、S1渡口、路线unknown。真实同fixture在运行 /tmp/v4-world-identity-live.log，session47210；输出paid-20260922/world-identity-live-20260923.json。共用paid-calls.json原110请求及USD5总上限，结束须收报告/语义审查/账本/凭据清理。
- 未提交/推送/PR/合并/清理/部署；保护库和无关WIP未动。下一步收真实验收并继续Phase3/融合、关系变更采用与完整V4缺口，不把本切片当全计划完成。

### 之前快照

## 最新执行快照（2026-09-23，World 候选接线与采用保护）

- 授权仍是完成全部V4计划后整理提交/PR/合并/清理本任务分支；**代理验收，非人工试用**。未部署，未提交/推送/PR/合并/清理，无关worktree/Guimi保护库未动。
- 新Reading `world_version=1`：观察/Phase1b后逐Scene执行世界对象、别名/关系、独立审查。纯builder+既有schema/领域候选持久化复用；每请求冻结实际request/schema指纹与结果、单次根预算，结果已存免费恢复，未知费用失败关闭。旧计划保留原版本。
- 新对象/别名/关系只candidate，同Scene回执/游标原子提交；strict传播DB失败，同名歧义与create_new撞旧身份待决定。既有描述不覆盖、仅name/type身份引文追加；新描述留冻结提案。跨attempt关系候选不合并旧描述并换新ref，而是留待决定，防来源洗白。
- 生产共享精确身份查询只收literal exact_name：World别名缺叙事截止证明，不能把未来身份/待采用alias带入前序状态。普通作者搜索未改。不能因此声称完整alias时态解析已实现。
- 候选meta/review_meta绑定evolution_ref；World采用、转别名、去重合并、单条/批量关系、关系吸收和普通采用包均回读真实已提交回执与最新正文/Scene。普通编辑保留ref，别名None/active/published/confirmed/canonical及字符串整体替换均检查来源。Project NOWAIT独占锁覆盖验源到提交，持领域锁时不等待升级，55P03转可重试冲突。
- 作者入口新增只读提案分页，显示候选/引文/复核问题和历史状态；不直接采用。Vue转义、异步换项目、390px截图通过（frontend-console/test-results/creative-forecast下world-proposals-mobile.png）。
- 验证：相关模块2095 passed（`/tmp/v4-world-regression-final.log`），后续World/语义契约35 passed；浏览器6 passed（`/tmp/v4-world-browser.log`），原生PG29 passed（`/tmp/v4-world-native-rerun.log`），前端指定7通过、lint/build通过。首次PG4失败是旧fake漏World调用/额度，已迁移保留原断言语义后29通过。第一次全CI未冻结本地.env开关，38项环境污染+3个旧去重fixture项目id不一致；fixture已修、明确flags重跑。最终完整CI通过（`/tmp/v4-world-ci-final.log`）：后端6252 passed/15 skipped，coverage86.02%；前端203文件/2586 passed，部署脚本270 passed。
- World真实探针 `world-live-20260923.json`（项目94d50b59-e4d6-487d-af70-49482014478c，run reading-2170ff09-c070-4b27-884d-a0ca3af7805e）2场9请求，原生worker连续完成，保存林舟character candidate、青竹other candidate、别名小舟、盟友关系candidate。第二场通称渡口/刻意回避等推论被独立审查阻断，未写World。主代理逐项审查见world-live-20260923-review.json；不称全部语义通过。
- 真实状态审查将无moved_from的entity_moved错误理解为必须证明移动，拒绝合法在场。已补兼容事件语义；sampler schema提供事件名枚举和timeline_changed/text_state/null主体指令。`world-presence-live-20260923.json`2次定向真实复核：原文在场supported，人工构造的无据白石城出发地unverifiable；原失败/冻结未改，未声称完整重新生成E2E。
- ledger现110请求（99+World9+定向2），全部settled；估算USD0.272941398、保守上界USD0.5645859，总USD5不重置。临时凭据finally移除，独立只读核对数量0。零费用World preflight6请求通过，preflight/所有失败/真实报告保留。
- 仍缺：World关系的真实历史候选上下文/变化、第一场新身份对应状态在同批物化、结构Phase3、高质量融合、定向completion/review恢复、细粒度依赖、地图/高级能力、E08等预算对比canary回滚与G0–G8完整代理验收。下一步先收取CI；最后crossattempt关系P1已由standards reviewer只读确认关闭，然后继续这些真实缺口，不提前Git交付。

### 上一快照：Phase1b 门禁完成


- 用户授权完整开发、代理验收、最后整理提交/PR/合并/清理本任务分支；没有部署授权。代理验收明确非人工试用，不替代真实长期人类效果证据。
- Phase1b 生产接线、边界确认 CAS、并发收尾与锁序修复已完成。最终 `make test-ci TEST_WORKERS=4`（`/tmp/v4-phase1b-final-ci-rerun.log`）通过：后端6237 passed/15 skipped、coverage86.00%，部署270，前端203文件/2585项。首次lint失败修正后重跑，原失败日志保留。
- 原生PG `/tmp/v4-phase1b-native-final.log` 28 passed；浏览器真实API/worker+合成provider `/tmp/v4-boundary-cas-browser.log` 5 passed；frontend lint/build通过。docs-check经逐项不变理由通过（`/tmp/v4-phase1b-docs-final.log`），diff-check通过。
- 真实两场7请求成功报告 `artifacts/paid-20260922/phase1b-audit-repair-live-20260923.json`，候选置信0.60/0.78，只保存提案，原约束null；time_advanced经独立复核，其他未解析身份仍待决定。旧失败/准备结果保持不变。
- 随后的定向审查 `phase1b-counterexample-live-final-20260923.json` 两次请求：原“任何间接方式也不得验证”重大冲突被阻断，收窄为原文未亲眼确认范围的对照通过。对照为代理编辑的审查控制样本，不是重新生成或完整E2E；其他叙事推论仍留候选。共同ledger现99 settled请求，估算USD0.256509012、上界USD0.5287482；USD5总授权不重置。临时凭据只读核对数量0。
- World迁移已追踪：旧policy世界对象/关系/别名都待采用，不能自动正史。Phase2a/2b纯builder与Imports facade已抽出，尚未接生产World链。下一步复用来源校验及领域persistence，加入严格失败传播、精确身份歧义保护、单场冻结/根预算/原子提交，不能套旧并行orchestrator。
- 随后仍须结构/高质量融合、细粒度依赖、地图、E08与完整G0–G8，不能以当前子集完成代替全计划。原分支/HEAD未变，未提交/推送/PR/合并/清理/部署，保护Guimi及无关worktree未动。

## 当前恢复快照（2026-09-23，Phase1b 已接线）

- 用户明确回复原 G7/独立读者门禁问题：**“由你执行代理验收，明确标记不是人工试用”**。本次交付采用代理验收替代原人工参与项，保留工程、真实模型、等预算和来源门禁；不得宣称真实人工试用或以自评分作审美 ground truth。全部计划完成后再提交、推送、PR、合并和清理本任务分支；没有部署授权。
- 新 Reading plan version1 已逐 Scene 运行 Phase1b 生成与独立 Evidence group audit，二者各占一次根预算，调用前冻结/调用后保存；使用本场完整精确正文和真实已提交前序回执，旧计划保持 version0。生成、复核与已通过状态事件共用 `_run_scene_call`，费用未知不重发，结果已存免费恢复。
- 自动草稿（source=evolution、auto_ingested、未 user_edited）语义字段与回执/游标同事务采用；人工/旧流程/已确认 Scene 不覆盖。blocked 只存完整候选和复核问题；场景详情可查看并显式“填入表单后修改”，不会自动保存。Scene 卡 guard 漂移拒绝提交；自动已充实草稿在明确重算时重做语义整理。
- Phase1b 已验证：模块 654 passed/12 skipped、前端指定 43 passed、此前原生 PG 26 passed；其后又修复两处并发问题，旧数字不代表最后改动验证。浏览器首轮1失败/3通过：旧fixture追加额度2已不足两场各3请求，已改6，重算改3，待复跑；失败日志保留 `/tmp/v4-phase1b-browser.log`。
- 审查两处 P1：state_review 收尾释放run后用旧payload可能覆盖后续journal；已改重新加锁+reload。enrichment run→Scene/共享fusion建议与作者写入反序；最终采用**所有 pipeline 提交在 claim事务结束后先 Project独占，再 advisory→run→领域写入**，不在 provider I/O 持锁。单行 NOWAIT 未采用，因为不能覆盖共享融合建议锁环。新 PG 双会话测试在跑 `/tmp/v4-phase1b-race-pg.log`；指定16项单测通过 `/tmp/v4-phase1b-race-unit.log`。
- 下一步：验完并发/浏览器与Phase1b文档，随后继续世界/关系/采用、结构与高质量融合、细粒度依赖、地图边界和 E08。完整任务仍 active；无新付费调用、无提交/远端/合并/部署，保护数据与其他 worktree 未动。

## 当前恢复快照（2026-09-22 23:53）

- 本轮修复规格 P1：新增 `evolution/state_review.py` 独立状态复核，生产采样器单独回读完整 Scene；通过结构门的全部事件逐项裁决，漏项/重复/伪引文/矛盾/未知均不产生正式状态。输入绑定 source、parent、epoch、候选与 attempt；`commit.apply_frozen` 再次校验，不信任生成者伪造复核字段。正式事件 meta 保存复核身份。
- 每次复核单独预留根预算，sampling/result/failed 持久化，结果已存后领域失败可无客户端免费恢复；预算在采样后耗尽时保留 compiled 原结果并进入 needs_budget，继续授权只补复核。旧 Reading plan/meta 或冻结没有复核版本时不追加调用，未复核提案保留待决定，历史已提交成果不改写。完整候选保留，pending_decisions 超限只压缩摘要并记录余项数。
- 并发 claim 修复两处审查发现的锁环：首次采样沿 Project→chapter→run，不能提前锁 run；无 pending 恢复不锁 run；verified 恢复先 commit 再进入 advisory→run 提交协议。同 run 冻结在 claim 锁下重读，防重复 provider 请求；原生 PG 用实际双会话/advisory holder/改稿版本锁覆盖三个竞争路径。
- 验证：完整后端 **6229 passed / 15 skipped / 13 warnings**，覆盖 **85.93%**（`/tmp/v4-state-review-backend-final.log`）；该全量在最后锁序补丁前启动，最终针对 Evolution/Imports 复跑 218 passed，见下方证据。前端 **203 files / 2583 passed**（`/tmp/v4-state-review-frontend.log`）；原生 PG 最终 **26 passed**（`/tmp/v4-state-review-pg-locks-final.log`）。新调用仅 fixture，0 次新增付费。任务专库不变，保护库未动。
- `make test-ci` 首轮 deployment 270/lint/secret/dependency 检查通过，后端先暴露新 capability 清单和地图 fixture 未迁移复核两项失败；已修清单并给有效 fixture 显式独立裁决/预算，原断言保留，随后完整后端绿色。失败日志 `/tmp/v4-state-review-ci.log` 保留。原生 PG 失效测试同样更新 fixture，失败 `/tmp/v4-state-review-pg.log`、最终绿色证据均保留。不能声称首轮 test-ci 全通过。
- code-review 规格轴确认原 P1 工程关闭，标准轴最终确认两处锁环已消除；两者仅只读复审，不代表模型效果验收。仍待原问题中用户明确 G7 长期作者试用/独立读者盲评的合并门禁选择；继续工程，不擅自代签。
- 下一步已开始 E07 Phase1b 接线：`imports/workflow_llm_adapters.py` 已提取原 Phase1b Prompt 构造为 `build_scene_enrichment_request()`，旧 adapter 复用相同请求，不改变治理或旧调用策略。纯来源/请求/结果验证端口已增加到 Imports facade，27 项旧适配器/新端口测试通过（`/tmp/v4-phase1b-port-final.log`）；当前尚未接新运行。应复用 `_validate_enrichment_evidence` / `_final_candidate` / `_build_structure_meta`，以当前 Scene 精确来源 + 实际前序 receipt 构造请求，禁止搬入旧 batch gather 的提前解释。新结果须在 scene 窄提交中原子更新，保留 user_edited/手工字段，Scene 卡漂移需冻结指纹重验；导演判断不回流角色事实。
- 最终定向检查：`/tmp/v4-state-review-and-phase1b.log` 218 passed（Evolution + 两个 Imports 测试文件）；`/tmp/v4-state-review-browser.log` 4 passed（原专库8058/8158）。状态复核机器记录与文件指纹：[验收记录](artifacts/v4-state-review-verification-20260922.json)。此前误写不存在的 `test_workflow_llm_adapters.py`，pytest 未执行即退出，记录 `/tmp/v4-state-review-targeted.log`，正确重跑已通过。
- 全计划仍 active，世界/关系/采用、结构、高质量融合、细粒度依赖、地图边界和 E08 等未完成；完整验收后才提交/推送/PR/合并/清理，未执行任何交付 Git 写入或部署。

- 2026-09-23 跨日接续：`pipeline._run_scene_call` 已从复核中提取同一冻结请求机制，保留 state_review journal 形状；独立复核现在走它，Evolution **192 passed**（`/tmp/v4-shared-scene-call.log`）。后续 Phase1b/其复核应复用它，不能另建预算或恢复协议。当前只有 state_review 实际调用，Phase1b 尚未进入生产流水线。
- Phase1b 来源端口 `imports.facade.prepare_scene_enrichment/build_scene_enrichment_request/materialize_scene_enrichment` 已通过 27 项测试；完整本场正文 + 实际 committed parent，排除旧卡导演判断，guard 指纹包含原 Scene 卡。首次新端口测试发现 request model/extra 不接受 None，已改空 model/空 dict，复用 Project client 的冻结 profile。失败与最终日志保留。
- Evidence 新增 `facade.build_group_audit_request/materialize_group_audit`，复用既有知识审查 Prompt/schema/宿主 findings 裁决，提供纯请求与冻结结果编译；不截断 24000 字后的反证，全部必查维度必须有源且 checked，缺项/重复失败关闭；输出完整 audit_receipt 绑定原 group/output。`/tmp/v4-group-audit-port.log` 6 passed（随后仅追加 audit_receipt 返回字段，收尾应重验）。旧 govern_group_output 原调用策略未改。这两个新端口还未由业务调用，下一步 Phase1b 独立复核将使用。
- **具体下一步**：通过当前任务已读取的 `get_scene_contract` + dataclasses.asdict 获取完整 Scene（已含字段/structure_meta，不新增宽读接口）；冻结 scene_card guard，与 Phase1b journal 同源。新 run 明确 version，旧运行不追加新付费步骤。Scene 语义生成和独立 group audit 各一根预算调用，域采用在原 apply_frozen 同事务中，重验 Scene guard、保留 author/user_edited/已确认字段及历史。可复用 SceneService/SceneRepository 更新与 Imports `_build_structure_meta`，但不要把未审通过的语义直接入正式字段；需要一起设计已有场景工作台的待决定展示/采用，不能把未知字段强填或把只有纯端口叫功能完成。

## 全计划交付接续（2026-09-22）

- 用户再次明确要求“计划全部完成，然后整理分支，pr，合并，清理分支”：完整验收后提交、推送、PR 与合并已授权，清理仅限本任务已合入分支；生产部署未授权。不得提前把部分切片当全计划完成。
- 已 fetch 并固定审查基线 `origin/main=ed9269d143db2300843197d107f14f7a5e85671b`；当前 HEAD `0efb1359d70af3bec92ad47d0493238d62bc7861`，继承全部 WIP。实现前 `make docs-check` 通过（`/tmp/v4-complete-docs-start.log`）。
- code-review 双轴只读预审：标准轴未发现新增硬阻断，README 引用对齐例外需同步；规格轴复现否定原文仍可产生相反位置变化，现有类型/引用/模态门不证明语义蕴含。优先补独立复核，绑定原文、前序回执、epoch 和候选，单独根预算预留与结果冻结后才允许正式状态写入。
- E07/E08 仍缺逐 Scene Phase1b、世界/关系/采用及结构完整接入，不能直接套用旧批量 Phase1b 的并行语义编排。地图边界、其余追踪矩阵和真实等预算/长书验收后续逐项完成。
- 原 G7 长期作者试用和独立读者盲评需要外部参与；已发聚焦问题等待用户选择保留原门禁或明确调整验收边界，期间继续全部独立工程工作。没有因等待此回答暂停实现，也没有默认降低门禁。

## 最新恢复快照（2026-09-22 23:20）

- 当前用户要求由本 Agent 继续剩余开发与验收；沿用原主任务和所有继承 WIP，分支/HEAD 未变，未提交、推送、合并或部署。完整 V4 仍 active，尚未达到全部计划完成后的提交条件。
- E07 新增对象/已有观察范围：选择本项目/run 已提交观察里的已解析身份或 observation_id，支持名称/观察文字检索分页；预览不调模型。目标用于定位最早相关 Scene，与正文首变位置取更早者，按顺序依赖重算后缀。保留并重验原前缀真实 run/attempt，不复制回执，不删除费用或历史，不将人物陈述/信念当事实。选择、扩大范围及真实起点进入确认指纹/分段授权；兼容旧授权缺少新增可选字段的原 operation 重放。
- 写作菜单统一进入现有“理解与整理正文”弹窗，根据当前 owner 显示旧整理或新 ReadingFlow；状态未读取/失败时关闭旧启动，错误可见并可重试，换项目重新查明归属。旧整理保留完整/分阶段/质量参数功能。服务端历史 can_continue 控制写作与世界页共用旧继续/重算按钮，查漏详情保持只读依据。切换确认明确世界/结构完整整理尚未迁入。
- 验证：本地 `make test-ci TEST_WORKERS=4` 通过，后端 **6223 passed / 15 skipped / 13 warnings**，覆盖率 **85.96%**（门槛 85%）；部署脚本 **270 passed**；该轮前端 2582 passed。最后状态读取/切项目修复后完整前端 **203 files / 2583 passed**，lint/build 通过。warnings 包含既有 async 标记与 SQLite ResourceWarning，未隐藏；依赖审计无已知漏洞，langchain-community archived 提示保留。
- 原生 PG 23 passed（最终复跑 `/tmp/v4-scope-native-final.log`）；浏览器真实 API/worker + 合成 provider **4 passed**，另旧整理入口/恢复/回收站 **9 passed**。390px 确认区已目视检查，正文与历史保留。`deep-import-worker.spec.js` 仅随新选择器迁移，未冒充完整旧流程真实 worker 新验收。
- 本轮捕获并修正的失败：新合成测试误用 character_belief，按现有 schema 改为 belief；收尾回归发现折叠面板换项目没有重新读取归属，已修 watcher，失败日志 `/tmp/v4-scope-frontend-final.log` 保留，最终全前端通过。没有削弱断言或来源校验。
- 文档影响门禁经逐项核对四份未变通用文档后通过（`/tmp/v4-scope-docs-final.log`），diff-check 通过；主要接口/行为已同步 Evolution、Imports、前端及业务场景文档。机器证据和代码 SHA-256 在 [本次验收记录](artifacts/v4-scope-entry-verification-20260922.json)。
- 本轮 **0 次新增付费请求**，共同 ledger 未改，先前 85 次模型证据与无效冻结保持原样。测试只使用明确任务专库，未迁移/清理保护库。工程通过不代表长书、真实模型语义或作者验收。
- **未完成/下一步**：审计新增“旧入口与新入口能力对照”。先从 Imports `workflow_scene_phase.py` / Phase1b 与高质量融合提取可调用步骤，接入 Evolution 已有队列、根预算与冻结恢复；接着迁入 Phase2 对象/关系/去重/采用包和 Phase3 结构与独立复核，保留旧 API 的 force/high_quality/采用/查漏/恢复契约。不能把当前 Scene-only 入口直接映射为旧 deep_import，也不能先删旧编排。细粒度依赖图、同源全能力对照/canary 观察、E08 和 U/V/R/C/A 余项、完整 G0–G8 仍未完成。

## 交付顺序补充（2026-09-22，用户最新指令）

- **全部计划完成后**才逐批提交；之后整理分支、创建并处理 PR，最后在核对合并状态与工作树后清理分支。当前 192 个工作树变动仍是未提交 WIP，V4 任务 active，未进入提交阶段。清理不得丢弃其他任务 WIP、独立 worktree、历史或未合入提交；逐支审计祖先关系与验证证据。
- 此指令是未来交付顺序授权，不把工程测试绿色或短篇合成模型结果改称完整 G0–G8 验收，也不授权提前推送、部署或清理。
- 提交前须逐文件分批暂存并复核：任务 `artifacts/paid-20260922/` 当前未被忽略，含真实请求/模型响应/共同费用账本，不能用 `git add .` 将整目录误放进 PR。现有主仓外还有 Guimi 测试 detached checkout、分支整理 detached checkout、世界模型审查 detached checkout、immutable-history checkout 及两个 archive 分支 worktree；最终清理只处理已核实属于本任务且已合入的分支，不碰这些既有工作区。

## 真实模型定向修复续验（2026-09-22 22:42）

- 只读核对 live 专库旧项目 `133190ab-82df-489f-8ae1-2da35f196f91`：原 run 游标 0、预算余 3，第二 Scene 无效 `sampled` 冻结仍在，旧任务终态 failed。原共同账本 84 次均 settled。`repair-preflight-01.json` 因临时探针在 rollback 后访问 ORM 对象失败，零付费；修正后的 `repair-preflight-02.json` 通过：继承 Scene 0 的原回执，仅重读 Scene 1，模型 `deepseek-flash`，调用上限 1。预览本身不会重采样。
- 复核 DeepSeek 官方 Flash 峰价与现有 Meter 一致后，经同一个 `paid-calls.json` 发起一次新授权请求。**第 85 次 settled**，新增估算 USD 0.0013395、无缓存峰价上界 USD 0.002679；累计估算 **USD 0.235453932**、上界 **USD 0.4840038**，仍低于 USD 5（均按用量估算，非账单）。新 Worker done，新 run 两 Scene completed，旧 run drained，旧无效冻结 SHA-256 `e51bf8b816a05e51aff1cd9ec5ef23898de9fda6e5d1d18faac5bccecba407bf` 未变；新完整链的原身份为旧 run/attempt Scene 0 + 新 run/attempt Scene 1。真实 `read_committed_understanding()` 返回两项且无遗漏，测试账户凭据清理为 0。
- 新输出第二场引用精确使用“也没有提起封锁”，不再把“他”补进 quote；predicate 概括可带主语。行程、封锁来源/真伪、空间关系保留未知；`entity_moved` 提案因人物主体未解析被宿主阻断，不能当作已落地地图/Story 状态验收。仍是短合成段落的单次模型结果，不证明长篇可靠性。`repair-live-01.json` 的 `stage=failed` 是**请求与 Worker 均成功之后**，临时验收脚本再次在 rollback 后读取已脱离 session 的对象造成的报告错误；该文件原样保留。只读独立复核在 `repair-live-01-postcheck.json`，语义核对在 `repair-live-01-review.json`；没有因脚本错误重发付费请求。
- 旧失败任务在新授权前仍显示 `can_resume=True`，来自旧持久 flags；新代码已对未来 `invalid_observation_source` 失败标不可直接恢复。新 run 建立后旧 run drained，旧任务不再可恢复。历史旗标没有追改。完整 G0–G8、对象/命题范围、旧入口等价替代、E08、作者验收仍未完成；不进入提交阶段。下一步继续 E07 范围与旧入口语义梳理，然后依追踪矩阵补工程/模型/用户门禁。
- 后续补充“定向修复后追加第三场”的继承链断言；现有定向测试 1 passed。最后一次共享查询改动后完整离线后端 **6221 passed / 15 skipped / 1 既有 warning**（`/tmp/v4-repair-backend-full.log`），前端 **203 files / 2578 passed**（`/tmp/v4-repair-frontend-full.log`），原生 PG **23 passed**（`/tmp/v4-repair-native-pg.log`）；backend Ruff 全量、frontend lint/build 均通过。文档影响检查和 diff-check 已通过。此组为工程回归，不替代三类正式验收。
- E07 入口继续调查：`/imports/deep` 旧请求及三个分阶段入口包含世界对象、结构资产、`high_quality`、重复确认、采用/查漏与旧任务恢复语义；当前 Evolution 入口只承接 Scene 理解。写作页 `WritingEditor.vue` 仍展示“完整整理世界与结构”等旧按钮，切换 Evolution 后会提交到受 owner 保护的旧路由而被拒。下一可执行工程步：围绕 `modules/imports/api.py`、`orchestrator.py`、`WritingEditor.vue` 与 `useWritingWorkspace.js` 建同源旧/新入口能力对照与实际 canary，按可证明等价的语义逐项迁入单 owner；在世界/结构/采用、费用确认和恢复对齐前不重定向旧 API 或删旧编排。

## 本次接续快照（2026-09-22 22:33）

- 已核对交接所列分支/HEAD 与大量未提交 WIP；未 reset、提交、推送、合并、部署或触碰保护库。共同付费 ledger `artifacts/paid-20260922/paid-calls.json` 原样保留，仍为 84 次、估算 USD 0.234114432，当前未新增真实请求。
- `store.py` 原继承读取草稿的指定回归 35 passed。现已接通 `workflow.py` 的 `revise`（首个变化起）与 Scene 范围 `scoped_recompute`（作者指定起点，必要时保守向前扩大）：预览/指纹/确认后仅继承逐条重验的成功原回执，设置真实游标与 head，旧 run/冻结失败/费用保留，旧任务未终态拒绝新 run。`reading.py` 按各原回执的 run 身份重验跨 run 链；前序观察进入新 Scene。`tasks.py` 将非法逐字引用的 sampled 失败标为不可直接恢复，需新授权请求。
- 工程验证：完整离线后端 **6220 passed / 15 skipped**、前端 **203 files / 2578 passed**、原生 PG **23 passed**、浏览器实际 API/worker + 合成 provider **4 passed**；frontend lint/build、Prompt contracts 24 项通过。此后又增加“继承 Scene 必须是当前最新成功回执”共用查询和反例，相关模块 **269 passed / 1 deselected**、原生 PG 定向 **2 passed**；完整全量数字早于这最后的小改动。前端确认文案/390px 排版调整后，ReadingFlow **4 passed**、frontend lint 和浏览器定向 **1 passed**，截图 `frontend-console/test-results/creative-forecast/.../reading-recompute-mobile.png` 已目视检查。`make docs-check BASE_REF=origin/main` 最终复核四份通用文档后用 `--no-change-reason` 显式通过；`git diff --check` 与目标 Ruff 均通过。所有绿色均不代表真实模型语义质量或作者验收。
- Prompt 门禁发现 Evolution 两处实际 LLM 调用未登记，已登记 `evolution.scene_observe`；Scene 边界准备复用 `imports.scene_slicing` 的静态能力归属，未虚称额外 Knowledge director/audit 流程。对应能力注册表测试 11 passed。
- 当前限制：仅 Scene 后缀级范围；对象/命题范围、细粒度依赖闭包、旧 deep-import 入口适配及 E08 尚未完成。旧 `/imports/deep` 承诺世界对象、结构资产、覆盖和采用语义，请求本身也没有新入口的调用上限与预览指纹；直接把当前 `legacy_adapter` 字典映射接到 Scene-only 路径会破坏契约。下一步先补 E07 等价能力和同源 canary，再接旧路由；随后逐项推进 G0–G8 未核销项。真实模型修复若要验证，先零费用 preflight 并复用共同费用账本。旧 `preparation-live-01.json` 失败保持原样。

以下 22:02 交接为当时快照；其“未贯通/未验证”状态已由上面的本次进展更新，其他边界与历史证据继续有效。

## 新会话交接（2026-09-22 22:02，用户要求整理进度后交接）

**本会话停止新增实现；原目标仍 active，完整计划未完成。新会话先恢复本记录和审计，不重做已有工作。**

1. 核对分支 `codex/v4-audit-fixpack-1` / HEAD `0efb1359d70af3bec92ad47d0493238d62bc7861` 与现有 WIP。当前没有提交、推送、合并或部署；不要 reset、清理未跟踪文件或修改保护库。
2. **当前代码有一段刚开始、尚未验证的实现**：`backend/modules/evolution/store.py` 新增 `load_committed_pairs()`，按本 run 或 `reading_plan_json.inherited_receipts` 中的原 run/attempt 对读取成功回执 + applied 冻结记录；`load_head_receipt()` 和 `load_prior_observations()` 已改用它，`load_head_observations()` 按 head.run_id 回读。这是继续/修订运行继承原前缀的基础，不是已接通功能。尚无 workflow 写入 inherited_receipts，`reading.py` 仍假定全链同 run；不要据此宣称 revise/scoped_recompute 完成。此段仅 Ruff format/check 与 diff-check 通过，**没有运行行为回归**。
3. `llm_sampler.py` 的新引用说明（predicate 可概括，quote 不得补主语或改代词/连词）已格式化、lint 通过，但尚未真实重测；旧第二场失败冻结结果保持原样。最后一次完整/模块/PG/browser 绿色均在上述 store 草稿之前。
4. 可执行第一步：阅读 `workflow.py`、`store.py`、`reading.py`、`orchestrator.py`、`pipeline.py` 与 `tests/test_workflow.py`；在根目录运行 `ASSISTANT_ENABLED=false RERANKER_ENABLED=false RAG_QUERY_PLANNER_ENABLED=false make test ARGS='-q modules/evolution/tests/test_orchestrator_store.py modules/evolution/tests/test_understanding_reading.py modules/evolution/tests/test_workflow.py modules/evolution/tests/test_preparation.py modules/evolution/tests/test_llm_sampler.py'`。先确认这段草稿对既有回执语义的影响，再把授权的新运行与真实前缀读取贯通。
5. 交接检查：store/sampler Ruff format/check 通过，git diff-check 通过；基于 origin/main 的文档影响门禁经逐项不变说明通过（`/tmp/v4-handoff-docs-ack.log`），原提示保留于 `/tmp/v4-handoff-docs.log`。Prompt 契约检查和 store 行为回归尚未执行。
6. 按下节“下一步设计与真实失败”完成定向修复，再推进 E07 剩余工作和完整 G0–G8。不要新建付费 ledger；84 次旧请求与失败都要累计保留。当前无活跃付费进程；两名只读 reviewer 均已结束，无待集成子代理代码。

### 下一步设计与真实失败（设计还未落地，不能当完成事实）

- `preparation-live-01.json` 的专用项目为 `133190ab-82df-489f-8ae1-2da35f196f91`，run 为 `reading-7389fede-e4c2-442d-95c8-ae76d983b7a8`；一章两场，prefix=0，总额度6/剩余3。请求82切分、83第一场提交、84第二场无效逐字引用；原报告 failed，人工审查在同目录 `preparation-live-01-review.json`。
- 第二场原文是“也没有提起封锁”，模型 quote 写成“他没有提起封锁”；校验拒绝正确。现有 sampled 恢复路径会重复尝试同一无效结果；状态仍可能 can_resume=True。需区分免费提交恢复与**作者明确确认的新修复请求**，不能放宽来源校验、修改旧 frozen payload 或盲目重采样。
- 拟复用原阅读预览/确认、Project 独占锁、v2 queue/root budget：新 revise/scoped_recompute run 只引用来源/Scene/完整链均重验的既有原回执前缀，保留其真实 run/attempt 身份，不复制合成回执。新场读取原前缀的观察、模态与覆盖度，原运行停止后不能复活；旧 provider 响应仍留历史。
- `store.load_head_receipt()` 原先按同 run 最大 Scene 取头；`save_receipt()` 要求 run.committed_scene_index 等于 frozen.previous_prefix，head_attempt_id 实际保存 receipt record.id；创建新继承运行必须设置真实已验证游标，不能仅放一串引用。
- `reading.py` 当前完整前缀消费验证：同 run、从0连续、真实 previous attempt/observations、当前 Scene、selected source roots、同 Scene 最新成功结果。继承需要统一读取原 receipt/frozen 对，输入 manifest 必须匹配各原始 receipt.run_key；不能削弱链/来源/最新结果校验。旧 source_stale run 的未受影响前缀若要复用，须逐步验证来源与失效起点，不能全量解封。
- revise 应比较新旧 source binding/Scene 身份，明确最早变化和依赖闭包；scoped_recompute 接作者范围。当前顺序依赖没有完整细粒度图，可保守扩大为后续范围，但预览必须说明并得到授权；之前未受影响的前缀保留。对象/命题范围还未实现，不能用范围子集代称完整能力。
- `tasks.py` 恢复标记目前仅按 sampled/compiled 判断；要让非法引用走需要重新核对状态且不能无限免费 resume。sampling/failed 费用未知仍不得重发。新请求先确认旧队列已终结，防旧任务与新运行并发；保持 Project-first 锁序、单写者和重复授权幂等。
- 旧 `invalidate_sources()` 只封锁 active run；历史/继承前缀和新重算派生产物的新鲜度也需要审查。保留人工确认、原始冻结输出、费用与历史；不要为凑完成度扩大跨模块写入。
- 活体失败项目结束时测试凭据已移除；若真实验证定向修复，沿 `v4_live.py` 的专库、同 owner、加密凭据仅内存临时恢复、结束移除与共同 Meter 方案，不访问保护库的小说内容。先零费用 preflight，再真实调用；保留失败结果和新旧 lineage/费用证据。

## 恢复快照

- 原目标仍为附件 V4 计划 review + 做完；完整 G0–G8 未验收，不能关闭任务。
- 工作区 `/Users/tywww/Desktop/项目/ai-writing-assist`，分支 `codex/v4-audit-fixpack-1`，HEAD `0efb1359d70af3bec92ad47d0493238d62bc7861`。保留大量继承及本轮未提交 WIP；没有提交、推送、合并或部署授权。
- 默认模型已按用户最新明确要求，经账户 SettingsService 激活 `deepseek-flash`（DeepSeek V4.1 Flash），从旧 `deepseek-v4-flash` 对齐；原 timeout/max_tokens/temperature/top_p/extra/creative_mode 保留，runtime 回读确认。此项修改了真实库账户默认设置，没有修改 Guimi 小说内容/项目/凭据或重启、迁移保护库。见 `artifacts/paid-20260922/default-model-alignment.json`。
- 付费授权：默认已验证连接，累计总额含重试不超过 USD 5。84 次真实请求全部已结算入共同 ledger，估算 USD 0.234114432，峰价无缓存保守上界 USD 0.4813248（按用量和公布价格计算，非账单）。当前无付费进程运行。**任何重跑必须复用 `artifacts/paid-20260922/paid-calls.json`，不得换 ledger 重置上限。**
- `live-06.json`（scenario_version=2）有界真实纵切通过：连续两 Scene → 独立查证 case → 不同创作目标的新 case → Forecast，实际 Prompt 含相应 Evo/C 引用；Map/Story/Evidence 同源。真实 Writing 改稿后旧 case/C/map/feed 共同失效。输出人工语义核对见 `live-06-review.json`；自由文本引用偏移有轻微标点误差，原审计与失败保留。不代表长书、等预算对比、真实作者或上线验收。
- 最近验证：全后端 **6211 passed / 15 skipped**；全前端 **203 files / 2577 passed**；原生 PG **16 passed**；浏览器实际 API/worker + 合成 provider **4 passed**，390px 截图检查通过；frontend lint/build、backend lint 通过。见 `/tmp/v4-reading-{backend-full,frontend-full,native-all,browser3}.log`。
- E07 受控入口已接 bootstrap/append：`workflow.py` 固定真实完整 Scene/来源/模型/分段授权，API 与 ProjectSettings 的 ReadingFlow 提供预览、确认、连续队列、进度、恢复与暂停。不是完整主链替代；Scene 自动准备本轮已接并正在验收；仍缺 revise/scoped_recompute、旧 API 适配与 E08。
- 真实 worker 恢复复审已核销：领域异常与服务器 shutdown，active run + 有效 lease + sampled/compiled 可同 attempt 免费恢复；sampling/failed 费用未知、作者停止/owner 撤销均拒绝。四种 native PG 反例从独立连接读旗标/预算。前端 409 解锁、网络未知复用操作，结束章超现存正文的续读游标取实际来源。
- `reading-live-01.json` 已通过（calls 79–81）：真实默认 V4.1 Flash 三次 transport，第一场 provider 返回后注入提交异常，真实 Worker 人工恢复同 attempt；两 Scene 连续完成再 append 第三场，预算共 3 次，无重复请求。审查在 `reading-live-01-review.json`。未预建世界对象，全部状态提议因主体未解析留待决定；不能将该用例称为新对象创建/地图物化验收。
- 本轮补充（尚待最终复审）：自动 Scene 准备已接同一 run/v2 queue/root budget，支持全文无 Scene 或已有前缀后缺场景的末尾；不支持跨中间缺口直接跳读。结果免费重放、预算耗尽显式 continue、原授权幂等、历次 preparation 保留、未决边界人工确认恢复。复用了 Imports Phase0/1a/Committer，未接旧 owner/旧隐式 LLM adapter。
- 新复审问题已修：按精确来源排序模型逆序输出、阻止开放右边界/未解左承接/低置信自动读取、旧任务终态前拒绝追加预算、模型结果保存先锁 Project 再锁 run。左侧章尾仅作固定版本边界参考；正文/边界来源修改参加失效。公共 Story boundary guard 同时阻止旧 fallback 进入读取/消费者；人工确认与可选语义问题保留区分。
- 最新新增验证：1279 passed/12 skipped（Evolution/Imports/Story）；native PG 21 passed 含真实 Worker 的准备中断/未知费用/撤权和结果返回与改稿锁序交错；浏览器 4 passed 含正文开始、预算追加、390px；最新入口/采样器 24 passed。日志 `/tmp/v4-preparation-{regression,native-final,browser,unit-final}.log`。UI 三项/lint/build 通过。`preparation-preflight-02.json` 通过，02 前的 01 为 eval 的 tests 模块路径错误，不是模型失败，零付费。
- `preparation-live-01.json` 已结束（calls 82–84），原报告保留 failed；`preparation-live-01-review.json` 保存实际输出/冻结快照和人工语义核对。边界切分两场、故障后的免费重放、第一 Scene 提交均通过；第二 Scene 将原文“也没有提起封锁”改成“他没有提起封锁”作为 quote，严格来源校验正确阻止提交。run prefix=0、总额度6、剩余3，所有 provider 费用已知。没有自动重采样或放宽校验。新采样 schema/prompt 已澄清 predicate 可概括、quote 不得补主语/改代词/连词；旧失败不改写。仍需显式定向修复生命周期，不能把同一无效冻结结果的无限免费 resume 称为有效修复。
- 下一步：先验证上方交接所列 store 未完成草稿，再贯通 E07 revise/scoped_recompute（含无效冻结观察的显式定向修复，而非原样无限 resume）；收尾文档/Prompt 门禁。最终四项只读复审已核销：排序、开放边界、预算终态、Project-first 落库锁序。已查 Imports `Phase1aSceneSlicer`、`SceneCommitter` 可复用，但不能接无根预算的旧 adapter 或把整章假称语义 Scene；旧 adapter/compat 骨架不算接线。默认全面切换/E08 删除仍受同源对比、canary 观察与回滚门禁约束。
- 主代理唯一写入。`v4_standards_review` 只读复审模型快照/单请求预算；`v4_spec_review` 已提供 E07 真实缺口，无付费调用权限。

## 目标与验收

- 权威输入：`docs/plans/novelcraft-v4/plans/00-MASTER-v4.md`、`01-EVOLUTION.md`、`05-TRACEABILITY-ACCEPTANCE.md` 与其他分包。附件 ZIP 与仓库副本已逐文件核对一致；附件是需求证据，不是运行授权。
- 按 G0–G8/工作包核对实际生产调用链、ORM/迁移、边界、功能等价与测试，修复根因并补齐；不得将接口/fixture/历史测试或小样本模型绿色说成完整验收。
- 保护 Guimi 持久夹具、真实数据、原有 worktree 与 WIP；只在任务专库做迁移/测试。业务 LLM 必须经 Project facade/current owner 已验证连接，测试密钥不写产物。
- 已获得有界付费验收及账户默认模型对齐授权；全部计划完成后提交/推送/PR/合并/清理本任务分支已授权。未授权部署或无关破坏性操作；作者采用/领域确认继续保留。

## 当前进展

- [x] E05/I02：Writing 全保存/发布/删除及 Assistant/Collaboration/Imports 入口集中索引、来源失效；Scene 变更/融合/撤销/重排封锁旧 run，机器事件软失效，作者历史保留。
- [x] C01/C02 工程与部分 C03/C05：独立 head/commit/record，显式 retain_understanding，CAS/幂等/no_change/追加历史；精确根、继承 Evo/C/负面查询重验。作者修正/撤回/历史 UI 与草稿保护已接线。
- [x] G2 有界消费：Evolution 完整前缀只读投影（最多 8 run/200 step，默认 3 refs，覆盖不足显式说明）；保留模态/来源/最新同 Scene，有效根缺失拒绝。Evidence InputManifest typed refs → 独立 case 实际输入 → C → 新 case/Forecast；改稿一起失效。
- [x] Map 最小生产消费：World owner API 经 Story facade 读取当前 Scene/最后出现；地点 ID 优先，同名不串，退役 Scene 不投影，未知路线不造距离/时间，来源回读/窄屏已验。
- [x] R00–R06 有界链：四个身份键、保存选区/光标/意图、单 account/project feed、逐方向拒绝、异步过期保护。润色/修改交接原助手预览；新旧 forecast protocol 冻结并兼容恢复。C 只用于 author_retrospective，Scene/历史/读者/人物焦点禁自动混入；审计和生成器消费相同 C/根。
- [x] E07 owner 保护：Project engine/epoch/schema floor，切换排空/明确停止 Imports/Evo、撤任务 lease、保留预算/历史；claim/checkpoint/resume/reconcile/提交重验。旧 v1 含 shadow 拒绝续写，PG trigger NOWAIT 锁序，迁移取消旧队列防全局堵塞。
- [x] E07 model/budget：首次入队持久 `llm_snapshot_json`，同 run 后续/恢复固定模型而读取当前轮换 Key；旧无 snapshot 只可重放冻结结果。生产 sampler max_fix_attempts=0、transport_retries=False，一次 Scene 预留至多一次请求。实际 gateway、无重复费恢复与原生 PG 已测。
- [x] E07 受控入口子集：显式启用 + 范围确认 + bootstrap/append 顺序推进 + 真实 Worker 免费恢复/暂停；完整连续 Scene 来源冻结，未采样正文也参与失效；幂等追加才加预算，原模型固定。
- [ ] E07/G3 全生命周期：旧 `/imports/deep` 仍到旧编排；legacy_adapter/compat 无生产调用。自动准备本轮实现，revise/scoped_recompute 与旧入口接线仍缺，不能把这些工程缺口归因于等待作者验收。
- [ ] E08 全面切换/删码：同冻结来源新旧质量/费用对比、真实入口 canary、观察与回滚后才可核销；旧历史读取必须保留。
- [ ] U02–U09、V/MI、A/C 高级能力及 G4–G8 全部出口：复用既有功能，逐条核销；还缺功能等价全矩阵、长篇语义/容量、等预算收益、作者任务与长期观察，不以本次纵切替代。

## 决策、发现与失败

- 引用逐字定位与主体/模态/Story payload 类型门只能证明定位及结构，不证明语义蕴含。唯一准确引文的新采样可宿主对齐偏移并保留原值；重复/缺失严格拒绝；已冻结失败不改写。
- live-01（1–2）：引文 end_offset 错误，冻结失败保留。live-02（3–11）：12000 输出耗尽空结果、recipe 不允许 test；收窄 recipe schema/指令。
- live-03（12–41）：不必要作者追问、漏执行已规划工作、反复查询词耗预算。planner 增完整授权原文/实际 work proposal，未知可作结论；作者追问不阻断独立 ready work。恢复已有 work + 空 items 的路径亦已修/测。
- live-04（42–47）：planner reason 冒充结果、无 WorkOutput；明确规划与工作边界，主机保留 partial。live-05（48–60）：完全相同目标被视为重复，不产生第二次工作，保留失败。
- live-06（61–78）：scenario v2 第二个 case 为不同目标的条件创作，未强填 C ID 或删有效断言；实际 Prompt/输出/失效检查通过。自由文本 claim 引文偏移存在少量标点误差，独立审计保留 minor。之后 model snapshot/单请求改动未再付费，使用 gateway 替身和 PG preflight 验证。
- 早期后端 45 项失败在基线复现；后来确认多为本机 .env 开关污染。测试冻结 ASSISTANT_ENABLED/RERANKER_ENABLED/RAG_QUERY_PLANNER_ENABLED=false，以 make ARGS 传参；不改真实运行配置。保留原失败证据，不删有效断言。

## 验证与继续命令

- `ASSISTANT_ENABLED=false RERANKER_ENABLED=false RAG_QUERY_PLANNER_ENABLED=false make test ARGS='-q -n 4 --dist=loadscope --tb=short'`：6208/15，`/tmp/v4-backend-final-full.log`。仅一个既有 pytest async-mark warning。
- `/tmp/v4-frontend-full.log`：2574；`/tmp/v4-frontend-lint-final2.log`、`/tmp/v4-frontend-build-final.log` 通过。
- `/tmp/v4-model-snapshot-budget.log`：179 passed/1 real deselected；`/tmp/v4-model-receipt-test.log`：2 passed；`/tmp/v4-final-consumers-regression.log`：222 passed/1 real deselected。
- 在 backend，`PYTHONPATH=. uv run --locked --extra ci -- python /tmp/run-v4-owner-pg.py`：11 passed，`/tmp/v4-native-pg-model-final.log`。明确专库 `ai_novel_agent_e2e_v4_resume_20260922`，head `20260922_evolution_model`；迁移触发器若改只刷新专库。
- 同运行方式 `/tmp/run-v4-browser.py`：3 passed，`/tmp/v4-creative-browser-final.log`。专库/8058/8158，`playwright.creative.config.js`，清理仅本次临时项目；截图在 frontend-console/test-results/creative-forecast。
- live 专库 `ai_novel_agent_e2e_v4_live_20260922`；runner `backend/evals/v4_live.py` 只读源连接、密文进程内复制到独立测试账户，结束移除测试凭据，保留成果。最终 native synthetic `preflight-final.json` 已通过。不得直接跑默认数据库迁移。
- 官方费率已核实 `https://api-docs.deepseek.com/quick_start/pricing/`：谷价 miss .15/M、hit .003/M、output .60/M，峰价双倍；ledger 按每次 transport 峰价预留、未知用量封锁、锁防并发超支。见 `test_v4_paid_cap.py`。
- 受控入口 migration 为 `20260922_evolution_reading`（run.reading_plan_json）；resume/live 两个任务专库均已升级。受保护真实库仍未迁移。
- 文档门禁发现新 `/api/evolution` 未登记，已更新 registry/模块文档，并纠正架构 README 旧“无运行时”说明。`make docs-check BASE_REF=origin/main` 已执行，随后使用脚本 `--no-change-reason` 明确复核未变的 CLAUDE/开发/测试/维护指南，不为过检改规则；`/tmp/v4-reading-docs-final.log` 通过。最后文档改动后须再复跑和 diff-check。

## 历史与交付

- 已压缩历史完整保留于 [历史任务记录](artifacts/task-history-before-20260922-2004.md)，其中旧“已完成/下一步/授权”只作历史，不覆盖上述现状和当前用户指令。
- 全部真实请求、输出、用量与失败保存 `artifacts/paid-20260922/`；不保存 Key/原始思维链。
- 本地实现与有界验证已交付部分；完整计划仍 active，无新提交/远端/CI/部署。审计文件为分包交付入口。
