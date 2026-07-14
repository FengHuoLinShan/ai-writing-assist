"""RAG 模块测试配置 — 使用根 conftest 的 db_session"""

from __future__ import annotations

import hashlib
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from modules.project.models import Project


@pytest.fixture
def sample_novel_id() -> uuid.UUID:
    """返回测试用的小说项目 ID"""
    return uuid.uuid4()


@pytest_asyncio.fixture
async def db_with_project(
    db_session: AsyncSession,
    sample_novel_id: uuid.UUID,
) -> AsyncSession:
    """创建包含 projects 记录的测试数据库"""
    project = Project(
        id=sample_novel_id,
        title="测试小说项目",
        genre="玄幻",
        language="zh",
    )
    db_session.add(project)
    await db_session.flush()
    yield db_session


@pytest.fixture(autouse=True)
def _mock_llm_embedding(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
):
    """Mock embeddings unless a test explicitly opts into real-LLM acceptance."""
    if request.node.get_closest_marker("real_llm"):
        yield None
        return

    from infrastructure.llm.client import LLMClient

    def embed_one(text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        embedding = [0.0] * 768
        for offset in range(0, 8, 2):
            index = int.from_bytes(digest[offset : offset + 2], "big") % 768
            embedding[index] = 0.5 if digest[8 + offset] % 2 == 0 else -0.5
        return embedding

    async def generate_embedding(
        _client,
        text: str | list[str],
        model: str | None = None,
        *,
        is_query: bool = False,
    ) -> list[float] | list[list[float]]:
        del model, is_query
        if isinstance(text, list):
            return [embed_one(item) for item in text]
        return embed_one(text)

    monkeypatch.setattr(LLMClient, "generate_embedding", generate_embedding)
    yield generate_embedding
