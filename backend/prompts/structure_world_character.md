# Structure: World & Character — 世界与人物结构生成 Prompt

> **用途**：根据用户的创意、世界观草稿、人物设定草稿，生成结构化的世界对象、人物档案、关系、人物知识边界，以及地理、伏笔、时间线候选。
>
> **输入来源**：用户直接提供的创意草稿 + 已有正史数据
>
> **输出去向**：实体类输出只进入候选清洗。`create_new` 表示建议创建新对象，`link_to_existing` / `alias_of_existing` 表示建议关联已有对象，`ignore` / `temporary_only` 表示建议清理；用户确认后才会写入正史。

---

## 前置引用

执行本 Prompt 前，请完整阅读并遵守：
- [shared_rules.md](./shared_rules.md) — 所有共享行为规则

---

## 输入 Schema

```json
{
  "novel_goal": "string（小说的核心目标和主题描述，如"一个关于复仇与救赎的史诗故事"）",
  "genre": "string（题材，如 奇幻/科幻/武侠/历史/都市/悬疑/言情/轻小说/混合）",
  "tone": "string（风格基调，如 黑暗/轻松/正剧/幽默/史诗/文艺/冷峻/温暖）",
  "raw_idea": "string（用户的原始创意文本，可以是段落、列表或关键词集合）",
  "existing_world_entities": [
    {
      "id": "uuid",
      "name": "string",
      "entity_type": "string",
      "summary": "string",
      "importance_level": "core|important|normal|minor"
    }
  ],
  "existing_characters": [
    {
      "id": "uuid",
      "name": "string",
      "role": "string",
      "personality": "string",
      "current_goal": "string"
    }
  ],
  "existing_relationships": [
    {
      "id": "uuid",
      "source_type": "string",
      "source_id": "uuid",
      "target_type": "string",
      "target_id": "uuid",
      "relation_type": "string"
    }
  ],
  "constraints": [
    "string（创作约束，如'不要超过 20 个主要角色'、'不要引入魔法体系'等）"
  ],
  "extraction_mode": "strict | normal | full",
  "user_preferences": {
    "language": "zh | en",
    "detail_level": "minimal | standard | detailed"
  }
}
```

### extraction_mode 说明

| 模式 | 阈值 | 适用场景 |
|------|------|---------|
| `strict` | importance ≥ 0.75 | 已有大量正史数据时，只抽取核心对象 |
| `normal` | importance ≥ 0.50 | 默认模式，初期设定创作 |
| `full` | importance ≥ 0.25 | 空白项目启动，从长篇草稿中全面识别潜在资产 |

---

## 输出 Schema

```json
{
  "world_entities": [
    {
      "temp_id": "string（临时标识，如 'we_1', 'we_2'，供本输出内其他数组引用）",
      "name": "string（对象名称）",
      "entity_type": "string（枚举值，见下方）",
      "summary": "string（一句话摘要）",
      "public_info": "string（读者已知的信息）",
      "hidden_truth": "string（作者视角的隐藏真相，可选，严格模式下可空）",
      "importance": 0.0-1.0,
      "importance_level": "core|important|normal|minor",
      "reveal_level": "reader_known|character_known|author_only",
      "status": "canonical",
      "embedding_text": "string（用于生成 embedding 的纯文本，可选）"
    }
  ],
  "characters": [
    {
      "temp_id": "string（临时标识，如 'ch_1', 'ch_2'）",
      "world_entity_temp_id": "string（关联 world_entities.temp_id，可选）",
      "name": "string（人物姓名）",
      "aliases": ["string（别名/称号列表）"],
      "role": "string（角色定位，如 主角/反派/导师/盟友/对手/恋人/配角/路人）",
      "appearance": "string（外貌描述）",
      "personality": "string（性格特征）",
      "desire": "string（欲望/追求）",
      "fear": "string（恐惧/弱点）",
      "secret": "string（角色隐藏的秘密）",
      "weakness": "string（性格或能力上的弱点）",
      "current_goal": "string（当前目标）",
      "current_state": "string（当前状态）",
      "current_emotion": "string（当前情绪）",
      "stance": "正义|中立|邪恶|混乱|秩序|旁观|摇摆",
      "voice_style": "string（语言风格特点）",
      "behavior_rules": ["string（行为规则/行动原则）"],
      "relationship_summary": "string（人物关系概述）",
      "importance": 0.0-1.0,
      "status": "canonical"
    }
  ],
  "relationships": [
    {
      "source_temp_id": "string（引用 world_entities 或 characters 的 temp_id）",
      "source_type": "world_entity|character",
      "target_temp_id": "string",
      "target_type": "world_entity|character",
      "relation_type": "string（枚举值，见下方）",
      "description": "string（关系描述）",
      "visibility": "reader_known|character_known|author_only",
      "strength": 0.0-1.0
    }
  ],
  "character_knowledge": [
    {
      "character_temp_id": "string",
      "target_temp_id": "string",
      "target_type": "world_entity|character|memory",
      "knowledge_level": "unknown|rumor|partial|full|false_belief",
      "known_content": "string（角色所知道的内容）",
      "misconception": "string（如果 knowledge_level 为 false_belief，角色的误解内容）"
    }
  ],
  "entity_candidates": [
    {
      "name": "string",
      "entity_type": "string",
      "summary": "string",
      "source_text_excerpt": "string（原始文本摘录）",
      "importance_score": 0.0-1.0,
      "confidence": 0.0-1.0,
      "candidate_reason": "string（为什么认为这是一个值得关注的对象）",
      "suggested_action": "create_new|merge_with_existing|alias_of_existing|ignore|temporary_only",
      "suggested_existing_entity_id": "uuid（当 suggested_action 为 merge/alias 时提供已有对象 ID）"
    }
  ],
  "geo_candidates": [
    {
      "name": "string",
      "location_level": "continent|country|region|city|district|landmark|building|room|abstract",
      "parent_name": "string（上级地点名称，引用 world_entities name 或为 null）",
      "terrain": "string（地形地貌）",
      "climate": "string（气候特征）",
      "summary": "string"
    }
  ],
  "foreshadowing_candidates": [
    {
      "name": "string",
      "summary": "string",
      "surface_meaning": "string（表面含义）",
      "hidden_meaning": "string（隐藏含义）",
      "suggested_seed_chapter": "int（建议埋下伏笔的章节索引）"
    }
  ],
  "timeline_candidates": [
    {
      "title": "string",
      "summary": "string",
      "suggested_order_index": "int",
      "event_type": "character_event|world_event|battle|discovery|relationship_change|travel|other"
    }
  ],
  "questions_for_user": [
    {
      "question": "string（需要用户回答的问题）",
      "context": "string（这个问题为什么重要）",
      "suggested_options": ["string（建议选项，可选）"]
    }
  ],
  "warnings": [
    {
      "severity": "info|warning|critical",
      "message": "string（警告信息）",
      "affected_items": ["string（受影响对象引用）"]
    }
  ]
}
```

---

## 字段详解

### entity_type 枚举值

| 值 | 说明 | 示例 |
|----|------|------|
| `location` | 地点/场所 | 幽暗森林、帝都皇城 |
| `faction` | 组织/势力/国家 | 暗影议会、北境部落 |
| `item` | 物品/道具/文物 | 龙魂之刃、记忆水晶 |
| `event` | 重要历史事件 | 焚城之夜、大迁徙 |
| `rule` | 规则/法则/定律 | 魔法守恒律、血统继承法则 |
| `power_system` | 能力/力量体系 | 元素魔法、真气修炼体系 |
| `secret` | 秘密/未揭示真相 | 国王的真实身份 |
| `legend` | 传说/神话/预言 | 救世主预言 |
| `resource` | 资源/材料/稀有物 | 星陨铁、灵泉水 |
| `character` | 人物 — 作为人物模块主实体的正史角色 | 主线角色、配角 |

### relation_type 枚举值

| 值 | 说明 |
|----|------|
| `belongs_to` | 属于 |
| `located_in` | 位于 |
| `rules_over` | 统治 |
| `allied_with` | 同盟 |
| `enemy_of` | 敌对 |
| `parent_of` | 长辈/上级关系 |
| `child_of` | 晚辈/下级关系 |
| `lover_of` | 恋人 |
| `mentor_of` | 师徒 |
| `created_by` | 创造 |
| `destroyed_by` | 毁灭 |
| `contains` | 包含 |
| `related_to` | 通用关联 |
| `symbol_of` | 象征 |
| `guarded_by` | 守卫 |
| `located_near` | 邻近 |
| `traded_with` | 贸易关系 |
| `worships` | 信仰 |
| `fears` | 畏惧 |
| `seeks` | 追寻 |

### importance 分级说明

| 等级 | 值范围 | 含义 | 示例 |
|------|--------|------|------|
| `core` | 0.75-1.0 | 核心对象，缺席会导致故事不成立 | 主角、主要反派、核心设定 |
| `important` | 0.50-0.75 | 重要对象，在多个章节中出现 | 主要配角、关键道具、重要地点 |
| `normal` | 0.25-0.50 | 普通对象，在部分章节中有作用 | 次要角色、特定场景物品 |
| `minor` | < 0.25 | 次要对象，偶尔提及 | 一次性NPC、普通背景物 |

### knowledge_level 说明

| 值 | 含义 |
|----|------|
| `unknown` | 角色完全不知道此信息 |
| `rumor` | 角色听说过传闻但不确认真假 |
| `partial` | 角色知道部分信息但不完整 |
| `full` | 角色知道完整信息 |
| `false_belief` | 角色有错误认知/误解 |

### suggested_action 决策树

```
该名词是否明显是已有对象的别名/同义表达？
├── 是 → alias_of_existing
└── 否 → 该对象是否只在当前场景有用且后续不会出现？
    ├── 是 → temporary_only
    └── 否 → 该对象是否值得成为长期创作资产？
        ├── 是（且不与已有对象重复）→ create_new
        ├── 是（但与已有对象高度相似）→ merge_with_existing
        ├── 不确定 → needs_user_decision
        └── 否 → ignore
```

---

## 执行流程

1. **理解创意**：阅读用户的 raw_idea 和已有正史数据，建立对世界的基本理解
2. **识别资产**：遵循"长期创作资产识别"原则，识别值得结构化的核心对象
3. **分级评估**：为每个候选对象评估 importance，按 extraction_mode 过滤
4. **构建关系**：识别对象之间的关键关系
5. **知识边界**：确定每个角色对相关信息的认知程度
6. **输出结构化数据**：按输出 Schema 生成结构化 JSON。不要输出 `status` 字段，系统会根据 `suggested_action` 和当前流水线决定创建、关联、忽略或保留为候选
7. **自查**：检查是否有违反 shared_rules 的内容，特别是规则 3（不提前揭示）、规则 4（知识边界）、规则 5（不凭空增加）

---

## 重要提醒

1. **引用一致性**：同一输出内，characters.relationship_summary 中引用的名称必须在本输出的 world_entities 或 characters 中存在
2. **importance 诚实**：不要因为某个对象"有趣"就给它过高的 importance。想象一下 500 章后的故事，这个对象是否仍然重要
3. **hidden_truth 使用**：只在严格必要时提供 hidden_truth。大多数对象只需要 public_info 即可
4. **geo_candidates 克制**：只有与剧情直接相关的地点才创建 geo_candidate。不需要为每个提及的地点创建地理信息
5. **questions_for_user 必要性**：只提出真正需要用户决策的问题。能合理推断的事项不要浪费用户精力
