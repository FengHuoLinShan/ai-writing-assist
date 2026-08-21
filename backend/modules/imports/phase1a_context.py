"""Deterministic, frozen reference context for Phase 1a Scene windows."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.imports.scene_planning import ScenePlanResult, SceneWindowPlan

PHASE1A_CONTEXT_CONTRACT_VERSION = "phase1a-context-v2"
PHASE1A_LEFT_BOUNDARY_CHAR_LIMIT = 2_000
PHASE1A_CHARACTER_TOP_K = 6
PHASE1A_WORLD_OBJECT_TOP_K = 16

OutlineLoader = Callable[..., Awaitable[Any]]
EntityTermsLoader = Callable[..., Awaitable[list[dict[str, Any]]]]
WorldContextLoader = Callable[..., Awaitable[Any]]
CharacterContextLoader = Callable[..., Awaitable[Any]]


class Phase1aContextBuilder:
    """Compile bounded author-safe context before provider execution."""

    def __init__(
        self,
        *,
        outline_loader: OutlineLoader | None = None,
        entity_terms_loader: EntityTermsLoader | None = None,
        world_context_loader: WorldContextLoader | None = None,
        character_context_loader: CharacterContextLoader | None = None,
    ) -> None:
        self._outline_loader = outline_loader
        self._entity_terms_loader = entity_terms_loader
        self._world_context_loader = world_context_loader
        self._character_context_loader = character_context_loader

    async def compile(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        plan: ScenePlanResult,
        boundary_chapters: Iterable[dict[str, Any]] | None = None,
    ) -> ScenePlanResult:
        """Return a deep copy of ``plan`` carrying one frozen bundle per window."""
        frozen_plan = plan.model_copy(deep=True)
        if frozen_plan.blocked or not frozen_plan.windows:
            frozen_plan.phase1a_context = _empty_context_manifest()
            return frozen_plan

        all_chapters = {
            int(item["chapter_index"]): item
            for item in [*frozen_plan.chapters, *(boundary_chapters or [])]
        }
        entity_terms = await self._load_entity_terms(db, novel_id)
        windows: list[dict[str, Any]] = []
        for window in frozen_plan.windows:
            outline = await self._load_outline(db, novel_id, window)
            self._require_novel(outline, novel_id, "outline context")
            reference = await self._build_reference_context(
                db,
                novel_id=novel_id,
                window=window,
                chapters=all_chapters,
                outline=outline,
                entity_terms=entity_terms,
            )
            left_context = _left_boundary_context(window, all_chapters)
            window.left_boundary_context = left_context
            window.reference_context = reference
            windows.append(
                {
                    "window_id": window.window_id,
                    "left_boundary_context": left_context,
                    "reference_context": reference,
                }
            )

        manifest = {
            "contract_version": PHASE1A_CONTEXT_CONTRACT_VERSION,
            "limits": {
                "left_boundary_chars": PHASE1A_LEFT_BOUNDARY_CHAR_LIMIT,
                "characters": PHASE1A_CHARACTER_TOP_K,
                "world_objects": PHASE1A_WORLD_OBJECT_TOP_K,
            },
            "windows": windows,
        }
        manifest["fingerprint"] = stable_context_hash(manifest)
        frozen_plan.phase1a_context = manifest
        frozen_plan.quality_stats = {
            **frozen_plan.quality_stats,
            "phase1a_context_contract_version": PHASE1A_CONTEXT_CONTRACT_VERSION,
            "phase1a_context_fingerprint": manifest["fingerprint"],
            "phase1a_context_window_count": len(windows),
        }
        return frozen_plan

    async def _build_reference_context(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        window: SceneWindowPlan,
        chapters: dict[int, dict[str, Any]],
        outline: Any,
        entity_terms: list[dict[str, Any]],
    ) -> dict[str, Any]:
        text = "\n".join(
            str(chapters[index].get("content") or "")
            for index in window.chapter_indices
            if index in chapters
        )
        ranked = _rank_relevant_entities(text, outline, entity_terms)
        character_ranked = [item for item in ranked if item["kind"] == "character"]
        object_ranked = [item for item in ranked if item["kind"] != "character"]
        selected_characters = character_ranked[:PHASE1A_CHARACTER_TOP_K]
        selected_objects = object_ranked[:PHASE1A_WORLD_OBJECT_TOP_K]
        selected_ids = [
            *(item["id"] for item in selected_characters),
            *(item["id"] for item in selected_objects),
        ]
        world = await self._load_world_context(
            db,
            novel_id,
            selected_ids,
            current_chapter=window.owned_end,
        )
        self._require_novel(world, novel_id, "world context")
        world_by_id = {
            str(item.entity_id): item
            for item in getattr(world, "entities", [])
            if str(getattr(item, "status", "")) == "canonical"
        }
        character_profiles = await self._load_character_context(
            db,
            novel_id,
            [item["id"] for item in selected_characters],
        )
        profile_by_id = {
            str(item.character_id): item
            for item in getattr(character_profiles, "characters", [])
        }
        resolved_characters = [
            item for item in selected_characters if item["id"] in world_by_id
        ]
        resolved_objects = [
            item for item in selected_objects if item["id"] in world_by_id
        ]
        unavailable_characters = [
            item for item in selected_characters if item["id"] not in world_by_id
        ]
        unavailable_objects = [
            item for item in selected_objects if item["id"] not in world_by_id
        ]

        payload = {
            "contract_version": PHASE1A_CONTEXT_CONTRACT_VERSION,
            "window_id": window.window_id,
            "range": {
                "covered": [window.covered_start, window.covered_end],
                "owned": [window.owned_start, window.owned_end],
            },
            "outline": _compact_outline(outline),
            "characters": [
                _character_payload(
                    item,
                    profile_by_id.get(item["id"]),
                    world_by_id.get(item["id"]),
                )
                for item in resolved_characters
            ],
            "world_objects": [
                _world_object_payload(item, world_by_id[item["id"]])
                for item in resolved_objects
            ],
            "selection_trace": {
                "priority": [
                    "text_mention",
                    "scene_relation",
                    "outline_relation",
                ],
                "included": {
                    "characters": _selection_trace(resolved_characters),
                    "world_objects": _selection_trace(resolved_objects),
                },
                "omitted": {
                    "characters": [
                        *_selection_trace(
                            character_ranked[PHASE1A_CHARACTER_TOP_K:],
                            omitted_reason="top_k_limit",
                        ),
                        *_selection_trace(
                            unavailable_characters,
                            omitted_reason="not_author_safe_canonical",
                        ),
                    ],
                    "world_objects": [
                        *_selection_trace(
                            object_ranked[PHASE1A_WORLD_OBJECT_TOP_K:],
                            omitted_reason="top_k_limit",
                        ),
                        *_selection_trace(
                            unavailable_objects,
                            omitted_reason="not_author_safe_canonical",
                        ),
                    ],
                },
            },
        }
        payload["content_hash"] = stable_context_hash(payload)
        return payload

    async def _load_outline(
        self,
        db: AsyncSession,
        novel_id: str,
        window: SceneWindowPlan,
    ) -> Any:
        loader = self._outline_loader
        if loader is None:
            from modules.story.facade import get_outline_analysis_context

            loader = get_outline_analysis_context
        return await loader(
            db,
            novel_id,
            start_chapter=window.covered_start,
            end_chapter=window.covered_end,
        )

    async def _load_entity_terms(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> list[dict[str, Any]]:
        loader = self._entity_terms_loader
        if loader is None:
            from modules.world.facade import list_entity_terms

            loader = list_entity_terms
        return await loader(db, novel_id, limit=10_000)

    async def _load_world_context(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_ids: list[str],
        *,
        current_chapter: int,
    ) -> Any:
        if not entity_ids:
            return _EmptyWorldContext(novel_id)
        loader = self._world_context_loader
        if loader is None:
            from modules.world.facade import get_world_context

            loader = get_world_context
        return await loader(
            db,
            novel_id,
            entity_ids=entity_ids,
            reveal_mode="author_safe",
            limit=len(entity_ids),
            current_chapter=current_chapter,
            include_review=False,
        )

    async def _load_character_context(
        self,
        db: AsyncSession,
        novel_id: str,
        character_ids: list[str],
    ) -> Any:
        if not character_ids:
            return _EmptyCharacterContext()
        loader = self._character_context_loader
        if loader is None:
            from modules.world.facade import get_characters_context

            loader = get_characters_context
        return await loader(
            db,
            novel_id,
            character_ids=character_ids,
            reveal_mode="author_safe",
        )

    @staticmethod
    def _require_novel(value: Any, novel_id: str, label: str) -> None:
        returned = str(getattr(value, "novel_id", "") or "")
        if returned and returned != novel_id:
            raise ValueError(f"{label} novel_id mismatch")


class _EmptyWorldContext:
    def __init__(self, novel_id: str) -> None:
        self.novel_id = novel_id
        self.entities: list[Any] = []


class _EmptyCharacterContext:
    characters: list[Any] = []


def apply_frozen_phase1a_context(
    plan: ScenePlanResult,
    manifest: dict[str, Any],
) -> ScenePlanResult:
    """Attach an already-fingerprinted v2 manifest to a fresh deterministic plan."""
    expected = str(manifest.get("fingerprint") or "")
    unhashed = {key: value for key, value in manifest.items() if key != "fingerprint"}
    if (
        manifest.get("contract_version") != PHASE1A_CONTEXT_CONTRACT_VERSION
        or not expected
        or stable_context_hash(unhashed) != expected
    ):
        raise ValueError("invalid frozen Phase 1a context manifest")
    frozen = plan.model_copy(deep=True)
    by_id = {
        str(item.get("window_id") or ""): item
        for item in manifest.get("windows") or []
        if isinstance(item, dict)
    }
    if set(by_id) != {window.window_id for window in frozen.windows}:
        raise ValueError("frozen Phase 1a context windows do not match Phase 0 plan")
    for window in frozen.windows:
        item = by_id[window.window_id]
        window.left_boundary_context = str(item.get("left_boundary_context") or "")
        reference = item.get("reference_context")
        if not isinstance(reference, dict):
            raise ValueError("frozen Phase 1a reference context is invalid")
        window.reference_context = dict(reference)
    frozen.phase1a_context = dict(manifest)
    frozen.quality_stats = {
        **frozen.quality_stats,
        "phase1a_context_contract_version": PHASE1A_CONTEXT_CONTRACT_VERSION,
        "phase1a_context_fingerprint": expected,
        "phase1a_context_window_count": len(frozen.windows),
    }
    return frozen


def stable_context_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _empty_context_manifest() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "contract_version": PHASE1A_CONTEXT_CONTRACT_VERSION,
        "limits": {
            "left_boundary_chars": PHASE1A_LEFT_BOUNDARY_CHAR_LIMIT,
            "characters": PHASE1A_CHARACTER_TOP_K,
            "world_objects": PHASE1A_WORLD_OBJECT_TOP_K,
        },
        "windows": [],
    }
    payload["fingerprint"] = stable_context_hash(payload)
    return payload


def _left_boundary_context(
    window: SceneWindowPlan,
    chapters: dict[int, dict[str, Any]],
) -> str:
    previous = chapters.get(window.covered_start - 1)
    if previous is None:
        return ""
    return str(previous.get("content") or "")[-PHASE1A_LEFT_BOUNDARY_CHAR_LIMIT:]


def _rank_relevant_entities(
    text: str,
    outline: Any,
    entity_terms: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    terms_by_id = {
        str(item.get("id") or ""): item for item in entity_terms if item.get("id")
    }
    lowered_text = text.casefold()
    for item_id, term_item in terms_by_id.items():
        positions = [
            lowered_text.find(str(term).casefold())
            for term in term_item.get("terms") or []
            if str(term or "").strip()
        ]
        positions = [position for position in positions if position >= 0]
        if positions:
            _offer_candidate(
                candidates,
                item_id=item_id,
                kind=str(term_item.get("entity_type") or "entity"),
                tier=0,
                order=min(positions),
                reason="text_mention",
                name=str(term_item.get("name") or ""),
            )

    scene_order = 0
    for scene in getattr(outline, "scenes", []) or []:
        for item_id in _ids_from(scene, _CHARACTER_KEYS):
            _offer_candidate(
                candidates,
                item_id=item_id,
                kind="character",
                tier=1,
                order=scene_order,
                reason="scene_relation",
                name=_term_name(terms_by_id, item_id),
            )
            scene_order += 1
        for item_id in _ids_from(scene, ("related_entity_ids",)):
            _offer_candidate(
                candidates,
                item_id=item_id,
                kind=_term_kind(terms_by_id, item_id),
                tier=1,
                order=scene_order,
                reason="scene_relation",
                name=_term_name(terms_by_id, item_id),
            )
            scene_order += 1

    outline_order = 0
    for item in [
        *(getattr(outline, "arcs", []) or []),
        *(getattr(outline, "plot_threads", []) or []),
    ]:
        for item_id in _ids_from(item, ("related_character_ids",)):
            _offer_candidate(
                candidates,
                item_id=item_id,
                kind="character",
                tier=2,
                order=outline_order,
                reason="outline_relation",
                name=_term_name(terms_by_id, item_id),
            )
            outline_order += 1
        for item_id in _ids_from(item, ("related_entity_ids",)):
            _offer_candidate(
                candidates,
                item_id=item_id,
                kind=_term_kind(terms_by_id, item_id),
                tier=2,
                order=outline_order,
                reason="outline_relation",
                name=_term_name(terms_by_id, item_id),
            )
            outline_order += 1
    return sorted(
        candidates.values(),
        key=lambda item: (item["tier"], item["order"], item["id"]),
    )


_CHARACTER_KEYS = (
    "pov_character_id",
    "related_character_ids",
    "present_character_ids",
    "character_ids",
)


def _offer_candidate(
    candidates: dict[str, dict[str, Any]],
    *,
    item_id: str,
    kind: str,
    tier: int,
    order: int,
    reason: str,
    name: str,
) -> None:
    normalized_id = str(item_id or "").strip()
    if not normalized_id:
        return
    normalized_kind = "character" if kind == "character" else kind or "entity"
    offered = {
        "id": normalized_id,
        "kind": normalized_kind,
        "tier": tier,
        "order": order,
        "reason": reason,
        "name": name,
    }
    current = candidates.get(normalized_id)
    if current is None or (tier, order, normalized_id) < (
        current["tier"],
        current["order"],
        current["id"],
    ):
        candidates[normalized_id] = offered
    elif normalized_kind == "character":
        current["kind"] = "character"


def _ids_from(item: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
    values: list[str] = []
    for key in keys:
        raw = item.get(key)
        if isinstance(raw, list | tuple | set):
            values.extend(str(value) for value in raw if value)
        elif raw:
            values.append(str(raw))
    return values


def _term_kind(terms: dict[str, dict[str, Any]], item_id: str) -> str:
    return str(terms.get(item_id, {}).get("entity_type") or "entity")


def _term_name(terms: dict[str, dict[str, Any]], item_id: str) -> str:
    return str(terms.get(item_id, {}).get("name") or "")


def _compact_outline(outline: Any) -> dict[str, Any]:
    return {
        "scenes": [
            _compact(
                item,
                (
                    "id",
                    "scene_index",
                    "chapter_indices",
                    "title",
                    "goal",
                    "core_conflict",
                    "emotional_beat",
                    "narrative_tag",
                    "pov_character_id",
                    "related_thread_ids",
                ),
            )
            for item in getattr(outline, "scenes", []) or []
        ],
        "arcs": [
            _compact(
                item,
                (
                    "id",
                    "title",
                    "arc_index",
                    "start_chapter",
                    "end_chapter",
                    "arc_goal",
                    "core_conflict",
                    "main_opposition",
                    "entry_hook",
                    "midpoint_turn",
                    "climax",
                    "result",
                    "next_hook",
                    "related_thread_ids",
                ),
            )
            for item in getattr(outline, "arcs", []) or []
        ],
        "plot_threads": [
            _compact(
                item,
                (
                    "id",
                    "name",
                    "thread_type",
                    "summary",
                    "visible_goal",
                    "hidden_truth",
                    "start_chapter",
                    "planned_payoff_chapter",
                    "current_stage",
                    "reader_known_state",
                    "author_known_state",
                ),
            )
            for item in getattr(outline, "plot_threads", []) or []
        ],
        "warnings": list(getattr(outline, "warnings", []) or []),
    }


def _compact(item: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {
        key: item[key]
        for key in keys
        if key in item and item[key] not in (None, "", [], {})
    }


def _character_payload(
    ranked: dict[str, Any],
    profile: Any | None,
    entity: Any,
) -> dict[str, Any]:
    return _drop_empty(
        {
            "id": ranked["id"],
            "name": getattr(profile, "name", None) or getattr(entity, "name", None),
            "role": getattr(profile, "role", None),
            "personality": getattr(profile, "personality", None),
            "desire": getattr(profile, "desire", None),
            "fear": getattr(profile, "fear", None),
            "weakness": getattr(profile, "weakness", None),
            "current_goal": getattr(profile, "current_goal", None),
            "current_state": getattr(profile, "current_state", None),
            "current_emotion": getattr(profile, "current_emotion", None),
            "stance": getattr(profile, "stance", None),
            "voice_style": getattr(profile, "voice_style", None),
            "relationship_summary": getattr(profile, "relationship_summary", None),
            "summary": getattr(entity, "summary", None),
            "public_info": getattr(entity, "public_info", None),
        }
    )


def _world_object_payload(ranked: dict[str, Any], entity: Any) -> dict[str, Any]:
    return _drop_empty(
        {
            "id": ranked["id"],
            "entity_type": getattr(entity, "entity_type", None),
            "name": getattr(entity, "name", None),
            "summary": getattr(entity, "summary", None),
            "public_info": getattr(entity, "public_info", None),
            "importance_level": getattr(entity, "importance_level", None),
        }
    )


def _selection_trace(
    items: list[dict[str, Any]],
    *,
    omitted_reason: str | None = None,
) -> list[dict[str, Any]]:
    return [
        _drop_empty(
            {
                "id": item["id"],
                "name": item.get("name"),
                "reason": item["reason"],
                "first_order": item["order"],
                "omitted_reason": omitted_reason,
            }
        )
        for item in items
    ]


def _drop_empty(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item not in (None, "", [], {})}


__all__ = [
    "PHASE1A_CHARACTER_TOP_K",
    "PHASE1A_CONTEXT_CONTRACT_VERSION",
    "PHASE1A_LEFT_BOUNDARY_CHAR_LIMIT",
    "PHASE1A_WORLD_OBJECT_TOP_K",
    "Phase1aContextBuilder",
    "apply_frozen_phase1a_context",
    "stable_context_hash",
]
