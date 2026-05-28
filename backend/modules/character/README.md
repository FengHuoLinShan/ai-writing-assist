# Module: character / 人物档案与知识边界模块

## 定位

character 模块属于**事实层**，负责人物档案、人物当前状态、人物关系摘要和人物知识边界。

当前阶段不构建复杂人物 Agent 群。

## 职责

- **人物档案管理**：创建、更新、查询人物（`characters` 表）
- **人物状态管理**：跟踪人物的当前状态、情绪、短期目标变化
- **人物关系摘要**：维护人物关系概览文本
- **人物语言风格**：记录人物的说话方式
- **人物行为规则**：定义人物的行为约束
- **人物知识边界**：管理角色知道什么、不知道什么、误解什么
- **人物档案抽取**：通过 RAG 查找相关正文，写入 `meta.ai_suggestions` 等待用户采纳

## 不负责

- 每个角色独立长期运行 Agent
- 自动对话模拟系统
- 复杂心理曲线图
- 关系强度自动计算系统

## 数据表

| 表名 | 用途 | 状态 |
|------|------|------|
| `characters` | 人物档案主表 | canonial / draft |
| `character_knowledge` | 人物知识边界记录 | canonial / draft |

### characters 表

主要字段：id, novel_id, world_entity_id (optional FK), name, aliases (JSONB),
role, appearance, personality, desire, fear, secret, weakness,
current_goal, current_state, current_emotion, stance, voice_style,
behavior_rules (JSONB), relationship_summary, status, created_at, updated_at

### character_knowledge 表

主要字段：id, novel_id, character_id (FK), target_type, target_id,
knowledge_level (unknown/rumor/partial/full/false_belief),
known_content, misconception, source_chapter_index, source_memory_id,
status, created_at

## 对外契约

### Facade 接口

其他模块只能通过 `facade.py` 访问本模块功能：

```python
async def get_characters_context(
    db, novel_id, character_ids, reveal_mode="author_safe"
) -> CharacterContextBundle:
    """获取人物上下文包"""

async def get_character_knowledge_context(
    db, novel_id, character_id, target_ids=None
) -> list[CharacterKnowledgeContext]:
    """获取人物对指定目标的知识情况"""

async def filter_context_by_character_knowledge(
    db, novel_id, character_id, context_items
) -> list[dict]:
    """按人物知识过滤上下文项（核心功能）"""
```

### 核心过滤逻辑

人物知识边界的过滤规则：

| knowledge_level | 过滤行为 |
|----------------|----------|
| `unknown` | 移除该项 —— 角色不知道 |
| `rumor` | 保留，标记为传闻 |
| `partial` | 保留，附上已知内容 |
| `full` | 保留，标记为完全知道 |
| `false_belief` | 替换为角色的误解内容 |

## API 路由

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/characters` | 创建人物 |
| GET | `/api/characters` | 获取人物列表 |
| GET | `/api/characters/{id}` | 获取人物详情 |
| PUT | `/api/characters/{id}` | 更新人物 |
| DELETE | `/api/characters/{id}` | 删除人物 |
| PATCH | `/api/characters/{id}/state` | 更新人物状态 |
| POST | `/api/characters/{id}/knowledge` | 创建知识记录 |
| GET | `/api/characters/{id}/knowledge` | 获取知识列表 |
| GET | `/api/characters/knowledge/{kid}` | 获取单条知识 |
| PUT | `/api/characters/knowledge/{kid}` | 更新知识 |
| DELETE | `/api/characters/knowledge/{kid}` | 删除知识 |
| POST | `/api/characters/{id}/filter-context` | 按知识过滤上下文 |

人物档案抽取依赖 RAG chunk，并使用 `mode="extraction"`。若历史导入章节尚未建立 RAG 索引，抽取任务会先按人物名补建相关章节索引，再重新检索正文。RAG/LLM 降级信息会进入任务 `warnings`，前端用于提示“本次建议可能不准确”。

## 测试方式

```bash
cd backend
python -m pytest modules/character/tests/ -v
```

## 依赖

- core (Base, UUIDMixin, TimestampMixin, StatusMixin, NovelMixin)
- shared (enums, constants)
- project (通过 facade 获取项目上下文)
