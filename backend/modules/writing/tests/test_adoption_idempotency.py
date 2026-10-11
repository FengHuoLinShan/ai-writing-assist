"""采用幂等键用例（BR-0b 交接 P0-4「确认回包丢失后重复点击」）。

作者对同一候选的采用请求可能因回包丢失而重放；携带同一幂等键的重放必须
返回原采用回执，而不是把已废弃候选当错误抛给作者。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from core.errors import ValidationError
from modules.evidence.compilation.facade import attach_result_ref, confirm_context
from modules.evidence.contracts import ContextConfirmationRequest
from modules.writing.models import WritingDraft
from modules.writing.repositories import WritingDraftRepository
from modules.writing.schemas import WritingDraftCreate
from modules.writing.services import WritingDraftService


async def _adoptable_candidate(db_session, novel_id: str) -> tuple[object, object]:
    confirmation = await confirm_context(
        db_session,
        ContextConfirmationRequest(
            novel_id=novel_id,
            action="writing.generate",
            task="采用幂等候选",
            scope="chapter",
            chapter_index=1,
        ),
    )
    candidate = await WritingDraftRepository().create_with_status(
        db_session,
        WritingDraftCreate(
            novel_id=novel_id,
            chapter_index=1,
            title="AI 建议",
            content="待采用正文",
            provenance_json={
                "source": "writing_generate",
                "context_confirmation_id": str(confirmation.id),
                "source_confirmation_id": str(confirmation.id),
                "knowledge_review": {"status": "passed"},
            },
        ),
        status="candidate",
    )
    await attach_result_ref(
        db_session,
        novel_id=novel_id,
        confirmation_id=confirmation.id,
        result_type="writing_draft",
        result_id=str(candidate.id),
        status="done",
    )
    return confirmation, candidate


async def _count_working_drafts(db_session, novel_id: str) -> int:
    result = await db_session.execute(
        select(func.count(WritingDraft.id)).where(
            WritingDraft.novel_id == uuid.UUID(str(novel_id)),
            WritingDraft.status != "deprecated",
        )
    )
    return int(result.scalar() or 0)


@pytest.mark.asyncio
async def test_adopt_replay_with_same_key_returns_original_receipt(
    db_session,
    test_project_id,
    monkeypatch,
) -> None:
    async def accept_candidate(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(
        "modules.writing.semantic_review.validate_candidate_upstream",
        accept_candidate,
    )
    _confirmation, candidate = await _adoptable_candidate(db_session, test_project_id)
    service = WritingDraftService()
    key = "adopt-key-1"

    first = await service.adopt_candidate_to_working(
        db_session,
        str(candidate.id),
        test_project_id,
        idempotency_key=key,
    )
    assert first.status != "deprecated"

    # 回包丢失后的重放：同一键返回原回执，不产生第二个工作稿
    replay = await service.adopt_candidate_to_working(
        db_session,
        str(candidate.id),
        test_project_id,
        idempotency_key=key,
    )
    assert replay.id == first.id
    assert await _count_working_drafts(db_session, test_project_id) == 1

    stored = await WritingDraftRepository().get(db_session, candidate.id)
    assert stored is not None
    assert stored.status == "deprecated"
    assert stored.provenance_json["adoption_idempotency_key"] == key
    assert stored.provenance_json["adoption_result_draft_id"] == str(first.id)


@pytest.mark.asyncio
async def test_adopt_replay_without_key_or_with_other_key_still_rejected(
    db_session,
    test_project_id,
    monkeypatch,
) -> None:
    async def accept_candidate(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(
        "modules.writing.semantic_review.validate_candidate_upstream",
        accept_candidate,
    )
    _confirmation, candidate = await _adoptable_candidate(db_session, test_project_id)
    service = WritingDraftService()
    await service.adopt_candidate_to_working(
        db_session,
        str(candidate.id),
        test_project_id,
        idempotency_key="adopt-key-1",
    )

    # 无键（旧客户端行为）或不同键：维持原校验错误，不返回原回执
    with pytest.raises(ValidationError, match="candidate"):
        await service.adopt_candidate_to_working(
            db_session,
            str(candidate.id),
            test_project_id,
        )
    with pytest.raises(ValidationError, match="candidate"):
        await service.adopt_candidate_to_working(
            db_session,
            str(candidate.id),
            test_project_id,
            idempotency_key="adopt-key-2",
        )
    assert await _count_working_drafts(db_session, test_project_id) == 1


@pytest.mark.asyncio
async def test_adopt_route_replay_with_idempotency_key(
    async_client,
    db_session,
    monkeypatch,
) -> None:
    """API 层：同键重放返回原采用回执，无键重放维持 4xx。"""

    async def accept_candidate(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(
        "modules.writing.semantic_review.validate_candidate_upstream",
        accept_candidate,
    )
    project_resp = await async_client.post("/api/projects", json={"title": "采用幂等"})
    novel_id = project_resp.json()["id"]
    _confirmation, candidate = await _adoptable_candidate(db_session, novel_id)
    url = f"/api/writing/drafts/{candidate.id}/adopt?novel_id={novel_id}"
    key = "route-adopt-key"

    first = await async_client.post(f"{url}&idempotency_key={key}")
    assert first.status_code == 200, first.text
    replay = await async_client.post(f"{url}&idempotency_key={key}")
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == first.json()["id"]
    assert await _count_working_drafts(db_session, novel_id) == 1

    no_key = await async_client.post(url)
    assert no_key.status_code == 400
    wrong_key = await async_client.post(f"{url}&idempotency_key=other-key")
    assert wrong_key.status_code == 400
