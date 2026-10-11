# Evolution 演化系统

V4 长期计划（`docs/plans/novelcraft-v4/plans/01-EVOLUTION.md`）的演化引擎模块。
含 E01 契约层（来源引用、观察外壳、身份解析、类型化状态操作、运行回执）、
稳定观察身份推导，及 E02–E09 的提交协议、持久化、编排、失效传播、迁移切换
与生产 LLM 采样接线。默认导入仍使用 deep_import；显式启用演化的项目由共享
owner 门禁封锁旧写入，入口替代和真实质量验收仍独立推进。

项目偏好中的“逐场景理解 · 试用”经 `/api/evolution`（`api.py` / `workflow.py`）提供范围预览、明确确认、
bootstrap/append 顺序执行和状态/恢复。已有场景前缀可复用；尚无场景的正文末尾通过
Imports 纯规划/切分/提交原语准备边界，不创建旧 workflow owner。计划持久化于
`reading_plan_json`，来源、模型与 owner 指纹确认后再入队；未采样来源也参加失效。
下一步沿用真实回执和原队列；重复确认不加预算。Worker 异常/服务器中断时独立持久化
恢复旗标，已冻结结果免采样恢复，费用未知不重发；作者停止或失去租约不可恢复。
每次边界切分/纠偏与 Scene 理解共用根调用预算；冻结请求与结果供免费恢复，历史准备回执
在追加时保留。额度用完后显式 `continue` 才追加，同一操作不重复加额度，旧队列终态前
不得追加。来源按正文位置排序，未确认的整章 fallback、开放边界、未解左承接及低置信
结果留作待审草稿；人工确认后沿原预算继续。相邻章尾仅作边界参考，固定来源并参加失效，
不回流为当前 Scene 的观察正文。边界结果不冒充 Phase 1b 语义补全。
`revise` 可从正文/Scene 首个变化处保守重算后缀；`scoped_recompute` 可由作者指定
Scene 起点，若更早来源已变则向前扩大。两者预览并确认新调用额度，新 run 仅引用
逐条重验的原回执前缀和真实游标，且每场必须仍是最新成功结果；不复制回执或旧费用，
旧任务终态前拒绝启动。
无效逐字引用的 sampled 冻结结果不能无限直接恢复，作者可显式发起新范围请求。
`scoped_recompute` 也可选择本 run 已提交观察中的对象身份或 observation_id；
`GET /reading/{run_key}/targets` 按名称/观察文字检索、分页，不调用模型。主体必须有本项目的
已解析身份，观察保留模态和原文，不把未命中说成正文不存在。宿主从最早相关 Scene 定位，
再与来源首变位置取更早者，保守重算整个顺序依赖后缀；预览绑定实际目标、扩大范围与额度。
新运行的分段授权记录目标和真实重算起点，原前缀回执身份不变；旧请求缺少新增可选字段时
仍能按原 operation 重放。精细依赖图和旧入口等价替代尚未完成。

## 职责边界

- 消费登记与影响评估（P2-C，2026-10-07）：`consumption.py` 契约（登记内嵌产物行
  `state_json["_consumption_registry"]`，不加表）+ `registration.py` 写入端 +
  `impact.py` 组装层。失效回执增量携带 `affected`（场景+机器可读原因+known/unknown）、
  `unknown_scope`、`receipt_id`、`recompute_options` 三分类；无登记时与既有保守
  行为逐位一致，无真实登记的锚定投影按 outline 结构合成整章登记。公共视图经 DI 键
  `EVOLUTION_INVALIDATION_RECEIPT_VIEW`（`facade.receipt_view`）供 Writing 保存链路
  消费。Story 真实投影已逐维度登记本场与继承前缀，重复 ensure 保持登记时间；
  回执指纹包含来源摘要，连续等长改稿仍产生独立提示。权威语义见 [docs/modules/22_evolution.md](../../../docs/modules/22_evolution.md)。
- 来源身份：`SourceRevisionRef`（章节序号不独自承担来源身份；
  range_hash 由 content_hash + 偏移确定性推导）。场景步的来源绑定
  （`pipeline.SceneSourceBinding`，A02）锚定真实 Writing 草稿并携带码点
  区间（start/end offset，缺省整章）：整稿指纹（版本门）与 Scene 区间
  （来源门）分别验证，服务端按权威草稿取出区间精确切片与 scene_text
  逐字比对（非自比较，不信任请求声称的正文）——同一章可分多个 Scene
  各自推进；区间漂移、越界、整稿换版（含同长度替换）都判 source_changed。
  任务层另经 outline_state 校验 scene_id 与章号的权威映射。观察的
  SourceRevisionRef 偏移映射回草稿绝对空间，分段变化不复用旧观察身份。
  跨章 Scene 使用 `additional_sources`（至多 15 个附加区间），按章序且
  不重叠地拼接；每段都重验最新草稿与范围，任一段换版即整步失效。Scene
  仍是原子提交单位：跨章事件与游标在末段所在章生效，不向首章泄漏后文。
  旧单区间请求形状和 manifest 指纹保持兼容，无数据库迁移。
- 前序认知（A04）：`store.load_prior_observations` 覆盖最近
  `PRIOR_OBSERVATION_WINDOW` 个已提交 Scene 的**结构化**观察（modality、
  主体表面名、观察身份、来源 Scene），不再压成裸谓词——传闻在下一
  Scene 的输入里仍是传闻；Prompt 按 modality 分级渲染并显式披露截断
  （scenes_included / total_committed_scenes / omitted_observations，
  未注入不等于不存在）。完整历史认知/持久知识查询仍属后续里程碑。
- 逐字引用：编译前校验 quote 与 Scene 正文完全一致；重复引用须提供
  `start_offset/end_offset` 码点范围，缺失、歧义、越界和错位一律
  `invalid_observation_source`，保留 sampled 结果及计量且恢复不重采样。
  新生产采样对唯一逐字引文可校准偏移，保留原值与 `exact-unique-scene/v1`
  回执；重复或缺失引文仍拒绝，旧冻结失败不改写。
  引用跨章时拆成多条精确 `evidence_quotes`，每条带真实草稿/hash/绝对区间；
  观察身份同时绑定全部引用范围，编译冻结保留来源以供后续 Evidence 回读。
- 观察：`ObservationEnvelope`（modality 区分事件/陈述/信念/假设/规划/比喻/不明；
  未解析提及保留 mention 身份，禁止伪造实体 UUID）。模型只输出表面名；
  提及身份由宿主按观察身份派生（`observations.derive_mention_id`），
  编译后观察（含解析结论）随冻结负载持久化。
- 身份解析：`IdentityResolution`（reuse/new_candidate/ambiguous/unrelated；
  身份去重与观察积累分离）。E02 确定性裁决内核只接受明确身份依据；生产仅字面精确名称自动
  reuse，相似度阈值永不自动合并已采用对象；同名多候选保持竞争（ambiguous）；
  观察者自带实体绑定必须经精确证据重验，不支持则 unrelated。生产候选召回
  经 world facade 精确名解析（`pipeline.exact_name_candidate_lookup`）。
- 状态操作语义门（`state_gate.py`，2026-09-22 审查 A03）：观察解释 →
  确定性验证 → 领域事件。每条 scene_event 提议必须自附证据
  （`source_observation_indices` 引用同批观察，伪造/越界拒绝）；客观状态
  维度（entities/relations/locations/timeline/causality）只接受
  event_observed 观察作证据，character_statement/belief/hypothesis 只
  支撑 knowledge 维度且必须写明 `knowledge_subject`（谁知道）；
  author_plan/figurative/unclear 不支撑任何状态操作。被拦提议带原因进入
  gated_scene_events 与 pending_decisions 待作者裁定；通过的事件携带
  宿主派生 `source_observation_ids` 与 `authority_basis` 证据链，并写入
  `snapshot_after.meta` 持久化；knowledge_subject 同样进入状态负载。
  move/observe 之辨（仅移动证据才算 traveled）仍在在场投影（T03）分层。
- 回执与游标：`EvolutionReceipt`（failed/blocked/unknown_billing 禁止推进
  committed_prefix——游标只在领域提交成功后推进）；paid_call_receipts 携带
  provider/model/usage 计量供费用审计。用量口径（A06）：任一尝试对某字段
  未知，该字段总量即 None（不把未知次数当免费）；`usage_complete` /
  `unknown_attempts` 区分完整计量与部分未知，attempts_detail 逐次对账；
  最终失败的采样同样固化失败回执（outcome=failed_final）再重抛（A07）。

- 窄提交（E03c，`commit.py`）：prepare 阶段 `freeze_attempt` 先持久化冻结
  负载（T10 恢复基础）；`apply_frozen` 短事务内依次重验 owner epoch（T12
  前置）→ 真实来源指纹 → 父回执身份与前缀，再执行注入的领域 applier 并
  保存回执——游标只在回执持久化后推进；同 attempt 重入直接重放原回执
  （T11：不重复领域写入）。`recover_attempt` 复用冻结负载重验重提交，
  全程不接触 provider。

- 持久化与编排（E04）：运行三表（run 注册表 / 冻结尝试 / 回执）+ Alembic
  `20260921_evolution_tables` / `20260921_evolution_shadow` /
  `20260921_evolution_single_writer`；`store.PostgresAttemptStore` 绑定
  `(db, novel_id)` 实现 AttemptStore（回执落库同事务推进游标与 head 指针；
  预算条件 UPDATE 原子预留，仅 active run 可扣减；同 run 重试不允许改变
  mode/execution_mode，避免把 shadow 请求作为既有 live run 执行）。E07.c 单写者是数据库级
  不变量：部分唯一索引保证同项目同时至多一个 active live run，并发注册在
  索引层只有一个赢者；排空/停止的 run 不因重复注册复活。
  `orchestrator.prepare_scene_input` 前序屏障（T07）带顺序检查——run head
  的 through_scene_index 必须恰好是 N-1，跳场/倒序/重复推进显式拒绝；前序
  输入携带实际状态内容（前序观察的有界摘要），采样 Prompt 据此注入真实理解。
  `plan_parallel_batches` 依赖键准入，Scene 批次位置取其全部任务的最大批次。

- 失效传播（E05）：`compute_source_change`（同长度修改也检出，含受影响
  偏移窗口）；`apply_source_invalidation` / `apply_scene_reorder_invalidation`
  跨域失效（evidence 索引换源 + story 投影软 supersede + 未接缝消费者
  显式 unsupported），回执带保守扩大说明。

- 管线与消费者（G2）：`pipeline.run_scene_step`（屏障→预算（先持久化）→
  请求前冻结→ provider 采样（事务边界之外，async sampler）→ 采样结果
  先行耐久化→ 观察/身份/结构门确定性编译 → 编译冻结 → 独立语义复核 → 窄提交（真实来源
  重验））。冻结负载按阶段推进 `sampling → sampled → compiled → verified`（A07）：
  attempt 身份与预算关系在请求发出**之前**落库；provider 结果在任何领域
  推导之前落库；观察编译是纯确定性推导，恢复可在 sampled 阶段负载上重跑
  而不重新采样。未调用的独立复核另计一次预算；域提交失败回滚不抹掉预算预留与冻结负载；
  `pipeline.recover_scene_step` 与任务 handler 的恢复优先重放（已提交→
  **任意已提交 Scene** 按稳定请求身份（`compute_scene_manifest_hash`：
  run/scene/正文/整稿版本/区间）幂等重放原回执，不重采样不扣费；修订
  请求指纹不同不套用旧回执（A08）；未提交冻结恢复同样检查请求指纹与
  Scene 身份，变化返回 request_changed；compiled→免采样重提交；sampled→
  确定性重编译；新协议已计划但未调用的独立复核仍需预算，verified 才能免费重提交；sampling/failed→`SamplePendingReconciliationError`
  待核对——请求已发起或已失败、费用可能已发生，不得自动重采样，对账后
  登记新 run 重来）。
- 执行模式进入冻结/提交协议（A01）：影子 run 的冻结负载盖章
  `execution_mode=shadow`；首次执行与恢复经同一写入策略解析
  （`_resolve_step_applier`：run 登记模式或负载盖章任一为 shadow 即强制
  隔离 applier，不信任调用方传入的正式写入器，未盖章的既有负载按 run
  登记模式兜底）；提交边界 `apply_frozen` 拒绝影子负载经未标记
  `shadow_isolated` 的 applier 写入（纵深防御）。预算单位说明：budget 以
  实际请求为准入控制单位，生产采样明确禁止结构化修复和传输重试，一次预留至多
  一次 provider 请求；失败保留费用与冻结结果。实际金额仍以 paid_call_receipts
  为准，调用次数不是美元预算。
  采样器经 `sampler.resolve_scene_sampler` 以 async context manager 持有
  （客户端生命周期成对）。`consumers.check_suggestion_validity`（T17 建议
  有效资格按索引指纹；无声称或无已索引指纹时 unknown，不宣称一致）；
  story 侧只读在场投影 `project_scene_presence`（T03 未知路线不造真）。
  端到端验证：`tests/test_g2_vertical_slice.py` 为**确定性夹具下的
  存储/投影集成切片**（provider、人物候选与场景事件来自固定夹具）；
  `tests/test_review_remediation.py` 覆盖评审返修的关键行为（真实链路
  观察-only sampler、故障注入、屏障顺序、单写者重入、计量回执）；
  `tests/test_audit_fixpack.py` + `tests/test_state_gate.py` 覆盖 2026-09-22
  审查 A01/A03/A07（影子恢复隔离、语义证据门、阶段化恢复与费用待核对）；
  `tests/test_fixpack2.py` 覆盖同轮审查 A02/A04/A08（同章多 Scene 区间
  来源、传闻保持传闻的前序注入与覆盖度、任意已提交 Scene 幂等回放）；
  `tests/e2e/test_evolution_single_writer_concurrency.py` 为真实 PG 双会话
  并发门禁。`tests/test_g2_consumers.py` 使用真实生产 handler 连接连续 Scene、
  两个独立 case、前瞻、地图与实际改稿失效；provider 替身只证明工程链路。
  `evals/v4_live.py` 在专库执行相同场景，按 transport 请求留存费用与实际输出。
  完整 G2 的质量结论以真实输出审查为准，不由合成测试代签。

`reading.py` 只读投影 live 已提交理解：验证完整前缀与传递正文根、Scene 映射及
同 Scene 最新成功回执，保留原模态与引用。Evidence 必须选中全部根来源才能消费；
后续无关追加不替换原冻结引用。当前有界读取八个 run、每 run 二百步、默认返回三条，
超限明确未覆盖。Collaboration 将实际消费的引用保存为持久理解依赖。

生产 sampler 对唯一逐字引文校准偏移并记录原值，重复或缺失引文仍失败关闭，旧冻结
失败不自动修写。状态门检查全部引用的主体/模态，再调用 Story 物化 schema；未解析
地点保留文字，不能伪造 ID。类型通过不证明语义蕴含，待决定提议不进入合法状态。

## 测试

`tests/`：契约语义、稳定观察身份、身份解析、窄提交协议、编排与预算、
失效传播、迁移切换、G2 夹具切片与评审返修行为；真实 PG 并发在
`tests/e2e/`（`RUN_E2E_TESTS=1` + 专用库）。

E09 长书规模验证（真实叙事语料 × 真实 handler × shadow 链 × 退出标准
断言）用 `tools/evolution_scale_harness.py`（专用库；`--sampler real`
经账户连接真实模型，另行授权）。

## 当前接线与验收边界（2026-09-22 复核）

Writing/Assistant/Collaboration/Imports 的保存已集中消费失效与索引入口；Scene 生命周期
和重排封锁 stale run 并软失效机器事件，作者历史与旧回执保留。Story 在场现由 World
MapSceneContext 实际消费。Collaboration 的独立持久理解已通过 Evidence 进入新 case
的实际模型输入，但冻结观察本身仍不冒充理解。`ownership.switch_project_engine`
在 Project 独占锁下检查预期 epoch，排空或明确停止旧 Imports/Evolution owner，
取消理解队列和 lease，推进项目 epoch/schema floor；预算、历史和冻结结果保留。
Imports 的提交、claim、checkpoint、恢复和 reconcile 与 Evolution 的注册、预算和
回执写入均重验项目 token。PG trigger 拒绝旧 worker 写入；新任务协议使用
`evolution_scene_step_v2`，旧 v1（含 shadow）不能续写。迁移先取消旧队列项，
已有 live run 的项目暂停为 read_only，避免猜测归属或阻塞其他项目任务。
schema floor 升至 2 后只能暂停或由兼容新版恢复，禁止降回旧引擎。
原生 PG 已验证新旧 owner 竞争、旧 SQL 拒绝、心跳锁序及历史迁移；默认入口替代、
观察期和真实质量尚未通过，不能宣称 G3 或 E08 退役完成。完整结论与继续顺序见
[本轮实施审查](../../../docs/plans/novelcraft-v4/IMPLEMENTATION-AUDIT-20260922.md)。

生产 run 在首次入队时冻结 `llm_snapshot_json`，同 run 后续 Scene 与恢复使用
Project snapshot seam，读取当前轮换 Key；改变账户默认模型不改变排队中的运行。
旧 run 缺快照时只能重放已经冻结的结果，新付费步失败关闭并要求新运行。
迁移 `20260922_evolution_model` 不猜填历史快照；预算与旧结果保持。

DeepSeek Flash 的窄观察采样显式关闭思考，输出上限 16,384；状态、场景语义和
复核/生成步骤显式使用 high 思考，输出至少 32,768；世界对象、别名关系与独立
审查至少 65,536。请求已冻结后的失败不原样重发；超出当前世界审查输入容量的候选
保留为 `capacity_deferred` 待核对，不写入 World 正式对象。
生产采样若最多三条引文缺失或重复且无精确区间，隔离这些观察及依赖它们的状态
提议，原输出与逐项原因保留回执，理解进度显式列为未解决；更多错误仍失败关闭。
底层提交来源门对任何未隔离的不准确引文继续拒绝。
仅当去空白后的引文在当前 Scene 唯一匹配时，采样器以原文连续片段校准缩进与
换行并记录模型原引文及区间；字词、标点不同或匹配不唯一仍不校准。
别名/关系步骤只允许现有结构化客户端逐项隔离 `uncertain_items` 的无效条目，
回执保留跳过数量、索引与校验原因；别名和关系条目仍须整批通过 schema。
世界或别名关系抽取若收到用量完整的格式/schema/截断失败，冻结失败调用回执并将本场
World 标为 `extraction_deferred`，不创建世界对象；来源观察与独立状态复核继续。
连接或费用未知、权限和来源失败仍阻断整场，不做同请求自动重试。

独立状态复核（`state_review.py`）：通过引用/类型门的候选仍不可写入正式状态。
新运行使用单独的 `evolution.state_review` 调用，完整回读当前 Scene，逐项检查
否定、条件、时态、主体、角色认知及移动来源；仅 supported 且有原文逐字依据才放行。
漏项、重复序号、无依据、矛盾或无法确定均保留为待决定候选，不产生状态效果。
复核输入绑定 attempt、来源、parent receipt、epoch、前序输入及全部候选，提交时再次
验证绑定。采样与复核各预留一次根预算、禁自动重试、各自冻结费用回执；采样后额度
不足显示 needs_budget，追加授权后只执行尚未调用的复核。复核结果已保存时免费恢复，
请求已发出但结果不明或最终失败则待核对，禁止重发。旧计划/冻结没有复核版本时不
自动增加付费步骤，其未复核状态提议进入待决定，历史已提交回执不改写。独立调用
降低自我确认风险，工程测试不等于真实模型语义质量通过。

### 顺序场景语义整理

新 Reading plan 的 `enrichment_version=1` 对本流程自动生成且未人工编辑的草稿逐场整理，
明确重算也会更新已自动整理的草稿；旧计划缺省为 0，不追加费用。每场使用当前精确正文与
真实已提交前序回执，通过 Imports 的 Phase1b 纯请求/校验端口生成叙事字段，再经 Evidence
独立 group audit。生成和复核分别占用一次根请求预算，完整结果冻结后才能进入下一步；
预算耗尽保留已有结果，继续授权只执行尚未调用的步骤，费用未知须对账，不能自动重采样。

Scene 卡、正文、parent 和 owner 在提交前重验。通过复核的字段与回执/游标同事务写入；
复核未通过、置信低于 0.90 或约束未决时只保存待核对候选，场景详情可显式填入编辑表单，保存仍由作者确认。人工编辑、
旧流程与已确认 Scene 不自动覆盖；候选叙事判断不作为角色事实。领域失败整体回滚，冻结结果
可免费恢复。短提交先取得 Project 独占锁，再 advisory/run/领域锁，provider 等待不持事务；
复核收尾重新加锁读取最新冻结记录，避免覆盖并发恢复已开始的后续计费记录。

当前此链覆盖场景语义、状态、世界候选与剧情结构；高质量融合及完整采用迁移仍按审计表推进。

### 剧情结构阶段（Phase 3 迁移）

新 Reading plan 携带 `structure_version=1`；旧计划缺省为 0，不追加费用。所选
Scene 前缀全部提交后，同 run/队列/根预算进入结构阶段：每批最多 16 个已提交
Scene 生成剧情线/人物弧/伏笔等候选（经 Story 纯端口复用 deep-import Phase 3
契约），再按 Scene 正文分片独立证据复核。生成/复核请求不钉 model，由 run 冻结
的模型连接解析默认；候选摘要超出复核窗口（4000 字）直接失败关闭为待核对草稿，
不物化未复核结论。复核通过的结果以 `needs_review` Story 草稿持久化并登记
`evolution_structure_ref`；作者在故事大纲采用时重验原回执与最新来源，来源漂移
拒绝采用。重新授权（追加额度/续读）重建计划时保留已完成结构批次，不静默重跑。

边界置信不足时暂停在 `needs_scene_review`。工作台单独确认边界后保持自动草稿资格，
恢复原预算和来源，继续语义整理；不能以整场采用替代边界确认并静默跳过语义生成。


### Scene 世界资料候选（2026-09-23）

新 Reading 授权冻结 `world_version=2`；旧计划恢复和 append 保留原版本，不偷加付费阶段。
观察与语义整理后，当前完整 Scene 和真实前序回执进入 Imports Phase2a 纯 builder，
然后给本场新候选分配局部引用供别名/关系观察，最后执行独立组级审查。三种请求各自
预留一次根预算，冻结具体 request/schema 指纹与结果；无身份对象时不空跑关系，空输出不假称语义审查。
结果已取回后的领域失败免费重放，费用未知则待核对，身份漂移要求新范围授权。

通过审查的世界对象、别名、关系只保存 candidate，与 Scene 回执/游标同一短事务。
同名歧义、明确新人物却撞旧名、旧字段新描述均保留待裁定；既有摘要不被覆盖，也不会
把新描述引文误挂为旧摘要的 supports。Phase2a delta 不进入旧 manual-correction 路径，
仍由独立状态门控制。新协议在 World 审查后给无歧义的本场新身份冻结 UUID，再复核
对应状态；候选创建、状态、回执必须一起成功。同场多个同类型同名新人物不给状态身份。
内部 `candidate_id` 仅能创建 candidate，不作为公共创建参数。

关系上下文只取本 run 或显式继承回执里的冻结物化内容（最近至多 64 个相关场景），
不读取当前 World 描述充当前史。原始回执、端点及来源一同保留，缺少前例不等于首次
结盟。变更/结束仍保留作者审查提案，不自动改写旧关系；旧 run 的付费步骤不改变。
生产精确身份查询排除无叙事截止证明的别名，避免后文身份揭示污染前序 Scene。

候选携带 `evolution_ref` 指向真实已提交回执。World 各采用/合并入口回读本项目来源、
Scene、最新回执并以 Project NOWAIT 独占锁覆盖验源到提交；并发改稿返回可重试冲突。
已采用的作者资产保留，不因来源修改硬删。作者入口可分页回看原提案、引文和复核问题，
未提交/来源失效显示历史状态，采用仍进入 World 的既有确认流程。


## 作者全景与细节台账（第三阶段验收中）

`ledger_contracts.py`、`ledger.py`、`discovery.py` 维护派生主题和不可变修订两表，
不成为新的 World/Story 正史。`GET /api/evolution/panorama` 按截止 Scene 展示作者状态，
对照前一场真实记录的前/后值；未知值不当作新增/消失。当前作者计划与排演另列。
条目列表/详情/历史/逐字来源 GET 和作者判断 POST 通过相同 owner/novel 非演示门。
instance 修正只适用确切 basis 记录，theme 扩大须作者确认；机器修订保留决定，不覆盖正文。

ReadingRequest 的 discover_details 显式开启；append/continue 沿原版本，旧客户端默认关闭。
发现与独立核对复用原 Scene 请求journal、项目账户snapshot、根预算及同事务receipt。
输入回读合法历史主题/原观察，并披露召回与部分覆盖；只放行该批实际收到的引用/目标。
无目标的待核实新主题携带独立资格及原证据，可由后续新证据沿原身份重新核对；
已有主题的不确定更新提案独立保存，不作为支持主题或原文证据回流。
同一动作按不可变发生区间锚定，不把观察谓词或抽取契约变化算成新发生；
回忆须绑定已给发生身份，不确定保持未知；追加引文不改变既定发生锚。
证据 purpose 区分所计实例与条件/背景支持；仅独立复核确认的实例增加次数，
正向发生、同条件例外和真正反证分别计数。历史缺少该资格时不据引文数补算发生。
不确定更新另存候选及精确 proposal_target，不替换原主题 head，不以支持主题回流；
作者可见复核结论/原因和此前获支持的理解。历史修订仍可回读。
复用SDK逐项隔离非法变化，剩余项继续严格schema与独立核对，隔离项和部分覆盖可见；
全部非法或无法恢复的输出错误不落派生结果；格式/schema错误且用量已知时整批隔离，
本场标部分检查并保留失败回执，可继续其它已验证资产；未知用量、权限、来源和其它故障
仍停止，禁止重发原请求。生成失败不空跑复核，复核失败不写该批，失败也占原根预算。
窄观察复用DeepSeek禁thinking模式；细节发现和独立复核复用已支持模型的max及393,216输出上限（含推理），模型质量仍须独立实测。
复用SDK完整响应的单括号确定性恢复，仅修格式、不改语义并留诊断，不再付费调用。
相同来源主题重抽时，变化的 dependencies/方法/review 追加资格修订并保留作者决定；
完整主题及精确复核目标带既有证据用途/锚，默认继承已认证旧用途；线索含义解释和相关
后续不同动作不成为原细节再次发生。新statement不能扩大原计数单位，明确兑现仍计入对应
承诺。用途分歧整项待核实，不剥源后保留声明。观察未覆盖提示不得与已抽取明确事实矛盾。
观察/发现/复核按整段原文区分说话人、回忆者和动作主体，叙述者资格说明不改成角色自述。
原文可明确识别的同一人物的原具体动作明确再现可在不同触发情境出现，确切物件同一性及机理未知
单列，不合并World资产、不从旧单次触发推出必要条件或普遍习惯；真实主体/动作歧义待核实。
清楚段落共指可还原人物原名但引用保留代词，不机械取最近名字、不将代词新造为人物；
World资产新候选不是文本主体未知。单次明确情境动作不须先证明习惯，可保留单次事实资格。
隐式 origin 匹配也遵守不确定候选隔离。来源抽取轮次数按截至所选修订的唯一 run/attempt
统计，作者判断和重复引用不增加次数。

EvolutionPanorama.vue 在Writing侧栏和Scene工作台使用表格、筛选、分页、来源和作者判断。
本机备份失败时全部待保存输入继续有离开保护、会话恢复与可复制文本；服务端回执成功后才
显示作品已保存。工程、模型开发/未使用验收和真实作者门禁分别评估，不能以新增UI核销长期R7。

同条件负向/不同选择实例使用 `exception_case`，与反驳原主张的 `counterevidence` 分开；
独立复核分别确认例外、反证及发生身份，正向/例外/反证数量分列。后来没做不否定过去一次动作。

发现复核按宿主显式change_index绑定每项，漏项不重排；分批主题摘要仅作路由。
同一主体同一细节的新含义、兑现和初始待核实主题续证优先沿旧主题，不能新增同义条目。
作者instance判断只约束其basis记录，不禁止后来独立实例增加主题发生数。

独立发现复核的 `occurrence_observation_ids` 认证实例身份，包含合法回忆与本轮明确重新认证的旧源，不表示新增次数；次数仍按发生身份去重。旧 unknown 仅在本批实际可见、复核 supported、发生模态及引文/来源引用一致时升级新修订，旧已知锚和历史不改。同观察已经定位时不再重复计为未知。`context_observation_ids` 明确复核背景用途，纠正新证据误标实例；不从 reason 自由文本推断，也不把真正身份未定的实例改成背景。相关物件保管不表示线索再次出现，为履约准备不表示兑现。全局 uncertain 不改已认证背景用途，作者决定仍独立保留。

发现主张和独立复核须覆盖每个新增断言，包括只补背景且发生数不变的状态。未描写、等候或相关对象未到不证明未履行，望向某处不证明身在该处；角色陈述模态仅承载实际说出的内容。缺少来源支持的推断仅作为竞争解释或待核实提案，不因背景用途、不增次数或保留竞争解释而取得 supported 资格。

主题身份与事件共指、模态、传闻真伪及机理独立；已确定同主体同细节的转述沿原主题。背景证据也须有原文关联，共场、缺描写或未说明关联不能形成关联；独立复核先核主题及逐条相关性，再核断言/模态/实例。conditions表示有来源的实质追踪条件，单次触发、体征及姿态保留context与竞争解释；更新保留原条件及情境差别，不任取交集制造例外，instance不禁止后续独立负样本。

演化项目采样器经既有snapshot facade设置900秒有限调用上限，保留固定provider、当前账户Key、原model；窄观察仍禁thinking，涉及多源身份/修订/实例绑定的细节发现及独立复核复用已支持模型的max思考与393,216输出上限（含推理）。非支持模型保持其原配置；不启用全client高质量模式。SDK仍受更短run deadline约束，失败关闭及未知用量不重发不变。该设置只缓解已证实180秒取消风险，不宣称修复连接读取失败或保证900秒足够。

绑定11接受 event_observed 观察的精确宿主自锚，效果与省略/空锚由宿主计算相同；只限实际输入中的该条观察，其他ID仍走旧主题同场同源重叠门，recall、context及主观模态不得借自锚绕过。supported的新背景用途须由结构化context名单认证，counter/context亦可由独立反证名单认证；缺一项整条隔离，不从reason猜测、不删源后保留statement。继承已认证证据/旧锚不重认证，uncertain仍独立候选。共指只识别所指对象，不能自动证明持有、归属、位置、知情或因果关系；协议与语义门分别验证。

发现复核四份认证名单只能引用本项选择的观察，以及身份/修订匹配的
`target_theme.evidence_observation_ids` 所列精确继承来源；全批其余对照只用于理由，
不能补入名单或改变证据绑定。目标描述从既有主题精确绑定名单摘取，不使用包含同场
额外观察的对照集合。资料未描写仅报告覆盖/待解，不能改读为世界状态未发生。

Scene World身份入口复用World已批准的类型归一，查询、候选和冻结查询采用同一canonical类型；
等价别名先去重。`人物/角色/character_ref`归为character，地点归为location，物品归为item，
物体归为object；物件及自定义类型仍保留，不跨类型复用。旧冻结查询与新范围不等时仍失败关闭，
不把旧付费结果重算为通过。事实性新增限定须由本项绑定引文支持，含时间、位置与情境，
复核不能把全批未绑定句子的真实内容当成本项已引用的证明。

已有主题条件集合变化时，发现复核须提供`conditions_review`专用资格：supported、非空且本项绑定/本批实际可见的来源，并解释原实质条件如何保留或有源重释。缺资格整项待处理，不从整体supported/自由reason放行、不自动合并条件或补源；new与条件未变不增加门。生成目标/修订只复制本批完整theme，历史review/作者basis及theme_index不是写入目标；主张采用最小充分绑定内容。合法recall认证当前回忆动作并绑定原锚，名单不是新增次数，回忆触发/见证陈述只作背景。新方法指纹保留旧运行与作者决定，旧未知用量不重发。

单次情境中的外部触发不因曾写入conditions就自动成为必要门槛。后续若以原/新两侧
原文明示的对照状态或约束重释旧条件，生成须显式修订、保留原情境，复核须走既有
conditions_review；未获资格仍整项待核，不任取共享词凑例外。转述优先原姓名/原引语，
性别代词只取本项绑定原句，不由姓名、旧摘要或后文补签。覆盖/待核说明也保留原叙述
资格，与已明确观察一致；缺完整主题/World未入库不等于文本主体歧义。无完整目标的批次
不输出其更新，仍如实说明本批未处理范围，不猜旧修订或填写空目标占位。

发现批次（含无旧主题的首次批次）、完整主题、路由索引与精确修订复核目标共享宿主
`conditions_semantics` 字段定义，并纳入方法指纹。它定义追踪维度而非替来源宣告条件无关。
首个单例优先原文明示可对照的基础状态/约束，不把整个初次情境拼为必要合取门槛；
具体触发、程度与伴随体征仍留原事实/context及竞争解释，原文或作者明示限制仍须保留。
已有条件重释继续经绑定两侧来源的 conditions_review，不自动删条件或补源。
当前观察引用要求逐条变化执行；合法空变化无需引文，仍返回 coverage 与 coverage_note 如实记录覆盖。

原段明确同主体且情境连续的条件与动作可分处相邻观察；发现须共同绑定条件context
与动作occurrence，人物动作不因涉及物件就改为clue。独立复核核类别及绑定，
不以未选择的相邻来源补签、不由共场臆造条件关联。

类别按主题所追踪单位核定：明示可对照条件中的人物动作不能被物件clue替代；
同段有独立外观/符号/现象来源的额外clue仍可保留。已承诺的履行/违背沿原commitment，
不因也是人物动作改类，各单位独立计数。

回忆没有本场新动作不等于已证明指定旧event同一，仅唯一已存候选不证明全文唯一。
缺唯一原锚指认时保留recall/null并由宿主列未知实例，不增已定位发生；可能另次旧event
属关键锚歧义，不能认证原锚后只写竞争解释。当前方法指纹还固定DeepSeek长结构步骤
采用SDK原生SSE聚合，完整结束原因与最终usage齐全才进入原JSON/schema链，断流未知、
禁传输重发；其他模型及短observer调用保持既有路径。


绑定12为本轮新增的specific旧锚recall引入`recall_identity_reviews`逐pair资格：匹配当前回忆
观察与精确旧occurrence，supported证书两侧须是本项已选/继承且本批实际可见；旧侧至少
包含该锚同用途/角色的原已定位event动作，新侧包含当前recall见证与指认context。
缺证书、重复、未确认或错误来源整项待核，不从reason推同一性或由宿主猜锚/改为unknown
来掩盖statement；无specific锚的recall/null仍未知且不增定位次数，继承已认证旧use不重要求。
复核target同时提供occurrences与旧用途以独立核pair，不把新句说无新动作当具体旧锚证明。
发现与复核仅对已支持DeepSeek使用已注册max思考/65,536输出上限（修复32,768全思考截断
的已证遗漏），仍不改变账户provider/model、预算请求数、免费恢复和未知不重发边界。
原文明确与动作相连的基础状态/约束进入追踪条件，外部触发不替代该状态；后续对照仍须
两侧来源专审，不默删原实质限制，不把条件维度当必要/充分或习惯。


绑定13额外保存宿主来源`occurrence_origin`（原提议类型）；继承unknown自动升级为event
仅允许原提议event且原引用/模态/本批可见/结构化认证均合格。未知回忆及旧无来源类型
的unknown不能仅靠正向名单变成新的物理发生，旧已认证known不重认证。后续显式重选
历史unknown recall可用双侧pair证书及本轮新增绑定指认context续证，原head不回算，
按同observation已证链接消未知，不增加旧物理发生；无本轮指认来源仍整项待核。


绑定14阻止已存回忆用途来源被模型重选为event产生新的物理锚；同主题回忆原观察/
相同引文与source_ref的重选仅能保留回忆/背景，合法链接续证仍经双侧pair证书。
question即使复核确认“问题有依据”，仍另存绑定原主题/修订的提案，不替换既有
已支持head或作者决定；这不是确认问题已有答案。所有proposal_target从自动支持
主题召回排除，初始无target uncertain仍可沿原ID在新来源中续证；详情保留原支持理解。
路由prior_review仅带verdict，不复制旧机器自由理由自证；完整主张、条件、作者决定、
原始观察/引用/用途与已知发生锚仍提供，未缩短历史窗口或删证据。
