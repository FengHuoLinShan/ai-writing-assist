"""人物信息加载器（含知识边界过滤）"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.redaction import redact_diagnostic
from modules.context.contracts import (
    CONTEXT_BUDGET,
    CompileOptions,
    StructureContextBundle,
)
from modules.context.services.protocol import Loader

logger = logging.getLogger(__name__)

_GetCharactersContextFn = Callable[..., Awaitable[Any]]
_FilterContextByKnowledgeFn = Callable[..., Awaitable[Any]]
_GetSceneContractFn = Callable[..., Awaitable[Any]]


async def _default_get_characters_context(*args: Any, **kwargs: Any) -> Any:
    from modules.world.facade import get_characters_context

    return await get_characters_context(*args, **kwargs)


async def _default_filter_context_by_character_knowledge(
    *args: Any,
    **kwargs: Any,
) -> Any:
    from modules.world.facade import filter_context_by_character_knowledge

    return await filter_context_by_character_knowledge(*args, **kwargs)


async def _default_get_scene_contract(*args: Any, **kwargs: Any) -> Any:
    from modules.outline.facade import get_scene_contract

    return await get_scene_contract(*args, **kwargs)


class CharactersLoader(Loader):
    """加载人物信息，对首个人物执行知识边界过滤"""

    def __init__(
        self,
        get_characters_context_fn: _GetCharactersContextFn = (
            _default_get_characters_context
        ),
        filter_context_by_character_knowledge_fn: _FilterContextByKnowledgeFn = (
            _default_filter_context_by_character_knowledge
        ),
        get_scene_contract_fn: _GetSceneContractFn = _default_get_scene_contract,
    ) -> None:
        self._get_characters_context = get_characters_context_fn
        self._filter_context_by_character_knowledge = (
            filter_context_by_character_knowledge_fn
        )
        self._get_scene_contract = get_scene_contract_fn

    @property
    def name(self) -> str:
        return "characters"

    async def load(
        self,
        db: AsyncSession,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> None:
        try:
            await self._load(db, options, bundle)
        except Exception as exc:
            if options.reveal_mode != "character":
                raise
            logger.warning(
                "Failed to load character knowledge safely: %s",
                redact_diagnostic(exc, limit=300),
            )
            bundle.characters = []
            bundle.world_entities = []
            bundle.budget_used["characters"] = 0
            bundle.warnings.append("人物知识加载失败，已按保守策略排除对象")

    async def _load(
        self,
        db: AsyncSession,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> None:
        char_limit = CONTEXT_BUDGET.get("characters", 6)
        relevance_action = options.consumer_action in {
            "writing.generate",
            "outline.analyze",
            "world.generation.chat",
            "world.generation.convergence",
            "world.generation.core_entity",
            "world.generation.world_bible_page",
        }
        candidates = [
            (character_id, "explicit")
            for character_id in dict.fromkeys(options.character_ids or [])
        ]
        viewpoint_character_id = (
            options.viewpoint_character_id
            if isinstance(options.viewpoint_character_id, str)
            else None
        )
        if viewpoint_character_id:
            candidates = self._merge_candidates(
                [(viewpoint_character_id, "viewpoint")],
                candidates,
            )

        if options.character_ids:
            if relevance_action:
                inferred = await self._infer_character_candidates(
                    db,
                    options,
                    bundle,
                )
                candidates = self._merge_candidates(candidates, inferred)
        else:
            candidates = await self._infer_character_candidates(db, options, bundle)

        if len(candidates) > char_limit:
            bundle.warnings.append(
                f"人物候选超过 Top-{char_limit}，已按显式选择、Scene、"
                "剧情线和检索证据的顺序裁剪"
            )
        selected_candidates = candidates[:char_limit]
        limited_ids = [character_id for character_id, _reason in selected_candidates]

        if limited_ids:
            ctx = await self._get_characters_context(
                db,
                options.novel_id,
                character_ids=limited_ids,
                reveal_mode=options.reveal_mode,
            )
            if ctx:
                characters = [c.model_dump() for c in ctx.characters]
                rank = {
                    self._id_key(item): index for index, item in enumerate(limited_ids)
                }
                characters.sort(
                    key=lambda item: rank.get(
                        self._id_key(item.get("character_id") or item.get("id") or ""),
                        len(rank),
                    )
                )
                bundle.characters = characters[:char_limit]

        if (
            options.scope == "generation_center"
            or options.consumer_action == "outline.analyze"
        ):
            actual_ids = [
                str(item.get("character_id") or item.get("id") or "")
                for item in bundle.characters
                if item.get("character_id") or item.get("id")
            ]
            bundle.selection_trace["characters"] = self._selection_trace(
                candidates,
                selected_candidates,
                actual_ids,
                top_k=char_limit,
            )

        # 知识边界过滤：仅在 character reveal 模式下执行，使用视角人物作为过滤主体。
        loaded_character_ids = {
            self._id_key(item.get("character_id") or item.get("id") or "")
            for item in bundle.characters
            if isinstance(item, dict)
        }
        if (
            options.reveal_mode == "character"
            and viewpoint_character_id
            and self._id_key(viewpoint_character_id) not in loaded_character_ids
        ):
            bundle.characters = []
            bundle.world_entities = []
            bundle.warnings.append("视角人物已不可用，已保守排除人物知识")
            bundle.budget_used["characters"] = 0
            return
        if (
            options.reveal_mode == "character"
            and limited_ids
            and bundle.world_entities
            and options.scope != "project"
        ):
            filter_character_id = options.viewpoint_character_id or limited_ids[0]
            visible_until_chapter = options.visible_until_chapter or options.chapter_index
            if visible_until_chapter is None:
                bundle.world_entities = []
                bundle.warnings.append("角色视角缺少截止章，已保守排除人物知识")
                bundle.budget_used["characters"] = len(bundle.characters)
                return
            if not options.viewpoint_character_id:
                logger.warning(
                    "character reveal 模式未提供 viewpoint_character_id，"
                    "使用 limited_ids[0] 作为过滤角色: %s",
                    filter_character_id,
                )

            try:
                # 世界对象字段 (entity_type/entity_id) 需要映射为知识过滤器的
                # target_type/target_id 才能正确匹配 character_knowledge 记录。
                # character_knowledge 的 target_type 使用粗粒度分类：
                # CharacterKnowledge 支持的 typed CoreEntity 保持原样，
                # 其它世界对象统一归为 entity。
                filter_input: list[dict] = []
                for ent in bundle.world_entities:
                    mapped = dict(ent)
                    etype = ent.get("entity_type", "")
                    if etype in {"character", "location", "event", "item", "faction"}:
                        mapped["target_type"] = etype
                    else:
                        mapped["target_type"] = "entity"
                    mapped["target_id"] = ent.get("entity_id", "") or ent.get("id", "")
                    filter_input.append(mapped)

                filtered = await self._filter_context_by_character_knowledge(
                    db,
                    options.novel_id,
                    filter_character_id,
                    filter_input,
                    visible_until_chapter=visible_until_chapter,
                )

                # 将过滤结果映射回世界对象字段，并整合知识边界信息。
                # false_belief 时用 misconception 替换 summary，且不暴露 hidden_truth。
                restored: list[dict] = []
                for ent in filtered or []:
                    mapped = dict(ent)
                    mapped.pop("target_type", None)
                    mapped.pop("target_id", None)
                    if ent.get("knowledge_level") in {"false_belief", "misunderstood"}:
                        misconception = ent.get("content", "")
                        if misconception:
                            mapped["summary"] = misconception
                            mapped["misconception"] = misconception
                        mapped.pop("hidden_truth", None)
                    restored.append(mapped)

                if filtered is not None:
                    bundle.world_entities = restored
                    if len(restored) < len(filter_input) or any(
                        item.get("visibility_source") == "public_info"
                        for item in restored
                    ):
                        bundle.warnings.append(
                            "无法确定学习位置或超出截止位置的人物知识"
                            "已保守排除；未授权对象仅保留公开基线"
                        )
            except Exception as exc:
                logger.warning(
                    "知识边界过滤失败: %s",
                    redact_diagnostic(exc, limit=300),
                )
                bundle.world_entities = []
                bundle.warnings.append("人物知识过滤失败，已按保守策略排除对象")

        bundle.budget_used["characters"] = len(bundle.characters)

    async def _infer_character_candidates(
        self,
        db: AsyncSession,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> list[tuple[str, str]]:
        candidates: list[tuple[str, str]] = []
        seen: set[str] = set()

        def add(value: object, reason: str) -> None:
            character_id = str(value or "").strip()
            identity = self._id_key(character_id)
            if character_id and identity not in seen:
                seen.add(identity)
                candidates.append((character_id, reason))

        def extend(values: object, reason: str) -> None:
            if not isinstance(values, list | tuple | set):
                return
            for value in values:
                add(value, reason)

        # 1. Explicit POV and Scene POV character.
        if options.viewpoint_character_id:
            add(options.viewpoint_character_id, "viewpoint")
        scene = (
            bundle.scene
            if isinstance(bundle.scene, dict)
            else asdict(bundle.scene)
            if bundle.scene is not None
            else None
        )
        pov = scene.get("pov_character_id") if scene else None
        if pov:
            add(pov, "scene_pov")
        elif options.scene_id:
            scene_contract = await self._get_scene_contract(
                db,
                options.novel_id,
                options.scene_id,
            )
            scene = (
                scene_contract
                if isinstance(scene_contract, dict)
                else asdict(scene_contract)
                if scene_contract is not None
                else None
            )
            pov = scene.get("pov_character_id") if scene else None
            if pov:
                add(pov, "scene_pov")

        # 2. Current Scene, arc, active threads and RAG evidence references.
        analysis = (
            bundle.outline_analysis if isinstance(bundle.outline_analysis, dict) else {}
        )
        extend(analysis.get("related_character_ids"), "outline_range")
        scene_meta = scene.get("structure_meta") if scene else None
        if isinstance(scene_meta, dict):
            extend(scene_meta.get("related_character_ids"), "scene")
        if scene:
            extend(scene.get("present_character_ids"), "scene")
            extend(scene.get("character_ids"), "scene")
            extend(scene.get("related_character_ids"), "scene")
        arc = bundle.outline_arc if isinstance(bundle.outline_arc, dict) else {}
        extend(arc.get("related_character_ids"), "arc")
        for thread in bundle.plot_threads:
            if isinstance(thread, dict):
                extend(thread.get("related_character_ids"), "plot_thread")
        for chunk in bundle.rag_chunks:
            if isinstance(chunk, dict):
                extend(chunk.get("character_ids"), "rag")

        # 3. Character-shaped world entities already selected for this request.
        for ent in bundle.world_entities:
            if ent.get("entity_type") == "character":
                eid = ent.get("entity_id") or ent.get("id")
                add(eid, "world_entity")

        return candidates

    @staticmethod
    def _merge_candidates(
        primary: list[tuple[str, str]],
        secondary: list[tuple[str, str]],
    ) -> list[tuple[str, str]]:
        result = list(primary)
        seen = {CharactersLoader._id_key(item_id) for item_id, _reason in result}
        for item in secondary:
            identity = CharactersLoader._id_key(item[0])
            if identity not in seen:
                seen.add(identity)
                result.append(item)
        return result

    @staticmethod
    def _id_key(value: object) -> str:
        text = str(value or "").strip()
        try:
            return uuid.UUID(text).hex
        except ValueError:
            return text

    @staticmethod
    def _selection_trace(
        candidates: list[tuple[str, str]],
        selected: list[tuple[str, str]],
        actual_ids: list[str],
        *,
        top_k: int,
    ) -> dict[str, object]:
        actual = {CharactersLoader._id_key(item_id) for item_id in actual_ids}
        selected_ids = {
            CharactersLoader._id_key(item_id) for item_id, _reason in selected
        }
        included = [
            {"id": item_id, "reason": reason}
            for item_id, reason in selected
            if CharactersLoader._id_key(item_id) in actual
        ]
        excluded = [
            {
                "id": item_id,
                "reason": reason,
                "exclusion_reason": (
                    "not_loaded"
                    if CharactersLoader._id_key(item_id) in selected_ids
                    else "top_k"
                ),
            }
            for item_id, reason in candidates
            if CharactersLoader._id_key(item_id) not in actual
        ]
        return {"top_k": top_k, "included": included, "excluded": excluded}
