# Module: outline / 大纲与结构管理模块

## 定位

outline 模块把事实层资产组织成剧情结构资产，服务写作、地图、RAG 和 AI 结构生成。

## 负责

- 小说总纲 `story_outline_heads` / `story_outline_revisions`
- 剧情线 `plot_threads`
- 篇章纲 `outline_arcs`
- Scene `scenes`
- SceneSpan `scene_spans`（由 `scene_chunks` 派生的只读查询索引）
- SceneChapterLink `scene_chapter_links`（Scene 与章节的轻量关联）
- 伏笔计划 `foreshadowing_plans`
- 揭示计划 `reveal_plans`

## 关键服务

- `StoryOutlineService`
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
- `P20GenerationService`
- `P20ApplyService`

## API

所有带 `novel_id` 的 outline API（包括查询、写入、preview/apply 和 AI
任务入队）都在领域操作前通过 project facade 校验项目仍处于活跃状态。
不存在和已进入回收站的项目统一返回 404，不读取结构资产或创建任务。

```http
GET  /api/outline/story-outline
POST /api/outline/story-outline/generate
POST /api/outline/story-outline/generate/apply
POST /api/outline/story-outline/revisions
GET  /api/outline/story-outline/revisions
GET  /api/outline/story-outline/revisions/{revision_id}
POST /api/outline/story-outline/revisions/{revision_id}/apply
POST/GET/PATCH/DELETE /api/outline/threads...
POST/GET/PATCH/DELETE /api/outline/arcs...
POST/GET/PATCH/DELETE /api/outline/scenes...
GET/PATCH/POST /api/outline/scene-workbench...
POST/GET/PATCH/DELETE /api/outline/foreshadowing...
POST/GET/PATCH/DELETE /api/outline/reveals...
POST /api/outline/generate
POST /api/outline/generate/apply
POST /api/outline/analyze
```

正文到 Scene 的自动提取统一由 imports 深度导入 Scene 阶段负责；outline 不再维护独立的
章节 Scene 提取、preview 或 apply 工作流。

## 小说总纲

`StoryOutline` 是 outline 拥有的小说级上位结构资产，层级为
`World → StoryOutline → OutlineArc → Scene`。它通常覆盖整部、至少覆盖半部小说的
长期创作方向，不是篇章纲、Scene 或逐章计划的提前展开；剧情线是总纲导航中可描述的
长期方向，但现有 `plot_threads` 仍是独立的可执行结构资产。

总纲使用每项目唯一的 `story_outline_heads` 和不可变的
`story_outline_revisions` 持久化。revision 保存标题、creative core、可读的
`outline_markdown`、主要剧情线导航、宏观推进、开放决策及 source/provenance；版本号在
项目内单调递增。所有查询显式带 `novel_id`。创建新版或应用历史版都必须提交调用方看到的
`base_revision_id`，服务在锁定 head 后执行 CAS；冲突返回 409。每次写入还要求项目内唯一
`idempotency_key`，相同请求重试返回首次 revision，键被不同请求复用时返回 409。
head 的 current 指针以及 revision 的 base/restore 来源都使用 `(revision_id, novel_id)`
复合外键，数据库不能把一个项目的版本挂到另一个项目；revision 更新另由数据库 trigger
拒绝，历史内容只能复制成更高版本的新 revision。

每个已采用 revision 的 provenance 都持有 version-bound
`story_execution_profile.v1` 和确定性 SHA-256 hash。作者可在 provenance 中显式提供
profile；否则服务从本 revision 的 creative core、剧情线收束方向和宏观状态变化确定性派生。
恢复历史 revision 时继承目标 revision 的 profile，而不是用恢复请求重新派生。它只属于
story layer，不复用 World Bible 页面。

跨模块正文/审查调用通过 `facade.get_scene_execution_bundle(db, novel_id, scene_id)` 取得
冻结的 `SceneExecutionBundleContract`（可 `dataclasses.asdict()`）：它包含当前总纲
revision/version/content hash、profile/hash、Scene 的 POV、知识边界、entry/exit、outcome/cost、
continuity、new fact candidates、must_happen/must_not_happen、`missing_fields`、精确
`upstream_manifest(type/id/version/hash)` 和 `contract_hash`。缺少当前总纲时返回明确
`current_story_outline` omission，绝不伪造 profile 或上游引用；该 seam 不写 Scene、正文或依赖表。

`POST .../generate` 创建 `story_outline_generate` 异步任务，请求固定包含
`novel_id / author_intent / planned_scale / coverage`，可显式选择人物和世界对象，
并可以通过 `include_current_outline` 或 `base_revision_id` 引入一份已有总纲。
返回的 task result 是通过 `StoryOutlineContent` strict schema 校验的可编辑 preview；
任务不建 revision，更不写 PlotThread、OutlineArc、Scene、伏笔或揭示计划。
作者编辑后通过 `POST .../generate/apply` 提交 `source_task_id`、strict content、
`base_revision_id / idempotency_key / confirmed=true` 明确采用。服务端严格校验
completed task 的 `task_type / novel_id / action / result / context provenance`，并重建
provenance 后写 `source=ai_generated` revision；请求不接受 provenance，无法伪造
manual 来源或引用跨项目 task。

生成上下文是预写阶段的独立策略：

- 必带项目标题、题材、基调、目标规模和当前阶段；
- 使用已采用的 World Bible synopsis / page 与核心规则；人物和普通世界对象有显式选择时
  只使用选择项，没有显式选择时分别按稳定 importance 顺序自动取 Top-K；各自动来源超过
  上限时记录省略项，显式选择永远优先；
- 不加载章节正文、Scene、RAG、OutlineArc、PlotThread、伏笔和揭示计划；
- task meta 记录实际纳入/省略 ID、Top-K reason、source refs、投影 hash 和整体
  context hash。worker 先把首次重建的 hash 与提交时 hash 比较，排队期间来源漂移则要求
  重新提交；provider 前 checkpoint，provider 后再次重建 hash，等待期间漂移时丢弃 preview。

结构化导航字段是 `outline_markdown` 的辅助浏览投影，不是关系键。服务只校验 exact shape、
文本/数组类型、长度和禁用持久化字段，不要求名称全局唯一，也不要求
`advanced_storylines` 与 `major_storylines.name` 做字符串精确相等；这些语义差异留给作者在
完整预览中编辑，不因命名措辞整批拒绝高质量输出。

LLM 通过 project execution snapshot seam 恢复提交时的 provider / model，使用固定
action `outline.story_outline.generate`、受管 structured step、输入/输出预算和 1800 秒超时。
system 固定来自 `load_prompt("story_outline")`；作者意图和所有资料都是转义后的
user JSON 数据块，不能闭合或覆盖 system 边界。首次候选和审计都从第一次
请求获得 exact `OUTPUT_CONTRACT`。候选会经过窄语义审计：项目上下文是已采用事实的
唯一来源，不允许模型把对同名作品的外部记忆写成正史。一般证据/作者意图
审计、外部正史污染检测和已采用世界规则/人物边界审计是三个分离 step。
正史污染检测只利用模型知识识别候选已写出、
但项目未提供的后续正史，不会把额外正史补入上下文。作者明确禁止借用时，
污染细节放入例子或开放决策也会被拒绝。世界规则审计则只比较项目已明确采用的
硬规则和人物边界；候选选项也不能默认违反它们，除非作者正在明确重设该规则。
同时审计不会因为新的未来
设计没有来源就压制创作，只要它清楚属于本版总纲的方向、条件提案或开放决策。
第一版越界时最多完整修订两次；每轮必须逐项执行审计给出的字段级修正，错误短引用应替换为
输入中的正确引用，无法确认时清空并标记不确定。候选、三类审计和全部语义修订共享一个
1800 秒阶段总时限，不为额外修订重新计时。
精确章号、章数区间和“前 N 章”式阶段日程还会经过确定性守卫，不依赖审计模型自觉。
任务冻结策略为 `restart_origin`。

`POST .../revisions` 是手工保存并采用新版本的明确动作。应用历史 revision 必须提交
`confirmed=true`；服务会复制其内容形成新的不可变 revision，再推进 current，而不是改写
历史或把版本号倒退。两种动作都只写 StoryOutline 聚合，绝不创建或修改 PlotThread、
OutlineArc、Scene、伏笔或揭示计划。

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
伏笔和揭示列表还支持 `related_thread_id` 与 `unassigned`。`unassigned=true`
表示没有任何同项目 active PlotThread 关联；旧资产、从未分配的计划，以及最后一条关联线程
进入历史后的计划都进入该集合。

## P20 当前层 AI 创作

`POST /api/outline/generate` 保留原地址，但 v2 请求必须声明
`target=plot_thread|outline_arc|planned_scene`、`mode=create|revise`、作者指令与当前层
显式选择。入口分别位于剧情线、篇章纲和 Scene 工作台，不在生成中心。三个入口都要求当前
StoryOutline；总纲或所选资产漂移会令 preview 失效并在 apply 返回 409。

模型只生成当前层 strict preview：剧情线可内嵌统一的信息推进 movement；篇章纲只能引用
已有剧情线；Planned Scene 不从正文提取 Scene。新建 Planned Scene 的
`scene_chunks/chapter_ids` 为空，`structure_meta.planning_state=planned` 并保存计划章节范围和
父篇章纲。建立真实正文映射后转为 `materialized`；修订已有正文 Scene 保留原 chunks、章节
关联和 span。

P20 的 context 使用完整当前总纲、作者确认的实际 context、相关结构/信息推进、人物 Top-6
和非人物对象 Top-16。人物会通过稳定 world facade 分页读完同项目候选后再排序，避免只在首个
50 条页面中取 Top-K；显式选择优先，其后综合作者指令/当前总纲名称命中、Scene 卡出现、既有
结构关联和 author-safe 档案相关性。Top-K 是资产范围而不是 token 预算；confirmation 必须显式使用
`budget_tokens=0`，provider 超限时失败，不做应用层裁剪。system 只承载目标、层级权限和
完整 JSON Schema 输出契约；所有动态资料作为转义后的不可信 user JSON。provider 调用前
checkpoint，等待时不持有数据库事务。

context 还显式记录 active Scene 的已物化章节范围；该范围内的剧情节点必须来自已确认正文或
Scene/RAG 证据，不能把未发生的后续正史插回已写章节。每版候选随后并行通过项目证据/外部正史、
层级权限/世界规则和作者指令忠实性三类审计；失败时允许最多两次完整语义修订并复审。候选、审计和修订共享
P20 的 1800 秒总预算，不把每个子步骤扩成独立的 30 分钟。初审与复审使用独立受管步骤名；
复审仍失败时，任务向作者返回经过长度限制、带证据/层级类别的违规说明，便于调整资料或指令。

`POST /api/outline/generate/apply` 仍要求 `confirmed=true + source_task_id +
draft_structure`。服务按源 task target 重验 strict schema、短引用、当前 StoryOutline、所选
资产与 context fingerprint，并在单一 savepoint 中全有或全无应用。新建写
`source=ai_generated`；修订保留 ID/source，把字段前值、task、总纲 revision、context hash
和采用时间追加到 `ai_revision_history`。已完成 v1 preview 仍由旧兼容 apply 读取；未完成
v1 task fail closed。`plot_structure_generate` 不再调用创作 Prompt。
生成任务失败或取消时，任务 handler 会先回滚未完成的预览业务写入，再把对应
`context_confirmation` 的结果跟踪收尾为 `failed` 或 `cancelled`。任务已进入终态后，
手动 AI 参考资料确认不得永久停留在 `running`。

PlotThread 是作者侧的信息推进聚合根。P20 将 movement 的 seed/reinforce/payoff 确定性投影
为伏笔计划，将 partial/full reveal 投影为揭示计划，两类记录共享
`information_movement_id`。揭示目标无法解析时，movement 以 `target_ref` uncertain 保留在
PlotThread 并标记复核，不伪造对象引用，也不创建无目标 RevealPlan。模型漏写这一不确定
标记时，内部契约根据“存在揭示节点且目标为空”确定性补上，不为纯记账字段重复调用模型。
信息对象只有现象或问题、尚无可靠答案时，movement 的 `hidden_content` 也可为空并确定性标记
uncertain；若揭示目标或秘密任一未解析，只保留 PlotThread movement，不投影伪 RevealPlan。
带确定章号的 movement 节点必须按时间从早到晚；倒序由确定性语义审计定位到具体 movement，
再进入有界语义修订，不作为 JSON 格式错误重试，也不静默改写节点。partial/full reveal 还必须
真实改变读者或人物对该 target 秘密的知识边界，一般能力展示、压力增加或线索积累只能作为
reinforce。
修订 PlotThread 时，以本次 movement 集合为准同步确定性投影：被移除或改变类型的旧伏笔/
揭示投影进入历史并解除线程关联，重新出现的同一 projection 可恢复为工作稿，避免剧情线已
删去的信息推进仍作为活跃计划残留。
`provenance_meta.information_movement_id` 并关联同一 PlotThread。RevealPlan 的
`related_thread_ids` 与伏笔一致，所有引用在写入前验证同一 `novel_id`。旧计划不猜测归属，
由剧情线页“未归入剧情线”区域人工分配；底层 CRUD、Context、Writing reveal decision 和
深度导入消费接口继续保留。

## Scene 工作台

Scene 工作台是 Scene 管理、章节映射和结构整理的主入口，直接挂载在前端
`outline/scenes` 子标签。旧 `scene/{scene_id}` 路由会兼容重定向到该入口并通过
`scene_id` query 定位 Scene，不再维护第二套 Scene 管理 UI。

`GET /api/outline/scene-workbench` 支持 `view_mode=normal|hot`；省略时仍为
`normal`。普通模式保持健康聚合、管理筛选、`scene_index` 顺序和显式分页。热点模式同样
保持剧情顺序，不为 Scene 虚构 importance；它额外按最新有效正文章返回
`progress` 聚合和每项 `segment=current|upcoming|past|unassigned`。章节范围覆盖截至章为
current，起始章更晚为 upcoming，结束章更早为 past，无可靠映射为 unassigned。
“最新有效正文章”只计算每章最新 working 版本中含实质正文的章节；空值、空串或纯 Unicode
空白占位稿不会推进 progress 或自动锚点。

热点模式可传 `anchor=latest`，服务端把分页窗口定位到覆盖截至章的 Scene；没有精确覆盖时
选择章节距离最近的 Scene。显式 `selected_scene_id`、非零分页、segment 或管理筛选优先于
自动锚点。健康聚合继续回答“需要处理什么”，progress 回答“现在写到哪里”，两套口径并存。

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
POST  /api/outline/scene-workbench/fusion/preview-task
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
深度导入 Scene 的 `structure_meta.core_conflict_status=not_applicable` 表示正文中没有
需要强行概括为冲突的内容；当其他必填设定完整时，空 `core_conflict` 不进入“缺设定”。
缺少该标记或标记为 `uncertain` 时仍进入“缺设定”，手工 Scene 继续沿用原有规则。
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
preview 只展示章节映射、字段、剧情线和伏笔 / 揭示影响，不修改数据，
也不因存在关联资产自动阻断。合并不硬删除来源 Scene，只把来源 Scene 标记为
`deprecated` 并保留可追踪 meta。拆分不修改正文内容，只调整 Scene 映射并创建新 Scene。

AI Scene 审稿响应统一由 `SceneDraftReviewService` 生成。`fusion/preview` 要求传入
`primary_scene_id`，返回统一审稿形状：`draft_scene` / `draft_scenes`、
`field_references`、`field_sources`、`source_scene_summaries`、`conflicts`、
`warnings`、`confidence` 和 `reason`。preview 不修改来源 Scene；章节映射和
`scene_chunks` 由系统确定性合并或拆分，LLM 不拥有这些事实字段。
Scene 融合语义草稿通过 project runtime seam 调用共享的 v2 synthesis 契约；
只有 `exact/reanchored` 且 draft / source hash / range 重新校验成功的
SceneSpan 正文才会进入 prompt，且 span 必须指向该章当前的
working / canonical 源版本。证据按 working 优先、canonical 回退，不做应用层
字符/token 裁剪；同时加载当前范围涉及的活跃结构、人物 Top-6 与非人物世界对象
Top-16。Top-K 只限定相关资产范围，不是输入预算。单次最多融合 20 个 Scene，
不精确映射只使用 Scene 卡。provider 调用前完成 context/DTO 编译并结束数据库事务。
LLM 或结构校验失败时返回明确 warning 的确定性草稿，不暴露
provider 原始错误，也不扩大保存权限。
`fusion/save` 支持 `keep_originals`、`deprecate_originals`、`discard` 和
`edit_then_save`。只有 `deprecate_originals` 会把来源 Scene 标记为
`deprecated`，新 Scene 记录 `source="manual_fusion"` 与
`structure_meta.fused_from_scene_ids`，来源 Scene 记录 `fused_into_scene_id`。确认保存会
记录 `adopted_at` 和 `source`，并保留/重算 `semantic_field_statuses`；未解决的
uncertain 字段继续令 `needs_review=true`。
精确映射按章节、起止 offset 稳定合并 `scene_chunks`；包含/相邻关系按范围而不是只按章节
ID 判断，因此同章首尾相接的 Scene 不会被误报为互相包含。融合语义保存前还会检查来源边界
限定是否已因融合失效，避免 must-happen 与 must-not-happen 自相矛盾。
保存后的 `fusion_strategy="author_reviewed_preview"` 只表示作者已审阅预览，
不把可编辑结果伪装成纯 LLM 或纯确定性产物。

深度导入 Phase 3 使用独立 Scene 证据结构化契约，不复用 P20 创作 Prompt。每条结论必须
引用输入 Scene；无有效 Scene 证据时不调用 provider，返回空结构和复核诊断。低置信或无法
解析目标的结果保留为 review 提案，无法解析的 reveal 不会用 zero UUID 伪造已落库资产。

新 Scene 写入的 `status` 只允许 `draft / canonical`；更新路径另允许 `deprecated` 用于软废弃。兼容期仍可读取存量 `candidate` Scene，但新 create/apply/split/fusion 不再写 candidate。

高质量深度导入 Phase 1c 先成组审阅相邻边界，再对满足自动门槛的连通组单独综合。建议持久化在
`scene_fusion_suggestions`，使用 `pending/adopted/dismissed/stale`
生命周期；刷新后仍可继续处理。前端打开建议后进入同一个
Scene 草稿审稿界面，由用户选择主 Scene 并确认编辑后再复用
`fusion/save` 保存；不提供批量自动采用。高置信且来源精确的 `separate` 以隐藏的
`dismissed` 决策保存，不进入待处理列表；其他 `keep_separate` 建议可在
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

应用建议必须由用户确认。Scene 默认创建待处理的 AI 融合建议，不立即修改或废弃
来源；作者随后在 Scene 工作台使用共享 synthesis 契约生成、编辑并保存。机械融合仍是
显式动作，只合并映射并按目标优先级选字段，字段冲突与无法判断的空字段写入复核元数据。
其他结构资产不会
硬删除，只标记为 `deprecated`，并在 `provenance_meta` 写入
`merged_into_asset_id`、`dedup_source="smart_dedup"` 和 `needs_review=true`。
项目级工作台调用 `apply_structure_dedup_group()` 严格入口：整组先校验资产类型、
状态和 execution fingerprint，任一操作失败直接向上抛出以便 project savepoint
回滚；组内存在 `keep_separate` 时，会在其他写入完成后按最终资产状态重新生成
semantic fingerprints。只有显式机械融合要求先调用 Scene merge preview 并确认；
AI 融合建议本身不改写 Scene。两条路径都委托 `SceneWorkbenchService`。

Analyze、P20、PlotStructureGenerator 和结构去重均通过
project runtime seam 获取 client；batch/pair 外层复用同一 client，结果仍只进入
preview/needs_review，不扩大自动 apply 权限。
异步 `plot_structure_generate`、`outline_analyze` 和 `outline_generate`
使用仅 TaskWorker 可调用的 prepare / execute /
finalize seam：提交时冻结无 secret 的 project LLM execution snapshot（旧任务首次执行时
补建并先做 lease-fenced checkpoint），prepare 阶段在 project `FOR SHARE` 保护下把确认
上下文和生成器输入复制为 plain DTO 并记录 source fingerprint，同时恢复冻结 profile
与对应阶段配置；随后显式 fenced commit 并清空 prepare 阶段的 ORM identity
map，LLM 等待期间 session 必须没有数据库事务。finalize 重新取得
project 短暂排他锁、复核 fresh confirmation，并重建必要上下文/生成器 fingerprint；并发修改
导致漂移时丢弃旧结果，不绑定 preview/result ref。取消或 provider 错误同样不会留下部分
结果。普通 API/service 入口不拥有该 commit 权限，也不会隐式提交调用方事务。
P20 在候选生成、每轮三路语义审计和最多两次语义修订后更新任务进度；这些阶段仍共享
同一 1800 秒总预算，进度更新不创建领域提交，也不重置超时。
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
P20 v2 task 还冻结实际确认内容和 reference map；worker 重新准备后的 fingerprint 必须与
提交值一致。未完成 v1 task 不会使用新 Prompt 消费旧快照。深度导入 Phase 3 传入任务提交时冻结的 project settings snapshot，
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

异步 AI 任务入口只解析 task meta、更新进度并委托 `OutlineAIWorkflowService`。P20 在
provider 返回后先重新编译并校验确认上下文，再取得短时项目独占锁；锁内只复核确认记录和
确定性资产指纹，不再触发使用独立事务写入的 RAG trace，避免 trace 外键等待当前事务持有的
project 行锁。

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
