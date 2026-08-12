"""Narrow OpenAI Image API client used by the map atlas."""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from typing import Any

import httpx
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    PermissionDeniedError,
    RateLimitError,
)

from core.config import get_settings
from infrastructure.llm.egress import build_public_llm_request_guard
from infrastructure.llm.redaction import redact_diagnostic

logger = logging.getLogger(__name__)

OPENAI_IMAGE_BASE_URL = "https://api.openai.com/v1"
OPENAI_IMAGE_MODEL = "gpt-image-2"


@dataclass(frozen=True, slots=True)
class GeneratedImage:
    data: bytes
    request_id: str | None


class ImageGenerationError(RuntimeError):
    """Secret-free provider failure with explicit replay semantics."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        possible_charge: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.possible_charge = possible_charge


def _provider_error_code(error: Exception) -> str | None:
    body = getattr(error, "body", None)
    if isinstance(body, dict):
        nested = body.get("error")
        if isinstance(nested, dict) and nested.get("code"):
            return str(nested["code"])
        if body.get("code"):
            return str(body["code"])
    return None


def _map_image_error(error: Exception) -> ImageGenerationError:
    provider_code = _provider_error_code(error)
    if provider_code == "moderation_blocked":
        return ImageGenerationError(
            "moderation_blocked",
            "图片请求未通过安全检查，请调整描述或参考图后重试",
        )
    if provider_code in {
        "insufficient_quota",
        "billing_not_active",
        "credit_balance_too_low",
    }:
        return ImageGenerationError(
            "image_quota_exhausted",
            "OpenAI 图片额度不足，请检查账户额度后重试",
        )
    if isinstance(error, AuthenticationError):
        return ImageGenerationError(
            "image_auth_failed",
            "OpenAI 图片连接已失效，请在账户设置中重新连接",
        )
    if isinstance(error, PermissionDeniedError):
        return ImageGenerationError(
            "image_permission_denied",
            "当前 OpenAI 账户尚无 GPT Image 2 使用权限或需要完成组织验证",
        )
    if isinstance(error, RateLimitError):
        return ImageGenerationError(
            "image_rate_limited",
            "OpenAI 图片服务繁忙，稍后将自动重试",
            retryable=True,
        )
    if isinstance(error, (APITimeoutError, APIConnectionError)):
        return ImageGenerationError(
            "image_connection_failed",
            "图片请求结果未知；确认可能重复扣费后才能重试",
            possible_charge=True,
        )
    if isinstance(error, BadRequestError):
        return ImageGenerationError(
            provider_code or "image_request_invalid",
            "图片描述或参考图不符合服务要求，请修改后重试",
        )
    if isinstance(error, APIStatusError) and int(error.status_code or 0) >= 500:
        return ImageGenerationError(
            "image_provider_unavailable",
            "OpenAI 图片服务暂时不可用",
            retryable=True,
        )
    diagnostic = redact_diagnostic(error, limit=240)
    logger.warning("Unclassified image provider failure: %s", diagnostic)
    return ImageGenerationError(
        "image_provider_failed",
        "图片生成失败，请稍后重试",
        possible_charge=True,
    )


class OpenAIImageClient:
    """Concrete GPT Image 2 client; no provider registry by design."""

    def __init__(self, *, api_key: str, timeout: int = 180) -> None:
        if not api_key.strip():
            raise ValueError("OpenAI image API key is required")
        settings = get_settings()
        self._http_client = httpx.AsyncClient(
            timeout=timeout,
            trust_env=settings.llm_trust_env,
            event_hooks={
                "request": [
                    build_public_llm_request_guard(
                        resolve_dns=not bool(settings.llm_proxy_url)
                    )
                ]
            },
            **(
                {"proxy": settings.llm_proxy_url}
                if settings.llm_proxy_url
                else {}
            ),
        )
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=OPENAI_IMAGE_BASE_URL,
            timeout=timeout,
            max_retries=0,
            http_client=self._http_client,
        )

    async def close(self) -> None:
        await self._client.close()

    async def verify_connection(self) -> None:
        """Verify the key endpoint, not quota or generation entitlement."""
        try:
            await self._client.models.list()
        except (
            AuthenticationError,
            PermissionDeniedError,
            RateLimitError,
            APITimeoutError,
            APIConnectionError,
            APIStatusError,
        ) as error:
            raise _map_image_error(error) from error

    async def generate(
        self,
        *,
        prompt: str,
        size: str,
        quality: str,
    ) -> GeneratedImage:
        try:
            response = await self._client.images.generate(
                model=OPENAI_IMAGE_MODEL,
                prompt=prompt,
                size=size,
                quality=quality,
                output_format="png",
                background="opaque",
                n=1,
            )
        except (
            AuthenticationError,
            PermissionDeniedError,
            RateLimitError,
            BadRequestError,
            APITimeoutError,
            APIConnectionError,
            APIStatusError,
        ) as error:
            raise _map_image_error(error) from error
        return self._decode_response(response)

    async def edit(
        self,
        *,
        prompt: str,
        images: list[tuple[str, bytes, str]],
        mask: tuple[str, bytes, str] | None,
        size: str,
        quality: str,
    ) -> GeneratedImage:
        if not images:
            raise ValueError("at least one image is required for editing")
        kwargs: dict[str, Any] = {
            "model": OPENAI_IMAGE_MODEL,
            "prompt": prompt,
            "image": images,
            "size": size,
            "quality": quality,
            "output_format": "png",
            "background": "opaque",
            "n": 1,
        }
        if mask is not None:
            kwargs["mask"] = mask
        try:
            response = await self._client.images.edit(**kwargs)
        except (
            AuthenticationError,
            PermissionDeniedError,
            RateLimitError,
            BadRequestError,
            APITimeoutError,
            APIConnectionError,
            APIStatusError,
        ) as error:
            raise _map_image_error(error) from error
        return self._decode_response(response)

    @staticmethod
    def _decode_response(response: Any) -> GeneratedImage:
        items = list(getattr(response, "data", None) or [])
        encoded = getattr(items[0], "b64_json", None) if items else None
        if not isinstance(encoded, str) or not encoded:
            raise ImageGenerationError(
                "image_response_invalid",
                "图片服务没有返回可用图片",
                possible_charge=True,
            )
        try:
            payload = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as exc:
            raise ImageGenerationError(
                "image_response_invalid",
                "图片服务返回了无法读取的图片",
                possible_charge=True,
            ) from exc
        if not payload:
            raise ImageGenerationError(
                "image_response_invalid",
                "图片服务返回了空图片",
                possible_charge=True,
            )
        request_id = getattr(response, "_request_id", None)
        return GeneratedImage(
            data=payload,
            request_id=str(request_id) if request_id else None,
        )
