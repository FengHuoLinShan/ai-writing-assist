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

## 测试

`modules/evolution/tests/`：契约校验语义（含游标纪律）与稳定身份性质。
