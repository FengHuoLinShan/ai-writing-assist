"""Preview and apply versioned manuscript updates for RP source projects."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections import defaultdict
from dataclasses import asdict

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from core.errors import ConflictError, ValidationError
from modules.imports.contracts import (
    SourceUpdateApplyContract,
    SourceUpdateChapterContract,
    SourceUpdatePreviewContract,
)
from modules.imports.parsers import parse_file
from modules.imports.repositories import ImportRecordRepository
from modules.imports.services import ImportService
from modules.project.facade import require_active_project_exclusive
from modules.writing.facade import (
    create_published_drafts_only,
    deprecate_chapter_versions,
    list_effective_chapter_indices,
    list_manuscript_sources,
)
from shared.utils import parse_uuid


class SourceUpdateService:
    """One deterministic file diff reused by preview and confirmed apply."""

    def __init__(self, records: ImportRecordRepository | None = None) -> None:
        self._records = records or ImportRecordRepository()

    async def preview(
        self,
        db: AsyncSession,
        *,
        project_id: str | None,
        title: str,
        file_name: str,
        file_content: bytes,
        mode: str,
    ) -> tuple[SourceUpdatePreviewContract, list[dict]]:
        if mode not in {"full", "append"}:
            raise ValidationError("更新方式必须是完整稿或追加稿")
        clean_title = " ".join(str(title or "").split())[:255]
        if not clean_title:
            raise ValidationError("作品名称不能为空")
        safe_name = os.path.basename(file_name or "")
        file_type = ImportService._validate_file(safe_name, len(file_content))
        chapters = await asyncio.to_thread(parse_file, file_content, file_type)
        if not chapters:
            raise ValidationError("文件中未检测到有效章节")
        max_chapters = get_settings().import_max_chapters
        if len(chapters) > max_chapters:
            raise ValidationError(
                f"导入章节数 {len(chapters)} 超过上限 {max_chapters}",
                status_code=413,
            )

        existing = {}
        if project_id:
            indices = await list_effective_chapter_indices(db, project_id)
            existing = {
                item.chapter_index: item
                for item in await list_manuscript_sources(
                    db,
                    project_id,
                    indices,
                    content_mode="canonical",
                )
            }

        start = max(existing, default=0) + 1 if mode == "append" else 1
        prepared = [
            {
                "chapter_index": start + offset,
                "title": str(item.get("title") or f"第{start + offset}章"),
                "content": str(item.get("content") or ""),
            }
            for offset, item in enumerate(chapters)
        ]
        prepared_indices = {item["chapter_index"] for item in prepared}
        existing_positions: dict[tuple[str, str], set[int]] = defaultdict(set)
        for index, item in existing.items():
            existing_positions[(str(item.title or ""), item.content_hash)].add(index)
        changes: list[SourceUpdateChapterContract] = []
        for item in prepared:
            previous = existing.get(item["chapter_index"])
            content_hash = _hash_text(item["content"])
            if (
                previous is not None
                and previous.content_hash == content_hash
                and previous.title == item["title"]
            ):
                change = "unchanged"
            elif mode == "full" and any(
                index != item["chapter_index"]
                for index in existing_positions.get((item["title"], content_hash), set())
            ):
                change = "reordered"
            elif previous is None:
                change = "added"
            else:
                change = "changed"
            changes.append(
                SourceUpdateChapterContract(
                    chapter_index=item["chapter_index"],
                    title=item["title"],
                    content_hash=content_hash,
                    change=change,
                )
            )
        if mode == "full":
            changes.extend(
                SourceUpdateChapterContract(
                    chapter_index=index,
                    title=str(existing[index].title or f"第{index}章"),
                    content_hash=existing[index].content_hash,
                    change="removed",
                )
                for index in sorted(set(existing) - prepared_indices)
            )

        preview_hash = hashlib.sha256(
            json.dumps(
                {
                    "project_id": project_id,
                    "title": clean_title,
                    "mode": mode,
                    "file_name": safe_name,
                    "file_hash": hashlib.sha256(file_content).hexdigest(),
                    "base_manifest": [
                        {
                            "chapter_index": index,
                            "draft_id": item.id,
                            "version_number": item.version_number,
                            "content_hash": item.content_hash,
                            "title": item.title,
                        }
                        for index, item in sorted(existing.items())
                    ],
                    "changes": [asdict(item) for item in changes],
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        return (
            SourceUpdatePreviewContract(
                preview_hash=preview_hash,
                mode=mode,
                title=clean_title,
                project_id=project_id,
                chapter_count=len(prepared),
                changes=changes,
                requires_destructive_confirmation=any(
                    item.change in {"changed", "removed", "reordered"} for item in changes
                ),
            ),
            prepared,
        )

    async def apply(
        self,
        db: AsyncSession,
        *,
        project_id: str,
        title: str,
        file_name: str,
        file_content: bytes,
        mode: str,
        expected_preview_hash: str,
        destructive_confirmed: bool,
    ) -> SourceUpdateApplyContract:
        await require_active_project_exclusive(db, project_id)
        preview, chapters = await self.preview(
            db,
            project_id=project_id,
            title=title,
            file_name=file_name,
            file_content=file_content,
            mode=mode,
        )
        if preview.preview_hash != expected_preview_hash:
            raise ConflictError("作品内容或章节版本已变化，请重新预览")
        if preview.requires_destructive_confirmation and not destructive_confirmed:
            raise ValidationError("修改、移除或重排既有章节需要再次确认")

        changed = {
            item.chapter_index
            for item in preview.changes
            if item.change in {"added", "changed", "reordered"}
        }
        removed = {
            item.chapter_index for item in preview.changes if item.change == "removed"
        }
        file_type = ImportService._validate_file(file_name, len(file_content))
        record = await self._records.create(
            db,
            parse_uuid(project_id, "project_id"),
            os.path.basename(file_name),
            file_type,
            len(file_content),
            import_kind="source_revision",
        )
        try:
            async with db.begin_nested():
                if changed:
                    await create_published_drafts_only(
                        db,
                        project_id,
                        [item for item in chapters if item["chapter_index"] in changed],
                    )
                for chapter_index in sorted(removed):
                    await deprecate_chapter_versions(db, project_id, chapter_index)
            await self._records.update_status(
                db,
                record.id,
                status="done",
                total_chapters=len(chapters),
                imported_chapters=len(changed),
            )
        except Exception:
            await self._records.update_status(
                db,
                record.id,
                status="failed",
                error_message="作品版本更新失败，请重试",
            )
            raise
        indices = [item["chapter_index"] for item in chapters]
        return SourceUpdateApplyContract(
            project_id=project_id,
            import_record_id=str(record.id),
            chapter_count=len(indices),
            first_chapter=min(indices),
            last_chapter=max(indices),
            changed_chapters=sorted(changed | removed),
        )


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
