"""Run the domain UoW contracts against PostgreSQL, plus DB-only invariants."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from modules.collaboration.models import CreativeWorkspaceRevision
from modules.collaboration.tests.test_workspaces import (
    setup_trial,
    test_deleted_overlay_stays_deleted_when_forked,  # noqa: F401
    test_failed_second_write_rolls_back_every_domain_write,  # noqa: F401
    test_grant_renewal_keeps_spend,  # noqa: F401
    test_new_source_invalidates_negative_query_and_old_trial,  # noqa: F401
    test_rebase_preserves_author_edits_requires_exact_conflict_resolution,  # noqa: F401
    test_revert_creates_checked_compensation_without_erasing_merge,  # noqa: F401
    test_trial_does_not_write_and_merge_is_exact_and_idempotent,  # noqa: F401
)


async def test_pg_revision_is_immutable_and_rejects_cross_project_pointer(
    db_session, test_project_id, project_factory, monkeypatch
):
    db, nid = db_session, test_project_id
    _, view, _, _ = await setup_trial(db, nid, monkeypatch)
    revision_id = UUID(view["revision_id"])
    with pytest.raises(DBAPIError, match="immutable"):
        async with db.begin_nested():
            await db.execute(
                text(
                    "UPDATE creative_workspace_revisions SET patches_json"
                    " = '[]'::json WHERE id = :id"
                ),
                {"id": revision_id},
            )
    other = await project_factory.create_project()
    revision = await db.scalar(
        select(CreativeWorkspaceRevision).where(
            CreativeWorkspaceRevision.id == revision_id
        )
    )
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(
                CreativeWorkspaceRevision(
                    id=uuid4(),
                    novel_id=other,
                    workspace_id=revision.workspace_id,
                    sequence=99,
                    goal_version=1,
                    patches_json=[],
                    manifest_json={},
                    digest="a" * 64,
                )
            )
            await db.flush()
