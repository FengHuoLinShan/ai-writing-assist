# ADR-0017 — 世界事实权威、不可变断言与统一 Card

- **状态**: Accepted / v1 implemented
- **日期**: 2026-08-27
- **决策来源**: 用户确认依据 `docs/references/world-object-worldbook-unification-research.md`
  重构世界书、世界对象和相应上下文
- **实施合同**: `docs/superpowers/specs/2026-08-27-world-authority-phase-0.md`
- **修订**: ADR-0006 的“页面不是事实源”边界；交叉引用 ADR-0015、ADR-0016

## 背景

当前 `CoreEntity`、Profile、`EntityRelation` 和 World Bible 页面分别承担身份、结构化资料、
关系和作者手册，但 `status="canonical"`、published head 与 adoption 状态无法固定一个可重放的
历史正典，也不能原子选择跨资源事实。前端又把“人物与设定”和“世界笔记”作为两套入口，
让作者先理解内部载体，才能完成同一项“找回并维护世界资料”的任务。

统一作者体验不能靠新增通用 `cards` 表或让页面正文变成第二套事实源。Card 是 Page、Entity
等既有资产的 tagged read model；世界事实权威则需要与可编辑 head 分开的不可变输入和一次
作者准入。

## 决策

### 1. 唯一作用域与模块所有权

- `novel_id` 是 Assert、CanonRevision、Canon head、Schema/policy 选择、receipt、引用解析和
  evaluator 的唯一正典作用域；`projects.id` 只是该键的当前物理载体。
- `world` 拥有不可变 Assert、CanonRevision、head CAS、资源准入和确定性 evaluator；不新增
  顶级 knowledge/canon 模块。
- `evidence/compilation` 继续拥有检索、可见性、预算、confirmation、snapshot 和 Activation
  Profile。它不得读取 world ORM，只经 world facade 获取固定 Canon 的事实上下文和文档资料。
- `story` 的 Scene/MemoryEvent 在 event/time family cutover 前不进入 formal WorldEval。

### 2. Card 统一体验，不统一持久化生命周期

- “人物与世界”默认主页使用封闭 Page/Entity tagged Card read model；Card 本身不持久化。
- Page 保留工作稿、发布、revision 和投影；Entity 保留身份、Profile、关系和专用历史。
- Page 与 Entity 的编辑深链继续有效。普通界面只展示作者语言，不展示 raw JSON、内部状态、
  proof 或 Canon 实现字段。
- generic blank 后续默认创建 resource-only 页面；只有显式 entity-bearing 操作才创建或链接
  `CoreEntity`。页面标题不自动成为 Referent Name。

### 3. 页面发布与世界事实永久分离

- ADR-0006 的默认 B/evidence-only 语义保留：页面正文可成为正式文档资料，但不自动创建世界
  Assert。
- Phase 1 沿用当前发布流程，不把 published 状态称为 formal DocCanon。
- Canon 基座启用后，发布必须封存 exact `WorldBiblePageRevision`，并在同一事务创建选择该
  revision 的新 CanonRevision、receipt 和 head CAS。事实 promotion 必须是同一提交中的显式
  独立选择。
- 未来若允许受控正文直接拥有某个事实 family，必须另行修订本 ADR，且只影响新的
  CanonRevision；旧版本永不被新 evaluator 追溯重解释。

### 4. 最小持久化新增

只新增：

1. `world_assertions`：不可变、带 `novel_id` 的有限 StatementValue、world/belief regime、
   正负 polarity、exact Schema、TimeScope、exact source revision、有限 hard grounds、cite、
   audit-only provenance actor 和内容 hash。
2. `world_canon_revisions`：不可变、单父、完整 manifest、manifest digest，以及内联不可变
   admission receipt。
3. `world_canon_heads`：每个 `novel_id` 一个 mutable CAS 指针；head 只前进到当前 head 的新
   直接子。
4. `entity_profile_template_revisions`：typed custom Schema 开工前，为现有 template head 提供
   exact immutable revision。

不新增通用 `cards`、`knowledge_resources`、`resource_revisions`、Statement 表、
AuthorityTransaction、动态类型表、通用事件总线或长期双写。

### 5. C0、历史与回滚

- 每部新旧作者小说建立一个 empty C0。C0 固定 v1 kernel、BaseSchema 和授权 policy，不选择
  legacy Assert，也不把旧 `canonical`/published 状态自动提升为 formal authority。
- 旧小说初始化从 C0 追加 C1，并要求作者确认 exact subset。
- v1 CanonRevision parent 为 `0..1`；历史浏览不移动 head。回滚只能以当前 head 为父追加
  revert CanonRevision，不允许 head 后退、多 head、多父或 merge。
- 历史查询验证提交时 receipt；当前权限只决定现在谁能读，不回写历史准入结论。

### 6. 唯一采用状态机与原子写入

```text
draft/candidate -> seal immutable revision -> validate -> explicit author admission
  -> Assert(s) + CanonRevision + receipt + head CAS
```

- validator、parser 和 AI 只能产生 sealed candidate；不得创建 Assert、移动 head或成为
  authoritative hard ground。
- Adoption Package 是默认 B promotion 的唯一批量 seam。成员集合必须 exact；任一成员失效
  则整批无写入，作者可重新确认一个 exact subset。
- 每个 fact family 的 cutover 同时固定 mutable authoring carrier、唯一 canonical write seam、
  canonical read projection 和 legacy 字段剩余用途。切换后 evaluator 不得 fallback legacy
  current value，也不得异步双写。
- family 顺序固定为 Name → custom typed fields → relation → event/time → belief。

### 7. 查询与执行完整性

- Ask World 保留 evidence/RAG 的资料回答语义；formal query 使用独立接口。
- formal query 返回 verdict、CanonRevision 和作者可读来源摘要；高级诊断才展开 direct
  authority 与 `S/F/I/X`。
- `X` 必须区分 complete、budget-truncated、unsupported family 和 invalid context；不得把
  预算截断伪装成 unknown 或 false。

## 安全与兼容

- 所有公开路径继续执行当前 account principal、owner、active project 与 `novel_id` 门禁；
  body/query 中的 `novel_id` 只是目标，owner 不由调用方指定。
- manifest、source、hard-ground、Schema 和 policy 中的每个引用都必须解析为同小说的 exact
  immutable revision；unknown kind/version、latest/head、mutable row 和跨小说引用 fail closed。
- Phase 1 不改 DB、旧 API 或对象/页面编辑 wire。后续 Phase 每次公共 contract 变化都必须有
  migration、OpenAPI contract test、回放/原子性测试和文档同步。

## 分阶段实施

1. Phase 0：由关联 Spec 固定 P0 wire、约束、resolver、receipt、状态机和反例测试。
2. Phase 1：交付默认“人物与世界”主页、Page/Entity Card、筛选、草稿恢复、失败态、390px
   和旧深链兼容；无 DB 变更。
3. Phase 2+：只有 Phase 0 没有多解且对应反例成为可运行测试后，才按 Name-first 顺序建设
   Canon 基座、family cutover、formal query、导入采用与 context 切换。

v1 实施已完成上述顺序：Name canonical write seam、exact Profile Schema revision、
typed scalar/binary relation B promotion、Adoption Package formal subset、formal query 和
Evidence/Writing/地图册 C-pinned context 均已启用。`working`/待处理视图仍走旧投影。
A 型正文 owner、同包 local-ref promotion、event/time 求值与 belief 不在 v1 中，保持
`unsupported-family`/validation fail-closed，不为它们预建空抽象。

## 结果与拒绝方案

- 作者先看到统一的世界资料卡片，仍可在需要时进入专用编辑器；复杂权威与证明信息不进入
  主路径。该体验价值面向画像 A，目前仍是产品假设，需用首次价值时间、找回资料耗时、
  草稿恢复和重复使用验证。
- 拒绝“把 World Bible 页面直接当全部事实源”：它会让人物话语、传闻和说明文字静默改变
  正史。
- 拒绝“只靠 status 拼正典”：mutable 行会使旧答案漂移，跨资源采用也没有原子边界。
- 拒绝通用 Card/KR/RR 表和长期 legacy/Canon 双写：既有专用历史语义更准确，双写会形成
  第二真相源。
