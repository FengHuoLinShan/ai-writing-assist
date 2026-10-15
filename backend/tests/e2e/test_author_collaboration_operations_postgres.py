"""Author workspace operations through HTTP and independent PostgreSQL sessions."""

import asyncio
from uuid import uuid4

import pytest
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.main import app
from modules.account.contracts import BOOTSTRAP_ACCOUNT_ID
from modules.account.models import Account
from modules.collaboration.tests.test_workspaces import approve_trial, setup_trial
from modules.project.models import Project
from modules.writing.facade import get_latest_draft_for_chapter
from tests.e2e.config import require_e2e_database_url
from tests.support.http import XhrAsyncClient

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


async def test_workspace_http_create_edit_replay_and_concurrent_cas(monkeypatch):
    engine = create_async_engine(require_e2e_database_url(), pool_size=3)
    novel_id, foreign_id, foreign_owner = (uuid4() for _ in range(3))
    try:
        async with AsyncSession(engine) as db:
            if await db.get(Account, BOOTSTRAP_ACCOUNT_ID) is None:
                db.add(Account(id=BOOTSTRAP_ACCOUNT_ID, support_code=uuid4().hex))
            db.add(Account(id=foreign_owner, support_code=uuid4().hex))
            db.add_all(
                [
                    Project(id=novel_id, owner_id=BOOTSTRAP_ACCOUNT_ID, title="试改作品"),
                    Project(id=foreign_id, owner_id=foreign_owner, title="他人作品"),
                ]
            )
            await db.commit()
            case, existing, drafts, _parent = await setup_trial(
                db, str(novel_id), monkeypatch
            )
            await db.commit()

        base = "/api/collaboration/author-operations/workspaces"
        create = {
            "case_id": case["id"],
            "operation_id": str(uuid4()),
            "label": "作者另试一版",
            "parent_revision_id": None,
        }
        async with XhrAsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            forbidden = await client.post(
                f"{base}/create/prepare",
                params={"novel_id": str(foreign_id)},
                json=create,
            )
            assert forbidden.status_code == 404
            preview = await client.post(
                f"{base}/create/prepare",
                params={"novel_id": str(novel_id)},
                json=create,
            )
            assert preview.status_code == 200, preview.text
            confirmed = {
                **create,
                "expected_preview_hash": preview.json()["preview_hash"],
                "confirmed": True,
            }
            created = await client.post(
                f"{base}/create/confirm",
                params={"novel_id": str(novel_id)},
                json=confirmed,
            )
            assert created.status_code == 200, created.text
            workspace = created.json()["result"]
            repeated = await client.post(
                f"{base}/create/confirm",
                params={"novel_id": str(novel_id)},
                json=confirmed,
            )
            assert repeated.status_code == 200, repeated.text
            assert repeated.json()["result"]["id"] == workspace["id"]
            inspected = await client.post(
                f"{base}/inspect",
                params={"novel_id": str(novel_id)},
                json={"workspace_id": workspace["id"]},
            )
            assert inspected.status_code == 200, inspected.text
            assert inspected.json()["preview"]["revision_id"] == workspace["revision_id"]

            patch = {
                "kind": "writing_draft",
                "id": str(drafts[0].id),
                "operation": "replace",
                "value": {"title": drafts[0].title, "content": "她留下证据再离开。"},
            }
            edit = {
                "workspace_id": workspace["id"],
                "expected_revision_id": workspace["revision_id"],
                "patches": [patch],
            }
            edit_preview = await client.post(
                f"{base}/edit/prepare",
                params={"novel_id": str(novel_id)},
                json=edit,
            )
            assert edit_preview.status_code == 200, edit_preview.text
            edit_confirm = {
                **edit,
                "expected_preview_hash": edit_preview.json()["preview_hash"],
                "confirmed": True,
            }
            edited = await client.post(
                f"{base}/edit/confirm",
                params={"novel_id": str(novel_id)},
                json=edit_confirm,
            )
            assert edited.status_code == 200, edited.text
            replay = await client.post(
                f"{base}/edit/confirm",
                params={"novel_id": str(novel_id)},
                json=edit_confirm,
            )
            assert replay.status_code == 200, replay.text
            assert (
                replay.json()["result"]["revision_id"]
                == edited.json()["result"]["revision_id"]
            )

            parent = edited.json()["result"]["revision_id"]
            rival_edits = []
            for text in ("她查证了第一条线索。", "她查证了第二条线索。"):
                rival = {
                    **edit,
                    "expected_revision_id": parent,
                    "patches": [{**patch, "value": {**patch["value"], "content": text}}],
                }
                prepared = await client.post(
                    f"{base}/edit/prepare",
                    params={"novel_id": str(novel_id)},
                    json=rival,
                )
                assert prepared.status_code == 200, prepared.text
                rival_edits.append(
                    {
                        **rival,
                        "expected_preview_hash": prepared.json()["preview_hash"],
                        "confirmed": True,
                    }
                )
            outcomes = await asyncio.gather(
                *(
                    client.post(
                        f"{base}/edit/confirm",
                        params={"novel_id": str(novel_id)},
                        json=item,
                    )
                    for item in rival_edits
                )
            )
            assert sorted(item.status_code for item in outcomes) == [200, 409]

            async with AsyncSession(engine) as domain_db:
                await approve_trial(domain_db, str(novel_id), case, existing)
                await domain_db.commit()
            adoption = {
                "workspace_id": existing["id"],
                "revision_id": existing["revision_id"],
                "expected_digest": existing["digest"],
                "operation_id": str(uuid4()),
                "editor_state": "saved",
            }
            adoption_preview = await client.post(
                f"{base}/adoption/prepare",
                params={"novel_id": str(novel_id)},
                json=adoption,
            )
            assert adoption_preview.status_code == 200, adoption_preview.text
            assert adoption_preview.json()["preview"]["author_confirmation_required"]
            without_confirmation = await client.post(
                f"{base}/adoption/confirm",
                params={"novel_id": str(novel_id)},
                json=adoption,
            )
            assert without_confirmation.status_code == 409
            approved = {
                **adoption,
                "expected_preview_hash": adoption_preview.json()["preview_hash"],
                "confirmed": True,
            }
            adopted = await client.post(
                f"{base}/adoption/confirm",
                params={"novel_id": str(novel_id)},
                json=approved,
            )
            assert adopted.status_code == 200, adopted.text
            repeated_adoption = await client.post(
                f"{base}/adoption/confirm",
                params={"novel_id": str(novel_id)},
                json=approved,
            )
            assert repeated_adoption.status_code == 200, repeated_adoption.text
            assert repeated_adoption.json()["result"]["replayed"] is True
            receipt = await client.post(
                f"{base}/adoption/result",
                params={"novel_id": str(novel_id)},
                json=approved,
            )
            assert receipt.status_code == 200, receipt.text
            assert receipt.json()["receipt_id"] == adopted.json()["result"]["receipt_id"]
            async with AsyncSession(engine) as domain_db:
                draft = await get_latest_draft_for_chapter(domain_db, str(novel_id), 1)
                assert draft.content.endswith("她仍保留了退路。")
    finally:
        await engine.dispose()
