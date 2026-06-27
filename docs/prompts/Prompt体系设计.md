# Prompt 体系设计文档（实际实现）

## 1. 设计原则

系统不以多 Agent 为核心。Prompt 是系统调用大模型完成特定结构化任务的模板。

## 2. Prompt 清单

| 文件 | 用途 | 实现状态 |
|------|------|---------|
| `structure_world_character.md` | 世界与人物结构生成（综合设定 Prompt） | ✅ 已创建 |
| `structure_plot.md` | 剧情结构生成（剧情线/篇章纲/伏笔/揭示） | ✅ 已创建，被 `outline/services.py` 调用 |
| `structure_chapter_scene.md` | 章节与场景结构生成 | ✅ 已创建 |
| `structure_review_memory.md` | 结构复查与状态抽取 | ⚠️ 已废弃（review 模块已移除） |
| `structure_extraction.md` | 从章节正文抽取世界对象（world 单章候选路径） | ✅ 已创建，被 `world/services/extraction_service.py` 调用 |
| `scene_entity_extraction.md` | 从 Scene 正文抽取实体/关系/Delta（深度导入 Phase 2） | ✅ 已创建，被 `imports/scene_entity_extraction.py` 调用 |
| `extract_chapter_scene.md` | 从正文提取章节卡字段 | ✅ 已创建 |
| `shared_rules.md` | 所有 Prompt 共享规则 | ✅ 已创建 |
| `scene_segmentation.md` | Scene 切分 | ✅ 已创建，被 `imports/scene_segmentation.py` 调用 |

Prompt 输出结构化 JSON。Prompt 不输出 `status` 字段；系统根据 `suggested_action` 和当前调用流水线决定创建、关联、忽略或保留为候选。

## 3. shared_rules.md

所有 Prompt 共享规则：

```text
1. 不直接生成小说正文。
2. 输出结构化数据，由系统根据 suggested_action 自动路由。
3. 不提前揭示隐藏真相。
4. 不让角色知道不该知道的信息。
5. 不凭空增加重大设定。
6. 输出必须符合 JSON schema。
7. 不重要对象不要升级为正史对象。
8. 别名不要创建新对象，应标记为 link_to_existing。
9. 临时对象只标记 temporary_only。
```

## 4. structure_world_character.md

- 输入：novel_goal / genre / tone / raw_idea / existing_entities / extraction_mode
- 输出：world_entities / characters / relationships / character_knowledge / entity_candidates / geo_candidates / foreshadowing_candidates / timeline_candidates
- 说明：`suggested_action=create_new` 的对象由调用方服务按当前流水线创建或保留为候选。

## 5. structure_plot.md

- 输入：world_context / character_context / memory_context / timeline_context / geo_context / user_intent / target_scope
- 输出：plot_threads / outline_arcs / foreshadowing_plans / reveal_plans / offscreen_progress

## 6. structure_chapter_scene.md

- 输入：arc context + 上下文
- 输出：chapter_cards（含 scene_cards）

## 7. structure_review_memory.md（已废弃）

- 状态：⚠️ `review` 模块已移除，本 Prompt 不再被调用
- 历史输出：decision / problems / conflict_warnings / early_reveal_warnings / character_knowledge_warnings / duplicate_entity_warnings / geo_warnings / revision_instructions / memory_update_proposals

## 8. structure_extraction.md（原设计以外新增）

- 用途：从已导入的章节正文中抽取世界对象
- 定位：不是 NER，而是"小说长期创作资产识别"
- 输入：章节正文 + 已有对象列表
- 输出：`entities` 数组（含 `suggested_action` 路由断言）+ `delta_events`
- 处理逻辑：
  - `create_new` → 经去重检测后创建为候选对象
  - `link_to_existing` → 作为已有对象别名处理
  - `ignore` / `temporary_only` → 跳过不入库
- 核心规则：
  - 只抽取对后续创作有价值的对象
  - 别名标记为 `link_to_existing`
  - 临时对象标记为 `temporary_only`
  - 宁可少抽
