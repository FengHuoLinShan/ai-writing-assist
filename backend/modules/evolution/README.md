# Evolution 演化系统

V4 长期计划（`docs/plans/novelcraft-v4/plans/01-EVOLUTION.md`）的演化引擎模块。
含 E01 契约层（来源引用、观察外壳、身份解析、类型化状态操作、运行回执）、
稳定观察身份推导，及 E02–E09 的提交协议、持久化、编排、失效传播、迁移切换
与生产 LLM 采样接线。替代而非并存旧 deep_import 编排（E07 切换前禁止双写，
当前无生产流量）。

## 职责边界

- 来源身份：`SourceRevisionRef`（章节序号不独自承担来源身份；
  range_hash 由 content_hash + 偏移确定性推导）。场景步的来源绑定
  （`pipeline.SceneSourceBinding`）锚定真实 Writing 草稿：指纹来自数据库，
  采样文本必须与绑定草稿逐字一致，提交时再经同一来源重验——来源漂移
  即整批作废，不消费旧冻结。
- 观察：`ObservationEnvelope`（modality 区分事件/陈述/信念/假设/规划/比喻/不明；
  未解析提及保留 mention 身份，禁止伪造实体 UUID）。模型只输出表面名；
  提及身份由宿主按观察身份派生（`observations.derive_mention_id`），
  编译后观察（含解析结论）随冻结负载持久化。
- 身份解析：`IdentityResolution`（reuse/new_candidate/ambiguous/unrelated；
  身份去重与观察积累分离）。E02 确定性裁决内核——仅精确名称/别名证据自动
  reuse，相似度阈值永不自动合并已采用对象；同名多候选保持竞争（ambiguous）；
  观察者自带实体绑定必须经精确证据重验，不支持则 unrelated。生产候选召回
  经 world facade 精确名解析（`pipeline.exact_name_candidate_lookup`）。
- 状态操作一致性门：模型提议的 scene_events 凡引用具体实体，该实体必须经
  观察与身份解析实际支持（reuse）；未支持的提议保持待处理
  （pending_decisions），不因模型单方面声称而写入。
- 回执与游标：`EvolutionReceipt`（failed/blocked/unknown_billing 禁止推进
  committed_prefix——游标只在领域提交成功后推进）；paid_call_receipts 携带
  provider/model/usage 计量供费用审计。

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
  provider 采样（事务边界之外，async sampler）→ 观察/身份/一致性门 →
  冻结（单独持久化）→ 窄提交（真实来源重验））。域提交失败回滚不抹掉预算
  预留与冻结负载；`pipeline.recover_scene_step` 与任务 handler 的恢复优先
  重放（已提交→原回执幂等重放；已冻结→免采样重提交）。采样器经
  `sampler.resolve_scene_sampler` 以 async context manager 持有（客户端
  生命周期成对）。`consumers.check_suggestion_validity`（T17 建议有效资格
  按索引指纹；无声称或无已索引指纹时 unknown，不宣称一致）；story 侧只读
  在场投影 `project_scene_presence`（T03 未知路线不造真）。
  端到端验证：`tests/test_g2_vertical_slice.py` 为**确定性夹具下的
  存储/投影集成切片**（provider、人物候选与场景事件来自固定夹具）；
  `tests/test_review_remediation.py` 覆盖评审返修的关键行为（真实链路
  观察-only sampler、故障注入、屏障顺序、单写者重入、计量回执）；
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
