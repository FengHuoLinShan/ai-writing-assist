"""Hidden guard material for character reveal validation.

Guard terms derive from the frozen compile's own sources (authoritative scope)
instead of re-querying the world with arbitrary limits. The literal guard stays
a deterministic first layer; synonym/implicit spoilers belong to the semantic
audit (ADR-0025).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.evidence.compilation.contracts import ConfirmedAIActionContext


@dataclass(frozen=True)
class HiddenGuardTerm:
    phrase: str
    rule: str
    severity: str
    source_type: str
    source_id: str
    source_label: str


class HiddenGuardBuilder:
    """Build deterministic validation terms outside the generation prompt."""

    async def build(
        self,
        db: AsyncSession,
        confirmed_context: ConfirmedAIActionContext,
    ) -> list[HiddenGuardTerm]:
        options = dict(confirmed_context.compile_options or {})
        character_id = options.get("viewpoint_character_id")
        if not character_id:
            return []

        novel_id = confirmed_context.confirmation.novel_id
        entity_ids, relation_ids = self._collect_frozen_targets(confirmed_context)
        knowledge_by_id = await self._knowledge_by_target(
            db,
            novel_id=novel_id,
            character_id=str(character_id),
            entity_ids=entity_ids,
            relation_ids=relation_ids,
            visible_until_chapter=options.get("visible_until_chapter"),
        )

        from modules.world.facade import get_hidden_guard_sources

        entities, relations = await get_hidden_guard_sources(
            db,
            novel_id=novel_id,
            entity_ids=entity_ids,
            relation_ids=relation_ids,
        )
        terms: list[HiddenGuardTerm] = [
            *self._world_hidden_terms(entities, knowledge_by_id),
            *self._relation_hidden_terms(relations, knowledge_by_id),
        ]
        terms.extend(self._director_terms(confirmed_context, options))
        return self._dedupe_terms(terms)

    @staticmethod
    def _collect_frozen_targets(
        confirmed_context: ConfirmedAIActionContext,
    ) -> tuple[list[str], list[str]]:
        """Enumerate guard targets from the frozen compile's own sources.

        The compile is the authoritative frozen scope, so every world entity or
        relation it referenced is guarded — no arbitrary limit and no second
        unbounded world query.
        """
        entity_ids: dict[str, str] = {}
        relation_ids: set[str] = set()
        for section in confirmed_context.compiled.sections:
            for source in section.sources:
                source_type = str(source.get("type") or "")
                source_id = str(source.get("id") or "")
                if not source_id or not _is_uuid(source_id):
                    continue
                if source_type in {
                    "entity",
                    "world_entity",
                    "character",
                    "item",
                    "location",
                    "faction",
                    "event",
                }:
                    entity_ids.setdefault(source_id, str(source.get("label") or ""))
                elif source_type in {"relation", "entity_relation"}:
                    relation_ids.add(source_id)
        return sorted(entity_ids), sorted(relation_ids)

    @staticmethod
    async def _knowledge_by_target(
        db: AsyncSession,
        *,
        novel_id: str,
        character_id: str,
        entity_ids: list[str],
        relation_ids: list[str],
        visible_until_chapter: int | None,
    ) -> dict[str, Any]:
        from modules.world.facade import get_character_knowledge_context

        target_ids = sorted(set(entity_ids) | set(relation_ids))
        valid_ids = [str(item) for item in target_ids if _is_uuid(item)]
        if not valid_ids:
            return {}
        knowledge = await get_character_knowledge_context(
            db,
            novel_id,
            character_id,
            target_ids=valid_ids,
            visible_until_chapter=(
                int(visible_until_chapter) if visible_until_chapter is not None else None
            ),
        )
        return {str(item.target_id): item for item in knowledge or []}

    @staticmethod
    def _world_hidden_terms(
        entities: list[Any],
        knowledge_by_id: dict[str, Any],
    ) -> list[HiddenGuardTerm]:
        terms: list[HiddenGuardTerm] = []
        for entity in entities:
            entity_id = str(entity.entity_id)
            record = knowledge_by_id.get(entity_id)
            if getattr(record, "knowledge_level", None) == "full":
                continue
            for phrase in _guard_phrases(entity.hidden_truth):
                terms.append(
                    HiddenGuardTerm(
                        phrase=phrase,
                        rule="hidden_truth_match",
                        severity="error",
                        source_type="core_entity",
                        source_id=entity_id,
                        source_label=str(entity.name or "已过滤的隐藏事实"),
                    )
                )
        return terms

    @staticmethod
    def _relation_hidden_terms(
        relations: list[Any],
        knowledge_by_id: dict[str, Any],
    ) -> list[HiddenGuardTerm]:
        terms: list[HiddenGuardTerm] = []
        for rel in relations:
            record = knowledge_by_id.get(str(rel.relation_id))
            if getattr(record, "knowledge_level", None) == "full":
                continue
            if not rel.description:
                continue
            for phrase in _guard_phrases(rel.description):
                terms.append(
                    HiddenGuardTerm(
                        phrase=phrase,
                        rule="hidden_relation_match",
                        severity="warning",
                        source_type="entity_relation",
                        source_id=str(rel.relation_id),
                        source_label="已过滤的隐藏关系",
                    )
                )
        return terms

    @staticmethod
    def _director_terms(
        confirmed_context: ConfirmedAIActionContext,
        options: dict[str, Any],
    ) -> list[HiddenGuardTerm]:
        scene_id = str(options.get("scene_id") or "scene_director_constraints")
        terms: list[HiddenGuardTerm] = []
        for section in confirmed_context.compiled.sections:
            if section.key != "scene_director_constraints":
                continue
            for line in section.content.splitlines():
                text = line.strip()
                if not text.startswith("- "):
                    continue
                _, _, value = text.partition(":")
                for phrase in _guard_phrases(value or text[2:]):
                    terms.append(
                        HiddenGuardTerm(
                            phrase=phrase,
                            rule="director_constraint_as_character_knowledge",
                            severity="warning",
                            source_type="scene_director_constraints",
                            source_id=scene_id,
                            source_label="导演约束",
                        )
                    )
        return terms

    @staticmethod
    def _dedupe_terms(terms: list[HiddenGuardTerm]) -> list[HiddenGuardTerm]:
        seen: set[tuple[str, str, str]] = set()
        result: list[HiddenGuardTerm] = []
        for term in terms:
            key = (term.phrase, term.rule, term.source_id)
            if key in seen:
                continue
            seen.add(key)
            result.append(term)
        return result


def _is_uuid(value: object) -> bool:
    import uuid as uuid_module

    try:
        uuid_module.UUID(hex=str(value))
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def _guard_phrases(value: str | None) -> list[str]:
    if not value:
        return []
    text = " ".join(str(value).split())
    pieces = [text]
    for separator in ("。", "！", "？", "；", ";", "\n"):
        next_pieces: list[str] = []
        for piece in pieces:
            next_pieces.extend(piece.split(separator))
        pieces = next_pieces
    result: list[str] = []
    for piece in pieces:
        phrase = piece.strip(" ：:，,。")
        if len(phrase) >= 4:
            result.append(phrase)
    return result or ([text] if len(text) >= 4 else [])
