# Story Scene vertical slice

Story owns the author-editable, Scene-scoped projections used by the writing
workbench. Canonical characters remain owned by `world`; outline structure and
Scenes are Story's `outline_state` subdomain. Story validates those IDs
through its stable facade and never writes World, Memory, or Writing records.

## Stable seams

- `contracts.py`: read contracts for character-card and script-file responses.
- `facade.py`: card CRUD/restore/archive, script save/adopt/archive/unadopt,
  Scene context and the adopted-only `get_scene_story_assets` read seam.
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
`modules.story.facade`. The old `modules.outline` and `modules.memory` packages
remain import/API/model aliases only until the canonical-preparation SHA has been
released once; they contain no second service, repository, task, or ORM implementation.

The existing public prefixes remain `/api/outline` and
`/api/novels/{novel_id}/memories`, alongside `/api/story`.

Every repository query is novel-scoped. Heads and revisions also have
composite `(id, novel_id)` constraints so a cross-project pointer cannot be
stored. Script `current_revision_id` is the latest save; `adopted_revision_id`
is the only revision exposed to the Writing execution bundle.

## AI and authorization

Independent card, reaction, and script tasks require a fresh Context
confirmation and return preview-only results. One-click compiles Context and
creates its snapshot itself. It may persist only missing/stale card revisions
when `submit_authorized` is explicit; it never persists reactions, scripts,
World, Memory, or Writing changes. One-click card freshness is based on a
source hash of the outline projection, stable compiled-context sections/text,
and character ID, excluding the card itself.

Manual apply payloads carrying `source_task_id` or `context_snapshot_id` are
accepted only when the completed task is same-novel and has the expected Story
task type/action; snapshot IDs must match the completed result. Provider calls
use the project snapshot LLM seam and happen outside a database transaction.

## Product boundary

This slice serves the long-form author persona: it shortens “return to a Scene
and continue writing” while keeping previews editable, sourced, versioned and
reversible. It is not an RP-user entry point and does not expose raw task or
database concepts as a product requirement. Adoption/undo/conflict behavior
must remain visible to the author in the workbench.
