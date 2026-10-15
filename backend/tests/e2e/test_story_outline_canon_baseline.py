"""G8c response comparison on real PostgreSQL; no live models."""

import pytest

from modules.story.outline_state.tests.test_canon_baseline import (
    test_actual_page_read_captures_current_revision_and_filters_projects as _page_read,
)
from modules.story.outline_state.tests.test_canon_baseline import (
    test_outline_read_only_notice_preserves_content_provenance_and_hash as _outline_read,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


async def test_page_revision_batch_is_novel_scoped(db_session, base_scene):
    await _page_read(db_session, str(base_scene["project_id"]))


@pytest.mark.parametrize("change", ["revision", "unadopt"])
async def test_outline_notice_does_not_mutate_persisted_revision(
    db_session, base_scene, change
):
    await _outline_read(db_session, str(base_scene["project_id"]), change)
