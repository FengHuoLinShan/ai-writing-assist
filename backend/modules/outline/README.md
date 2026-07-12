# Module: outline / 大纲与结构管理模块

## 定位

outline 模块把事实层资产组织成剧情结构资产，服务写作、地图、RAG 和 AI 结构生成。

## 负责

- 剧情线 `plot_threads`
- 篇章纲 `outline_arcs`
- Scene `scenes`
- SceneSpan `scene_spans`（由 `scene_chunks` 派生的只读查询索引）
- SceneChapterLink `scene_chapter_links`（Scene 与章节的轻量关联）
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
POST /api/outline/generate/apply
POST /api/outline/chapter-scenes/extract
POST /api/outline/chapter-scenes/apply
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

Scene 工作台是 Scene 管理、章节映射和结构整理的主入口，直接挂载在前端
`outline/scenes` 子标签。旧 `scene/{scene_id}` 路由会兼容重定向到该入口并通过
`scene_id` query 定位 Scene，不再维护第二套 Scene 管理 UI。

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
GET   /api/outline/scene-workbench/fusion-suggestions
POST  /api/outline/scene-workbench/fusion-suggestions/dismiss
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
顶层健康键保持四类，`health_details.needs_organize` 进一步区分
Scene 结构、正文定位和待处理跨章融合建议；`health.needs_organize.breakdown`
提供各子类的 Scene 数量。`采用/标记已检查`只处理 Scene 审阅状态，
正文定位必须通过独立确认命令处理。
工作台筛选分三层：健康筛选、常用管理筛选和高级导入诊断筛选。`GET
/api/outline/scene-workbench` 支持 `health`、`q`、`chapter_from`、
`chapter_to`、`status`、`source`、`needs_review`、`workflow_id`、
`boundary_status`、`phase`、`phase1a_fallback`、`confidence_band`、
`skip` 和 `limit` query 参数；`confidence_band` 固定为 `low`、`medium`、
`high` 三档，分别表示 `<0.5`、`0.5-0.8` 和 `>=0.8`。健康筛选在服务端
应用，返回的 `total` 与分页都基于筛选后结果；健康统计仍按其他管理筛选后的
全集计算，不被当前健康桶二次缩窄。显式 `selected_scene_id` 不在请求页时，服务端
把窗口对齐到目标 Scene 所在页，并在响应 `skip` 返回实际窗口起点；目标不属于当前
novel 或筛选结果时返回 404。

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
`structure_meta.fused_from_scene_ids`，来源 Scene 记录 `fused_into_scene_id`。确认保存会将新 Scene 的 `structure_meta.needs_review` 明确清为 false，并记录 `adopted_at` 和 `source`；preview 中的旧 review 标记不会残留到已采用 Scene。

`generate` 只把 AI 结构生成为 `draft_structure` review preview，任务结果标记
`requires_apply=true` 且不写入剧情线、篇章纲、Scene、伏笔或揭示表。作者编辑后
通过 `generate/apply` 提交 `confirmed=true`；服务在同一事务内锁定源 task，复核
novel/action/fresh confirmation 和各类条目数，然后写入普通 `draft` 工作资产，并记录
`source=ai_generated / adopted_at / adopted_from_preview_task_id`。重放同一 task 返回首次
采用结果，不重复建资产。旧 `plot_structure_generate` task 也只产生 preview，且不能作为
`generate/apply` 的源 task；深度导入则继续由其一次性授权流水线显式
`persist=true` 写入工作资产。采用使用 savepoint 严格全成功语义：任一预期资产写入
失败则整批回滚，源 task 仍保持可采用。

深度导入 Phase 3 把每条结构的 `confidence / needs_review / review_reason /
supporting_scene_ids` 写入 `provenance_meta`；无有效 Scene 证据、低置信或无法解析目标的
揭示保留为 review 提案。无法解析的 reveal 不会用 zero UUID 伪造已落库资产。

`chapter-scenes/extract` 保留原有异步任务路由，但任务结果只返回 `draft_scenes` preview、`scene_ids=[]` 和 `requires_apply=true`，不写 `scenes` 表，也不把 context confirmation 当作结果采用。作者编辑后通过 `chapter-scenes/apply` 传 `confirmed=true`；服务会复核同 novel/action 的 fresh confirmation，然后创建普通 `draft` Scene，写入 `adopted_at / source=ai_generated / adopted_from_preview_task_id`，并仅在此时绑定真实 `outline_scene` result refs。apply 只接受作者可编辑的 Scene 内容/章节字段，忽略请求中伪造的 `structure_meta`、source/status 和 POV 引用，系统 provenance 始终重建。

新 Scene 写入的 `status` 只允许 `draft / canonical`；更新路径另允许 `deprecated` 用于软废弃。兼容期仍可读取存量 `candidate` Scene，但新 create/apply/split/fusion 不再写 candidate。

高质量深度导入 Phase 1c 生成同章候选、跨章延续和重复窗口的 Scene 融合建议。建议持久化在
`scene_fusion_suggestions`，使用 `pending/adopted/dismissed/stale`
生命周期；刷新后仍可继续处理。前端打开建议后进入同一个
Scene 草稿审稿界面，由用户选择主 Scene 并确认编辑后再复用
`fusion/save` 保存；不提供批量自动采用。

### SceneSpan 派生读模型

`scene_spans` 是 outline 拥有的派生读模型，用于把 Scene 的逻辑卡片映射到
具体章节文本片段。权威输入仍是 `scenes.scene_chunks`；现有 API/前端继续返回
`scene_chunks`，不把 `scene_spans` 作为新的编辑入口。Scene 与章节不是一对一：一个 Scene 可覆盖一至多章，同一章也可容纳多个 span 不重叠的独立 Scene。健康检查只在同一正文版本内比较精确 span，报告真实重叠、缺口或映射不一致。

同步规则：

- `SceneRepository` 统一从 `scene_chunks` 同步 `scene_chapter_links` 和
  `scene_spans`，覆盖 create、create_many、update、Workbench merge/split/fusion、
  断章、deprecated 和 deep-import cleanup。
- Workbench 的 `start_pos/end_pos` 映射为 `start_offset/end_offset`；deep-import 的
  `start_paragraph/end_paragraph` 保留为段落边界；缺失 offset 时允许 span offset 为
  null。
- `scene_spans.source/status` 镜像 Scene，不建立独立生命周期。默认只读查询排除
  `deprecated` span。
- span 以 `(novel_id, scene_id, content_mode, part_no)` 唯一，并保存
  `source_draft_id/source_content_hash/mapping_status/anchor_hash`。新正文版本使用
  anchor 字面匹配重定位：唯一命中为 `reanchored`，无精确范围为
  `chapter_only`，歧义/缺失为 `unresolved`。只有精确绑定当前源 hash 的
  span 可自动归因证据；`chapter_only` / `unresolved` 会进入 Scene
  工作台“待整理”人工复核入口。人工可确认“仅按章节关联”，
  但该确认只隐藏当前 fingerprint 的注意项，不改写 `mapping_status`，
  也不放开 RAG/context 的精确证据归因。
- `chapter_ids` 变化只同步章节关联；`scene_chunks` 变化才重建 span；
  Scene `status/source` 变化只原地镜像到现有 span，不得丢失版本绑定和 anchor。
- 跨模块调用只能通过 `modules.outline.facade.get_scene_spans_by_chapter()` /
  `get_scene_spans_for_scene()` 获取 `SceneSpanContract`。

`scene_summary_checkpoints` 是可重建的派生摘要，保存可见截止位置、source refs
与 `based_on_hash`。checkpoint 只能消费截止位置以前的精确 span；hash 失效时
忽略。缺少 checkpoint 时只降级为可见原文摘录，不使用可能包含未来内容的
完整 Scene 卡摘要。

`get_reader_reveal_decision()` 是 `reveal_plans` 的确定性读者可见性 seam。
同章但无法确定先后的 reveal stage 不视为已揭示；context 在返回对象前会再执行该判定。

## 结构资产智能去重

outline 模块拥有剧情线、篇章纲、Scene、伏笔和揭示的去重判断与应用规则。
`OutlineStructureDedupService` 先用标题 / 摘要 / 章节范围召回相似资产，再用
RAG 片段或资产摘要作为证据交给 LLM 判断 `merge`、`deprecate_duplicate`、
`keep_separate` 或 `needs_review`。RAG 不可用时降级为摘要证据，并在建议中保留
`degraded` reason。

应用建议必须由用户确认。Scene 复用 Scene 工作台 merge 逻辑；其他结构资产不会
硬删除，只标记为 `deprecated`，并在 `provenance_meta` 写入
`merged_into_asset_id`、`dedup_source="smart_dedup"` 和 `needs_review=true`。

Analyze/generate/Scene extract、PlotStructureGenerator 和结构去重均通过
project runtime seam 获取 client；batch/pair 外层复用同一 client，结果仍只进入
preview/needs_review，不扩大自动 apply 权限。
深度导入 Phase 3 传入任务提交时冻结的 project settings snapshot，
`PlotStructureGenerator` 用 project snapshot seam 构造并在 `finally` 关闭 client；
`high_quality=true` 时使用 `max` reasoning，但仍使用冻结 snapshot 中手动选择的 model，不因 worker 启动后项目默认模型变更而漂移。

## Facade

跨模块调用优先走 `modules.outline.facade`。`facade.py` 是兼容 re-export hub，
内部按 seam 拆到子 facade：

- `scene_facade.py`：Scene 读取、创建、更新、章节拆分、Phase 1c 融合建议持久化和 `SceneContract`
- `structure_dedup_facade.py`：outline 结构资产智能去重建议与应用
- `deep_import_repair_facade.py`：deep import 修复、最小结构补齐和清理
- `foreshadowing_facade.py`：伏笔计划只读上下文

`modules.outline.facade.*` 路径仍是唯一跨模块公共 seam，供外部模块 import 和
测试 monkeypatch；子 facade 只是 outline 内部的 locality 拆分。root facade 的
显式 `__all__` 与 public API snapshot 已冻结当前公共面。新增入口前必须证明现有
Scene/repair/dedup/reveal seam 无法表达，并同步 contract、README 和调用方测试；不得
为单一调用方增加 pass-through。当前常用入口包括：

```python
async def get_scene(...)
async def get_scene_contract(...)
async def get_scene_spans_by_chapter(...)
async def get_scene_spans_for_scene(...)
async def bind_scene_spans_to_source(...)
async def get_scene_summary_checkpoint(...)
async def rebuild_scene_summary_checkpoint(...)
async def get_reader_reveal_decision(...)
async def get_scenes_by_novel(...)
async def get_scenes_by_chapter(...)
async def suggest_structure_dedup(...)
async def apply_structure_dedup(...)
```

异步 AI 任务入口只解析 task meta、更新进度并委托 `OutlineAIWorkflowService`；

`get_scene_span_coverage()` 是只读稳定 facade，按 `novel_id + content_mode + active
Scene/status` 统计 exact/reanchored/chapter_only/unresolved、无 span Scene 和 precise rate。
该指标只表示运行覆盖，不代替 Scene 边界 P/R/F1。
facade 只保留跨模块稳定函数名和返回形状。Scene 读取继续通过 facade 暴露给跨模块
调用；Scene mutation 统一归 Workbench service 拥有，API/facade 不直接拼装
Scene 业务规则。

## 与 writing 的依赖方向

outline 可以通过 `modules.writing.facade` / `modules.writing.contracts` 只读消费
正文草稿和章节索引，用于结构生成上下文、Scene 工作台健康项和跨章 Scene 检测；不得
直接访问 writing 的 model / repository / service。

writing 对 outline 的同步操作不再在服务模块顶层 import outline facade。写作断章和
冲突检查通过可注入 provider 调用 outline split / Scene contract 能力，默认 provider
在运行时 lazy import outline facade，保持旧行为和 wire shape 不变。

## 测试

```bash
cd backend
pytest modules/outline/tests/ -v
```
