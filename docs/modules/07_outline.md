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
- `SceneWorkbenchService`
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
POST   /api/outline/scenes/split

GET    /api/outline/scene-workbench
PATCH  /api/outline/scene-workbench/scenes/{scene_id}/mapping
POST   /api/outline/scene-workbench/merge/preview
POST   /api/outline/scene-workbench/merge
POST   /api/outline/scene-workbench/split/preview
POST   /api/outline/scene-workbench/split
POST   /api/outline/scene-workbench/fusion/preview
POST   /api/outline/scene-workbench/fusion/save

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

跨模块调用优先走 `modules.outline.facade`。`facade.py` 是兼容 re-export hub，
内部按 seam 拆到 `scene_facade.py`、`structure_dedup_facade.py`、
`deep_import_repair_facade.py` 和 `foreshadowing_facade.py`。子 facade 只提升
outline 内部 locality；旧 `modules.outline.facade.*` 仍是跨模块公共 seam 和测试
monkeypatch 路径。

当前常用入口包括：

- `get_scene()`
- `get_scene_contract()`
- `get_scenes_by_novel()`
- `get_scenes_by_chapter()`

## 与 writing 的依赖方向

outline 可以只读依赖 `modules.writing.facade` / `modules.writing.contracts` 加载最新
草稿和章节索引，供结构生成上下文、Scene 工作台和跨章 Scene 检测使用；outline 不直接
访问 writing 的 model / repository / service。

writing 侧不在服务模块顶层依赖 outline facade。断章同步 Scene chunk 和冲突检查读取
Scene contract 都通过可注入 provider 完成；默认 provider 在调用时 lazy import
`modules.outline.facade`，因此旧的用户流程、HTTP/API schema 和 wire shape 保持不变。

## Scene 设计要点

- `scenes` 是当前最小叙事单元的权威表
- `scene_index` 是逻辑顺序
- `scene_chunks` 保存 Scene 到正文物理区间的映射
- `structure_meta` 保存结构整理元信息，如 `needs_organize`、`reviewed_at`、`merged_into_scene_id`、`merged_from_scene_ids`、`split_from_scene_id`、`split_at_chapter_index`
- 深度导入 / 手动融合等自动整理来源通过 `source` 与 `structure_meta` / `provenance_meta` 暴露给管理筛选；手动融合新 Scene 使用 `source="manual_fusion"`
- `chapter_cards.scene_cards` 只保留历史兼容/冗余上下文，不是当前权威来源
- 写作页、地图摘要、RAG `scene_id` 关联都依赖 `scenes` 表

## Scene 工作台

Scene 工作台是 Scene 管理、章节映射和结构整理的主入口；大纲页旧“场景卡”
子标签只保留跳转页，不再承载创建、编辑、排序、删除等完整管理 UI。

第一版健康项固定为：

- `未复核`：导入 / AI 生成来源仍处于草稿或候选，且缺少人工复核标记
- `未关联章节`：Scene 没有关联章节，或存在有正文草稿但未归入任何 Scene 的章节
- `缺设定`：目标、核心冲突、必须发生、禁止发生等关键字段缺失
- `待整理`：人工标记、重复章节映射、chunk/chapter 不一致等结构整理信号

跨多章 Scene 是正常创作形态，不作为默认风险。合并 / 拆分必须先请求影响预览，
再二次确认执行；预览只提示章节映射、字段、剧情线、伏笔 / 揭示和地图摘要影响，
不自动阻断。合并来源 Scene 标记为 `deprecated` 而不是硬删除；拆分只调整映射并
创建新 Scene，不修改正文内容。

Scene 工作台区分机械合并和 AI 融合草稿。机械合并由目标 Scene 吸收来源 Scene，
来源标记为 `deprecated`；AI 融合先由用户选择 `primary_scene_id`，`fusion/preview`
返回可编辑草稿、字段来源引用和冲突提示，再由用户选择保留原 Scene、保存并废弃原
Scene、放弃结果或继续编辑后保存。只有“保存并废弃原 Scene”会把来源 Scene 标记为
`deprecated`；所有融合新 Scene 都记录 `structure_meta.fused_from_scene_ids` 和主
Scene 信息。

剧情线、篇章纲、伏笔和揭示列表支持按 `status`、`source`、`workflow_id`、
`needs_review`、分页参数筛选；`source` / `workflow_id` / `needs_review` 来自
`provenance_meta`，用于整理深度导入 Phase 3 结构资产。

## 测试

```bash
cd backend
pytest modules/outline/tests/ -v
```
