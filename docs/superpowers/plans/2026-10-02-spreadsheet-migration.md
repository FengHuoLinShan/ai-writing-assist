# 表格迁移（xlsx / csv）并行开发计划

- 任务记录：[`.agent/tasks/2026/T-20261002-spreadsheet-migration/TASK.md`](../../../.agent/tasks/2026/T-20261002-spreadsheet-migration/TASK.md)
- 集成分支与 worktree：`codex/spreadsheet-migration`，路径 `../ai-writing-assist-spreadsheet`。基线为
  `origin/main@0d555c463`，Alembic head 为 `20260929_world_object_image_candidates`。
- 新 ADR 编号：ADR-0030。如编号已被占用，顺延并同步本文。
- 本文是实施拆解，不是架构权威。实施完成后，事实以 ADR-0030、模块 README、ORM、migration 和测试为准。

## 0. 执行者必读

1. 先读根 `AGENTS.md`、所改模块的 `AGENTS.md`/README，以及本文 §1–§3 和自己负责的车道（§4）。
2. 只写本车道“独占文件”中列出的文件。需要改动契约（§3）或别人的文件时，不要自行修改，在交接
   报告里提出，由集成者裁定。
3. 车道分支从集成分支的 L0 提交切出，命名 `codex/spreadsheet-migration-<lane>`，各用独立 worktree。
   不提交 `main`，不 push，除非集成者另行授权。
4. 测试规则：`@patch` / `mock.patch` 一律 `autospec=True`；跨模块测试替身走 DI 或 facade；生产代码
   不得 import Mock。车道合入前对方实现未就绪时，可以用 autospec 替身顶替 §3 的契约函数；集成阶段
   （L8）再换成真实链路。
5. 完成后按 §7 模板写交接报告。

## 1. 背景与已确认决策

作者常用 Excel、WPS、飞书、腾讯文档、Google 表格、Notion 数据库管理人物卡、设定词条、关系、大纲
和细纲。目前系统只能导入正文（txt/epub/html），作者迁移进行中的项目只能逐条手抄。

以下决策已由用户确认（2026-10-02）：

- **范围**
  - 世界对象与人物卡：人物、地点、势力、物品、设定词条等，含别名、类型、简介和人物字段。
  - 人物关系表。
  - 大纲和细纲等自然语言表，交给 LLM 转成故事结构。
- **格式**：只支持 `.xlsx` 和 `.csv`。正文继续走现有导入，文稿白名单不变。
- **映射**
  - 默认：按表名和中文表头的同义词规则识别，作者在预览中逐表、逐列调整。
  - 可选：AI 整理，例如把人物小传拆成人物字段。
  - 大纲类表：默认预选 AI 转化。模型未配置、作者跳过或单行失败时，回落到规则映射，原文逐字保留。
- **落库**：确认即采用。
  - 新对象成为正式资产，带“表格迁移”来源，整次迁移可撤销。
  - 与已有对象同名时绝不覆盖，只补空字段。
  - 冲突项不落库，只展示给作者。
  - LLM 输出只进入预览，作者确认后才采用。

产品门禁（`docs/product/user-personas.md` §4.3）：
- **目标画像**：A，长篇作者。
- **消除的摩擦**：手抄迁移；深度导入对不上作者已有的设定。
- **控制感**：表类型和列映射逐项可调、冲突不覆盖、来源可见、整次可撤。
- **验证指标**：迁移完成率、撤销率、放弃点。目前没有真实数据，这些是产品假设。
- **结论**：做。

## 2. 架构总览

```text
浏览器 ──multipart──▶ /api/imports/migrations (imports)
                       │ parsers.parse_spreadsheet_file ─▶ ParsedUpload（有界、不落盘）
                       │ classify ─▶ 表类型/列映射建议 ─▶ import_migration_sessions（草稿）
                       │ PUT mapping/decisions ─▶ planning ─┬▶ world.plan_author_migration_world   (只读)
                       │                                    └▶ story.plan_author_migration_structures (只读)
                       │ POST ai-runs ─▶ task spreadsheet_migration_ai ─▶ LLM（预览结果写回会话）
                       │ POST apply(expected_preview_hash) ─ 单事务 ─▶ world.apply… ─▶ story.apply… ─▶ 回执
                       └ POST rollback ─▶ story.rollback… ─▶ world.rollback…（按回执逆序，已改动则保留）
```

关键决策（ADR-0030 将固化）：

1. **入口归 imports 子包** `backend/modules/imports/spreadsheet_migration/`，路由 `/api/imports/migrations`。
   - 不扩展 `parsers.ALLOWED_EXTENSIONS`，不复用 `/imports/upload`，理由同 ADR-0016。
   - 签名校验与分派按 imports AGENTS 接入 `parsers.py`，但使用独立的 `SPREADSHEET_EXTENSIONS`。
   - 匿名 demo 已被拦截，因为 `/api/imports/` 不在 `account/middleware.py:49` 的 `_DEMO_CORE_READ_PREFIXES` 中。要加测试钉住这一点。
2. **world 落库用新的窄 seam，不复用 adoption package**。adoption package 不适合的原因：
   - 单包最多 32 项，跨包不能引用对方新建的对象；
   - 没有人物卡字段；
   - apply 写死 `force_create=False`；
   - 回滚只覆盖 focused 包。
3. **未识别列默认写入“作者备注”**：以 `【表格·列名】值` 追加到 `CoreEntity.hidden_truth`。
   - hidden_truth 只在作者视图进入上下文（`entity_context_service.py:351` `_entity_to_context`），读者和 RP 侧已剔除，不会泄露秘密。
   - 作者可以逐列改投到其他字段。
4. **确认即采用**：新实体 `status="canonical"`、`created_by="spreadsheet_migration"`、`approved_by=<owner account>`。
   - 项目启用 world validation policy 时，`require_legacy_canon_write_allowed`（`world_validation_service.py:769`）失败关闭：预览阶段提前告知，apply 时什么都不写。
5. **会话表由 imports 自有**：`import_migration_sessions`，不复用 world 的 CreationSuggestion。
   - 草稿期暂存有界的单元格，用于跨请求预览、AI 整理和刷新恢复。
   - 采用成功或删除记录后清空 `rows_json`。回执只存 id、hash 和被改字段的原值，不存正文。
6. **AI 整理**：一个 capability `imports.spreadsheet_migration`，`CONFIRMATION_NONE`，因为输入只有作者自己上传的行。
   - 两个 step：`outline`（大纲/细纲/总纲结构化）和 `cleanup`（长单元格拆字段）。
   - 审查经 `govern_group_output`（`modules.evidence.contracts`），最多返修一次。

## 3. 冻结契约（L0 交付，所有车道依赖）

L0 把本节落成代码，函数体先写 `raise NotImplementedError`，提交后各车道并行开发。字段名和签名
以本节为准。

### 3.1 共享常量

文件 `imports/spreadsheet_migration/constants.py`。

```python
MIGRATION_SOURCE = "spreadsheet_migration"
SPREADSHEET_EXTENSIONS = frozenset({".xlsx", ".csv"})
MAX_FILES = 5; MAX_FILE_BYTES = 10 * 1024 * 1024; MAX_SHEETS_PER_FILE = 20
MAX_ROWS_PER_SHEET = 5000; MAX_COLUMNS = 60; MAX_CELL_CHARS = 20_000
MAX_SESSION_CHARS = 2_000_000; MAX_APPLY_ITEMS = 1500; MAX_RELATIONS = 3000
XLSX_MAX_MEMBERS = 500; XLSX_MAX_UNCOMPRESSED = 60 * 1024 * 1024
AI_PACKET_CHARS = 24_000; AI_MAX_PACKETS = 24
SheetKind = Literal["characters", "world_objects", "relations", "chapter_outline", "arcs",
                    "threads", "foreshadowing", "story_outline", "freeform_outline", "skip"]
ColumnTarget = Literal[
  # world
  "name", "aliases", "entity_type", "summary", "public_info", "hidden_truth", "author_note", "ignore",
  # character
  "role", "appearance", "personality", "desire", "fear", "weakness", "current_goal",
  "current_state", "stance", "voice_style", "relationship_summary",
  # relation
  "source_name", "target_name", "relation_type", "relation_description", "direction",
  # story
  "chapter_ref", "title", "content", "core_conflict", "emotional_beat", "must_not_happen",
  "pov_name", "chapter_start", "chapter_end", "thread_type", "seed_chapter", "payoff_chapter",
  "reinforce_chapters", "surface_meaning", "hidden_meaning", "related_names",
  "arc_goal", "climax", "result", "next_hook"]
```

各表类型可用的列目标：
- characters / world_objects：world 组和 character 组（character 组只对人物有效）。
- relations：relation 组。
- 其余故事表：story 组，以及 `ignore` / `author_note`。

### 3.2 解析与识别

由 L1 实现。

```python
# imports/parsers.py（新增，不改 ALLOWED_EXTENSIONS）
def audit_zip_container(data: bytes, *, max_members: int, max_member_bytes: int,
                        max_total_uncompressed: int) -> None   # EPUB 与 XLSX 共用；违规抛 ValueError(作者可读)
def parse_spreadsheet_file(data: bytes, file_name: str) -> "ParsedUpload"  # 按扩展名分派到 spreadsheet_migration.parsing

# imports/spreadsheet_migration/parsing.py
@dataclass(frozen=True)
class ParsedSheet:
    sheet_key: str          # f"f{file_idx}s{sheet_idx}"，会话内唯一
    file_key: str           # f"f{file_idx}"
    name: str               # 表名；csv 用去扩展名的文件名
    hidden: bool
    rows: list[list[str]]   # 全部为字符串；合并单元格已填充；去尾部空行/空列
    warnings: list[str]     # 作者可读的提示（公式无缓存值、图片已忽略……）
@dataclass(frozen=True)
class ParsedUpload:
    file_key: str; file_name: str; file_type: str; size: int; sha256: str
    sheets: list[ParsedSheet]

# imports/spreadsheet_migration/classify.py
@dataclass(frozen=True)
class ColumnSuggestion:
    column_key: str         # f"c{index}"
    header: str
    target: ColumnTarget
    confident: bool
@dataclass(frozen=True)
class SheetSuggestion:
    kind: SheetKind
    header_row: int         # 0 起
    columns: list[ColumnSuggestion]
def detect_header_row(rows: list[list[str]]) -> int
def classify_sheet(sheet: ParsedSheet, header_row: int | None = None) -> SheetSuggestion

# imports/spreadsheet_migration/synonyms.py
def normalize_entity_type(label: str) -> str          # 系统 key 或作者自定义类型
def split_aliases(text: str) -> list[str]
def parse_chapter_ref(text: str) -> tuple[int, int] | None   # 第N章 / 阿拉伯 / 中文数字 / 区间
def guess_relation_kind(relation_type: str, *, both_characters: bool) -> tuple[str, bool]  # (kind, guessed)
```

### 3.3 world 契约

L0 写入 `modules/world/contracts.py`，并在 `facade.py` 中做 stub。L2 实现
`services/worldbuilding/author_migration.py`。

```python
class AuthorNote(BaseModel): label: str = Field(max_length=64); value: str = Field(max_length=20000)
CharacterFieldName = Literal["role", "appearance", "personality", "desire", "fear", "weakness",
    "current_goal", "current_state", "stance", "voice_style", "relationship_summary"]

class AuthorMigrationEntityInput(BaseModel):          # extra="forbid"
    item_key: str            # ^[a-z0-9_-]{1,64}$
    source_ref: str          # "<sheet_key>:r<row>"
    source_hash: str         # sha256(行单元格)
    name: str = Field(min_length=1, max_length=255)
    entity_type: str = Field(min_length=1, max_length=64)
    aliases: list[str] = []                       # 每个 ≤255，≤64 个
    summary: str | None = Field(None, max_length=5000)
    public_info: str | None = None
    hidden_truth: str | None = None               # 显式“秘密”列
    author_notes: list[AuthorNote] = []           # 追加到 hidden_truth
    character_fields: dict[CharacterFieldName, str] = {}
    decision: Literal["auto", "different_object", "use_existing", "append_note", "skip"] = "auto"
    target_entity_id: str | None = None           # decision=use_existing 时必填

class AuthorMigrationRelationInput(BaseModel):
    item_key: str; source_ref: str; source_hash: str
    source_name: str; target_name: str
    source_item_key: str | None = None; target_item_key: str | None = None  # 优先匹配本次条目
    relation_type: str = Field(min_length=1, max_length=64)
    relation_kind: RelationKind | None = None     # 作者覆盖；None 时由 world 解析
    description: str | None = Field(None, max_length=5000)
    symmetric: bool = False
    decision: Literal["auto", "skip"] = "auto"

class AuthorMigrationWorldRequest(BaseModel):
    migration_id: str
    entities: list[AuthorMigrationEntityInput] = Field(max_length=1500)
    relations: list[AuthorMigrationRelationInput] = Field(max_length=3000)

class FieldConflict(BaseModel): field: str; current_excerpt: str; incoming_excerpt: str  # 摘录 ≤200 字
class WorldMigrationItemPlan(BaseModel):
    item_key: str; kind: Literal["entity", "relation"]
    action: Literal["create", "fill_empty", "adopt_existing", "existing_ref", "conflict",
                    "needs_review", "similar_name", "alias_collision", "skip"]
    target_id: str | None = None; target_label: str | None = None
    fills: list[str] = []                         # 将补的字段名
    conflicts: list[FieldConflict] = []
    similar: list[dict] = []                      # {entity_id, name, entity_type}
    relation_kind: RelationKind | None = None; relation_kind_guessed: bool = False
    reason_code: str | None = None                # 如 endpoint_missing / endpoint_ambiguous / stale_candidate
class WorldMigrationPlan(BaseModel):
    items: list[WorldMigrationItemPlan]; validation_policy_active: bool; fingerprint: str
class MigrationAppliedChange(BaseModel):
    item_key: str; kind: str; target_id: str
    operation: Literal["create", "fill_empty", "promote", "alias", "relation_create", "relation_fill"]
    before: dict = {}                             # 仅被改字段原值（必为空值或状态），不含正文
    after_hash: str                               # stable_hash(当前状态)；回滚比对用
class WorldMigrationReceipt(BaseModel):
    applied_changes: list[MigrationAppliedChange]; entity_ids: dict[str, str]  # item_key → id
class MigrationRollbackResult(BaseModel):
    reverted: list[str]; kept: list[dict]         # kept: {item_key, reason_code}

# world facade（加入 __all__，并更新公共面回归测试）
async def plan_author_migration_world(db, novel_id: str, request: AuthorMigrationWorldRequest) -> WorldMigrationPlan
async def apply_author_migration_world(db, novel_id: str, request: AuthorMigrationWorldRequest, *,
        expected_fingerprint: str, authorized_by: str) -> WorldMigrationReceipt
    # 只 flush。指纹不符 → ConflictError(code="migration_preview_stale")；policy 生效 → 原 required_validation 错误
async def rollback_author_migration_world(db, novel_id: str, receipt: WorldMigrationReceipt, *,
        dry_run: bool) -> MigrationRollbackResult
```

### 3.4 story 契约

L0 写入 `modules/story/outline_state/contracts.py`，并在 `facade.py` 中做 stub。L3 实现
`outline_state/author_migration.py`。

```python
class AuthorMigrationStoryItem(BaseModel):            # extra="forbid"
    item_key: str; source_refs: list[str]; source_hash: str
    kind: Literal["arc", "thread", "foreshadowing", "chapter_plan"]
    title: str = Field(min_length=1, max_length=255)  # thread / foreshadowing 用作 name
    chapter_start: int | None = Field(None, ge=1); chapter_end: int | None = Field(None, ge=1)
    fields: dict[str, str] = {}
    # 每种 kind 的允许键：
    #   arc: arc_goal, core_conflict, climax, result, next_hook
    #   thread: thread_type, summary, visible_goal, hidden_truth
    #   foreshadowing: surface_meaning, hidden_meaning, seed_chapter, payoff_chapter, reinforce_chapters
    #   chapter_plan: must_happen（原文逐字）, goal, core_conflict, emotional_beat, must_not_happen
    related_entity_keys: list[str] = []           # world item_key 或已有 entity_id
    pov_entity_key: str | None = None
    decision: Literal["auto", "skip"] = "auto"
class AuthorMigrationOutlineInput(BaseModel):
    title: str | None = None; outline_markdown: str = Field(max_length=200_000)
    creative_core: dict[str, str]                 # 对齐 StoryOutlineCreativeCore: premise / tone_and_reader_promise / story_engine / ending_direction?
    policy: Literal["create_if_missing", "replace", "skip"]
class AuthorMigrationStoryRequest(BaseModel):
    migration_id: str; items: list[AuthorMigrationStoryItem] = Field(max_length=1500)
    outline: AuthorMigrationOutlineInput | None = None
    written_chapter_policy: Literal["reference_only", "link_scene"] = "reference_only"
class StoryMigrationItemPlan(BaseModel):
    item_key: str
    action: Literal["create", "planned_scene", "link_scene", "existing_ref", "fill_empty",
                    "conflict", "reference_only", "skip"]
    target_id: str | None = None; target_label: str | None = None
    fills: list[str] = []; conflicts: list[FieldConflict] = []; reason_code: str | None = None
class StoryMigrationPlan(BaseModel):
    items: list[StoryMigrationItemPlan]
    outline_action: Literal["create", "replace", "skip"] | None; fingerprint: str  # 指纹不含新实体 id
class StoryMigrationReceipt(BaseModel):
    applied_changes: list[MigrationAppliedChange]; outline_change: dict | None  # {revision_id, base_revision_id}

# story outline_state facade（加入 __all__）
async def plan_author_migration_structures(db, novel_id: str, request: AuthorMigrationStoryRequest, *,
        entity_refs: dict[str, str | None]) -> StoryMigrationPlan    # None = 本次新建、尚无 id
async def apply_author_migration_structures(db, novel_id: str, request: AuthorMigrationStoryRequest, *,
        entity_ids: dict[str, str], expected_fingerprint: str, authorized_by: str) -> StoryMigrationReceipt
async def rollback_author_migration_structures(db, novel_id: str, receipt: StoryMigrationReceipt, *,
        dry_run: bool) -> MigrationRollbackResult
```

`FieldConflict`、`MigrationAppliedChange` 和 `MigrationRollbackResult` 由 world contracts 定义。story 通过
`modules.world.contracts` 引用它们，这是允许的跨模块依赖。

### 3.5 会话表

L0 创建 model、迁移和 repository 骨架，L4、L5 使用。

- **表名**：`import_migration_sessions`，model `ImportMigrationSession` 放在 `imports/models.py`。`alembic/env.py` 已经 import 了 imports.models。
- **迁移文件**：`backend/alembic/versions/20261003_import_migration_sessions.py`。`down_revision` 以实施时的 `uv run alembic heads` 为准。
- **列**：

| 列 | 类型与说明 |
|---|---|
| `id` | UUID PK |
| `novel_id` | FK projects/novels，ON DELETE CASCADE，有索引 |
| `owner_id` | 有索引 |
| `status` | String(24)，取值 `draft` / `applied` / `rolled_back` / `partially_rolled_back` |
| `revision` | int，从 1 起，mapping、decisions 和 AI 结果写入时 +1，作 CAS 用 |
| `file_manifest` | JSON：`[{file_key, file_name, file_type, size, sha256, sheets:[{sheet_key, name, hidden, row_count, col_count, warnings}]}]` |
| `rows_json` | JSON：`{sheet_key: rows}`；采用或删除后置空 |
| `mapping_json` | JSON：`{sheets:[{sheet_key, kind, header_row, default_entity_type, columns:{column_key: target}}], options:{written_chapter_policy, outline_head_policy}}` |
| `decisions_json` | JSON：`{item_key: {action, relation_kind?, accept_ai?}}`，另含 `relation_kind_groups: {relation_type: kind}` |
| `plan_json` | JSON：最近一次 world/story 计划及其 fingerprint |
| `preview_hash` | String(64) |
| `ai_task_id` | 无额外说明 |
| `ai_status` | String(16)，取值 idle / queued / running / done / failed |
| `ai_scope_hash` | 无额外说明 |
| `ai_authorization` | JSON |
| `ai_result_json` | JSON |
| `receipt_json` | JSON：`{world: WorldMigrationReceipt, story: StoryMigrationReceipt, counts}` |
| `error_code` | String(64) |
| `applied_at` / `rolled_back_at` / `created_at` / `updated_at` | 时间戳 |

- **索引**：`(novel_id, created_at)`。

repository 方法（imports 内部，`spreadsheet_migration/repository.py`）：
- `create`
- `get(db, session_id, *, novel_id, owner_id, for_update=False)`
- `list_recent`
- `save_mapping(..., expected_revision)`
- `save_decisions(..., expected_revision)`
- `store_ai_result(db, session_id, *, novel_id, task_id, scope_hash, result)`
- `mark_ai_status(...)`
- `mark_applied(..., receipt)`：同时清空 rows
- `mark_rolled_back(...)`
- `delete`

### 3.6 HTTP API

L0 在 `spreadsheet_migration/schemas.py` 定义 Pydantic，L4 实现，L6 消费。前缀 `/api/imports/migrations`。

| 方法与路径 | 请求 | 响应 / 错误 |
|---|---|---|
| `POST /` multipart | `novel_id`, `files[]`（1–5 个） | 201 `MigrationSessionResponse`；400 类型/签名/超限（作者可读）；413 |
| `GET /?novel_id&limit&offset` | — | `{items:[{id, status, file_names, counts, created_at, applied_at, can_rollback}], total}` |
| `GET /{id}?novel_id` | — | `MigrationSessionResponse` |
| `GET /{id}/rows?novel_id&sheet_key&offset&limit≤200` | — | `{header:[str], rows:[{row, cells:[str]}], total}`；采用后返回 410 |
| `PUT /{id}/mapping` | `{novel_id, expected_revision, sheets:[{sheet_key, kind, header_row, default_entity_type?, columns:{column_key: target}}], options:{written_chapter_policy, outline_head_policy}}` | `MigrationSessionResponse`（含重算后的 preview）；409 revision |
| `POST /{id}/ai-runs` | `{novel_id, expected_revision, authorization_confirmed: true, operation_id, scope:{outline_sheet_keys:[], cleanup:[{sheet_key, column_key}]}}` | 202 `{task_id, status, reused}`；422 超预算或没有可用模型 |
| `PUT /{id}/decisions` | `{novel_id, expected_revision, decisions:[{item_key, action, relation_kind?, accept_ai?}], relation_kind_groups?:{relation_type: kind}}` | `MigrationSessionResponse` |
| `GET /{id}/rollback-preview?novel_id` | — | `{revertible:[{item_key, label}], kept:[{item_key, label, reason}]}` |
| `POST /{id}/apply` | `{novel_id, expected_preview_hash, confirmed: true}` | `{status, counts, receipt_summary}`；409 `migration_preview_stale`（附新 hash）或 `required_validation` |
| `POST /{id}/rollback` | `{novel_id, confirmed: true}` | `{status, reverted_count, kept:[{label, reason}]}` |
| `DELETE /{id}?novel_id&confirmed=true` | — | 204；删除后不可再撤销，界面需二次确认 |

`MigrationSessionResponse` 的字段：
- 基本信息：`id`、`status`、`revision`、`created_at`、`applied_at`、`rolled_back_at`
- `files`：`[{file_key, file_name, file_type, size}]`
- `sheets`：`[{sheet_key, file_key, name, hidden, kind, kind_suggested, header_row, row_count, columns:[{column_key, header, target, target_suggested}], sample_rows:[[str]] (≤5), warnings:[{code, message}]}]`
- `options`
- `preview`：为 null，或包含：
  - `preview_hash`、`validation_policy_active`
  - `counts{create, fill, adopt, existing, conflict, skip, relations, structures, reference_only}`
  - `world_items:[{item_key, label, type_label, action, target_id?, target_label?, fills:[field_label], conflicts:[{field_label, current_excerpt, incoming_excerpt}], similar:[{label}], source:{sheet_name, row}, decision, ai?:{available, passed, accepted}}]`
  - `relations:[{item_key, source_label, target_label, relation_type, relation_kind, kind_guessed, action, reason, source, decision}]`
  - `structures:[{item_key, kind, label, chapter_label, action, target_label?, reason, source, decision, ai?}]`
  - `outline:{action, title}|null`
- `ai`：`{status, task_id, estimate:{rows, chars, requests}, blocked_count}`
- `receipt_summary`：null，或 `{created, filled, adopted, relations, structures, outline, can_rollback}`
- `error`：null，或 `{code, message}`

响应不出现 raw JSON 或内部枚举文案。`target_id` 只用于生成跳转链接，界面不显示。

**preview_hash** = sha256(world.fingerprint, story.fingerprint, mapping_json, decisions_json, 已接受的 AI 条目, revision)。

**apply 在同一事务内**依次执行：
1. 重算 preview 并与 `expected_preview_hash` 比对；
2. `require_active_project_exclusive`；
3. world.apply；
4. story.apply（使用 world 回执中的 `entity_ids`）；
5. `mark_applied`；
6. commit。

各 facade 只 flush，DB 异常向上传播。

### 3.7 AI 契约

由 L5 实现。

- 任务类型 `spreadsheet_migration_ai`，root capability `imports.spreadsheet_migration`。
  - step 名：`imports.spreadsheet_migration.outline` 和 `imports.spreadsheet_migration.cleanup`。
- 对 L4 暴露的接口：

  ```python
  def estimate_ai_run(rows_by_sheet, mapping, scope) -> AiEstimate          # {rows, chars, packets, requests}
  async def submit_ai_run(db, *, novel_id, session, scope, operation_id) -> TaskRef  # {task_id, status, reused}
  def ai_items_for_planning(ai_result_json, decisions) -> AiPlanningInput  # 已通过审查且作者接受的条目
  ```

- 输出 schema 放在 `spreadsheet_migration/ai_schemas.py`，全部 `extra="forbid"`，长度上限参照 `story/outline_state/p20_schemas.py`：
  - `SpreadsheetOutlineConversion{creative_core?, arcs[], threads[], chapter_plans[{chapter_start, chapter_end, title, must_happen, goal, core_conflict, emotional_beat, pov_name}], foreshadowing[], unmapped_rows[]}`
    - 每项带 `proposal_ref`、`source_rows:[row_ref]`、`evidence`（逐字）和 `uncertain_fields`。
  - `SpreadsheetCellCleanup{fields:[{field: CharacterFieldName | "summary" | "public_info", value, evidence}], remainder}`
- 输入行格式：`{row_ref: "<sheet_key>:r<row>", cells: {列名: 值}}`，作为围栏内的不可信 JSON。
  - 附带的上下文只有已写章节号（只给数字）和已知对象名（名称与类型）。
- 输出不得包含 id、novel_id、status、source。

## 4. 并行车道

### 波次与依赖

```text
Wave 0（串行）：L0 契约冻结 ──提交──┐
Wave 1（并行）：L1 解析识别 │ L2 world 落库 │ L3 story 落库 │ L4 会话/API │ L5 AI │ L6 前端 │ L7a ADR/AGENTS
Wave 2（串行）：L8 集成验收 + L7b 文档全量
```

L1–L6 只依赖 L0 的契约，彼此没有代码依赖。合入顺序：L1 → L2 → L3 → L4 → L5 → L6 → L7a。
各车道的独占文件互不重叠，按理不会出现合并冲突。

### L0 契约冻结（集成者，Wave 0）

- **独占文件**：
  - `backend/pyproject.toml`、`backend/uv.lock`（执行 `uv add openpyxl defusedxml`）
  - `imports/spreadsheet_migration/{__init__,constants,schemas,repository}.py`
  - `parsing.py` / `classify.py` / `synonyms.py` / `planning.py` / `service.py` / `ai.py` / `ai_schemas.py` 的 stub（只有签名）
  - `imports/models.py`（新增 model）、Alembic 迁移文件
  - `modules/world/contracts.py`、`modules/world/facade.py`
  - `modules/world/services/worldbuilding/author_migration.py`（stub）
  - `modules/story/outline_state/contracts.py`、`.../facade.py`、`.../author_migration.py`（stub）
  - facade 公共面回归测试（`backend/tests/unit/test_facade_public_api.py` 及 story 对应测试）
- **完成标准**：
  - `make lint` 通过；
  - `make schema-check` 通过；
  - 公共面测试通过；
  - `uv run alembic upgrade head` 在 SQLite 上成功，在 PG 上用开发库验证；
  - 提交到集成分支（提交需用户授权）。

### L1 解析与识别

- **独占文件**：
  - `imports/parsers.py`：新增 `audit_zip_container` 并让 EPUB 改用它；新增 `parse_spreadsheet_file`
  - `imports/spreadsheet_migration/{parsing,classify,synonyms}.py`
  - `imports/tests/test_spreadsheet_parsing.py`、`test_spreadsheet_classify.py`
  - `imports/tests/spreadsheet_fixtures.py`：用 openpyxl 在测试中生成夹具
- **xlsx 解析要点**
  - 先做内容签名检查：
    - 必须以 `PK\x03\x04` 开头，且包含 `[Content_Types].xml` 和 `xl/workbook.xml`；
    - 拒绝 OLE `D0CF11E0`（.xls 或加密文件），提示“请在 Excel/WPS 中另存为 .xlsx”；
    - 拒绝 `xl/vbaProject.bin` 和 macroEnabled；
    - 拒绝含 DOCTYPE 或 ENTITY 的 xml/rels；
    - 拒绝不安全的成员路径，以及成员数或解压总量超限。
  - 加载：`openpyxl.load_workbook(BytesIO, read_only=False, data_only=True, keep_vba=False, keep_links=False)`。
    - 解析是同步函数，由 L4 通过 `asyncio.to_thread` 调用。
  - 单元格处理：
    - 合并单元格用左上角的值填充；
    - 日期转为 ISO 字符串；
    - 整数型浮点数转为 int 字符串；
    - 布尔值转为“是 / 否”；
    - 公式取缓存值，没有缓存值时留空，并给出 warning；
    - 图片和批注只计数并提示已忽略；
    - 隐藏表标记 `hidden=True`。
- **csv 解析要点**
  - 编码用 `parsers.detect_encoding`，覆盖 BOM 和 GBK。
  - 分隔符用 `csv.Sniffer` 识别，候选为 `,`、Tab、`;`。
  - `field_size_limit(MAX_CELL_CHARS+1)`。
  - 去掉 Notion 导出名称后缀 ` (https://www.notion.so/…)` 和 32 位 hex 后缀。
- **限额**：所有限额都按 §3.1 执行。超限一律明确拒绝该文件或该表，不静默截断。
- **识别规则**（`synonyms.py`）
  - 表类型：

    | 表类型 | 关键词或判断依据 |
    |---|---|
    | 人物 | 人物 / 角色 / 人设 / NPC / 人物小传 |
    | 世界对象 | 地点 / 势力 / 组织 / 门派 / 宗门 / 物品 / 道具 / 法宝 / 种族 / 功法 / 技能 / 设定 / 词条 / 名词 / 术语 / 世界观 |
    | 关系 | 两个名称列加一个关系列，或矩阵表（首行首列都是名称） |
    | 细纲 | 细纲 / 章纲 / 章节大纲，或“章”列加内容列 |
    | 卷纲 | 卷纲 / 分卷 / 阶段 |
    | 主线支线 | 主线 / 支线 / 剧情线 |
    | 伏笔 | 伏笔 / 埋线 |
    | 总纲 | 总纲 / 故事大纲 |
    | 自由文本大纲 | 像大纲但无可用列 |
    | 跳过 | 时间线 / 字数 / 写作计划 / 隐藏表 |

  - 列同义词：
    - 名称 / 姓名 / 角色名 / Name → name
    - 别名 / 外号 / 称号 / 又名 / 字 / 号 → aliases，按 `、,，;；/|` 和换行拆分
    - 简介 / 概要 / 描述 → summary；超过 5000 字时改投作者备注并给出 warning
    - 秘密 / 隐藏设定 / 真相 → hidden_truth
    - 身份 / 定位 / 职业 → role；超过 64 字转作者备注
    - 外貌、性格、目标 / 动机、恐惧、弱点、现状、立场 / 阵营、口癖 / 说话风格、人际 → 对应人物字段
    - 人物小传 / 背景 / 生平 → author_note（可交给 AI 整理）
    - 未识别列 → author_note
  - 实体类型：
    - 设定 / 词条 / 名词 / 术语 → `concept`（覆盖 `ENTITY_TYPE_MAP["设定"]="secret"`）
    - 法宝 / 装备 → item；门派 / 宗门 → faction；功法 → skill；境界 / 修炼体系 → power_system
    - 其余走 `normalize_author_entity_type`，可以产生作者自定义类型。
  - 关系种类关键词：
    - social：师 / 徒 / 父 / 母 / 兄 / 姐 / 妹 / 友 / 敌 / 恋 / 夫 / 妻 / 仇 / 盟 / 同门 / 上司 / 下属
    - spatial：位于 / 坐落 / 相邻
    - causal：导致 / 引发
    - epistemic：知道 / 隐瞒 / 怀疑
    - intentional：想要 / 追杀 / 保护 / 效忠
    - state：持有 / 拥有 / 成员 / 属于 / 隶属
    - temporal：之前 / 之后 / 继任
    - 兜底：两端都是人物时为 social，否则为 state，并标记为推测。
  - 表头行：在前 10 行内找短单元格多、同义词命中多的一行，跳过合并标题行。
- **测试**
  - 合并单元格、日期、缓存公式、隐藏表、首行是标题。
  - 恶意包：DOCTYPE、vbaProject、成员过多、zip 炸弹、路径穿越、改了后缀的 .xls。
  - CSV：BOM、GBK、Tab 分隔、内嵌换行、超长单元格。
  - 识别：“设定”判为 concept、矩阵关系表、Notion 后缀、别名拆分、中文章号区间。
  - EPUB 原有测试保持全绿。
- **自检**：`make test TESTS="backend/modules/imports/tests/test_spreadsheet_parsing.py backend/modules/imports/tests/test_spreadsheet_classify.py backend/modules/imports/tests/test_imports.py"`，以及 `make lint`。

### L2 world 落库

- **独占文件**：
  - `world/services/worldbuilding/author_migration.py`
  - `world/services/worldbuilding/applied_change_reversal.py`（新增）
  - `world/services/worldbuilding/focused_adoption.py`（把 `rollback` 的逆序循环抽到新文件，行为不变）
  - `world/tests/test_author_migration.py`
- **plan（只读）**
  - 名称和别名解析顺序：先匹配本次条目，再用 `find_working_entity_ids_by_names`，然后 `find_exact_identity_candidates`，最后用 `find_similar_entities` 召回相似名。
  - 每项的动作判定：

    | 情况 | 动作 |
    |---|---|
    | 同名同类型的 canonical 对象 | existing_ref；有空字段可补时为 fill_empty |
    | 同名候选 | adopt_existing（promote 后补空）；先预检 `require_fresh_understanding_source`，不新鲜则 conflict(stale_candidate) |
    | 兼容影子 | needs_review |
    | 名称相似但未经作者确认 | similar_name，不落库；作者选 different_object 后为 create |
    | 别名与其他对象重名 | alias_collision |
    | 已有对象的字段非空且不同 | conflict；hidden_truth 非空时作者可选 append_note |

  - 关系：
    - relation_kind 解析顺序：作者覆盖，然后 `suggest_relation_type`/`default_relation_kind`（`review_queue.py:321/340`），然后 L1 的 `guess_relation_kind`。
    - 去重：文件内按（源, 目标, 类型）去重，对称关系视同一条。
    - 与已有 canonical 边的处理：描述为空就补，描述相同为 existing_ref，不同为 conflict。
    - 端点缺失或有歧义时为 conflict。
    - 不对 canonical 边调用 `create_or_merge_relation`，避免描述被合并。
  - fingerprint 由涉及目标的 (id, updated_at) 和计划本身计算 stable_hash。
- **apply**
  1. 在行锁下重新 plan，与 `expected_fingerprint` 比对。
  2. 门禁只检查一次：`require_legacy_canon_write_allowed`。
  3. 写入：
     - 新实体：`WorldEntityService.create(..., status="canonical", created_by="spreadsheet_migration", approved_by=authorized_by, force_create=True, _validation_prechecked=True)`；
     - `content_json._meta = {source, spreadsheet_migration:{migration_id, source_ref, source_hash, authorized_by, applied_at}}`；
     - 人物：canonical 创建会自动生成 Character 行（`CharacterService.ensure_for_core_entity`）；之后用 `CharacterService.update` 只补空字段；
     - 别名：`EntityAliasService.create_alias(source="spreadsheet_migration", status="confirmed", _validation_prechecked=True)`；
     - 作者备注追加到 hidden_truth。
  4. 回执按 §3.3，不含正文。
- **rollback**
  - 用抽出的 reversal helper 逆序处理：当前状态哈希等于 after_hash 时，废弃（deprecated）或恢复 before；否则保留，原因 `modified_after_migration`。
  - 被外部关系或世界书引用的项保留，原因 `referenced`。
  - 回滚前写修订快照，回滚后标记上下文变化并请求 reannotation。
  - `dry_run` 只返回判定结果，不写入。
- **测试**
  - 动作：create、fill、conflict、adopt、stale candidate、影子、相似名、别名冲突。
  - 隔离：跨 novel 同名不匹配。
  - 门禁：policy 生效时零写入。
  - 关系：kind 解析；已有 canonical 边的描述保持不变。
  - 回滚：撤回、被修改后保留、被引用后保留；dry_run 不写入。
  - 健壮性：flush 异常向上传播。
  - 回归：focused 回滚测试全部保持通过。
- **自检**：`make test TESTS="backend/modules/world/tests/test_author_migration.py backend/modules/world/tests -k 'focused or adoption'"`。

### L3 story 落库

- **独占文件**：
  - `story/outline_state/author_migration.py`
  - `story/outline_state/story_outline_service.py`（新增 `clear_head_if_revision`）
  - `story/tests/test_author_migration_story.py`
- **映射**
  - arc → OutlineArc
  - thread → PlotThread（thread_type 不合法时用 sub）
  - foreshadowing → ForeshadowingPlan
  - chapter_plan：
    - 该章已被 active Scene 覆盖（chapter_ids 或 planned_chapter_range）：existing_ref
    - 未写章节：planned Scene，形状与 P20 `_apply_scenes`（`p20_service.py:938`）相同：`scene_chunks=[]`、`chapter_ids=[]`、`structure_meta.planning_state="planned"`，加 `planned_chapter_range`
    - 已写章节且策略为 `reference_only`：不写
    - 已写章节且策略为 `link_scene`：建 Scene 并关联 `chapter_ids`
  - 来源标记：
    - `Scene.source = "spreadsheet_migration"`
    - `provenance_meta` / `structure_meta = {source, migration_id, source_refs, authorized_by, adopted_at}`
    - status 写 canonical；字段允许值以各 Create schema 为准。
- **同名与重叠**：同名 thread/arc/伏笔只补空字段，其他差异为 conflict；卷的章节范围重叠为 conflict。
- **总纲**：经 `create_revision`（`story_outline_service.py:107`）写入。
  - `outline_markdown` 写作者原文。
  - `creative_core` 必须完整，缺失时为 conflict(`outline_core_missing`)，由作者在预览中补全或交给 AI。
  - `create_if_missing`：项目无 head 时才创建。
  - `replace`：以当前 head 为 base 追加新修订。
  - `skip`：不写。
- **rollback**
  - 资产：快照一致则废弃或恢复 before，否则保留。
  - 总纲：head 仍是本次创建的修订时，`apply_revision(base)` 回到基线修订；若本次创建的是首个修订，用 `clear_head_if_revision` 移除 head 指针，修订本身留在历史中；其他情况保留。
  - 先确认 `get_current`（`story_outline_service.py:39`）能处理没有 head 的情况。
- **测试**
  - Scene：planned、已有覆盖、两种已写章节策略。
  - 同名与重叠：同名补空、卷范围重叠。
  - 总纲：三种策略及其回滚。
  - 隔离：跨 novel。
  - 回归：deep import 的 scene 替换不会清理 spreadsheet_migration 来源的 Scene（`scene_replacement.py:_is_cleanable`）。
- **自检**：`make test TESTS="backend/modules/story/tests/test_author_migration_story.py"`。

### L4 会话、服务与 API

- **独占文件**：
  - `imports/spreadsheet_migration/{planning,service,api}.py`
  - `app/main.py`（挂载路由，紧挨 `imports_api.router`）
  - `imports/tests/test_spreadsheet_migration_service.py`
  - `imports/tests/test_spreadsheet_migration_api.py`
- **planning**
  - 按 mapping 把 rows 转成 world/story 请求：
    - 文件内同名同类型的行合并，值不一致时记为文件内冲突；
    - item_key 由 sheet_key、行号和名称确定性生成；
    - source_hash 为行单元格的 sha256。
  - 合并 AI 条目：只合并 `ai_items_for_planning` 返回的、已通过审查且作者接受的条目。AI 未覆盖或失败的行回落规则映射，原文写入 `must_happen` 或作者备注。
  - 默认大纲类表等待 AI 结果；作者选择“跳过 AI”后直接用规则映射。
- **service**
  - 上传：`require_active_project`，然后 `asyncio.to_thread(parse_spreadsheet_file)`，然后 classify，最后建会话。
  - 每个请求都按 (id, novel_id, owner) 加载会话，否则返回 404。
  - mapping、decisions 带 revision CAS，并重算 preview。
  - apply 按 §3.6 执行。
  - 读取会话时，对照任务的最终状态修正 `ai_status`，避免长期停在 running。
- **API**
  - 路由按 §3.6。
  - multipart 用 `_read_upload_file_in_chunks` 的分块上限模式。
  - 错误文案用作者语言，不回显单元格内容和路径。
- **测试**
  - 走全部路由。
  - 鉴权：401；demo/匿名 403（不在 demo 前缀白名单）；跨 owner 和跨 novel 返回 404。
  - 上传：413、扩展名或签名拒绝。
  - CAS 409；stale 409（附新 hash）；`Literal[True]` 校验。
  - 日志、回执、错误中不含正文（caplog）。
  - world/story/AI 的 facade 在本车道用 autospec 替身，L8 再换成真实链路。
- **自检**：`make test TESTS="backend/modules/imports/tests/test_spreadsheet_migration_service.py backend/modules/imports/tests/test_spreadsheet_migration_api.py"`。

### L5 AI 整理

- **独占文件**：
  - `imports/spreadsheet_migration/{ai,ai_schemas}.py`
  - `backend/prompts/spreadsheet_outline_convert.md`、`backend/prompts/spreadsheet_cell_cleanup.md`
  - `backend/tools/prompt_contracts/contracts/spreadsheet_{outline_convert,cell_cleanup}.json` 及对应 fixtures
  - `modules/evidence/compilation/knowledge/policies.py`：新增 `imports.spreadsheet_migration`，紧挨 `imports.targeted_completion`（:693）
  - `backend/tools/prompt_contracts/capability_bindings.py`：紧挨 :116
  - `imports/tasks.py`：handler
  - `infrastructure/tasks/api.py`：把任务类型加入 `_MODULE_API_ONLY_TASK_TYPES`（:66）
  - `imports/tests/test_spreadsheet_migration_ai.py`，以及 run-envelope 测试
- **step 实现**：仿照 `imports/targeted_completion.py`（`run_managed_structured` :244，`govern_group_output` :284）。
  - 调用：`run_managed_structured(..., max_fix_attempts=1, context_budget=ContextBudget(max_input_chars=100_000, max_output_chars=40_000))`。
  - 审查：`govern_group_output(capability="imports.spreadsheet_migration", sources=(GroupSource(source_key=f"sheet:{key}:rows:{a}-{b}", source_type="imported_assets", content_hash=...),), ...)`，最多返修一次。
- **确定性校验**
  - 引用的 row_ref 必须存在于本包；
  - evidence 是所引行的子串（空白归一后）；
  - 章号在合法范围内；
  - 字段在白名单内；
  - 长度不超限。

  不通过的项丢弃，该行回落规则映射。审查未通过的项标记 `passed=false`，不可被作者接受。
- **任务**
  - 注册：`@task_handler("spreadsheet_migration_ai", recovery_policy="auto_requeue", max_attempts=2, retry_transient_llm_errors=True, root_capability_id="imports.spreadsheet_migration", run_request_limit=<packets*6+2>)`。
  - 提交仿照 `modules/project/smart_dedup.py:33` `submit_scan`：`require_active_project`，然后 `get_operation_task`，然后 `build_project_llm_execution_snapshot`，最后 `enqueue_task_with_optional_operation`。
  - worker 用快照恢复客户端，`finally` 中 close。
  - 结果通过 repository 的 `store_ai_result` 写回，只有 `scope_hash` 一致才写。
  - 打包：每包 ≤`AI_PACKET_CHARS`，总包数 ≤`AI_MAX_PACKETS`；超出时返回 422，提示缩小范围。
- **Prompt 要求**
  - 只做忠实整理，不编造人物、关系、事件或章号。
  - 每项必须带 `source_rows` 和逐字 `evidence`。
  - 禁止输出 id、status、source。
  - 允许 `unmapped_rows`。
- **测试**
  - 用 DI 注入的 fake client 覆盖：schema 校验、子串校验、行引用、审查拦截、一次返修、超预算 422、scope_hash 漂移不写回。
  - 任务类型在模块 API 白名单中。
  - run envelope：仿照 `modules/story/tests/test_run_envelope_story.py`。
- **自检**：
  - `make prompt-contracts`
  - `make test TESTS="backend/modules/imports/tests/test_spreadsheet_migration_ai.py backend/tests/prompt_contracts"`

### L6 前端

- **独占文件**（`frontend-console/` 下）：
  - `api.js`：新增 `imports.migrations.{create, list, get, rows, saveMapping, startAi, saveDecisions, rollbackPreview, apply, rollback, remove}`；`create` 用 `uploadMultipart`。
  - `apiContracts.js`
  - `vue/views/project/components/SpreadsheetMigrationPanel.vue`
  - `vue/views/project/components/spreadsheetMigration/*.vue`：`MigrationUploadStep`、`MigrationSheetMappingStep`、`MigrationAiStep`、`MigrationPreviewStep`、`MigrationRecordList`
  - `vue/views/project/logic/spreadsheetMigration.js`：纯逻辑（标签、目标选项、决策 payload）
  - `vue/views/project/components/ImportDrawer.vue`
  - `vue/composables/useImportUpload.js`：新增 `SPREADSHEET_FILE_ACCEPT=".xlsx,.csv"` 和 10MB 校验；`IMPORT_FILE_ACCEPT` 不变
  - `shared/workflowProgress.js`：任务类型标签 `spreadsheet_migration_ai: "整理表格大纲"`
  - 来源徽标 `spreadsheet_migration: "表格迁移"`：`WorldEntityCollection.vue`、`WorldAliasesTab.vue`、`useWorldReview.js`、大纲结构徽标（`outlineStructure.js`）、`sceneModel.js`
  - `vue/views/world/library/WorldEntityDetail.vue`：profileFields 补 weakness、current_goal、stance、relationship_summary
  - 世界库空态和大纲结构空态的入口
  - `tests/vue/**` 下对应的 Vitest 用例
  - `e2e/spreadsheet-migration.spec.js`：由 L8 运行
- **交互**
  - 步骤：上传 → 核对表格（表类型、表头行、列映射、样例行）→ AI 整理（大纲类表默认预选；先显示行数、字数、调用次数并请作者确认，进度用 `WorkflowProgressCard`）→ 预览与冲突 → 确认采用 → 完成（查看世界库 / 撤销本次迁移）。
  - 预览分页签：人物与设定 / 关系 / 大纲结构 / 冲突 / 仅参考。
  - ImportDrawer 分“导入正文”“导入设定表格”两个页签，并提示：“已有人物表、设定表、大纲表？建议先导入表格再导入正文，深度导入会自动对上你的人物。”
- **状态覆盖**：首次进入、空态、加载、失败、409 后重新预览、离开后按记录恢复、窄屏卡片式映射。
- **文案**：只用作者语言，不出现 raw id、JSON、英文状态、canonical 或 session。
- **组件约束**：只通过 `vue/bridge/index.js` 访问基建；不用动态 `v-html`。
- **测试**：
  - 逻辑模块；
  - `api-contract.test.js`；
  - 映射与预览组件（含 409、空态、窄屏）；
  - ImportDrawer 页签：正文的 accept 不变。
- **自检**：`cd frontend-console && npm run lint && npm run test`。

### L7 文档

L7a 在 Wave 1 与其他车道并行，L7b 在 Wave 2 进行。

- **L7a 独占文件**：
  - `docs/adr/0030-spreadsheet-migration.md`，状态 Proposed，L8 验收后改为 Accepted
  - `docs/adr/README.md`
  - 根 `AGENTS.md`：增加一行边界
  - `backend/modules/world/AGENTS.md`：补充受限例外
  - `backend/modules/imports/AGENTS.md`：补充表格会话的保留规则
- **ADR-0030 要点**
  - 独立入口，正文白名单不变。
  - xlsx 作为有界的固定部件 OOXML 处理，不落盘，不执行公式或宏。
  - 确认即采用：owner 是授权人（ADR-0017 §4），validation policy 生效时失败关闭。
  - 不覆盖已有内容，只补空字段；未识别列进作者备注。
  - AI 只产出预览，按 ADR-0025 治理。
  - 会话表在草稿期暂存单元格，采用或删除后清空；回执不存正文。
  - 只通过 world/story 的窄 facade 落库。
  - 回滚的语义与限制。
  - 被拒方案：复用 adoption package、只落 candidate、AI 唯一路径、.xls/.et/.ods、Notion zip。
- **根 AGENTS.md 新增行**（放在“数据与安全”）：
  > 表格迁移只走 `/api/imports/migrations`（ADR-0030），仅收 `.xlsx/.csv`，不扩文稿白名单、不执行公式/宏；
  > 作者确认预览后经 world/story 窄 facade 落为已采用资产并带 `spreadsheet_migration` 来源与可撤销回执，
  > 同名只补空字段，冲突不落地；AI 整理仅预览。
- **L7b 独占文件**（L8 期间同步）：
  - 模块文档：`docs/modules/13_imports.md`、`02_world.md`、`14_frontend.md`，以及 story/outline 模块文档
  - 数据与 Prompt：`docs/01_数据库设计.md`、`docs/prompts/Prompt体系设计.md`
  - 用户文档：`docs/核心业务场景与预期行为.md`（新增“从其他工具迁移进行中的作品”场景）、`docs/new-user-guide.md`
  - `CONTEXT.md`：新增词汇“表格迁移、导入记录、作者备注”
  - 三个 README：imports、world、story
  - `docs/testing/technical-coverage.md`
  - 素材来源：各车道交接报告中的“文档要点”。

### L8 集成与验收（集成者，Wave 2）

1. 按顺序合入 L1–L7a。每合入一个就跑该车道的自检和 `make lint`。
2. 去掉 L4 的 facade 替身，补一组真实链路测试 `imports/tests/test_spreadsheet_migration_e2e.py`（SQLite）：
   上传 xlsx（人物 + 关系 + 细纲）→ 映射 → 预览 → 采用 → 世界库、关系和 Scene 都可见 → 撤销 → 状态恢复。
3. PostgreSQL 关键路径 `backend/tests/e2e/test_import_migrations_pg.py`，并加入 Makefile 的 `test-postgresql-critical` 列表：
   - 并发 apply 时只有一个成功，另一个 409；
   - deep import 持有排他锁时 apply；
   - 预览后实体被修改，apply 判为 stale；
   - 回滚与编辑竞争；
   - mapping 的 CAS；
   - 1000 行 apply 计时。批量太慢时在 world 内部加批量标志，不能跳过副作用。
4. 浏览器 e2e：用专用 PG 跑 `e2e/spreadsheet-migration.spec.js`，流程为上传 → 映射 → 采用 → 出现“表格迁移”徽标 → 撤销。
5. 真实文件验收（`external_data`）：
   - 来源：Excel（xlsx、GBK csv）、WPS、飞书、腾讯文档、Google 表格（xlsx、csv）、Notion csv；
   - 脱敏后放入 `backend/tests/fixtures/spreadsheets/`；
   - 没跑过真实文件的来源不对外宣称支持。
6. 真实模型验收：自由文本大纲表加人物小传。这一步消耗用户的 API 额度，执行前须单独征得用户确认。
   原始请求和输出留在仓库外，只提交去原文的账本（见 `testing-guide.md`“付费实测账本与证据”）。
7. 门禁：
   - `make docs-check BASE_REF=origin/main`
   - `make test-ci TEST_WORKERS=2`
   - `make prompt-contracts`
   - `make test-postgresql-critical`
   - `npm run test:e2e:smoke`
   - `git diff --check`
   - 前端人工走查：首次进入、空态、失败、冲突、恢复、窄屏。
8. L7b 完成后，把 ADR 改为 Accepted，更新任务记录。合并 main 需另行取得授权。

## 5. 单写者文件与冲突热点

| 文件 | 唯一写入者 |
|---|---|
| `backend/pyproject.toml`、`uv.lock`、Alembic 迁移、`imports/models.py`、world/story `contracts.py` 与 `facade.py`、公共面测试 | L0 |
| `imports/parsers.py` | L1 |
| `world/.../focused_adoption.py` | L2 |
| `story/.../story_outline_service.py` | L3 |
| `app/main.py` | L4 |
| `policies.py`、`capability_bindings.py`、`imports/tasks.py`、`infrastructure/tasks/api.py` | L5 |
| `frontend-console/api.js`、`apiContracts.js`、`shared/workflowProgress.js` | L6 |
| ADR、AGENTS、`docs/**`、README、`CONTEXT.md` | L7 |

热点处理：
- 某车道确实需要改 §3 契约时，先停在本地，报告集成者，由集成者在 L0 分支上修改并通知全部车道 rebase。
- 存在 storyforge-v6 等未合入的分支。若它先合入 main，集成分支需 rebase，并重新确认 Alembic head、`model_routing.py` 和 `capability_bindings.py` 的邻近改动。

## 6. 风险与待实测

- **批量性能**：每次 canonical 创建都会触发 synopsis 失效和 reannotation。L8 先实测 1000 行，再决定是否在 world 内部加批量处理。
- **Scene 重复**：planned Scene 之后再深度导入同一章，可能出现两个 Scene，P20 现在也是这样。本次只在文档说明，不修复。
- **作者自定义类型**：深度导入只按同类型的名称或别名精确复用，自定义类型不会自动与深度导入对齐。预览中要提示作者。
- **大文件内存**：openpyxl 非只读模式内存占用较高。10MB 上限配合解压总量上限，L1 用最大夹具测峰值内存。

## 7. 交接报告模板（每车道完成时提交给集成者）

```text
车道：Lx　分支：codex/spreadsheet-migration-<lane>　提交：<sha 或“未提交”>
已完成：
改动文件：（应全部在本车道独占清单内；如有例外逐条说明）
契约偏离：无 / 列出并说明原因（未经集成者同意不得偏离）
测试：命令 + 结果（通过数/失败数）；未运行的检查及原因
文档要点：需要写入 README/模块文档/ADR 的事实（供 L7b）
风险与待决：
```
