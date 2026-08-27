# ADR-0017 — 世界事实权威、不可变断言与 CanonRevision

- **状态**: Accepted / Phase 0 implemented
- **日期**: 2026-08-27
- **关联 Spec**:
  [`2026-08-27-world-authority-phase0-spec.md`](../superpowers/specs/2026-08-27-world-authority-phase0-spec.md)
- **研究依据**:
  [`world-object-worldbook-unification-research.md`](../references/world-object-worldbook-unification-research.md)

## 背景

当前 `world` 用 `CoreEntity`、Profile、`EntityRelation`、Event、World Bible 页面及各自状态
表达作者已采用内容。它们足以支撑现有编辑、检索和生成，但不能唯一回答以下问题：

- 某一历史时点究竟选择了哪些正文版本和结构化断言；
- AI 候选的哪一个精确快照、哪一部分经谁授权进入了正典；
- 页面发布、结构化字段和关系边发生分歧时，WorldEval 应读取哪一个权威来源；
- 一个关系 family 切换到形式求值后，如何避免继续从 legacy current row 回退读取。

直接建立通用 Card、KnowledgeResource、ResourceRevision、Statement 或 receipt 表，会复制已有
专用资产生命周期。长期双写 legacy 行与新断言也会制造第二个事实源。

## 提议决策

### 1. 正典作用域与历史

- 正典作用域固定为 `novel_id`；v1 不提供命名 branch、merge 或多父历史。
- 每个作者项目拥有一个空的 `C0`、一个 mutable CAS head，以及单父、不可变、追加式的
  `CanonRevision` 历史。
- 每个 `CanonRevision` 在逻辑上保存完整 manifest。物理 delta 仅在能够沿单父链唯一还原
  完整 manifest 时允许。
- 回退历史不是移动 head，而是追加一个新 revision。family cutover 后，不能恢复会令
  `canon-owned` family 回到 legacy authority 的旧 manifest。

### 2. 最小新增数据

`world` 继续拥有世界事实权威，只新增：

- `world_assertions`：不可变、自包含、带正负极性和时间范围的受限断言；
- `world_canon_revisions`：完整 manifest 与唯一内联 admission receipt；
- `world_canon_heads`：每个 `novel_id` 唯一的 current CAS 指针；
- `entity_profile_template_revisions`：为现有 Profile Template 补齐不可变 Schema carrier。

不新增顶级 knowledge/canon 模块，也不新增通用 Card、KnowledgeResource、ResourceRevision、
Statement、receipt 或 authorization-policy 表。资源继续由现有专用 head/revision 承载。

### 3. 封闭资源与断言语言

- 只有版本化 resolver catalog 明确列出的资源和 selector 可以进入 Canon manifest、引用或
  documentary source；unknown kind/version、`latest` 和任意 JSON path 失败关闭。
- 第一批 catalog 只包含 World Bible PageRevision 与 EntityProfileTemplateRevision。
  CoreEntity 继续作为 Referent；mutable Profile、Relation、Event、Suggestion 和 cache 不直接
  充当 ResourceRevision。
- v1 Statement 只包含名称、有限 typed scalar 和二元关系。任意 predicate、程序、递归规则、
  belief、惯性与事件演算后置。
- StatementClaimRef 若出现，必须内联完整 claim（regime、polarity、StatementValue 和
  TimeScope）；claim digest 是该完整值的规范哈希，不自包含在被哈希的 claim 内。v1
  没有启用对应 statement kind 时仍拒绝准入。

### 4. 唯一准入事务与授权

- 只有 `Admit` 可以同时创建 Assert、CanonRevision、receipt 并推进 head；不提供通用
  “直接创建 canonical assertion”接口。
- Preview validation 不产生权威。Admit 将 mutable candidate 的精确快照和作者选择封入
  `AdmissionInputValue`，在同一事务中重新验证；任一 include 无效则全批无写入。
- receipt 区分 authorizer 与 executor。普通 authorizer 只能是当前项目 owner 的
  `AccountPrincipal.account_id`；AI、parser、worker 和 validation result 不能成为 authorizer。
- executor 使用现有账户请求或 `task_id + task_type + attempt + lease_id` 标识，不建立 worker
  身份系统。授权政策来自代码内封闭、版本化 registry；World Validation Policy 不是授权政策。
- 同一 decision ID 与 digest 重试返回原 CanonRevision；同 ID 不同 digest 拒绝。head CAS
  失败不得自动 rebase。

### 5. family 权威切换

- family 按 `name → typed_scalar → binary_relation → event_time → belief` 分期切换。
- v1 只允许 `formal-disabled → canon-owned`。每次 cutover 必须同时切换 canonical write seam
  和 read evaluator，且明确 legacy 字段此后的 draft/projection/retirement 角色。
- World Bible 页面保持 ADR-0006 的 B-default：发布正文具有 documentary canon 效力，但不会
  自动提升为 WorldEval 事实。正文事实 promotion 必须是同次 Admit 中的显式独立动作。

## 与既有 ADR 的关系

- ADR-0006 继续约束“资料归 world、激活归 evidence”；本提议只增加精确 PageRevision 选择，
  不让页面字段控制 Prompt 或自动成为事实。
- ADR-0015 的模块融合、稳定 seam 和“不建通用 revision 框架”保持不变。
- ADR-0016 的 validation receipt 仍只证明校验输入与结果；它不能替代 Canon admission receipt。
  Adoption Package 在后续 phase 通过唯一 Admit 写入，不再平行直写 formal authority。

## 后果

- 目标画像是长期创作作者。用户界面仍使用“已发布 / 已采用 / 历史 / 冲突”，不暴露
  Assert、CanonRevision、manifest、receipt 或证明内部术语。
- Phase 1 的“人物与世界”统一卡片主页可以先做 read model，不依赖本 ADR 落地。
- Phase 0 已实现封闭 wire、精确 resolver、C0/head、内联 receipt 回放、追加式
  Preview/Admit/Revert 与 World Bible PageRevision 选择。
- 所有 formal family 仍为 `formal-disabled`；Assert 准入、task-attempt 执行、family cutover、
  查询推理和统一卡片 UI 仍需后续独立实现与门禁。

## 拒绝方案

### A. 建立通用知识资源与版本总表

拒绝。现有专用 revision 已拥有不同生命周期；总表只会增加同步和删除语义。

### B. 继续把 `status=canonical` 当统一正典

拒绝。它不能冻结跨资源历史，也无法在 family cutover 后提供唯一 evaluator owner。

### C. 用事件日志重放全部正典

拒绝。当前需要的是可直接验证的完整选择快照；通用事件溯源扩大恢复和兼容面。

### D. 让 AI 或 worker 直接成为 authorizer

拒绝。执行自动化可以执行已持久化的人类授权，但不能创造授权。
