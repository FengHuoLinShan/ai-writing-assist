"""Author-only World Bible synopsis and explicitly selected draft loader."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.contracts import CompileOptions, StructureContextBundle
from modules.context.services.protocol import Loader


class WorldBibleLoader(Loader):
    @property
    def name(self) -> str:
        return "world_bible"

    async def load(
        self,
        db: AsyncSession,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> None:
        if (
            not options.include_world_synopsis
            and not options.selected_world_bible_draft_ids
        ):
            return
        if options.reveal_mode not in {"author_safe", "author_full"}:
            bundle.warnings.append(
                "excluded_visibility: 世界观简介和工作稿仅供作者模式使用"
            )
            return

        from modules.world.facade import (
            get_world_bible_synopsis_context,
            get_world_bible_working_pages_context,
        )

        if options.include_world_synopsis:
            synopsis = await get_world_bible_synopsis_context(
                db,
                options.novel_id,
                revision_id=options.world_synopsis_revision_id,
            )
            bundle.world_bible_synopsis = dict(synopsis.__dict__)
            if synopsis.revision_id:
                options.world_synopsis_revision_id = synopsis.revision_id
            options.world_synopsis_source_hash = synopsis.source_hash
            options.world_synopsis_block_hash = synopsis.block_hash
            if synopsis.stale:
                bundle.warnings.append("世界观简介已过期，使用最后成功版本或确定性降级")
            if synopsis.fallback:
                bundle.warnings.append("世界观简介尚无成功版本，已使用确定性降级资料")

        if options.selected_world_bible_draft_ids:
            bundle.world_bible_working_pages = (
                await get_world_bible_working_pages_context(
                    db,
                    options.novel_id,
                    draft_ids=options.selected_world_bible_draft_ids,
                )
            )


__all__ = ["WorldBibleLoader"]
