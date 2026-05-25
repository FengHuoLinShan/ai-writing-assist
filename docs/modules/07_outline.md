# Module: outline / 结构化剧情模块

## 定位

outline 模块是核心创作模块。把事实层资产转化为可执行的剧情结构。

## 核心产物

- PlotThread：剧情线（6 种类型）
- OutlineArc：篇章纲（8-15 章闭环）
- ChapterCard：章节卡（scene_cards 放 JSONB）
- ForeshadowingPlan：伏笔计划
- RevealPlan：信息揭示计划

## 数据表

- plot_threads — name / thread_type / visible_goal / hidden_truth / start_chapter / planned_payoff_chapter
- outline_arcs — title / arc_index / start_chapter / end_chapter / arc_goal / core_conflict / entry_hook / midpoint_turn / climax / result / next_hook
- chapter_cards — chapter_index / chapter_goal / main_conflict / must_happen / must_not_happen / scene_cards(JSONB) / 完整字段
- foreshadowing_plans — surface_meaning / hidden_meaning / planned_seed_chapter / planned_payoff_chapter
- reveal_plans — target_type / target_id / secret_summary / reveal_stages JSONB

## 结构生成流程

```text
Context Compiler → 剧情结构 Prompt → 候选 → 用户确认 → 章节场景 Prompt → 候选 → Review → 用户确认
```

## API（全部 CRUD）

```
# 剧情线
POST/GET/DELETE /api/outline/threads

# 篇章纲
POST/GET/DELETE /api/outline/arcs

# 章节卡
POST/GET/GET{id}/PUT/DELETE /api/outline/chapters

# 伏笔
POST/GET/DELETE /api/outline/foreshadowing

# 揭示
POST/GET/DELETE /api/outline/reveals
```

## Facade

```python
# PlotThread
async def create_thread(db, novel_id, data) -> PlotThreadResponse
async def update_thread(db, thread_id, data, novel_id) -> PlotThreadResponse
async def list_thread_summaries(db, novel_id, limit=50) -> list[dict]

# OutlineArc
async def create_arc(db, novel_id, data) -> OutlineArcResponse
async def update_arc(db, arc_id, data, novel_id) -> OutlineArcResponse
async def list_arc_summaries(db, novel_id, limit=50) -> list[dict]

# ChapterCard
async def get_chapter_card(db, novel_id, chapter_index) -> ChapterCardContext | None
async def create_chapter_cards_from_candidate(db, novel_id, candidate_payload) -> list[ChapterCardContext]
```

## 异步任务

- `@task_handler("plot_structure_generate")` — 从正文生成剧情线+篇章纲（支持增量）
- `@task_handler("chapter_card_extraction")` — 逐章从正文提取章节卡字段

章节卡提取流程：检查正文 → 跳过已有卡 → LLM 提取 7 个核心字段（chapter_goal, main_conflict, emotional_point, ending_hook, scene_cards, must_happen/not_happen, visible/hidden_progress）→ 创建 candidate 状态章节卡

## 不做

- 一次性生成 500 章全部章节卡
- 复杂多 Agent 大纲辩论
- 自动无确认修改正史大纲
