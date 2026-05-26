"""
TB1: Embedding provider — generate_embedding() 测试
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from infrastructure.llm.providers import OpenAIProvider


@pytest.fixture
def mock_openai_client():
    """返回一个 mock AsyncOpenAI client"""
    with patch("infrastructure.llm.providers.AsyncOpenAI") as mock:
        client = MagicMock()
        client.embeddings = MagicMock()
        client.embeddings.create = AsyncMock()
        mock.return_value = client
        yield client


@pytest.fixture
def provider(mock_openai_client) -> OpenAIProvider:
    """初始化 provider（使用 mock client）"""
    # 使用测试专用配置，避免读取真实 .env
    return OpenAIProvider(
        api_key="test-key",
        base_url="http://test",
        default_model="text-embedding-3-large",
    )


@pytest.mark.asyncio
async def test_generate_embedding_single(provider, mock_openai_client):
    """RED: 单文本应返回单个向量（list[float]）"""
    # mock embedding API 返回
    mock_openai_client.embeddings.create.return_value = MagicMock(
        data=[MagicMock(embedding=[0.1, 0.2, 0.3])],
        model="text-embedding-3-large",
        usage=MagicMock(prompt_tokens=4, total_tokens=4),
    )

    result = await provider.generate_embedding("测试文本")
    assert isinstance(result, list), "应返回 list[float]"
    assert len(result) > 0, "向量不应为空"
    assert isinstance(result[0], float), "元素应为 float"

    # 验证调用参数
    mock_openai_client.embeddings.create.assert_called_once()
    kwargs = mock_openai_client.embeddings.create.call_args[1]
    assert kwargs["input"] == "测试文本"
    assert kwargs["model"] == "text-embedding-3-large"


@pytest.mark.asyncio
async def test_generate_embedding_batch(provider, mock_openai_client):
    """RED: 批量文本应返回多个向量（list[list[float]]）"""
    mock_openai_client.embeddings.create.return_value = MagicMock(
        data=[
            MagicMock(embedding=[0.1, 0.2]),
            MagicMock(embedding=[0.3, 0.4]),
        ],
        model="text-embedding-3-large",
        usage=MagicMock(prompt_tokens=8, total_tokens=8),
    )

    texts = ["第一段", "第二段"]
    results = await provider.generate_embedding(texts)
    assert isinstance(results, list), "应返回 list"
    assert len(results) == 2, "应有 2 个向量"
    for vec in results:
        assert isinstance(vec, list), "每个元素应为 list[float]"
        assert isinstance(vec[0], float), "元素应为 float"


@pytest.mark.asyncio
async def test_generate_embedding_empty_text(provider, mock_openai_client):
    """RED: 空字符串应抛出 ValueError"""
    with pytest.raises(ValueError, match="empty"):
        await provider.generate_embedding("")

    with pytest.raises(ValueError, match="empty"):
        await provider.generate_embedding([])


@pytest.mark.asyncio
async def test_generate_embedding_custom_model(provider, mock_openai_client):
    """RED: 支持指定不同的 embedding model"""
    mock_openai_client.embeddings.create.return_value = MagicMock(
        data=[MagicMock(embedding=[0.1, 0.2, 0.3])],
        model="text-embedding-3-small",
        usage=MagicMock(prompt_tokens=4, total_tokens=4),
    )

    await provider.generate_embedding("测试", model="text-embedding-3-small")
    kwargs = mock_openai_client.embeddings.create.call_args[1]
    assert kwargs["model"] == "text-embedding-3-small"
