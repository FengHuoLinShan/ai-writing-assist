# Module: context / 上下文编译模块

## 定位

context 模块是系统核心智能模块。RAG 负责找资料，Context Compiler 决定哪些资料交给模型。

## 聚合来源

project / world / memory / outline / rag

## 架构

ContextCompiler 使用 Loader 策略模式，每个数据源独立一个 Loader 类：

| Loader | 来源 |
|--------|------|
| ProjectLoader | project.facade.get_project_context |
| WorldEntitiesLoader | world.facade.get_world_context |
| CharactersLoader | world.facade.get_characters_context |
| EventsLoader | world.facade.get_events_context（v3 新增，替代 TimelineEventsLoader） |
| MemoryRecordsLoader | memory.facade.get_recent_story_memory |
| PlotThreadsLoader | outline.api — get_active_threads（outline 无 facade） |
| OutlineArcLoader | outline.api — get_arc_context |
| ChapterCardLoader | outline.api — get_chapter_card |
| RagChunksLoader | rag.facade.retrieve |
> `TimelineEventsLoader` 和 `GeoLocationsLoader` 已随 timeline/geo 模块移除。

## Scene-Centric Compiler v2

**输入**：Scene + POV Character + Delta Stream + Foreshadowing

**输出**：`CompiledContext` IR（非 Markdown），经 `MarkdownRenderer` 转为 LLM Prompt

### 9 段 Tier 输出

| Tier | 段 | 截断策略 |
|------|-----|----------|
| P0 | Writing Objective（任务） | 永不截断 |
| P0 | Scene Blueprint（Scene 卡） | 永不截断 |
| P1 | POV Knowledge（知识边界，伪装模式） | 最后截断 |
| P1 | Delta Timeline（自上一 Scene 后的世界线变化） | 最后截断 |
| P2 | Open Narrative Obligations（伏笔/揭示义务） | 按条截断 |
| P2 | Retrieval Evidence Packs（RAG 父子证据包） | 按包截断 |
| P3 | Style Assets（风格素材） | 优先截断 |
| P0 | Hard Constraints（约束引擎输出） | 永不截断 |
| P4 | Compiler Warnings（风险提示） | 最先截断 |

**双模式**：Writing 模式输出 Delta 摘要；Debug 模式输出全量 Snapshot

## ConstraintEngine

动态生成硬约束，来源：

- **StaticConstraints** — 代码写死的项目级约束
- **KnowledgeConstraints** — CharacterKnowledge 三态：unknown→禁止 / restricted→限制 / misunderstood→按误判表现
- **ForeshadowingConstraints** — status=seeded 且 payoff_scene > 当前 Scene → 禁止提前揭示
- **SceneConstraints** — `must_not_happen` 直接列出

**Tier 驱逐顺序**：P4 → P3 → P2（按条）→ P1（Delta 20→15→10）→ P0 不截断

## 核心函数

```python
async def compile_structure_context(db, novel_id, task, scope, chapter_index=None, arc_id=None, entity_ids=None, character_ids=None, location_ids=None, reveal_mode="author_safe", enable_geo_filter=False, viewpoint_character_id=None) -> StructureContextBundle
def render_context_markdown(context: StructureContextBundle) -> str
```

## Context Budget

各分类预算见 `contracts.py` 中的 `CONTEXT_BUDGET` 常量，编译时自动应用。

## API

```
POST /api/context/compile    # 编译上下文
POST /api/context/render     # 渲染 Markdown
```

## 不做

- 无限上下文塞入
- 全量世界设定注入
- 自动剧情推理
