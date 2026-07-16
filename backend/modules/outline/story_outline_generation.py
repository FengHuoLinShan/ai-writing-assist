from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.agent_step_harness import (
    AgentPermissionLevel,
    ContextBudget,
    run_managed_structured,
)
from infrastructure.llm.client import LLMClient
from infrastructure.llm.prompt_loader import load_prompt
from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
from modules.outline.story_outline_schemas import (
    StoryOutlineContent,
    StoryOutlineGenerateRequest,
)
from modules.outline.story_outline_service import StoryOutlineService
from modules.project.facade import get_project_context
from modules.world.facade import (
    get_characters_context,
    get_world_background,
    get_world_bible_synopsis_context,
    get_world_context,
)

logger = logging.getLogger(__name__)

STORY_OUTLINE_GENERATE_ACTION = "outline.story_outline.generate"
STORY_OUTLINE_STEP_NAME = "outline.story_outline.generate.structured"
STORY_OUTLINE_CONTEXT_VERSION = "story-outline-context-v1"
STORY_OUTLINE_TIMEOUT_SECONDS = 180
STORY_OUTLINE_MAX_OUTPUT_TOKENS = 32_768
STORY_OUTLINE_AUTO_WORLD_TOP_K = 24
STORY_OUTLINE_AUTO_CHARACTER_TOP_K = 12
STORY_OUTLINE_AUTO_ENTITY_TOP_K = 24
STORY_OUTLINE_INPUT_MAX_CHARS = 96_000


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _serialize_untrusted_json(value: Any) -> str:
    """Keep dynamic data inside one JSON block without allowing tag closure."""
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )


def _bounded_text(value: Any, *, max_chars: int) -> tuple[str, bool]:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text, False
    head = max_chars * 2 // 3
    tail = max_chars - head
    return (
        text[:head].rstrip()
        + "\n[...deterministically truncated for StoryOutline context...]\n"
        + text[-tail:].lstrip(),
        True,
    )


def _bounded_json_value(value: Any, *, text_limit: int = 900) -> Any:
    if isinstance(value, str):
        return _bounded_text(value, max_chars=text_limit)[0]
    if isinstance(value, list):
        return [_bounded_json_value(item, text_limit=text_limit) for item in value[:40]]
    if isinstance(value, dict):
        return {
            str(key): _bounded_json_value(item, text_limit=text_limit)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if not str(key).startswith("_")
        }
    return value


@dataclass(frozen=True)
class StoryOutlineGenerationPlan:
    request: StoryOutlineGenerateRequest
    context: dict[str, Any]
    context_provenance: dict[str, Any]
    source_fingerprint: str


class StoryOutlineGenerationService:
    """Build and execute one preview-only StoryOutline LLM task."""

    def __init__(
        self,
        *,
        llm_client: LLMClient | None = None,
        story_outline_service: StoryOutlineService | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._story_outline_service = story_outline_service or StoryOutlineService()

    async def prepare(
        self,
        db: AsyncSession,
        data: StoryOutlineGenerateRequest,
    ) -> StoryOutlineGenerationPlan:
        project = await get_project_context(db, data.novel_id)
        if project is None:
            raise LookupError("Project not found")
        if str(project.novel_id) != data.novel_id:
            raise ValueError("project context novel_id mismatch")

        synopsis = await get_world_bible_synopsis_context(db, data.novel_id)
        if str(synopsis.novel_id) != data.novel_id:
            raise ValueError("world synopsis novel_id mismatch")
        background = await get_world_background(
            db,
            data.novel_id,
            context_mode="author_full",
            limit=1000,
        )
        if str(background.novel_id) != data.novel_id:
            raise ValueError("world background novel_id mismatch")
        current_outline = await self._selected_outline(db, data)

        explicit_character_ids = set(data.selected_character_ids)
        explicit_entity_ids = set(data.selected_entity_ids)
        automatic_world_candidates = []
        automatic_character_candidates = []
        automatic_entity_candidates = []
        for entry in background.entries:
            is_page = entry.asset_type == "world_bible_page"
            entity_group = entry.group.split(":", 1)[0]
            is_rule = entry.asset_type == "entity" and entity_group in {
                "rule",
                "power_system",
            }
            is_character = entry.asset_type == "entity" and entity_group == "character"
            if is_page or (is_rule and entry.asset_id not in explicit_entity_ids):
                automatic_world_candidates.append(entry)
            elif is_character and entry.asset_id not in explicit_character_ids:
                automatic_character_candidates.append(entry)
            elif (
                entry.asset_type == "entity" and entry.asset_id not in explicit_entity_ids
            ):
                automatic_entity_candidates.append(entry)

        for candidates in (
            automatic_world_candidates,
            automatic_character_candidates,
            automatic_entity_candidates,
        ):
            candidates.sort(
                key=lambda item: (-float(item.importance), item.asset_type, item.asset_id)
            )
        included_automatic = automatic_world_candidates[:STORY_OUTLINE_AUTO_WORLD_TOP_K]
        omitted_automatic = automatic_world_candidates[STORY_OUTLINE_AUTO_WORLD_TOP_K:]

        if data.selected_character_ids:
            selected_characters = await self._selected_characters(db, data)
            eligible_automatic_character_ids: list[str] = []
            character_selection_reason = "explicit_selection_priority"
        else:
            (
                selected_characters,
                eligible_automatic_character_ids,
            ) = await self._automatic_characters(
                db,
                data,
                automatic_character_candidates,
            )
            character_selection_reason = "automatic_character_top_k"

        if data.selected_entity_ids:
            selected_entities = await self._selected_entities(db, data)
            eligible_automatic_entity_ids: list[str] = []
            entity_selection_reason = "explicit_selection_priority"
        else:
            (
                selected_entities,
                eligible_automatic_entity_ids,
            ) = await self._automatic_entities(
                db,
                data,
                automatic_entity_candidates,
            )
            entity_selection_reason = "automatic_entity_top_k"

        character_top_k = self._top_k_provenance(
            explicit=bool(data.selected_character_ids),
            explicit_count=len(data.selected_character_ids),
            eligible_count=len(eligible_automatic_character_ids),
            limit=STORY_OUTLINE_AUTO_CHARACTER_TOP_K,
            reason="automatic_character_top_k",
        )
        entity_top_k = self._top_k_provenance(
            explicit=bool(data.selected_entity_ids),
            explicit_count=len(data.selected_entity_ids),
            eligible_count=len(eligible_automatic_entity_ids),
            limit=STORY_OUTLINE_AUTO_ENTITY_TOP_K,
            reason="automatic_entity_top_k",
        )

        pages = [
            self._background_entry(entry)
            for entry in included_automatic
            if entry.asset_type == "world_bible_page"
        ]
        rules = [
            self._background_entry(entry)
            for entry in included_automatic
            if entry.asset_type == "entity"
        ]
        synopsis_content, synopsis_truncated = _bounded_text(
            synopsis.content if synopsis.included else "",
            max_chars=20_000,
        )

        context: dict[str, Any] = {
            "project": {
                "title": project.title,
                "genre": project.genre,
                "tone": project.tone,
                "target_length": project.target_length,
                "current_stage": project.current_stage,
            },
            "world_bible_synopsis": (
                {
                    "content": synopsis_content,
                    "status": synopsis.status,
                    "stale": synopsis.stale,
                    "fallback": synopsis.fallback,
                }
                if synopsis.included and synopsis_content
                else None
            ),
            "world_bible_pages": pages,
            "core_world_rules": rules,
            "selected_characters": selected_characters,
            "selected_world_entities": selected_entities,
            "current_story_outline": current_outline,
        }
        source_refs = self._source_refs(
            data=data,
            context=context,
            synopsis=synopsis,
            automatic=included_automatic,
            selected_characters=selected_characters,
            selected_entities=selected_entities,
            current_outline=current_outline,
            synopsis_truncated=synopsis_truncated,
            character_selection_reason=character_selection_reason,
            entity_selection_reason=entity_selection_reason,
        )
        provenance = {
            "version": STORY_OUTLINE_CONTEXT_VERSION,
            "action": STORY_OUTLINE_GENERATE_ACTION,
            "included_asset_ids": {
                "world_bible_synopsis": (
                    [synopsis.revision_id or "deterministic-fallback"]
                    if context["world_bible_synopsis"] is not None
                    else []
                ),
                "characters": [item["character_id"] for item in selected_characters],
                "entities": [item["entity_id"] for item in selected_entities],
                "world_bible_pages": [item["asset_id"] for item in pages],
                "core_world_rules": [item["asset_id"] for item in rules],
                "story_outline_revisions": (
                    [current_outline["source_revision_id"]]
                    if current_outline is not None
                    else []
                ),
            },
            "omitted_assets": [
                *(
                    [
                        {
                            "type": "world_bible_synopsis",
                            "id": synopsis.revision_id or "missing",
                            "reason": synopsis.status,
                        }
                    ]
                    if context["world_bible_synopsis"] is None
                    else []
                ),
                *[
                    {
                        "type": entry.asset_type,
                        "id": entry.asset_id,
                        "reason": "automatic_world_assets_exceeded_top_k",
                    }
                    for entry in omitted_automatic
                ],
                *[
                    {
                        "type": "character",
                        "id": item,
                        "reason": "automatic_characters_exceeded_top_k",
                    }
                    for item in eligible_automatic_character_ids[
                        STORY_OUTLINE_AUTO_CHARACTER_TOP_K:
                    ]
                ],
                *[
                    {
                        "type": "entity",
                        "id": item,
                        "reason": "automatic_entities_exceeded_top_k",
                    }
                    for item in eligible_automatic_entity_ids[
                        STORY_OUTLINE_AUTO_ENTITY_TOP_K:
                    ]
                ],
            ],
            "top_k": {
                "world_assets": {
                    "applied": bool(omitted_automatic),
                    "limit": STORY_OUTLINE_AUTO_WORLD_TOP_K,
                    "candidate_count": len(automatic_world_candidates),
                    "reason": (
                        "automatic_world_assets_exceeded_top_k"
                        if omitted_automatic
                        else "not_needed"
                    ),
                },
                "characters": character_top_k,
                "world_entities": entity_top_k,
                "explicit_selection_priority": True,
            },
            "policy_excluded_sources": [
                "chapter_prose",
                "scene",
                "rag",
                "outline_arc",
                "plot_thread",
                "foreshadowing_plan",
                "reveal_plan",
            ],
            "projection_policy": {
                "selected_text_max_chars": 700,
                "world_entry_summary_max_chars": 1200,
                "world_synopsis_max_chars": 20_000,
                "current_outline_markdown_max_chars": 30_000,
            },
            "warnings": [*background.warnings, *synopsis.warnings],
            "source_refs": source_refs,
        }
        fingerprint_payload = {
            "author_brief": self._author_brief(data),
            "context": context,
            "source_refs": source_refs,
            "top_k": provenance["top_k"],
            "omitted_assets": provenance["omitted_assets"],
        }
        source_fingerprint = _stable_hash(fingerprint_payload)
        provenance["context_hash"] = source_fingerprint
        provenance["actual_input_chars"] = len(
            _serialize_untrusted_json(
                {
                    "author_brief": self._author_brief(data),
                    "context": context,
                }
            )
        )
        if provenance["actual_input_chars"] > STORY_OUTLINE_INPUT_MAX_CHARS:
            raise ValueError(
                "StoryOutline context exceeds the bounded input budget; "
                "reduce explicit selections or current outline size"
            )
        return StoryOutlineGenerationPlan(
            request=data,
            context=context,
            context_provenance=provenance,
            source_fingerprint=source_fingerprint,
        )

    async def generate_for_task(
        self,
        db: AsyncSession,
        *,
        data: StoryOutlineGenerateRequest,
        llm_execution_snapshot: dict[str, Any],
        submission_context_hash: str,
        progress_callback: Callable[[float], None] | None = None,
        context_checkpoint: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        from infrastructure.tasks.facade import require_task_checkpoint_session
        from modules.project.facade import require_active_project_exclusive

        require_task_checkpoint_session(db)
        plan = await self.prepare(db, data)
        if plan.source_fingerprint != submission_context_hash:
            raise ValueError(
                "StoryOutline generation context changed after submission; "
                "restart from a new request"
            )
        if context_checkpoint is not None:
            context_checkpoint(plan.context_provenance)
        if progress_callback is not None:
            progress_callback(0.2)

        async with self._open_task_client(
            db,
            data.novel_id,
            llm_execution_snapshot,
        ) as client:
            await self._checkpoint_before_provider(db)
            preview = await self._generate_preview(client, plan)
        if progress_callback is not None:
            progress_callback(0.85)

        await require_active_project_exclusive(db, data.novel_id)
        fresh = await self.prepare(db, data)
        if fresh.source_fingerprint != plan.source_fingerprint:
            raise ValueError(
                "StoryOutline generation context changed while the task was running; "
                "discarded stale preview"
            )
        if progress_callback is not None:
            progress_callback(0.95)
        await db.flush()
        logger.info(
            "StoryOutline preview complete (characters=%d, entities=%d, auto_world=%d)",
            len(plan.context["selected_characters"]),
            len(plan.context["selected_world_entities"]),
            len(plan.context["world_bible_pages"])
            + len(plan.context["core_world_rules"]),
        )
        return preview.model_dump(mode="json")

    @asynccontextmanager
    async def _open_task_client(
        self,
        db: AsyncSession,
        novel_id: str,
        snapshot: dict[str, Any],
    ) -> AsyncIterator[LLMClient]:
        if self._llm_client is not None:
            yield self._llm_client
            return
        if not isinstance(snapshot, dict) or not snapshot:
            raise ValueError("llm_execution_snapshot is required for StoryOutline task")
        from modules.project.facade import (
            create_project_snapshot_llm_client,
            restore_project_llm_execution_settings,
        )

        settings = await restore_project_llm_execution_settings(
            db,
            novel_id,
            snapshot,
        )
        client = create_project_snapshot_llm_client(
            settings,
            timeout_override=STORY_OUTLINE_TIMEOUT_SECONDS,
            novel_id=novel_id,
        )
        try:
            yield client
        finally:
            await client.close()

    @staticmethod
    async def _checkpoint_before_provider(db: AsyncSession) -> None:
        await db.commit()
        if db.in_transaction():
            raise RuntimeError(
                "StoryOutline task provider execution requires a transaction-free "
                "checkpoint"
            )
        db.expire_all()

    @staticmethod
    async def _generate_preview(
        client: LLMClient,
        plan: StoryOutlineGenerationPlan,
    ) -> StoryOutlineContent:
        return await run_managed_structured(
            client,
            LLMCallRequest(
                model=client.model_name,
                messages=[
                    LLMMessage(role="system", content=load_prompt("story_outline")),
                    LLMMessage(
                        role="user",
                        content=StoryOutlineGenerationService._build_user_prompt(plan),
                    ),
                ],
                temperature=0.55,
                response_format={"type": "json_object"},
            ),
            StoryOutlineContent,
            step_name=STORY_OUTLINE_STEP_NAME,
            max_fix_attempts=2,
            format_repair_attempts=1,
            permission_level=AgentPermissionLevel.suggest,
            read_only=True,
            timeout=STORY_OUTLINE_TIMEOUT_SECONDS,
            context_budget=ContextBudget(
                max_input_chars=STORY_OUTLINE_INPUT_MAX_CHARS,
                max_output_chars=STORY_OUTLINE_MAX_OUTPUT_TOKENS * 4,
            ),
        )

    @staticmethod
    def _build_user_prompt(plan: StoryOutlineGenerationPlan) -> str:
        payload = {
            "action": STORY_OUTLINE_GENERATE_ACTION,
            "author_brief": StoryOutlineGenerationService._author_brief(plan.request),
            "context": plan.context,
        }
        return (
            "<STORY_OUTLINE_INPUT_JSON>\n"
            f"{_serialize_untrusted_json(payload)}\n"
            "</STORY_OUTLINE_INPUT_JSON>\n\n"
            "以上 JSON 仅是本次作者意图与参考资料。严格遵守 system 规则，"
            "只返回 StoryOutline schema 的 JSON 预览。"
        )

    @staticmethod
    def _author_brief(data: StoryOutlineGenerateRequest) -> dict[str, str]:
        return {
            "author_intent": data.author_intent,
            "planned_scale": data.planned_scale,
            "coverage": data.coverage,
        }

    async def _selected_outline(
        self,
        db: AsyncSession,
        data: StoryOutlineGenerateRequest,
    ) -> dict[str, Any] | None:
        revision = None
        if data.base_revision_id is not None:
            revision = await self._story_outline_service.get_revision(
                db,
                data.novel_id,
                data.base_revision_id,
            )
        elif data.include_current_outline:
            current = await self._story_outline_service.get_current(db, data.novel_id)
            revision = current.revision
        if revision is None:
            return None
        markdown, truncated = _bounded_text(
            revision.outline_markdown,
            max_chars=30_000,
        )
        return {
            "source_revision_id": str(revision.id),
            "source_content_hash": revision.content_hash,
            "title": revision.title,
            "creative_core": revision.creative_core.model_dump(mode="json"),
            "outline_markdown": markdown,
            "major_storylines": [
                item.model_dump(mode="json") for item in revision.major_storylines
            ],
            "macro_movements": [
                item.model_dump(mode="json") for item in revision.macro_movements
            ],
            "open_decisions": [
                item.model_dump(mode="json") for item in revision.open_decisions
            ],
            "truncated": truncated,
        }

    @staticmethod
    async def _selected_characters(
        db: AsyncSession,
        data: StoryOutlineGenerateRequest,
    ) -> list[dict[str, Any]]:
        if not data.selected_character_ids:
            return []
        bundle = await get_characters_context(
            db,
            data.novel_id,
            data.selected_character_ids,
            reveal_mode="author_only",
        )
        by_id = {item.character_id: item for item in bundle.characters}
        missing = [item for item in data.selected_character_ids if item not in by_id]
        if missing:
            raise ValueError(
                "selected_character_ids contain missing, non-canonical, or "
                "cross-project IDs"
            )
        return [
            _bounded_json_value(by_id[item].model_dump(mode="json"), text_limit=700)
            for item in data.selected_character_ids
        ]

    @staticmethod
    async def _selected_entities(
        db: AsyncSession,
        data: StoryOutlineGenerateRequest,
    ) -> list[dict[str, Any]]:
        if not data.selected_entity_ids:
            return []
        bundle = await get_world_context(
            db,
            data.novel_id,
            entity_ids=data.selected_entity_ids,
            reveal_mode="author_full",
            limit=len(data.selected_entity_ids),
        )
        if str(bundle.novel_id) != data.novel_id:
            raise ValueError("world context novel_id mismatch")
        by_id = {item.entity_id: item for item in bundle.entities}
        missing = [item for item in data.selected_entity_ids if item not in by_id]
        if missing:
            raise ValueError(
                "selected_entity_ids contain missing, non-canonical, or cross-project IDs"
            )
        return [
            _bounded_json_value(by_id[item].model_dump(mode="json"), text_limit=700)
            for item in data.selected_entity_ids
        ]

    @staticmethod
    async def _automatic_characters(
        db: AsyncSession,
        data: StoryOutlineGenerateRequest,
        candidates: list[Any],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        candidate_ids = list(dict.fromkeys(item.asset_id for item in candidates))
        if not candidate_ids:
            return [], []
        bundle = await get_characters_context(
            db,
            data.novel_id,
            candidate_ids,
            reveal_mode="author_only",
        )
        by_id = {item.character_id: item for item in bundle.characters}
        eligible_ids = [item for item in candidate_ids if item in by_id]
        included_ids = eligible_ids[:STORY_OUTLINE_AUTO_CHARACTER_TOP_K]
        return (
            [
                _bounded_json_value(by_id[item].model_dump(mode="json"), text_limit=700)
                for item in included_ids
            ],
            eligible_ids,
        )

    @staticmethod
    async def _automatic_entities(
        db: AsyncSession,
        data: StoryOutlineGenerateRequest,
        candidates: list[Any],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        candidate_ids = list(dict.fromkeys(item.asset_id for item in candidates))
        if not candidate_ids:
            return [], []
        bundle = await get_world_context(
            db,
            data.novel_id,
            entity_ids=candidate_ids,
            reveal_mode="author_full",
            limit=len(candidate_ids),
        )
        if str(bundle.novel_id) != data.novel_id:
            raise ValueError("world context novel_id mismatch")
        by_id = {item.entity_id: item for item in bundle.entities}
        eligible_ids = [item for item in candidate_ids if item in by_id]
        included_ids = eligible_ids[:STORY_OUTLINE_AUTO_ENTITY_TOP_K]
        return (
            [
                _bounded_json_value(by_id[item].model_dump(mode="json"), text_limit=700)
                for item in included_ids
            ],
            eligible_ids,
        )

    @staticmethod
    def _top_k_provenance(
        *,
        explicit: bool,
        explicit_count: int,
        eligible_count: int,
        limit: int,
        reason: str,
    ) -> dict[str, Any]:
        if explicit:
            return {
                "applied": False,
                "limit": limit,
                "candidate_count": explicit_count,
                "reason": "explicit_selection",
            }
        return {
            "applied": eligible_count > limit,
            "limit": limit,
            "candidate_count": eligible_count,
            "reason": reason if eligible_count > limit else "not_needed",
        }

    @staticmethod
    def _background_entry(entry: Any) -> dict[str, Any]:
        return {
            "asset_id": entry.asset_id,
            "asset_type": entry.asset_type,
            "title": entry.title,
            "summary": _bounded_text(entry.summary, max_chars=1200)[0],
            "group": entry.group,
            "importance": entry.importance,
        }

    @staticmethod
    def _source_refs(
        *,
        data: StoryOutlineGenerateRequest,
        context: dict[str, Any],
        synopsis: Any,
        automatic: list[Any],
        selected_characters: list[dict[str, Any]],
        selected_entities: list[dict[str, Any]],
        current_outline: dict[str, Any] | None,
        synopsis_truncated: bool,
        character_selection_reason: str,
        entity_selection_reason: str,
    ) -> list[dict[str, Any]]:
        refs = [
            {
                "type": "project",
                "id": data.novel_id,
                "hash": _stable_hash(context["project"]),
                "reason": "required_project_context",
            }
        ]
        if context["world_bible_synopsis"] is not None:
            refs.append(
                {
                    "type": "world_bible_synopsis",
                    "id": synopsis.revision_id or "deterministic-fallback",
                    "hash": _stable_hash(context["world_bible_synopsis"]),
                    "source_hash": synopsis.source_hash,
                    "block_hash": synopsis.block_hash,
                    "reason": (
                        "included_with_deterministic_truncation"
                        if synopsis_truncated
                        else "adopted_author_context"
                    ),
                }
            )
        for item in automatic:
            projected = StoryOutlineGenerationService._background_entry(item)
            refs.append(
                {
                    "type": item.asset_type,
                    "id": item.asset_id,
                    "hash": _stable_hash(projected),
                    "reason": "automatic_world_top_k",
                }
            )
        for item in selected_characters:
            refs.append(
                {
                    "type": "character",
                    "id": item["character_id"],
                    "hash": _stable_hash(item),
                    "reason": character_selection_reason,
                }
            )
        for item in selected_entities:
            refs.append(
                {
                    "type": "entity",
                    "id": item["entity_id"],
                    "hash": _stable_hash(item),
                    "reason": entity_selection_reason,
                }
            )
        if current_outline is not None:
            refs.append(
                {
                    "type": "story_outline_revision",
                    "id": current_outline["source_revision_id"],
                    "hash": _stable_hash(current_outline),
                    "source_hash": current_outline["source_content_hash"],
                    "reason": (
                        "included_with_deterministic_truncation"
                        if current_outline["truncated"]
                        else "explicit_revision_context"
                    ),
                }
            )
        return refs


__all__ = [
    "STORY_OUTLINE_GENERATE_ACTION",
    "STORY_OUTLINE_STEP_NAME",
    "StoryOutlineGenerationPlan",
    "StoryOutlineGenerationService",
]
