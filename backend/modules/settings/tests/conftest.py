"""Settings tests shared fixtures."""

import pytest_asyncio


@pytest_asyncio.fixture
async def factory(project_factory):  # noqa: ANN001, ANN201
    """Expose the shared factory, including timestamp override support."""
    return project_factory
