"""Pure unified-notice source contract for deterministic Scene Director findings.

The application notice registry composes this read-only source for the author
workbench alongside the other domain notice providers.
"""

from __future__ import annotations

from typing import Any

from infrastructure.stable_hash import stable_hash
from modules.story.director_service import list_director_history

SOURCE_ID = "story.scene_director"


async def list_scene_director_notices(
    db, novel_id: str, scope: dict[str, object]
) -> list[dict[str, Any]]:
    scene_id = str(scope.get("scene_id") or "")
    if not scene_id:
        return []
    history = await list_director_history(db, novel_id, scene_id, purge_expired=False)
    branches = {item["id"]: item for item in history.get("branches", [])}
    notices: list[dict[str, Any]] = []
    for round_item in history.get("rounds", []):
        branch = branches.get(round_item.get("branch_id"))
        if branch is None:
            continue
        consistency = round_item.get("consistency") or {}
        for finding in consistency.get("findings") or []:
            severity = finding.get("severity")
            field = str(finding.get("field") or "")
            is_candidate = field in {"candidate", "candidate_event"}
            if severity not in {"conflict", "unknown", "notice"}:
                continue
            if severity == "notice" and not is_candidate:
                continue
            content = {
                "round_id": round_item.get("id"),
                "round_output_hash": round_item.get("output_hash"),
                "finding": finding,
            }
            digest = stable_hash(content)
            label = "场景导演候选" if is_candidate else "场景导演一致性"
            summary = str(finding.get("statement") or "导演输出需要作者核对")
            evidence = [
                {
                    "field": str(finding.get("field") or "consistency"),
                    "finding_hash": digest,
                }
            ]
            notices.append(
                {
                    "notice_key": f"{SOURCE_ID}:{digest[:32]}",
                    "source_id": SOURCE_ID,
                    "category": "scene_director_consistency",
                    "severity": "info"
                    if is_candidate
                    else "medium"
                    if severity == "conflict"
                    else "low",
                    "target": {
                        "scene_id": scene_id,
                        "director_round_id": round_item.get("id"),
                    },
                    "summary": f"{label}：{summary}",
                    "evidence": evidence,
                    "basis_fingerprint": digest,
                    "stale": False,
                    "actions": [
                        {
                            "kind": "navigate",
                            "page": "story",
                            "scene_id": scene_id,
                            "tab": "director",
                            "label": "打开场景导演",
                        }
                    ],
                    "disposition_ref": None,
                }
            )
    return notices


NOTICE_SOURCE_SPEC = {
    "source_id": SOURCE_ID,
    "label": "场景导演一致性",
    "list_notices": list_scene_director_notices,
}
