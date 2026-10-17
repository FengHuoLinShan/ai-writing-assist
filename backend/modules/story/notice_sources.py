"""Story-owned structural notices for the author writing cockpit."""

from __future__ import annotations

from typing import Any

from infrastructure.stable_hash import stable_hash
from modules.story.outline_state.scene_workbench import SceneWorkbenchService

SOURCE_ID = "story.structure"


def _semantic_status(scene: Any, field: str) -> str | None:
    meta = scene.structure_meta if isinstance(scene.structure_meta, dict) else {}
    source = str(scene.source or "")
    origin = str(meta.get("semantic_origin") or "")
    trusted = source in {"deep_import", "manual_fusion"} or origin in {
        "phase1b_enrichment",
        "phase1c_synthesis",
        "author_reviewed_fusion",
    }
    if not trusted:
        return None
    statuses = meta.get("semantic_field_statuses")
    if not isinstance(statuses, dict):
        statuses = meta.get("phase1b_field_statuses")
    if not isinstance(statuses, dict):
        statuses = {}
    value = statuses.get(field)
    if field == "core_conflict":
        value = value or meta.get("core_conflict_status")
    return value if value in {"present", "not_applicable", "uncertain"} else None


def _scene_maps_to_chapter(scene: Any, chapter_index: int) -> bool:
    for raw in scene.chapter_ids or []:
        try:
            if int(raw) == chapter_index:
                return True
        except (TypeError, ValueError):
            continue
    for chunk in scene.scene_chunks or []:
        if not isinstance(chunk, dict):
            continue
        raw = chunk.get("chapter_index") or chunk.get("chapter_id")
        try:
            if int(raw) == chapter_index:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _scene_issues(item: Any, chapter_index: int | None) -> list[tuple[str, str, str]]:
    scene = item.scene
    issues: list[tuple[str, str, str]] = []
    labels = {
        "goal": ("目标", "medium"),
        "core_conflict": ("核心冲突", "low"),
        "emotional_beat": ("情绪节拍", "low"),
    }
    for field, (label, severity) in labels.items():
        status = _semantic_status(scene, field)
        if status == "not_applicable":
            continue
        if status == "uncertain":
            issues.append((f"structure-{field}", severity, f"场景的{label}仍待确认"))
        elif not str(getattr(scene, field, None) or "").strip():
            issues.append((f"structure-{field}", severity, f"场景尚未配置{label}"))

    if not str(scene.pov_character_id or "").strip():
        issues.append(("structure-pov", "low", "场景尚未配置视角人物"))

    meta = scene.structure_meta if isinstance(scene.structure_meta, dict) else {}
    health = set(item.health or [])
    if (
        meta.get("needs_review") is True
        or "unreviewed" in health
        or "needs_review" in health
    ):
        issues.append(("structure-review", "medium", "场景尚未完成人工复核"))
    if meta.get("needs_organize") is True or "needs_organize" in health:
        issues.append(("structure-organize", "medium", "场景已标记为待整理"))
    if chapter_index is not None and not _scene_maps_to_chapter(scene, chapter_index):
        issues.append(("structure-chapter-map", "medium", "场景尚未对应到当前章节"))
    return issues


def _scene_field(code: str) -> str | None:
    return {
        "structure-pov": "pov-character",
        "structure-review": "review",
        "structure-goal": "goal",
        "structure-core_conflict": "core_conflict",
        "structure-emotional_beat": "emotional_beat",
        "structure-chapter-map": "context",
    }.get(code)


async def list_scene_structure_notices(
    db, novel_id: str, scope: dict[str, object]
) -> list[dict[str, Any]]:
    scene_id = str(scope.get("scene_id") or "")
    raw_chapter = scope.get("chapter_index")
    chapter_index = int(raw_chapter) if raw_chapter is not None else None
    workbench = SceneWorkbenchService()
    result = await workbench.get_workbench(
        db,
        novel_id,
        selected_scene_id=scene_id or None,
        chapter_from=None if scene_id or chapter_index is None else chapter_index,
        chapter_to=None if scene_id or chapter_index is None else chapter_index,
        # A chapter can map to any number of Scenes. The workbench's unbounded
        # mode is required here so the notice source never silently truncates.
        limit=1 if scene_id else None,
    )
    rows = [item for item in result.items if item.kind == "scene"]
    if scene_id:
        rows = [item for item in rows if str(item.scene.id) == scene_id]
    notices: list[dict[str, Any]] = []
    for item in rows:
        scene = item.scene
        for code, severity, summary in _scene_issues(item, chapter_index):
            basis = stable_hash(
                {
                    "scene_id": str(scene.id),
                    "code": code,
                    "scene_updated_at": (
                        scene.updated_at.isoformat() if scene.updated_at else None
                    ),
                    "title": scene.title,
                    "goal": scene.goal,
                    "core_conflict": scene.core_conflict,
                    "emotional_beat": scene.emotional_beat,
                    "pov_character_id": scene.pov_character_id,
                    "structure_meta": scene.structure_meta or {},
                    "health": item.health,
                    "chapter_ids": scene.chapter_ids or [],
                    "scene_chunks": scene.scene_chunks or [],
                    "chapter_index": chapter_index,
                }
            )
            notices.append(
                {
                    "notice_key": f"{SOURCE_ID}:{scene.id}:{code}",
                    "source_id": SOURCE_ID,
                    "category": "scene_structure",
                    "severity": severity,
                    "target": {
                        "scene_id": str(scene.id),
                        "chapter_index": chapter_index,
                    },
                    "summary": summary,
                    "evidence": [],
                    "basis_fingerprint": basis,
                    "stale": False,
                    "actions": [
                        {
                            "kind": "navigate",
                            "page": "outline",
                            "scene_id": str(scene.id),
                            "scene_field": _scene_field(code),
                            "label": "打开场景",
                        }
                    ],
                    "disposition_ref": None,
                }
            )
    return notices


NOTICE_SOURCE_SPEC = {
    "source_id": SOURCE_ID,
    "label": "场景结构",
    "list_notices": list_scene_structure_notices,
}
