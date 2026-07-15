from __future__ import annotations

import os

import pytest

from tests.e2e.config import require_e2e_database_url
from tools.map_subsystem_reset import inspect_database, run_dry_run


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_dry_run_leaves_map_and_non_map_counts_unchanged() -> None:
    database_url = require_e2e_database_url(os.getenv("E2E_DATABASE_URL"))
    before = await inspect_database(database_url, "test")

    report = await run_dry_run(
        database_url=database_url,
        environment="test",
        expected_environment="test",
        expected_fingerprint=before.identity.database_fingerprint,
    )
    after = await inspect_database(database_url, "test")

    assert report.destructive_actions_available is False
    assert report.identity.declared_environment == "test"
    assert report.identity.target_environment_classification == "test"
    assert "/" not in report.identity.host
    assert report.blockers == ()
    assert before.missing_reference_registry_tables == ()
    assert after.identity.database_fingerprint == before.identity.database_fingerprint
    assert after.identity.alembic_revision == before.identity.alembic_revision
    assert after.actual_map_tables == before.actual_map_tables
    assert after.actual_foreign_keys == before.actual_foreign_keys
    assert dict(after.map_row_counts) == dict(before.map_row_counts)
    assert dict(after.map_novel_counts) == dict(before.map_novel_counts)
    assert dict(after.non_map_counts) == dict(before.non_map_counts)


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_backup_restore_drill_leaves_target_database_unchanged() -> None:
    database_url = require_e2e_database_url(os.getenv("E2E_DATABASE_URL"))
    before = await inspect_database(database_url, "test")

    report = await run_dry_run(
        database_url=database_url,
        environment="test",
        expected_environment="test",
        expected_fingerprint=before.identity.database_fingerprint,
        backup_restore_drill=True,
    )
    after = await inspect_database(database_url, "test")

    if not report.ready_for_future_reset_review:
        pytest.fail(f"test database has dry-run blockers: {report.blockers}")
    assert report.backup_restore_drill is not None
    assert report.backup_restore_drill["status"] == "passed"
    assert report.backup_restore_drill["temporary_database"].startswith(
        "map_reset_drill_"
    )
    assert after.actual_map_tables == before.actual_map_tables
    assert after.actual_foreign_keys == before.actual_foreign_keys
    assert dict(after.map_row_counts) == dict(before.map_row_counts)
    assert dict(after.map_novel_counts) == dict(before.map_novel_counts)
    assert dict(after.non_map_counts) == dict(before.non_map_counts)
