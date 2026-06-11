# Module: outline / 大纲与结构管理模块

## 定位

outline 模块管理剧情计划的结构层：把事实组织成可执行的剧情计划。主干实体包括剧情线（PlotThread）、篇章纲（OutlineArc）、Scene 卡（Scene）、伏笔计划（ForeshadowingPlan）、揭示计划（RevealPlan）。

无 facade 层，API 直接路由到 services。

## 数据表

| 表 | 职责 |
|----|------|
| `plot_threads` | 剧情线：主线/支线/隐藏线，含 visible_goal/hidden_truth 双视角字段 |
| `outline_arcs` | 篇章纲：按 arc_index 排序，含 arc_goal/core_conflict/climax 等结构字段 |
| `scenes` | Scene 卡：叙事结构的最小可编辑单元，scene_index 逻辑排序，含 scene_chunks 物理映射 |
| `foreshadowing_plans` | 伏笔计划：planned_seed→reinforce→payoff 状态链 |
| `reveal_plans` | 信息揭示计划：分层逐步披露，reveal_stages JSONB |

## Services

- **PlotThreadService** — 剧情线 CRUD
- **OutlineArcService** — 篇章纲 CRUD
- **SceneService** — Scene 卡 CRUD + 批量重排（reorder）
- **PlotStructureGenerator** — AI 剧情结构生成（调用 LLM `structure_plot.md` prompt）

## API

```
# PlotThreads
POST   /api/outline/threads                     # 创建剧情线
GET    /api/outline/threads                      # 剧情线列表（分页）
GET    /api/outline/threads/{id}                 # 剧情线详情
PATCH  /api/outline/threads/{id}                 # 更新剧情线
DELETE /api/outline/threads/{id}                 # 删除剧情线

# OutlineArcs
POST   /api/outline/arcs                         # 创建篇章纲
GET    /api/outline/arcs                         # 篇章纲列表（分页）
GET    /api/outline/arcs/{id}                    # 篇章纲详情
PATCH  /api/outline/arcs/{id}                    # 更新篇章纲
DELETE /api/outline/arcs/{id}                    # 删除篇章纲

# Scenes
POST   /api/outline/scenes                       # 创建 Scene 卡
GET    /api/outline/scenes                       # Scene 列表（分页）
GET    /api/outline/scenes/ordered               # 按 scene_index 排序全量获取
GET    /api/outline/scenes/by-chapter            # 按 chapter_index 查询关联 Scene
GET    /api/outline/scenes/{id}                  # Scene 详情
PATCH  /api/outline/scenes/{id}                  # 更新 Scene
DELETE /api/outline/scenes/{id}                  # 删除 Scene（软删除）
POST   /api/outline/scenes/reorder              # 批量重排 Scene 顺序

# AI Generation
POST   /api/outline/generate                     # AI 生成剧情结构（plot_threads + outline_arcs）
```

## Scene 数据模型

```python
class Scene(Base, UUIDMixin, TimestampMixin, StatusMixin, NovelMixin):
    scene_index: int          # 逻辑顺序（从 0 开始）
    title: str | None
    goal: str | None          # 此 Scene 要完成什么
    core_conflict: str | None
    emotional_beat: str | None
    must_happen: str | None
    must_not_happen: str | None
    narrative_tag: str        # inciting_incident / rising_action / climax / valley / transition / hook / payoff / draft
    source: str               # manual / deep_import / ai_generated
    scene_chunks: list        # 物理映射：Scene → Chapter 位置区间
    chapter_ids: list         # 关联 Chapter ID 列表
    pov_character_id: str | None  # POV 人物 ID
```

## Scene 与 Chapter 的 M:N 关系

通过 `scene_chunks` JSONB 实现多对多映射：
```json
[
  {"chapter_id": "uuid", "start_pos": 0, "end_pos": 1500},
  {"chapter_id": "uuid", "start_pos": 0, "end_pos": 3000}
]
```

同一 Chapter 可跨 Scene（如第 5 章前 1500 字属 Scene 1，后 1500 字属 Scene 2），右侧 Scene 卡面板根据光标位置动态切换。
