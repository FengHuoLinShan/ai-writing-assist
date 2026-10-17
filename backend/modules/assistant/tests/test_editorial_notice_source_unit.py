"""Offline contract tests for the editorial notice projection."""

from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from modules.assistant import editorial_notice_source as source

NOVEL_ID = "11111111-1111-4111-8111-111111111111"
ISSUE_ID = "22222222-2222-4222-8222-222222222222"


def issue(*, chapter=3, version=4, disposition="open", stale=False):
    return {
        "id": ISSUE_ID,
        "fingerprint": "f" * 64,
        "review_id": "33333333-3333-4333-8333-333333333333",
        "version": version,
        "disposition": disposition,
        "source_may_be_stale": stale,
        "finding": {
            "category": "scene",
            "severity": "high",
            "judgment": "人物选择缺少前因",
            "evidence": [{"chapter_index": chapter, "quote": "他转身离开。"}],
        },
    }


@pytest.mark.asyncio
async def test_list_only_projects_open_issues_from_requested_chapter(monkeypatch):
    monkeypatch.setattr(
        source,
        "list_issues",
        AsyncMock(return_value=[issue(), issue(chapter=4), issue(disposition="closed")]),
    )

    result = await source.list_editorial_notices(object(), NOVEL_ID, {"chapter_index": 3})

    assert len(result) == 1
    assert result[0]["source_id"] == "assistant.editorial"
    assert result[0]["notice_key"] == f"assistant.editorial:{ISSUE_ID}"
    assert result[0]["target"] == {"chapter_index": 3, "issue_id": ISSUE_ID}
    assert result[0]["stale"] is False
    assert result[0]["actions"][0]["issue_id"] == ISSUE_ID


@pytest.mark.asyncio
async def test_ignore_forwards_to_existing_closed_issue_decision(monkeypatch):
    decide_issue = AsyncMock(return_value=[{"id": ISSUE_ID}])
    monkeypatch.setattr(source, "decide_issue", decide_issue)
    item = source._notice(issue(), 3)

    result = await source.decide_editorial_notice(
        object(), NOVEL_ID, item, "ignore", None
    )

    assert result == {"status": "ignored", "issue_id": ISSUE_ID, "disposition": "closed"}
    decide_issue.assert_awaited_once()
    assert decide_issue.await_args.args[1] == UUID(ISSUE_ID)
    decision = decide_issue.await_args.args[2]
    assert decision.novel_id == UUID(NOVEL_ID)
    assert decision.expected_version == 4
    assert decision.disposition == "closed"


@pytest.mark.asyncio
async def test_read_and_snooze_leave_editorial_issue_facts_untouched(monkeypatch):
    decide_issue = AsyncMock()
    monkeypatch.setattr(source, "decide_issue", decide_issue)
    item = source._notice(issue(), 3)

    assert (
        await source.decide_editorial_notice(object(), NOVEL_ID, item, "read", None)
        is None
    )
    assert (
        await source.decide_editorial_notice(object(), NOVEL_ID, item, "snooze", None)
        is None
    )
    decide_issue.assert_not_awaited()


def test_editorial_notice_basis_changes_with_domain_row_version():
    old = source._notice(issue(version=4), 3)
    new = source._notice(issue(version=5), 3)

    assert old["basis_fingerprint"] != new["basis_fingerprint"]
    assert old["disposition_ref"]["issue_row_version"] == 4
    assert new["disposition_ref"]["issue_row_version"] == 5
    assert "row_version" not in old
