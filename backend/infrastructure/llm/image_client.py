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
from infrastructure.llm.schemas import AIStepCallKind, LLMUsage

logger = logging.getLogger(__name__)

OPENAI_IMAGE_BASE_URL = "https://api.openai.com/v1"
OPENAI_IMAGE_MODEL = "gpt-image-2"
# 运行信封 step 身份：图片 generate/edit 共用同一 canonical capability，
# 由 call_kind（image_generate / image_edit）区分。注册表项由共享层新增。
IMAGE_ENVELOPE_STEP_NAME = "world.map_image.render"
IMAGE_ENVELOPE_CAPABILITY_ID = "world.map_image.generate"

_IMAGE_PROVIDER_ERRORS = (
    AuthenticationError,
    PermissionDeniedError,
    RateLimitError,
    BadRequestError,
    APITimeoutError,
    APIConnectionError,
    APIStatusError,
)


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

    def __init__(
        self,
        *,
        api_key: str,
        timeout: int = 180,
        envelope_step_name: str = IMAGE_ENVELOPE_STEP_NAME,
        envelope_capability_id: str = IMAGE_ENVELOPE_CAPABILITY_ID,
    ) -> None:
        if not api_key.strip():
            raise ValueError("OpenAI image API key is required")
        self._envelope_step_name = envelope_step_name
        self._envelope_capability_id = envelope_capability_id
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
        async def _request() -> Any:
            return await self._client.images.generate(
                model=OPENAI_IMAGE_MODEL,
                prompt=prompt,
                size=size,
                quality=quality,
                output_format="png",
                background="opaque",
                n=1,
            )

        return await self._metered_request(
            AIStepCallKind.image_generate, _request
        )

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

        async def _request() -> Any:
            return await self._client.images.edit(**kwargs)

        return await self._metered_request(AIStepCallKind.image_edit, _request)

    async def _metered_request(
        self,
        call_kind: AIStepCallKind,
        request: Any,
    ) -> GeneratedImage:
        """活动运行信封下 reserve→I/O→settle；无信封时与改造前行为一致。

        reserve 发生在任何 provider I/O 之前：预算、deadline 或 checkpoint
        拒绝时不发请求、不产生计数。已知 usage 记 recorded，缺 usage 或
        结果未知记 unknown/possible；possible_charge/request_id/retryable
        投影到 settle 的 error/finish 信息。
        """
        ledger, reservation = await self._reserve_image_request(call_kind)
        if ledger is None or reservation is None:
            try:
                response = await request()
            except _IMAGE_PROVIDER_ERRORS as error:
                raise _map_image_error(error) from error
            return self._decode_response(response)
        try:
            response = await request()
        except _IMAGE_PROVIDER_ERRORS as error:
            mapped = _map_image_error(error)
            await self._settle_image_request(ledger, reservation, error=mapped)
            raise mapped from error
        except BaseException as error:
            # 请求已发出但结果未知（取消、中断）：收敛为 unknown/possible。
            await self._settle_image_request(ledger, reservation, error=error)
            raise
        try:
            decoded = self._decode_response(response)
        except ImageGenerationError as error:
            await self._settle_image_request(
                ledger,
                reservation,
                usage=self._response_usage(response),
                error=error,
                request_id=self._response_request_id(response),
            )
            raise
        await self._settle_image_request(
            ledger,
            reservation,
            usage=self._response_usage(response),
            request_id=decoded.request_id,
        )
        return decoded

    async def _reserve_image_request(self, call_kind: AIStepCallKind):
        from infrastructure.llm.workflow_budget import (
            AIManagedStepContext,
            current_ai_run_envelope,
            managed_step_scope,
        )

        ledger = current_ai_run_envelope()
        if ledger is None:
            return None, None
        context = AIManagedStepContext(
            step_name=self._envelope_step_name,
            call_kind=call_kind,
            capability_id=self._envelope_capability_id,
            profile_source="account",
            profile_summary={"model": OPENAI_IMAGE_MODEL, "provider_id": "openai"},
        )
        with managed_step_scope(context):
            reservation = await ledger.reserve()
        return ledger, reservation

    async def _settle_image_request(
        self,
        ledger: Any,
        reservation: Any,
        *,
        usage: LLMUsage | None = None,
        error: BaseException | None = None,
        request_id: str | None = None,
    ) -> None:
        error_kind = ""
        retryable = False
        finish_reason = ""
        if error is not None:
            error_kind = (
                str(getattr(error, "code", "") or "") or type(error).__name__
            )
            retryable = bool(getattr(error, "retryable", False))
            if getattr(error, "possible_charge", False):
                finish_reason = "possible_charge"
        if request_id:
            token = f"request:{request_id}"
            finish_reason = f"{finish_reason}+{token}" if finish_reason else token
        await ledger.settle(
            reservation,
            usage=usage,
            finish_reason=finish_reason,
            error_kind=error_kind,
            retryable=retryable,
        )

    @staticmethod
    def _response_usage(response: Any) -> LLMUsage | None:
        """读取 Images API 的 usage；缺失或畸形时按未知用量处理。"""
        usage = getattr(response, "usage", None)
        if usage is None:
            return None
        try:
            prompt = int(getattr(usage, "input_tokens") or 0)
            completion = int(getattr(usage, "output_tokens") or 0)
        except (TypeError, ValueError):
            return None
        total = getattr(usage, "total_tokens", None)
        try:
            total_tokens = int(total) if total is not None else prompt + completion
        except (TypeError, ValueError):
            total_tokens = prompt + completion
        return LLMUsage(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total_tokens,
        )

    @staticmethod
    def _response_request_id(response: Any) -> str | None:
        request_id = getattr(response, "_request_id", None)
        return str(request_id) if request_id else None

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
