# Evolution 演化系统

V4 长期计划（`docs/plans/novelcraft-v4/plans/01-EVOLUTION.md`）的演化引擎模块。
当前仅含 E01 契约层：来源引用、观察外壳、身份解析、类型化状态操作与运行回执，
以及稳定观察身份推导。无 ORM、无 API、无编排——接入按 E02–E08 的
owner epoch、窄事务与影子运行规则逐步落地，替代而非并存旧 deep_import 编排。

## 职责边界

- 来源身份：`SourceRevisionRef`（章节序号不独自承担来源身份；
  range_hash 由 content_hash + 偏移确定性推导）。
- 观察：`ObservationEnvelope`（modality 区分事件/陈述/信念/假设/规划/比喻/不明；
  未解析提及保留 mention 身份，禁止伪造实体 UUID）。
- 身份解析：`IdentityResolution`（reuse/new_candidate/ambiguous/unrelated；
  身份去重与观察积累分离）。
- 状态操作：`TypedStateOperation`（observe/move 分离；knowledge 必须指明主体；
  `documentary_assertion` 不改变核心状态）。
- 回执与游标：`EvolutionReceipt`（failed/blocked/unknown_billing 禁止推进
  committed_prefix——游标只在领域提交成功后推进）。
- 身份解析（E02，`identity.py`）：确定性裁决内核——仅精确名称/别名证据自动
  reuse，相似度阈值永不自动合并已采用对象；同名多候选保持竞争（ambiguous）；
  观察者自带实体绑定必须经精确证据重验，不支持则 unrelated。观察积累与身份
  解析分离：解析结论不改 observation_id、不吞观察。候选召回经
  `IdentityCandidatePort` 注入，world 侧用 `facade.find_similar_entities` 做
  结构适配。

- 窄提交（E03c，`commit.py`）：prepare 阶段 `freeze_attempt` 先持久化冻结
  负载（T10 恢复基础）；`apply_frozen` 短事务内依次重验 owner epoch（T12
  前置）→ 来源 manifest → 父回执身份与前缀，再执行注入的领域 applier 并
  保存回执——游标只在回执持久化后推进；同 attempt 重入直接重放原回执
  （T11：不重复领域写入）。`recover_attempt` 复用冻结负载重验重提交，
  全程不接触 provider。存储经 `AttemptStore` port 注入（生产 PG 实现随
  E04/E07 接线）。

## 测试

`tests/`：契约校验语义与稳定观察身份（重排不变、同断言去重、
来源/方法变化换代）。
