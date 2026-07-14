# Worldbuilding Workspace v1 Spec

## Status

Draft for implementation planning.

Date: 2026-07-05

This spec consolidates the World Bible / worldbuilding workspace design, the
context activation rules, and the deep-import safety boundaries into one v1
implementation target.

## Goals

- Provide an author-facing World Bible workspace for pre-writing and ongoing
  worldbuilding.
- Reuse the existing `world`, `context`, `map`, `writing`, and `imports`
  modules instead of creating a parallel world database.
- Make world facts available to AI reference material through audited
  `ContextSection` compilation.
- Support map linkage, consistency checks, creation suggestions, and conflict
  queues.
- Let deep import benefit from world context while preventing it from silently
  creating narrative knowledge rules.

## Non-Goals

- No new multi-agent runtime.
- No new frontend framework.
- No separate lorebook database or SillyTavern file format.
- No LLM output directly into canonical facts without schema validation and the
  required confirmation boundary.
- No automatic creation of narrative visibility policies, private knowledge,
  character cognition, or reader reveal rules from deep import.
- No dashboard-style health homepage. Consistency checks are run on demand.

## Core Principles

### Fact Ownership

Each world fact has exactly one authoritative owner.

- World object facts belong to `CoreEntity`, typed profile tables,
  `generic_entity_profiles`, `EntityRelation`, map facts, character knowledge
  boundaries, or structure assets.
- `WorldBiblePage` organizes, references, and narrates facts. It does not own
  profile facts.
- `page_meta_json` stores page organization metadata only.
- `free_text` stores author notes or handbook prose. It is not a structured
  fact source.
- `world_bible_page_projections` are derived caches for context assembly. They
  never write back canonical facts.
- `writing_drafts` are reader-facing artistic text, not the source of world
  truth.

Data flow is one way:

```text
profile / relation / map fact / knowledge / structure
  -> World Bible page reference and narration
  -> projection cache
  -> ContextSection / AI reference material
```

Reverse flow must go through suggestions and author confirmation.

### Author Control

The system can suggest structure, identify conflicts, and fill low-risk drafts,
but author-controlled narrative choices must stay explicit:

- who knows what;
- what readers may safely know;
- which secrets are public, private, or tag-gated;
- which narrative tags are granted to a character;
- whether an event-derived tag should survive a rewrite.

### Deterministic Gates Before LLM Judgment

LLM calls may propose, summarize, or repair format. They do not replace:

- Pydantic schema validation;
- TargetRef validation;
- novel_id isolation;
- knowledge visibility filtering;
- reader safety filtering;
- import write risk classification.

## Domain Model

### CoreEntity And Profiles

`CoreEntity` remains the identity layer for world objects.

Required `entity_type` values:

- `character`
- `location`
- `faction`
- `item`
- `event`
- `rule`
- `power_system`
- `species`
- `group`
- `secret`
- `legend`
- `resource`
- `concept`
- `creature`
- `skill`
- `other`

First batch strong profile tables:

- `species_profiles`
- `faction_profiles`
- `location_profiles`
- `rule_profiles`
- `item_profiles`
- `secret_profiles`

Existing tables remain:

- `characters`
- `events`

Later or lower-frequency types use:

- `entity_profile_templates`
- `generic_entity_profiles`

Profile table constraints:

- 1:1 with `CoreEntity` through `entity_id`.
- Includes `novel_id`.
- Does not duplicate identity fields such as name, aliases, summary, status,
  or provenance.
- Strong fields are used for query, conflict check, context activation, map
  linkage, and sorting.
- `extra_json` / `data_json` is schema-validated and acts as a semi-structured
  incubator for future strong fields.

### World Bible Pages

`world_bible_pages` stores author handbook pages, not fact truth.

Required fields:

- `id`
- `novel_id`
- `page_type`
- `page_key`
- `title`
- `status`
- `page_meta_json`
- `free_text`
- `linked_asset_refs_json`
- `activation_defaults_json`
- `template_key`
- `template_version`
- `version_number`
- `sort_order`
- `created_by`
- `updated_by`
- `created_at`
- `updated_at`

`page_meta_json` may contain:

- display grouping;
- editorial status;
- page ordering;
- related storylines;
- highlight sections;
- local checklist state.

`page_meta_json` must not contain duplicated profile facts such as species
lifespan, faction territory, item powers, or rule consequences.

Fixed entry pages:

- world basic background;
- species / groups;
- factions;
- locations / maps;
- history;
- rules;
- important items;
- main characters;
- secrets / foreshadowing;
- custom pages.

Entity detail pages are dynamic by default. Create an entity-bound World Bible
extension page only when the author writes extra handbook prose or page-specific
metadata for that entity.

### World Bible Revisions

`world_bible_page_revisions` stores meaningful page publish points.

Create a revision when:

- publishing a canonical page;
- applying accepted organization suggestions;
- rolling back to a previous version;
- making a meaningful page-level update.

Do not create revisions for every autosave or cursor-level edit.

Rollback creates a new revision. It does not delete prior revisions and does
not roll back `CoreEntity`, profiles, relations, map facts, or structure assets.

#### 2026-07-14 publish-workspace amendment

Page editing now uses `world_bible_page_drafts`. A new-page draft may have
`page_id=NULL`; an existing page has at most one draft per novel/page. Drafts
store the full editable snapshot and `base_version_number`. Publish locks the
page and performs a version CAS; success updates/creates the canonical page,
writes one immutable revision, removes the draft and invalidates the author
synopsis. A conflict returns 409 and keeps the draft. Restoring a revision
creates a new draft instead of rewriting history.

Built-in categories are `background/species/faction/location/rule/secret/custom`.
Custom categories are presentation metadata only; their key is immutable and
archiving does not delete pages. Structured assets remain canonical truth and
are edited in their owning views, not inline inside World Bible pages.

### Author World Bible Synopsis

`world_bible_synopsis` is a separate P1, author-only derived section. It does
not replace the deterministic, non-evictable P0 `World Core Brief`.
`world_bible_synopsis_heads` stores desired source hash, current/pinned
revision, active task, stale/error state and persisted auto-maintenance
authorization. `world_bible_synopsis_revisions` stores immutable claims,
rendered text, source manifest, coverage/omissions, prompt/model/provider and
project execution snapshot provenance. Reader, character and POV compilation
always excludes it. Restoring an old revision pins it and pauses automatic
promotion until unpin-and-refresh.

### Free Text Projection

`world_bible_page_projections` caches context-ready material derived from
`free_text`.

Projection types:

- `context_brief`
- `style_notes`
- `fact_candidates`
- `excerpt`

Rules:

- Short `free_text` can be excerpted deterministically.
- Long `free_text` can be summarized by LLM.
- Prompts must require extract / compress / organize only.
- Projection must not add facts, infer missing facts, or change canonical
  status.
- `fact_candidates` goes only to suggestions and review UI, not normal writing
  context.
- Each projection records source spans, sensitivity, reveal metadata, token
  estimate, omitted reasons, uncertainty, and stale/fallback state.

### TargetRef

All world fact addressing uses `TargetRef`:

```json
{
  "target_type": "profile",
  "target_id": "species_profiles:<row_id>",
  "target_path": "traits.lifespan"
}
```

First-version `target_type` values:

- `core_entity`
- `profile`
- `generic_profile`
- `relation`
- `world_bible_page`
- `map_fact`
- `projection_span`
- `event`
- `character_knowledge`
- `structure`

`target_path` uses dot paths plus array indexes, for example:

- `history.origin`
- `traits[0].label`
- `source_spans[3]`

No wildcard execution in v1.

All writers must pass `TargetValidator`.

## Knowledge Model

### CharacterKnowledge

`CharacterKnowledge` is a sparse override table for what a character knows.

Levels:

- `unknown`
- `rumor`
- `partial`
- `full`
- `restricted`
- `false_belief`
- `misunderstood`

This table is not a full character by fact matrix. It is used for:

- POV characters;
- main characters;
- key misunderstandings;
- secret holders;
- exceptions from group defaults.

### Knowledge Tags

Tags compress shared knowledge domains.

Core tables:

- `knowledge_tags`
- `character_knowledge_tags`
- `asset_knowledge_tags`
- `knowledge_tag_exclusions`

Grant sources:

- `derived`
- `manual`
- `confirmed_suggestion`
- `triggered`

V1 execution:

- `derived`, `manual`, and `confirmed_suggestion` may affect official
  filtering.
- `triggered` is reserved for a later automatic trigger engine.
- `knowledge_tag_triggers` exists only for draft / preview in v1. The v1 spec
  reserves the concept but does not finalize the executable trigger schema.
  Implementation may store draft trigger metadata only if it is clearly marked
  non-executing.

Minimum draft trigger fields, if stored in v1:

- `id`
- `novel_id`
- `name`
- `event_type`
- `condition_json`
- `action_type`
- `action_params_json`
- `status`: `draft | preview_only`
- `created_at`
- `updated_at`

`status=active` is intentionally out of scope for v1.

Derived tags are generated from existing object facts, such as:

- species;
- faction membership;
- home location;
- profession group.

Derived synchronization must subtract exclusions:

```text
final_derived_tags = derived_candidates - excluded_tags(character_id)
```

### KnowledgeTagExclusion

`knowledge_tag_exclusions` stores author intent that a derived tag should not
apply.

Fields:

- `id`
- `novel_id`
- `character_id`
- `tag_id`
- `reason`
- `source`
- `created_at`

Unique:

- `(novel_id, character_id, tag_id)`

Do not model this as `character_knowledge_tags.is_active=false`.

### Grant Provenance

`character_knowledge_tags` stores source provenance:

- `grant_source`
- `source_ref_type`
- `source_ref_id`
- `source_scene_id`
- `source_chapter_index`
- `source_memory_id`
- `author_locked`

Use it for Scene rewrite / delete / rollback impact previews.

V1 behavior:

- show affected grants before Scene rewrite/delete/rollback;
- allow batch locking;
- allow manual removal;
- do not automatically delete grants.

V2 may auto-remove unlocked event-derived grants.

### Visibility Policies

`knowledge_visibility_policies` supports:

- `public`
- `tag`
- `private`
- `rule_draft`

V1 official filtering executes only:

- `public`
- `tag`
- `private`
- `CharacterKnowledge`

`rule_draft`, implications, and triggers are preview-only.

No LLM batch process may directly create:

- `KnowledgeVisibilityPolicy`;
- private grants;
- `CharacterKnowledge`;
- narrative-specific tags.

They must create suggestions.

## Reader Safety

Reader safety is separate from character knowledge.

`reader_safe` is computed at query/compile time. It is not a stored global
boolean.

`ReaderRevealInfo`:

- `status`: `unrevealed | partial | revealed`
- `reveal_chapter_index`
- `reveal_scene_id`
- `reveal_plan_id`

`ReaderProgress`:

- `effective_chapter_index`
- optional `scene_id`
- optional `reveal_plan_id`

Rules:

- No reveal info means not reader-safe by default.
- `public_baseline=true` world common knowledge may be visible without a
  reveal point.
- `partial` exposes only known / revealed content.
- Reader-facing output and character POV output use the intersection of reader
  safety and character visibility.

Facade:

```text
check_reader_safety(novel_id, targets, reader_progress)
```

Returns:

- `reader_safe`
- `reveal_status`
- `effective_reveal_point`
- `visible_content`
- `public_baseline`
- `diagnostics`

## Import Write Risk Classifier

Deep import can extract facts. It must not make narrative knowledge choices.

Risk levels:

### Low Risk

May write `draft` / `candidate`:

- `CoreEntity`
- typed profile draft;
- generic profile draft;
- relation candidate;
- map fact candidate;
- World Bible material page / free-text excerpt.

Required metadata:

- `source="deep_import"`
- workflow id;
- scene id / chapter index;
- evidence refs;
- confidence;
- `needs_review`.

Low-risk profile drafts are not official knowledge reasoning inputs until
confirmed.

### Medium Risk

May automatically apply only when all conditions hold:

- tag is derived from existing CoreEntity/profile fields;
- tag is public-default only;
- no narrative-specific meaning;
- `knowledge_tag_exclusions` does not block it;
- target entity and novel_id are valid.

Example:

- profile says character species is "elf";
- system grants derived `species:elf` tag.

### High Risk

Must go to import review suggestions:

- `KnowledgeVisibilityPolicy`;
- private grants;
- rule drafts that affect visibility;
- narrative-specific tags;
- manual / triggered character tags;
- `CharacterKnowledge`;
- reader reveal policy.

Scene-local "character learned X" is high risk in v1, even with direct textual
evidence. It becomes a `character_knowledge` suggestion with evidence span,
confidence, source scene, and proposed knowledge level.

## Suggestion And Conflict Queues

### Creation Suggestions

`creation_suggestion_queue` stores LLM/system suggestions.

Fields for import review:

- `source_module`: `imports | world_bible | conflict_check | manual`
- `review_group`: `import_profile | import_knowledge | import_structure | page_organization`
- `target_type`: `profile_field | relation | map_fact | character_tag | character_knowledge | visibility_policy | reader_reveal_policy | structure`
- `payload_json`
- `evidence_refs_json`
- `risk_level`
- `status`: `pending | accepted | rejected | conflict`

Import review panels should use the same queue endpoint with query filters:

- `source_module=imports`
- `review_group=import_knowledge | import_profile | import_structure`
- optional `risk_level`
- optional `status`

Accepting suggestions must use module facades and schema validation. Do not
write from queue payload directly to tables.

### Conflict Queue

`conflict_check_queue` stores:

- fact conflicts;
- narrative risks.

Fact conflicts require correction or explicit resolution.
Narrative risks are advisory and non-blocking.

## Context Activation

`ContextActivationRule` determines when world assets enter AI reference
material.

Inputs may include:

- task type;
- scene id;
- chapter range;
- explicit map id;
- focus entity id;
- character / POV;
- keywords;
- linked assets;
- recursion depth.

V1 defaults:

- recursive activation depth: 2;
- top-k caps on each expansion;
- activation reasons visible in UI metadata;
- activation reasons do not enter LLM token budget.

Context sections must expose:

- activation reason;
- source refs;
- token estimate;
- clipped / omitted reason;
- stale or fallback projection state;
- sensitivity;
- computed reader safety when applicable.

## Map Linkage

Map focus can affect context, but there is no implicit global current map.

Map focus sources in priority order:

1. Explicit `map_id` passed by the request.
2. `scene_id` inferred through scene markers, confirmed map facts, or candidate
   observations.
3. `focus_entity_id` inferred through location binding, markers, or territory.
4. UI active map only if frontend passes it explicitly.

Map facts participate in:

- object-to-map navigation;
- map-to-object navigation;
- context activation;
- conflict checks.

## Page Organization Workflow

`POST /api/world/bible/pages/{id}/organize`

Stages:

1. `page_preflight`
2. `projection_refresh`
3. `page_meta_suggestion`
4. `asset_suggestion`
5. `conflict_scan`
6. `result_commit`

Writes only:

- task result;
- creation suggestions;
- conflict queue items;
- projection diagnostics.

It does not directly write canonical facts.

## Deep Import Integration

Imports consumes context through context facade. It does not own world
aggregation.

### Phase 2

Target flow:

1. Build `ImportContextActivation` for each Scene.
2. Run Scene-local extraction concurrently.
3. Submit writes in `scene_index` order.
4. Run dedup/merge at write boundaries.
5. Record checkpoint and quality stats.

Scene-local context:

- current Scene: full chunks;
- previous neighbors: default 2 briefs, rerun up to 4;
- previous snippets only when strong continuity evidence exists;
- future Scene text is forbidden.

Future evidence can be used only for:

- alias/entity dedup;
- relation reconciliation;
- cross-chapter continuity scoring;
- Phase 3 structure overview;
- foreshadowing payoff analysis.

Future evidence cannot rewrite current Scene knowledge, reader state, or fact
time.

### Phase 3

Uses all-book summary view, not full book text.

Inputs:

- all Scene briefs;
- WorldBackgroundAggregation;
- sampled evidence snippets;
- compact summaries only when budget requires them.

Quality gates:

- plot threads must cite Scene or entity;
- arcs must have chapter ranges;
- fallback ratio has limits;
- empty `related_entity_ids` ratio has limits;
- cross-chapter Scenes must be structurally carried forward.

## Frontend UX

World Bible homepage:

- page navigation;
- recent page or world basic background entry;
- bottom buttons for `创设建议` and `冲突检查`;
- no dashboard health percentage.

Entity / page UI:

- encyclopedia / handbook style;
- entry points for species, groups, factions, locations, rules, history, items,
  secrets, characters;
- AI reference preview with activation reasons, token share, sources, clipping,
  stale/fallback status;
- page organization result modal grouped by risk;
- import review panel for high-risk knowledge suggestions.

Knowledge UI:

- show derived, manual, and confirmed suggestion tags separately;
- allow "remove and permanently exclude" for derived tags;
- show provenance for event-derived or suggestion-derived tags;
- allow batch lock before Scene rewrite/delete/rollback;
- show reader reveal point and preview by chapter.

## Backend Boundaries

`world` owns:

- CoreEntity;
- profiles;
- relations;
- character knowledge;
- knowledge tags;
- reader reveal policies;
- map fact business rules;
- suggestion acceptance into world assets.

`context` owns:

- activation rules;
- context compilation;
- budget enforcement;
- context snapshots;
- compact steps.

`imports` owns:

- import workflow;
- LLM extraction;
- checkpoints;
- phase artifacts;
- quality stats;
- import write risk classification before calling world/context facades.

`frontend-console` owns:

- author UI;
- previews;
- review panels;
- progress display.

Cross-module calls use contracts/facades only.

## Suggested Facades

World facade:

```text
get_entity_profile(novel_id, entity_id)
list_entity_profiles(novel_id, entity_type, filters)
check_knowledge_visibility(novel_id, character_id, targets, mode)
check_reader_safety(novel_id, targets, reader_progress)
sync_derived_knowledge_tags(novel_id, character_id)
create_knowledge_tag_exclusion(novel_id, character_id, tag_id, reason)
delete_knowledge_tag_exclusion(novel_id, character_id, tag_id)
preview_scene_knowledge_tag_impact(novel_id, scene_id)
accept_creation_suggestion(novel_id, suggestion_id)
```

Context facade:

```text
compile_context(novel_id, request)
preview_activation(novel_id, request)
create_context_confirmation(novel_id, request)
build_import_context_activation(novel_id, scene_id, options)
```

Imports adapter:

```text
classify_import_write(candidate) -> low | medium | high
submit_low_risk_draft(candidate)
submit_import_suggestion(candidate)
```

## HTTP API Shape

Suggested additions:

```text
GET    /api/world/profiles?entity_type=...
GET    /api/world/profiles/{entity_id}

GET    /api/world/bible/pages
POST   /api/world/bible/pages
GET    /api/world/bible/pages/{id}
PATCH  /api/world/bible/pages/{id}
GET    /api/world/bible/templates
POST   /api/world/bible/pages/{id}/organize
POST   /api/world/bible/pages/{id}/refresh-projection
POST   /api/world/bible/pages/{id}/consistency-check

GET    /api/world/suggestions
GET    /api/world/suggestions?source_module=imports&review_group=import_knowledge
POST   /api/world/suggestions/{id}/confirm
POST   /api/world/suggestions/{id}/reject

GET    /api/world/conflicts
POST   /api/world/conflicts/{id}/resolve

POST   /api/world/characters/{character_id}/knowledge-tags/{tag_id}/exclude
DELETE /api/world/characters/{character_id}/knowledge-tags/{tag_id}/exclude
POST   /api/world/characters/{character_id}/knowledge-tags/{tag_id}/lock

GET    /api/world/scenes/{scene_id}/knowledge-tag-impact

GET    /api/context/activation-preview
POST   /api/context/confirm
```

Existing deep import API shape should not break.

## Migration Plan

1. Add / finalize world profile contracts.
2. Extend `CoreEntity.entity_type` validation.
3. Add first-batch profile tables.
4. Add `entity_profile_templates` and `generic_entity_profiles`.
5. Add TargetRef validators and shared contract.
6. Add Fact Ownership checks in docs/tests.
7. Add `world_bible_pages`, revisions, templates, projections.
8. Replace old `structured_fields_json` planning with `page_meta_json`.
9. Add knowledge tables and execution rules.
10. Add reader reveal policies.
11. Add suggestion/conflict queue contracts for import review.
12. Add Import Write Risk Classifier.
13. Implement page organization task.
14. Implement context activation defaults and preview.
15. Connect Phase 2 and Phase 3 imports through context facade.
16. Add frontend World Bible workspace.
17. Run small-sample deep import validation.
18. Run full project 212 validation when cost/time allows.

## Test Plan

Backend:

- profile CRUD and novel_id isolation;
- TargetRef validation;
- page meta schema validation;
- projection stale/fallback behavior;
- fact ownership: profile wins over page/free_text/projection;
- knowledge visibility public/tag/private;
- CharacterKnowledge override levels;
- derived tag sync with exclusions;
- grant provenance and Scene impact preview;
- reader safety by chapter/scene progress;
- import write risk classifier;
- creation suggestion acceptance through facade;
- context activation recursion and top-k;
- deep import no future Scene context;
- Phase 2 ordered commit after concurrent extraction;
- Phase 3 structure references and fallback limits.

Frontend:

- World Bible navigation;
- profile and page editing;
- page organization modal grouping;
- suggestion/conflict modals from homepage buttons;
- AI reference preview with sources, reasons, token share, stale/fallback;
- derived tag exclusion UX;
- reader progress preview;
- import review UX.

Regression:

- imports targeted pytest;
- world targeted pytest;
- context targeted pytest;
- outline structure tests;
- frontend-console tests;
- ruff check;
- git diff --check.

## Acceptance Criteria

- Authors can maintain core worldbuilding assets through World Bible entry
  points without duplicating fact truth in page text.
- AI reference preview shows why each section is included and how much budget it
  consumes.
- Deep import uses world/context information but high-risk knowledge choices
  remain review items.
- Derived public tags can be synchronized and permanently excluded.
- Reader-safe output changes with reader progress.
- Map focus participates in context only when explicitly passed or provably
  inferred from Scene/entity evidence.
- No module crosses into another module's repositories/services in production
  code.
