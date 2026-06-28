# Module: outline / 大纲与结构管理模块

## 定位

outline 模块负责把事实层资产组织成“可执行的剧情计划”。

当前活跃对象：

- `plot_threads`：剧情线
- `outline_arcs`：篇章纲
- `chapter_cards`：章节卡
- `scenes`：最小叙事单元
- `foreshadowing_plans`：伏笔计划
- `reveal_plans`：揭示计划

## 架构现状

- HTTP 入口在 `api.py`
- 业务逻辑在 `services.py`
- AI 结构生成拆在 `generation/`
- 当前**已有** `facade.py`，主要对外提供 Scene 相关稳定接口，供 rag、world/map 等模块跨 seam 调用

## 职责

- 剧情线、篇章纲、Scene、伏笔、揭示计划的 CRUD
- Scene 顺序重排
- 按章节查询相关 Scene
- 根据 AI 参考资料确认记录，发起结构生成任务
- 为其他模块提供 Scene 查询能力

## 关键服务

- `PlotThreadService`
- `OutlineArcService`
- `SceneService`
- `ForeshadowingPlanService`
- `RevealPlanService`
- `PlotStructureGenerator`

## `generation/` 子模块

`PlotStructureGenerator` 不是神类，当前职责被拆为：

- `context_builder`：组装结构生成所需上下文
- `parser`：调用 LLM、解析 JSON、处理重试/降级
- `persister`：把结果写入 thread / arc / scene / foreshadowing / reveal
- `models`：生成流程专用 Pydantic 模型

## API

```http
POST   /api/outline/threads
GET    /api/outline/threads
GET    /api/outline/threads/{thread_id}
PATCH  /api/outline/threads/{thread_id}
DELETE /api/outline/threads/{thread_id}

POST   /api/outline/arcs
GET    /api/outline/arcs
GET    /api/outline/arcs/{arc_id}
PATCH  /api/outline/arcs/{arc_id}
DELETE /api/outline/arcs/{arc_id}

POST   /api/outline/scenes
GET    /api/outline/scenes
GET    /api/outline/scenes/ordered
GET    /api/outline/scenes/by-chapter
GET    /api/outline/scenes/{scene_id}
PATCH  /api/outline/scenes/{scene_id}
DELETE /api/outline/scenes/{scene_id}
POST   /api/outline/scenes/reorder
POST   /api/outline/scenes/split-chapters

POST   /api/outline/foreshadowing
GET    /api/outline/foreshadowing
GET    /api/outline/foreshadowing/{plan_id}
PATCH  /api/outline/foreshadowing/{plan_id}
DELETE /api/outline/foreshadowing/{plan_id}

POST   /api/outline/reveals
GET    /api/outline/reveals
GET    /api/outline/reveals/{plan_id}
PATCH  /api/outline/reveals/{plan_id}
DELETE /api/outline/reveals/{plan_id}

POST   /api/outline/generate
```

## 对外 facade

跨模块调用优先走 `modules.outline.facade`，当前常用入口包括：

- `get_scene()`
- `get_scene_contract()`
- `get_scenes_by_novel()`
- `get_scenes_by_chapter()`

## Scene 设计要点

- `scenes` 是当前最小叙事单元的权威表
- `scene_index` 是逻辑顺序
- `scene_chunks` 保存 Scene 到正文物理区间的映射
- `chapter_cards.scene_cards` 只保留历史兼容/冗余上下文，不是当前权威来源
- 写作页、地图摘要、RAG `scene_id` 关联都依赖 `scenes` 表

## 测试

```bash
cd backend
pytest modules/outline/tests/ -v
```
