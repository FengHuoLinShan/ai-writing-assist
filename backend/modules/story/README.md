# Story Scene vertical slice

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

The migration creates exactly four Story tables:

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
P20采用在同一事务向 source.changed 发出真实成果引用；规则引用检查不等同语义强提醒。


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

## 导入场景的定向核对

Story 提供 `preview_import_scene_resolution`、`apply_import_scene_resolution` 和对应撤销 seam。Imports 冻结原场景指纹、从 Evidence 读取来源、执行边界提案与终检；Story 在提交时重验正文和全章覆盖。当前仅自动处理原定位不变、未编辑的导入草稿；改变引用范围的提案保持待决定。字段必须有独立证据，不因边界正确而自动通过写作约束，自动核对不伪造人工 reviewed_at。
