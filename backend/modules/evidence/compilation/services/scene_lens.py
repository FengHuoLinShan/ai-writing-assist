"""Read-only, character-visible context for the writing Scene Lens."""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFoundError, ValidationError
from infrastructure.llm.redaction import redact_diagnostic
from modules.evidence.compilation.services.loaders import (
    CharactersLoader,
)

logger = logging.getLogger(__name__)
_STATE_LABELS = {
    "entities": "人物与对象",
    "relations": "关系",
    "locations": "空间与位置",
    "knowledge": "知识边界",
    "timeline": "时间顺序",
    "causality": "因果与前提",
}


async def _get_scene(db: AsyncSession, novel_id: str, scene_id: str) -> Any:
    # 函数内导入保持 evidence→story 惰性：顶层会与 story→evidence 形成顶层双向对。
    from modules.story.facade import get_scene_contract

    return await get_scene_contract(db, novel_id, scene_id)


async def _get_checkpoints(db: AsyncSession, novel_id: str, scene_id: str) -> Any:
    from modules.story.facade import get_scene_checkpoints

    return await get_scene_checkpoints(db, novel_id, scene_id)


async def _get_state_view(
    db: AsyncSession, novel_id: str, scene_id: str, *, viewpoint: dict | None = None
) -> Any:
    from modules.story.facade import get_scene_state_view

    return await get_scene_state_view(
        db, novel_id, scene_id, viewpoint=viewpoint or {"kind": "author"}
    )


class SceneLensService:
    """Load a minimal Scene view without retrieval, generation, or writes."""

    def __init__(
        self,
        *,
        get_scene_fn=_get_scene,
        characters_loader: CharactersLoader | None = None,
        get_scene_checkpoints_fn=_get_checkpoints,
        get_state_view_fn=_get_state_view,
    ) -> None:
        self._get_scene = get_scene_fn
        self._characters_loader = characters_loader or CharactersLoader()
        self._get_checkpoints = get_scene_checkpoints_fn
        self._get_state_view = get_state_view_fn

    async def load(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        scene_id: str,
        chapter_index: int,
    ) -> dict[str, Any]:
        scene_contract = await self._get_scene(db, novel_id, scene_id)
        if scene_contract is None:
            raise NotFoundError("Scene not found", code="scene_not_found")
        scene = (
            scene_contract if isinstance(scene_contract, dict) else asdict(scene_contract)
        )
        if chapter_index not in self._scene_chapters(scene):
            raise ValidationError(
                "Scene 不属于当前章节",
                code="scene_chapter_mismatch",
                status_code=422,
            )

        viewpoint_id = scene.get("pov_character_id")
        warnings = []
        if not viewpoint_id:
            warnings.append("本场未设定 POV 人物，未加载角色可见知识")

        state_view = await self._read_state_view(
            db, novel_id=novel_id, scene_id=scene_id, warnings=warnings
        )
        role_view = (
            await self._read_state_view(
                db,
                novel_id=novel_id,
                scene_id=scene_id,
                warnings=warnings,
                viewpoint={"kind": "character", "target_id": viewpoint_id},
            )
            if viewpoint_id
            else {}
        )
        actor_choices = {}
        try:
            actor_choices = await self._characters_loader.identity_choices(
                db, novel_id, list(state_view.get("subject_labels") or {})
            )
        except Exception as exc:
            logger.warning(
                "Failed to read Scene identity choices: %s",
                redact_diagnostic(exc, limit=300),
            )
            warnings.append("本场人物名单暂时无法读取")
        return {
            "state_fingerprint": state_view.get("state_fingerprint"),
            "subject_choices": actor_choices,
            "role_visible_knowledge": self._knowledge_items(role_view, viewpoint_id),
            "scene_world_state": await self._state_items(
                db,
                novel_id=novel_id,
                scene_id=scene_id,
                warnings=warnings,
                state_view=state_view,
            ),
            "object_states": await self._object_states(
                db,
                novel_id=novel_id,
                scene_id=scene_id,
                related_ids=set(self._related_entity_ids(scene)) | {str(viewpoint_id)}
                if viewpoint_id
                else set(self._related_entity_ids(scene)),
                warnings=warnings,
                state_view=state_view,
            ),
            "warnings": list(dict.fromkeys(warnings)),
        }

    async def _read_state_view(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        scene_id: str,
        warnings: list[str],
        viewpoint: dict | None = None,
    ) -> dict[str, Any]:
        """作者视角状态视图（单次读取，供维度新鲜度与对象状态共用）。"""
        try:
            view = await self._get_state_view(
                db, novel_id, scene_id, **({"viewpoint": viewpoint} if viewpoint else {})
            )
            data = view.model_dump() if hasattr(view, "model_dump") else view
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            logger.warning(
                "Failed to read Scene Lens state view: %s",
                redact_diagnostic(exc, limit=300),
            )
            warnings.append("对象状态暂时无法读取")
            return {}

    async def _state_items(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        scene_id: str,
        warnings: list[str],
        state_view: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        try:
            value = await self._get_checkpoints(db, novel_id, scene_id)
            data = value.model_dump() if hasattr(value, "model_dump") else value
        except Exception as exc:
            logger.warning(
                "Failed to read Scene Lens checkpoints: %s",
                redact_diagnostic(exc, limit=300),
            )
            warnings.append("Scene 时点状态暂时无法读取")
            data = {}

        raw_items = []
        if isinstance(data, dict):
            raw_items = data.get("items") or []
        by_dimension = {
            item.get("dimension"): item for item in raw_items if isinstance(item, dict)
        }
        view_dimensions = {
            str(item.get("dimension")): item
            for item in ((state_view or {}).get("dimensions") or [])
            if isinstance(item, dict)
        }
        return [
            self._state_item(
                dimension,
                by_dimension.get(dimension),
                view_status=(view_dimensions.get(dimension) or {}).get("status"),
            )
            for dimension in _STATE_LABELS
        ]

    @staticmethod
    def _state_item(
        dimension: str,
        item: dict[str, Any] | None,
        *,
        view_status: str | None = None,
    ) -> dict[str, Any]:
        available = bool(
            item
            and item.get("status") == "ready"
            and (
                item.get("source") == "system_generated" or item.get("confirmed") is True
            )
        )
        # M4：checkpoint 行 ready 但视图基线比对 degraded 时，作者侧必须看到
        # 待核对，而不是把绕过失效钩子的旧投影当确定事实展示。
        stale = bool(available and view_status == "degraded")
        return {
            "label": _STATE_LABELS[dimension],
            "summary": (
                str(item.get("display_summary") or "已记录")
                if available
                else "暂无可靠记录"
            ),
            "availability": available,
            "stale": stale,
        }

    async def _object_states(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        scene_id: str,
        related_ids: set[str],
        warnings: list[str],
        state_view: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """作者视角的对象级状态明细（M2：字段/认知/未知分层，来源可回开）。"""
        data = (
            state_view
            if state_view is not None
            else await self._read_state_view(
                db, novel_id=novel_id, scene_id=scene_id, warnings=warnings
            )
        )

        dimensions = {
            str(item.get("dimension")): item
            for item in (data.get("dimensions") or [])
            if isinstance(item, dict)
        }
        entity_facts = [
            fact
            for fact in (dimensions.get("entities") or {}).get("facts") or []
            if isinstance(fact, dict)
        ]
        labels = {
            str(subject): str(label)
            for subject, label in (data.get("subject_labels") or {}).items()
        }
        beliefs_by_subject: dict[str, list[dict[str, Any]]] = {}
        for fact in (dimensions.get("knowledge") or {}).get("facts") or []:
            if not isinstance(fact, dict) or fact.get("layer") != "belief":
                continue
            subject = str(fact.get("field") or "").removeprefix("knows:")
            if subject == "unspecified":
                continue
            beliefs_by_subject.setdefault(subject, []).append(fact)

        states: list[dict[str, Any]] = []
        for subject in sorted(related_ids):
            facts = [f for f in entity_facts if str(f.get("subject_id")) == subject]
            locations = [
                f
                for f in (dimensions.get("locations") or {}).get("facts") or []
                if isinstance(f, dict) and str(f.get("subject_id")) == subject
            ]
            beliefs = beliefs_by_subject.get(subject, [])
            unknowns = []
            if not facts:
                unknowns.append("该对象的状态尚未记录；不能据此推断行动条件已满足")
            if not locations:
                unknowns.append("所在位置未记录")
            if not beliefs:
                unknowns.append("哪些人物知情尚未记录")
            for dimension in ("entities", "locations", "knowledge"):
                item = dimensions.get(dimension) or {}
                if item.get("gap_reason"):
                    unknowns.append(str(item["gap_reason"]))
            unknowns.extend(str(item) for item in data.get("omissions") or [])
            states.append(
                {
                    "subject_id": subject,
                    "label": labels.get(subject) or "未命名对象",
                    "fields": [
                        {
                            "field": str(fact.get("field")),
                            "display": {"full": "月圆", "other": "非月圆"}.get(
                                str(fact.get("value")), "未记载"
                            )
                            if fact.get("field") == "opening_moon_phase"
                            else self._display_value(fact.get("value"), labels),
                            "layer": str(fact.get("layer")),
                            "confidence": str(fact.get("confidence")),
                            "possibly_false": bool(fact.get("possibly_false")),
                            "source": self._source(fact, dimensions.get("entities")),
                        }
                        for fact in facts
                    ],
                    "location": self._display_value(locations[0].get("value"), labels)
                    if locations
                    else None,
                    "location_source": self._source(
                        locations[0], dimensions.get("locations")
                    )
                    if locations
                    else None,
                    "unknowns": list(dict.fromkeys(unknowns)),
                    "stale": any(
                        (dimensions.get(key) or {}).get("status") == "degraded"
                        for key in ("entities", "locations", "knowledge")
                    ),
                    "knowledge": [
                        {
                            "holder": labels.get(str(belief.get("subject_id")), "某角色"),
                            "text": str(belief.get("value") or ""),
                            "possibly_false": bool(belief.get("possibly_false")),
                            "source": self._source(belief, dimensions.get("knowledge")),
                        }
                        for belief in beliefs_by_subject.get(subject, [])
                    ],
                }
            )
        return states

    @staticmethod
    def _source(fact: dict, dimension: dict | None) -> dict:
        return {
            **dict(fact.get("source") or {}),
            "evidence_refs": list((dimension or {}).get("evidence_refs") or []),
        }

    @staticmethod
    def _display_value(value: Any, labels: dict[str, str]) -> str:
        if isinstance(value, str):
            if value in labels:
                return labels[value]
            import uuid

            try:
                uuid.UUID(value)
            except ValueError:
                return value.strip()
            return "未记录名称的对象"
        if isinstance(value, list):
            return "、".join(
                part
                for part in (
                    SceneLensService._display_value(item, labels) for item in value
                )
                if part
            )
        if isinstance(value, dict):
            if value.get("text_state"):
                return str(value["text_state"])
            if value.get("location_id"):
                return SceneLensService._display_value(value["location_id"], labels)
            return "，".join(
                f"{key}：{SceneLensService._display_value(item, labels)}"
                for key, item in value.items()
                if item not in (None, "", [])
            )
        return "" if value is None else str(value)

    @staticmethod
    def _knowledge_items(data: dict, viewpoint_id: str | None) -> list[dict[str, Any]]:
        if not viewpoint_id:
            return []
        dimension = next(
            (
                item
                for item in data.get("dimensions", [])
                if item.get("dimension") == "knowledge"
            ),
            {},
        )
        if dimension.get("status") != "ok":
            return [
                {
                    "label": "本场人物知识",
                    "summary": dimension.get("gap_reason")
                    or "本场知识依据不足；不能用今日人物资料补齐",
                    "availability": False,
                    "stale": dimension.get("status") == "degraded",
                }
            ]
        facts = [
            item
            for item in dimension.get("facts", [])
            if item.get("layer") == "belief" and item.get("subject_id") == viewpoint_id
        ]
        return [
            {
                "label": "本场人物的认知",
                "summary": str(item.get("value") or "未记载内容")
                + ("（可能误信）" if item.get("possibly_false") else ""),
                "availability": True,
                "stale": False,
            }
            for item in facts
        ] or [
            {
                "label": "本场人物知识",
                "summary": "未记录本场已知事项；不能推断行动条件已满足",
                "availability": False,
                "stale": False,
            }
        ]

    @staticmethod
    def _scene_chapters(scene: dict[str, Any]) -> set[int]:
        values = list(scene.get("chapter_ids") or [])
        values.extend(
            chunk.get("chapter_index", chunk.get("chapter_id"))
            for chunk in scene.get("scene_chunks") or []
            if isinstance(chunk, dict)
        )
        return {int(value) for value in values if str(value).isdigit()}

    @staticmethod
    def _related_entity_ids(scene: dict[str, Any]) -> list[str]:
        meta = scene.get("structure_meta")
        values = meta.get("related_entity_ids") if isinstance(meta, dict) else []
        return list(dict.fromkeys(str(value) for value in values or [] if value))
