"""Hidden guard material for character reveal validation."""

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
        novel_id = confirmed_context.confirmation.novel_id
        character_id = options.get("viewpoint_character_id")
        if not character_id:
            return []

        terms: list[HiddenGuardTerm] = []
        terms.extend(
            await self._world_hidden_terms(
                db,
                novel_id=novel_id,
                character_id=character_id,
            )
        )
        terms.extend(
            await self._relation_hidden_terms(
                db,
                novel_id=novel_id,
                character_id=character_id,
            )
        )
        terms.extend(self._director_terms(confirmed_context, options))
        return self._dedupe_terms(terms)

    async def _world_hidden_terms(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        character_id: str,
    ) -> list[HiddenGuardTerm]:
        from modules.world.facade import (
            get_character_knowledge_context,
            get_world_context,
        )

        world = await get_world_context(
            db,
            novel_id,
            reveal_mode="author_full",
            limit=100,
        )
        entities = [
            item.model_dump() if hasattr(item, "model_dump") else dict(item)
            for item in (world.entities if world else [])
        ]
        target_ids = [str(item.get("entity_id") or item.get("id")) for item in entities]
        knowledge = await get_character_knowledge_context(
            db,
            novel_id,
            character_id,
            target_ids=[item for item in target_ids if item],
        )
        knowledge_by_id = {str(item.target_id): item for item in knowledge or []}

        terms: list[HiddenGuardTerm] = []
        for item in entities:
            entity_id = str(item.get("entity_id") or item.get("id") or "")
            if not entity_id:
                continue
            record = knowledge_by_id.get(entity_id)
            if getattr(record, "knowledge_level", None) == "full":
                continue
            hidden_truth = item.get("hidden_truth")
            if not hidden_truth:
                continue
            for phrase in _guard_phrases(hidden_truth):
                terms.append(
                    HiddenGuardTerm(
                        phrase=phrase,
                        rule="hidden_truth_match",
                        severity="error",
                        source_type="core_entity",
                        source_id=entity_id,
                        source_label=str(item.get("name") or "已过滤的隐藏事实"),
                    )
                )
        return terms

    async def _relation_hidden_terms(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        character_id: str,
    ) -> list[HiddenGuardTerm]:
        from modules.world.facade import (
            get_character_knowledge_context,
            get_entity_relations,
        )

        relations, _total = await get_entity_relations(db, novel_id, skip=0, limit=200)
        relation_ids = [str(item.id) for item in relations or []]
        knowledge = await get_character_knowledge_context(
            db,
            novel_id,
            character_id,
            target_ids=relation_ids,
        )
        knowledge_by_id = {str(item.target_id): item for item in knowledge or []}

        terms: list[HiddenGuardTerm] = []
        for rel in relations or []:
            record = knowledge_by_id.get(str(rel.id))
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
                        source_id=str(rel.id),
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
