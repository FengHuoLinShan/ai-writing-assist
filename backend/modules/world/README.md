# Module: world / 世界对象与关系管理模块

## 定位

world 模块管理小说世界中的核心对象及其关系，是结构化创作的事实底座。

对象包括地点、组织、物品、事件、规则、能力体系、秘密、传说、资源、人物引用。

## 核心原则

- 对象抽取不是 NER，而是长期创作资产识别
- 手动创建对象默认直接写入 `status="canonical"`，并保留 `created_by` / `approved_by`；显式传入 `draft` / `candidate` 的旧调用仍保持原状态
- 手动 AI 补抽必须先通过 `POST /api/context/confirm` 确认“AI 参考资料”，再调用 `POST /api/world/entities/extract`
- AI 抽取对象以 `status="candidate"` 入库，等待用户确认、合并或忽略；不自动提升为正史
- 别名不建新对象，存储于 `core_entities.content_json.aliases` JSONB 字段
- 深度导入 Phase 2b 发现的别名以内联待复核形式写入 `content_json.aliases`，单条别名携带 `status/source/workflow_id/scene_id/confidence/needs_review` 元数据
- 待复核别名可在确认前修改目标对象、别名文本和别名类型；来源、workflow、Scene、引用和置信度作为只读证据保留
- “待处理”入口按对象 / 别名 / 关系三个子 tab 处理复核队列；对象库、别名、关系页仍保留全量管理能力
- `link_to_existing` / `alias_of_existing` 候选可在待确认对象队列中确认为已有对象别名，源候选标记 `status="merged"` 并记录 `resolved_as="alias"`，不硬删除、不提升为正史
- 深度导入 Phase 2b 发现的关系写入 `entity_relations(status="candidate")`，两端可解析到 canonical / draft / candidate 工作对象
- 待确认关系可在确认前修改源对象、目标对象、关系类型、描述和强度；引用和来源章节作为只读证据保留，复核审计写入 `review_meta`
- 人物扩展表 `characters` 保留历史独立 `aliases` JSONB 字段，新别名应优先写入 `core_entities.content_json.aliases`
- `characters` / `events` / `character_knowledge` 活跃扩展只能挂在同项目、类型匹配且已采用的 `CoreEntity` 下；列表与写作上下文默认排除父对象或 CoreEntity 目标已转为待处理/已归档的历史扩展行
- 对象分级：core / important / normal / temporary
- 版本回滚基于 `TextArchive` 归档与 `EntityRevision` 兜底（活跃回滚路由优先查询 `TextArchive`，无归档时回退到最近 `EntityRevision` 快照）

### 作者态投影

对象、关系、创设建议与地图 observation/fact 响应在保留原始
`status` / `review_state` / `fact_status` 的同时，附加稳定的作者视图字段：

- `display_state`: `active` / `review` / `archived`
- `source`: 来源模块或创建者
- `attention_reasons`: 如 `conflict` / `needs_review` / `low_confidence`
- `suggested_action`: 建议的下一步动作

`GET /api/world/entities?display_state=active|review|archived` 可以按作者态筛选；
旧 `status` 筛选与原始状态字段保持兼容。地图界面将 candidate / conflicted
统一表达为“待处理”，confirmed 表达为“已采用”；冲突仍作为
`attention_reasons=["conflict"]` 保留，不丢失原始审查态。

## 职责

- 世界对象 CRUD（CoreEntity / `WorldEntityService`）
- 对象关系管理（EntityRelation）
- 别名管理（`EntityAliasService`，内联于 CoreEntity.aliases JSONB，支持待复核别名元数据）
- 候选别名确认（将候选对象解析为目标对象别名，并复用关系迁移/去重逻辑）
- 对象去重（EntityDedupService）
- 对象融合建议（WorldEntityFusionService，LLM 只生成建议，用户确认后应用）
- 面向项目级智能去重的实体融合子 facade（`entity_facade.suggest_entity_fusion` /
  `entity_facade.apply_entity_fusion`；root `facade.py` 仅 re-export）
- 世界上下文/检索词典/批次（`EntityContextService`）
- 实体统计与自动抽取批次查询（`EntityStatsService`）
- 实体 embedding 回填（`EntityEmbeddingService`）
- 向其他模块提供世界上下文（`get_world_context`）
- 人物档案与知识边界（Character / CharacterKnowledge）

## 边界

明确不做：

- 人物档案管理 → character 已迁入 world，不再独立模块
- 对象 embedding 全量实时更新 → rag 模块
- 自动合并正史对象
- 复杂跨类型实体消歧
- 所有 Mention 实时 embedding
- 独立知识图谱数据库

## AI 抽取确认策略

- 手动 AI 抽取或补抽默认写入 `candidate`，不得自动提升为 `canonical`。
- 只有用户明确启动并确认的自动流水线可直接写入 `canonical`；这类路径必须保留来源、可编辑/可回滚标记，并有对应测试覆盖。
- 本模块不恢复旧 `entity_candidates` 表；候选状态由 `core_entities.status` 表达。
- `POST /api/world/entities/fusion-suggestions` 只创建异步建议任务，建议结果保存在
  `AsyncTask.result`；`POST /api/world/entities/fusion-suggestions/apply` 必须
  `confirmed=true` 才会写库。`canonical -> canonical` 合并还必须逐条显式
  `allow_canonical_merge=true`。
- 项目级“智能去重”按钮复用同一套 world 实体融合逻辑；它只改变入口和结果聚合，
  不放宽用户确认、正史二次确认或 novel_id 隔离规则。
- 候选合并/清洗完成后，响应会尽量返回 `affected_ids` / `merged_ids`；前端只能按精确 ID 更新本地候选列表，缺少这些字段时刷新当前 tab，不按名称或候选组猜测删除。
- 确认为别名不是深合并：仅写入目标别名、迁移/去重关系并标记源候选为 `merged`，不得合并 summary/public_info/hidden_truth 或人物扩展字段。
- `CreationSuggestion` 中的 `core_entity` / `core_entity_draft` 经用户确认后直接写入 `canonical`，并保留建议 ID、来源、证据与 `approved_by` 审计。
- `entity_relation` / `entity_alias` 建议必须通过各自的 schema 验证和领域服务写入；未支持的 `target_type` 直接拒绝，不得标记为已接受后空操作。
- 生成中心与手动 AI 章节补抽的新对象统一先写 `creation_suggestion_queue`。为保持旧 API / 批次读取契约，队列服务同时物化一条 `draft` / `candidate` 兼容影子，并以 `_meta.compatibility_shadow=true` 与 `suggestion_id` 关联；采用或编辑后采用时提升同一条对象，合并/设为别名时由队列原子裁决并归档同一影子，忽略时同步标记该影子为 `ignored`。待处理影子不能绕过队列直接 CRUD，所有裁决都必须经过建议队列的 compare-and-set 门禁。
- imports 模块的 deep-import Scene 抽取是用户明确启动的独立受控流水线，不调用 `EntityExtractionService`；该授权路径的 candidate 写入契约仍由 imports 模块拥有。

## 数据表

| 表名 | 用途 |
|------|------|
| `core_entities` | 统一核心实体正史库（原 `world_entities`） |
| `entity_relations` | 对象间关系边（原 `relationships`） |
| `events` | 事件扩展表（entity_id PK+FK → core_entities） |
| `characters` | 人物档案（entity_id PK+FK → core_entities） |
| `character_knowledge` | 人物知识边界 |
| `entity_revisions` | 实体快照版本表（旧版快照；当前活跃回滚优先使用 `TextArchive`，无归档时回退到 `EntityRevision`） |
| `map_configs` | 动态地图配置（世界/城市/区域/地下城，自引用树，PRD §4.1） |
| `map_tiles` | 六边形地形网格（轴向坐标 q,r，PRD §4.2） |
| `map_location_bindings` | 地点绑定（core_entities.entity_type=location → hex，PRD §4.3） |
| `map_location_layouts` | 地点布局节点（中心 hex、占用半径、锁定状态、快速创建/拖拽来源） |
| `map_markers` | 动态标记（P1 预留：character/event/item，按 Scene 时间层显隐，PRD §4.5） |
| `map_territory_tiles` | 势力范围（组织控制区域，可与地形/地点/标记叠加） |
| `map_terrain_layers` | 手绘地形图层（素材、透明度、显隐、锁定、层级） |
| `map_terrain_regions` | 手绘地形区域（一次连续手绘或可命名区域） |
| `map_terrain_patches` | 手绘地形 patch（region 覆盖的离散 hex） |
| `map_terrain_bindings` | 手绘地形区域与地点的用户确认绑定（footprint / influence） |
| `map_observations` | 地图观察事实候选（来源证据、置信度、审查状态；默认不污染正式事实） |
| `map_facts` | 已确认时间化地图事实（由 observation 确认生成，供世界动态地图消费） |
| ~~`entity_aliases`~~ | 已移除，别名存 `core_entities.content_json.aliases` JSONB |
| ~~`entity_candidates`~~ | 已废弃；候选对象存于 `core_entities.status="candidate"` |
| ~~`relationships`~~ | 已废弃，使用 `entity_relations` |

`character_knowledge.source_chapter_index` 表示人物学到该知识的章节。
读者/角色视角仅激活早于可见截止章的记录；无来源章节的旧数据默认排除，
只有显式标记 `is_public_baseline=true` 的开场公开知识例外。同章但没有更精确学习
位置的记录按保守规则排除。

### ORM 模型布局

`modules.world.models` 是兼容导出 package，导入该 package 会注册 world 所有
ORM 表到同一个 `core.base.Base.metadata`。具体模型按子域拆分：

- `models/core.py`：CoreEntity、Event、EntityRelation、EntityRevision、TextArchive。
- `models/character.py`：Character、CharacterKnowledge。
- `models/profiles.py`：世界资产 profile 与模板表。
- `models/worldbuilding.py`：生成模板、World Bible、知识标签、创设建议和冲突队列。
- `models/common.py`：共享 SQLAlchemy imports 与 pgvector/SQLite embedding column helper。

旧路径 `from modules.world.models import CoreEntity` 与 `import modules.world.models`
保持可用；兼容别名 `WorldEntity` 等仍从 package 顶层导出。

### core_entities 表核心字段

- `id` — UUID 主键
- `novel_id` — 项目 ID（FK → projects.id）
- `entity_type` — 对象类型（自由字符串，以下为常用示例：character / location / faction / item / concept / event / rule / power_system / secret / legend / resource）
- `name` — 对象名称
- `summary` — 概要
- `public_info` — 对外公开信息
- `hidden_truth` — 隐藏真相
- `content_json` — 扩展信息（JSONB，内含 `aliases` 等动态属性）
- `importance` — 重要性（0~1）
- `importance_level` — 重要性级别（core / important / normal / temporary）
- `reveal_level` — 揭示层级（author_only / hinted / revealed / fully_known）
- `status` — 状态（candidate / draft / canonical / deprecated / ignored / conflicted；`pending` 属于 async_tasks）
- `embedding_text` — 用于向量化的文本
- `embedding` — 向量（768 维，生产环境使用 pgvector bge-base-zh-v1.5）
- `search_text` — 用于 pg_trgm 模糊搜索的 PostgreSQL 生成列（name + aliases），业务层不得显式写入
- `pinyin_string` — name 的拼音字符串缓存（用于去重音似特征）
- `created_by` / `approved_by` — 创建/确认者

### entity_relations 表核心字段

- `id` — UUID 主键
- `novel_id` — 项目 ID
- `source_id` — 源对象 ID（FK → core_entities.id）
- `target_id` — 目标对象 ID（FK → core_entities.id）
- `relation_type` — 关系类型
- `description` — 关系描述
- `strength` — 关系强度（0~1）
- `quote` — 原文依据
- `review_meta` — 人工复核审计元数据（reviewed_by / reviewed_at / review_before / review_after）
- `status` — 状态（candidate / canonical / deprecated）
- `source_chapter_id` — 来源章节 ID
- `caused_by_event_id` — 导致此关系的事件 ID

`candidate` 关系必须经用户复核后进入 `canonical`。`canonical` 关系以
`(novel_id, source_id, target_id, relation_type)` 为数据库幂等键。关系写入走仓储层
upsert；调用方不应再实现“先查再插”的并发控制。关系复核确认走
`PATCH /api/world/relations/{rel_id}/review-edit`；旧 `PUT /relations/{rel_id}`
若变更 status，也会写入等价 `review_meta`，避免绕过审计。

### aliases（内联 JSONB）

存储于 `core_entities.content_json.aliases`，格式为列表：
```json
[
  {"alias": "别名文本", "type": "name|title|nickname|translation|abbreviation"}
]
```

- 别名不创建新实体行
- 去重检查：别名不与已有别名重复（大小写不敏感）
- `PATCH /api/world/entities/{entity_id}/aliases` 只更新复核元数据；编辑文本或移动目标必须走 `/aliases/edit`
- `POST /api/world/entities/{candidate_id}/resolve-as-alias` 将候选对象登记为目标对象别名，并把源候选移出待确认对象队列

### entity_revisions 表（legacy 快照兜底）

- 原用于实体快照版本管理
- `POST /api/world/entities/{entity_id}/rollback` 是当前活跃的版本回滚路由，请求体：`{ "target_scene_index": 12 }`；由 `EntityRevisionService.rollback_to_scene_index` 实现，优先使用 `TextArchive`，无归档时回退到最近 `EntityRevision`
- `POST /api/world/entities/{entity_id}/rollback-by-revision` 是 `entity_revisions` 的兼容路由，按显式 `revision_id` 回滚
- `EntityRevisionService` 同时承担活跃回滚实现与 legacy 兼容，不应再被描述为仅 read/compat

### map_observations / map_facts 表

- `map_location_bindings` / `map_location_layouts` / `map_markers` /
  `map_territory_tiles` / `map_terrain_bindings` 是实体拥有的正式地图图层：
  新建或更新时关联实体必须为 `canonical`，且继续校验 `novel_id` 与实体类型。
  默认聚合状态和各图层独立列表只返回 canonical owner；历史
  `draft` / `candidate` owner 只进入显式 candidate preview，归档 owner 默认隐藏。
  `GET /api/world/maps/{map_id}/terrain?include_candidates=true` 可显式返回
  `candidate_bindings`，默认 `bindings` 只包含 confirmed 且 canonical-owner 的绑定。
- `map_configs.parent_entity_id` 和已确认的 `map_terrain_bindings` 同样只能引用已采用的 location；候选地形绑定可保留预览，但采用前会重新校验地点状态。
- `map_observations` 是世界动态地图的证据层：deep import `delta_events`、即时分析或人工编辑先写入 observation，默认 `review_state="candidate"`。
- observation 必须能说明目标名称/类型、动态类型、时间锚点、空间锚点、来源引用、证据摘要、置信度和审查状态；目标实体或地图尚未解析时可为空，但不得存入跨 `novel_id` 的实体引用。
- `map_facts` 是正式时间化地图事实，由用户确认 observation 后生成，默认 `fact_status="confirmed"`。
- observation 可在确认前编辑目标名称/类型、动态类型、时间/空间锚点、字段差异、来源引用、证据文本和置信度；确认时 `map_facts` 复制编辑后的 observation 字段。
- `PATCH /observations/{id}` 只能更新候选字段或把 `review_state` 设为 `candidate` / `ignored` / `conflicted`；不得通过 PATCH 直接设为 `confirmed`。正式确认必须走 `/confirm`，以保证生成或复用对应 `map_facts`。
- 忽略候选只更新 `review_state="ignored"`，不硬删除候选记录。
- 深度导入仍保留 `memory.delta_log`，同时把每条 `delta_event` 接入 `map_observations` 候选流；该接入不自动写正式 `map_facts`。
- 地图移动解释使用 `dynamic_type="movement_explanation"`，地图冲突使用 `dynamic_type="map_conflict"`；二者复用 observation/fact 流，不新增独立冲突表。
- 写作冲突检查通过 `summarize_scene_map_for_writing(..., include_candidates=False)` 消费 Scene 地图摘要，默认只返回已确认事实；用户在写作页显式勾选包含待确认对象时才会纳入 candidate observation，并在 writing 问题项标记 `needs_review`。

## 对外契约（contracts.py）

```python
@dataclass(frozen=True)
class CoreEntityContract:
    novel_id: str
    entity_id: str
    entity_type: str
    name: str
    summary: str | None = None
    public_info: str | None = None
    hidden_truth: str | None = None
    importance: float = 0.5
    importance_level: str = "normal"
    reveal_level: str = "author_only"
    status: str = "canonical"
    display_state: str = "active"
    source: str | None = None
    attention_reasons: list[str] = field(default_factory=list)
    suggested_action: str | None = None

@dataclass(frozen=True)
class EntityRelationContract:
    novel_id: str
    relation_id: str
    source_id: str
    target_id: str
    relation_type: str
    description: str | None = None
    strength: float = 0.5
    quote: str | None = None
    status: str = "canonical"
    display_state: str = "active"
    source: str | None = None
    attention_reasons: list[str] = field(default_factory=list)
    suggested_action: str | None = None

@dataclass(frozen=True)
class EntityRevisionContract:
    """版本快照契约（legacy，活跃回滚优先使用 TextArchive，无归档时回退到 EntityRevision）"""
    entity_id: str
    revision_id: str
    revision_reason: str = "ai_import"
    created_at: str | None = None

@dataclass(frozen=True)
class DuplicateSuggestion:
    candidate_id: str = ""
    candidate_name: str = ""
    existing_entity_id: str = ""
    existing_entity_name: str = ""
    similarity_score: float = 0.0
    match_method: str = ""
    action: str = "needs_user_decision"

@dataclass(frozen=True)
class MergeResult:
    target_entity_id: str
    candidate_entity_id: str
    aliases_inherited: int = 0
    relations_migrated: int = 0
    relations_deduplicated: int = 0
    self_loops_cleaned: int = 0
    character_synced: bool = False
    conflicts_archived: int = 0

@dataclass(frozen=True)
class ResolveResult:
    action: str  # "merged" | "promoted" | "needs_user_decision"
    merge_result: MergeResult | None = None
    promoted_entity_id: str | None = None
    suggestions: list = field(default_factory=list)
```

## 地图内部结构

`backend/modules/world/services/` 已按领域拆成子包：

- `services/core/`：核心实体、人物、事件、关系、去重、抽取、版本和回滚。
- `services/map/`：地图配置、tile、marker、territory、observation/fact、dashboard、playback、动态队列。
- `services/worldbuilding/`：世界书页面、模板、投影、作者资料整理和上下文摘要。
  其中 `worldbuilding_service.py` 是旧 import path 兼容 hub；实际实现按概念拆到
  `profile_service.py`、`world_bible_service.py`、`suggestion_queue_service.py`、
  `knowledge_tag_service.py`、`reader_safety_service.py`、`conflict_queue_service.py`
  和 `activation_preview_service.py`。
- `services/common.py`：跨子包通用 helper。
- `services/__init__.py`：顶层 re-export hub，保留常用 service 和 helper 的旧聚合入口。
- `services/map_service.py`：历史兼容导出层，不承载业务逻辑。

`modules.world.services.map_service` 保留旧测试和 API 路由 import 路径；具体地图实现位于 `services/map/`：

- `map_templates.py`：初始地形模板和详图 tile 生成。
- `map_config_service.py` / `map_tile_service.py` / `map_location_binding_service.py`：地图配置、tile 批量编辑、地点绑定。
- `map_marker_service.py` / `map_territory_service.py`：动态标记和势力范围。
- `map_dynamic_service.py`：保留 `MapDynamicFactService` 名称，作为 observation、fact、dashboard、playback、open target 的兼容 facade。
- `map_observation_service.py` / `map_fact_service.py`：观察事实候选、确认流转和正式事实状态。
- `map_dashboard_service.py` / `map_playback_service.py` / `map_open_target_service.py`：只读派生视图、播放事件流和地图打开目标。
- `map_dynamic_helpers.py`：动态地图 formatter、risk/priority/label、UUID 安全解析、空间锚点校验等私有 helper。
- `map_state_assembler.py`、`map_scene_summary.py`、`map_terrain.py`、`map_location_layout.py`、`map_quick_create.py`：独立地图入口，不通过 `map_service.py` 承载业务实现。

## Facade

Root `facade.py` 是纯 re-export hub，不定义 async wrapper 或承载业务编排；
旧 `modules.world.facade.*` import path 保持可用。具体薄委托按子域落在
`entity_facade.py`、`character_facade.py`、`event_facade.py`、`map_facade.py`
和 `worldbuilding_facade.py`。

`worldbuilding_facade.py` 承载世界书上下文激活相关入口：
`preview_worldbuilding_activation()` 调用确定性 activation preview 服务；
`mark_worldbuilding_context_stale()` 保持函数内 lazy import `modules.context.facade`，
避免扩大 context ↔ world 循环 import 风险。

`get_world_background()` 返回只读的 `WorldBackgroundBundleContract`。它从世界对象、
关系、已确认地图事实和人物知识边界派生 token-aware 条目，供 context 编译；不拥有
新的正史表，也不写回任何事实。

```python
# ---- CoreEntity ----
async def list_entities(db, novel_id, *, entity_type=None, statuses=None, display_state=None, limit=100) -> list[dict]
async def list_entity_terms(db, novel_id, *, limit=500) -> list[dict]
async def create_entity(db, novel_id, data: dict) -> dict
async def count_entities(db, novel_id, *, status_filter=None) -> int
async def backfill_entity_embeddings(db, novel_id, *, batch_size=64) -> int

# ---- Entity Context ----
async def get_world_context(db, novel_id, entity_ids=None, ..., include_review=False) -> WorldContextBundle
async def expand_related_entities(db, novel_id, seed_entity_ids, depth=1, limit=20) -> list[CoreEntityContext]

# Entity extraction is owned by imports `world_objects` deep-import stage.
# World no longer exposes a parallel `run_entity_extraction` facade.

# ---- Dedup ----
async def find_similar_entities(db, novel_id, name, aliases=None, ...) -> list[DuplicateSuggestionResult]
async def merge_candidate_into_entity(db, novel_id, candidate_id, target_entity_id) -> MergeResult
async def suggest_entity_fusion(db, novel_id, *, entity_type=None, status=None, ...) -> dict
async def apply_entity_fusion(db, novel_id, *, confirmed: bool, suggestions: list[dict]) -> dict

# ---- Relationships (thin proxy) ----
async def find_entity_id_by_name(db, novel_id, name, entity_type=None) -> str | None
async def upsert_relationship(db, novel_id, source_id, target_id, ...) -> None

# ---- EntityRelation ----
async def get_entity_relations(db, novel_id, skip=0, limit=100) -> tuple
async def create_relation(db, novel_id, data: dict) -> EntityRelationResponse
async def upsert_relation(db, novel_id, source_id, target_id, relation_type, ...) -> EntityRelationResponse

# ---- Events ----
async def create_event(db, novel_id, data: dict) -> dict
async def get_events_context(db, novel_id, limit=50) -> EventsContextBundle
async def get_full_state(db, novel_id) -> dict

# ---- Map dynamic facts ----
async def create_map_observation_from_delta_event(db, novel_id, *, event: dict, scene_index: int, ...) -> dict
async def summarize_scene_map_for_writing(db, novel_id, scene_id, *, include_candidates=False) -> dict

# ---- Worldbuilding ----
async def preview_worldbuilding_activation(db, novel_id, *, entity_ids=None, ...) -> dict
async def mark_worldbuilding_context_stale(db, novel_id, *, reason: str, asset_id="worldbuilding") -> int

# ---- EntityRevision (legacy rollback by revision_id) ----
async def get_entity_revisions(db, novel_id, entity_id, skip=0, limit=20) -> dict
async def rollback_to_revision(db, novel_id, entity_id, revision_id) -> dict

# ---- Character ----
async def create_character(db, novel_id, name, world_entity_id=None) -> CharacterResponse
async def list_characters(db, novel_id, skip=0, limit=100) -> tuple
async def get_characters_context(db, novel_id, character_ids, ...) -> CharacterContextBundle
async def get_character_knowledge_context(db, novel_id, character_id, target_ids=None) -> list
async def get_character_knowledge_entries(db, novel_id) -> list[dict]
async def filter_context_by_character_knowledge(db, novel_id, character_id, context_items) -> list[dict]
async def find_character_id_by_name(db, novel_id, name) -> str | None
async def update_character_location(db, novel_id, character_id, location_id, ...) -> None
async def get_characters_at_location(db, novel_id, location_id) -> list[dict]
async def get_character_location_id(db, novel_id, character_id) -> str | None
async def get_character_id_by_world_entity(db, novel_id, entity_id) -> str | None
```

`summarize_scene_map_for_writing` 返回写作模块可消费的轻量 Scene 地图摘要，包括主地点、角色/事件/势力/风险、打开地图目标和候选支持状态。它是 world → writing 的稳定边界；writing 不直接读取 `map_observations` / `map_facts` 内部表。
默认主地点只从 `canonical` 绑定推导；只有调用方显式传入
`include_candidates=True` 时才可纳入历史 `draft` / `candidate` 绑定，且响应会以
`depends_on_candidate=true` 和 `candidate_review_state` 标明尚未采用。

`get_world_context` 默认在查询层只返回 `canonical`，不会泄漏待处理对象。
只有明确需要 working context 的调用方才传 `include_review=True`，此时额外
包含 `draft` / `candidate` / `conflicted`，但始终排除已归档状态。
`compatibility_shadow` 在待处理期间只使用 `draft` / `candidate`，不会进入默认 active context；它只用于旧读取契约与可回滚迁移。队列采用后同一对象转为 `canonical`、可正常编辑，拒绝后转入 `ignored` 历史。

## API 路由

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/api/world/entities` | 世界对象列表；可按原始 `status` 或 `display_state` 筛选，`q` 支持名称、别名和描述的模糊搜索（名称/别名优先） |
| POST | `/api/world/entities` | 手动创建世界对象；未传 `status` 时默认已采用 |
| GET | `/api/world/suggestions` | 创设建议队列，响应包含作者态投影 |
| POST | `/api/world/suggestions/{suggestion_id}/confirm` | 确认建议；支持对象、关系、别名与世界书目标 |
| POST | `/api/world/suggestions/{suggestion_id}/edit-confirm` | 编辑世界对象建议并原子采用 |
| POST | `/api/world/suggestions/{suggestion_id}/merge` | 将世界对象建议合并到已采用对象 |
| POST | `/api/world/suggestions/{suggestion_id}/resolve-as-alias` | 将世界对象建议设为已采用对象的别名 |
| POST | `/api/world/suggestions/{suggestion_id}/reject` | 拒绝建议 |
| POST | `/api/world/object-draft-chat` | 生成中心自由共创聊天；不写库 |
| POST | `/api/world/object-drafts/generate` | 将生成中心聊天/粘贴内容收束为待处理建议；同时返回兼容草稿视图 |
| GET | `/api/world/generation-prompt-templates` | 生成中心 Prompt 模板列表（含内置模板） |
| POST | `/api/world/generation-prompt-templates` | 创建用户自定义 Prompt 模板 |
| POST | `/api/world/generation-prompt-templates/validate` | 校验模板变量、危险指令和输出契约 |
| POST | `/api/world/generation-prompt-templates/preview` | 预览模板渲染结果；不调用 LLM、不写库 |
| GET | `/api/world/generation-prompt-templates/{template_id}` | 模板详情 |
| PUT | `/api/world/generation-prompt-templates/{template_id}` | 更新模板并生成版本记录 |
| DELETE | `/api/world/generation-prompt-templates/{template_id}` | 软归档用户模板 |
| GET | `/api/world/generation-prompt-templates/{template_id}/revisions` | 模板版本历史 |
| POST | `/api/world/generation-prompt-templates/{template_id}/copy` | 复制内置模板为用户模板 |
| POST | `/api/world/entities/extract` | 手动世界对象补抽；必须携带 `context_confirmation_id` |
| GET | `/api/world/entities/{entity_id}` | 对象详情 |
| PUT | `/api/world/entities/{entity_id}` | 更新对象 |
| DELETE | `/api/world/entities/{entity_id}` | 删除对象 |
| POST | `/api/world/entities/{entity_id}/promote` | 将草稿/候选实体提升为正史 |
| POST | `/api/world/entities/{candidate_id}/resolve-as-alias` | 将候选确认为目标对象别名 |
| GET | `/api/world/entities/{entity_id}/relations` | 实体关系列表 |
| DELETE | `/api/world/entities/{entity_id}/aliases` | 删除别名 |
| PATCH | `/api/world/entities/{entity_id}/aliases/edit` | 编辑/移动并确认别名 |
| GET | `/api/world/entities/{entity_id}/revisions` | 版本历史（legacy，只读兼容） |
| POST | `/api/world/entities/{entity_id}/rollback` | 回滚到指定 scene_index（优先 TextArchive，无归档时回退到 EntityRevision） |
| POST | `/api/world/entities/{entity_id}/rollback-by-revision` | 按 revision_id 回滚（`entity_revisions` 兼容） |
| GET | `/api/world/aliases` | 别名列表 |
| POST | `/api/world/aliases` | 添加别名 |
| GET | `/api/world/entity-batches` | 实体批次分组列表 |
| GET | `/api/world/relations` | 关系列表（v3） |
| POST | `/api/world/relations` | 创建关系（v3） |
| PUT | `/api/world/relations/{rel_id}` | 更新关系（v3） |
| PATCH | `/api/world/relations/{rel_id}/review-edit` | 编辑待确认关系并确认 |
| DELETE | `/api/world/relations/{rel_id}` | 删除关系（v3） |
| GET | `/api/world/events` | 事件列表 |
| POST | `/api/world/events` | 创建事件 |
| GET | `/api/world/events/{entity_id}` | 事件详情 |
| PUT | `/api/world/events/{entity_id}` | 更新事件 |
| DELETE | `/api/world/events/{entity_id}` | 删除事件 |
| GET | `/api/world/characters` | 人物列表 |
| POST | `/api/world/characters` | 创建人物 |
| GET | `/api/world/characters/{character_id}` | 人物详情 |

### AI 参考资料确认

- `POST /api/world/entities/extract` 的确认 action 为 `world.entities.extract`。
- entity extraction、entity fusion、对象草稿和世界书生成通过 project runtime seam 消费项目 profile；
  extraction 在成功、异常和取消路径都由 context manager 关闭 client；
  Mock-only 测试兼容分支不是生产 fallback。
  LLM 输出继续只形成 suggestion/draft，不直接成为 canonical。
- 补抽结果写入 `context_confirmations.result_refs`，类型为 `world_entity`。
- 候选提升、合并、重命名或忽略会将相关确认记录标记为 `needs_review` 或 `stale_context`，并写入 `stale_reasons`。
- 生成中心 Chatbox 的自由聊天不创建确认记录，也不写库；只有
  `POST /api/world/object-drafts/generate` 会创建待处理 `CreationSuggestion`。响应中的
  `entity` 是保留旧 wire contract 的 `status="draft"` 兼容影子，`suggestion` 才是采用流的权威对象；确认后原地提升该影子为 `canonical`。
- 生成中心 Prompt 模板按 `novel_id` 隔离；内置模板是只读虚拟模板，自定义模板支持
  `version_number`、内容 hash 和 revision 历史。使用 `template_id` 生成时会在 LLM
  调用前做 P1 阻断校验，并把模板版本/hash 写入草稿 `_meta`，用于提示模板漂移。
- 模板 `validate` / `preview` 不调用 LLM、不写世界对象；preview 只回显模板片段，
  长变量值会截断，避免完整正文或隐藏 prompt 泄漏。P1 会阻断保存和生成，P2/P3
  仅提示。`template_version` 过期会返回 409
  `template_version_conflict`，前端提示刷新或重新选择模板。
- 软归档模板不会出现在默认列表中，也不能再按 id 读取、更新或用于生成；需要继续
  编辑时应从内置模板或现有模板复制为新的自定义模板。

生成中心前端 E2E 需要使用 `frontend-console/playwright.config.js`，不要从仓库根目录
直接传 `frontend-console/e2e/generate.spec.js`。推荐命令：

```bash
make generate-e2e
# 等价于：
cd frontend-console && BACKEND_PORT=18000 FRONTEND_PORT=18080 npx playwright test e2e/generate.spec.js
```

| 方法 | 路径 | 用途 |
|------|------|------|
| PUT | `/api/world/characters/{character_id}` | 更新人物 |
| DELETE | `/api/world/characters/{character_id}` | 删除人物 |
| GET | `/api/world/characters/{character_id}/knowledge` | 人物知识边界列表 |
| POST | `/api/world/characters/{character_id}/knowledge` | 添加人物知识 |
| PUT | `/api/world/knowledge/{knowledge_id}` | 更新人物知识 |
| DELETE | `/api/world/knowledge/{knowledge_id}` | 删除人物知识 |
| GET | `/api/world/maps` | 地图列表（?parent_map_id，PRD §6.1） |
| POST | `/api/world/maps` | 创建地图（含初始地形生成） |
| GET | `/api/world/maps/{map_id}` | 地图详情 |
| GET | `/api/world/maps/scene-summary` | 写作页 Scene 地图摘要 |
| GET | `/api/world/maps/open-target` | 统一地图打开目标（scene / focus entity / fallback） |
| GET | `/api/world/maps/quick-create/context` | 快速创建上下文（默认 canonical，可显式包含 candidate） |
| POST | `/api/world/maps/quick-create/preview` | 快速创建预览草稿；不落库、不识别正文、不创建世界对象 |
| POST | `/api/world/maps/quick-create/confirm` | 确认快速创建，一次只写入一张地图；未传 `layouts` 时写入全部预览地点，传入 `layouts` 时只写入选中地点，`layouts=[]` 不写地点布局/绑定/fact |
| PATCH | `/api/world/maps/{map_id}` | 更新地图配置 |
| DELETE | `/api/world/maps/{map_id}` | 删除地图（硬删，前端二次确认） |
| POST | `/api/world/maps/{map_id}/generate` | 快速生成详图地形（中心 city + 外 road） |
| GET | `/api/world/maps/{map_id}/state` | 地图聚合状态（map+面包屑+地形+绑定，PRD §6.2） |
| GET | `/api/world/maps/{map_id}/dashboard` | 世界动态总控台派生状态（首屏层、动态队列、检查器、批量分组） |
| GET | `/api/world/maps/{map_id}/playback` | 世界动态播放派生状态（typed observation 轨道和事件） |
| GET | `/api/world/maps/{map_id}/location-layouts` | 地点布局节点列表 |
| PUT | `/api/world/maps/{map_id}/location-layouts` | 覆盖保存地点布局节点（拖拽、锁定、+/-） |
| PATCH | `/api/world/maps/{map_id}/tiles` | 批量编辑地形（PRD §6.3） |
| GET | `/api/world/maps/{map_id}/terrain` | 手绘地形图层/区域/patch/绑定聚合状态 |
| PUT | `/api/world/maps/{map_id}/terrain/layers/{layer_id}/patches` | 覆盖保存某手绘地形图层最终 patches |
| POST | `/api/world/maps/{map_id}/terrain/regions/{region_id}/bindings` | 创建地形区域与地点绑定 |
| PATCH | `/api/world/maps/{map_id}/terrain/bindings/{binding_id}` | 更新地形绑定状态或类型 |
| POST | `/api/world/maps/{map_id}/location-bindings` | 批量创建地点绑定（PRD §6.4） |
| PATCH | `/api/world/maps/{map_id}/location-bindings/{binding_id}` | 更新地点绑定 |
| DELETE | `/api/world/maps/{map_id}/location-bindings/{binding_id}` | 删除地点绑定 |
| GET | `/api/world/maps/{map_id}/markers` | 动态标记列表（P1，可带 scene_id） |
| POST | `/api/world/maps/{map_id}/markers` | 创建动态标记（P1） |
| PATCH | `/api/world/maps/{map_id}/markers/{marker_id}` | 更新动态标记（P1） |
| DELETE | `/api/world/maps/{map_id}/markers/{marker_id}` | 删除动态标记（P1） |
| GET | `/api/world/maps/{map_id}/territories` | 势力范围列表（P2） |
| POST | `/api/world/maps/{map_id}/territories` | 批量创建势力范围（P2） |
| PATCH | `/api/world/maps/{map_id}/territories/{territory_id}` | 更新单格势力范围样式（P2） |
| DELETE | `/api/world/maps/{map_id}/territories/{territory_id}` | 删除单格势力范围（P2） |
| DELETE | `/api/world/maps/{map_id}/territories` | 按组织删除全部势力范围（P2） |
| GET | `/api/world/maps/{map_id}/focus` | 聚焦模式：仅返回指定组织势力范围（P2） |
| GET | `/api/world/maps/{map_id}/observations` | 地图观察事实候选列表，可按 `review_state` 过滤 |
| POST | `/api/world/maps/{map_id}/observations` | 创建地图观察事实候选 |
| PATCH | `/api/world/maps/{map_id}/observations/{observation_id}` | 更新 observation 候选字段或候选审查状态（不直接确认） |
| POST | `/api/world/maps/{map_id}/observations/batch-review` | 批量确认、忽略或标记冲突候选 observation |
| POST | `/api/world/maps/{map_id}/batch-actions` | 批量动作入口：候选确认/忽略/冲突、fact 状态、图层可见性 patch |
| POST | `/api/world/maps/{map_id}/observations/{observation_id}/confirm` | 确认 observation 并生成/复用正式 `map_facts` |
| POST | `/api/world/maps/{map_id}/observations/{observation_id}/ignore` | 忽略 observation，不生成正式事实 |
| GET | `/api/world/maps/{map_id}/facts` | 已确认地图事实列表，可按 `fact_status` 过滤 |
| PATCH | `/api/world/maps/{map_id}/facts/{fact_id}` | 软更新地图事实状态（confirmed / rolled_back / deprecated） |

## 依赖

- `core.database` — 数据库连接
- `core.base` — Base ORM、UUIDMixin、TimestampMixin、StatusMixin、NovelMixin
- `core.dependencies` — DbSession
- `shared.enums` — EntityType、ObjectStatus、Visibility、CandidateAction 等
- `shared.types` — NovelID、EntityID 等
- `shared.constants` — DEFAULT_PAGE_SIZE、相似度阈值

## 测试方式

```bash
cd backend
python -m pytest modules/world/tests/ -v
```

## MVP

实现世界对象 CRUD、关系管理、基础别名管理、关系一跳/二跳扩展、规则去重、人物档案与知识边界。
