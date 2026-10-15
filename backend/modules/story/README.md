# Story Scene vertical slice

`validate_machine_event_snapshot` 经 facade 复用全景 schema 校验机器事件，保留合法
部分更新和删除；地点尚未解析时 `location_id` 可空，原文字位置继续供全景、Evidence
和地图读取。类型检查不代替来源的语义证明。

ADR-0039 的对象时点字段登记在 `continuity.field_provenance.STATE_FIELD_REGISTRY`
中，按对象类型和 Scene-memory 维度匹配；字段来源仍沿用 `FieldProvenance` 的
exact / unverified / conflict 判定。关系事件可携带 Story facade 导出的
`RelationAttitude`，其来源对象、目标对象与分级态度共同构成有向关系态度。自由字段
继续透传，但不会获得字段来源链或进入确定性字段检查。

Story 的异步 AI handler 在 worker 领取时冻结 root capability 与 L0 请求额度，auto-requeue 和
manual resume 累计同一 run；各 step/attempt 保留既有 timeout，串行长链补保守总墙钟护栏
（reaction 3600s、one_click 7200s，只切病态挂起）。信封只作为任务私有审计元数据，不改变
Scene、CAS 或采用回执。
场景排演的全部步骤使用项目账户连接；按 [ADR-0029](../../../docs/adr/0029-local-cli-image-only.md)
本机 CLI 不再承接人物意图 Agent。Story 执行入口在读取 Context 或调用模型前拒绝旧本机任务标记及
`agent_llm_execution_snapshot` 副快照；即使同时保存了合法账户主快照，也不改用账户模型恢复旧排演。

Story owns the author-editable, Scene-scoped projections used by the writing
workbench. Canonical characters remain owned by `world`; outline structure and
Scenes are Story's `outline_state` subdomain. Story validates those IDs
through its stable facade and never writes World, Memory, or Writing records.

跨章 Scene 的工作稿来源锚点按章节生成，可能只有部分 `part_no`。边界验证按部分身份
优先使用工作稿锚点，仅从原 canonical 映射补充尚未生成的部分；已有工作稿映射的漂移、
缺失来源范围或原稿版本不符仍拒绝，不写入补出的映射或改变已确认范围。
`validate_scene_source_ranges(..., content_mode=...)` 可显式限定 canonical 或 working 映射，
用于验证消费者实际读取的模式；省略此参数时继续保留上述按部分覆盖的行为。

## Stable seams

- `contracts.py`: read contracts for character-card and script-file responses, plus the
  plot-thread stage helpers (`TERMINAL_THREAD_STAGES`, `thread_stage_is_terminal`,
  `thread_overdue_notice`) shared by context selection and overdue rendering.
- `continuity/basis.py`: checkpoint 来源基线（M4）——系统行构建时登记的
  working 稿指纹切片 + 重放窗口场景结构 + 契约版本，供 `get_scene_state_view`
  读时确定性比对；系统行漂移即 degraded 待核对。改稿命中手工/已确认行时保留原内容，
  将状态标为 `needs_revalidation`，不自动覆盖作者决定。
- `facade.py`: card CRUD/restore/archive, script save/adopt/archive/unadopt,
  Scene context and the adopted-only `get_scene_story_assets` read seam, plus
  the read-only plot-thread reverse lookup `list_plot_threads_referencing_entities`
  consumed by the World impact preview (ADR-0022). Continuity exposes
  `get_scene_state_view` — the viewpoint-layered (author/character/reader)
  read-only Scene state projection (M2 scene-state-view-v1); it reads only
  `is_current` checkpoints, never backfills from today's World, and is also
  exported through the `STORY_SCENE_SOURCE` port for cross-module consumers
  (see `continuity/scene_state_view.py` and the M2 contract in docs/plans). Complete source-consumption
  registrations let Evolution supersede only affected Scene dimensions; incomplete coverage still
  falls back to the conservative suffix.
- `read_object_dossier_state` 经 `evidence.read_story_object_state` 只读 DI 键提供同一 Scene 的
  POV 状态；仅作者请求会附带 checkpoint set，角色视角不会从此口读取作者 checkpoint。
- `schemas.py`: strict Pydantic request, preview and response payloads.
- `tasks.py`: four deterministic async handlers registered through the shared
  task registry: `story_character_card_generate`, `story_reaction_propose`,
  `story_scene_script_generate`, and `story_one_click`.
- `api.py`: author routes under `/api/story`; Scene-centric aliases are under
  `/api/story/scenes/{scene_id}`.

## Writing scene-structure notices

`notice_sources.py` exports the read-only `story.structure` spec for the unified author-notice registry.
It derives goal, core conflict, emotional beat, POV, review/organize flags, and chapter linkage from the
authorized Scene workbench. Trusted imported/fused semantics preserve `semantic_field_statuses`:
`not_applicable` is not reported missing, while `uncertain` is reported as awaiting review. Chapter
linkage follows the existing many-to-many Scene mapping. The provider writes nothing; the writing client
does not calculate structural gaps from Scene fields.

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

## Unified structural notices (ADR-0040 §13)

`notice_sources.py` exports a pure `NOTICE_SOURCE_SPEC` for Assistant's composition-root registry;
Story returns raw source-owned dictionaries and imports no Assistant contract. Its reader uses
`SceneWorkbenchService.get_workbench()` health/details, preserves the trusted semantic-field status
rules (`deep_import`, `manual_fusion`, and the approved semantic origins), does not report
`not_applicable`, reports `uncertain` as pending confirmation, and includes missing POV, review,
organization, and chapter-mapping issues. Chapter lookup preserves the Scene–chapter many-to-many
mapping and uses the unbounded workbench mode to avoid silent truncation. Scope ownership is checked
at the Assistant API boundary before this provider runs. This provider only projects existing
structure and health; it does not create a second Story issue record.

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

### 滚动规划窗口（BR-6）

`story.plan_structure` 的滚动推进携带起止章窗口：篇章/剧情线窗口默认 3 章、上限 5 章，
计划 Scene 层只覆盖紧邻 1-2 章。窗口进入 `outline.generate` 确认参数
（`chapter_index` + `planning_window_end`，后者仅随确认记录，不参与检索或编译裁剪）
与 P20 来源指纹；带窗口的请求以 `rolling_window=true` 提交。

生成后执行确定性硬校验：新条目的章节定位必须落在窗口内、不得覆盖已写章节
（Writing 有效章节，经 `writing.facade.list_effective_chapter_indices` 读取），并有条数上限
（篇章/剧情线 3 条、Scene 每章 2 条）；违规条目丢弃并在结果 `window_validation` 中说明，
不是整任务失败。修订按原资产冻结范围判断：跨窗或未完整定位的原对象只输出只读建议，模型缩小范围
不得绕过；采用时再按最新原对象与已写章节重验。窗内篇章保留标题、序号与覆盖范围。
新增重叠篇章只作提示，不重复写入。

窗口回执由完整参数、来源预览（含确认）与流程操作身份经 uuid5 派生；同一意图重试
返回原任务，新指令、资料或新运行产生新身份。采用支持非空保序子集，预检排除依赖；
准备采用后，以任务版本、原确认、来源、选择/排除及编辑内容指纹绑定，采用锁内重验，
选择变化不得使用旧指纹。回执保留选择、排除与采用指纹。未采用的规划只存在于任务回执，不进入写作上下文与检索；回归见
`modules/story/tests/test_unadopted_planning_context.py`。手动结构工作台不使用窗口，
照常可用全书范围；`_require_scope` 未放宽。

流程侧补窗检查（BR-6）经 outline_state facade 的只读缝
`get_planned_chapter_coverage(db, novel_id, start_chapter=, end_chapter=)`
统计窗口内已被已采用规划覆盖的章（非 deprecated 篇章、`planning_state="planned"`
且带计划章节范围的计划 Scene、起始章在窗口内的剧情线），供引导流程在采用后
判断"前方已规划章数、不足 2 章提议补足"；只读，不写回、不重复判断领域门禁。


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

Story 新建的排演使用 `simulation_v3`。通用 `/tasks/one-click` 默认仍是 `legacy`，
以保留现有操作目录的请求与幂等键；新排演需显式走 Scene rehearsal 入口和 v3。
该入口拒绝新建旧协议，旧排演只读。当前一次提交一回合；连续推进待共享根预算与再次授权接线。
协议在 Story 共用 `SimulationReference`、
`SimulationIntent`、有限结算、`StateDelta`、`ResolutionBatch` 与 `replay_batch`；
现有对象和地图节点用各自 ID，候选和文字标签保持独立命名空间。协议模型不限制参与者、
位置、目的地、受众或回合数量。每轮仍是待审候选；意图不等于成功。
公开入口和 worker 在模型调用前按当前作品重验现有对象与已采用地图节点，候选/文字标签
只进入独立命名空间；模型轮次后的再验阻止来源变化落为新回合。公开事件只有发言者本人
及已知同地的观察者可见；位置未知不推定同地。未声明的现有对象不能被结算为资源接收者。

`story_simulation_runs` / `story_simulation_steps` 保存协议、来源、完成回合与分支；回放只重放已存差量，
不重新调用模型。Story 不再新建或续跑 `rehearsal_v1` / `observation_v2`，旧记录按原协议只读，
不跨协议重解释或分叉。Interaction 的 `team_v1` 与 `observation_v2` 入口继续使用原适配，
其 `max_actors` 继续由 Interaction 入口策略控制。v1–v7 冻结目录后续如接新排演，必须显式版本化协议和路由，
不能按新默认重解释旧运行。启用见 development-guide；工程验证与模型自然性验收分别记录。

## 创作试验的结构与观察边界

Story 为 Collaboration 提供 Scene、伏笔/揭示安排的冻结可编辑字段与原领域操作 port。
试改独立保存，采用仍验证当前结构版本。`observations.py` 保留 RP `observation_v2` 的输入刺激、私有意图和可观察事件语义；
`simulation_v3.py` 承载共享意图、有限结算、差量和回放算法。说法不是事实，未知资源、路线或唯一资源冲突
不宣告成功。旧 `rehearsal_v1` / `observation_v2` 记录按原协议只读，不迁移。

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

Scene 消费登记一次批量读取缺少字段来源锚的章节。投影缓存命中保留已有同项目、Scene、维度、
方法版本及前序 checkpoint 的完整登记；旧行缺登记或锚不完整时补齐，不重登记已有效消费以刷新旧稿身份。

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

## 作者表格迁移窄 seam（ADR-0030）

`outline_state/author_migration.py` 提供 `plan/apply/rollback_author_migration_structures`
（经 outline facade 再导出）：arc/thread/foreshadowing/chapter_plan 四类条目与总纲的
只读预览、指纹比对后的采用与按回执逆序回滚。planned Scene 形状与 P20 一致
（structure_meta.planning_state="planned" + planned_chapter_range）；已写章节按
written_chapter_policy 取 reference_only 或 link_scene；总纲经 create_revision 写入，
creative_core 缺失为 conflict（合成条目键 `__outline__`），回滚时 head 仍是本次修订
则回基线或用 clear_head_if_revision 清指针。资产带 spreadsheet_migration 来源与
provenance；deep import 的 Scene 替换不会清理该来源的 Scene（scene_replacement 的
_cleanable 边界）。

## 只读条件比较与历史来源

`facade.compare_scene_state_trial` 通过 `simulation_v3` 的 state-trial mode 与共享 `ResolutionBatch/replay_batch`
在内存比较保管转交和三条件锁。HTTP 接口、三值裁决、来源归因、owner 与零事件写入保持；
`resolution.protocol` 与比较 digest 随意图/batch schema 迁至 `simulation_v3`，方法指纹从
`scene-key-lock-v1` 升为 `scene-key-lock-v2:simulation_v3`（
`e324598864c4b73c79a6abd5794a3f7ac183d0480f6ecf05fd5a3ad9ecdc764e` →
`c12dae97d3cfd40e8095e9fbafa1592ece96acb412f595f0c6a470ac73cea5b3`），旧 digest 不可复用。原状态/有限假设逐条件返回
当前值、所需值、来源及未知；不把自然语言或缺证据行动视作成功，不授予口令知识、不改 owner，不写事件或正文。
Grant 必须携比较 digest，执行与采用重验；接口和范围见 [M5 契约](../../../docs/plans/2026-10-07-m5-trial-change-comparison-contract.md)。

历史来源经同项目 `scene-checkpoints/{id}` 与 `events/by-id` 显式回读，不能替代 current 投影。POV 知识来自本场 Story character 视图；受限事实需 knowledge 值匹配，不能用当前 World 状态、误信或关系提及补齐。

Continuity events freeze manuscript references at ingestion. Rebuilt field provenance
revalidates those references; legacy or stale references remain unverified. Reader
visibility checks each field's historical value against its source range, and checkpoint
consumption includes the inherited manuscript prefix. See [Memory contract](../../../docs/modules/05_memory.md).

### Scene 工作台实现职责

`outline_state/scene_workbench.py` 保留 SceneWorkbenchService 与基础编辑、映射、
人工复核、合并/拆分。`scene_workbench_health.py` 提供健康诊断/区间重叠投影，
`scene_workbench_fusion.py` 负责融合预览、来源重验和持久建议生命周期；
共用定义在 `scene_workbench_support.py`。同一服务实例、repository和锁维持公开API与来源/CAS合同。

Delta categories are source-bound descriptive strings, stored in `delta_log.category` as Text (20261013_delta_category_text). They are not truncated to32 characters. Downgrade refuses when longer history exists; it does not delete or shorten those records.

Story outline generation records only the revisions of World Bible pages actually
placed in its direct `world_bible_pages` input. Current/history reads compare these
baselines through the World DI reader and return `canon_staleness` without changing
content hashes, execution profiles, checkpoints, or publication snapshots. Legacy
records remain silent. Manual revisions inherit the base revision’s page baselines;
restoring a historical revision preserves its original baselines. Extra pages inside Evidence confirmations and other World
consumers remain explicitly outside this first slice; Scene checkpoint unsupported
dependencies are unchanged. See `docs/modules/07_outline.md` for the covered boundary.

### 生效锚点只读端口

`read_temporal_anchor_scenes()` 通过 Story facade 与既有 `story.scene_source` port 导出当前
Scene 顺序、状态、章节引用和 `replaced_by_scene_ids`。查询按 `novel_id` 隔离，保留退役身份
供消费方解析替换链；锚点解析不把历史顺序冻结为世界事实。
