"""PostgreSQL nullable fingerprint aggregates and bounded metric hydration."""

import pytest

from modules.evidence.indexing.tests.test_index_state_metrics import (
    test_metrics_preserve_nulls_ranges_without_hydration as metric_scenario,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


async def test_index_state_metrics_on_postgres(db_session, test_project_id):
    await metric_scenario(db_session, test_project_id)


async def test_world_term_projection_on_postgres(db_session, test_project_id):
    from modules.world.tests.test_term_projection import (
        test_term_projection_keeps_status_aliases_order_and_limit,
    )

    await test_term_projection_keeps_status_aliases_order_and_limit(
        db_session, test_project_id
    )
