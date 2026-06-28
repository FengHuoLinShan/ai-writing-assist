# AI Import Persistent Context Snapshot

Status: Implemented v1 for deep import Phase 2/Phase 3.

## Source Context

`CONTEXT.md` defines working context as an internal AI pipeline context layer for long-document import, later structure analysis, and cross-phase extraction. Working context may include canonical assets, drafts, candidate creative assets, evidence fragments, confidence, and source dependencies, but it is not canonical context.

The persisted snapshot in this workflow is a context snapshot: the exact context view used by an AI call, with enough metadata for audit, reproduction, and debugging. It does not replace canonical asset tables, does not replace `memory_snapshots`, and does not change candidate-to-canonical confirmation semantics.

## Loop

Each deep-import AI call compiles a working context, invokes an LLM, and writes generated assets. The repeatable loop is:

1. Compile the context view for the next AI operation.
2. Persist the context view or summary before the LLM call.
3. Execute the LLM call with a pointer to that persisted snapshot.
4. Attach generated result references to the same snapshot.
5. Mark downstream results stale or needing review when referenced pending assets change.

## Trigger

Runtime trigger: an AI operation is about to execute inside the import pipeline.

Initial candidate operations:

- Deep import Phase 2 scene entity extraction.
- Deep import Phase 3 structure analysis.

Manual AI operations already go through `context_confirmations`; they are not part of the first implementation slice. They can migrate after the persistent snapshot table is proven in deep import.

## First Implementation Slice

Only deep import Phase 2 and Phase 3 create persistent context snapshots.

Reason: `CONTEXT.md` already defines deep import as an internal automated workflow that uses `working` context without a manual AI reference checkpoint. Manual AI operations already have `context_confirmations`, so including them would mix two review models before the new persistence path is stable.

## Required Behavior

- The import pipeline keeps its automated experience; it must not insert a manual "AI reference materials" checkpoint during deep import.
- Persistent context snapshots are stored in a new `context_snapshots` table.
- `context_snapshots` is separate from `context_confirmations`: confirmations are user-approved reference material records for manual AI operations; snapshots are automated audit records for AI calls.
- The `context` module owns `context_snapshots` creation and mutation.
- The `context` module exposes stable facade functions such as `create_context_snapshot(...)`, `mark_context_snapshot_succeeded(...)`, `mark_context_snapshot_failed(...)`, and `prune_rendered_context(...)`.
- `imports` calls the context facade only; it must not import context models, repositories, or services directly.
- First-version context facade contracts:
  - `create_context_snapshot(db, *, novel_id, task_id=None, workflow_id=None, phase, operation, scene_id=None, scene_index=None, chapter_index=None, context_mode="working", include_pending_objects=True, attempt=1, prompt_name, model, compile_options, included_asset_ids, excluded_asset_ids=None, context_summary, section_metadata, token_metadata, rendered_context=None, retain_rendered_context=False) -> ContextSnapshotContract`
  - `mark_context_snapshot_succeeded(db, *, snapshot_id, result_refs) -> ContextSnapshotContract`
  - `mark_context_snapshot_failed(db, *, snapshot_id, error_kind, error_message) -> ContextSnapshotContract`
  - `prune_rendered_context(db, *, novel_id=None, older_than_days=30, keep_latest_per_project=200) -> int`
- `imports` keeps only `snapshot_id` across the LLM call and uses success/failure facade calls to update the audit record.
- Snapshot granularity is one record per actual LLM call.
- Phase 2 writes one snapshot per Scene extraction LLM call because working context changes as Scene processing accumulates state.
- Phase 3 writes one snapshot for the structure analysis LLM call.
- Phase 2 does not get rewired to the context compiler in the first slice.
- Phase 2 snapshots persist the actual handcrafted extraction context currently sent to the LLM: system prompt, existing entities context, accumulated memory context, scene/chapter source refs, compile/options metadata, and prompt hash.
- Phase 2 `context_summary` includes scene index, source chapters, existing entity count, the latest five accumulated memory entries, scene text character count, and whether pending objects are included.
- Phase 2 `included_asset_ids` shape:
  - `scenes`
  - `chapters`
  - `existing_entities`
  - `pending_entities`
- If current Phase 2 code has only entity name/type terms and not ids, `included_asset_ids.existing_entities` may be empty in the first slice and the terms go into `section_metadata.existing_entity_terms`.
- Phase 2 `section_metadata` records `system_prompt`, `existing_entities_context`, `memory_context`, and `scene_text`; each section includes character count, token estimate, and content hash.
- Phase 2 `token_metadata` records total estimated tokens, estimated tokens per section, LLM max tokens, and temperature.
- Phase 3 `context_summary` comes from `CompiledContext` and records chapter range, `context_mode="working"`, `include_pending_objects=true`, section count, total tokens, evicted sections, truncated sections, and warnings count.
- Phase 3 `included_asset_ids` should use selected asset ids from the compiler/confirmation path when available. If `CompiledContext` does not expose full asset id details, the first slice may store empty arrays by section key and write a `section_metadata.asset_id_visibility` note that the current compiler does not expose ids.
- Do not refactor every context loader only to expose complete asset ids in the first slice.
- Phase 3 `section_metadata` records each compiled section's `key`, `tier`, `token_count`, `truncated`, and content hash; it also stores `evicted` and `truncated` lists.
- Phase 3 `token_metadata` records `total_tokens`, `budget_tokens`, and per-section tokens.
- Phase 3 only stores `render_compiled_context(ctx)` in `rendered_context` when `retain_rendered_context=true`; otherwise it stores hashes and summary only.
- Snapshot records must capture `task_id` or workflow id, phase, `context_mode`, included asset ids, rendered context or summary, prompt hash, and creation time.
- First-version `context_snapshots` fields:
  - `id`
  - `novel_id`
  - `task_id`
  - `workflow_id`
  - `phase`
  - `operation`
  - `scene_id`
  - `scene_index`
  - `chapter_index`
  - `context_mode`
  - `include_pending_objects`
  - `status`
  - `attempt`
  - `prompt_hash`
  - `prompt_name`
  - `model`
  - `compile_options`
  - `included_asset_ids`
  - `excluded_asset_ids`
  - `context_summary`
  - `section_metadata`
  - `token_metadata`
  - `rendered_context`
  - `result_refs`
  - `error_kind`
  - `error_message`
  - `rendered_context_expires_at`
  - `created_at`
  - `updated_at`
- `rendered_context` is nullable.
- `compile_options`, `included_asset_ids`, `excluded_asset_ids`, `section_metadata`, `token_metadata`, and `result_refs` use JSON.
- Minimum indexes:
  - `(novel_id, workflow_id, phase)`
  - `(novel_id, created_at)`
  - `(status)`
  - `(rendered_context_expires_at)`
- Snapshot records default to compact persistence: summary, included asset ids, prompt hash, token metadata, section metadata, and compile options.
- Full `rendered_context` is supported as an optional field, disabled by default and enabled explicitly by the caller for deep debugging or reproducibility.
- Historical data management is part of the feature, not a later cleanup: compact snapshot metadata is the durable audit trail; full rendered context is bounded by retention policy and can be pruned without deleting result provenance.
- Compact metadata is retained long term.
- Optional full `rendered_context` retention defaults to 30 days or the latest 200 full-context snapshots per project, whichever limit is reached first.
- Retention cleanup clears or compresses only `rendered_context`; it must not delete the snapshot row, included asset ids, prompt hash, result references, token metadata, section metadata, or compile options.
- Failed calls create snapshots too.
- Snapshot lifecycle:
  - Create the snapshot before the LLM call with `status="running"`.
  - On success, update to `status="succeeded"` and attach `result_refs`.
  - On failure, update to `status="failed"` with `error_kind`, `error_message`, and attempt metadata.
- The default context mode for deep import snapshots is `working`.
- The snapshot must preserve provenance links from generated results back to the context view used to generate them.
- Provenance is lightweight and bidirectional in the first slice:
  - `context_snapshots.result_refs` records generated or affected object references from the LLM call.
  - Generated objects store `context_snapshot_id` in existing `_meta` or metadata JSON where available.
  - Do not add dedicated `context_snapshot_id` columns to every Phase 2/Phase 3 business table in the first slice.
- Candidate creative assets included in a working snapshot remain pending evidence, not canonical facts.
- Results derived from candidate assets must remain `draft`, `candidate`, or `pending`.
- When included candidate assets are ignored, merged, renamed, or promoted, dependent generated results must be markable as `needs_review` or `stale_context`.
- User-facing copy should say "待确认对象" rather than exposing "candidate asset".

## Non-Goals

- Do not promote candidate assets to canonical automatically.
- Do not replace `memory_snapshots` or `memory_events`.
- Do not generalize `context_confirmations` in the first slice.
- Do not let `imports` own context snapshot persistence internals.
- Do not change Phase 2 extraction context assembly to use the context compiler in the first slice.
- Do not persist full Markdown context by default.
- Do not allow unbounded growth of optional full rendered context.
- Do not add per-table provenance columns across every generated asset table in the first implementation.
- Do not require a manual checkpoint inside deep import.
- Do not build full automatic cascade recomputation in the first version.
- Do not make the context page the required control surface for import review.

## Checkpoint

The human checkpoint is pushed right: after deep import finishes, the user receives a brief that summarizes generated assets, degraded phases, stale or review-needed results, and links into the review surfaces. The user should not review raw prompts or full rendered context during the import run.

The deep-import completion brief shows an import audit summary:

- Phase 2 and Phase 3 snapshot counts.
- Snapshot success and failure counts.
- Failed Scene list, when any Phase 2 calls failed.
- Whether any full rendered contexts were retained, plus expiration timing.
- Generated asset counts.
- Results requiring review count.
- A "view audit details" entry point.

Audit details show summary, section metadata, hashes, and result references. Raw prompt or full rendered context is not shown in the brief. Full rendered context is shown in details only when the specific snapshot retained it.

First implementation exposes read-only backend audit APIs but does not build a full audit workbench UI.

- List snapshots by `workflow_id` or `task_id`.
- Get snapshot details by `snapshot_id`.
- Existing deep-import result UI shows the audit summary and a lightweight detail drawer or JSON detail entry point.
- The first UI slice must not become a separate context-audit workspace.

## Acceptance Tests

- Context module tests cover snapshot creation, default compact storage, optional full `rendered_context` storage, expiration timestamp behavior, success status update, failure status update, and pruning.
- Snapshot creation defaults to not saving `rendered_context`.
- Snapshot creation with `retain_rendered_context=true` saves `rendered_context` and sets `rendered_context_expires_at`.
- Pruning clears or compresses only `rendered_context`; it does not delete the snapshot row or provenance metadata.
- Imports Phase 2 tests cover one snapshot per successful Scene LLM call.
- Imports Phase 2 tests cover failed LLM calls leaving `status="failed"` snapshots with error metadata.
- Imports Phase 2 tests assert generated entity `_meta.context_snapshot_id` is written.
- Phase 3/workflow tests cover one `phase="structure_analysis"` snapshot with `context_mode="working"` and `include_pending_objects=true`.
- Phase 3/workflow tests assert `result_refs` are written back to the snapshot.
- Boundary tests prove snapshots are isolated by `novel_id`.
- Static import tests prove `imports` does not directly import `modules.context.models`, `modules.context.repositories`, or `modules.context.services`.
- Schema/docs acceptance includes ORM, Alembic migration, context module README, imports README, and `CONTEXT.md` staying consistent.
- Demo-stage schema changes do not need a historical data migration path, but ORM, schema, tests, and docs must agree.

## Later Upgrade Points

- Revisit Phase 2 extraction context assembly after snapshot persistence is stable. A later slice may route Phase 2 through the context compiler, but that is a behavior and quality change, not part of first-slice audit persistence.
- Migrate manual AI operations from `context_confirmations` toward `context_snapshots` only after the automated deep-import path is proven.
- Promote high-traffic provenance lookups from metadata JSON to dedicated columns only when query pressure justifies it.
- Add scheduled retention cleanup for optional full `rendered_context` once long-running deployments need automatic pruning beyond explicit facade calls.
