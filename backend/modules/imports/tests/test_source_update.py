from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import func, select

from core.errors import ConflictError, ValidationError
from modules.imports.models import ImportRecord
from modules.imports.source_update import SourceUpdateService
from modules.writing.facade import (
    create_published_draft_only,
    list_manuscript_sources,
)
from modules.writing.models import WritingDraft

pytestmark = pytest.mark.asyncio


def _file(*chapters: tuple[str, str]) -> bytes:
    return "\n\n".join(f"{title}\n{content}" for title, content in chapters).encode()


async def test_preview_is_read_only_and_apply_revalidates_same_file(
    db_session,
    project_factory,
) -> None:
    project_id = await project_factory.create_project(title="导入作品")
    content = _file(("第一章", "雾中火车到站。"), ("第二章", "来客走下站台。"))
    service = SourceUpdateService()

    preview, _chapters = await service.preview(
        db_session,
        project_id=str(project_id),
        title="导入作品",
        file_name="novel.txt",
        file_content=content,
        mode="full",
    )
    count_before = (
        await db_session.execute(select(func.count(WritingDraft.id)))
    ).scalar_one()
    applied = await service.apply(
        db_session,
        project_id=str(project_id),
        title="导入作品",
        file_name="novel.txt",
        file_content=content,
        mode="full",
        expected_preview_hash=preview.preview_hash,
        destructive_confirmed=False,
    )
    sources = await list_manuscript_sources(
        db_session,
        str(project_id),
        [1, 2],
        content_mode="canonical",
    )

    assert count_before == 0
    assert applied.changed_chapters == [1, 2]
    assert [item.chapter_index for item in sources] == [1, 2]


async def test_source_update_preview_hash_is_a_version_cas(
    db_session,
    project_factory,
) -> None:
    project_id = await project_factory.create_project(title="CAS 作品")
    await create_published_draft_only(
        db_session,
        str(project_id),
        1,
        "第一章",
        "旧内容",
    )
    service = SourceUpdateService()
    update = _file(("第一章", "预览时的新内容"))
    preview, _chapters = await service.preview(
        db_session,
        project_id=str(project_id),
        title="CAS 作品",
        file_name="novel.txt",
        file_content=update,
        mode="full",
    )
    await create_published_draft_only(
        db_session,
        str(project_id),
        1,
        "第一章",
        "另一个页面已先修改",
    )

    with pytest.raises(ConflictError, match="已变化"):
        await service.apply(
            db_session,
            project_id=str(project_id),
            title="CAS 作品",
            file_name="novel.txt",
            file_content=update,
            mode="full",
            expected_preview_hash=preview.preview_hash,
            destructive_confirmed=True,
        )


async def test_append_only_adds_after_last_chapter_and_full_removal_needs_confirmation(
    db_session,
    project_factory,
) -> None:
    project_id = await project_factory.create_project(title="连载")
    service = SourceUpdateService()
    initial = _file(("第一章", "一"), ("第二章", "二"))
    initial_preview, _ = await service.preview(
        db_session,
        project_id=str(project_id),
        title="连载",
        file_name="serial.txt",
        file_content=initial,
        mode="full",
    )
    await service.apply(
        db_session,
        project_id=str(project_id),
        title="连载",
        file_name="serial.txt",
        file_content=initial,
        mode="full",
        expected_preview_hash=initial_preview.preview_hash,
        destructive_confirmed=False,
    )

    append = _file(("新章", "三"))
    append_preview, _ = await service.preview(
        db_session,
        project_id=str(project_id),
        title="连载",
        file_name="append.txt",
        file_content=append,
        mode="append",
    )
    assert [(item.chapter_index, item.change) for item in append_preview.changes] == [
        (3, "added")
    ]

    reordered = _file(("第二章", "二"), ("第一章", "一"))
    reorder_preview, _ = await service.preview(
        db_session,
        project_id=str(project_id),
        title="连载",
        file_name="reordered.txt",
        file_content=reordered,
        mode="full",
    )
    assert [item.change for item in reorder_preview.changes] == [
        "reordered",
        "reordered",
    ]
    assert reorder_preview.requires_destructive_confirmation is True

    shorter = _file(("第一章", "一"))
    removal_preview, _ = await service.preview(
        db_session,
        project_id=str(project_id),
        title="连载",
        file_name="shorter.txt",
        file_content=shorter,
        mode="full",
    )
    assert any(item.change == "removed" for item in removal_preview.changes)
    with pytest.raises(ValidationError, match="再次确认"):
        await service.apply(
            db_session,
            project_id=str(project_id),
            title="连载",
            file_name="shorter.txt",
            file_content=shorter,
            mode="full",
            expected_preview_hash=removal_preview.preview_hash,
            destructive_confirmed=False,
        )


async def test_apply_failure_rolls_back_drafts_and_keeps_failed_import_record(
    db_session,
    project_factory,
) -> None:
    project_id = await project_factory.create_project(title="失败可恢复")
    service = SourceUpdateService()
    content = _file(("第一章", "正文"))
    preview, _ = await service.preview(
        db_session,
        project_id=str(project_id),
        title="失败可恢复",
        file_name="novel.txt",
        file_content=content,
        mode="full",
    )

    with (
        patch(
            "modules.imports.source_update.create_published_drafts_only",
            autospec=True,
            side_effect=RuntimeError("write failed"),
        ),
        pytest.raises(RuntimeError, match="write failed"),
    ):
        await service.apply(
            db_session,
            project_id=str(project_id),
            title="失败可恢复",
            file_name="novel.txt",
            file_content=content,
            mode="full",
            expected_preview_hash=preview.preview_hash,
            destructive_confirmed=False,
        )

    record = (
        await db_session.execute(
            select(ImportRecord).where(ImportRecord.novel_id == project_id)
        )
    ).scalar_one()
    drafts = await db_session.scalar(
        select(func.count(WritingDraft.id)).where(WritingDraft.novel_id == project_id)
    )
    assert record.status == "failed"
    assert drafts == 0
