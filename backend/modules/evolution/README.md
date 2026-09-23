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

- 持久化与编排（E04）：三张表（run 注册表 / 冻结尝试 / 回执）+ Alembic
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
世界抽取若收到用量完整的格式/schema/截断失败，冻结失败调用回执并将本场
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
