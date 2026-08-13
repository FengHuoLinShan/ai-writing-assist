from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.errors import ConflictError
from modules.writing.schemas import (
    WritingSemanticReviewRequest,
    WritingTargetedRevisionRequest,
    project_writing_draft_state,
)
from modules.writing.semantic_review import validate_candidate_upstream


def test_semantic_review_requests_are_bounded_and_deduplicated() -> None:
    request = WritingSemanticReviewRequest(
        novel_id="00000000-0000-0000-0000-000000000001",
        draft_ids=["00000000-0000-0000-0000-000000000002"],
        scope="book",
    )
    assert request.scope == "book"

    with pytest.raises(ValueError, match="draft_ids must be unique"):
        WritingSemanticReviewRequest(
            novel_id=request.novel_id,
            draft_ids=[request.draft_ids[0], request.draft_ids[0]],
        )

    revision = WritingTargetedRevisionRequest(
        novel_id=request.novel_id,
        draft_id=request.draft_ids[0],
        review_task_id="00000000-0000-0000-0000-000000000003",
        finding_ids=["finding_123"],
    )
    assert revision.finding_ids == ["finding_123"]


def test_candidate_projection_exposes_independent_review_gate() -> None:
    pending = project_writing_draft_state(
        "candidate",
        {"source": "writing_generate", "review_required": True},
    )
    assert pending["attention_reasons"] == ["semantic_review_required"]

    blocked = project_writing_draft_state(
        "candidate",
        {
            "source": "writing_generate",
            "review_required": True,
            "independent_review": {
                "verdict": "needs_revision",
                "blocking_count": 2,
            },
        },
    )
    assert blocked["attention_reasons"] == ["semantic_review_blocked"]


@pytest.mark.anyio
async def test_generated_candidate_requires_matching_independent_review() -> None:
    draft = SimpleNamespace(
        novel_id="00000000-0000-0000-0000-000000000001",
        content_hash="a" * 64,
        provenance_json={
            "source": "writing_generate",
            "review_required": True,
        },
    )
    with pytest.raises(ConflictError, match="独立语义审查"):
        await validate_candidate_upstream(None, draft)  # type: ignore[arg-type]

    draft.provenance_json["independent_review"] = {
        "draft_hash": draft.content_hash,
        "verdict": "pass",
        "blocking_count": 0,
    }
    await validate_candidate_upstream(None, draft)  # type: ignore[arg-type]
