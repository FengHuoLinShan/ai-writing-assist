"""Response-only canonical page comparison; never alters Story semantic content."""

from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from core.container import get
from core.service_keys import WORLD_READ_BIBLE_PAGE_REVISIONS
from modules.story.outline_state.story_outline_schemas import (
    StoryOutlineRevisionResponse,
    WorldCanonStaleness,
)


class PageRevisionReader(Protocol):
    async def __call__(
        self, db: AsyncSession, novel_id: str, page_ids: list[str]
    ) -> dict[str, dict[str, str]]: ...


async def with_canon_staleness(
    db: AsyncSession, novel_id: str, responses: list[StoryOutlineRevisionResponse]
) -> list[StoryOutlineRevisionResponse]:
    page_ids = sorted(
        {
            str(b.page_id)
            for r in responses
            for b in r.provenance.world_bible_page_revisions
        }
    )
    if not page_ids:
        return responses
    reader: PageRevisionReader = get(WORLD_READ_BIBLE_PAGE_REVISIONS)
    current = await reader(db, novel_id, page_ids)
    result = []
    for response in responses:
        baselines = response.provenance.world_bible_page_revisions
        if not baselines:
            result.append(response)
            continue
        changed = [
            b.page_id
            for b in baselines
            if current.get(str(b.page_id))
            != {
                "revision_id": str(b.revision_id),
                "revision_digest": b.revision_digest,
            }
        ]
        result.append(
            response.model_copy(
                update={
                    "canon_staleness": WorldCanonStaleness(
                        changed=bool(changed),
                        changed_page_ids=changed,
                    )
                }
            )
        )
    return result
