"""P20 v2 context preparation for current-layer outline creation."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.context import facade as context_facade
from modules.context.contracts import ConfirmedAIActionContext
from modules.outline.models import (
    ForeshadowingPlan,
    OutlineArc,
    PlotThread,
    RevealPlan,
    Scene,
)
from modules.outline.p20_schemas import OutlineLayerGenerateRequest
from modules.outline.story_outline_service import StoryOutlineService
from modules.world.facade import (
    get_characters_context,
    get_world_context,
    list_characters,
    list_entities,
)

P20_CONTEXT_VERSION = "outline-layer-context-v2"
P20_CHARACTER_TOP_K = 6
P20_ENTITY_TOP_K = 16
P20_CHARACTER_PAGE_SIZE = 50
_TEXT_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]+|[a-z0-9]+", re.IGNORECASE)


def stable_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def serialize_untrusted_json(value: Any) -> str:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )


@dataclass(frozen=True)
class P20GenerationPlan:
    request: OutlineLayerGenerateRequest
    context: dict[str, Any]
    reference_map: dict[str, dict[str, str]]
    context_provenance: dict[str, Any]
    source_fingerprint: str
    confirmed_context: ConfirmedAIActionContext | None = None


class P20ContextBuilder:
    """Freeze the exact P20 provider input and its novel-scoped references."""

    async def prepare(
        self,
        db: AsyncSession,
        data: OutlineLayerGenerateRequest,
        *,
        confirmed_context: ConfirmedAIActionContext | None = None,
    ) -> P20GenerationPlan:
        confirmed = confirmed_context
        if confirmed is None:
            confirmed = await context_facade.prepare_confirmed_ai_action(
                db,
                novel_id=data.novel_id,
                action="outline.generate",
                confirmation_id=data.context_confirmation_id,
            )
        else:
            confirmation = confirmed.confirmation
            if (
                str(confirmation.novel_id) != data.novel_id
                or confirmation.action != "outline.generate"
                or str(confirmation.id) != data.context_confirmation_id
            ):
                raise ValueError("confirmed P20 context does not match the request")
        if confirmed.compile_options.get("budget_tokens") != 0:
            raise ValueError(
                "P20 v2 requires a no-eviction context confirmation; "
                "review the references and submit again"
            )

        current_outline = await StoryOutlineService().get_current(db, data.novel_id)
        if current_outline.revision is None:
            raise ValueError(
                "AI 大纲分层创作需要当前小说总纲；请先在小说总纲页创建并采用总纲"
            )

        nid = current_outline.revision.novel_id
        threads = list(
            (
                await db.scalars(
                    select(PlotThread)
                    .where(PlotThread.novel_id == nid, PlotThread.status != "deprecated")
                    .order_by(
                        PlotThread.start_chapter,
                        PlotThread.name,
                        PlotThread.id,
                    )
                )
            ).all()
        )
        arcs = list(
            (
                await db.scalars(
                    select(OutlineArc)
                    .where(OutlineArc.novel_id == nid, OutlineArc.status != "deprecated")
                    .order_by(OutlineArc.arc_index, OutlineArc.id)
                )
            ).all()
        )
        scenes = list(
            (
                await db.scalars(
                    select(Scene)
                    .where(Scene.novel_id == nid, Scene.status != "deprecated")
                    .order_by(Scene.scene_index, Scene.id)
                )
            ).all()
        )
        foreshadowing = list(
            (
                await db.scalars(
                    select(ForeshadowingPlan)
                    .where(
                        ForeshadowingPlan.novel_id == nid,
                        ForeshadowingPlan.status != "deprecated",
                    )
                    .order_by(
                        ForeshadowingPlan.planned_seed_chapter,
                        ForeshadowingPlan.id,
                    )
                )
            ).all()
        )
        reveals = list(
            (
                await db.scalars(
                    select(RevealPlan)
                    .where(RevealPlan.novel_id == nid, RevealPlan.status != "deprecated")
                    .order_by(RevealPlan.created_at, RevealPlan.id)
                )
            ).all()
        )

        refs = {
            "threads": self._ref_map("T", [str(item.id) for item in threads]),
            "arcs": self._ref_map("A", [str(item.id) for item in arcs]),
            "scenes": self._ref_map("S", [str(item.id) for item in scenes]),
        }
        reverse_refs = {
            key: {asset_id: ref for ref, asset_id in mapping.items()}
            for key, mapping in refs.items()
        }
        self._require_selected_assets(data, reverse_refs)

        outline_payload = current_outline.revision.model_dump(mode="json")
        relevance_text = serialize_untrusted_json(
            {
                "author_instruction": data.instruction,
                "creative_core": outline_payload["creative_core"],
                "major_storylines": outline_payload["major_storylines"],
                "macro_movements": outline_payload["macro_movements"],
                "open_decisions": outline_payload["open_decisions"],
            }
        )
        characters, entities, people_refs, entity_refs, selection_meta = (
            await self._world_context(
                db,
                data,
                confirmed.compile_options,
                threads=threads,
                arcs=arcs,
                scenes=scenes,
                relevance_text=relevance_text,
            )
        )
        refs["characters"] = people_refs
        refs["entities"] = entity_refs
        reverse_refs["characters"] = {
            asset_id: ref for ref, asset_id in people_refs.items()
        }
        reverse_refs["entities"] = {
            asset_id: ref for ref, asset_id in entity_refs.items()
        }

        selected_thread_ids = set(data.selected_thread_ids)
        selected_arc_ids = set(data.selected_arc_ids)
        selected_scene_ids = set(data.selected_scene_ids)
        context = {
            "contract_version": P20_CONTEXT_VERSION,
            "target": data.target,
            "mode": data.mode,
            "author_instruction": data.instruction,
            "requested_chapter_range": {
                "start": data.start_chapter,
                "end": data.end_chapter,
            },
            "structure_coverage": self._structure_coverage(scenes),
            "story_outline": {
                "revision_ref": "SO-CURRENT",
                "version_number": current_outline.revision.version_number,
                "title": current_outline.revision.title,
                "creative_core": outline_payload["creative_core"],
                "outline_markdown": current_outline.revision.outline_markdown,
                "major_storylines": outline_payload["major_storylines"],
                "macro_movements": outline_payload["macro_movements"],
                "open_decisions": outline_payload["open_decisions"],
                "content_hash": current_outline.revision.content_hash,
            },
            "confirmed_author_context": {
                "markdown": str(confirmed.rendered_markdown),
                "compile_options": dict(confirmed.compile_options),
                "selected_asset_ids": dict(
                    confirmed.confirmation.selected_asset_ids or {}
                ),
                "excluded_asset_ids": dict(
                    confirmed.confirmation.excluded_asset_ids or {}
                ),
                "warnings": list(confirmed.confirmation.warnings or []),
            },
            "plot_threads": [
                self._thread_card(
                    item,
                    reverse_refs,
                    selected=str(item.id) in selected_thread_ids,
                )
                for item in threads
            ],
            "outline_arcs": [
                self._arc_card(
                    item,
                    reverse_refs,
                    selected=str(item.id) in selected_arc_ids,
                )
                for item in arcs
            ],
            "scenes": [
                self._scene_card(
                    item,
                    reverse_refs,
                    selected=str(item.id) in selected_scene_ids,
                )
                for item in self._relevant_scenes(data, scenes)
            ],
            "information_progression": {
                "foreshadowing": [
                    self._foreshadow_card(item, reverse_refs)
                    for item in foreshadowing
                ],
                "reveals": [
                    self._reveal_card(item, reverse_refs) for item in reveals
                ],
            },
            "characters": characters,
            "world_entities": entities,
        }
        fingerprint_payload = {
            "request": data.model_dump(mode="json"),
            "context": context,
            "reference_map": refs,
        }
        fingerprint = stable_hash(fingerprint_payload)
        provenance = {
            "version": P20_CONTEXT_VERSION,
            "action": "outline.generate",
            "target": data.target,
            "mode": data.mode,
            "story_outline_revision_id": str(current_outline.current_revision_id),
            "story_outline_content_hash": current_outline.revision.content_hash,
            "context_confirmation_id": data.context_confirmation_id,
            "confirmed_context_hash": stable_hash(
                {
                    "markdown": str(confirmed.rendered_markdown),
                    "compiled": self._compiled_fingerprint(confirmed.compiled),
                }
            ),
            "included_asset_ids": {
                "plot_threads": [str(item.id) for item in threads],
                "outline_arcs": [str(item.id) for item in arcs],
                "scenes": [
                    str(item.id) for item in self._relevant_scenes(data, scenes)
                ],
                "foreshadowing_plans": [str(item.id) for item in foreshadowing],
                "reveal_plans": [str(item.id) for item in reveals],
                **selection_meta["included_asset_ids"],
            },
            "omitted_assets": selection_meta["omitted_assets"],
            "top_k": selection_meta["top_k"],
            "context_hash": fingerprint,
            "actual_input_chars": len(serialize_untrusted_json(context)),
            "input_budget_policy": "no_application_truncation",
        }
        return P20GenerationPlan(
            request=data,
            context=context,
            reference_map=refs,
            context_provenance=provenance,
            source_fingerprint=fingerprint,
            confirmed_context=confirmed,
        )

    async def _world_context(
        self,
        db: AsyncSession,
        data: OutlineLayerGenerateRequest,
        compile_options: dict[str, Any],
        *,
        threads: list[PlotThread],
        arcs: list[OutlineArc],
        scenes: list[Scene],
        relevance_text: str | None = None,
    ) -> tuple[
        list[dict[str, Any]],
        list[dict[str, Any]],
        dict[str, str],
        dict[str, str],
        dict[str, Any],
    ]:
        character_rows = await self._list_all_characters(db, data.novel_id)
        entity_rows = await list_entities(
            db,
            data.novel_id,
            statuses=("canonical",),
            limit=1000,
        )

        explicit_characters = {
            str(value) for value in (compile_options.get("character_ids") or [])
        }
        explicit_entities = {
            str(value) for value in (compile_options.get("entity_ids") or [])
        }
        related_characters: set[str] = set()
        related_entities: set[str] = set()
        for item in [*threads, *arcs]:
            related_characters.update(
                str(value) for value in item.related_character_ids or []
            )
            related_entities.update(str(value) for value in item.related_entity_ids or [])
        for item in scenes:
            if item.pov_character_id:
                related_characters.add(str(item.pov_character_id))
            meta = dict(item.structure_meta or {})
            related_characters.update(
                str(value) for value in meta.get("related_character_ids") or []
            )
            related_entities.update(
                str(value) for value in meta.get("related_entity_ids") or []
            )

        relevance = relevance_text or data.instruction

        def rank(
            asset_id: str,
            name: str,
            asset: Any,
            related: set[str],
            explicit: set[str],
        ):
            direct_score = self._name_mention_score(name, relevance)
            scene_count, first_scene = self._scene_mention_stats(name, scenes)
            affinity = self._shared_ngram_score(
                relevance,
                self._asset_relevance_text(asset),
            )
            return (
                0 if asset_id in explicit else 1,
                0 if direct_score else 1,
                -direct_score,
                0 if scene_count else 1,
                -scene_count,
                first_scene,
                0 if asset_id in related else 1,
                -affinity,
                str(name or ""),
                asset_id,
            )

        ranked_characters = sorted(
            character_rows,
            key=lambda item: rank(
                str(item.entity_id),
                item.name,
                item,
                related_characters,
                explicit_characters,
            ),
        )
        ranked_entities = sorted(
            [
                item
                for item in entity_rows
                if str(item.get("entity_type") or "") != "character"
            ],
            key=lambda item: rank(
                str(item.get("id") or item.get("entity_id") or ""),
                str(item.get("name") or ""),
                item,
                related_entities,
                explicit_entities,
            ),
        )
        selected_character_rows = ranked_characters[:P20_CHARACTER_TOP_K]
        selected_entity_rows = ranked_entities[:P20_ENTITY_TOP_K]
        character_ids = [str(item.entity_id) for item in selected_character_rows]
        entity_ids = [
            str(item.get("id") or item.get("entity_id"))
            for item in selected_entity_rows
            if item.get("id") or item.get("entity_id")
        ]
        character_bundle = await get_characters_context(
            db,
            data.novel_id,
            character_ids,
            reveal_mode="author_safe",
        )
        entity_bundle = await get_world_context(
            db,
            data.novel_id,
            entity_ids=entity_ids,
            reveal_mode="author_safe",
            limit=max(len(entity_ids), 1),
        )
        people_refs = self._ref_map(
            "C",
            [str(item.character_id) for item in character_bundle.characters],
        )
        entity_refs = self._ref_map(
            "E",
            [str(item.entity_id) for item in entity_bundle.entities],
        )
        person_reverse = {value: key for key, value in people_refs.items()}
        entity_reverse = {value: key for key, value in entity_refs.items()}
        characters = []
        for item in character_bundle.characters:
            payload = item.model_dump(mode="json")
            payload.pop("character_id", None)
            characters.append(
                {"ref": person_reverse[str(item.character_id)], **payload}
            )
        entities = []
        for item in entity_bundle.entities:
            payload = item.model_dump(mode="json")
            payload.pop("entity_id", None)
            payload["related_entity_refs"] = [
                entity_reverse[value]
                for value in payload.pop("related_entity_ids", [])
                if value in entity_reverse
            ]
            entities.append({"ref": entity_reverse[str(item.entity_id)], **payload})
        return (
            characters,
            entities,
            people_refs,
            entity_refs,
            {
                "included_asset_ids": {
                    "characters": character_ids,
                    "entities": entity_ids,
                },
                "omitted_assets": [
                    *[
                        {
                            "type": "character",
                            "id": str(item.entity_id),
                            "reason": "character_top_k",
                        }
                        for item in ranked_characters[P20_CHARACTER_TOP_K:]
                    ],
                    *[
                        {
                            "type": "entity",
                            "id": str(item.get("id") or item.get("entity_id")),
                            "reason": "world_entity_top_k",
                        }
                        for item in ranked_entities[P20_ENTITY_TOP_K:]
                    ],
                ],
                "top_k": {
                    "characters": {
                        "limit": P20_CHARACTER_TOP_K,
                        "candidate_count": len(ranked_characters),
                        "reason": (
                            "explicit_then_instruction_outline_mention_then_scene_"
                            "then_structure_affinity"
                        ),
                    },
                    "world_entities": {
                        "limit": P20_ENTITY_TOP_K,
                        "candidate_count": len(ranked_entities),
                        "reason": (
                            "explicit_then_instruction_outline_mention_then_scene_"
                            "then_structure_affinity"
                        ),
                    },
                },
            },
        )

    @staticmethod
    async def _list_all_characters(
        db: AsyncSession,
        novel_id: str,
    ) -> list[Any]:
        rows: list[Any] = []
        total: int | None = None
        while total is None or len(rows) < total:
            page, reported_total = await list_characters(
                db,
                novel_id,
                skip=len(rows),
                limit=P20_CHARACTER_PAGE_SIZE,
            )
            total = int(reported_total)
            if not page:
                break
            rows.extend(page)
        return rows

    @staticmethod
    def _normalized_text(value: Any) -> str:
        return "".join(_TEXT_TOKEN_RE.findall(str(value or "").casefold()))

    @classmethod
    def _name_mention_score(cls, name: str, text: str) -> int:
        normalized_name = cls._normalized_text(name)
        normalized_text = cls._normalized_text(text)
        if not normalized_name or not normalized_text:
            return 0
        if normalized_name in normalized_text:
            return len(normalized_name)
        variants = [
            cls._normalized_text(part)
            for part in _TEXT_TOKEN_RE.findall(str(name or "").casefold())
        ]
        direct = [
            len(part)
            for part in variants
            if len(part) >= 2 and part in normalized_text
        ]
        if direct:
            return max(direct)
        # Long compound entity names often contain connective words not used by
        # the author (for example “安提哥努斯家族笔记” vs “安提哥努斯笔记”).
        # A shared run of at least three characters is still a direct mention;
        # two-character thematic overlap is left to the weaker affinity score.
        for width in range(min(8, len(normalized_name)), 2, -1):
            if any(
                normalized_name[index : index + width] in normalized_text
                for index in range(len(normalized_name) - width + 1)
            ):
                return width
        return 0

    @classmethod
    def _scene_mention_stats(
        cls,
        name: str,
        scenes: list[Scene],
    ) -> tuple[int, int]:
        variants = [
            cls._normalized_text(part)
            for part in _TEXT_TOKEN_RE.findall(str(name or "").casefold())
            if len(cls._normalized_text(part)) >= 2
        ]
        if not variants:
            return 0, 10**9
        count = 0
        first_scene = 10**9
        for scene in scenes:
            text = cls._normalized_text(
                " ".join(
                    str(value or "")
                    for value in (
                        getattr(scene, "title", None),
                        getattr(scene, "goal", None),
                        getattr(scene, "core_conflict", None),
                        getattr(scene, "emotional_beat", None),
                        getattr(scene, "must_happen", None),
                        getattr(scene, "must_not_happen", None),
                        json.dumps(
                            dict(getattr(scene, "structure_meta", None) or {}),
                            ensure_ascii=False,
                            default=str,
                        ),
                    )
                )
            )
            if any(variant in text for variant in variants):
                count += 1
                first_scene = min(
                    first_scene,
                    int(getattr(scene, "scene_index", 10**9) or 10**9),
                )
        return count, first_scene

    @staticmethod
    def _asset_relevance_text(asset: Any) -> str:
        raw = asset if isinstance(asset, dict) else vars(asset)
        allowed = {
            "name",
            "aliases",
            "entity_type",
            "role",
            "summary",
            "public_info",
            "importance",
            "desire",
            "fear",
            "secret",
            "current_goal",
            "current_state",
            "relationship_summary",
            "meta",
            "content_json",
        }
        return json.dumps(
            {key: value for key, value in raw.items() if key in allowed},
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )

    @classmethod
    def _shared_ngram_score(cls, left: str, right: str) -> int:
        def ngrams(value: str) -> set[str]:
            result: set[str] = set()
            for token in _TEXT_TOKEN_RE.findall(str(value or "").casefold()):
                compact = cls._normalized_text(token)
                for width in range(2, min(6, len(compact)) + 1):
                    result.update(
                        compact[index : index + width]
                        for index in range(len(compact) - width + 1)
                    )
            return result

        overlap = ngrams(left) & ngrams(right)
        return sum(len(value) ** 2 for value in overlap)

    @staticmethod
    def _ref_map(prefix: str, asset_ids: list[str]) -> dict[str, str]:
        return {
            f"{prefix}{index:03d}": asset_id
            for index, asset_id in enumerate(asset_ids, start=1)
        }

    @staticmethod
    def _require_selected_assets(
        data: OutlineLayerGenerateRequest,
        reverse_refs: dict[str, dict[str, str]],
    ) -> None:
        selected = {
            "threads": data.selected_thread_ids,
            "arcs": data.selected_arc_ids,
            "scenes": data.selected_scene_ids,
        }
        for key, asset_ids in selected.items():
            missing = [value for value in asset_ids if value not in reverse_refs[key]]
            if missing:
                raise ValueError(f"selected {key} must be active assets in this novel")

    @staticmethod
    def _thread_card(
        item: PlotThread,
        reverse: dict[str, dict[str, str]],
        *,
        selected: bool,
    ) -> dict[str, Any]:
        return {
            "ref": reverse["threads"][str(item.id)],
            "selected_for_revision": selected,
            "name": item.name,
            "thread_type": item.thread_type,
            "summary": item.summary,
            "visible_goal": item.visible_goal,
            "hidden_truth": item.hidden_truth,
            "start_chapter": item.start_chapter,
            "planned_payoff_chapter": item.planned_payoff_chapter,
            "current_stage": item.current_stage,
            "related_character_refs": P20ContextBuilder._resolve_refs(
                item.related_character_ids,
                reverse.get("characters", {}),
            ),
            "related_entity_refs": P20ContextBuilder._resolve_refs(
                item.related_entity_ids,
                reverse.get("entities", {}),
            ),
            "reader_known_state": item.reader_known_state,
            "author_known_state": item.author_known_state,
            "information_movements": dict(item.provenance_meta or {}).get(
                "information_movements",
                [],
            ),
            "content_fingerprint": stable_hash(P20ContextBuilder._asset_snapshot(item)),
        }

    @staticmethod
    def _arc_card(
        item: OutlineArc,
        reverse: dict[str, dict[str, str]],
        *,
        selected: bool,
    ) -> dict[str, Any]:
        return {
            "ref": reverse["arcs"][str(item.id)],
            "selected_for_revision": selected,
            "title": item.title,
            "arc_index": item.arc_index,
            "start_chapter": item.start_chapter,
            "end_chapter": item.end_chapter,
            "arc_goal": item.arc_goal,
            "core_conflict": item.core_conflict,
            "main_opposition": item.main_opposition,
            "entry_hook": item.entry_hook,
            "midpoint_turn": item.midpoint_turn,
            "climax": item.climax,
            "result": item.result,
            "next_hook": item.next_hook,
            "related_thread_refs": P20ContextBuilder._resolve_refs(
                item.related_thread_ids,
                reverse["threads"],
            ),
            "related_character_refs": P20ContextBuilder._resolve_refs(
                item.related_character_ids,
                reverse.get("characters", {}),
            ),
            "related_entity_refs": P20ContextBuilder._resolve_refs(
                item.related_entity_ids,
                reverse.get("entities", {}),
            ),
            "content_fingerprint": stable_hash(P20ContextBuilder._asset_snapshot(item)),
        }

    @staticmethod
    def _scene_card(
        item: Scene,
        reverse: dict[str, dict[str, str]],
        *,
        selected: bool,
    ) -> dict[str, Any]:
        meta = dict(item.structure_meta or {})
        return {
            "ref": reverse["scenes"][str(item.id)],
            "selected_for_revision": selected,
            "scene_index": item.scene_index,
            "title": item.title,
            "goal": item.goal,
            "core_conflict": item.core_conflict,
            "emotional_beat": item.emotional_beat,
            "must_happen": item.must_happen,
            "must_not_happen": item.must_not_happen,
            "narrative_tag": item.narrative_tag,
            "narrative_function": meta.get("narrative_function"),
            "semantic_field_statuses": meta.get("semantic_field_statuses", {}),
            "parent_arc_ref": reverse["arcs"].get(
                str(meta.get("parent_outline_arc_id") or "")
            ),
            "planned_chapter_range": meta.get("planned_chapter_range"),
            "planning_state": meta.get("planning_state", "materialized"),
            "related_thread_refs": P20ContextBuilder._resolve_refs(
                meta.get("related_thread_ids"),
                reverse["threads"],
            ),
            "pov_character_ref": reverse.get("characters", {}).get(
                str(item.pov_character_id or "")
            ),
            "locked_prose_mapping": {
                "has_mapping": bool(item.scene_chunks or item.chapter_ids),
                "mapped_chapter_range": P20ContextBuilder._mapped_chapter_range(item),
                "llm_may_modify": False,
            },
            "content_fingerprint": stable_hash(P20ContextBuilder._asset_snapshot(item)),
        }

    @staticmethod
    def _structure_coverage(scenes: list[Scene]) -> dict[str, Any]:
        mapped_indices: list[int] = []
        materialized_scene_count = 0
        planned_scene_count = 0
        for scene in scenes:
            meta = dict(scene.structure_meta or {})
            planning_state = meta.get("planning_state", "materialized")
            if planning_state == "planned" and not (
                scene.scene_chunks or scene.chapter_ids
            ):
                planned_scene_count += 1
                continue
            materialized_scene_count += 1
            mapped = P20ContextBuilder._mapped_chapter_range(scene)
            if mapped:
                mapped_indices.extend([mapped["start"], mapped["end"]])
        return {
            "materialized_scene_count": materialized_scene_count,
            "planned_scene_count": planned_scene_count,
            "materialized_chapter_range": (
                {"start": min(mapped_indices), "end": max(mapped_indices)}
                if mapped_indices
                else None
            ),
            "rule": (
                "Within the materialized range, candidate events and chapter hints "
                "must describe supplied evidence rather than invent unwritten events."
            ),
        }

    @staticmethod
    def _foreshadow_card(
        item: ForeshadowingPlan,
        reverse: dict[str, dict[str, str]],
    ) -> dict[str, Any]:
        meta = dict(item.provenance_meta or {})
        return {
            "ref": f"F-{str(item.id)[:8]}",
            "name": item.name,
            "summary": item.summary,
            "surface_meaning": item.surface_meaning,
            "hidden_meaning": item.hidden_meaning,
            "planned_seed_chapter": item.planned_seed_chapter,
            "planned_reinforce_chapters": item.planned_reinforce_chapters or [],
            "planned_payoff_chapter": item.planned_payoff_chapter,
            "related_thread_refs": P20ContextBuilder._resolve_refs(
                item.related_thread_ids,
                reverse["threads"],
            ),
            "information_movement_id": meta.get("information_movement_id"),
        }

    @staticmethod
    def _reveal_card(
        item: RevealPlan,
        reverse: dict[str, dict[str, str]],
    ) -> dict[str, Any]:
        meta = dict(item.provenance_meta or {})
        return {
            "ref": f"R-{str(item.id)[:8]}",
            "target_ref": (
                reverse.get("characters", {}).get(str(item.target_id))
                or reverse.get("entities", {}).get(str(item.target_id))
            ),
            "secret_summary": item.secret_summary,
            "reveal_stages": item.reveal_stages or [],
            "related_thread_refs": P20ContextBuilder._resolve_refs(
                item.related_thread_ids,
                reverse["threads"],
            ),
            "information_movement_id": meta.get("information_movement_id"),
        }

    @staticmethod
    def _resolve_refs(
        values: list[Any] | None,
        reverse: dict[str, str],
    ) -> list[str]:
        return [
            reverse[str(value)] for value in values or [] if str(value) in reverse
        ]

    @staticmethod
    def _relevant_scenes(
        data: OutlineLayerGenerateRequest,
        scenes: list[Scene],
    ) -> list[Scene]:
        if data.target == "planned_scene" or data.selected_scene_ids:
            if data.start_chapter is None and data.end_chapter is None:
                return scenes
            start = data.start_chapter or data.end_chapter
            end = data.end_chapter or data.start_chapter
            selected = set(data.selected_scene_ids)
            return [
                item
                for item in scenes
                if str(item.id) in selected
                or P20ContextBuilder._scene_overlaps(item, start, end)
            ]
        return scenes

    @staticmethod
    def _scene_overlaps(
        scene: Scene,
        start: int | None,
        end: int | None,
    ) -> bool:
        if start is None or end is None:
            return True
        meta_range = dict(scene.structure_meta or {}).get("planned_chapter_range") or {}
        indices: list[int] = []
        for value in [meta_range.get("start"), meta_range.get("end")]:
            if isinstance(value, int):
                indices.append(value)
        for value in scene.chapter_ids or []:
            try:
                indices.append(int(value))
            except (TypeError, ValueError):
                continue
        for chunk in scene.scene_chunks or []:
            if not isinstance(chunk, dict):
                continue
            try:
                indices.append(int(chunk.get("chapter_index")))
            except (TypeError, ValueError):
                continue
        return bool(indices) and min(indices) <= end and max(indices) >= start

    @staticmethod
    def _mapped_chapter_range(scene: Scene) -> dict[str, int] | None:
        indices: list[int] = []
        for value in scene.chapter_ids or []:
            try:
                indices.append(int(value))
            except (TypeError, ValueError):
                continue
        for chunk in scene.scene_chunks or []:
            if not isinstance(chunk, dict):
                continue
            try:
                indices.append(int(chunk.get("chapter_index")))
            except (TypeError, ValueError):
                continue
        if not indices:
            return None
        return {"start": min(indices), "end": max(indices)}

    @staticmethod
    def _asset_snapshot(item: Any) -> dict[str, Any]:
        return {
            key: value
            for key, value in vars(item).items()
            if not key.startswith("_") and key not in {"created_at"}
        }

    @staticmethod
    def _compiled_fingerprint(compiled: Any) -> list[dict[str, Any]]:
        return [
            {
                "key": section.key,
                "content": section.content,
                "sources": list(section.sources or []),
                "excluded": section.excluded,
                "truncated_reason": section.truncated_reason,
            }
            for section in compiled.sections
        ]
