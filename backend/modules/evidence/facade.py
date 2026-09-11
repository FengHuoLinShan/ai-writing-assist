"""Single stable cross-module facade for evidence indexing and compilation."""

from modules.evidence.compilation.facade import *  # noqa: F403
from modules.evidence.indexing.facade import *  # noqa: F403


async def retrieve_focused_evidence(db, request, *, llm_client=None, before_llm=None):
    """Read the next scoped root/one-hop evidence slice; never adopt assets."""
    from modules.evidence.compilation.services.focused_evidence import (
        FocusedEvidenceService,
    )

    service = FocusedEvidenceService()
    result = await service.retrieve(
        db, request, llm_client=llm_client, before_llm=before_llm
    )
    await service.revalidate(db, request, result)
    return result


async def revalidate_focused_evidence(db, request, result):
    """Recheck the frozen source and selection before a consumer uses this slice."""
    from modules.evidence.compilation.services.focused_evidence import (
        FocusedEvidenceService,
    )

    return await FocusedEvidenceService().revalidate(db, request, result)


async def read_review_resolution_sources(db, **kwargs):
    from modules.evidence.compilation.services.review_resolution_sources import (
        read_sources,
    )

    return await read_sources(db, **kwargs)


async def read_review_resolution_chapters(db, **kwargs):
    from modules.evidence.compilation.services.review_resolution_sources import (
        read_chapters,
    )

    return await read_chapters(db, **kwargs)


async def read_review_resolution_evidence(db, *, novel_id, task_id, visibility):
    from core.errors import NotFoundError
    from modules.imports.facade import inspect_review_resolution

    if visibility.mode != "author":
        raise NotFoundError("整理结果仅对作者开放")
    return await inspect_review_resolution(
        db, novel_id=novel_id, task_id=task_id, cutoff_chapter=visibility.cutoff_chapter
    )
