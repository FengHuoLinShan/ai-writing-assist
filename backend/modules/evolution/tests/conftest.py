"""Evolution tests explicitly opt their own project into the new engine."""

import pytest_asyncio

from modules.evolution.facade import switch_project_engine


@pytest_asyncio.fixture
async def evolution_project_id(test_project_id, db_session):
    await switch_project_engine(
        db_session, test_project_id, to_engine="evolution", expected_epoch=1
    )
    await db_session.commit()
    return test_project_id
