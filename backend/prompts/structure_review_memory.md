# Structure: Review & Memory — 结构复查与状态抽取 Prompt

> **用途**：对结构化创作候选进行复查（冲突检查、剧透检查、知识边界检查、重复检查），以及从用户手写正文或结构变更中抽取状态更新候选。
>
> **输入来源**：结构候选（world_entities_candidate、plot_structure_candidate、chapter_cards_candidate 等）或用户手写正文 / 结构变更
>
> **输出去向**：review_reports（复查报告）+ memory_update_proposals（状态更新候选）
>
> **两种模式**：
> - **复查模式**：对候选结构进行检查，输出 decision + warnings + revision_instructions
> - **抽取模式**：从正文或变更中抽取 memory_update_proposals

---

## 前置引用

执行本 Prompt 前，请完整阅读并遵守：
- [shared_rules.md](./shared_rules.md) — 所有共享行为规则
- [structure_world_character.md](./structure_world_character.md) — 对象管理规则
- [structure_plot.md](./structure_plot.md) — 剧情结构标准
- [structure_chapter_scene.md](./structure_chapter_scene.md) — 章节场景标准

---

## 复查模式

### 输入 Schema（复查模式）

```json
{
  "mode": "review",
  "target_type": "world_structure | geo_structure | plot_structure | chapter_cards | memory_update | entity_candidates",
  "candidate_payload": {
    "description": "待复查的完整结构化候选数据"
  },
  "existing_data": {
    "world_entities": [
      {"id": "uuid", "name": "string", "entity_type": "string", "summary": "string", "importance_level": "string"}
    ],
    "relationships": [
      {"source_id": "uuid", "target_id": "uuid", "relation_type": "string"}
    ],
    "characters": [
      {"id": "uuid", "name": "string", "role": "string", "secret": "string（标注'作者视角'）"}
    ],
    "character_knowledge": [
      {"character_id": "uuid", "target_type": "string", "target_id": "uuid", "knowledge_level": "string", "known_content": "string"}
    ],
    "geo_locations": [
      {"id": "uuid", "name": "string", "location_level": "string", "parent_location_id": "uuid", "access_level": "string"}
    ],
    "geo_edges": [
      {"source_location_id": "uuid", "target_location_id": "uuid", "relation_type": "string", "difficulty": "string"}
    ],
    "plot_threads": [
      {"id": "uuid", "name": "string", "current_stage": "string", "reader_known_state": "string"}
    ],
    "timeline_events": [
      {"id": "uuid", "order_index": "int", "title": "string", "chapter_index": "int"}
    ],
    "foreshadowing_plans": [
      {"id": "uuid", "name": "string", "planned_seed_chapter": "int", "planned_payoff_chapter": "int"}
    ],
    "reveal_plans": [
      {"id": "uuid", "target_type": "string", "target_id": "uuid", "secret_summary": "string"}
    ]
  }
}
```

### 输出 Schema（复查模式）

```json
{
  "mode": "review",
  "decision": "pass | minor_revision | major_revision | reject",
  "score": 0.0-1.0,
  "problems": [
    {
      "severity": "critical | major | minor | info",
      "category": "conflict | reveal | knowledge | duplicate | geo | structure | quality",
      "message": "string（问题的具体描述）",
      "location": "string（问题所在的 JSON path 或字段名）",
      "suggestion": "string（修复建议）"
    }
  ],
  "conflict_warnings": [
    {
      "type": "时空矛盾|逻辑矛盾|设定冲突|角色行为矛盾|时间线冲突",
      "description": "string",
      "involved_items": ["string"],
      "severity": "critical | major | minor"
    }
  ],
  "early_reveal_warnings": [
    {
      "secret": "string（被提前揭示的秘密）",
      "revealed_in": "string（在哪里被揭示）",
      "planned_reveal_chapter": "int（原计划的揭示章节）",
      "severity": "critical | major | minor",
      "suggestion": "string"
    }
  ],
  "character_knowledge_warnings": [
    {
      "character_name": "string",
      "knows_about": "string（角色知道了什么本不应知道的信息）",
      "information_type": "secret|future_event|hidden_location|other",
      "severity": "critical | major | minor",
      "suggestion": "string"
    }
  ],
  "duplicate_entity_warnings": [
    {
      "candidate_name": "string",
      "existing_entity_name": "string",
      "similarity_type": "name_similar|semantic_similar|alias_match|relationship_match",
      "similarity_score": 0.0-1.0,
      "severity": "major | minor | info",
      "suggested_action": "merge|alias|keep_both|user_decision"
    }
  ],
  "geo_warnings": [
    {
      "type": "通行不可达|访问权限冲突|历史时期冲突|位置层级错误",
      "description": "string",
      "location_names": ["string"],
      "severity": "major | minor"
    }
  ],
  "revision_instructions": [
    {
      "priority": "must_fix | should_fix | nice_to_have",
      "target": "string（需要修改的位置或字段）",
      "instruction": "string（具体的修改指令）",
      "reason": "string（为什么需要修改）"
    }
  ]
}
```

---

## 抽取模式

### 输入 Schema（抽取模式）

```json
{
  "mode": "extract",
  "source_type": "user_writing | structure_change",
  "source_id": "string（来源 ID，如写作草稿 ID 或变更记录 ID）",
  "chapter_index": "int",
  "content": "string（用户手写正文内容或结构变更的详细描述）",
  "existing_data": {
    "world_entities": [...],
    "characters": [...],
    "character_knowledge": [...],
    "plot_threads": [...],
    "timeline_events": [...],
    "foreshadowing_plans": [...]
  }
}
```

### 输出 Schema（抽取模式）

```json
{
  "mode": "extract",
  "memory_update_proposals": [
    {
      "proposal_type": "new_entity|entity_update|character_state|relationship_change|knowledge_update|timeline_event|foreshadowing_status|geo_change|outline_drift",
      "chapter_index": "int",
      "payload": {
        "field1": "value",
        "field2": "value"
      },
      "confidence": 0.0-1.0,
      "reason": "string（为什么提议这个更新）",
      "source_text_excerpt": "string（原文摘录，支持依据）"
    }
  ],
  "timeline_event_proposals": [
    {
      "title": "string",
      "summary": "string",
      "order_index": "int",
      "chapter_index": "int",
      "event_type": "character_event|world_event|battle|discovery|relationship_change|travel|other",
      "related_character_names": ["string"],
      "related_entity_names": ["string"],
      "visibility": "reader_known|character_known|author_only"
    }
  ],
  "character_knowledge_proposals": [
    {
      "character_name": "string",
      "target_name": "string",
      "target_type": "world_entity|character|memory|timeline",
      "new_knowledge_level": "unknown|rumor|partial|full|false_belief",
      "known_content": "string",
      "confidence": 0.0-1.0,
      "source_chapter_index": "int"
    }
  ],
  "foreshadowing_status_proposals": [
    {
      "foreshadowing_name": "string",
      "new_status": "active|reinforced|triggered|paid_off|abandoned",
      "chapter_index": "int",
      "note": "string"
    }
  ]
}
```

---

## 复查标准

### 检查维度与严重程度

| 维度 | 检查内容 | critical 示例 | major 示例 | minor 示例 |
|------|---------|-------------|-----------|-----------|
| **引用完整性** | 对象是否存在 | 引用不存在的 UUID | 引用已废弃的对象 | 引用名称拼写不一致 |
| **提前揭示** | 秘密是否被提前暴露 | 核心秘密在首章揭示 | 次要秘密提前 10+ 章揭示 | 暗示过强，容易被猜出 |
| **知识边界** | 角色是否知道不该知道的 | 路人角色知道皇室机密 | 配角知道主角的隐藏计划 | 角色知道过多细节 |
| **设定冲突** | 与已有设定矛盾 | 角色死而复生无解释 | 地点位置与前文矛盾 | 时间顺序轻微混乱 |
| **重复对象** | 与已有对象重复 | 完全相同的对象（名+描述） | 相似度 >0.88 | 相似度 0.78-0.88 |
| **结构质量** | 章节/场景结构 | 纯过渡章无任何推进 | 章节无冲突 | 场景功能重叠 |
| **时空矛盾** | 时间线顺序 | 事件 B 发生在事件 A 之前但需要事件 A 的结果 | 时间顺序不明确 | 时间跳跃无标记 |
| **地理冲突** | 地理关系 | 穿越不可通行的地理屏障 | 错误的位置层级 | 距离估算不精确 |

### decision 判定标准

| 判定 | 条件 | 含义 |
|------|------|------|
| `pass` | 无 critical/major 问题，minor 问题 ≤3 个 | 可直接进入用户确认阶段 |
| `minor_revision` | 有 1-2 个 major 问题，或 3-5 个 minor 问题 | 修复建议后无需重新复查 |
| `major_revision` | 有 ≥3 个 major 问题，或 1 个 critical 问题 | 必须修复后重新复查 |
| `reject` | 有 ≥2 个 critical 问题，或结构有根本性缺陷 | 候选不合格，需重新生成 |

### 复查优先级

```
引用完整性 > 知识边界 > 提前揭示 > 设定冲突 > 时空矛盾 > 重复对象 > 地理冲突 > 结构质量
```

引用完整性是最基础的检查——如果一个候选引用了不存在的对象，其他检查没有意义。

---

## 执行流程

### 复查模式流程

1. **Schema 校验**：检查候选结构是否符合对应的 JSON Schema
2. **引用检查**：检查所有 ID/name 引用是否存在于 existing_data 中
3. **知识边界检查**：逐条检查角色认知是否越界
4. **提前揭示检查**：对比 reveal_plans 和 foreshadowing_plans
5. **重复检查**：对 entity_candidates 进行名称/语义相似度检查
6. **地理检查**：检查位置关系和通行约束
7. **时间线检查**：检查事件顺序一致性
8. **结构质量检查**：评估章节/场景的结构完整性
9. **综合评分**：按检查结果给出 decision
10. **输出复查报告**

### 抽取模式流程

1. **理解正文/变更**：阅读用户提供的内容
2. **识别状态变化**：识别哪些事实发生了变化（新信息、人物状态变化、关系变化等）
3. **评估重要性**：只对值得记录的变化生成 proposal
4. **检查知识边界**：判断这些变化是否影响了角色知识
5. **更新伏笔状态**：检查是否有伏笔被触发或兑现
6. **输出 proposals**：按输出 Schema 生成结构化的更新提案

---

## 重要提醒

1. **复查不是重写**：发现问题的输出问题是修改建议，不要直接输出修正后的完整结构
2. **诚实评估**：confidence 和 severity 必须诚实。不要人为降低严重性来让候选通过
3. **抽取不是 NER**：和世界对象抽取一样，只提取值得记录的长期状态变化。角色吃了顿饭这种日常事件不需要生成 memory_update_proposal
4. **记忆 vs 正史**：memory_records 是状态变化历史，不是重复存储正史。只在发生状态变化时生成 proposal
5. **每个 warning 必须 actionable**：每个 warning 必须附带可操作的 suggestion 或 revision_instruction。只说"有问题"而不说"怎么修"等于没有复查
