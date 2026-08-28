from __future__ import annotations

import uuid
from unittest.mock import patch

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
from modules.world.services.worldbuilding.world_validation_service import (
    WorldValidationService,
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
    assert draft.page_type == "custom"
    assert draft.free_text == "第一版"
    assert (
        draft.page_meta_json["worldbook_import"]["source_authority_hint"] == "candidate"
    )
    assert draft.page_meta_json["worldbook_import"]["activation_eligible"] is True

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
async def test_validation_policy_import_stays_a_draft_until_explicit_publish(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    service = WorldbookImportService()
    manifest = WorldbookImportManifest(
        files=[
            {
                "path": ".wiki/wiki/validation-policy.md",
                "content": (
                    "---\ntitle: 世界书校验策略\ntype: validation_policy\n"
                    "validation_policy:\n"
                    "  schema_version: world_validation_policy.v1\n"
                    "  policy_version: imported-v1\n"
                    "  semantic_enabled: false\n"
                    "---\n待作者审阅后发布。"
                ),
            }
        ]
    )
    preview = await service.preview(db_session, project_novel_id, manifest)
    result = await service.apply(
        db_session,
        project_novel_id,
        preview.suggestion_id,
        WorldbookImportApplyRequest(expected_preview_hash=preview.preview_hash),
    )
    draft = await db_session.scalar(
        select(WorldBiblePageDraft).where(
            WorldBiblePageDraft.id == uuid.UUID(result.draft_ids[0])
        )
    )
    assert draft is not None
    assert draft.page_type == "rule"
    assert draft.page_meta_json["validation_policy"]["policy_version"] == "imported-v1"
    assert (
        draft.page_meta_json["worldbook_import"]["source_authority_hint"] == "candidate"
    )
    assert (
        await WorldValidationService().active_policy(db_session, project_novel_id) is None
    )
    await WorldBibleLifecycleService()._seal_draft_for_admission(
        db_session, project_novel_id, str(draft.id)
    )
    active = await WorldValidationService().active_policy(db_session, project_novel_id)
    assert active is not None
    assert active[0].policy_version == "imported-v1"

    with pytest.raises(ValidationError, match="requires validation_policy"):
        await service.preview(
            db_session,
            project_novel_id,
            WorldbookImportManifest(
                files=[
                    {
                        "path": ".wiki/wiki/bad-policy.md",
                        "content": (
                            "---\ntitle: 坏策略\ntype: validation_policy\n---\n无配置"
                        ),
                    }
                ]
            ),
        )


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
    with pytest.raises(ValidationError, match="clean UTF-8"):
        await service.preview(
            db_session,
            project_novel_id,
            WorldbookImportManifest(
                files=[{"path": "world/bad.md", "content": "bad\ufffdtext"}]
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


@pytest.mark.asyncio
async def test_llmwiki_maps_raw_and_wiki_without_adopting_source_authority(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    service = WorldbookImportService()
    preview = await service.preview(
        db_session,
        project_novel_id,
        WorldbookImportManifest(
            files=[
                {"path": ".wiki/raw/interview.txt", "content": "原始访谈"},
                {
                    "path": ".wiki/wiki/tide-city.md",
                    "content": (
                        "---\ntitle: 潮汐城\ntype: location\n"
                        "canon_status: canonical\naliases: [潮城]\n"
                        "dependency:\n  target: 潮汐\n  relation: informs\n"
                        "---\n[[潮城]]"
                    ),
                },
            ]
        ),
    )

    assert preview.source_format == "llmwiki"
    assert {item.path: item.page_type for item in preview.items} == {
        ".wiki/raw/interview.txt": "source_material",
        ".wiki/wiki/tide-city.md": "location",
    }
    applied = await service.apply(
        db_session,
        project_novel_id,
        preview.suggestion_id,
        WorldbookImportApplyRequest(expected_preview_hash=preview.preview_hash),
    )
    drafts = list(
        (
            await db_session.execute(
                select(WorldBiblePageDraft).where(
                    WorldBiblePageDraft.id.in_(
                        [uuid.UUID(value) for value in applied.draft_ids]
                    )
                )
            )
        )
        .scalars()
        .all()
    )
    by_type = {draft.page_type: draft for draft in drafts}
    assert (
        by_type["source_material"].page_meta_json["worldbook_import"][
            "activation_eligible"
        ]
        is False
    )
    imported = by_type["location"].page_meta_json["worldbook_import"]
    assert imported["frontmatter"]["canon_status"] == "canonical"
    assert imported["frontmatter"]["dependency"]["relation"] == "informs"
    assert imported["source_authority_hint"] == "candidate"


@pytest.mark.asyncio
async def test_missing_source_marks_a_working_draft_without_deleting_content(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    service = WorldbookImportService()
    first = await service.preview(db_session, project_novel_id, _manifest("保留的正文"))
    first_apply = await service.apply(
        db_session,
        project_novel_id,
        first.suggestion_id,
        WorldbookImportApplyRequest(expected_preview_hash=first.preview_hash),
    )
    original_id = first_apply.draft_ids[0]

    missing = await service.preview(
        db_session,
        project_novel_id,
        WorldbookImportManifest(files=[{"path": "世界/其他.md", "content": "其他"}]),
    )
    assert missing.counts["missing"] == 1
    result = await service.apply(
        db_session,
        project_novel_id,
        missing.suggestion_id,
        WorldbookImportApplyRequest(expected_preview_hash=missing.preview_hash),
    )
    assert original_id in result.draft_ids
    original = await db_session.get(WorldBiblePageDraft, uuid.UUID(original_id))
    assert original is not None
    assert original.free_text == "保留的正文"
    assert original.page_meta_json["worldbook_import"]["source_missing"] is True

    restored = await service.preview(
        db_session, project_novel_id, _manifest("保留的正文")
    )
    restored_result = await service.apply(
        db_session,
        project_novel_id,
        restored.suggestion_id,
        WorldbookImportApplyRequest(expected_preview_hash=restored.preview_hash),
    )
    assert original_id in restored_result.draft_ids
    await db_session.refresh(original)
    assert original.free_text == "保留的正文"
    assert original.page_meta_json["worldbook_import"]["source_missing"] is False


@pytest.mark.asyncio
async def test_worldbook_import_rejects_case_collisions_and_corrupt_text(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    service = WorldbookImportService()
    with pytest.raises(ValidationError, match="Duplicate"):
        await service.preview(
            db_session,
            project_novel_id,
            WorldbookImportManifest(
                files=[
                    {"path": "World/A.md", "content": "a"},
                    {"path": "world/a.md", "content": "b"},
                ]
            ),
        )


@pytest.mark.asyncio
async def test_interrupted_import_apply_rolls_back_and_retries_atomically(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    service = WorldbookImportService()
    manifest = WorldbookImportManifest(
        files=[
            {"path": "world/a.md", "content": "A"},
            {"path": "world/b.md", "content": "B"},
        ]
    )
    preview = await service.preview(db_session, project_novel_id, manifest)
    await db_session.commit()
    original = WorldBibleLifecycleService.create_draft
    calls = 0

    async def interrupt_after_first(lifecycle, db, data):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("interrupted")
        return await original(lifecycle, db, data)

    with patch.object(
        WorldBibleLifecycleService,
        "create_draft",
        autospec=True,
        side_effect=interrupt_after_first,
    ):
        with pytest.raises(RuntimeError, match="interrupted"):
            await service.apply(
                db_session,
                project_novel_id,
                preview.suggestion_id,
                WorldbookImportApplyRequest(expected_preview_hash=preview.preview_hash),
            )
    await db_session.rollback()
    drafts = list(
        (
            await db_session.execute(
                select(WorldBiblePageDraft).where(
                    WorldBiblePageDraft.novel_id == uuid.UUID(project_novel_id)
                )
            )
        )
        .scalars()
        .all()
    )
    assert drafts == []

    retried = await service.apply(
        db_session,
        project_novel_id,
        preview.suggestion_id,
        WorldbookImportApplyRequest(expected_preview_hash=preview.preview_hash),
    )
    assert len(retried.draft_ids) == 2
