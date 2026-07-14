# Worldbuilding Workspace v1 Backend Contract

## Status

Frozen implementation contract for v1.

This contract narrows the broader Worldbuilding Workspace spec into
implementation rules that must stay synchronized with ORM, API schemas and
tests.

## Profile Registry

Strong profile entity types:

- `species`
- `faction`
- `location`
- `rule`
- `item`
- `secret`

Generic profile entity types:

- `group`
- `creature`
- `skill`
- `other`
- `concept`
- `resource`
- `legend`
- `power_system`

Any entity type not in the strong registry uses `generic_entity_profiles`.
Strong and generic rows may coexist only for reversible type history; exactly
one Profile row may be non-`migrated` for one `CoreEntity`. Type transitions
persist versioned snapshots and history in
`generic_entity_profiles.extra_json._type_migration_v1`. Returning to an old
type restores its snapshot and reuses the migrated row. First-time generic to
strong migration preserves fields outside the target binding in
`extra_json.unmapped_generic`. Two active rows are a `profile_state_conflict`.

Author create/update/promote/suggestion-edit-confirm inputs accept safe custom
`entity_type` strings up to 64 characters. AI extraction and initial suggestion
creation remain restricted to the fixed system catalog. Existing entity type
changes must use the world-internal transition service; typed dependencies
block with `entity_type_change_blocked` instead of being deleted or archived.

Profile status carries confirmation semantics. `canonical` and `confirmed` can
be used by reasoning and derived tags. `draft` and `candidate` cannot.

`confidence` records automatic extraction confidence only. It never replaces
author confirmation. `evidence_refs_json` is required for automatic import
writes and optional for manual edits.

## TargetRef

Wire shape:

```json
{
  "target_type": "profile",
  "target_id": "species_profiles:<id>",
  "target_path": "traits[0].name"
}
```

`target_path` may be empty. Empty and `null` normalize to `""`.

Allowed path grammar:

```text
segment := [A-Za-z0-9_]+(\[[0-9]+\])?
path := segment("." segment)*
```

No wildcard, quoted key, negative index or special character path is supported
in v1.

Hash rule:

```text
target_hash = sha256(utf8(json.dumps(
  {"target_id": id, "target_path": normalized_path, "target_type": type},
  sort_keys=True,
  separators=(",", ":")
)))
```

Legacy `CharacterKnowledge.target_type/target_id` remains column-based. Service
adapters expose it as `TargetRef` for read paths; it is not double-written into
a JSON target column.

## Projection Refresh

Projection refresh uses `async_tasks` with task type
`world_bible_projection_refresh`.

Idempotency:

- pending/running + `force=false`: return existing task.
- done/failed + `force=false`: return `409` with old task status and hint.
- done/failed + `force=true`: create a new task.

Projection status is stored on `world_bible_page_projections`. `stale` is read
from that row. Short-lived inconsistency during async updates is acceptable and
responses expose `stale_checked_at`.

## Author Synopsis Refresh

The author-only `world_bible_synopsis_refresh` task uses the existing
PostgreSQL queue and the project LLM execution snapshot seam. The per-project
head is locked when scheduling, so at most one pending/running task is active.
Source commands only mark the synopsis stale; refresh updates the desired
source hash, and both refresh and context compilation recompute the normalized
manifest hash as the correctness check. Before promotion the worker
locks/re-reads the head and performs a source-hash CAS. An obsolete result is
stored as `superseded`, never promoted, and auto-maintenance may enqueue one
coalesced follow-up task.

`CompileOptions.include_world_synopsis` defaults to false and
`selected_world_bible_draft_ids` defaults to an empty list. Confirmations pin
the actual synopsis revision. Generation-center object chat/generate reaches
context through the registered `GenerationBackgroundProvider` port and returns
optional `context_usage` with section/revision/source hash/block hash/token,
stale and fallback fields. These additive defaults preserve old wire behavior.

## Activation Scoring

Source weights:

- `explicit`: 10000. Request directly provides a `TargetRef`, `entity_id`,
  `map_id`, `scene_id` or `focus_entity_id`.
- `scene/map/focus evidence`: 8000. Derived from confirmed Scene or map
  evidence.
- `page linked`: 6000. From World Bible page linked target refs.
- `relation`: 4000. From canonical entity relations.
- `generic related`: 2000. From structured TargetRefs inside `extra_json`, not
  all entities in the same novel.

Final score:

```text
score = source_weight + int(entity.importance * 1000) + recency_bonus
```

Tie-breaker is `target_hash`. Explicit and scene/map/focus candidates are kept
before low-weight truncation.

Defaults: depth 2, top-k 64.

## Derived Knowledge Tags

Derived sync is an explicit service operation, not a DB trigger.

Sources:

- `characters.meta.worldbuilding.species_entity_id`
- canonical `member_of` relation, direction character -> faction
- current character location
- `characters.meta.worldbuilding.profession_label`

`profession_label` is normalized to a lowercase slug. It only grants a tag if
a matching tag already exists with `source=system_profession` or
`source=confirmed_suggestion`.

Draft/candidate sources do not create medium-risk derived tags. They become
high-risk suggestions.

## Canonical World Assets Fallback

When past Scene briefs are unavailable, fallback context may include only:

- `CoreEntity.status=canonical`
- profile/generic `status in (canonical, confirmed)`
- canonical relations
- confirmed map facts
- page-level `context_brief` projections with `status=ready` and `stale=false`

Absent projections and stale projections are both excluded and must produce a
warning.

## Import Risk Classifier

Low:

- objective draft/candidate assets: core entity, profile, generic profile,
  relation candidate, map observation, material page.

Medium:

- derived public tag whose source status is confirmed/canonical, is not blocked
  by exclusion and has confirmed/normalized profession tag semantics.

High:

- draft/candidate source derived tags, `CharacterKnowledge`, visibility
  policy, reader reveal policy, private/manual/triggered tags and unknown
  target types.

## API Response Boundaries

Repeated suggestion confirmation returns HTTP `409`:

```json
{
  "status": "already_processed",
  "suggestion_status": "accepted"
}
```

Projection terminal retry without `force=true` returns HTTP `409`:

```json
{
  "status": "projection_task_finished",
  "task_id": "...",
  "task_status": "failed",
  "hint": "retry with force=true"
}
```

## Non-Goals

- No `knowledge_tag_triggers` table in v1.
- No trigger execution engine.
- No WebSocket for projection progress.
- No dynamic profile plugin registry.
