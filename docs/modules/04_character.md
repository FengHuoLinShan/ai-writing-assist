# Module: character / 人物档案与知识边界模块

## 定位

character 模块负责人物档案、当前状态和知识边界。当前阶段不构建复杂人物 Agent 群。

## 数据表

- characters — 人物档案（name / role / appearance / personality / desire / fear / secret / weakness / current_goal / current_state / current_emotion / stance / voice_style / behavior_rules / relationship_summary / aliases JSONB / meta JSONB）
- character_knowledge — 知识边界（target_type / target_id / knowledge_level: unknown|rumor|partial|full|false_belief）

## 服务

- CharacterService：人物 CRUD
- CharacterKnowledgeService：知识边界 CRUD

## Facade

```python
async def list_characters(db, novel_id, skip=0, limit=100) -> tuple[list[CharacterResponse], int]
async def get_characters_context(db, novel_id, character_ids, reveal_mode="author_safe") -> CharacterContextBundle
async def get_character_knowledge_context(db, novel_id, character_id, target_ids=None) -> list
async def filter_context_by_character_knowledge(db, novel_id, character_id, context_items) -> list[dict]
async def create_character(db, novel_id, name, world_entity_id=None) -> CharacterResponse
async def get_character_id_by_world_entity(db, novel_id, world_entity_id) -> str | None
async def find_character_id_by_name(db, novel_id, name) -> str | None
async def update_character_location(db, novel_id, character_id, location_id, text_state, chapter_index) -> None
async def get_characters_at_location(db, novel_id, location_id) -> list[dict]
async def get_character_location_id(db, novel_id, character_id) -> str | None
```

## API

```
# CRUD
POST   /api/characters
GET    /api/characters
GET    /api/characters/{id}
PUT    /api/characters/{id}
DELETE /api/characters/{id}

# 知识边界
POST   /api/characters/{id}/knowledge
GET    /api/characters/{id}/knowledge
PUT    /api/characters/knowledge/{id}
DELETE /api/characters/knowledge/{id}

# 状态更新
PATCH  /api/characters/{id}/state

# AI 抽取
POST   /api/characters/{id}/extract          # 单人物抽取
POST   /api/characters/extract-all           # 全部人物抽取
GET    /api/characters/{id}/suggestions      # 获取 AI 建议
PUT    /api/characters/{id}/apply-suggestions # 应用 AI 建议

# 上下文过滤
POST   /api/characters/{id}/filter-context
```

人物档案抽取优先通过 RAG `mode="extraction"` 检索相关正文。若历史导入数据缺少 RAG 索引，抽取任务会按人物名从已有草稿中补建相关章节索引，再重新检索；仍无命中时返回 no_chunks。RAG/LLM 降级会写入任务 `warnings`，前端提示本次建议可能不准确。

## 异步任务

- `@task_handler("character_extract")` — 通过 RAG 检索人物相关 chunk，调用 LLM 逐字段抽取档案，结果写入 `meta.ai_suggestions`

## Context 输出重点

当前目标、当前状态、当前已知、当前未知、当前误解、语言风格、行为边界。

## 不做

- 每个角色独立长期运行 Agent
- 自动对话模拟系统
- 复杂心理曲线图
