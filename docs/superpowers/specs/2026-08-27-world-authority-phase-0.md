# World Authority Phase 0 实施合同

> 状态：Accepted / v1 implemented。本文固定 Phase 2+ 的唯一实现合同。
> 关联 ADR：[`ADR-0017`](../../adr/0017-world-authority-and-unified-cards.md)。

## 1. 范围与验收顺序

本合同将世界对象—世界书研究收敛为可执行的 DB、wire、状态机和失败语义。只有本文件列出的
P0 反例获得测试后，才能创建 Canon 基座或切换任何 fact family。

Phase 1 目标画像是长期维护小说世界的作者（画像 A）：默认入口用 Page/Entity 混合 Card
缩短找回资料路径；旧对象/页面深链不丢目标；空态、加载失败、筛选、工作稿恢复和 390px
属于验收。Card 统一浏览，不改变页面与实体各自的保存/历史语义。

## 2. 版本与唯一正典作用域

- `WORLD_KERNEL_SPEC_VERSION = "world-kernel.v1"`
- `WORLD_BASE_SCHEMA_REF = "builtin:world-base-schema.v1"`
- `WORLD_AUTHORIZATION_POLICY_REF = "builtin:world-canon-author-policy.v1"`
- manifest schema：`world_canon_manifest.v1`
- receipt schema：`world_canon_admission_receipt.v1`
- StatementValue schema：`world_statement.v1`
- 唯一 scope：`novel_id`。所有 ID/ref 在准入事务内逐项验证同 novel。

内置版本字符串属于代码注册的不可变规范；改变解释语义必须发布新版本。不得从项目设置、
latest template、当前权限或运行时 discovery 解析这些版本。

## 3. 封闭资源解析目录

Phase 2 v1 只允许以下 `resource_kind`；目录是代码常量和 Pydantic discriminated union，不从
数据库或插件动态注册。

| `resource_kind` | stable resource identity | exact revision | 允许角色 | selector |
|---|---|---|---|---|
| `world_bible_page` | `WorldBiblePage.id` | `WorldBiblePageRevision.id` | documentary source、cite、hard ground | `whole`、`free_text`、`section:<section_id>` |
| `world_bible_page_template` | `WorldBiblePageTemplate.id` | `WorldBiblePageTemplateRevision.id` | layout provenance；不得作为 fact Schema | `whole` |
| `core_entity` | `CoreEntity.id` | `EntityRevision.id` | Referent documentary source、Name source | `whole`、`field:<allowed core field>` |
| `entity_profile_template` | `EntityProfileTemplate.id` | `EntityProfileTemplateRevision.id` | exact typed Schema | `whole` |
| `world_policy` | builtin stable ref | builtin exact version | BaseSchema、authorization policy | `whole` |

`EntityRelation`、Event、Profile、CreationSuggestion、working draft、current head、checkpoint、cache、
AI Interpretation、validation result 和 MemoryEvent 都不是 v1 可解析 resource revision。其事实
内容只能进入自包含 Assert；候选若需要成为 source/hard ground，必须先 seal 为上表允许的
专用 revision，否则保持非权威。

解析器输入固定为：

```json
{
  "resource_kind": "world_bible_page",
  "resource_id": "uuid",
  "revision_kind": "world_bible_page_revision",
  "revision_id": "uuid",
  "selector": "section:history"
}
```

解析必须验证：kind/version、stable head 与 revision 归属、`novel_id`、selector 存在且唯一、
revision snapshot 覆盖所声明角色、归档/删除后的历史可读语义。以下输入统一 422；准入事务中
出现则整笔回滚：unknown kind、裸 digest、`latest`/head、mutable ID、跨小说 ref、不存在或
越界 selector、已删除且不可历史读取的 revision。

## 4. StatementValue、TimeScope 与 Assert wire

v1 只开放三个 self-contained statement kind，不支持任意 predicate、程序或 StatementRef：

```text
NameStatementV1 {
  kind="name", version=1, subject_entity_id, value, name_kind=primary|alias
}
TypedScalarStatementV1 {
  kind="typed_scalar", version=1, subject_entity_id, field_key,
  value_type=string|integer|decimal|boolean|enum, value, unit?
}
BinaryRelationStatementV1 {
  kind="binary_relation", version=1, source_entity_id, target_entity_id,
  relation_kind=state|social|spatial|causal|temporal|epistemic|intentional,
  relation_type
}
```

`value` 必须按 `value_type` 严格校验；decimal 使用规范十进制字符串。所有 entity ref 必须属于
同一小说。statement identity 是 kind、version、exact Schema ref 和 canonical payload 的
SHA-256；digest 只校验/去重，不替代完整 payload。

TimeScope 是 `timeless | point | interval` discriminated union：

- `timeless` 只允许 Name 和 Spec 明确声明无 world-time 维度的 scalar/relation；
- `point` 固定 `time_ref` 与 `phase=pre|at|post`；
- `interval` 固定 start/end exact ref 和半开 `[start,end)`；start 必须早于 end。

Phase 2 只实现 `timeless` 的存储与重放；point/interval 可通过 schema 校验并 fail closed 为
`unsupported_family`，不得猜测时间。

`world_assertions` 字段唯一确定为：

```text
id UUID PK
novel_id UUID NOT NULL FK projects ON DELETE CASCADE
regime_kind world|belief
belief_holder_entity_id UUID NULL
polarity positive|negative
statement_kind VARCHAR(32)
statement_version SMALLINT
statement_payload_json JSON NOT NULL
schema_ref_json JSON NOT NULL
time_scope_json JSON NOT NULL
source_revision_ref_json JSON NOT NULL
hard_ground_refs_json JSON NOT NULL default []
cite_refs_json JSON NOT NULL default []
provenance_actor_ref VARCHAR(128) NULL       # audit-only
content_hash CHAR(64) NOT NULL
created_at TIMESTAMPTZ NOT NULL
```

约束：world regime 的 holder 必须为空；belief 必须有同小说 holder；kind/version 必须与 payload
一致；hard grounds 有限、无重复、同 novel、可解析，且不得形成环。业务层禁止 UPDATE/DELETE；
撤回只由新 Canon manifest 不再选择旧 Assert 表达。

## 5. Canon manifest 与 receipt

`world_canon_revisions`：

```text
id UUID PK
novel_id UUID NOT NULL FK projects ON DELETE CASCADE
parent_id UUID NULL FK world_canon_revisions ON DELETE RESTRICT
kernel_spec_version VARCHAR(64) NOT NULL
manifest_json JSON NOT NULL
manifest_digest CHAR(64) NOT NULL
admission_receipt_json JSON NOT NULL
created_at TIMESTAMPTZ NOT NULL
```

`manifest_json` 是完整快照，不是 query-specific subset：

```json
{
  "schema_version": "world_canon_manifest.v1",
  "novel_id": "uuid",
  "kernel_spec_version": "world-kernel.v1",
  "resources": ["closed ResourceRevisionRef, sorted"],
  "selected_assertion_ids": ["uuid, sorted"],
  "schema_refs": ["exact refs, sorted"],
  "rule_refs": [],
  "policy_refs": ["builtin:world-base-schema.v1", "builtin:world-canon-author-policy.v1"],
  "calendar_refs": [],
  "correspondence_refs": [],
  "inactive_resource_refs": []
}
```

数组在 hash 前按 canonical key 排序；JSON 使用 UTF-8、排序 key、无多余空白。manifest digest
为 canonical bytes 的 SHA-256。v1 直接保存完整 manifest；只有实际体积证明需要时才设计可
唯一还原的 delta，不预建压缩层。

receipt 内联在 CanonRevision，唯一形状为：

```json
{
  "schema_version": "world_canon_admission_receipt.v1",
  "novel_id": "uuid",
  "canon_revision_id": "uuid",
  "manifest_digest": "sha256",
  "committer_principal": "stable account uuid",
  "action": "initialize|publish_page|adopt|promote|canonical_edit|revert",
  "authorization_scope": "world.canon.commit",
  "authorization_policy_ref": "builtin:world-canon-author-policy.v1",
  "authorization_policy_digest": "sha256",
  "decision": "allowed",
  "committed_at": "RFC3339 UTC",
  "expected_previous_head": "uuid|null"
}
```

receipt 只记录提交时授权，不证明内容为真。`committer_principal` 来自当前 principal，body 不得
指定。历史重放核对 receipt、manifest 和 parent，不用当前角色重判当时准入。

## 6. Head、C0 与事务

`world_canon_heads`：

```text
novel_id UUID PK FK projects ON DELETE CASCADE
canon_revision_id UUID NOT NULL FK world_canon_revisions ON DELETE RESTRICT
head_version BIGINT NOT NULL default 0
updated_at TIMESTAMPTZ NOT NULL
```

每个作者小说建立一个 C0：parent=null、空 resources/assertions、固定 v1 kernel/BaseSchema/policy，
receipt action=`initialize`、expected_previous_head=null。interaction 项目不建立 World Canon。

每次提交锁定 active project 与 head，要求请求的 `expected_previous_head` 等于当前 head；新 C 的
parent 必须等于该 head。随后在一个事务内插入 sealed revisions/Assert、新 C/receipt，并以
`WHERE novel_id=? AND canon_revision_id=? AND head_version=?` 更新 head。影响行数不是 1 时整笔
回滚并返回 409 `world_canon_head_changed`。失败不得留下 Assert、CanonRevision、receipt 或
canonical projection 的部分写入。

历史浏览只传 `canon_revision_id` 查询，不改 head。revert 复制目标 C 的完整 manifest，按当前
权限重新 Admit，创建以当前 head 为父的新 C；action=`revert`，head 继续前进。

## 7. Page publish、候选采用与 family seam

- Phase 1：页面仍走当前 draft publish；UI 和文档不得称其为 formal DocCanon。
- Phase 2：publish 在现有 page/draft 锁和 validation receipt 后，seal exact PageRevision，复制
  当前完整 manifest 并替换该 Page stable resource 的 revision，创建 C/receipt/CAS。默认不建
  Assert。
- Adoption Package 是唯一批量 B promotion seam。preview 固定 package revision、source refs、
  head、Schema、成员和 digest；apply 重验所有项。任一项 invalid/stale/cross-novel/unsupported，
  全批 409/422 且零写入。作者要部分采用，必须重新 preview/确认 exact subset。
- Name cutover 后，canonical 名称编辑必须在一个事务内：锁 entity/head → seal EntityRevision →
  create Name Assert → create C/receipt → CAS head → 更新 `CoreEntity.name` 只读投影。任一步失败，
  名称和 Canon 都不变。旧独立 update 只能成为明确工作稿；evaluator 只读 C 选中的 Name Assert。
- custom typed 与 relation 已通过 exact `EntityProfileTemplateRevision` + exact source
  的显式 B promotion 切换 formal evaluator；legacy Profile/Relation 只留作编辑/展示投影，
  不 fallback。event/time 与 belief 在另有 phase contract 前保持 unsupported/legacy。

## 8. API 与错误合同

Phase 1 只复用现有 API。Phase 2 新增的最小 owner-only API：

```text
GET  /api/world/canon                         # current head summary
GET  /api/world/canon/{canon_revision_id}     # immutable manifest summary
POST /api/world/canon/revert                  # expected head + target C + confirmation
POST /api/world/canon/initialize/preview       # legacy exact PageRevision subset, zero write
POST /api/world/canon/initialize               # expected head + preview digest + confirmation
POST /api/world/profile-templates              # CreateTemplate; seal exact v1 revision
POST /api/world/profile-templates/{id}/revisions
POST /api/world/profile-templates/{id}/adopt   # AdoptSchema; future profiles only
POST /api/world/canon/promotions/preview        # exact B subset, zero write
POST /api/world/canon/promotions                # PromoteHistoricalContent
POST /api/world/formal-query                    # selected Assert only; verdict + S/F/I/X
```

`POST /api/world/formal-query` 始终与 Ask World 分离，只求值固定 C 的 selected
Name/scalar/relation Assert。S/F/I/X 在 wire 中使用同名别名；`X` 区分
complete、budget-truncated、unsupported-family 和 invalid-context。

普通响应不返回完整 receipt、raw manifest 或 proof。诊断入口可返回经 schema 约束的明细。错误：

- 404：项目/资源在当前 owner + novel scope 不可见；
- 409 `world_canon_head_changed`：CAS stale；
- 409 `world_canon_initialization_required`：旧小说还只有 C0，操作要求显式初始化；
- 422 `world_canon_invalid_reference`：unknown/mutable/cross-novel/selector invalid；
- 422 `world_statement_unsupported`：kind/version/StatementRef/time family 未支持；
- 422 `world_canon_manifest_not_closed`：manifest、ground 或 receipt 不闭合；
- 503 `world_kernel_unsupported`：没有该历史 K 的合规 evaluator。

## 9. 最小反例测试门禁

Phase 2 开工前先建立失败测试，至少覆盖：

1. 相同输入不能产生两种 `novel_id` scope；跨 novel body/ref 全拒。
2. 完整 manifest 可独立重放旧 Page revision；published latest 变化不影响旧 C。
3. receipt 缺任一必填字段、digest/head/policy 不匹配时拒绝。
4. unknown kind、mutable row、latest/head、裸 digest、无效 selector 和不可读 revision 全拒。
5. validation/AI/candidate 不创建 Assert、不移动 head、不成为 hard ground。
6. C0 不提升 legacy status；每 novel 唯一 head，parent 只 `0..1`。
7. stale CAS、非法批次或 canonical edit 任一步失败时没有部分写入。
8. 历史浏览不动 head；revert 创建新 child，不修改旧 C。
9. Page publish 只选择 exact PageRevision，除非显式 promotion，否则零 Assert。
10. family cutover 后 canonical read/write 都不 fallback legacy；未 cutover family 仍完全沿用 legacy。
11. formal query 区分正、负、both、unknown 与 `X=budget-truncated|unsupported|invalid`。
12. evidence compiler 只经 world facade 读取 C-pinned facts；MemoryEvent 在 event/time cutover 前排除。

## 10. 文档与验证

每个 phase 同步 `CONTEXT.md`、整体/数据库设计、world README、Evidence compilation README、
frontend 文档/业务场景、ADR 索引和 OpenAPI contract tests。收尾运行受影响 pytest、Vitest/E2E、
Ruff、migration check、`make docs-check BASE_REF=origin/main` 与 `git diff --check`。

Phase 0 完成判据：本文件所有字段、resolver、事务、错误和状态机均只有一种符合文本的实现；
最小反例有可执行测试清单。v1 实施已满足该门禁；A 型正文 owner、event/time、
belief 与 multi-head/merge 仍须新 Spec/ADR，不得由当前 API 暗中扩展。
