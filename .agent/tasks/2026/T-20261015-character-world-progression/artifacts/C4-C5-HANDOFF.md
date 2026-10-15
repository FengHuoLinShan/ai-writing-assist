# C4 / C5 后续批次交接

本文件只记录本次并行执行的切片与接线约束。产品语义以
[主计划](../../../../../docs/plans/2026-10-15-world-object-dossier-and-scene-director.md)、
ADR-0040、ADR-0041 为准；不是新的授权或验收豁免。

## 当前依赖和写入边界

- C0a 代码已在 primary b81ba6887，跨 World/Story/Evidence 回归2978通过；C0b/C2仍在实现。
  C3a已集成后端，C3b界面仍在实施。完整导演启用要等对象聚合/简报与参考维度，不能用旧
  Character.current_*、当前 World 或假资料补历史。纯协议基础可先作为离线切片审查。
- A0b composition/Assistant既有核心、service_keys、main、alembic env由其单一写入者管理；
  后续插件提供纯SPEC与精确接线清单。每阶段同时提供静态trace字段、R0–R4和事务形态。
- C0b可能正在改Story人物卡/Reaction及其schema/task；C3b独占SceneCockpit、ReadingFlow
  和相关前端API。开始前核对当前文件归属，优先新增协议/导演独立模块、router和组件；
  不在这些共享文件并行写。root唯一写TASK；review问题和Git冲突由Sol/high直接修。
- 唯一最终验证解释器是
  `/Users/tywww/项目/ai-writing-assist/.worktrees/map-enhancement-plan/backend/.venv/bin/python`
  （3.14.8/Pydantic2.14.0），配目标树backend cwd。原仓库venv版本不同，不能混用或改golden。

## C4a：共用协议与既有状态试验

- 入口源：`backend/modules/story/observations.py`、`simulation.py`、`rehearsals.py`、
  `continuity/state_trial.py`；验证源：`tests/test_simulation.py`、`tests/test_rehearsals.py`、
  `continuity/tests/test_state_trial.py`及P2-A/B知识边界测试（路径均相对Story）。
- `simulation_v3`统一意图、有限结算、StateDelta、ResolutionBatch和replay；新协议不写
  人物/地点/受众/轮次数量上限。已有身份按对象或地图节点ID；新增候选和文字标签不得
  冒充World地点身份。候选状态不能写World、continuity或正文。
- 先固定现有状态试验与RP回放样例，再迁移共用算法。HTTP状态试验保留接口、条件、
  三值判决、来源/拒绝归因、owner不变和零事件写入；协议版本和方法指纹变化须显式说明，
  不能把实际行为漂移藏进测试预期。与旧结果逐条件比较，不仅检查新实现自己能往返。
- Story停止新建旧排演协议后，旧运行仍按原协议只读，不重解释或迁移旧记录。
  Interaction观察者回合切换须过自己的真实评测；此前RP仍新建observation_v2，入口自身
  max_actors策略仍有效。不要为了统一协议提前切RP或删其安全限制。

## C4b：导演与参考剧本

- 新导演服务读Evidence统一简报；人物意图仅角色可知，导演层作者约束分开。只要无法证明
  某人物可知，不能把作者台账/秘密放进角色packet。人物/素材按上下文预算分组，列出分组
  和省略；不静默截断，不用固定低人数限制回避容量。
- 一次点击默认一轮；连续N轮须显式选择并预览根预算。80%或费用结果未知停止，原根累计
  用量不因暂停/重试重置。新引入的人物/物件/位置只标候选，意图不等于成功。
- 每轮不可变历史保存来源指纹、表演卡、素材、差量、用量和父/同级分支。支持从历史继续与
  依据变化选择；历史只作者删除、30天可恢复，AI目录不得暴露删除历史。
- 参考剧本保存内容副本/素材ID/角度/来源轮次，独立于历史是否删除。不得写SceneScriptFile、
  adopted_scripts或get_scene_story_basis_hash。director_reference只用于Writing生成/定向返修，
  默认关；缺失/陈旧/省略只提示，绝不降低核心KnowledgeScope或替代采用资格。
- C4完整验收仍包括：完整表演卡、区分与套话提示、可感知者标注、素材角度选择、参考保存、
  历史树/恢复、对象一致性，以及前端390/1280、键盘/失败/冲突/旧响应隔离。基础协议通过
  不能冒称导演全完成。

## C5：候选世界推进

- 在同一协议增加自由/导向推进模式；默认一步，参与者默认12可配置，步长/推荐/推进量
  单列。步数由作者选择与根预算约束，不设任意低上限；状态精确差量与滚动叙事摘要分存。
- 交汇检测依据结构化位置、目的地、目标、资源、路线、信息接收者；未知行程不能用示意图
  坐标推物理距离。无地图仅退化到同目的地，明确未核对范围；不交汇也要可行性核对。
- 生死、位置、保留项和作者有效期只读既有结构化事实及受信来源；自然语言不升级为成功
  证据。违反/未定在候选记录中明确，不回写continuity、World、正文或RP知识。
- 钩子经story.plan_structure预览后R3作者采用；人物近况仅作者笔记或作者确认的备注修订。
  势力和方案分支仍等独立路线图阶段1/2，不能读旧无时效字段假装上线。
- 持续推进提醒默认关闭，须根预算和既有持续授权，不自动开启。真实题材质量、长篇前置、
  RP迁移门禁及human_validated=false单列；不得把离线测试或模拟作者当真人验收。

## 审查与下一步

实现按C4a、C4b、C5分批Luna/max提交，逐批Sol/high审查并直接修复；所有必要实现仍属于
原三份计划，不因拆批变成可选项。先收到C0b/C2与C3b可审查提交并检查接口，再启动C4a。
不得重试封存R3、读取holdout或自行增加模型请求；真实评测由root在最终固定代码后重新预检。


## 2026-10-16 当前固定点与剩余C0

- C0b与C3b/C2b已在primary19589fa11（业务a18b80cd5）；root86后端/3专用PG/
  3134前端/lint/build组合通过。C2后端与Generic读写/类型迁移由新的Luna
  dossier_consumers在world-object-dossier-impl从5217f5310恢复，尚未交付。
- C4a Luna实现4cbc97e35已交Sol/high固定点审修，尚未集成。Sol实证typed object/map_node
  没核验owner/novel/真实来源、未知位置observer被视为同地两处问题，正在直接修复与专用PG验证。
  C4b必须从审修后的协议继续。Luna原代码的API/worker多轮409仅为暂时边界，不能保留成最终产品上限。
- 后续C4b独立导演运行/轮次/参考存储，读Evidence统一简报；不要把旧rehearsal记录或
  SceneScriptFile改名冒充导演历史，也不把新导演产物接入adopted_scripts/正文事实依据。
  本文上方完整C4b/C5验收不因基础协议完成而缩减。
- root逐项核对C0发现作者有效期覆盖的项目读规则/默认关闭开关与结构化冲突提醒仍缺；
  有向态度、别名生效区间及项目自定义文字状态字段也要实证盘点，不把注册静态字段或
  DossierValidity锚点过滤当这些能力已实现。C2/Generic首切片后另排C0c，仍属本次范围。
- C1真实长篇前置、M5势力阶段1与RP迁移评测仍未通过；工程可用切片与这些门禁分列。
  R3和holdout封存，不添加模型请求；新真实评测只在最终固定代码及完整预算预检后由root协调。


## 2026-10-16T01:17 当前协议已通过独立审修

- C4a现已在primary b3182b2c5，root1034后端/1专用PG/23Vue/lint/build通过；Luna原4cbc与Sol净fix均保留。身份、seed参与者一致、未知位置观察者及接收者保护已闭合，旧RP/state_trial未迁移协议语义。
- C4b从该审修后协议开始，仍需完整预算/历史/表演/素材/参考/一致性/UI，不保留C4a多轮409作最终限制。C2后端尚在另树自检，拟提供ReactionPreviewV2/ReactionProposalV2每人物2–4 performances完整表演结构，可复用；未获审不能直接当已发布API。
- A2新Luna在map-assistant-review独立实施目标引擎，Assistant现有核心仍由Sol A1组合单写。新migration需最终由Sol串成单head；不要抢写keys/bootstrap/既有Assistant状态机。

## 2026-10-16T01:44 C4b已启动

- Luna/max scene_director在map-assistant-structure/codex/scene-director-impl从ea8889f16（业务b318已审C4a）实施完整导演；primary已到A1审修6a31，后续由Sol统一组合。C2后端仍未固定，不直接依赖未审新符号，现有Evidence三层brief可用。
- 现有公共AIRunEnvelope/new_ai_run_envelope/read_ai_run_envelope/ai_run_scope/managed_step_scope足以承载导演域内累计账本；Goal正在改共享schemas/workflow_budget新版本，导演不并行写。新task/router/migration/纯SPEC/NoticeSource等给精确接线清单，最终由Sol真实装配验证，清单本身不算产品闭环。
- 原有有向态度RelationAttitude已含degree与端点配对基础schema；C0c需核验真实事件/来源/三视角读取，不能再声称完全没有态度模型。作者有效期读规则/开关、别名区间和项目自定义文字状态仍待实现。

## 2026-10-16T03:18 C4b 当前组合清单（尚未交付）

- Luna 工作树仍为 map-assistant-structure/codex/scene-director-impl，未固定最终提交。新 HTTP router 为 modules.story.director_api.router，暂未挂入 Story 旧聚合器；普通旧模块回归不覆盖这些新 HTTP。Sol 必须在同一审修批次登记下面四项操作后挂入路由并验证 app.main、真实 API 和 trace，不能以导出清单替代装配。
- 纯 OPERATIONS_SPEC 在 modules.story.director_operations：story.scene_director.preview → POST /api/story/scenes/director/budget-preview（R0）；story.scene_director.start → POST /api/story/scenes/{scene_id}/director（R4）；story.scene_director.continue_preview → POST /api/story/director/roots/{root_id}/budget-preview（R0）；story.scene_director.continue → POST /api/story/director/roots/{root_id}/branches（R4）。历史管理仅作者 HTTP，必须逐项 trace 豁免并确认不暴露 AI 删除。
- Task 名 story_scene_director，根能力 story.scene_director，never_retry/max_attempts=1/retry_transient=false；请求、token、时限来自作者冻结预算，run_id=director_root_id，checkpoint 镜像同一 root ledger。最终 TaskRegistry/root-capability/confirmation 与 NoticeSource story.scene_director 都由 Sol 组合，不扩旧 RP 能力或重置开始时间。
- 正式 director_reference 已在 Luna 树实现独立 loader/section/KnowledgeScopeDimension/confirmation IDs 与写作提交时冻结副本。DI 接线：modules.evidence.compilation.contracts.EVIDENCE_READ_STORY_DIRECTOR_REFERENCES（键 evidence.read_story_director_references）→ modules.story.facade.read_scene_director_references_for_writing。默认空 NOVELCRAFT_DIRECTOR_REFERENCE_ENABLED_CAPABILITIES，只允许 writing.generate、writing.targeted_revision；缺失或陈旧副本只提示，不改变核心 stale 指纹或采用资格。
- 独立 Sol 必审：新增未知费用不能继承旧 attempt 的确认而被绕过；80%时间、同根分支并发与原 deadline；旧人物卡任意自由文字不得绕过 Evidence 知情证明进入角色 packet；模型 fact/pattern IDs 必须属于该角色的当前可知 packet 和冻结来源。Luna 已自行收窄旧卡文本，不能因此省略独立验证。

## C5 下一批不得遗漏的入口与门禁

- 从已审 C4 固定点复用共用协议和知情 packet；由 Story 持有新推进运行/步骤与不可变历史，不把导演回合改名当推进。根开关 STORY_WORLD_PROGRESSION_ENABLED 默认关闭；目录中准备运行为 R4、已授权根内推进一步 R1、读取 R0、钩子结构预览/采用 R3，费用与授权语义分别核验。
- Assistant 的 world_progression_review 引导流程按 ADR-0032 正式注册且默认关闭；钩子接真实 story.plan_structure 滚动窗口预览，交汇起点向导演传显式假设。人物近况只进入作者备注的确认入口。推进记录不进入 Writing 检索、Evolution 阅读或 RP。
- 持续推进提醒需要真实持续授权预算/读入新章的触发及统一 NoticeSource，不能用静态提示冒充轻量自由推进，也不能后台另起脱离授权的预算。模型推荐步长须来自可说明的模型/步推进量观测；无实测时明确样本缺口，不伪造测量值。长篇、题材与真人验收仍单列。


## 2026-10-16T04:41 已集成C4的C5起点

- primary固定6ad6b94df，产品等于Sol10b5f6f00（C4与Goal组合）；b085仅测试notice manager回收。新C5树world-progression-impl/codex/world-progression-impl已从6ad创建，无产品WIP。上文早期未装配清单是历史记录；现在v10实际100项，其中导演8项：history、check_consistency、advance、save_reference、preview、start、continue_preview、continue。旧v1-v9与map.edit哈希90aa均保留。
- Director/Goal新空专库联合24项、前端3157/lint/build通过；实际worker同根8次受控provider/80token与新unknown再次停、390/1280参考保存/刷新/Writing窄栏键盘保存已验，零真实模型。普通广覆盖仍有3个测试fixture遗留manager顺序失败，由C4 Sol修后再结案；不影响从固定产品实现C5，但不可冒称回归全绿。
- 共享组合根、keys、操作目录冻结、TaskRegistry与migration祖先当前由C0 Sol单写。C5先独立服务/schema/router/task/纯SPEC/组件，报告精确接线；完成实现后仍须Sol真实注册、API/trace/PG/worker与浏览器审修。root独占三TASK。
- 复用director_budget/tasks已审durable checkpoint、原root start/deadline与账本单调合并，避免重演expire_all异步失效、client.timeout、内部mode误校验和续轮preview漏branch_kind等实际缺陷。普通Assistant的R1域内推进必须验证确为author turn并记原领域根；Goal未适配不得伪造根身份。
- C0 Sol正补Map/Relation/自定义状态真实typed有效期读取及director consistency，不把尚未接线写成永久unknown。C5先从稳定接口准备明确依赖，不抢写该批composition。


## 2026-10-16T04:49:15+08:00 C5已审产品起点与组合复验

- C5独立树已快进primary07264f17a，新增仅测试资源归属修复616e9d474；根源是HTTP fixture经留痕创建背景manager后未回收，未改生产隔离guard。root原组合最终5102通过/1 deselected/已知warning，183.84s；Sol逐测modules5751与Editorial→Notice→Evals同序34通过，原8299广覆盖尚待最终结果。
- 原先3个Writing隔离失败已在root最终组合中消失，前端3157、24专用PG与真实worker/UI证据继续有效，不因仅测试夹具改动重复付费或浏览器流程。C0c仍由另一个Sol独占接线，完整C0另有模板借用、题材包与互通尾项，见C0-TEMPLATE-INTERCHANGE-TAIL.md。

- 2026-10-16T04:51:59+08:00 Sol原8299最终通过/8 deselected/已知warning，323.76s，两个Director专库已释放使用权、数据保留；Luna/max luna_world_progression已启动上述072树，完整C5实施中，不再等待C4。当前其余活动为Luna A3与Sol C0c。


## 当前C5实施环境补充

C5 Luna仍独占world-progression-impl/codex/world-progression-impl的新独立模块。
root已分配新专库world_progression_impl_test_20261016（是否创建待实际回报）与空闲端口
18590/18591；原凭据0600、仅loopback65202严格守卫和替换该新库，不探默认/他库。
准备PG前先checkpoint独立WIP，再仅在无冲突时合C0c固定9b9c022a5，迁移接实际单head；
有Git冲突停下交Sol直接处理。当前起点072没有C0c真实有效期代码，阅读新源码不算运行已覆盖。
共享keys/bootstrap/catalog/TaskRegistry仍归A3 Sol，不在Luna树争写。


## 2026-10-16 root逐项复核的C4尾项（待Sol直接补）

计划§6.4第3条要求导演新人物/物件/地点可“一键转为World候选”。root核对primary f5c6：
SceneDirectorPanel.vue:167–170的candidate_events仅显示label/description/说明；
director_api.py和World域未找到该转换桥接。原先候选不自动写入状态/正史边界正确，
但缺显式作者转换的端到端证据，不能将当前C4工程测试当全部功能已交付。
已通知当前A4 Sol排后续队列，由Sol独立核对并直接补最小作者候选桥接；不是root改产品。
需精确绑定已存round/candidate reference、来源指纹与novel owner，不凭名称猜已有身份，
重试幂等，候选后续采用仍经既有确认；有真实HTTP/trace/UI闭环。新候选不是已发生事件，
不进入角色知识或Writing检索。新增目录与历史冻结由Sol按实际操作类别处理。
C0模板互通和C5推进仍独立写入，不能同时抢写其World/Story文件。
C5已获flows.py中world_progression_review v1注册与TOML Story prefix窄写权；
root为后续C3/A1准备的旧C4 review路径现切到codex/chapter-order-timeline-impl/f5c6，
原codex/scene-director-review/616e9d474与原证据保留，没有删除旧提交或数据。


root另为C5审修复用已结束的map-clue-review旧C0c干净树，保留旧
codex/world-object-validity-review/7b91006d4后，切到codex/world-progression-review/c482b0da9。
当前只是准备，没有代理在此树写入；后续从当时最新primary核实后由Sol接C5候选。
C5 Luna已确认未改director_*.py或SceneDirectorPanel.vue，但api/story.js由其窄写。
其全前端3177/3178唯一失败为旧WorldEntityDetail fixture，root指定先checkpoint，
只cherry已审Sol 8ca60ff805ad3bc45e6f04364201ecf5c4501995，不能另写弱化断言。
PG world_progression_impl_test_20261016尚未创建（代理最近确认），暂无真实HTTP/browser。
后续C4桥接、C5、C0不得同时写api/story.js或World facade；顶层装配顺序由root移交。


## C5 PG不可变性边界的已确认待修

Luna已创建world_progression_impl_test_20261016并升级至20261016_wp_cascade，数据保留。
原step trigger一律阻止UPDATE/DELETE会误拦项目删除；新follow-up仅用
DELETE + pg_trigger_depth()>1放行，root读迁移:25指出这也会放行存续项目下root/branch
物理删除及其他嵌套trigger。Luna已明确承认，保留当前专库和parent-delete红例，停止改该
触发器规则，交Sol按用户要求直接修。应按既有安全模式仅在真实schema限定的父Project
已消失时放行项目清理；直接Step UPDATE/DELETE、仍存Project的父root/branch删除均拒绝，
不要用TEMP同名表/宽泛深度条件绕过。当前门禁不合格、未合primary。
C5没有director_*.py或SceneDirectorPanel.vue改动；api/story.js仍本域写权。
五Vue组件用例不是浏览器，真实HTTP/browser尚未运行，后续Sol须验完整TaskWorker/预算/界面。


## 2026-10-16T06:39:58+08:00 执行检查点

C4对象候选桥接首版已跑8PG/真实浏览器，但root指出仅candidate_events不覆盖表演/素材的kind=candidate新人物/地点refs，Sol正直接补真实结构化对象选择/去重和纯SPEC R3/HTTP trace。C5 Sol已直接修演员作者摘要泄漏、地图有效期gap、钩子重放回执与锁后重复采用，并发现实际app import的_task_meta缺失，继续修复；52定向通过仍不替代完整装配。第9项独立R4 resume由root按完整预算契约明确推进，同Root与未知累计不得重置。


## 2026-10-16T06:59:09+08:00 当前执行检查点



当前执行检查点（优先于上面的批次历史）：C4尾项Sol固定64a99091272e133d4df4ec3a5e2e50c4ad82d104，已无冲突合primary c579beb872e7f6193476ff4d0abd0d034810f95c，25文件1219+/37-。新人物/地点/物件/设定的结构化refs按精确ID去重，和剧情事件分别转World候选；R3纯SPEC/HTTP真实confirmed-executed trace与v13冻结已装配，旧v1–12保留，未进Goal R2自动allowlist。唯一head20261016_story_director_candidate_transfer。Sol Story170/Assistant+Writing248/Trace42/9PG+1Goal预算PG/3182前端及lint/build/docs/repo gates通过。root已看390/1280两图与真实浏览器日志，确认HTTP201、World陌生访客candidate无approved_by、刷新回读及390无溢出；18596/18597已停，旧review库释放保留。

root在保留的operation_trace_report_primary_test_20261016正常从A4 upgrade到C4，head/ORM parity通过；新组合PG为43通过/2失败（15.47s）：新C4 test_director_candidate_transfer_postgres.py:285假定账户原trace偏好off，保留库中on使先前合法确认也被统计（4!=1）。这是测试隔离问题，未改产品；已授当前Sol C5该单文件写权，要求净fixture commit供root单独cherry与复验，不能放宽成>=1或改trace。原CREATE脚本不重跑，/tmp/map-c4-tail-primary-reuse-pg-20261016.py仅复用升级且已执行；失败日志/tmp/map-c4-tail-primary-pg-20261016.log。当前完整普通后端在session65443、/tmp/map-c4-tail-primary-backend-all-20261016.log，未提前宣称C4集成全绿；docs/repo gates已过。root确认与Sol64a的backend/frontend源码无净差，前端沿用同源3182及已看图证据。

共享槽已正式移交Sol C5：其独占审修先固定并合c579为c6061dd77，只在数据库设计文档标题冲突由Sol保留C4+四C5表修正；首C5 migration父接C4，唯一head20261016_wp_cascade_guard，新world_progression_review_test_20261016已创建一次fresh upgrade成功，旧Luna库未动。现装配main/bootstrap/metadata/TaskRegistry/worker/9项目录/NOTICE/Flow/Writing真实commit触发/story.js并验PG/actualWorker/HTTP/browser。已直接修累计摘要泄角色、地图gap、钩子锁后重放、缺_task_meta import、同根R4 resume、原deadline80%检查、锁顺序、失败候选事件回灌、每步sum(a,b,c,d)必抛TypeError等；定向绿仍不替代实际Worker+PG。原root/start/deadline、所有已用/unknown计数不重置。

C0 Sol独立审修继续：已安全创建dossier_template_interchange_review_test_20261016，fresh/head/parity与2PG/HTTP通过。发现并直接修同名dossier重复导入/异值不冲突、JSON来源修订及证据伪造、借用移除与条目创建并发；原JSON只有下载，现补作者文件预览/映射/确认UI。四新纯SPEC borrowed.read R0/borrowed.edit R3/manifest.preview R0/manifest.apply R3由该Sol实现，旧冻结不改，manual export独立明确边界，顶层冻结等C5后顺序组装。World facade/dossier/Imports/world.js仍该Sol独占。

C4退出的子槽已启动新Luna/max luna_copilot_alignment，simulation-v3-director-impl/codex/copilot-mechanism-alignment-impl从c579实现C3真正forecast v2/人物弧计划实际/Evolution阅读notice；禁止其写C5共享顶层/Story.js/Writing commit/flows/推进/导演及C0 World hub。专库copilot_alignment_impl_test_20261016与18600/18601已分配但hold CREATE/upgrade，待C5线性迁移固定再接后继。A1章节重排/一般事件时间线仍下一批，准备树未派。
