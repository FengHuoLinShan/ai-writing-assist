# AI Import Persistent Context Snapshot

Status: Draft, grilling in progress.

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
- Snapshot records must capture `task_id` or workflow id, phase, `context_mode`, included asset ids, rendered context or summary, prompt hash, and creation time.
- The default context mode for deep import snapshots is `working`.
- The snapshot must preserve provenance links from generated results back to the context view used to generate them.
- Candidate creative assets included in a working snapshot remain pending evidence, not canonical facts.
- Results derived from candidate assets must remain `draft`, `candidate`, or `pending`.
- When included candidate assets are ignored, merged, renamed, or promoted, dependent generated results must be markable as `needs_review` or `stale_context`.
- User-facing copy should say "待确认对象" rather than exposing "candidate asset".

## Non-Goals

- Do not promote candidate assets to canonical automatically.
- Do not replace `memory_snapshots` or `memory_events`.
- Do not require a manual checkpoint inside deep import.
- Do not build full automatic cascade recomputation in the first version.
- Do not make the context page the required control surface for import review.

## Checkpoint

The human checkpoint is pushed right: after deep import finishes, the user receives a brief that summarizes generated assets, degraded phases, stale or review-needed results, and links into the review surfaces. The user should not review raw prompts or full rendered context during the import run.

## Open Question

Should the first persistent snapshot store full rendered context, a compact summary plus asset ids, or both?
