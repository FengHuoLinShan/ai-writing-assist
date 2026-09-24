# Story Scene vertical slice

`validate_machine_event_snapshot` 经 facade 复用全景 schema 校验机器事件，保留合法
部分更新和删除；地点尚未解析时 `location_id` 可空，原文字位置继续供全景、Evidence
和地图读取。类型检查不代替来源的语义证明。

Story 的异步 AI handler 在 worker 领取时冻结 root capability 与 L0 请求额度，auto-requeue 和
manual resume 累计同一 run；各 step/attempt 保留既有 timeout，串行长链补保守总墙钟护栏
（reaction 3600s、one_click 7200s，只切病态挂起）。信封只作为任务私有审计元数据，不改变
Scene、CAS 或采用回执。
选择本机 Agent 的场景排演只把人物意图 Agent 交给本机 CLI；环境裁决与剧本步骤沿用项目
账户连接。此类任务逐次确认且 `never_retry`，中断后不能自动重跑本机副作用。

Story owns the author-editable, Scene-scoped projections used by the writing
workbench. Canonical characters remain owned by `world`; outline structure and
Scenes are Story's `outline_state` subdomain. Story validates those IDs
through its stable facade and never writes World, Memory, or Writing records.

## Stable seams

- `contracts.py`: read contracts for character-card and script-file responses.
- `facade.py`: card CRUD/restore/archive, script save/adopt/archive/unadopt,
  Scene context and the adopted-only `get_scene_story_assets` read seam, plus
  the read-only plot-thread reverse lookup `list_plot_threads_referencing_entities`
  consumed by the World impact preview (ADR-0022).
- `schemas.py`: strict Pydantic request, preview and response payloads.
- `tasks.py`: four deterministic async handlers registered through the shared
  task registry: `story_character_card_generate`, `story_reaction_propose`,
  `story_scene_script_generate`, and `story_one_click`.
- `api.py`: author routes under `/api/story`; Scene-centric aliases are under
  `/api/story/scenes/{scene_id}`.

## Persistence

The original Scene asset migration creates four Story tables; ADR-0027 adds the two rehearsal tables below:

1. `story_character_cards` — one `(novel_id, scene_id, character_id)` head.
2. `story_character_card_revisions` — immutable card payloads and provenance.
3. `story_scene_script_files` — named multi-file current and adopted heads.
4. `story_scene_script_revisions` — immutable editable script revisions.

Story also physically owns the former Outline and Memory persistence subdomains
without changing their table names or public APIs. The complete owner inventory
is: `story_outline_heads`, `story_outline_revisions`, `plot_threads`,
`outline_arcs`, `scenes`, `scene_spans`, `scene_fusion_suggestions`,
`scene_summary_checkpoints`, `scene_chapter_links`, `foreshadowing_plans`,
`reveal_plans`, `memory_events`, `memory_snapshots`, `memory_scene_checkpoints`,
`memory_scene_snapshots`, and `delta_log`. Active callers and owner tests use
`modules.story.outline_state`, `modules.story.continuity`, and the stable
`modules.story.facade`. The old `modules.outline` and `modules.memory` import
aliases were removed after the canonical-preparation SHA completed production release.

Continuity checkpoints are versioned: V1 confirmations replay the original four dimensions;
V2 adds timeline and causality without backfilling missing history as empty facts. Writing may
append one author-confirmed continuity event through the stable facade after revalidating the
draft, check item, source checkpoint and Evidence confirmation. The append is Scene-locked and
idempotent and invalidates only the affected downstream dimension.

The existing public prefixes remain `/api/outline` and
`/api/novels/{novel_id}/memories`, alongside `/api/story`.

Every repository query is novel-scoped. Heads and revisions also have
composite `(id, novel_id)` constraints so a cross-project pointer cannot be
stored. Script `current_revision_id` is the latest save; `adopted_revision_id`
is the only revision exposed to the Writing execution bundle.

## AI and authorization

Independent card, reaction, script, and one-click tasks require a fresh Context
confirmation and return preview-only results. Workers rematerialize the reviewed
Context and fail before provider I/O when its fingerprint changed. One-click may persist only missing/stale card revisions
when `submit_authorized` is explicit; it never persists reactions, scripts,
World, Memory, or Writing changes. One-click card freshness is based on a
source hash of the outline projection, stable compiled-context sections/text,
and character ID, excluding the card itself.

Scene asset reads batch-load card and script revisions with two bounded `IN`
queries. The common Story baseline is hashed once, then per-script exclusion
hashes are derived in memory; basis hashes and stale decisions remain identical.

Manual apply payloads carrying `source_task_id` or `context_snapshot_id` are
accepted only when the completed task is same-novel and has the expected Story
task type/action; snapshot IDs must match the completed result. Provider calls
use the project snapshot LLM seam and happen outside a database transaction.

StoryOutline generation uses the same preflight contract. Its public wire carries
`context_confirmation_id`; submission and worker execution rematerialize the confirmation and
include the confirmed Markdown in the bounded StoryOutline input. Automatic World/character
overlays are filtered by the confirmation's actual selected assets, so they cannot reintroduce an
item the author excluded. This adds no Story table or migration.

Scene fusion additionally requires the submitted Scene set to equal the confirmation's pinned
Scene refs. Its provider payload uses the rematerialized confirmed Markdown; the legacy related
World/outline overlay is not loaded on a confirmed author task.

## Product boundary

This slice serves the long-form author persona: it shortens “return to a Scene
and continue writing” while keeping previews editable, sourced, versioned and
reversible. It is not an RP-user entry point and does not expose raw task or
database concepts as a product requirement. Adoption/undo/conflict behavior
must remain visible to the author in the workbench.

## Project assistant integration (ADR-0023)

Story-owned operations prepare concrete previews for versioned outlines, appended Scene plans,
Scene edits, character cards and script revisions. Confirmation invokes the existing CAS/version
services; scripts enter Writing only through their adopted head. Assistant provenance remains
with the saved revision. Ordinary Scene edits cannot disguise reordering, archival or source remapping.

Structure and card/script changes mark pending review in the same transaction. The
`story_reference_review` task reads existing adopted-script basis/staleness projections over
bounded, directly associated Scenes. It is a reference check, not a semantic or character-quality review.

Assistant 的 story.plan_structure 复用 P20 的整层来源快照、outline_generate 任务和提案结构，
story.adopt_structure 复用原采用包及 revision history、场景正文映射和信息推进投影。API 与助手
共享 OutlineAIWorkflowService.submit_layer_generation；新工具不进入旧冻结运行的目录。
P20 三种预览在原结果卡共用同一内联追踪入口，组合展示当时 Confirmation、
确切 task operation、知识复核、结果引用与来源失效。预览保持待处理；采用成功后把
Confirmation 标为 `adopted`，并对新建或修改的 PlotThread、OutlineArc 和 Scene 调用
Evidence 精确失效：排除本次 Confirmation，但使仍引用旧状态的其他记录失效，
同时复用该入口中的 `source.changed` 通知，不另发一路重复通知。规则引用检查不等同语义强提醒。


### 助手维护与变化检查

结构成果返回具体 revision_id，P20 采用回执返回类型化 result_refs。原任务可打开专业审阅页；
信息推进结果定位到具体计划，助手可修改内容、章节与关联剧情线，目标对象变更沿用结构工作台。

新剧本以 basis_manifest.version=2 记录明确关联的剧情线、篇章和信息计划指纹。已知起点、
无结束章的活跃剧情线按原领域开放区间语义参与；未定位范围不推测。旧 v1 仍按原算法读取，
稳定 facade 的默认计算版本保留 v1。变更通知携带原关联场景，与最新范围合并后有界检查，
不得因范围迁移或投影退役丢掉先前受影响的场景。版本提醒不替代语义审稿。

### 作者结构整理

前端可选择现有剧情线、篇章加入可编辑总览草稿，并在手工版本 provenance.source_refs 保留来源版本标识；不双向覆盖来源或人工总览。篇章支持就地编辑，线索支持分组归类。生成线程分类统一为 main/sub/background；旧生成词项 subplot/secondary/relationship 映射 sub，mystery/hidden/world 映射 background，未知词项由 schema 拒绝而非静默变为主线。现有手工未知类型在前端编辑时保留。简单结构参数契约升级为 phase3_structure_simple_v3。

剧情线名称/分类与篇章名称/范围可就地编辑；未保存行按账户与作品保存在当前浏览器，保存失败保留输入，备份失败或保存进行中阻止离开。未知旧分类在只改名称时原样保留。

## World dependency review

`list_world_dependencies` / `read_world_dependency` expose versioned, read-only references from plot threads, arcs, Scenes and the current story-outline revision. They separate declared object references from literal outline mentions and return source hashes. World owns review receipts; resolving a finding still uses Story's own editor and version rules. The seam does not write World, Writing or continuity state, and planning records have no reader/Scene-local visibility projection.

### 审阅与导航体验约定

场景相关用户标签统一使用“场景”；剧本区修改或切换文件后将临时检查标为过期，检查不被解释为新稿结论。篇章行编辑只备份实际修改，提供取消及Escape退出。

## 导入场景的定向核对

Story 提供 `preview_import_scene_resolution`、`apply_import_scene_resolution` 和对应撤销 seam。Imports 冻结原场景指纹、从 Evidence 读取来源、执行边界提案与终检；Story 在提交时重验正文和全章覆盖。当前仅自动处理原定位不变、未编辑的导入草稿；改变引用范围的提案保持待决定。字段必须有独立证据，不因边界正确而自动通过写作约束，自动核对不伪造人工 reviewed_at。

## 知识回执

P20、人物卡/反应/剧本预览、总纲与 Scene fusion 在输出后复核。总纲/P20 采用经 Evidence 公共门禁要求 `knowledge_review.status=passed`；旧任务或 blocked 回执必须重新生成。
总纲请求覆盖高潮选择与结局时，预览须给出具体主方案、结果与代价；只有作者明确保留开放、
已有决定冲突或超出授权才留待定。候选提案不等于采用，不能借 `open_decisions` 省略要求的交付。
既有意图/证据审查同时核对支撑主方案的数量、金额和时间，内部矛盾也进入原有一次语义返修。

人物卡/反应/剧本的复核读取生成时实际发送的完整请求，包括同一场景、目标人物、作者补充与
已裁剪的参考；不在审查层再次截断为 24K 字符。返修包含原预览及问题清单，最多一次。

## 有限排演（ADR-0027）

`simulation_protocol=rehearsal_v1` 仍使用原 one-click task 与 confirmation，最多三人、每次一至三轮。
人物分别读取自己的 Evidence 包和上一轮观察；环境只裁决动作结果，服务器投影公开/私下/耳语事件。
`story_simulation_runs`、`story_simulation_steps` 保存来源、完成回合与分叉，回放不重新生成。
回合不可变；分叉校验原回合 hash 与当前来源，不修改父排演。叙述只消费已裁决事件，仍是待审预览。
旧 one-click 默认不消费本轮候选；新客户端显式使用 `simulation_candidates`，不冒充 `accepted_reactions`。
启用见 development-guide；工程验证与模型自然性验收分别记录。

## 创作试验的结构与观察边界

Story 为 Collaboration 提供 Scene、伏笔/揭示安排的冻结可编辑字段与原领域操作 port。
试改独立保存，采用仍验证当前结构版本。`observations.py` 区分输入刺激、私有意图、
可观察事件和可重放的 ResolutionBatch；说法不是事实，未知资源或唯一资源冲突不宣告成功。
`observation_v2` 不重新解释旧 rehearsal_v1。读者推测与作者安排分开，派生前瞻不是新信息计划。

### DS Flash 档位调优（2026-09-21）

深度导入Phase3的high_quality=True在Flash上统一max，生成与独立证据复核输出上限至少65,536；普通档仍为high及冻结阶段预算，引用和采用门禁不变。

### 演化引擎 seam（V4，2026-09-21）

continuity 归约统一为单一 `reducer.py::StoryStateReducer`（章节重放与 Scene
投影共用内核；manual_correction 与未知实体更新入 changes 观察层）。facade
新增两个只读/失效缝供 evolution 消费：`supersede_scene_projections_from`
（E05 失效传播：软 supersede，不删历史）与 `project_scene_presence`
（G2 在场投影：未知路线标 unknown，不造移动细节）。Scene 事件替换按
producer family 分区 + 稳定 `meta.event_key`（作者确认永不参与机器替换）。

## 演化来源失效与地图消费

continuity 保留原事件历史，通过 `source_stale` 排除已失效机器事件；作者确认事件保持独立权威。
Scene 生命周期/来源范围/重排在同事务使受影响派生流失效，重排先封锁演化 run，再对齐事件，避免反锁。
`facade.project_scene_presence` 只读取当前 draft/canonical Scene，在场附带事件/章节/观察出处；
World 地图是其只读消费者，不持有另一份人物位置事实。无 Scene 身份或失效事件不进入投影。

### 自动场景的边界确认

场景工作台的 `review_boundary` 只确认 Evolution 的 `boundary_only` 草稿范围，绑定当前
Scene 顺序、章节和区间指纹，保留 draft 与尚未整理的语义字段。请求须携带工作台返回的
`boundary_fingerprint`，在行锁内对照；旧页面确认拒绝，`boundary_review_current=false`
时保留纯边界确认入口。作者在工作台点击
“确认边界，继续整理”后可回到正文理解恢复原运行；该操作不标记语义已审核、不提升为
canonical。重新标记待检查撤销该边界确认；区间/顺序变化使指纹失效，正文来源仍由正常
来源门禁重验。正式 `review` 的完整采用语义保持原契约。
