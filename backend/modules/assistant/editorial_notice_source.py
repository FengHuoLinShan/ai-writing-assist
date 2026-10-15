"""Read-only projection of the existing editorial issue queue into notices."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from core.errors import ConflictError
from infrastructure.stable_hash import stable_hash
from modules.assistant.editorial import decide_issue, list_issues
from modules.assistant.editorial_contracts import IssueDecision

SOURCE_ID = "assistant.editorial"


def _chapter_matches(issue: dict[str, Any], chapter_index: int) -> bool:
    finding = issue.get("finding") if isinstance(issue.get("finding"), dict) else {}
    for evidence in finding.get("evidence", []):
        if not isinstance(evidence, dict) or evidence.get("chapter_index") is None:
            continue
        try:
            if int(evidence["chapter_index"]) == chapter_index:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _notice(issue: dict[str, Any], chapter_index: int) -> dict[str, Any]:
    finding = issue.get("finding") if isinstance(issue.get("finding"), dict) else {}
    issue_id = str(issue["id"])
    review_id = str(issue.get("review_id") or "")
    disposition = str(issue.get("disposition") or "open")
    evidence = [item for item in finding.get("evidence", []) if isinstance(item, dict)][
        :20
    ]
    summary = str(
        finding.get("judgment")
        or finding.get("summary")
        or finding.get("description")
        or "有一条编辑意见待查看"
    ).strip()
    basis = stable_hash(
        {
            "issue_id": issue_id,
            "fingerprint": issue.get("fingerprint"),
            "row_version": int(issue.get("version") or 0),
            "disposition": disposition,
            "source_may_be_stale": bool(issue.get("source_may_be_stale")),
            "finding": finding,
        }
    )
    return {
        "notice_key": f"{SOURCE_ID}:{issue_id}",
        "source_id": SOURCE_ID,
        "category": str(finding.get("category") or "editorial_issue"),
        "severity": finding.get("severity")
        if finding.get("severity") in {"high", "medium", "low", "info"}
        else "low",
        "target": {"chapter_index": chapter_index, "issue_id": issue_id},
        "summary": summary[:4000] or "有一条编辑意见待查看",
        "evidence": evidence,
        "basis_fingerprint": basis,
        "stale": bool(issue.get("source_may_be_stale")),
        "actions": [
            {
                "kind": "navigate",
                "page": "assistant",
                "editorial": True,
                "issue_id": issue_id,
                "review_id": review_id,
                "chapter_index": chapter_index,
                "label": "查看编辑意见",
            }
        ],
        "disposition_ref": {
            "issue_id": issue_id,
            "review_id": review_id,
            "issue_row_version": int(issue.get("version") or 0),
        },
    }


async def list_editorial_notices(
    db, novel_id: str, scope: dict[str, object]
) -> list[dict[str, Any]]:
    raw_chapter = scope.get("chapter_index")
    if raw_chapter is None:
        # Editorial findings are chapter-bound. Scene-only scopes do not imply
        # an issue relationship; the writing cockpit always supplies a chapter.
        return []
    chapter_index = int(raw_chapter)
    issues = await list_issues(db, novel_id)
    return [
        _notice(issue, chapter_index)
        for issue in issues
        if issue.get("disposition") != "closed" and _chapter_matches(issue, chapter_index)
    ]


async def decide_editorial_notice(
    db,
    novel_id: str,
    item: dict[str, Any],
    action: str,
    wake_at,
) -> dict[str, Any] | None:
    # Read and timed snooze are presentation preferences. Ignore is the one
    # unified action that corresponds to an existing author issue decision.
    if action != "ignore":
        return None
    reference = item.get("disposition_ref") or {}
    issue_id = reference.get("issue_id")
    row_version = reference.get("issue_row_version")
    if not issue_id or not isinstance(row_version, int):
        raise ConflictError(
            "编辑意见版本暂不可用，请重新读取提醒", code="EDITORIAL_NOTICE_STALE"
        )
    await decide_issue(
        db,
        UUID(str(issue_id)),
        IssueDecision(
            novel_id=UUID(str(novel_id)),
            expected_version=row_version,
            disposition="closed",
            note="",
        ),
    )
    return {"status": "ignored", "issue_id": str(issue_id), "disposition": "closed"}


NOTICE_SOURCE_SPEC = {
    "source_id": SOURCE_ID,
    "label": "编辑员意见",
    "list_notices": list_editorial_notices,
    "decide": decide_editorial_notice,
}
