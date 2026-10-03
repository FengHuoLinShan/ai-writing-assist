# DECISIONS.md

Lightweight decision log for in-progress design cleanup. ADRs in `docs/adr/` remain the authority for durable architecture decisions; this file tracks accepted design choices and follow-up document sync points while a spec is still evolving.

## 2026-07-04 — World Bible First-Version Scope

- Decision: World Bible does not use a dashboard-style homepage or health percentage.
  - Impact: World Bible homepage remains a light entry with page navigation and action buttons.
  - Execution: Replace health/dashboard wording with on-demand `世界一致性检查报告`.

- Decision: Knowledge levels are `unknown`, `rumor`, `partial`, `full`, `restricted`, `false_belief`, `misunderstood`.
  - Impact: Character POV filtering can represent limited knowledge and distorted understanding.
  - Execution: Keep `CharacterKnowledge.knowledge_level` as the single override depth field.

- Decision: `background_group` is not a World Bible asset type.
  - Impact: Groups are represented as `CoreEntity(entity_type="group")` using `generic_entity_profiles`; organized factions use `faction_profiles`.
  - Execution: Remove `/api/world/background/groups` from proposed public API shape.

- Decision: Knowledge visibility v1 executes only `public`, `tag`, `private`, plus `CharacterKnowledge` override.
  - Impact: `rule_draft`, `knowledge_implications`, and `knowledge_tag_triggers` are stored and previewed only.
  - Execution: Official prompt filtering must use `check_knowledge_visibility(..., mode="enabled")`.

- Decision: All world fact addressing uses `TargetRef`.
  - Impact: Visibility, conflict checks, projections, suggestions, and UI highlights share `target_type`, `target_id`, `target_path`.
  - Execution: Do not use `background_group` or ad hoc string paths as authoritative references; wire shape uses TargetRef JSON.

- Decision: Reader safety is progress-dependent, not a stored global boolean.
  - Impact: Character knowledge and reader-safe output are independent filters; reader-facing output uses their intersection when both apply.
  - Execution: Store reveal metadata on TargetRef / projection spans and compute `reader_safe` from `ReaderRevealInfo` plus `ReaderProgress`.

- Decision: Derived knowledge tag removals use a dedicated exclusion table.
  - Impact: Author intent survives future automatic tag synchronization from species, faction, location, or relations.
  - Execution: Add `knowledge_tag_exclusions`; sync computes derived candidates, subtracts exclusions, then upserts effective grants.

- Decision: Event-derived knowledge tags need provenance before automatic rollback.
  - Impact: Scene rewrite/delete/rollback can identify affected derived grants without silently erasing author intent.
  - Execution: Store grant source refs and `author_locked` on `character_knowledge_tags`; v1 shows impact and allows locking, v2 may auto-remove unlocked event-derived grants.

- Decision: World facts have one authoritative owner.
  - Impact: Profile fields / profile `extra_json`, relations, map facts, character knowledge, and structure assets own facts; World Bible pages organize and narrate them.
  - Execution: Use `page_meta_json` for page organization metadata, move old `structured_fields_json` fact-like content into profile suggestions, and keep projections as caches only.

- Decision: Deep import records fact outlines but does not make narrative knowledge choices.
  - Impact: Auto-import can fill draft/candidate entities and profiles, while visibility policies, narrative tags, and character cognition stay under author review.
  - Execution: Add an import write risk classifier; high-risk knowledge outputs become `creation_suggestion_queue` import review items, not direct writes.
