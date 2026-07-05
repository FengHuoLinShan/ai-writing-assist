# Module: world / 世界对象与关系管理模块

## 定位

world 模块管理小说世界中的核心对象及其关系，是结构化创作的事实底座。

对象包括地点、组织、物品、事件、规则、能力体系、秘密、传说、资源、人物引用。

## 核心原则

- 对象抽取不是 NER，而是长期创作资产识别
- AI 抽取对象默认以 `status="candidate"` 入库，等待用户确认后再进入正史
- 手动 AI 补抽必须先通过 `POST /api/context/confirm` 确认“AI 参考资料”，再调用 `POST /api/world/entities/extract`
- AI 抽取对象以 `status="candidate"` 入库，等待用户确认、合并或忽略；不自动提升为正史
- 别名不建新对象，存储于 `core_entities.content_json.aliases` JSONB 字段
- 深度导入 Phase 2b 发现的别名以内联待复核形式写入 `content_json.aliases`，单条别名携带 `status/source/workflow_id/scene_id/confidence/needs_review` 元数据
- 深度导入 Phase 2b 发现的关系写入 `entity_relations(status="candidate")`，两端可解析到 canonical / draft / candidate 工作对象
- 人物扩展表 `characters` 保留历史独立 `aliases` JSONB 字段，新别名应优先写入 `core_entities.content_json.aliases`
- 对象分级：core / important / normal / temporary
- 版本回滚基于 `TextArchive` 归档与 `EntityRevision` 兜底（活跃回滚路由优先查询 `TextArchive`，无归档时回退到最近 `EntityRevision` 快照）

## 职责

- 世界对象 CRUD（CoreEntity / `WorldEntityService`）
- 对象关系管理（EntityRelation）
- 别名管理（`EntityAliasService`，内联于 CoreEntity.aliases JSONB，支持待复核别名元数据）
- 对象去重（EntityDedupService）
- 对象融合建议（WorldEntityFusionService，LLM 只生成建议，用户确认后应用）
- 面向项目级智能去重的实体融合 facade（`suggest_entity_fusion` /
  `apply_entity_fusion`）
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
- `status` — 状态（canonical / deprecated）
- `source_chapter_id` — 来源章节 ID
- `caused_by_event_id` — 导致此关系的事件 ID

`canonical` 关系以 `(novel_id, source_id, target_id, relation_type)` 为数据库幂等键。关系写入走仓储层 upsert；调用方不应再实现“先查再插”的并发控制。

### aliases（内联 JSONB）

存储于 `core_entities.content_json.aliases`，格式为列表：
```json
[
  {"alias": "别名文本", "type": "name|title|nickname|translation|abbreviation"}
]
```

- 别名不创建新实体行
- 去重检查：别名不与已有别名重复（大小写不敏感）

### entity_revisions 表（legacy 快照兜底）

- 原用于实体快照版本管理
- `POST /api/world/entities/{entity_id}/rollback` 是当前活跃的版本回滚路由，请求体：`{ "target_scene_index": 12 }`；由 `EntityRevisionService.rollback_to_scene_index` 实现，优先使用 `TextArchive`，无归档时回退到最近 `EntityRevision`
- `POST /api/world/entities/{entity_id}/rollback-by-revision` 是 `entity_revisions` 的兼容路由，按显式 `revision_id` 回滚
- `EntityRevisionService` 同时承担活跃回滚实现与 legacy 兼容，不应再被描述为仅 read/compat

### map_observations / map_facts 表

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
    status: str = "draft"

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

`modules.world.services.map_service` 是历史兼容导出层，保留旧测试和 API 路由 import 路径；具体实现拆到以下内部服务：

- `map_templates.py`：初始地形模板和详图 tile 生成。
- `map_config_service.py` / `map_tile_service.py` / `map_location_binding_service.py`：地图配置、tile 批量编辑、地点绑定。
- `map_marker_service.py` / `map_territory_service.py`：动态标记和势力范围。
- `map_dynamic_service.py`：保留 `MapDynamicFactService` 名称，作为 observation、fact、dashboard、playback、open target 的兼容 facade。
- `map_observation_service.py` / `map_fact_service.py`：观察事实候选、确认流转和正式事实状态。
- `map_dashboard_service.py` / `map_playback_service.py` / `map_open_target_service.py`：只读派生视图、播放事件流和地图打开目标。
- `map_dynamic_helpers.py`：动态地图 formatter、risk/priority/label、UUID 安全解析、空间锚点校验等私有 helper。

已有的 `map_state_assembler.py`、`map_scene_summary.py`、`map_terrain.py`、`map_location_layout.py`、`map_quick_create.py` 继续作为独立入口存在，不通过 `map_service.py` 承载业务实现。

## Facade（facade.py）

```python
# ---- CoreEntity ----
async def list_entities(db, novel_id, *, entity_type=None, statuses=None, limit=100) -> list[dict]
async def list_entity_terms(db, novel_id, *, limit=500) -> list[dict]
async def create_entity(db, novel_id, data: dict) -> dict
async def count_entities(db, novel_id, *, status_filter=None) -> int
async def backfill_entity_embeddings(db, novel_id, *, batch_size=64) -> int

# ---- Entity Context ----
async def get_world_context(db, novel_id, entity_ids=None, ...) -> WorldContextBundle
async def expand_related_entities(db, novel_id, seed_entity_ids, depth=1, limit=20) -> list[CoreEntityContext]

# ---- Entity Extraction ----
async def run_entity_extraction(db, novel_id, start_chapter, end_chapter, batch_size=5) -> dict

# ---- Dedup ----
async def find_similar_entities(db, novel_id, name, aliases=None, ...) -> list[DuplicateSuggestionResult]
async def merge_candidate_into_entity(db, novel_id, candidate_id, target_entity_id) -> MergeResult

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

## API 路由

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/api/world/entities` | 世界对象列表 |
| POST | `/api/world/entities` | 创建世界对象 |
| POST | `/api/world/entities/extract` | 手动世界对象补抽；必须携带 `context_confirmation_id` |
| GET | `/api/world/entities/{entity_id}` | 对象详情 |
| PUT | `/api/world/entities/{entity_id}` | 更新对象 |
| DELETE | `/api/world/entities/{entity_id}` | 删除对象 |
| POST | `/api/world/entities/{entity_id}/promote` | 将草稿/候选实体提升为正史 |
| GET | `/api/world/entities/{entity_id}/relations` | 实体关系列表 |
| DELETE | `/api/world/entities/{entity_id}/aliases` | 删除别名 |
| GET | `/api/world/entities/{entity_id}/revisions` | 版本历史（legacy，只读兼容） |
| POST | `/api/world/entities/{entity_id}/rollback` | 回滚到指定 scene_index（优先 TextArchive，无归档时回退到 EntityRevision） |
| POST | `/api/world/entities/{entity_id}/rollback-by-revision` | 按 revision_id 回滚（`entity_revisions` 兼容） |
| GET | `/api/world/aliases` | 别名列表 |
| POST | `/api/world/aliases` | 添加别名 |
| GET | `/api/world/entity-batches` | 实体批次分组列表 |
| GET | `/api/world/relations` | 关系列表（v3） |
| POST | `/api/world/relations` | 创建关系（v3） |
| PUT | `/api/world/relations/{rel_id}` | 更新关系（v3） |
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
- 补抽结果写入 `context_confirmations.result_refs`，类型为 `world_entity`。
- 候选提升、合并、重命名或忽略会将相关确认记录标记为 `needs_review` 或 `stale_context`，并写入 `stale_reasons`。

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
| POST | `/api/world/maps/quick-create/confirm` | 确认快速创建，一次只写入一张地图及其布局/绑定 |
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
