# Module: world / 世界对象模块

## 定位

world 模块管理小说世界中的核心对象及其关系，是结构化创作的事实底座。

## 核心原则

- 对象抽取不是 NER，而是长期创作资产识别
- AI 抽取对象先进入 entity_candidates
- 别名不建新对象，存储于 `core_entities.aliases` JSONB 字段（不再使用独立 entity_aliases 表）
- 对象分级：core / important / normal / temporary / alias

## 数据表

- core_entities — 共享核心实体表（取代 world_entities + entity_aliases），公共字段（name / aliases JSONB / summary / public_info / hidden_truth / importance / embedding）统一存储。character/geo 子系统通过 1:1 FK (entity_id = PK) 扩展核心表。
- relationships — 对象间关系边（source_id/target_id → core_entities.id）
- entity_candidates — AI 生成候选池（含 suggested_action 断言，confirmed 后进入 core_entities）

## 服务

- CoreEntityService — 核心实体 CRUD + 别名管理（add_alias / remove_alias）
- RelationshipService — 关系 CRUD + 一跳/二跳扩展
- EntityCandidateService — 候选池管理（晋升/合并/别名）
- EntityDedupService — 模糊去重（difflib 0.72）+ 合并
- EntityExtractionService — RAG 有序 chunk → LLM 抽取 → 候选
- ExtractionResult — 抽取结果 dataclass

## Facade

```python
# ---- CoreEntity ----
async def create_entity(db, novel_id, name, entity_type, *, aliases=None, summary=None, public_info=None, hidden_truth=None, importance=0.5, importance_level="normal", status="draft", skip_dedup=False) -> CoreEntityResponse
async def get_entity(db, entity_id, novel_id=None) -> CoreEntityResponse
async def update_entity(db, entity_id, novel_id=None, **fields) -> CoreEntityResponse
async def delete_entity(db, entity_id, novel_id=None) -> None
async def list_entities(db, novel_id, *, entity_type=None, status=None, limit=100) -> list[dict]
async def list_entity_terms(db, novel_id, *, limit=500) -> list[dict]

# ---- Alias (inline on CoreEntity) ----
async def add_alias(db, entity_id, alias, alias_type="name") -> bool
async def remove_alias(db, entity_id, alias) -> bool

# ---- Entity Context ----
async def get_world_context(db, novel_id, entity_ids=None, reveal_mode="author_safe", limit=20) -> WorldContextBundle
async def get_entity_importance_map(db, novel_id) -> dict
async def expand_related_entities(db, novel_id, seed_entity_ids, depth=1, limit=20) -> list[CoreEntityContext]

# ---- Entity Extraction ----
async def run_entity_extraction(db, novel_id, start_chapter, end_chapter, batch_size=5) -> dict

# ---- Candidates ----
async def count_pending_candidates(db, novel_id) -> int
async def accept_candidate(db, novel_id, candidate_id, user_edits=None) -> CoreEntityResponse
async def merge_candidate_into_entity(db, novel_id, candidate_id, target_entity_id) -> CoreEntityResponse

# ---- Dedup ----
async def find_duplicate_entity_candidates(db, novel_id, candidate_id) -> list[DuplicateSuggestionResult]
async def find_similar_entities(db, novel_id, name, aliases=None, entity_type=None) -> list[DuplicateSuggestionResult]

# ---- Relationships (thin proxy) ----
async def find_entity_id_by_name(db, novel_id, name, entity_type=None) -> str | None
async def upsert_relationship(db, novel_id, source_id, target_id, source_type, target_type, relation_type, description=None) -> None
async def get_location_factions(db, novel_id, location_id) -> list[dict]
```

## API

```
# CoreEntity
POST   /api/world/entities
GET    /api/world/entities
GET    /api/world/entities/{id}
PUT    /api/world/entities/{id}
DELETE /api/world/entities/{id}
GET    /api/world/entities/{id}/related          # 关联实体（关系一跳/二跳扩展）

# 别名（inline on CoreEntity）
POST   /api/world/entities/{entity_id}/aliases
DELETE /api/world/entities/{entity_id}/aliases

# 候选
GET    /api/world/candidates
POST   /api/world/candidates                     # 手动创建候选
GET    /api/world/candidates/{id}
PUT    /api/world/candidates/{id}
POST   /api/world/candidates/{id}/accept          # 接受候选→创建CoreEntity
DELETE /api/world/candidates/{id}
POST   /api/world/candidates/{id}/dedup           # 去重检查

# 关系
POST   /api/world/relationships
GET    /api/world/relationships
PUT    /api/world/relationships/{rel_id}
DELETE /api/world/relationships/{rel_id}

# 合并
POST   /api/world/entities/{entity_id}/merge-from-candidate/{candidate_id}
```

## 候选建议动作

create_new / merge_with_existing / alias_of_existing / ignore / temporary_only / needs_user_decision

## 不做

- 自动合并正史对象
- 复杂跨类型实体消歧
- 所有 Mention 实时 embedding
- 独立知识图谱数据库
