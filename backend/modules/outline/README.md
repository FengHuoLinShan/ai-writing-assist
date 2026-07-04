# Module: outline / 大纲与结构管理模块

## 定位

outline 模块把事实层资产组织成剧情结构资产，服务写作、地图、RAG 和 AI 结构生成。

## 负责

- 剧情线 `plot_threads`
- 篇章纲 `outline_arcs`
- 章节卡 `chapter_cards`
- Scene `scenes`
- 伏笔计划 `foreshadowing_plans`
- 揭示计划 `reveal_plans`

## 关键服务

- `PlotThreadService`
- `OutlineArcService`
- `SceneService`
- `OutlineAIWorkflowService`
- `OutlineStructureCleanupService`
- `SceneWorkbenchService`
- `SceneDraftReviewService`
- `OutlineStructureDedupService`
- `ForeshadowingPlanService`
- `RevealPlanService`
- `PlotStructureGenerator`

## API

```http
POST/GET/PATCH/DELETE /api/outline/threads...
POST/GET/PATCH/DELETE /api/outline/arcs...
POST/GET/PATCH/DELETE /api/outline/scenes...
GET/PATCH/POST /api/outline/scene-workbench...
POST/GET/PATCH/DELETE /api/outline/foreshadowing...
POST/GET/PATCH/DELETE /api/outline/reveals...
POST /api/outline/generate
```

结构资产列表筛选：

```http
GET /api/outline/threads
GET /api/outline/arcs
GET /api/outline/foreshadowing
GET /api/outline/reveals
```

以上列表接口支持 `status`、`source`、`workflow_id`、`needs_review`、
`skip`、`limit` query 参数。其中 `status` 匹配表字段；`source`、
`workflow_id`、`needs_review` 匹配 `provenance_meta`，用于整理深度导入
产生的 `deprecated`、`needs_review` 等结构资产。返回的 `total` 为筛选后的
总数，仍按 `novel_id` 隔离。

## Scene 工作台

Scene 工作台是 Scene 管理、章节映射和结构整理的主入口。旧大纲页
“场景卡”子标签只保留跳转，不再维护第二套管理 UI。

Scene mutation 的稳定内部接口是 `SceneWorkbenchService`。旧
`/api/outline/scenes/*` 路由仅作为兼容 adapter，创建、更新、删除、重排和
legacy split 都应委托 Workbench，以统一章节映射校验、健康摘要和地图影响摘要。
默认删除语义是把 Scene 标记为 `deprecated`，不硬删除正史结构资产。

工作台 API：

```http
GET   /api/outline/scene-workbench
PATCH /api/outline/scene-workbench/scenes/{scene_id}/mapping
POST  /api/outline/scene-workbench/merge/preview
POST  /api/outline/scene-workbench/merge
POST  /api/outline/scene-workbench/split/preview
POST  /api/outline/scene-workbench/split
POST  /api/outline/scene-workbench/fusion/preview
POST  /api/outline/scene-workbench/fusion/save
POST  /api/outline/scene-workbench/cross-chapter/detect
```

`scenes.structure_meta` 保存结构整理元信息，例如：

- `needs_organize`
- `reviewed_at`
- `merged_into_scene_id`
- `merged_from_scene_ids`
- `split_from_scene_id`
- `split_at_chapter_index`

健康项由 `SceneWorkbenchService` 派生，固定为 `未复核`、`未关联章节`、
`缺设定`、`待整理`。跨多章 Scene 是正常形态，不作为默认风险。

合并 / 拆分都必须先走 preview；执行请求必须包含 `confirmed: true`。
preview 只展示章节映射、字段、剧情线、伏笔 / 揭示和地图摘要影响，不修改数据，
也不因存在关联资产自动阻断。合并不硬删除来源 Scene，只把来源 Scene 标记为
`deprecated` 并保留可追踪 meta。拆分不修改正文内容，只调整 Scene 映射并创建新 Scene。

AI Scene 草稿统一由 `SceneDraftReviewService` 生成。`fusion/preview` 要求传入
`primary_scene_id`，返回统一审稿形状：`draft_scene` / `draft_scenes`、
`field_references`、`field_sources`、`source_scene_summaries`、`conflicts`、
`warnings`、`confidence` 和 `reason`。preview 不修改来源 Scene；章节映射和
`scene_chunks` 由系统确定性合并或拆分，LLM 不拥有这些事实字段。
`fusion/save` 支持 `keep_originals`、`deprecate_originals`、`discard` 和
`edit_then_save`。只有 `deprecate_originals` 会把来源 Scene 标记为
`deprecated`，新 Scene 记录 `source="manual_fusion"` 与
`structure_meta.fused_from_scene_ids`，来源 Scene 记录 `fused_into_scene_id`。

跨章 Scene 识别通过 `cross-chapter/detect` 创建异步任务，只生成相邻 Scene
递归扩展建议，不直接改库。前端打开建议后进入同一个 Scene 草稿审稿界面，
由用户选择主 Scene 并确认编辑后再复用 `fusion/save` 保存。

## 结构资产智能去重

outline 模块拥有剧情线、篇章纲、Scene、伏笔和揭示的去重判断与应用规则。
`OutlineStructureDedupService` 先用标题 / 摘要 / 章节范围召回相似资产，再用
RAG 片段或资产摘要作为证据交给 LLM 判断 `merge`、`deprecate_duplicate`、
`keep_separate` 或 `needs_review`。RAG 不可用时降级为摘要证据，并在建议中保留
`degraded` reason。

应用建议必须由用户确认。Scene 复用 Scene 工作台 merge 逻辑；其他结构资产不会
硬删除，只标记为 `deprecated`，并在 `provenance_meta` 写入
`merged_into_asset_id`、`dedup_source="smart_dedup"` 和 `needs_review=true`。

## Facade

跨模块调用优先走 `facade.py`，当前主要提供 Scene 读取能力：

```python
async def get_scene(...)
async def get_scene_contract(...)
async def get_scenes_by_novel(...)
async def get_scenes_by_chapter(...)
async def suggest_structure_dedup(...)
async def apply_structure_dedup(...)
```

异步 AI 任务入口只解析 task meta、更新进度并委托 `OutlineAIWorkflowService`；
facade 只保留跨模块稳定函数名和返回形状。Scene 读取继续通过 facade 暴露给跨模块
调用；Scene mutation 统一归 Workbench service 拥有，API/facade 不直接拼装
Scene 业务规则。

## 测试

```bash
cd backend
pytest modules/outline/tests/ -v
```
