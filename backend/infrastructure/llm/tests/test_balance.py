from __future__ import annotations

from decimal import Decimal

import httpx
import pytest

from infrastructure.llm import balance as balance_module
from infrastructure.llm.balance import ProviderBalanceError, query_provider_balance

pytestmark = pytest.mark.asyncio


class _FakeAsyncClient:
    def __init__(
        self,
        *,
        response: httpx.Response | None = None,
        error: Exception | None = None,
        **kwargs,
    ) -> None:
        self.response = response
        self.error = error
        self.kwargs = kwargs
        self.requests: list[tuple[str, dict[str, str]]] = []

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *_args) -> None:
        return None

    async def get(self, url: str, *, headers: dict[str, str]) -> httpx.Response:
        self.requests.append((url, headers))
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


async def test_deepseek_balance_uses_official_endpoint_and_total(
    monkeypatch,
) -> None:
    client = _FakeAsyncClient(
        response=httpx.Response(
            200,
            json={
                "is_available": True,
                "balance_infos": [
                    {
                        "currency": "CNY",
                        "total_balance": "19.75",
                        "granted_balance": "4.00",
                        "topped_up_balance": "15.75",
                    }
                ],
            },
        )
    )
    monkeypatch.setattr(
        balance_module.httpx,
        "AsyncClient",
        lambda **kwargs: _configure_client(client, kwargs),
    )

    result = await query_provider_balance("deepseek", "unit-test-deepseek-key")

    assert result.amount == Decimal("19.75")
    assert result.currency == "CNY"
    assert client.requests == [
        (
            "https://api.deepseek.com/user/balance",
            {"Authorization": "Bearer unit-test-deepseek-key"},
        )
    ]
    assert client.kwargs["timeout"] == 15


async def test_kimi_balance_uses_open_platform_available_balance(
    monkeypatch,
) -> None:
    client = _FakeAsyncClient(
        response=httpx.Response(
            200,
            json={
                "code": 0,
                "status": True,
                "data": {
                    "available_balance": "8.50",
                    "cash_balance": "5.00",
                    "voucher_balance": "3.50",
                }
            },
        )
    )
    monkeypatch.setattr(
        balance_module.httpx,
        "AsyncClient",
        lambda **kwargs: _configure_client(client, kwargs),
    )

    result = await query_provider_balance("kimi", "unit-test-kimi-key")

    assert result.amount == Decimal("8.50")
    assert result.currency == "CNY"
    assert client.requests == [
        (
            "https://api.moonshot.cn/v1/users/me/balance",
            {"Authorization": "Bearer unit-test-kimi-key"},
        )
    ]


async def test_deepseek_zero_balance_is_still_displayable(
    monkeypatch,
) -> None:
    client = _FakeAsyncClient(
        response=httpx.Response(
            200,
            json={
                "is_available": False,
                "balance_infos": [
                    {
                        "currency": "CNY",
                        "total_balance": "0.00",
                        "granted_balance": "0.00",
                        "topped_up_balance": "0.00",
                    }
                ],
            },
        )
    )
    monkeypatch.setattr(
        balance_module.httpx,
        "AsyncClient",
        lambda **kwargs: _configure_client(client, kwargs),
    )

    result = await query_provider_balance("deepseek", "unit-test-zero-key")

    assert result.amount == Decimal("0.00")
    assert result.currency == "CNY"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(401, json={"error": "credential body must stay hidden"}),
        httpx.Response(200, json={"unexpected": "shape"}),
        httpx.Response(
            200,
            json={"is_available": False, "balance_infos": []},
        ),
    ],
)
async def test_provider_error_and_schema_drift_fail_safely(
    monkeypatch,
    response: httpx.Response,
) -> None:
    client = _FakeAsyncClient(response=response)
    monkeypatch.setattr(
        balance_module.httpx,
        "AsyncClient",
        lambda **kwargs: _configure_client(client, kwargs),
    )

    with pytest.raises(ProviderBalanceError) as exc_info:
        await query_provider_balance("deepseek", "unit-test-hidden-key")

    assert str(exc_info.value) == "temporarily_unavailable"
    assert "credential" not in str(exc_info.value)
    assert "unit-test-hidden-key" not in str(exc_info.value)


async def test_transport_error_and_unsupported_provider_are_sanitized(
    monkeypatch,
) -> None:
    client = _FakeAsyncClient(
        error=httpx.ConnectError("transport included unit-test-hidden-key")
    )
    monkeypatch.setattr(
        balance_module.httpx,
        "AsyncClient",
        lambda **kwargs: _configure_client(client, kwargs),
    )

    with pytest.raises(ProviderBalanceError, match="temporarily_unavailable"):
        await query_provider_balance("deepseek", "unit-test-hidden-key")
    with pytest.raises(ProviderBalanceError, match="unsupported_provider"):
        await query_provider_balance("other", "unit-test-hidden-key")


def _configure_client(
    client: _FakeAsyncClient,
    kwargs: dict,
) -> _FakeAsyncClient:
    client.kwargs = kwargs
    return client
