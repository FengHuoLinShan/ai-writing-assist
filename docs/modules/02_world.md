# Module: world / 世界对象模块

## 定位

world 模块管理小说世界中的核心对象及其关系，是结构化创作的事实底座。

## 核心原则

- 对象抽取不是 NER，而是长期创作资产识别
- AI 抽取对象先进入 entity_candidates
- 别名不建新对象，进入 entity_aliases（EntityAliasRepository.create()）
- 对象分级：core / important / normal / temporary / alias

## 数据表

- world_entities — 正史对象库（含 public_info / hidden_truth / importance / embedding）
- relationships — 对象/人物间关系边（source_type / target_type 通用引用）
- entity_aliases — 对象别名（FK → world_entities.id ON DELETE CASCADE）
- entity_candidates — AI 生成候选池（含 suggested_action 断言）

## 服务

services/ 目录下按职责拆分：

- `entity_service.py` — WorldEntityService：对象 CRUD
- `entity_types.py` — ENTITY_TYPE_MAP：24 种中文→英文实体类型映射 + map_entity_type() + is_entity_type_valid()
- `relationship_service.py` — RelationshipService：关系 CRUD + 一跳/二跳扩展
- `candidate_service.py` — EntityCandidateService：候选池管理 + 晋升/合并/别名
- `alias_service.py` — AliasService：别名管理
- `dedup_service.py` — EntityDedupService：_fuzzy_name_matches（difflib 0.72 阈值）+ entity_type 兼容性过滤 + 候选合并
- `extraction_service.py` — EntityExtractionService：调用 LLM 批量抽取（5 章一批），创建候选 + 去重
- `helpers.py` — 共享函数（parse_uuid / normalize_name / merge_text_field / world_entity_types_compatible）

## Facade

```python
async def get_world_context(db, novel_id, entity_ids=None, reveal_mode="author_safe", limit=20) -> WorldContextBundle
async def expand_related_entities(db, novel_id, seed_entity_ids, depth=1, limit=20) -> list[WorldEntityContext]
async def find_duplicate_entity_candidates(db, novel_id, candidate_id) -> list[DuplicateSuggestion]
async def find_similar_entities(db, novel_id, name, aliases=None, entity_type=None) -> list[DuplicateSuggestionResult]
async def merge_candidate_into_entity(db, novel_id, candidate_id, target_entity_id) -> WorldEntityResponse
async def list_entities(db, novel_id, entity_type=None, limit=100) -> list[dict]
async def count_pending_candidates(db, novel_id) -> int
async def accept_candidate(db, novel_id, candidate_id, user_edits=None) -> WorldEntityResponse
async def run_entity_extraction(db, novel_id, start_chapter, end_chapter, batch_size=5) -> dict
async def find_entity_id_by_name(db, novel_id, name, entity_type=None) -> str | None
async def upsert_relationship(db, novel_id, source_id, target_id, source_type, target_type, relation_type, description=None) -> None
async def get_location_factions(db, novel_id, location_id) -> list[dict]
```

## API

```
# 对象
POST   /api/world/entities
GET    /api/world/entities
GET    /api/world/entities/{id}
PUT    /api/world/entities/{id}
DELETE /api/world/entities/{id}

# 候选
GET    /api/world/candidates
POST   /api/world/candidates/{id}/dedup
PUT    /api/world/candidates/{id}       # 确认/修改候选
DELETE /api/world/candidates/{id}

# 关系
POST   /api/world/relationships
GET    /api/world/relationships
GET    /api/world/relationships/{id}
PUT    /api/world/relationships/{id}
DELETE /api/world/relationships/{id}

# 别名
POST   /api/world/aliases
GET    /api/world/aliases
DELETE /api/world/aliases/{id}

# 合并
POST   /api/world/entities/{entity_id}/merge-from-candidate/{candidate_id}
```

## 候选建议动作

create_new / merge_with_existing / alias_of_existing / ignore / temporary_only / needs_user_decision

## 抽取模式

- strict：importance >= 0.75
- normal：importance >= 0.45
- full：尽量全面，但只作为 Mention 或候选

## 测试要求

- conftest 必须 import `modules.project.models`（NovelMixin FK）
- dedup 测试：精确匹配 + 模糊匹配 + 合并
- 抽取测试：mock LLMClient，验证候选创建和去重逻辑

## 不做

- 自动合并正史对象
- 复杂跨类型实体消歧
- 所有 Mention 实时 embedding
- 独立知识图谱数据库
