# Evolution 演化系统

V4 长期计划（`docs/plans/novelcraft-v4/plans/01-EVOLUTION.md`）的演化引擎模块。
含 E01 契约层（来源引用、观察外壳、身份解析、类型化状态操作、运行回执）、
稳定观察身份推导，及 E02–E09 的提交协议、持久化、编排、失效传播、迁移切换
与生产 LLM 采样接线。替代而非并存旧 deep_import 编排（E07 切换前禁止双写，
当前无生产流量）。

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
  已登记缺口：跨章 Scene 需多区间绑定契约，尚未支持。
- 前序认知（A04）：`store.load_prior_observations` 覆盖最近
  `PRIOR_OBSERVATION_WINDOW` 个已提交 Scene 的**结构化**观察（modality、
  主体表面名、观察身份、来源 Scene），不再压成裸谓词——传闻在下一
  Scene 的输入里仍是传闻；Prompt 按 modality 分级渲染并显式披露截断
  （scenes_included / total_committed_scenes / omitted_observations，
  未注入不等于不存在）。完整历史认知/持久知识查询仍属后续里程碑。
- 观察：`ObservationEnvelope`（modality 区分事件/陈述/信念/假设/规划/比喻/不明；
  未解析提及保留 mention 身份，禁止伪造实体 UUID）。模型只输出表面名；
  提及身份由宿主按观察身份派生（`observations.derive_mention_id`），
  编译后观察（含解析结论）随冻结负载持久化。
- 身份解析：`IdentityResolution`（reuse/new_candidate/ambiguous/unrelated；
  身份去重与观察积累分离）。E02 确定性裁决内核——仅精确名称/别名证据自动
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
  宿主派生 `source_observation_ids` 与 `authority_basis` 证据链。
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
  预算条件 UPDATE 原子预留，仅 active run 可扣减）。E07.c 单写者是数据库级
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
  先行耐久化→ 观察/身份/语义门确定性编译 → 编译冻结 → 窄提交（真实来源
  重验））。冻结负载按阶段推进 `sampling → sampled → compiled`（A07）：
  attempt 身份与预算关系在请求发出**之前**落库；provider 结果在任何领域
  推导之前落库；观察编译是纯确定性推导，恢复可在 sampled 阶段负载上重跑
  而不接触 provider。域提交失败回滚不抹掉预算预留与冻结负载；
  `pipeline.recover_scene_step` 与任务 handler 的恢复优先重放（已提交→
  **任意已提交 Scene** 按稳定请求身份（`compute_scene_manifest_hash`：
  run/scene/正文/整稿版本/区间）幂等重放原回执，不重采样不扣费；修订
  请求指纹不同不套用旧回执（A08）；compiled→免采样重提交；sampled→
  确定性重编译后提交；sampling/failed→`SamplePendingReconciliationError`
  待核对——请求已发起或已失败、费用可能已发生，不得自动重采样，对账后
  登记新 run 重来）。
- 执行模式进入冻结/提交协议（A01）：影子 run 的冻结负载盖章
  `execution_mode=shadow`；首次执行与恢复经同一写入策略解析
  （`_resolve_step_applier`：run 登记模式或负载盖章任一为 shadow 即强制
  隔离 applier，不信任调用方传入的正式写入器，未盖章的既有负载按 run
  登记模式兜底）；提交边界 `apply_frozen` 拒绝影子负载经未标记
  `shadow_isolated` 的 applier 写入（纵深防御）。预算单位说明：budget 以
  Scene 步为准入控制单位（一步一次结构化采样，内部修复尝试不另计），
  实际计费以回执 paid_call_receipts 为准，二者不互为证明。
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
  并发门禁。完整 G2（持续认知闭环、真实模型质量、独立 case 经 Evidence
  消费）在后续里程碑验收。

## 测试

`tests/`：契约语义、稳定观察身份、身份解析、窄提交协议、编排与预算、
失效传播、迁移切换、G2 夹具切片与评审返修行为；真实 PG 并发在
`tests/e2e/`（`RUN_E2E_TESTS=1` + 专用库）。

E09 长书规模验证（真实叙事语料 × 真实 handler × shadow 链 × 退出标准
断言）用 `tools/evolution_scale_harness.py`（专用库；`--sampler real`
经账户连接真实模型，另行授权）。
