"""Read-only page revision identities for downstream consumption baselines."""

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.models import WorldBiblePage, WorldBiblePageRevision
from shared.utils import parse_uuid


async def read_world_bible_page_revisions(
    db: AsyncSession, novel_id: str, page_ids: list[str]
) -> dict[str, dict[str, str]]:
    """Read adopted page versions in one query; absent/unadopted pages are missing."""
    if not page_ids:
        return {}
    rows = await db.execute(
        select(
            WorldBiblePage.id,
            WorldBiblePageRevision.id,
            WorldBiblePageRevision.revision_digest,
        )
        .join(
            WorldBiblePageRevision,
            and_(
                WorldBiblePageRevision.page_id == WorldBiblePage.id,
                WorldBiblePageRevision.novel_id == WorldBiblePage.novel_id,
                WorldBiblePageRevision.version_number == WorldBiblePage.version_number,
            ),
        )
        .where(
            WorldBiblePage.novel_id == parse_uuid(novel_id, "novel_id"),
            WorldBiblePage.id.in_([parse_uuid(p, "page_id") for p in set(page_ids)]),
            WorldBiblePage.status.in_({"canonical", "confirmed"}),
        )
    )
    return {
        str(page_id): {"revision_id": str(revision_id), "revision_digest": digest}
        for page_id, revision_id, digest in rows.all()
    }
