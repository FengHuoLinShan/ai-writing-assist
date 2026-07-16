"""Project tests shared fixtures."""

import pytest_asyncio


@pytest_asyncio.fixture
async def factory(project_factory):  # noqa: ANN001, ANN201
    """Expose the shared persisted-project factory under the legacy fixture name."""
    return project_factory
