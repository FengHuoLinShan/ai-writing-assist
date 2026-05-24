# Module: world / 世界对象与关系管理模块

## 定位

world 模块管理小说世界中的核心对象及其关系，是结构化创作的事实底座。

对象包括地点、组织、物品、事件、规则、能力体系、秘密、传说、资源、人物引用。

## 核心原则

- 对象抽取不是 NER，而是长期创作资产识别
- AI 抽取对象先进入 entity_candidates
- 别名不建新对象，进入 entity_aliases
- 对象分级：core / important / normal / temporary / alias

## 职责

- 世界对象 CRUD（WorldEntity）
- 对象关系管理（Relationship）
- 别名管理（EntityAlias）
- 候选对象池（EntityCandidate）
- 对象去重（EntityDedupService）
- 向其他模块提供世界上下文（get_world_context）

## 边界

明确不做：

- 地点地理扩展 → geo 模块
- 人物档案管理 → character 模块
- 对象 embedding 全量实时更新 → rag 模块
- 自动合并正史对象
- 复杂跨类型实体消歧
- 所有 Mention 实时 embedding
- 独立知识图谱数据库

## 数据表

| 表名 | 用途 |
|------|------|
| `world_entities` | 世界对象正史库 |
| `relationships` | 对象间关系 |
| `entity_aliases` | 对象别名（不独立建对象） |
| `entity_candidates` | AI 生成的候选对象池 |

### world_entities 表核心字段

- `id` — UUID 主键
- `novel_id` — 项目 ID（FK → projects.id）
- `entity_type` — 对象类型（location / faction / item / event / rule / power_system / secret / legend / resource / character_ref）
- `name` — 对象名称
- `summary` — 概要
- `public_info` — 对外公开信息
- `hidden_truth` — 隐藏真相
- `content_json` — 扩展信息（JSONB）
- `importance` — 重要性（0~1）
- `importance_level` — 重要性级别（core / important / normal / temporary / alias）
- `reveal_level` — 揭示层级（author_only / hinted / revealed / fully_known）
- `status` — 状态（draft / candidate / canonical / deprecated / ignored / conflicted / pending）
- `embedding_text` — 用于向量化的文本
- `embedding` — 向量（1024 维，生产环境使用 pgvector）
- `created_by` / `approved_by` — 创建/确认者

### relationships 表核心字段

- `id` — UUID 主键
- `novel_id` — 项目 ID
- `source_type` / `source_id` — 源对象类型+ID
- `target_type` / `target_id` — 目标对象类型+ID
- `relation_type` — 关系类型
- `description` — 关系描述
- `visibility` — 可见性（author_only / author_safe / reader_known / public）
- `strength` — 关系强度（0~1）
- `status` — 状态

### entity_aliases 表核心字段

- `id` — UUID 主键
- `novel_id` — 项目 ID
- `entity_id` — 所属对象 ID（FK → world_entities.id）
- `alias` — 别名
- `alias_type` — 别名类型（name / title / nickname / alias / translation / abbreviation）
- `source_chapter_index` — 首次出现章节
- `confidence` — 确认置信度

### entity_candidates 表核心字段

- `id` — UUID 主键
- `novel_id` — 项目 ID
- `name` — 候选对象名称
- `entity_type` — 候选对象类型
- `summary` — 概要
- `source_text` — 来源文本
- `source_chapter_index` — 来源章节
- `importance_score` — 重要性评分
- `confidence` — 置信度
- `candidate_reason` — 推荐理由
- `suggested_action` — 建议动作（create_new / merge_with_existing / alias_of_existing / ignore / temporary_only / needs_user_decision）
- `suggested_existing_entity_id` — 建议关联的已有对象
- `status` — 状态

## 对外契约（contracts.py）

```python
@dataclass
class WorldEntityContract:
    novel_id: str
    entity_id: str
    entity_type: str
    name: str
    summary: str | None
    public_info: str | None
    hidden_truth: str | None
    importance: float
    importance_level: str
    reveal_level: str
    status: str

@dataclass
class RelationshipContract:
    novel_id: str
    relationship_id: str
    source_type: str
    source_id: str
    target_type: str
    target_id: str
    relation_type: str
    description: str | None
    visibility: str
    strength: float

@dataclass
class DuplicateSuggestion:
    candidate_id: str
    candidate_name: str
    existing_entity_id: str
    existing_entity_name: str
    similarity_score: float
    match_method: str
    action: str
```

## Facade（facade.py）

```python
async def get_world_context(
    db, novel_id: str,
    entity_ids: list[str] | None = None,
    reveal_mode: str = "author_safe",
    limit: int = 20,
) -> WorldContextBundle: ...

async def expand_related_entities(
    db, novel_id: str,
    seed_entity_ids: list[str],
    depth: int = 1,
    limit: int = 20,
) -> list[WorldEntityContext]: ...

async def find_duplicate_entity_candidates(
    db, novel_id: str,
    candidate_id: str,
) -> list[DuplicateSuggestion]: ...
```

## API 路由

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/api/world/entities` | 世界对象列表 |
| POST | `/api/world/entities` | 创建世界对象 |
| GET | `/api/world/entities/{entity_id}` | 对象详情 |
| PUT | `/api/world/entities/{entity_id}` | 更新对象 |
| DELETE | `/api/world/entities/{entity_id}` | 删除对象 |
| GET | `/api/world/entities/{entity_id}/related?depth=1` | 关系扩展 |
| GET | `/api/world/relationships` | 关系列表 |
| POST | `/api/world/relationships` | 创建关系 |
| PUT | `/api/world/relationships/{rel_id}` | 更新关系 |
| DELETE | `/api/world/relationships/{rel_id}` | 删除关系 |
| GET | `/api/world/aliases` | 别名列表 |
| POST | `/api/world/aliases` | 创建别名 |
| GET | `/api/world/candidates` | 候选对象列表 |
| POST | `/api/world/candidates` | 创建候选对象 |
| GET | `/api/world/candidates/{candidate_id}` | 候选对象详情 |
| PUT | `/api/world/candidates/{candidate_id}` | 更新候选 |
| DELETE | `/api/world/candidates/{candidate_id}` | 删除候选 |
| POST | `/api/world/candidates/{candidate_id}/dedup` | 候选去重 |

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

实现世界对象 CRUD、关系管理、候选对象池、基础别名管理、关系一跳/二跳扩展、规则去重。
