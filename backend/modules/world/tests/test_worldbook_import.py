from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, ValidationError
from modules.world.models import ConflictCheckQueueItem, WorldBiblePageDraft
from modules.world.schemas import (
    WorldBiblePageDraftUpdate,
    WorldbookImportApplyRequest,
    WorldbookImportManifest,
)
from modules.world.services.worldbuilding.world_bible_lifecycle_service import (
    WorldBibleLifecycleService,
)
from modules.world.services.worldbuilding.worldbook_import_service import (
    WorldbookImportService,
)


def _manifest(content: str) -> WorldbookImportManifest:
    return WorldbookImportManifest(
        files=[
            {"path": ".obsidian/app.json", "content": "{}"},
            {"path": "AGENTS.md", "content": "ignore me"},
            {"path": "scripts/check.rb", "content": "puts 'ignore me'"},
            {
                "path": "世界/潮汐城.md",
                "content": f"---\ntitle: 潮汐城\n---\n{content}",
            },
        ]
    )


@pytest.mark.asyncio
async def test_worldbook_import_three_way_update_and_conflict(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    service = WorldbookImportService()
    first = await service.preview(db_session, project_novel_id, _manifest("第一版"))
    assert first.source_format == "obsidian"
    assert first.counts == {
        "create": 1,
        "update": 0,
        "preserve": 0,
        "conflict": 0,
        "missing": 0,
    }
    assert first.ignored_paths == [
        ".obsidian/app.json",
        "AGENTS.md",
        "scripts/check.rb",
    ]
    applied = await service.apply(
        db_session,
        project_novel_id,
        first.suggestion_id,
        WorldbookImportApplyRequest(expected_preview_hash=first.preview_hash),
    )
    assert applied.status == "accepted"
    draft = await db_session.scalar(
        select(WorldBiblePageDraft).where(
            WorldBiblePageDraft.id == uuid.UUID(applied.draft_ids[0])
        )
    )
    assert draft is not None
    assert draft.page_type == "source_material"
    assert draft.free_text == "第一版"
    assert (
        draft.page_meta_json["worldbook_import"]["source_authority_hint"] == "candidate"
    )

    unchanged = await service.preview(db_session, project_novel_id, _manifest("第一版"))
    assert unchanged.counts["preserve"] == 1

    changed = await service.preview(db_session, project_novel_id, _manifest("第二版"))
    assert changed.counts["update"] == 1
    await service.apply(
        db_session,
        project_novel_id,
        changed.suggestion_id,
        WorldbookImportApplyRequest(expected_preview_hash=changed.preview_hash),
    )
    await db_session.refresh(draft)
    assert draft.free_text == "第二版"

    await WorldBibleLifecycleService().update_draft(
        db_session,
        project_novel_id,
        str(draft.id),
        WorldBiblePageDraftUpdate(free_text="作者本地修改"),
    )
    conflict_preview = await service.preview(
        db_session, project_novel_id, _manifest("第三版")
    )
    assert conflict_preview.counts["conflict"] == 1
    conflict_result = await service.apply(
        db_session,
        project_novel_id,
        conflict_preview.suggestion_id,
        WorldbookImportApplyRequest(expected_preview_hash=conflict_preview.preview_hash),
    )
    await db_session.refresh(draft)
    assert draft.free_text == "作者本地修改"
    assert len(conflict_result.conflict_ids) == 1
    conflict = await db_session.scalar(
        select(ConflictCheckQueueItem).where(
            ConflictCheckQueueItem.id == uuid.UUID(conflict_result.conflict_ids[0])
        )
    )
    assert conflict is not None
    assert conflict.conflict_type == "worldbook_import_conflict"
    assert conflict.resolution_json["author_action"] == "needs_decision"


@pytest.mark.asyncio
async def test_worldbook_import_rejects_unsafe_paths_yaml_and_stale_apply(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    service = WorldbookImportService()
    with pytest.raises(ValidationError, match="unsafe"):
        await service.preview(
            db_session,
            project_novel_id,
            WorldbookImportManifest(files=[{"path": "../secret.md", "content": "x"}]),
        )
    with pytest.raises(ValidationError, match="aliases"):
        await service.preview(
            db_session,
            project_novel_id,
            WorldbookImportManifest(
                files=[
                    {
                        "path": "bad.md",
                        "content": "---\ntitle: &name bad\ncopy: *name\n---\nx",
                    }
                ]
            ),
        )

    preview = await service.preview(db_session, project_novel_id, _manifest("初版"))
    await WorldbookImportService().preview(
        db_session,
        project_novel_id,
        WorldbookImportManifest(files=[{"path": "另一个.md", "content": "并发变化"}]),
    )
    with pytest.raises(ConflictError, match="target changed"):
        await service.apply(
            db_session,
            project_novel_id,
            preview.suggestion_id,
            WorldbookImportApplyRequest(expected_preview_hash="0" * 64),
        )


@pytest.mark.asyncio
async def test_worldbook_import_api_keeps_preview_compact(
    async_client: AsyncClient,
    project_novel_id: str,
) -> None:
    response = await async_client.post(
        f"/api/world/bible/imports/preview?novel_id={project_novel_id}",
        json={
            "schema_version": "world_worldbook_import.v1",
            "files": [{"path": "世界/城市.md", "content": "不会回显的正文"}],
        },
    )
    assert response.status_code == 201
    preview = response.json()
    assert "不会回显的正文" not in response.text
    applied = await async_client.post(
        f"/api/world/bible/imports/{preview['suggestion_id']}/apply?novel_id={project_novel_id}",
        json={"expected_preview_hash": preview["preview_hash"]},
    )
    assert applied.status_code == 200
    assert applied.json()["counts"]["create"] == 1
