# Module: world / 世界对象模块

## 定位

world 模块管理小说世界中的核心对象及其关系，是结构化创作的事实底座。

## 核心原则

- 对象抽取不是 NER，而是长期创作资产识别
- AI 抽取对象直接以 `status="canonical"` 自动入库，不经过候选池
- 别名不建新对象，存储于 `core_entities.content_json.aliases` JSONB 字段
- 对象分级：core / important / normal / temporary
- 实体变更同时写入 Delta Log + Text Archive，用于版本回滚

## 数据表

- `core_entities` — 共享核心实体表，公共字段（name / aliases JSONB / summary / public_info / hidden_truth / importance / embedding / search_text / pinyin_string）统一存储
- `events` — 事件扩展表（entity_id PK+FK → core_entities.id）
- `entity_relations` — 实体关系边（UUID FK → core_entities + 章节追溯字段）
- `entity_revisions` — 实体快照版本表（已废弃，改用 DeltaLog + TextArchive）
- `characters` — 人物档案（entity_id PK+FK → core_entities.id）
- `character_knowledge` — 人物知识边界
- `entity_candidates` — 候选对象池（已废弃，AI 抽取直接入正史）
- ~~`relationships`~~ — 已废弃，使用 `entity_relations`
- ~~`entity_aliases`~~ — 已移除，别名存 `core_entities.content_json.aliases` JSONB

## 数据表（关联模块）

- `text_archive`（定义在 world/models.py）— 文本归档：记录长文本字段每次变更的快照，用于版本回滚。字段：entity_id / field_name / text_content / scene_index / source / meta
- `delta_log`（定义在 memory/models.py）— 实体变更日志：记录结构化字段的 before/after 变更（category / field_path / old_value / new_value）

## 服务

- **WorldEntityService** — 核心实体 CRUD + 别名管理
- **EntityRelationService** — 实体关系边 CRUD（v3 取代旧 RelationshipService）
- **EventService** — 事件 CRUD（entity_type="event"）
- **EntityRevisionService** — 实体版本管理（list / rollback，基于 EntityRevision 快照，后续迁移到 DeltaLog）
- **EntityCandidateService** — 候选池管理（已废弃，AI 抽取不经过候选池）
- **EntityDedupService** — 混合去重（pg_trgm 词法 + pgvector 语义 RRF 融合）+ 9 步深度事务合并
- **DedupScorer** — 多路信号级联评分（rapidfuzz 形似 + pinyin 音似 + 子串包含 + 语义余弦 + 长度差异 + trigram Jaccard），可选 LR 模型
- **EntityExtractionService** — RAG 有序 chunk → LLM 抽取 → 实体入库
- **CharacterService** — 人物 CRUD + 知识边界（从 character 模块迁入）
- **AliasService** — 旧别名兼容路由

## Facade

```python
# ---- CoreEntity ----
async def create_entity(db, novel_id, name, entity_type, *, ...) -> CoreEntityResponse
async def get_entity(db, entity_id, novel_id=None) -> CoreEntityResponse
async def update_entity(db, entity_id, novel_id=None, **fields) -> CoreEntityResponse
async def delete_entity(db, entity_id, novel_id=None) -> None
async def list_entities(db, novel_id, *, entity_type=None, status=None, limit=100) -> list[dict]
async def list_entity_terms(db, novel_id, *, limit=500) -> list[dict]

# ---- Alias (inline on CoreEntity) ----
async def add_alias(db, entity_id, alias, alias_type="name") -> bool
async def remove_alias(db, entity_id, alias) -> bool

# ---- Entity Context ----
async def get_world_context(db, novel_id, entity_ids=None, ...) -> WorldContextBundle
async def get_entity_importance_map(db, novel_id) -> dict
async def expand_related_entities(db, novel_id, seed_entity_ids, depth=1, limit=20) -> list[CoreEntityContext]

# ---- Entity Extraction ----
async def run_entity_extraction(db, novel_id, start_chapter, end_chapter, batch_size=5) -> dict

# ---- Candidates (已废弃) ----
async def count_pending_candidates(db, novel_id) -> int
async def accept_candidate(db, novel_id, candidate_id, user_edits=None) -> CoreEntityResponse
async def merge_candidate_into_entity(db, novel_id, candidate_id, target_entity_id) -> MergeResult

# ---- Dedup ----
async def find_similar_entities(db, novel_id, name, aliases=None, ...) -> list[DuplicateSuggestionResult]

# ---- Relationships (thin proxy) ----
async def find_entity_id_by_name(db, novel_id, name, entity_type=None) -> str | None
async def upsert_relationship(db, novel_id, source_id, target_id, ...) -> None
async def get_location_factions(db, novel_id, location_id) -> list[dict]

# ---- Events ----
async def create_event(db, novel_id, data: dict) -> dict
async def get_events_context(db, novel_id, limit=50) -> EventsContextBundle

# ---- EntityRelation ----
async def get_entity_relations(db, novel_id, skip=0, limit=100) -> tuple
async def create_relation(db, novel_id, data: dict) -> EntityRelationResponse
async def upsert_relation(db, novel_id, source_id, target_id, ...) -> EntityRelationResponse

# ---- EntityRevision ----
async def get_entity_revisions(db, novel_id, entity_id, skip=0, limit=20) -> dict
async def rollback_to_revision(db, novel_id, entity_id, revision_id) -> dict

# ---- Character ----
async def create_character(db, novel_id, name, world_entity_id=None) -> CharacterResponse
async def list_characters(db, novel_id, skip=0, limit=100) -> tuple
async def get_characters_context(db, novel_id, character_ids, ...) -> CharacterContextBundle
async def get_character_knowledge_context(db, novel_id, character_id, target_ids=None) -> list
async def filter_context_by_character_knowledge(db, novel_id, character_id, context_items) -> list[dict]
async def find_character_id_by_name(db, novel_id, name) -> str | None
async def update_character_location(db, novel_id, character_id, location_id, ...) -> None
async def get_characters_at_location(db, novel_id, location_id) -> list[dict]
async def get_character_location_id(db, novel_id, character_id) -> str | None
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
DELETE /api/world/entities/{entity_id}/aliases

# 实体批次
GET    /api/world/entity-batches

# 关系（v3）
GET    /api/world/relations
POST   /api/world/relations
PUT    /api/world/relations/{rel_id}
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

## 不做

- 自动合并正史对象
- 复杂跨类型实体消歧
- 所有 Mention 实时 embedding
- 独立知识图谱数据库
