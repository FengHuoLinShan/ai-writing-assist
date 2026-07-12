# Module: world / 世界对象模块

## 定位

world 模块管理小说世界中的核心对象及其关系，是结构化创作的事实底座。

## 核心原则

- 对象抽取不是 NER，而是长期创作资产识别
- 人工创建对象、关系和别名时，保存即表示采用；CoreEntity 默认写入 `canonical` 并记录 `created_by / approved_by`
- 新的普通 AI 创设入口统一先写 `creation_suggestion_queue`。为兼容旧 entity wire、批次读取和结果引用，可同时物化带 `compatibility_shadow=true` 的 draft/candidate 影子；队列仍拥有采用决策，确认时提升同一影子而不重复创建实体
- 别名不建新对象，存储于 `core_entities.content_json.aliases` JSONB 字段
- 待处理别名可在采用前修改目标对象、别名文本和别名类型；证据来源、workflow、Scene、引用和置信度保持只读
- `link_to_existing` / `alias_of_existing` 待处理项可设为已有对象别名，源兼容对象标记 `status="merged"` 并记录 `resolved_as="alias"`，不硬删除、不采用为独立对象
- 世界对象 UI 的“待处理”入口按对象 / 别名 / 关系三个子 tab 聚合；对象库、别名、关系页继续作为全量管理入口，历史默认隐藏
- 待处理关系可在采用前编辑源对象、目标对象、关系类型、描述和强度；来源章节、引用等证据只读，人工审计写入 `entity_relations.review_meta`
- 对象分级：core / important / normal / temporary
- 版本回滚基于 `TextArchive` 归档与 `EntityRevision` 兜底（活跃回滚路由优先查询 `TextArchive`，无归档时回退到最近 `EntityRevision` 快照）
- 关系原始状态仍兼容 `candidate` / `canonical` / `deprecated`；作者界面统一投影为待处理 / 已采用 / 历史。`canonical` 关系边使用 `(novel_id, source_id, target_id, relation_type)` 作为数据库幂等键，关系写入由仓储层 upsert 兜底。
- 待处理对象合并响应可带 `affected_ids` / `merged_ids`，前端只按精确 ID 更新；缺少 affected ids 时刷新当前待处理 tab。
- CoreEntity、关系、别名、创设建议和 Map Observation/Fact 响应按需提供 `display_state / source / attention_reasons / suggested_action`；原始状态字段保持兼容

## 数据表

- `core_entities` — 共享核心实体表，公共字段（name / aliases JSONB / summary / public_info / hidden_truth / importance / embedding / search_text / pinyin_string）统一存储
- `events` — 事件扩展表（entity_id PK+FK → core_entities.id）
- `entity_relations` — 实体关系边（UUID FK → core_entities + 章节追溯字段 + `review_meta` 复核审计）
- `entity_revisions` — 实体快照版本表（旧版快照；当前活跃回滚优先使用 `TextArchive`，无归档时回退到 `EntityRevision`）
- `characters` — 人物档案（entity_id PK+FK → core_entities.id）
- `character_knowledge` — 人物知识边界
- `species_profiles` / `faction_profiles` / `location_profiles` / `rule_profiles` / `item_profiles` / `secret_profiles` / `entity_profile_templates` / `generic_entity_profiles` — 世界对象的类型化 Profile 与模板
- `generation_prompt_templates` / `generation_prompt_template_revisions` / `world_bible_pages` / `world_bible_page_revisions` / `world_bible_page_projections` — 生成模板与世界书资产
- `knowledge_tags` / `character_knowledge_tags` / `asset_knowledge_tags` / `knowledge_tag_exclusions` / `knowledge_visibility_policies` / `reader_reveal_policies` / `creation_suggestion_queue` / `conflict_check_queue` — 知识标签、可见性和待处理工作队列
- `map_configs` / `map_tiles` / `map_location_bindings` / `map_location_layouts` / `map_terrain_layers` / `map_terrain_regions` / `map_terrain_patches` / `map_terrain_bindings` / `map_markers` / `map_territory_tiles` / `map_observations` / `map_facts` — 动态地图子系统表，详见 `docs/modules/15_map.md`
- ~~`entity_candidates`~~ — 已废弃，候选对象直接用 `core_entities.status="candidate"` 表达
- ~~`relationships`~~ — 已废弃，使用 `entity_relations`
- ~~`entity_aliases`~~ — 已移除，别名存 `core_entities.content_json.aliases` JSONB

## 数据表（关联模块）

- `text_archive`（由 `modules.world.models` 兼容入口导出，具体定义在 world 模型 package 的 core 子域）— 文本归档：存储回滚时使用的长文本字段快照，在执行回滚时写入并读取以恢复先前值；不会在日常每次编辑时自动填充。字段：entity_id / field_name / text_content / scene_index / source / meta
- `delta_log`（定义在 memory/models.py）— 实体变更日志：属于 memory 模块，记录结构化字段的 before/after 变更（category / field_path / old_value / new_value）；不会在每个实体编辑时自动写入

### models 子包布局

`backend/modules/world/models/` 已按领域拆成 package；`modules.world.models`
仍是稳定兼容入口，导入后会注册所有 world ORM 表到同一个
`core.base.Base.metadata`：

- `models/core.py`：核心实体、事件、关系、版本快照和 TextArchive。
- `models/character.py`：人物档案和人物知识边界。
- `models/profiles.py`：世界资产 profile、模板和通用档案。
- `models/worldbuilding.py`：生成模板、World Bible、知识标签、创设建议和冲突队列。
- `models/common.py`：共享 SQLAlchemy imports 与 pgvector/SQLite embedding column helper。

## 服务

- **WorldEntityService** — 核心实体 CRUD + 别名管理
- **EntityRelationService** — 实体关系边 CRUD（v3 取代旧 RelationshipService）
- **EventService** — 事件 CRUD（entity_type="event"）
- **EntityRevisionService** — 实体版本回滚服务：实现活跃回滚 `rollback_to_scene_index`（基于 `TextArchive` 查询与恢复，`EntityRevision` 兜底），同时保留 `rollback_to_revision` 兼容能力
- **EntityDedupService** — 混合去重（pg_trgm 词法 + pgvector 语义 RRF 融合）+ 9 步深度事务合并
- **DedupScorer** — 多路信号级联评分（rapidfuzz 形似 + pinyin 音似 + 子串包含 + 语义余弦 + 长度差异 + trigram Jaccard），可选 LR 模型
- **EntityExtractionService** — RAG 有序 chunk → LLM 抽取 → 去重 → `SuggestionQueueService`；不直接拥有 CoreEntity 采用决策
- **SuggestionQueueService** — 校验创设建议、可选兼容影子、并发安全裁决，以及对象/关系/别名的领域采用
- **CharacterService** — 人物 CRUD + 知识边界（从 character 模块迁入）
- **CharacterKnowledgeService** — 人物知识边界管理

`CharacterKnowledge.source_chapter_index` 表示人物学到该知识的章节。角色视角查询只纳入
严格早于可见截止章的记录；同章但没有更精确学习位置、或缺少来源章的旧数据默认排除。
只有明确 `is_public_baseline=true` 的开场公开知识可作为无来源章例外。
- 动态地图服务 — 详见 `docs/modules/15_map.md`

### services 子包布局

`backend/modules/world/services/` 已按领域拆成子包，顶层仅保留聚合导出、通用
helper 和历史兼容入口：

- `services/core/`：核心实体、关系、事件、版本回滚、去重与抽取。
- `services/map/`：动态地图、地图状态、标记、territory、observation/fact 和播放。
- `services/worldbuilding/`：世界书、模板、投影和作者资料整理。
  `worldbuilding_service.py` 仅作为旧 import path 兼容 hub；实现按概念拆到
  `profile_service.py`、`world_bible_service.py`、`suggestion_queue_service.py`、
  `knowledge_tag_service.py`、`reader_safety_service.py`、`conflict_queue_service.py`
  和 `activation_preview_service.py`。
- `services/common.py`：跨子包通用 helper，如 `parse_uuid`、`normalize_name`。
- `services/map_service.py`：历史兼容导出层，不承载业务逻辑。

拆分保持 world facade、API wire shape、novel_id 隔离和现有测试入口稳定；跨模块调用仍只能通过 facade/contracts/API/DI port。

## Facade

Root `modules.world.facade` 是纯 re-export hub，用来保持旧跨模块 import path
稳定；它不定义 async function，也不承载业务编排。具体入口按子域下沉到
`entity_facade.py`、`character_facade.py`、`event_facade.py`、`map_facade.py`
和 `worldbuilding_facade.py`。

`worldbuilding_facade.py` 承载世界书上下文激活入口：
`preview_worldbuilding_activation()` 委托确定性 activation preview 服务；
`mark_worldbuilding_context_stale()` 保持函数内 lazy import `modules.context.facade`，
避免扩大 context ↔ world 循环 import 风险。

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
# World no longer exposes a parallel extraction facade.

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

## API

```
# CoreEntity
POST   /api/world/entities
GET    /api/world/entities
GET    /api/world/entities/{id}
PUT    /api/world/entities/{id}
DELETE /api/world/entities/{id}
GET    /api/world/entities/{id}/relations

# 别名（inline on CoreEntity）
GET    /api/world/aliases
POST   /api/world/aliases
PATCH  /api/world/entities/{entity_id}/aliases/edit
DELETE /api/world/entities/{entity_id}/aliases
POST   /api/world/entities/{candidate_id}/resolve-as-alias

# 实体批次
GET    /api/world/entity-batches

# 关系（v3）
GET    /api/world/relations
POST   /api/world/relations
PUT    /api/world/relations/{rel_id}
PATCH  /api/world/relations/{rel_id}/review-edit
DELETE /api/world/relations/{rel_id}

# 事件
GET    /api/world/events
POST   /api/world/events
GET    /api/world/events/{entity_id}
PUT    /api/world/events/{entity_id}
DELETE /api/world/events/{entity_id}

# 版本
GET    /api/world/entities/{entity_id}/revisions
POST   /api/world/entities/{entity_id}/rollback
POST   /api/world/entities/{entity_id}/rollback-by-revision

# 人物（从 character 模块迁入）
GET    /api/world/characters
POST   /api/world/characters
GET    /api/world/characters/{character_id}
PUT    /api/world/characters/{character_id}
DELETE /api/world/characters/{character_id}
GET    /api/world/characters/{character_id}/knowledge
POST   /api/world/characters/{character_id}/knowledge
PUT    /api/world/knowledge/{knowledge_id}
DELETE /api/world/knowledge/{knowledge_id}
```

## 回滚

- `POST /api/world/entities/{entity_id}/rollback` 是当前活跃的版本回滚路由。请求体：`{ "target_scene_index": 12 }`。该路由由 `EntityRevisionService.rollback_to_scene_index` 实现：优先查询 `TextArchive` 中该实体在 `target_scene_index` 及之前的归档字段值并恢复；若无 `TextArchive` 记录，则回退到最近一条 `EntityRevision` 快照；回滚动作本身会作为新的 `TextArchive` 记录保存。
- `POST /api/world/entities/{entity_id}/rollback-by-revision` 是 legacy 兼容路由，按 `revision_id` 回滚到 `entity_revisions` 中的显式快照。
- `EntityRevisionService` 同时承担活跃回滚实现与 legacy 回滚兼容，不应再被描述为仅 read/compat。

## 不做

- 未经作者确认或已持久化流水线授权自动合并已采用对象
- 复杂跨类型实体消歧
- 所有 Mention 实时 embedding
- 独立知识图谱数据库

## World Background Aggregation

`world.facade.get_world_background()` 是 context 的只读世界背景接口。它从世界对象、
关系、已确认地图事实和人物知识边界派生带来源、状态、敏感级别、分组、优先级与 token
估算的条目；该聚合不新增正史表，也不把 projection 写回事实层。
