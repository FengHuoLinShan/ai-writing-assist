# Prompt 体系设计文档（实际实现）

## 1. 设计原则

系统使用一组结构化 Prompt 完成生成、抽取和切分任务，不构建自治多 Agent 运行时。

统一原则：

- Prompt 输出结构化 JSON，不直接写数据库状态
- `status` 不应作为 Prompt 契约的一部分
- 创建/关联/忽略主要通过 `suggested_action` 或调用方路由语义决定
- reveal、知识边界、候选与正史隔离由调用方服务和上下文编译器共同保证

## 2. 当前活跃 Prompt

| 文件 | 用途 | 主要调用方 |
|------|------|-----------|
| `shared_rules.md` | 所有结构化 Prompt 的共享规则 | 全部结构化 Prompt |
| `structure_world_character.md` | 创意启动阶段的世界/人物结构生成 | 手动生成流 |
| `structure_plot.md` | 剧情结构生成 | outline 结构生成 |
| `structure_chapter_scene.md` | 章节与场景结构生成 | 手动生成流 |
| `structure_extraction.md` | 从章节正文补抽世界对象 | world 抽取任务 |
| `scene_segmentation.md` | 深度导入 Phase 1，Scene 切分 | imports |
| `scene_entity_extraction.md` | 深度导入 Phase 2，Scene 实体/关系/Delta 抽取 | imports |
| `extract_chapter_scene.md` | 从正文提取章节卡信息 | 写作/大纲辅助 |
| `extract_character.md` | 从正文片段提取人物档案字段 | 人物信息补全 |

## 3. 历史 Prompt

| 文件 | 状态 | 说明 |
|------|------|------|
| `structure_review_memory.md` | 已废弃 | `review` 模块已移除，保留文件仅作历史参考 |

## 4. 当前设计约束

### 结构生成类

- `structure_world_character.md`
- `structure_plot.md`
- `structure_chapter_scene.md`

这类 Prompt 面向“结构化创作资产生成”，重点是：

- 产出世界对象、人物、剧情线、篇章纲、章节结构等资产
- 调用方根据当前流水线决定结果是候选、草稿还是直接落目标表
- 文档不要再把旧版 `entity_candidates` / `geo_candidates` / `timeline_candidates` 当作数据库设计权威

### 抽取类

- `structure_extraction.md`
- `scene_entity_extraction.md`
- `extract_character.md`

这类 Prompt 面向“从已有正文中识别长期资产”，重点是：

- 不是 NER，而是长期创作资产识别
- 别名走关联，不创建重复对象
- 临时对象优先忽略或标记为临时
- 深度导入路径会保留 `auto_ingested` 来源元数据

### 切分类

- `scene_segmentation.md`
- `extract_chapter_scene.md`

这类 Prompt 服务于 Scene 和章节结构整理，不负责正史对象落库策略。

## 5. `shared_rules.md` 的权威地位

共享规则要求：

1. 不直接生成小说正文。
2. 不输出最终数据库状态。
3. 不提前揭示隐藏真相。
4. 不让角色知道不该知道的信息。
5. 不凭空增加重大设定。
6. 输出必须符合调用方 schema。

Prompt 设计文档的职责是解释“为什么这样分工”，不是逐字复刻每个 Prompt 当前文件里的全部 JSON 字段。
