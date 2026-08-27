# World Authority Phase 0 实施 Spec

## 状态与范围

- 状态：Accepted / Implemented（Phase 0）。
- 日期：2026-08-27。
- 架构决策：[`ADR-0017`](../../adr/0017-world-fact-authority-and-canon-revisions.md)。
- canonical fixtures：
  [`world-authority-canonical-fixtures-v1.json`](../../references/world-authority-canonical-fixtures-v1.json)。
- 影响模块：`world` 为 owner；`account` 提供 authorizer contract；`project` 保持 owner/active
  gate并在作者项目创建时初始化 C0。`task_attempt` wire 已封闭，但当前无可用的后台
  Canon admission 消费者，因此未增加空执行入口。
- 本文固定并记录已实现的 Phase 0 数据库、wire、状态机、失败语义和测试边界。

## 1. 目标与非目标

Phase 0 只解决四个工程事实：

1. 哪些现有资源能被精确解析，以及 snapshot/digest 覆盖什么；
2. authorizer、executor 与 admission authorization policy 如何持久化；
3. v1 StatementValue、TimeScope 与 StatementClaimRef 的封闭 wire；
4. versioned selector、canonical bytes 与可执行 fixture。

Phase 0 不实现 Card UI、查询引擎、规则推理、belief、事件演算、branch、proof cache、FRI 或
legacy family cutover。也不建立通用 Card、KnowledgeResource、ResourceRevision、Statement、
receipt、policy 或 worker identity 表。

## 2. 当前仓库证据

| 事实 | 当前证据 | Phase 0 结论 |
|---|---|---|
| 项目与 authorizer | `projects.owner_id` 与 `AccountPrincipal.account_id` | account ID 是唯一人类 authorizer；请求体不得指定 |
| executor | `AsyncTask` 已有 task ID、type、attempt、lease | 用 task attempt 标识后台执行，不新增 worker identity |
| 当前 TargetRef | 只有 type、ID、path、relation | 保留给现有 evidence；Canon exact ref 使用新 wire，不改名复用 |
| PageRevision | snapshot 完整但无 persisted digest | 增加 `revision_digest` 并 backfill |
| PageTemplateRevision | 有 content hash，但只描述布局 | 不进入首批 Canon resource catalog |
| EntityRevision | 无 digest，且只快照 CoreEntity 字段 | 保留 legacy rollback，不作为 Canon ResourceRevision |
| EntityProfileTemplate | mutable head，无 revision | 增加专用 revision carrier |
| CreationSuggestion | `payload_json` 可变 | Admit 内联封存 exact snapshot，不称其为 immutable revision |
| World Validation Policy | 校验内容与证据门禁 | 不得作为 admission authorization policy |
| Relation/Profile/Event | mutable current row | family cutover 前保持 current authority；不得直接进入 Canon manifest |

## 3. 产品门禁

目标画像是长期创作作者。Phase 0 本身无新 UI；后续 Card 与历史界面必须继续使用作者语言：

- 已发布、已采用、历史、待处理、冲突；
- 不在普通界面展示 raw ID、manifest、Assert、receipt、S/F/I/X 或内部 policy key；
- canonical edit 失败时保留草稿，并说明“设定已变化，请重新确认”，不得静默 rebase；
- AI 结果继续先进入待处理，作者能看见来源、影响范围与撤销结果。

用户价值是假设：统一历史能减少“正文、字段和关系谁算数”的不确定感。上线后以采用撤销率、
冲突恢复成功率、历史回看完成率和定性反馈验证，不以 schema 完整度代替产品验证。

## 4. Canonical bytes 与 digest

所有进入 digest 的值先经过对应 Pydantic tagged union 校验，`extra="forbid"`。规范化顺序固定：

1. UUID 输出为小写、带连字符的标准字符串；时间输出 UTC RFC 3339，使用 `Z`。
2. 字符串统一 Unicode NFC 和 `LF` 换行。名称、标识和枚举去除首尾空白；正文值不折叠内部
   或首尾空白，除非其具体 variant 明确要求。
3. identifier 使用所属 variant 的 ASCII pattern；不做隐式同义词、拼音或大小写猜测。
4. 禁止 float、NaN 和 Infinity。整数使用 JSON integer；decimal 使用无指数、无前导 `+`、
   无无效前导零、无尾随零且 `-0 → 0` 的十进制字符串。
5. object key 按 Unicode code point 升序；array 顺序有意义；schema 未允许的 `null` 不得出现。
6. 使用 Python stdlib `json.dumps(value, ensure_ascii=False, sort_keys=True,
   separators=(",", ":"), allow_nan=False)`，编码为无 BOM UTF-8。
7. digest 为上述 bytes 的 SHA-256 小写 64 位十六进制。

不引入 JCS 或其他 canonical JSON 依赖。任何规范化规则变化必须提升相关 wire version，旧
CanonRevision 始终用其固定版本重放。

代码内 sealed artifact registry 首批固定三项非项目资源；descriptor 与 digest 由 fixture
逐字节冻结：

| artifact ID/version | descriptor digest | 用途 |
|---|---|---|
| `world.canon-kernel/1` | `f8d47106cd0c8803739815de39439bbb6d6d95e4b0657d63763060f82671ff6c` | manifest、canonicalization 与 claim 深度语义 |
| `world.statement-schema/1` | `3eda28fd8a246e2c44cfd36683b754b221de5a340ce0c04be58a85f186c6c81e` | 三种 Statement 与五种 Scalar union |
| `world.canon-rules.empty/1` | `c110c7c624f2715b92eb5b0283b316470fbb8b2a6ab49379c157ec014920bad1` | v1 空推导规则集 |

`VersionedArtifactRef = {artifact_id, version, digest}`。registry unknown ID/version 或 digest mismatch
失败关闭；代码行为改变必须新建 version，不能只改 descriptor 文本。

ResourceRevision digest 输入固定为：

```json
{
  "kind": "resource_revision_digest_input",
  "version": 1,
  "resource": "<ResourceRef>",
  "revision_id": "<UUID>",
  "snapshot": "<完整 immutable snapshot>"
}
```

`created_at`、`revision_reason` 与操作者不进入资源内容 digest；它们仍是不可变审计字段。

## 5. Exact ref 与封闭 resolver catalog

### 5.1 公共逻辑 wire

```text
ResourceRef = {
  kind, version, novel_id, resource_id
}

ExactResourceRevisionRef = {
  resource: ResourceRef,
  revision_id,
  revision_digest
}

TargetRefV1 = {
  kind: "target_ref",
  version: 1,
  revision: ExactResourceRevisionRef,
  selector: SelectorValue
}

AssertRefV1 = {
  kind: "assert_ref",
  version: 1,
  novel_id,
  assert_id,
  assert_digest
}

GroundRefV1 = TargetRefV1 | AssertRefV1
```

所有 UUID 和嵌套引用必须与外层 `novel_id` 相同。`revision_digest` 和 `assert_digest` 必须由
resolver 重算，不信任调用方。wire 不支持 `latest`、缺省 version 或 current-head 解析。

### 5.2 首批 resource catalog

| resource kind/version | stable head | immutable revision | 允许角色 | admission/replay |
|---|---|---|---|---|
| `world_bible_page/1` | `world_bible_pages.id` | `world_bible_page_revisions.id` | `card_document`, `documentary_source`, `citation`, `validation_policy` | 新 admission 只选已发布 revision；历史 replay 可读后来归档 head 的旧 revision |
| `entity_profile_template/1` | `entity_profile_templates.id` | 新 `entity_profile_template_revisions.id` | `schema` | 新 admission 只选 active template 的 revision；旧 Canon 固定旧 revision |

明确排除：WorldBiblePageTemplate（布局）、CoreEntity（Referent）、EntityRevision（不完整 legacy
snapshot）、Profile、Relation、Event、CharacterKnowledge、CreationSuggestion、Story current
head、Memory checkpoint、projection、synopsis 和 cache。未来增加 kind 必须修改 catalog、wire
union、resolver tests 和 fixtures，不能 runtime discovery。

### 5.3 snapshot 与 digest 覆盖

`world_bible_page/1` 的 snapshot 必须完整包含当前 PageRevision 已保存的：

- `page_type`, `page_key`, `title`, `status`；
- `page_meta_json`, `free_text`, `sections_json`, `linked_asset_refs_json`；
- `activation_defaults_json`, `template_key`, `template_version`, `sort_order`。

新增 `revision_digest`，并对历史 revision 按相同 envelope backfill。当前
`source_content_hash()` 只服务 workflow/source freshness，覆盖不完整，不能复用为 revision
digest。

`entity_profile_template/1` 的新 revision snapshot 固定：

- `profile_type`, `template_schema_json`, `display_schema_json`；
- `version_number`, `status`。

现有 head 增加 `version_number`。任何 schema 或 display schema 保存、归档、恢复都追加 revision；
历史 revision 禁止 UPDATE，普通服务禁止 DELETE，项目永久删除仍按 `novel_id` 级联。

### 5.4 selector catalog

| resource | selector kind/version | payload | 结果 |
|---|---|---|---|
| 两者 | `whole/1` | `{}` | 完整 snapshot |
| Page | `world_bible_page.field/1` | `field = title | free_text` | 精确字段值 |
| Page | `world_bible_page.section/1` | `section_id` | 唯一匹配的完整 section |
| Page | `world_bible_page.metadata/1` | `key = validation_policy | card_subject_ref_v1` | reserved metadata value |
| ProfileTemplate | `entity_profile_template.field/1` | `field_key` | template schema 中该字段定义 |

不支持任意 JSON path、数组 index、regex、substring 或 section offset。缺字段、重复 section ID、
unknown selector 或 selector/resource 不匹配均失败关闭。Page 对 WorldEval family 仍为
evidence-only，Page TargetRef 不能充当形式 hard ground。

### 5.5 归档与删除

- 资源 head 归档不影响历史 Canon replay；新 admission 默认不能选归档 head。
- restore 必须先通过现有领域流程产生新 head revision，再由新 CanonRevision 选择。
- 被任一 CanonRevision 引用的 revision 不提供普通硬删除路径。项目永久删除是唯一整体删除
  例外，仍由 owner、回收站和 `novel_id` 级联门禁控制。

## 6. Authorizer、executor 与 policy carrier

### 6.1 Principal wire

`AuthorizerRefV1` 是封闭 union：

- `account/1`：只含服务端取得的 `account_id`；必须等于项目当前 owner；
- `bootstrap/1`：固定 subject `world.canon.bootstrap`，仅能创建空 C0。

`ExecutorRefV1` 是封闭 union：

- `account_request/1`：服务端取得的 `account_id`；
- `task_attempt/1`：`task_id`, `task_type`, `attempt`, `lease_id`；finalizer 必须仍持有该 lease；
- `bootstrap/1`：只用于 C0。

HTTP body、LLM output 和 candidate payload 都不能提供 authorizer/executor。物理 worker hostname、
PID 和 deployment instance 不进入 receipt；task attempt 已能唯一标识实际执行，无需新身份系统。

### 6.2 Authorization policy registry

代码内建立封闭、只读 descriptor registry，不建表：

| policy ID/version | descriptor digest | 允许行为 |
|---|---|---|
| `world.canon.bootstrap-empty/1` | `a1104c58dcb18c278a1fab2b5b944b4f76d05a49d9a22a2412df1e9e7b56cc29` | 仅项目初始化；parent/head 均为空；零资源、零 Assert、全部 family `formal-disabled` |
| `world.canon.explicit-author/1` | `2ee3ff5a3c5d64259b5712a3d17f869b6d717e1efd0325effb8cebd1f328d1b6` | 当前 owner 在当前请求中显式确认 exact input 与 expected head |
| `world.canon.persisted-workflow/1` | `bdced8af8cc6eb4619c73a2f4592e323b37c0778f2c638cfb51818df4be4f0ef` | 当前 owner 预先持久化 exact scope；task attempt 只能执行该 scope，提交时 owner 与 lease 仍有效 |

descriptor 本身按第 4 节生成 digest；receipt 固定 `{artifact_id, version, digest}`。policy 代码与
descriptor 不一致时测试失败；更新逻辑必须新建 version。`world_validation_policy.v1`、
validation run、AI review、task status 和 imported `canon/status` 都不能返回 authorization allow。

### 6.3 Admission receipt

receipt 是 `CanonRevision` 内联不可变值，不建表。必填：

- `novel_id`, `canon_revision_id`, `manifest_digest`；
- decision ID/digest、action、`expected_previous_head`、UTC committed time；
- authorizer、executor、authorization policy ref 与固定 `allow` decision；
- affected families/resources；
- 完整 `AdmissionInputValue` 与其 digest。

历史 replay 校验当时 receipt 与 policy descriptor digest，不用当前授权政策重判当时准入；当前
owner/权限仍决定调用者能否读取历史。

## 7. v1 Statement、Claim 与时间

### 7.1 Assert envelope

每条 `world_assertions` 逻辑值为：

```text
AssertV1 = {
  novel_id,
  regime: "objective_world.v1",
  polarity: "positive" | "negative",
  statement: StatementValueV1,
  schema_ref: BuiltinSchemaRef | ExactResourceRevisionRef,
  time_scope: TimeScopeV1,
  source_refs: TargetRefV1[],
  hard_grounds: GroundRefV1[],
  provenance_actor_ref,
  content_digest
}
```

`content_digest` 覆盖除数据库 ID、创建时间和 audit-only provenance 之外的完整语义 envelope。
`hard_grounds` 是无重复、按 digest 排序的 flat conjunction；禁止自指、循环和未被当前 Canon
选择的 AssertRef。`source_refs` 同样去重并按 digest 排序，可为空；直接作者断言可以是空
grounds。

### 7.2 StatementValueV1

封闭 union 只有三种：

1. `entity_name/1`：同 novel ReferentRef + 规范化 name；只表示 primary name。
2. `entity_scalar/1`：ReferentRef + exact EntityProfileTemplateRevision + `field_key` + ScalarValue。
3. `entity_relation/1`：两个同 novel ReferentRef + 七类 `relation_kind` + 规范化非空
   `relation_type`；description、strength、quote 和 review metadata 不属于关系真值。

Name 与 binary relation 使用 C 固定的 `world.statement-schema/1`；typed scalar 还必须固定
对应 EntityProfileTemplateRevision。builtin artifact ref 不能由请求替换为同名其他 digest。

`ScalarValueV1` 只有：

- `text/1`：保留正文空白，仅做 NFC/LF；
- `integer/1`：JSON integer；
- `decimal/1`：第 4 节规范十进制字符串；
- `boolean/1`：JSON boolean；
- `enum/1`：由 exact schema field 声明的稳定 key。

列表、对象、quantity、money、任意 JSON 和 entity ref scalar 均不在 v1；对象引用使用
`entity_relation`。字段类型、required/default 与枚举必须由 exact template revision 验证。
default 只预填 UI，作者未实际保存就不产生 Assert。

### 7.3 TimeScopeV1

封闭 union：

- `timeless/1`；
- `point/1`：exact `calendar_ref` + integer value；
- `interval/1`：exact `calendar_ref` + integer start/end + 开闭边界，且 start ≤ end。

Phase 2–5 只准入 `timeless/1`。当前仓库没有合格 Calendar carrier；point/interval wire 可以被
canonical fixture 验证，但 admission 返回 `unsupported_calendar`。event/time cutover 必须先用
新 ADR/Spec 把 calendar 加入封闭 registry，不能把 Scene index、chapter index、
`timeline_order` 或自由时间标签猜成世界时间。

### 7.4 StatementClaimRefV1

```text
StatementClaimRefV1 = {
  kind: "statement_claim_ref",
  version: 1,
  regime,
  polarity,
  statement: StatementValueV1,
  time_scope: TimeScopeV1
}
```

claim digest 由上述完整规范值计算，由外层 carrier 保存或比较，不作为被哈希值的
自引用字段，也不是 Assert ID 或 pointer。内层 StatementValue 不能再次包含
StatementClaimRef，因此深度恒为 1。Phase 0 定义并测试 wire，但三种 v1 StatementValue 都不
接收 claim object；试图将其写入 Assert 返回 `unsupported_statement_kind`，直到 belief phase
另立 Spec。

## 8. CanonRevision 与 family authority

`CanonManifestV1` 是完整 snapshot，固定：

- `active_resources`：按 `(kind, resource_id)` 唯一、按 canonical key 排序的 exact revisions；
- `selected_assertions`：无重复 AssertRef 全集；
- exact kernel ref、schema refs、rule ref、可空 validation policy ref 与 calendar ref；
- pinned documentary/provenance/citation dependencies；
- 五个 family 的完整 authority map：`formal-disabled | canon-owned`。

C0 必须是零资源、零 Assert、空 dependency、无 calendar，所有 family 均
`formal-disabled`。新作者项目在项目创建事务中经 world facade 建立 C0/head；migration 为现有
作者项目 backfill。bootstrap decision ID 使用固定 namespace 对 `novel_id` 计算 UUIDv5，使初始化
重试可由 `(novel_id, decision_id)` 唯一收敛；`interaction` 项目不创建 Canon。

`world_canon_heads` 每个 `novel_id` 一行。一次成功 CAS 只能从 current C 指向其新直接子；
head 不得指向祖先、旁支或其他 novel。历史浏览不更新 head。

family cutover 只允许 `formal-disabled → canon-owned`，并在专用 phase Spec 中同时给出：

- mutable draft/authoring carrier；
- 唯一 canonical write seam；
- 唯一 canonical read projection/evaluator；
- legacy 字段允许用途和禁止用途；
- 失败时全成全败的事务边界。

## 9. 最小物理 schema

### 9.1 `world_assertions`

- `id`, `novel_id`, `regime`, `polarity`；
- `statement_json`, `schema_ref_json`, `time_scope_json`；
- `source_refs_json`, `hard_ground_refs_json`, nullable `provenance_actor_ref_json`；
- unique `(novel_id, content_digest)`, `content_digest`, `created_at`。

### 9.2 `world_canon_revisions`

- `id`, `novel_id`, monotonic `version_number`；
- nullable same-novel `parent_revision_id`；
- `manifest_json`, `manifest_digest`, `receipt_json`, `decision_id`, `decision_digest`, `created_at`；
- unique `(novel_id, version_number)` 与 `(novel_id, decision_id)`；decision 两列只是 receipt 的
  immutable lookup projection，写入时必须与 receipt 内值完全一致。

### 9.3 `world_canon_heads`

- `novel_id` PK/FK；
- non-null same-novel `current_revision_id`；
- `updated_at`。

### 9.4 `entity_profile_template_revisions`

- `id`, `novel_id`, `template_id`, `version_number`；
- `snapshot_json`, `revision_digest`, `revision_reason`, `created_by`, `created_at`；
- unique `(template_id, version_number)`，并以 same-novel composite FK 防止跨项目引用。

同时给 `entity_profile_templates` 增加 `version_number`，给
`world_bible_page_revisions` 增加 `revision_digest`。新表和 exact JSON ref 均保留
`novel_id`；公开 API 仍以 current account owner + target novel 双门禁。

## 10. AdmissionInputValue 与唯一 Admit

`AdmissionInputValueV1` 是封闭 tagged union：

- `bootstrap_empty/1`；
- `page_publish/1`：exact draft snapshot、base page version、impact hash、可选 validation run ref；
- `assert_batch/1`：typed proposed assertions、exact candidate snapshot、作者选择的 item keys 与
  source refs；
- `revert/1`：target CanonRevision、expected head 与兼容性 judgment；
- `family_cutover/1`：专用 phase 才开放的 exact migration input。

当前 `CreationSuggestion` snapshot 必须包含 ID、source module、review group、target type、
action schema、payload/evidence/result refs、status、updated time，并由相应 action schema 重验。
它只证明 Admit 看到了哪个 mutable 候选状态，不把 suggestion row 升格为 ResourceRevision。

Admit 的唯一事务顺序：

1. 通过现有 active project 与 owner gate，锁定本 novel Canon head；
2. 读取 current C，验证 expected head、decision idempotency、authorizer、executor、policy；
3. 按稳定 ID 顺序锁定该 action 涉及的 draft/candidate/resource heads；
4. 重新生成并比较 AdmissionInput digest，解析 exact refs、selector、Schema 与同 novel 约束；
5. 运行 action-specific authoritative validation；任一 include 无效则退出且零写入；
6. 必要时 seal domain revision，插入去重后的 Assert；
7. 构造完整新 manifest、receipt 和 CanonRevision；
8. 以 `expected_previous_head` 做 CAS，成功后一次 commit。

CAS 失败不自动 rebase。相同 decision ID+digest 已成功时返回原 CanonRevision；相同 ID 不同
digest 返回 409。Preview 只返回 normalized input、digest、diff 和错误，不写 Assert/C/head。

## 11. HTTP 与稳定 seam

Phase 2 拟新增以下 owner-only API；名称在实现 review 中可做一致性微调，但语义不可改变：

| 方法 | 路径 | 语义 |
|---|---|---|
| GET | `/api/world/canon/head` | 当前 C 摘要；普通响应不展开 receipt/proof |
| GET | `/api/world/canon/revisions/{revision_id}` | 当前项目内历史 C 与作者可读变化摘要 |
| POST | `/api/world/canon/admissions/preview` | 零写入规范化、验证与 diff |
| POST | `/api/world/canon/admissions` | 显式确认后执行唯一 Admit |
| POST | `/api/world/canon/revert` | 追加式恢复；不移动 head |

不提供 Assert CRUD、任意 manifest 写入、任意 policy 上传或“以 latest 重试”接口。API body 只
携带 target novel、decision、expected head 和 typed input；authorizer/executor 由服务端注入。

跨模块只新增有真实消费者的窄 read seam：evidence 可取得指定 C 的 canonical fact/document
bundle；project 创建 author 项目时调用 world 的 C0 初始化 facade。任何新 facade 在实现时仍需
做 deletion test，不预建空 port。

## 12. 失败码与安全

| code | HTTP | 条件 |
|---|---:|---|
| `canon_reference_invalid` | 422 | malformed/unknown kind/version/selector |
| `canon_reference_unavailable` | 404 | missing、跨 novel、无权或已删除；不泄露存在性 |
| `canon_revision_digest_mismatch` | 409 | exact revision 内容与提交 digest 不同 |
| `unsupported_statement_kind` | 422 | 未开放 statement/claim kind |
| `invalid_statement_value` | 422 | normalization、schema 或 time scope 无效 |
| `unsupported_calendar` | 422 | point/interval 未绑定已支持 calendar |
| `canon_admission_stale` | 409 | candidate/draft/source/expected head 漂移 |
| `canon_decision_id_reused` | 409 | 同 decision ID 不同 digest |
| `canon_authorization_denied` | 403 | authorizer/policy/scope 不允许 |
| `canon_head_conflict` | 409 | CAS 失败；不得自动 rebase |
| `incompatible_revert_target` | 409 | revert 会逆转 family cutover 或 Schema 不兼容 |
| `canon_ground_cycle` | 422 | self/cycle/non-selected hard ground |

日志与响应不得包含正文、完整 candidate payload、receipt、内部 manifest、API Key、lease secret
或跨项目 ID。所有 Pydantic/DB/LLM 输入继续经过 schema guard；任何 AI 输出都没有 authorizer
variant。

## 13. 实施顺序与最小验证

1. 先提交 Pydantic unions、canonicalizer、artifact/policy registry 与 fixtures；不建表。
2. 增加四张表、两个 revision 字段、约束与 backfill；为所有 author novel 建空 C0/head。
3. 实现 resolver catalog、replay 和 receipt validation。
4. 实现 Preview/Admit/Revert；只开放 C0 与 Page documentary selection，所有 family 仍
   `formal-disabled`。
5. 把 World Bible publish 接入同一事务：seal PageRevision + 选择它的新 C + receipt + head CAS。
6. 后续 phase 再逐 family cutover；不得提前从 Assert 与 legacy current row双读。

最小自动验证：

- fixture 文件逐例重新 canonicalize 并比对 canonical JSON/SHA-256；
- unknown kind/version/selector、arbitrary path、跨 novel、digest mismatch 全拒绝；
- C0、每 novel 唯一 head、same-novel parent、只前进 CAS、旧 C replay；
- authorizer/executor 封闭 union、policy 绑定、AI authorizer 不可构造与当前 owner 门禁；
- `task_attempt` 尚无 admission 入口；未来接入时必须在提交前增加 lease 与 owner 重验；
- same decision retry、different digest conflict、CAS conflict 零写入；
- Page publish 任一步失败时 draft 保留，Page/current C/WorldEval 均不改变；
- Statement 正负极性、typed scalar normalization、StatementClaimRef 深度与 calendar 拒绝；
- project 永久删除完整级联，普通历史 revision 无硬删除入口；
- `make docs-check BASE_REF=origin/main`、受影响 backend tests、Ruff 与 PostgreSQL migration check。

## 14. 当前实现状态

Phase 0 已同步：

- `CONTEXT.md`、整体设计、数据库设计；
- `backend/modules/world/README.md`、`docs/modules/02_world.md`；
- project 创建 C0 行为与 world 稳定 facade；
- World Bible 发布的前端 API adapter；
- ADR-0006、ADR-0016 的 amendment、ADR 索引和 architecture inventory。

Phase 1 纯 Card read model 可以消费 CanonRevision 摘要，但不得将尚未启用的 Assert/family
推理声称为当前能力。探索式世界模型文档不在本 Spec
维护范围内。
