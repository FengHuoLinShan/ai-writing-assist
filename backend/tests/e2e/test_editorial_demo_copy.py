"""Local demo copies carry author intent and drafts, not private editor history."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import AccountPrincipal
from modules.account.models import Account
from modules.account.public_demo import PublicDemoConfig
from modules.assistant.editorial_models import EditorialIssue, EditorialReview
from modules.project.demo_copy import DemoProjectCopyService
from modules.project.editorial_brief import EditorialBrief
from modules.project.facade import read_editorial_brief
from modules.project.models import Project
from modules.writing.facade import create_draft_only
from modules.writing.models import WritingDraft
from modules.writing.schemas import EditorialReadyRequest
from modules.writing.services import WritingDraftService
from tests.e2e.config import DATABASE_URL

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


async def test_disposable_demo_copy_can_enter_editorial_flow_without_private_history(
    monkeypatch,
):
    engine = create_async_engine(DATABASE_URL, pool_size=3, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    source_owner, target_owner, source_id = uuid4(), uuid4(), uuid4()
    copy_id = None
    brief = EditorialBrief(voice="保留慢节奏和第一人称").model_dump()
    monkeypatch.setattr(
        "modules.project.demo_copy.configured_public_demo",
        lambda: PublicDemoConfig(
            enabled=True, project_id=source_id, version="editorial-test-v1"
        ),
    )
    try:
        async with sessions.begin() as db:
            db.add_all(
                [
                    Account(
                        id=source_owner, status="active", support_code="EDITORIAL-SOURCE"
                    ),
                    Account(
                        id=target_owner, status="active", support_code="EDITORIAL-TARGET"
                    ),
                ]
            )
            await db.flush()
            db.add(
                Project(
                    id=source_id,
                    owner_id=source_owner,
                    title="Synthetic demo source",
                    settings={"editorial_brief_v1": {"version": 1, "brief": brief}},
                )
            )
            await db.flush()
            draft = await create_draft_only(
                db, str(source_id), 1, "第一章", "她在码头找到一封信。"
            )
            private_review = EditorialReview(
                novel_id=source_id,
                owner_id=source_owner,
                operation_id=uuid4(),
                status="completed",
                scope_json={},
                brief_json={},
                source_json=[],
                progress_json={},
                report_json={"summary": "私人意见"},
                llm_snapshot_json={},
            )
            db.add(private_review)
            await db.flush()
            db.add(
                EditorialIssue(
                    novel_id=source_id,
                    review_id=private_review.id,
                    fingerprint="a" * 64,
                    finding_json={"judgment": "私人问题"},
                    decision_json=[],
                    history_json=[],
                    recheck_json=[],
                )
            )
            source_draft_id = draft.id
        token = bind_principal(
            AccountPrincipal(
                account_id=target_owner,
                status="active",
                identity_type="email",
                support_code="EDITORIAL-TARGET",
            )
        )
        try:
            async with sessions.begin() as db:
                copied = await DemoProjectCopyService().copy(db)
                copy_id = copied.project.id
                assert copied.status == "created"
                assert copied.project.settings["editorial_brief_v1"]["version"] == 1
            async with sessions.begin() as db:
                assert (await read_editorial_brief(db, copy_id))["brief"] == brief
                draft = await db.scalar(
                    select(WritingDraft).where(WritingDraft.novel_id == UUID(copy_id))
                )
                assert draft is not None and draft.id != source_draft_id
                assert draft.content == "她在码头找到一封信。"
                assert (
                    await db.scalar(
                        select(EditorialReview).where(
                            EditorialReview.novel_id == UUID(copy_id)
                        )
                    )
                    is None
                )
                assert (
                    await db.scalar(
                        select(EditorialIssue).where(
                            EditorialIssue.novel_id == UUID(copy_id)
                        )
                    )
                    is None
                )
                ready = await WritingDraftService().mark_editorial_ready(
                    db,
                    str(draft.id),
                    copy_id,
                    EditorialReadyRequest(expected_content_hash=draft.content_hash),
                )
                assert ready.editorial_ready_hash == draft.content_hash
        finally:
            reset_principal(token)
    finally:
        async with sessions.begin() as db:
            if copy_id:
                await db.execute(delete(Project).where(Project.id == UUID(copy_id)))
            await db.execute(delete(Project).where(Project.id == source_id))
            await db.execute(
                delete(Account).where(Account.id.in_([source_owner, target_owner]))
            )
        await engine.dispose()
