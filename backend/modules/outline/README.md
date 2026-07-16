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

所有带 `novel_id` 的 outline API（包括查询、写入、preview/apply 和 AI
任务入队）都在领域操作前通过 project facade 校验项目仍处于活跃状态。
不存在和已进入回收站的项目统一返回 404，不读取结构资产或创建任务。

```http
POST/GET/PATCH/DELETE /api/outline/threads...
POST/GET/PATCH/DELETE /api/outline/arcs...
POST/GET/PATCH/DELETE /api/outline/scenes...
GET/PATCH/POST /api/outline/scene-workbench...
POST/GET/PATCH/DELETE /api/outline/foreshadowing...
POST/GET/PATCH/DELETE /api/outline/reveals...
POST /api/outline/generate
POST /api/outline/generate/apply
POST /api/outline/analyze
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
产生的 `deprecated`、`needs_review` 等结构资产。未指定 `status` 时默认排除
`deprecated`；显式传入 `status=deprecated` 时可查看历史。返回的 `items` 和
`total` 使用同一过滤条件，分页在过滤后执行，仍按 `novel_id` 隔离。

## Scene 工作台

Scene 工作台是 Scene 管理、章节映射和结构整理的主入口，直接挂载在前端
`outline/scenes` 子标签。旧 `scene/{scene_id}` 路由会兼容重定向到该入口并通过
`scene_id` query 定位 Scene，不再维护第二套 Scene 管理 UI。

Scene mutation 的稳定内部接口是 `SceneWorkbenchService`。旧
`/api/outline/scenes/*` 路由仅作为兼容 adapter，创建、更新、删除、重排和
legacy split 都应委托 Workbench，以统一章节映射校验、健康摘要和地图影响摘要。
legacy 重排请求必须把当前项目的全部 active Scene 各提交一次，重复、缺失、历史态或
跨项目 ID 会在写入前拒绝；legacy split 同样先校验 source / target，缺失、跨项目或
历史 target 统一按 404 隐藏，同一 source / target 和无效边界按 400 拒绝。成功拆分会
同时更新 `chapter_ids`、`scene_chunks`、章节关联和 span 派生读模型。
默认删除语义是把 Scene 标记为 `deprecated`，不硬删除正史结构资产。
前端 Scene 行菜单将该操作显示为“移入历史”并要求二次确认；正文和
追踪信息保留，用户可通过 `status=deprecated` 历史筛选查看。

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
POST  /api/outline/scene-workbench/replacement-suggestions/apply
```

`GET /api/outline/scene-workbench` 的每个 Scene 条目在保留旧
`scene.scene_chunks` 编辑形状的同时，额外返回两组只读解释字段：

- `span_summaries` 按章节与片段顺序返回 `mapping_status`、中文状态、
  offset / 段落边界、短 anchor 摘要和可直接展示的 `range_label`。
- `overlap_details` 只在同一正文版本的精确 span 真实重叠时返回，
  包含对方 Scene ID / 标题 / 作者可读标签、双方范围与实际重叠区间。

这些字段由 `SceneSpan` 派生读模型生成，不是新的编辑入口；查询与
对方 Scene 标签始终按 `novel_id` 隔离。前端应优先展示中文 label 和标题，
只把 Scene ID 用于定位对方 Scene 或诊断复制。

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
全集计算，不被当前健康桶二次缩窄。健康桶是活跃 Scene 的可操作队列，
全局统计只读取健康计算所需的轻量投影，完整 Scene ORM 记录仅按当前页加载；
章节占用同样使用标量投影，避免分页请求把全项目 Scene 全量物化到 session。
即使同时指定 `status=deprecated` 也不会返回历史 Scene；历史产物仍可通过状态筛选
单独查看。显式 `selected_scene_id` 不在请求页时，服务端
把窗口对齐到目标 Scene 所在页，并在响应 `skip` 返回实际窗口起点；目标不属于当前
novel 或筛选结果时返回 404。

合并 / 拆分都必须先走 preview；执行请求必须包含 `confirmed: true`。
preview 只展示章节映射、字段、剧情线、伏笔 / 揭示和地图摘要影响，不修改数据，
也不因存在关联资产自动阻断。合并不硬删除来源 Scene，只把来源 Scene 标记为
`deprecated` 并保留可追踪 meta。拆分不修改正文内容，只调整 Scene 映射并创建新 Scene。

AI Scene 审稿响应统一由 `SceneDraftReviewService` 生成。`fusion/preview` 要求传入
`primary_scene_id`，返回统一审稿形状：`draft_scene` / `draft_scenes`、
`field_references`、`field_sources`、`source_scene_summaries`、`conflicts`、
`warnings`、`confidence` 和 `reason`。preview 不修改来源 Scene；章节映射和
`scene_chunks` 由系统确定性合并或拆分，LLM 不拥有这些事实字段。
Scene 融合语义草稿通过 project runtime seam 调用受管结构化 LLM step；
只有 `exact/reanchored` 且 draft / source hash / range 重新校验成功的
SceneSpan 正文才会进入 prompt，且 span 必须指向该章当前的
working / canonical 源版本。证据按 working 优先、canonical 回退，
全部来源 Scene 正文合计不超过 24000 字符；完整 prompt 还会按
结构卡和 JSON 开销二次限制。单次最多融合 20 个 Scene，不精确映射只使用 Scene 卡。
LLM 或结构校验失败时返回明确 warning 的确定性草稿，不暴露
provider 原始错误，也不扩大保存权限。
`fusion/save` 支持 `keep_originals`、`deprecate_originals`、`discard` 和
`edit_then_save`。只有 `deprecate_originals` 会把来源 Scene 标记为
`deprecated`，新 Scene 记录 `source="manual_fusion"` 与
`structure_meta.fused_from_scene_ids`，来源 Scene 记录 `fused_into_scene_id`。确认保存会将新 Scene 的 `structure_meta.needs_review` 明确清为 false，并记录 `adopted_at` 和 `source`；preview 中的旧 review 标记不会残留到已采用 Scene。
保存后的 `fusion_strategy="author_reviewed_preview"` 只表示作者已审阅预览，
不把可编辑结果伪装成纯 LLM 或纯确定性产物。

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
`fusion/save` 保存；不提供批量自动采用。已判定为 `keep_separate` 的建议可在
前端每批最多 100 条确认“保持分开”，该操作只将建议标记为 `dismissed`，
不修改 Scene 内容；合并、替换和失败复核仍须逐条预览与确认。来源指纹仍有效的 pending、dismissed、adopted
建议来源对，以及 adopted 融合结果与其来源的组合，由工作台独占处理，
`OutlineStructureDedupService` 的项目级 Scene 扫描会跳过它们；
来源 Scene 变更或废弃后建议失效，才恢复全局扫描资格。

重复提取还复用该队列保存 `suggestion_kind=replacement` 的替换审查。已采用、人工、
已编辑或无合法 deep-import ownership 的 active Scene 不会被自动覆盖；与它们重叠的新
候选保存在 `proposed_scene.draft_scenes`，不参与正文、上下文、RAG 或后续提取。作者可
保留原 Scene、直接替换或只编辑语义字段后替换。替换采用在同一事务内创建 canonical
Scene、软废弃来源、稳定重排、同步 span 和 suggestion 生命周期，并入队 RAG 重建。
前端替换审查将后两种操作明确表述为“采用新 Scene，旧 Scene 移入历史”，
避免把可追踪的软废弃误解为硬删除。

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
`degraded` reason。对 Scene，它会先排除仍由 Phase 1c 融合决定管理的来源对，以及
已采用融合结果与其来源的组合，避免全局语义扫描与导入边界审稿产生两条待办。

应用建议必须由用户确认。Scene 复用 Scene 工作台 merge 逻辑；其他结构资产不会
硬删除，只标记为 `deprecated`，并在 `provenance_meta` 写入
`merged_into_asset_id`、`dedup_source="smart_dedup"` 和 `needs_review=true`。
项目级工作台调用 `apply_structure_dedup_group()` 严格入口：整组先校验资产类型、
状态和 execution fingerprint，任一操作失败直接向上抛出以便 project savepoint
回滚；组内存在 `keep_separate` 时，会在其他写入完成后按最终资产状态重新生成
semantic fingerprints。Scene 融合还要求客户端先调用 Scene 工作台 preview，确认预览后才能进入
待执行组；实际写入仍委托 `SceneWorkbenchService`。

Analyze/generate/Scene extract、PlotStructureGenerator 和结构去重均通过
project runtime seam 获取 client；batch/pair 外层复用同一 client，结果仍只进入
preview/needs_review，不扩大自动 apply 权限。
异步 `plot_structure_generate`、`outline_analyze`、`outline_generate` 和
`outline_chapter_scenes_extract` 使用仅 TaskWorker 可调用的 prepare / execute /
finalize seam：提交时冻结无 secret 的 project LLM execution snapshot（旧任务首次执行时
补建并先做 lease-fenced checkpoint），prepare 阶段在 project `FOR SHARE` 保护下把确认
上下文和生成器输入复制为 plain DTO 并记录 source fingerprint，同时恢复冻结 profile
与 Phase 3 token budget；随后显式 fenced commit 并清空 prepare 阶段的 ORM identity
map，LLM 等待期间 session 必须没有数据库事务。finalize 重新取得
project 短暂排他锁、复核 fresh confirmation，并重建必要上下文/生成器 fingerprint；并发修改
导致漂移时丢弃旧结果，不绑定 preview/result ref。取消或 provider 错误同样不会留下部分
结果。普通 API/service 入口不拥有该 commit 权限，也不会隐式提交调用方事务。
手动 `outline_analyze` 把 `start_chapter / end_chapter` 与已确认 context 中的
`chapter_index / visible_until_chapter` 对齐后才调用模型。确认阶段通过
`get_outline_analysis_context()` 读取范围内按 `scene_index` 排序的 Scene、重叠篇章、
区间重叠或被范围资产显式关联的剧情线，以及伏笔和揭示计划；这些资产会先显示在
AI 参考资料审查台，任务阶段
只按确认记录的 compile options 重编译并核对确认指纹；上下文发生变化时会在 LLM 前
拒绝执行，不会静默追加资料。显式章节范围若未成功加载对应范围 section，确认或回放都会
失败关闭；无范围的历史确认仍可按原语义回放。`confirmation.task` 是唯一经作者确认的分析目标，
任务 metadata 中的兼容性 `instruction` 不能覆盖它。相关人物与世界对象沿用 context 的 Top-K
（人物 6、世界对象 16）。结果保持 `{"analysis": string}` 只读形状，只绑定
`outline_analysis` result ref，不提供 apply，也不写结构资产。
深度导入 Phase 3 传入任务提交时冻结的 project settings snapshot，
`PlotStructureGenerator` 用 project snapshot seam 构造并在 `finally` 关闭 client；
`high_quality=true` 时使用 `max` reasoning，但仍使用冻结 snapshot 中手动选择的 model，不因 worker 启动后项目默认模型变更而漂移。

## Facade

跨模块调用优先走 `modules.outline.facade`。`facade.py` 是兼容 re-export hub，
内部按 seam 拆到子 facade：

- `scene_facade.py`：Scene 读取、创建、更新、章节拆分、深度导入 Scene 原子提交、
  Phase 1c/替换建议持久化和 `SceneContract`
- `structure_dedup_facade.py`：outline 结构资产智能去重建议与应用
- `deep_import_repair_facade.py`：deep import 修复、最小结构补齐和清理
- `foreshadowing_facade.py`：伏笔计划只读上下文
- `analysis_context_facade.py`：按已确认章节范围读取有序 Scene 与相关结构计划；供
  手动大纲分析 context loader 使用
- `thread_facade.py`：按显式 ID 与真实章节锚点读取剧情线的只读 context contract；
  不在缺少章节锚点时默认注入第一章剧情线

`modules.outline.facade.*` 路径仍是唯一跨模块公共 seam，供外部模块 import 和
测试 monkeypatch；子 facade 只是 outline 内部的 locality 拆分。root facade 的
显式 `__all__` 与 public API snapshot 已冻结当前公共面。新增入口前必须证明现有
Scene/repair/dedup/reveal seam 无法表达，并同步 contract、README 和调用方测试；不得
为单一调用方增加 pass-through。当前常用入口包括：

```python
async def get_scene(...)
async def get_outline_analysis_context(...)
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
