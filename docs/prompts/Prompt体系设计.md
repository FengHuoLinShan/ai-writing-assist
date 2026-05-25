# Prompt 体系设计文档（实际实现）

## 1. 设计原则

系统不以多 Agent 为核心。Prompt 是系统调用大模型完成特定结构化任务的模板。

## 2. Prompt 清单

| 文件 | 用途 | 实现状态 |
|------|------|---------|
| `structure_world_character.md` | 世界与人物结构生成 | ✅ 已创建 |
| `structure_plot.md` | 剧情结构生成（剧情线/篇章纲/伏笔/揭示） | ✅ 已创建 |
| `structure_chapter_scene.md` | 章节与场景结构生成 | ✅ 已创建 |
| `structure_review_memory.md` | 结构复查与状态抽取 | ✅ 已创建 |
| `structure_extraction.md` | 从章节正文抽取世界对象候选（原设计以外新增） | ✅ 已创建 |
| `shared_rules.md` | 所有 Prompt 共享规则 | ✅ 已创建 |

所有 Prompt 输出结构化 JSON，所有输出均为候选。

## 3. shared_rules.md

所有 Prompt 共享规则：

```text
1. 不直接生成小说正文。
2. 只生成结构化候选。
3. 不擅自改正史。
4. 不提前揭示隐藏真相。
5. 不让角色知道不该知道的信息。
6. 不凭空增加重大设定。
7. 输出必须符合 JSON schema。
8. 不重要对象不要升级为正史对象。
9. 别名不要创建新对象，应标记为 alias_of_existing。
10. 临时对象只标记 temporary_only。
```

## 4. structure_world_character.md

- 输入：novel_goal / genre / tone / raw_idea / existing_entities / extraction_mode
- 输出：world_entities / characters / relationships / character_knowledge / entity_candidates / geo_candidates / foreshadowing_candidates / timeline_candidates

## 5. structure_plot.md

- 输入：world_context / character_context / memory_context / timeline_context / geo_context / user_intent / target_scope
- 输出：plot_threads / outline_arcs / foreshadowing_plans / reveal_plans / offscreen_progress

## 6. structure_chapter_scene.md

- 输入：arc context + 上下文
- 输出：chapter_cards（含 scene_cards）

## 7. structure_review_memory.md

- 输出：decision / problems / conflict_warnings / early_reveal_warnings / character_knowledge_warnings / duplicate_entity_warnings / geo_warnings / revision_instructions / memory_update_proposals

## 8. structure_extraction.md（原设计以外新增）

- 用途：从已导入的章节正文中抽取世界对象候选
- 定位：不是 NER，而是"小说长期创作资产识别"
- 输入：章节正文 + 已有对象列表
- 输出：实体候选列表（含 suggested_action 断言）
- 核心规则：
  - 只抽取对后续创作有价值的对象
  - 别名标记为 alias_of_existing
  - 临时对象标记为 temporary_only
  - 宁可少抽
