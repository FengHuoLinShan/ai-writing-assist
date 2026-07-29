"""Narrow balance adapters for the two account-level LLM providers."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

from core.config import get_settings
from infrastructure.llm.egress import build_public_llm_request_guard


class ProviderBalanceError(Exception):
    """Safe balance failure that never contains provider response bodies."""


@dataclass(frozen=True)
class ProviderBalance:
    amount: Decimal
    currency: str


class _DeepSeekBalanceInfo(BaseModel):
    currency: str = Field(min_length=1, max_length=16)
    total_balance: Decimal


class _DeepSeekBalanceResponse(BaseModel):
    is_available: bool
    balance_infos: list[_DeepSeekBalanceInfo]


class _KimiBalanceData(BaseModel):
    available_balance: Decimal


class _KimiBalanceResponse(BaseModel):
    code: int
    status: bool
    data: _KimiBalanceData


async def query_provider_balance(
    provider_id: Literal["deepseek", "kimi"] | str,
    api_key: str,
) -> ProviderBalance:
    """Return the provider's total available balance in its original currency."""

    if provider_id == "deepseek":
        url = "https://api.deepseek.com/user/balance"
    elif provider_id == "kimi":
        url = "https://api.moonshot.cn/v1/users/me/balance"
    else:
        raise ProviderBalanceError("unsupported_provider")

    settings = get_settings()
    client_kwargs: dict = {
        "timeout": 15,
        "trust_env": settings.llm_trust_env,
        "event_hooks": {
            "request": [
                build_public_llm_request_guard(
                    resolve_dns=not bool(settings.llm_proxy_url),
                )
            ]
        },
    }
    if settings.llm_proxy_url:
        client_kwargs["proxy"] = settings.llm_proxy_url

    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {api_key}"},
            )
    except Exception as exc:
        raise ProviderBalanceError("temporarily_unavailable") from exc

    if response.status_code >= 400:
        raise ProviderBalanceError("temporarily_unavailable")

    try:
        if provider_id == "deepseek":
            payload = _DeepSeekBalanceResponse.model_validate(response.json())
            if not payload.balance_infos:
                raise ProviderBalanceError("temporarily_unavailable")
            # DeepSeek normally returns one entry. If it ever returns multiple
            # currencies, do not invent a converted total: surface the first
            # provider-ordered original-currency total.
            first = payload.balance_infos[0]
            return ProviderBalance(
                amount=first.total_balance,
                currency=first.currency,
            )
        payload = _KimiBalanceResponse.model_validate(response.json())
        if payload.code != 0 or not payload.status:
            raise ProviderBalanceError("temporarily_unavailable")
        return ProviderBalance(
            amount=payload.data.available_balance,
            currency="CNY",
        )
    except (ValidationError, ValueError, TypeError, KeyError) as exc:
        raise ProviderBalanceError("temporarily_unavailable") from exc
