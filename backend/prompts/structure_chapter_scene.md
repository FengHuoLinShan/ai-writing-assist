# Structure: Chapter & Scene — 章节与场景结构生成 Prompt

> **用途**：根据篇章纲和结构化上下文，生成具体的章节卡（ChapterCard）与场景卡（SceneCard）。
>
> **输入来源**：Context Compiler 编译的上下文 + OutlineArc（篇章纲）
>
> **输出去向**：chapter_cards + scene_cards 候选 → 结构复查 → 用户确认 → 正史库

---

## 前置引用

执行本 Prompt 前，请完整阅读并遵守：
- [shared_rules.md](./shared_rules.md) — 所有共享行为规则
- [structure_plot.md](./structure_plot.md) — 剧情结构设计原则（如有已确认的剧情线）

---

## 输入 Schema

```json
{
  "arc_context": {
    "title": "string",
    "arc_index": "int",
    "start_chapter": "int",
    "end_chapter": "int",
    "chapter_count": "int（本篇章总章节数）",
    "arc_goal": "string",
    "core_conflict": "string",
    "main_opposition": "string",
    "entry_hook": "string",
    "midpoint_turn": "string",
    "climax": "string",
    "result": "string",
    "next_hook": "string",
    "related_threads": [
      {
        "name": "string",
        "thread_type": "string",
        "summary": "string",
        "current_stage": "string"
      }
    ]
  },
  "world_context": {
    "entities": [
      {
        "id": "uuid",
        "name": "string",
        "entity_type": "string",
        "summary": "string",
        "public_info": "string",
        "hidden_truth": "string（标注'作者视角'）",
        "reveal_level": "string"
      }
    ],
    "relationships": [
      {"source_name": "string", "target_name": "string", "relation_type": "string"}
    ]
  },
  "character_context": {
    "characters": [
      {
        "id": "uuid",
        "name": "string",
        "role": "string",
        "current_goal": "string",
        "current_state": "string",
        "current_emotion": "string",
        "personality": "string",
        "desire": "string",
        "fear": "string",
        "voice_style": "string",
        "behavior_rules": ["string"],
        "known_facts_summary": "string"
      }
    ]
  },
  "memory_context": {
    "recent_memories": [
      {
        "chapter_index": "int",
        "title": "string",
        "summary": "string",
        "importance": 0.0-1.0
      }
    ]
  },
  "timeline_context": {
    "events": [
      {
        "order_index": "int",
        "title": "string",
        "summary": "string",
        "chapter_index": "int"
      }
    ],
    "latest_chapter_index": "int"
  },
  "active_foreshadowing": [
    {
      "name": "string",
      "surface_meaning": "string",
      "planned_seed_chapter": "int",
      "planned_payoff_chapter": "int",
      "needs_reinforcement": "bool"
    }
  ],
  "user_intent": "string（用户对本章节的具体意图）",
  "chapter_count": "int（本次需要生成的章节数）",
  "start_from_chapter_index": "int"
}
```

---

## 输出 Schema

```json
{
  "chapter_cards": [
    {
      "chapter_index": "int",
      "title": "string（章节标题，可选）",
      "chapter_goal": "string（本章必须达成的叙事目标）",
      "main_conflict": "string（本章的核心冲突）",
      "emotional_point": "string（本章希望读者感受到的情绪）",
      "plot_function": "string（本章在剧情线中的功能，如 开局/铺垫/冲突建立/转折/高潮/收束/过渡/揭示）",
      "must_happen": [
        "string（本章必须发生的事件列表）"
      ],
      "must_not_happen": [
        "string（本章禁止发生的事件列表）"
      ],
      "involved_character_names": ["string"],
      "involved_entity_names": ["string"],
      "related_thread_names": ["string"],
      "visible_progress": [
        "string（读者能看到的剧情推进，如'主角发现了一封信'）"
      ],
      "hidden_progress": [
        "string（读者看不到但作者需要知道的推进，如'反派暗中派出了刺客'）"
      ],
      "offscreen_progress": [
        "string（本章时间范围内，在其他地点发生的事，如'与此同时，帝都正在召开紧急会议'）"
      ],
      "foreshadowing_actions": [
        {
          "foreshadowing_name": "string",
          "action": "string（本章为这个伏笔做些什么）",
          "action_type": "seed|reinforce|payoff|ignore"
        }
      ],
      "ending_hook": "string（章末钩子，给读者继续阅读的理由）",
      "status": "draft",
      "scene_cards": [
        {
          "scene_index": "int（场景在章节内的序号）",
          "setting": "string（场景设置：时间+地点）",
          "involved_character_names": ["string"],
          "point_of_view": "string（视角人物）",
          "scene_goal": "string（本场景的叙事目标）",
          "conflict": "string（场景内部的具体冲突）",
          "emotional_tone": "string（场景的情绪基调）",
          "key_dialogue_topic": "string（关键对话主题）",
          "sensory_details": ["string（感官细节提示，可选）"],
          "outcome": "string（场景结束时发生了什么变化）",
          "transition_to_next": "string（衔接下一场景的方式）"
        }
      ]
    }
  ]
}
```

---

## 创作标准

### 每章的硬性要求

每个 `chapter_card` **必须同时满足以下 5 个条件**，否则该章为无效章节：

| # | 条件 | 检查方式 |
|---|------|---------|
| 1 | **明确目标** | `chapter_goal` 不为空且具体。不要说"推进剧情"，要说"让主角决定离开村庄" |
| 2 | **明确冲突** | `main_conflict` 不为空。冲突可以是与他人、与环境、与内心的对抗 |
| 3 | **状态变化** | `visible_progress` 或 `hidden_progress` 中有至少一项。章节结束时必须有某些东西发生了改变 |
| 4 | **信息推进** | 至少有一个场景提供了新信息给读者或角色。可以是对话揭示、发现、意外事件 |
| 5 | **情绪点或钩子** | `emotional_point` 或 `ending_hook` 不为空。读者看完这章需要感受到某种情绪或想知道接下来会发生什么 |

### 必须避免的章节类型

| 类型 | 问题 | 替代方案 |
|------|------|---------|
| **纯过渡章** | 角色只是从一个地点移动到另一个地点，没有任何冲突或信息 | 在移动中加入冲突（追兵、路障、同伴争执）或关键对话 |
| **无目标章** | 角色没有主动目标，只是被动反应 | 给角色一个明确的短期目标，即使是小的 |
| **无冲突章** | 一切顺利，没有任何阻碍 | 加入微小冲突（遗失物品、天气变化、信息不对称） |
| **无变化章** | 章节结束后一切和开始一样 | 至少改变一个信息状态或人物关系状态 |
| **重复桥段** | 用了和前几章相同的叙事模式（相同的冲突类型、相同的情绪节奏） | 改变节奏：长/短、激烈/平静、户外/室内、对话/行动交替 |
| **提前揭示暗线** | 在铺垫不足的情况下揭示了本应在后期揭示的秘密 | 检查 foreshadowing_plans 和 reveal_plans，确保揭示节奏正确 |

### 场景卡设计标准

每个 `scene_card` 应遵循以下原则：

1. **每章 2-4 个场景**为宜，过多场景会使节奏碎片化
2. **每个场景应有独立目标**：不服务于本章目标的场景应删除或合并
3. **场景转换应有理由**：时间跳转、视角切换、地点变化都应有叙事目的
4. **视角一致性**：建议每章保持同一视角人物，切换视角应有明确的章节分隔
5. **结局钩子**：每章最后一个场景应留下悬念或情绪余韵

### plot_function 取值说明

| 值 | 说明 | 位置建议 |
|----|------|---------|
| `开局` | 篇章开始，建立场景和初始状态 | 篇章首章 |
| `铺垫` | 铺设背景、引入冲突要素 | 篇章前 1/3 |
| `冲突建立` | 冲突逐步升级 | 篇章前 2/3 |
| `转折` | 关键转折点，midpoint_turn | 篇章中段 |
| `高潮` | 冲突集中爆发 | 篇章后 1/3 |
| `收束` | 冲突解决，结果呈现 | 篇章末尾 |
| `过渡` | 调节节奏的缓冲章 | 高潮前后 |
| `揭示` | 关键信息揭示 | 按 reveal_plan 安排 |

---

## 执行流程

1. **理解篇章上下文**：阅读 arc_context，理解本篇章的目标、冲突和走向
2. **拆分章节**：按 chapter_count 将篇章拆分为若干章节，每个章节有独立的功能定位
3. **确保章节质量**：对每个章节卡逐一检查 5 个硬性条件
4. **设计场景**：为每章设计 2-4 个场景，确保每个场景服务于章节目标
5. **嵌入伏笔**：检查 active_foreshadowing，在适当时机安排 seed/reinforce
6. **信息揭示控制**：检查 character_context 中的已知信息，确保角色视角不越界
7. **输出候选**：按输出 Schema 生成结构化 JSON
8. **自查**：检查是否有纯过渡章、无冲突章、提前揭示等问题

---

## 重要提醒

1. **每章都是一个"微型故事"**：即使在全篇章的大框架下，每章也应有独立的起承转合
2. **节奏变化**：不要所有章节都是高强度冲突。在高潮章之间安排缓冲章
3. **角色动机驱动**：角色的行动应由其 current_goal 和 personality 驱动，而不是被情节推着走
4. **场景不是流水账**：不要事无巨细地描述角色的每个动作。只写那些推动叙事或塑造人物的场景
5. **hook 要诚实的**：ending_hook 不应是虚假的悬念。如果真相就是如此，不要故意误导读者
