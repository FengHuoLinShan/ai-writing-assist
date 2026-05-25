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

## 不做

- 一次性生成 500 章全部章节卡
- 复杂多 Agent 大纲辩论
- 自动无确认修改正史大纲
