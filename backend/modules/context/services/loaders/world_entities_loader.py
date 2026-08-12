"""世界对象加载器"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.contracts import (
    AUTHOR_ONLY_WARNING,
    CONTEXT_BUDGET,
    CompileOptions,
    StructureContextBundle,
)
from modules.context.services.protocol import Loader

logger = logging.getLogger(__name__)

_GetWorldContextFn = Callable[..., Awaitable[Any]]
_ACTIVE_WORLD_STATUSES = frozenset({"active", "canonical", "confirmed", "published"})
_ARCHIVED_WORLD_STATUSES = frozenset(
    {"accepted", "deprecated", "ignored", "merged", "rejected", "rolled_back"}
)


def _entity_dict(entity: Any) -> dict[str, Any]:
    if isinstance(entity, dict):
        return dict(entity)
    if hasattr(entity, "model_dump"):
        return dict(entity.model_dump())
    return {key: value for key, value in vars(entity).items() if not key.startswith("_")}


def _project_display_state(entity: dict[str, Any]) -> str:
    projected = str(entity.get("display_state") or "").strip().lower()
    if projected in {"active", "review", "archived"}:
        return projected
    status = str(entity.get("status") or "canonical").strip().lower()
    if status in _ACTIVE_WORLD_STATUSES:
        return "active"
    if status in _ARCHIVED_WORLD_STATUSES:
        return "archived"
    return "review"


def _filter_world_entities(
    entities: list[dict[str, Any]],
    *,
    include_pending_objects: bool,
) -> list[dict[str, Any]]:
    visible: list[dict[str, Any]] = []
    for raw_entity in entities:
        entity = dict(raw_entity)
        display_state = _project_display_state(entity)
        entity["display_state"] = display_state
        if display_state == "archived":
            continue
        if display_state == "review" and not include_pending_objects:
            continue
        visible.append(entity)
    return visible


async def _default_get_world_context(*args: Any, **kwargs: Any) -> Any:
    from modules.world.facade import get_world_context

    return await get_world_context(*args, **kwargs)


class WorldEntitiesLoader(Loader):
    """加载世界对象，按重要性排序并受 budget 限制"""

    def __init__(
        self,
        get_world_context_fn: _GetWorldContextFn = _default_get_world_context,
    ) -> None:
        self._get_world_context = get_world_context_fn

    @property
    def name(self) -> str:
        return "world_entities"

    async def load(
        self,
        db: AsyncSession,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> None:
        core_limit = CONTEXT_BUDGET.get("core_entities", 8)
        normal_limit = CONTEXT_BUDGET.get("normal_entities", 8)
        all_limit = core_limit + normal_limit
        generation_action = options.consumer_action in {
            "outline.analyze",
            "world.generation.chat",
            "world.generation.core_entity",
            "world.generation.world_bible_page",
            "world.map_atlas.generate",
        }
        if options.consumer_action == "world.map_atlas.generate":
            from modules.world.facade import get_world_background

            background = await get_world_background(
                db,
                options.novel_id,
                context_mode=options.context_mode,
                reveal_mode=options.reveal_mode,
                limit=160,
            )
            bundle.world_entities = [
                {
                    "id": item.asset_id,
                    "entry_id": item.entry_id,
                    "entity_type": item.asset_type,
                    "name": item.title,
                    "summary": item.summary,
                    "status": item.status,
                    "sensitivity": item.sensitivity,
                    "importance": item.importance,
                    "source_ids": item.source_ids,
                    "source_type": item.asset_type,
                    "source_ref": {"source_hash": item.source_hash},
                    "title": item.title,
                }
                for item in background.entries
            ]
            bundle.budget_used["core_entities"] = len(bundle.world_entities)
            return
        related_candidates = _related_entity_candidates(options, bundle)
        related_ids = [entity_id for entity_id, _reason in related_candidates]

        if related_ids:
            if len(related_ids) > all_limit:
                bundle.warnings.append(
                    f"世界对象候选超过 Top-{all_limit}，已按作者显式选择、Scene、"
                    "剧情线和检索证据的顺序裁剪"
                )
            limited_ids = related_ids[:all_limit]
            ctx = await self._get_world_context(
                db,
                options.novel_id,
                entity_ids=limited_ids,
                reveal_mode=options.reveal_mode,
                limit=all_limit,
                current_chapter=options.visible_until_chapter or options.chapter_index,
                include_review=options.include_pending_objects,
            )
            raw_entities = [_entity_dict(e) for e in ctx.entities] if ctx else []
            entities = _filter_world_entities(
                raw_entities,
                include_pending_objects=options.include_pending_objects,
            )
            if generation_action:
                entities = [
                    item for item in entities if item.get("entity_type") != "character"
                ]
            rank = {item: index for index, item in enumerate(limited_ids)}
            entities.sort(
                key=lambda item: rank.get(
                    str(item.get("entity_id") or item.get("id") or ""),
                    len(rank),
                )
            )
            bundle.world_entities = entities[:all_limit]
            bundle.budget_used["core_entities"] = min(len(entities), core_limit)
            bundle.budget_used["normal_entities"] = max(0, len(entities) - core_limit)
        elif options.consumer_action == "outline.analyze":
            # Manual outline analysis is about the confirmed range. Loading
            # globally important objects when that range has no real relation
            # would add unrelated lore and consume the author's prompt budget.
            bundle.world_entities = []
            bundle.budget_used["core_entities"] = 0
            bundle.budget_used["normal_entities"] = 0
        else:
            ctx = await self._get_world_context(
                db,
                options.novel_id,
                reveal_mode=options.reveal_mode,
                limit=core_limit + normal_limit,
                current_chapter=options.visible_until_chapter or options.chapter_index,
                include_review=options.include_pending_objects,
            )
            raw_entities = [_entity_dict(e) for e in ctx.entities] if ctx else []
            entities = _filter_world_entities(
                raw_entities,
                include_pending_objects=options.include_pending_objects,
            )
            if generation_action:
                entities = [
                    item for item in entities if item.get("entity_type") != "character"
                ]
            entities.sort(key=lambda e: e.get("importance", 0.0), reverse=True)

            core_entities = [
                e
                for e in entities
                if e.get("importance_level") == "core" or e.get("importance", 0.0) >= 0.75
            ][:core_limit]
            normal_entities = [e for e in entities if e not in core_entities][
                :normal_limit
            ]

            bundle.world_entities = core_entities + normal_entities
            bundle.budget_used["core_entities"] = len(core_entities)
            bundle.budget_used["normal_entities"] = len(normal_entities)

        if (
            options.scope == "generation_center"
            or options.consumer_action == "outline.analyze"
        ):
            actual_ids = [
                str(item.get("entity_id") or item.get("id") or "")
                for item in bundle.world_entities
                if item.get("entity_id") or item.get("id")
            ]
            if related_candidates:
                trace_candidates = related_candidates
                selected_candidates = related_candidates[:all_limit]
            else:
                trace_candidates = [(item_id, "importance") for item_id in actual_ids]
                selected_candidates = trace_candidates
            bundle.selection_trace["world_entities"] = _selection_trace(
                trace_candidates,
                selected_candidates,
                actual_ids,
                top_k=all_limit,
            )

        if any(
            entity.get("display_state") == "review" for entity in bundle.world_entities
        ):
            bundle.warnings.append("上下文包含未采用的世界对象")

        # Reveal 过滤
        if options.reveal_mode == "author_safe":
            for ent in bundle.world_entities:
                if ent.get("hidden_truth"):
                    ent["hidden_truth"] = f"{AUTHOR_ONLY_WARNING} {ent['hidden_truth']}"
        if options.reveal_mode in {"reader", "character"}:
            await self._apply_reader_visibility(db, options, bundle)

    async def _apply_reader_visibility(
        self,
        db: AsyncSession,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> None:
        from modules.outline.facade import get_reader_reveal_decision

        cutoff = options.visible_until_chapter or options.chapter_index
        if cutoff is None:
            bundle.world_entities = []
            bundle.warnings.append("读者/角色视角缺少截止章，已保守排除世界对象")
            return
        visible: list[dict] = []
        for item in bundle.world_entities:
            if item.get("status") != "canonical":
                continue
            decision = await get_reader_reveal_decision(
                db,
                novel_id=options.novel_id,
                target_type=(
                    "character" if item.get("entity_type") == "character" else "entity"
                ),
                target_id=str(item.get("entity_id") or item.get("id") or ""),
                cutoff_chapter=cutoff,
            )
            redacted = dict(item)
            redacted["hidden_truth"] = None
            if decision.has_policy:
                redacted["reader_reveal_content"] = decision.reveal_content
                if not decision.revealed:
                    redacted["summary"] = None
            else:
                # `summary` is an author-facing synopsis. Without an explicit
                # reveal policy only the public baseline is safe for readers.
                redacted["summary"] = redacted.get("public_info")
            visible.append(redacted)
        bundle.world_entities = visible


def _related_entity_candidates(
    options: CompileOptions,
    bundle: StructureContextBundle,
) -> list[tuple[str, str]]:
    """Rank explicit and current-writing references before applying Top-K."""
    ranked: list[tuple[str, str]] = []
    seen: set[str] = set()

    def extend(values: object, reason: str) -> None:
        if not isinstance(values, list | tuple | set):
            return
        for value in values:
            entity_id = str(value or "").strip()
            if entity_id and entity_id not in seen:
                seen.add(entity_id)
                ranked.append((entity_id, reason))

    extend(options.entity_ids, "explicit_or_source")
    analysis = (
        bundle.outline_analysis
        if isinstance(bundle.outline_analysis, dict)
        else {}
    )
    extend(analysis.get("related_entity_ids"), "outline_range")
    scene = bundle.scene if isinstance(bundle.scene, dict) else {}
    scene_meta = scene.get("structure_meta") or {}
    if isinstance(scene_meta, dict):
        extend(scene_meta.get("related_entity_ids"), "scene")
    arc = bundle.outline_arc if isinstance(bundle.outline_arc, dict) else {}
    extend(arc.get("related_entity_ids"), "arc")
    for thread in bundle.plot_threads:
        if isinstance(thread, dict):
            extend(thread.get("related_entity_ids"), "plot_thread")
    for chunk in bundle.rag_chunks:
        if isinstance(chunk, dict):
            extend(chunk.get("entity_ids"), "rag")
    return ranked


def _related_entity_ids(
    options: CompileOptions,
    bundle: StructureContextBundle,
) -> list[str]:
    """Compatibility wrapper for callers that only need ranked IDs."""
    return [
        entity_id for entity_id, _reason in _related_entity_candidates(options, bundle)
    ]


def _selection_trace(
    candidates: list[tuple[str, str]],
    selected: list[tuple[str, str]],
    actual_ids: list[str],
    *,
    top_k: int,
) -> dict[str, object]:
    actual = set(actual_ids)
    selected_ids = {item_id for item_id, _reason in selected}
    included = [
        {"id": item_id, "reason": reason}
        for item_id, reason in selected
        if item_id in actual
    ]
    excluded = [
        {
            "id": item_id,
            "reason": reason,
            "exclusion_reason": "not_loaded" if item_id in selected_ids else "top_k",
        }
        for item_id, reason in candidates
        if item_id not in actual
    ]
    return {"top_k": top_k, "included": included, "excluded": excluded}
