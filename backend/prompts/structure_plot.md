# Structure: Plot — 剧情结构生成 Prompt

> **用途**：根据正史事实（世界对象、人物、地理历史、记忆、时间线），生成剧情线、篇章纲、伏笔计划与信息揭示计划。
>
> **输入来源**：Context Compiler 编译的结构化上下文（world_context + character_context + memory_context + timeline_context + geo_context）
>
> **输出去向**：plot_threads + outline_arcs + foreshadowing_plans + reveal_plans 直接入库。

---

## 前置引用

执行本 Prompt 前，请完整阅读并遵守：
- [shared_rules.md](./shared_rules.md) — 所有共享行为规则

---

## 输入 Schema

```json
{
  "world_context": {
    "entities": [
      {
        "id": "uuid",
        "name": "string",
        "entity_type": "string",
        "summary": "string",
        "public_info": "string",
        "hidden_truth": "string（标注为'作者视角，不得直接揭示'）",
        "importance_level": "core|important|normal|minor",
        "reveal_level": "reader_known|character_known|author_only"
      }
    ],
    "relationships": [
      {
        "source_name": "string",
        "target_name": "string",
        "relation_type": "string",
        "strength": 0.0-1.0,
        "description": "string"
      }
    ],
    "entity_count": "int",
    "summary": "string（Context Compiler 生成的世界概要）"
  },
  "character_context": {
    "characters": [
      {
        "id": "uuid",
        "name": "string",
        "role": "string",
        "personality": "string",
        "desire": "string",
        "fear": "string",
        "secret": "string（标注为'作者视角，不得直接揭示'）",
        "current_goal": "string",
        "current_state": "string",
        "current_emotion": "string",
        "stance": "string",
        "voice_style": "string",
        "relationship_summary": "string",
        "known_facts_summary": "string（该角色当前已知信息的摘要）"
      }
    ],
    "count": "int"
  },
  "memory_context": {
    "recent_memories": [
      {
        "id": "uuid",
        "chapter_index": "int",
        "title": "string",
        "summary": "string",
        "importance": 0.0-1.0,
        "memory_type": "chapter_state|event|character_state|knowledge|foreshadowing|resource|outline_drift|geo_history",
        "related_entity_names": ["string"],
        "related_character_names": ["string"]
      }
    ],
    "count": "int"
  },
  "timeline_context": {
    "events": [
      {
        "id": "uuid",
        "order_index": "int",
        "chapter_index": "int",
        "title": "string",
        "summary": "string",
        "event_type": "string",
        "visibility": "reader_known|character_known|author_only"
      }
    ],
    "count": "int",
    "latest_chapter_index": "int"
  },
  "geo_context": {
    "locations": [
      {
        "id": "uuid",
        "name": "string",
        "location_level": "string",
        "parent_name": "string",
        "terrain": "string",
        "climate": "string",
        "access_level": "normal|restricted|forbidden|secret",
        "era_states_summary": "string"
      }
    ],
    "travel_constraints": [
      {
        "from": "string",
        "to": "string",
        "difficulty": "easy|moderate|hard|impossible",
        "condition": "string"
      }
    ],
    "count": "int"
  },
  "user_intent": "string（用户的创作意图，如'我要写一个关于宫廷权谋的篇章'）",
  "target_scope": {
    "type": "arc | full",
    "chapter_count": 12,
    "start_chapter_index": 0,
    "focus_entity_names": ["string（可选，聚焦某些特定对象）"],
    "focus_character_names": ["string（可选，聚焦某些特定人物）"]
  }
}
```

---

## 输出 Schema

```json
{
  "plot_threads": [
    {
      "name": "string（剧情线名称）",
      "thread_type": "main|secondary|hidden|relationship|villain|foreshadowing",
      "summary": "string（剧情线概述）",
      "visible_goal": "string（读者/角色能看到的表层目标）",
      "hidden_truth": "string（作者视角的暗线真相）",
      "start_chapter": "int",
      "planned_payoff_chapter": "int（预计收束的章节）",
      "current_stage": "未开始|初期|发展中|接近高潮|收束中|已完成",
      "related_character_names": ["string"],
      "related_entity_names": ["string"],
      "reader_known_state": "string（读者目前知道什么）",
      "author_known_state": "string（作者知道但读者还不知道什么）",
      "status": "draft"
    }
  ],
  "outline_arcs": [
    {
      "title": "string（篇章名称）",
      "arc_index": "int（篇章序号）",
      "start_chapter": "int",
      "end_chapter": "int",
      "arc_goal": "string（本篇章的核心目标）",
      "core_conflict": "string（核心冲突）",
      "main_opposition": "string（主要阻碍力量）",
      "entry_hook": "string（开篇钩子，吸引读者进入本篇章）",
      "midpoint_turn": "string（篇章中段的转折点）",
      "climax": "string（高潮场景描述）",
      "result": "string（篇章结束时的结果状态）",
      "next_hook": "string（引导进入下一篇章的钩子）",
      "related_thread_names": ["string"],
      "related_character_names": ["string"],
      "related_entity_names": ["string"],
      "status": "draft"
    }
  ],
  "foreshadowing_plans": [
    {
      "name": "string（伏笔名称）",
      "summary": "string（伏笔概述）",
      "surface_meaning": "string（表面看上去的含义）",
      "hidden_meaning": "string（真正的隐藏含义）",
      "planned_seed_chapter": "int（埋下伏笔的章节）",
      "planned_reinforce_chapters": ["int（强化/重复暗示的章节列表）"],
      "planned_payoff_chapter": "int（揭示/兑现的章节）",
      "related_entity_names": ["string"],
      "related_thread_names": ["string"],
      "status": "draft"
    }
  ],
  "reveal_plans": [
    {
      "target_name": "string（被揭示的对象名称）",
      "target_type": "world_entity|character|memory|timeline_event",
      "secret_summary": "string（被隐藏的秘密是什么）",
      "reveal_stages": [
        {
          "stage_index": "int",
          "chapter_index": "int",
          "reveal_content": "string（本阶段揭示什么）",
          "trigger": "string（触发条件）",
          "effect": "string（揭示后的影响）"
        }
      ],
      "status": "draft"
    }
  ],
  "offscreen_progress": [
    {
      "thread_name": "string",
      "chapter_range": {"start": "int", "end": "int"},
      "offscreen_description": "string（在读者看不到的地方发生了什么）",
      "importance": "low|medium|high"
    }
  ],
  "risks": [
    {
      "risk_type": "结构失衡|节奏问题|剧透风险|设定冲突|人物OOC|伏笔遗失|其他",
      "description": "string（风险描述）",
      "severity": "low|medium|high",
      "suggestion": "string（规避建议）"
    }
  ],
  "questions_for_user": [
    {
      "question": "string",
      "context": "string",
      "suggested_options": ["string"]
    }
  ]
}
```

---

## 创作标准

### 剧情线类型说明

| 类型 | 说明 | 创作要点 |
|------|------|---------|
| `main` | 主线/核心剧情线 | 贯穿全篇，是故事的主干。必须有明确的起承转合 |
| `secondary` | 支线剧情 | 与主线并行或交织，丰富世界观和人物。注意不要让支线超过主线 |
| `hidden` | 暗线/隐藏剧情线 | 读者和多数角色不知情，后期揭示。必须严格保密 |
| `relationship` | 关系线 | 人物关系变化发展的主线。可以是爱情、友情、敌对关系的变化 |
| `villain` | 反派线 | 反派行动线，在读者可见和不可见层面分别铺设 |
| `foreshadowing` | 伏笔线 | 贯穿多个章节的伏笔链，最终收束为一个重大揭示 |

### 篇章纲标准（OutlineArc）

每个篇章纲代表 **8-15 章** 的小剧情闭环，必须包含以下元素：

| 元素 | 要求 |
|------|------|
| `arc_goal` | 明确、可衡量。如"主角完成第一阶段的训练并赢得第一次战斗" |
| `core_conflict` | 具体的冲突，不要说"主角与反派对抗"，要说"主角必须保护村庄，而反派需要村庄地下的古代遗物" |
| `main_opposition` | 具体的阻碍力量。不一定是反派人物，可以是环境、制度、内心障碍 |
| `entry_hook` | 前几章内抓住读者的钩子。可以是悬念、危机、意外、强烈的开局场景 |
| `midpoint_turn` | 篇章中段的关键转折。可以是一次失败、一个意外发现、一个联盟的崩塌 |
| `climax` | 篇章高潮。必须是之前矛盾的集中爆发，并推动故事进入下一阶段 |
| `result` | 篇章结束后的新状态。世界、人物关系、力量格局发生了什么变化 |
| `next_hook` | 给读者继续读下去的理由。可以是新悬念、新目标或新威胁的暗示 |

### 伏笔设计原则

1. **埋得够早**：伏笔应在兑现前至少 3-5 章埋下
2. **表面合理**：伏笔在表面层面上必须看起来合理（像是正常的情节元素）
3. **隐藏含义**：隐藏的真正含义不能太容易被猜出
4. **强化节奏**：在埋下和兑现之间安排 1-2 次强化暗示
5. **兑现分量**：伏笔的兑现必须对得起它的铺垫。大伏笔大兑现，小伏笔小兑现
6. **不要遗忘**：所有伏笔必须有 planned_payoff_chapter，并在兑现前被强化足够次数

### 信息揭示计划（Reveal Plan）设计原则

1. **分层揭示**：一个秘密不要在单一时刻全部揭示，应分层逐步披露
2. **触发条件**：每个揭示阶段应有明确的触发条件（角色到达某地、发现某物、某人说出关键信息）
3. **连锁反应**：揭示不仅释放信息，还应改变人物关系、权力格局、读者预期
4. **节奏控制**：不要在连续章节内揭示多个重大秘密。揭示之间应有缓冲章

---

## 执行流程

1. **理解上下文**：认真阅读所有输入 context，建立对当前故事阶段的完整理解
2. **评估已有结构**：检查已有 plot_threads 的状态，确认哪些是活跃的、哪些需要收束
3. **设计新剧情线**：根据 user_intent 和 target_scope，提出新的 plot_threads
4. **构建篇章纲**：将剧情线组织为具体篇章纲（8-15 章闭环）
5. **规划伏笔**：为关键揭示设计伏笔链
6. **设计揭示计划**：为重要秘密设计分层揭示方案
7. **评估风险**：诚实评估结构中的潜在风险
8. **输出候选**：按输出 Schema 生成结构化 JSON
9. **自查**：检查是否违反 shared_rules，特别是规则 3（不提前揭示）和规则 5（不凭空增加重大设定）
