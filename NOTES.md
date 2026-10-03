# Notes

- "持久化快照" in the AI import upgrade refers to persistent context snapshots: records of the context view used by an AI call. It does not mean `memory_snapshots`, an import result batch snapshot, or automatic canonical promotion.
- First implementation scope: deep import Phase 2 and Phase 3 only. Manual AI operations keep using `context_confirmations` until the new persistence path is stable.
- Default snapshot storage should be compact: summary, asset ids, prompt hash, token and section metadata, and compile options. Full rendered context is optional and caller-enabled, not default.
- Persistent context snapshots should use a new `context_snapshots` table. Do not overload `context_confirmations`, which remains the user-confirmation record for manual AI operations.
- Snapshot granularity should be one record per actual LLM call: Phase 2 per Scene extraction call, Phase 3 one structure analysis call. Add retention and pruning for full rendered context to avoid data bloat.
- Retention default: compact metadata stays long term; optional full rendered context is disabled by default and, when enabled, keeps 30 days or latest 200 full-context snapshots per project. Cleanup must preserve provenance metadata.
- Result provenance should be lightweight and bidirectional: `context_snapshots.result_refs` plus `context_snapshot_id` inside existing generated-object `_meta`/metadata JSON. Avoid adding dedicated columns to every generated asset table in the first slice.
- Failed LLM calls should create snapshots. Create before the call as `running`, mark success with result refs, or mark failure with error kind/message and attempt metadata.
- The context module owns `context_snapshots` and exposes facade functions for create/success/failure/prune. Imports should call the facade and avoid direct context internals.
- First slice should not rewire Phase 2 to the context compiler. Persist the handcrafted extraction context actually sent to the LLM, and record compiler-based Phase 2 as a later upgrade point.
- First `context_snapshots` table shape includes task/workflow/phase/operation, scene/chapter ids, mode/status/attempt, prompt/model/hash, JSON metadata and refs, nullable rendered_context, expiration, and indexes for workflow lookup, project chronology, status, and rendered context pruning.
- Context facade first slice should expose create/succeeded/failed/prune functions. Imports keeps snapshot_id through the LLM call and never writes context snapshot internals directly.
- Phase 2 snapshot metadata should summarize scene/chapter, existing entity count, recent accumulated memory, scene text length, pending-object mode; asset ids include scenes/chapters/entities when available, with entity terms allowed in section metadata if ids are not available.
- Phase 3 snapshot metadata should derive from CompiledContext: section count, tokens, evicted/truncated/warnings, section hashes, optional rendered markdown only when retained. Do not refactor all loaders just to expose asset ids in the first slice.
- Acceptance should cover context snapshot CRUD/state/prune behavior, Phase 2 per-call snapshots including failures and entity metadata links, Phase 3 working-context snapshot/result refs, novel_id isolation, forbidden imports, and docs/schema sync.
- Deep-import completion brief should show audit summary counts, failures, retained full-context status/expiry, generated asset counts, review-needed counts, and a detail entry point. Brief should not show raw prompts or full context.
- First implementation should expose read-only backend audit APIs for listing by workflow/task and details by snapshot id, while keeping frontend to existing deep-import summary plus lightweight details. No full audit workbench UI in first slice.
- `workflows/ai-import-persistent-context-snapshot.md` is ready for implementation; no open product decisions remain in the workflow spec.
