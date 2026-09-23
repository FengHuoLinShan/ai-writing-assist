# Module: evolution / 演化系统模块

V4 长期计划（`docs/plans/novelcraft-v4/plans/01-EVOLUTION.md`）的演化引擎：
"读取正文 → 观察 → 身份解析 → 状态解释 → 校验 → 窄批次提交"的运行所有权。
当前状态：**E01 契约层**——仅提供稳定类型契约与稳定观察身份推导，
无 ORM、无 API、无编排、无迁移。E02–E08 按 owner epoch、影子运行与
退役清单逐步接入；接入前后 deep_import 仍是唯一编排 owner，禁止双写。

## 契约层（`contracts.py` / `observations.py`）

- `SourceRevisionRef`：不可变来源引用。range_hash 由 content_hash + 偏移确定性
  推导；章节序号只用于展示排序，来源身份由 draft/content_hash/revision 承担——
  同字数替换、复制、恢复旧稿都产生可识别变化。
- `ObservationEnvelope`：原文观察外壳。modality 区分观察到的事件、角色陈述、
  信念、假设、作者规划、比喻与非字面、不明确；逐字证据必须携带自己的来源范围；
  未解析提及保留 `MentionRef` 身份并记录原因，禁止为凑 schema 伪造实体 UUID。
- `IdentityResolution`：reuse / new_candidate / ambiguous / unrelated 四态；
  reuse 必须带候选证据，ambiguous 必须有两个以上候选。身份去重与观察积累分离
  ——命中已有身份不跳过新观察。
- `TypedStateOperation`：类型化状态操作。location.observe 与 location.move 分离
  （后者需移动证据）；knowledge.* 必须指明认知主体；`documentary_assertion`
  承载尚不能安全投影的观察且不改变核心状态；前值未知允许 before 为空（assert
  语义），不得伪造前值。
- `EvolutionReceipt` + `CommittedPrefix`：跨模块交接回执与已提交前缀游标。
  failed / blocked / unknown_billing 的回执 committed_prefix 必须等于前值且
  不得倒退——游标只在领域提交成功后推进；coverage 按 inspected / not_run /
  unknown / excluded / stale / unsupported 分列，局部完成不折叠成全量完成。
- 稳定观察身份（`derive_observation_id`）：来源范围 + 观察语义 + 契约版本的
  sha256，不含输出位置与 run id——批次重排/合并不重建身份（T06），另一 run
  同断言去重，契约版本提升产生新一代观察并保留旧身份可对照。

- 窄提交协调器（E03c，`commit.py`）：freeze → apply 两段协议。模型返回后
  先冻结负载；apply 短事务内重验 owner epoch、来源 manifest 与父回执，
  任一漂移抛 `CommitConflictError` 作废重准备；领域写入由注入 applier 完成，
  回执持久化后游标才推进；同 attempt 重入重放原回执不重复写入（T10/T11
  故障注入测试覆盖：持久化失败复用冻结不重采样、响应丢失重放原回执）。
  存储经 `AttemptStore` port 注入，生产 PG 实现随 E04/E07 接线。

- 持久化与编排（E04，`models.py` / `store.py` / `orchestrator.py`）：
  `evolution_runs`（owner epoch、已提交前缀游标、根预算）、
  `evolution_frozen_attempts`、`evolution_receipts` 三表与 Alembic 迁移
  `20260921_evolution_tables`；`PostgresAttemptStore` 绑定 `(db, novel_id)`
  作用域实现 AttemptStore 协议——回执落库同事务推进游标与 head（不可改写），
  `reserve_budget` 条件 UPDATE 原子预留（T21 不透支）。编排内核：
  `prepare_scene_input` 前序屏障（T07：Scene N+1 输入实际包含 Scene N 的
  已提交回执；前序未提交显式 blocked，不携带假结论）；前序状态内容为
  **结构化观察**（A04，2026-09-22 审查）：覆盖最近
  `PRIOR_OBSERVATION_WINDOW` 个已提交 Scene，保留 modality/主体/来源
  Scene——传闻在下一 Scene 输入里仍是传闻，窗口与截断在
  `previous_observations_coverage` 显式披露（未注入不等于不存在）；
  `plan_parallel_batches`
  确定性准入（同 Scene 依赖键不相交可并行；键冲突或叙事顺序强制分批，
  不采信模型自称可并行）。当前无生产写入方，deep_import 仍是唯一编排
  owner；E07 切换前禁止双写。

- 失效传播（E05，`invalidation.py`）：`compute_source_change` 物理差异
  （同字数替换也给出非空受影响窗口，T08）；`apply_source_invalidation`
  传播正文变更——证据索引换源重建（旧结果不再显示有效）+ Scene 派生投影
  软 supersede（保守扩大到受影响章锚定的最早 Scene 起，范围记入回执）；
  `apply_scene_reorder_invalidation` 处理场景重排（事件序号对齐 + 从最早
  移动 Scene 起失效）。失效不删历史：作者确认与已提交回执保留。未接线
  消费者（world 知识/地图册/助手建议）在回执显式列为 unsupported，不以
  局部完成冒充全量失效（G2/V/R 系列接线）。

- 场景步管线（G2，`pipeline.py`）：`run_scene_step` 按 §4.1 顺序组合——
  前序屏障（T07）→ 预算原子预留（T21，先预留再采样）→ provider 采样
  （sampler 注入，事务外；生产接项目 LLM 入口）→ 稳定观察 → E02 身份
  解析 → 冻结（T10）→ 窄提交（E03c/E04）。来源绑定（A02，2026-09-22
  审查）携带草稿内码点区间：整稿指纹与 Scene 区间分别验证，服务端按
  权威草稿切片逐字比对 scene_text——同一章可分多 Scene；观察偏移映射
  回草稿绝对空间（分段变化不复用旧观察身份）；跨章 Scene 需多区间
  绑定契约，为已登记缺口。解析结论与观察 ID 进入冻结
  负载可审计。不注册 async_tasks handler——deep_import 仍是唯一编排
  owner（计划 N03 禁双写），E07 切换期由新 handler 调用本组合函数。
- 建议有效性缝（G2，`consumers.py`）：`check_suggestion_validity` 按证据
  索引指纹判定（T17）——新来源已请求未重建、或声称指纹与当前索引不符
  即失效；来源一致才保持有效资格；无状态返回 unknown。失效回执已把
  assistant_suggestion_validity 列为接线消费者。
- 在场投影（G2，story/continuity/presence.py，经 story facade
  `project_scene_presence` 导出）：从已提交事件推导 confirmed_in_scene /
  last_observed 与路线段——仅当后一事件自带移动来源证据才标 traveled，
  否则 unknown（T03：不造路程/方式/时间）。只读 DTO，不占地图几何。

- 恢复与 fencing（E06，`recovery.py`）：`replay_committed_prefix`
  键集分页有界重放已提交回执链（链缺口 fail-closed、检查点信任锚跳过
  早期页）；`verify_run_checkpoint` 校验游标与 head 一致性并执行恢复期
  owner fence；`store.save_receipt` 以 epoch 条件更新完成 T12 完整
  fencing（旧 worker 回执在持久化边界被拒，游标不动）。性能测量工具
  `tools/evolution_checkpoint_bench.py` 与 1k/5k/10k 档位结果见
  `docs/plans/novelcraft-v4/e06/E06-恢复与性能测量.md`。

- 迁移切换（E07，`compat.py` / `sampler.py` / `tasks.py` / `legacy_adapter.py`）：
  影子运行 `execution_mode=shadow`（迁移 `20260921_evolution_shadow`）——
  执行模式盖章进冻结负载，首次执行与恢复经同一写入策略解析强制替换为
  隔离 applier（即使调用方传入会写正式表的 applier），提交边界
  `apply_frozen` 亦拒绝影子负载的正式领域写（2026-09-22 审查 A01），不
  产生第二套有效事实，影子回执留在 evolution 自己的表里供对比；项目级
  单 live 写入者门禁（`register_run` 拒绝第二个 active live run）；
  `switch_project_engine` 排空旧 owner 并推进 epoch（在途旧 worker 在
  持久化边界被 fence）；在途兼容分类（冻结契约 → 续接，未知 → 保留费用
  从可验证批次继续）；`evolution_scene_step` async_tasks handler 走真实
  路径（采样器未接线 fail-closed 拒伪造，生产 LLM 接线属 E09；请求可带
  章稿内码点区间，scene_id 与章号经 outline_state 权威校验——A02；恢复
  优先含**任意已提交 Scene** 的幂等重放，按稳定请求身份
  `compute_scene_manifest_hash`（run/scene/正文/整稿版本/区间）判定，
  同请求重试拿原回执不重采样不扣费，修订请求指纹不同不套用旧回执
  ——A08）；deep_import
  入口适配层返回真实新回执形状 + deprecation 提示（实际路由重定向待
  canary）。E08 退役登记表见
  `docs/plans/novelcraft-v4/e08/E08-退役登记表.md`（核销条件满足前不删码）。

- 生产采样器（E09 第一步，`llm_sampler.py`）：``ProjectLLMSampler`` 经
  ``open_project_llm_client`` 使用项目 owner 账户连接；输出为 Pydantic
  schema 化窄观察（modality 七态/提及禁造 UUID/引用必须来自原文，校验
  失败即失败；scene_events 状态提议须引用本批观察序号 `source_observation_indices`
  作证据，knowledge 提议须带 `knowledge_subject`——经 `state_gate.py`
  语义门验证，2026-09-22 审查 A03）；Prompt 确定性注入正文与前序已提交
  回执身份（T07 注入面）；每次调用记录 paid_call_receipt 进入冻结负载可
  审计（任一尝试用量未知则总量 None + `usage_complete`/`unknown_attempts`
  显式留痕；最终失败也固化 failed_final 回执——A06/A07）。生产 provider
  ``project_llm`` 已注册到采样器注册表；真实模型验收单独授权执行，
  单元验证用冻结 fixture 客户端（不联网）。

## 测试

`modules/evolution/tests/`：契约校验语义（含游标纪律）与稳定身份性质。
