"""A versioned partition of the existing watch, sharing its daily allowance."""

from datetime import UTC, datetime

from core.config import get_settings
from core.errors import ConflictError, ValidationError
from modules.assistant.forecast.contracts import ForecastPolicy, PolicyView
from modules.assistant.forecast.registry import require_capabilities
from modules.assistant.proactive import _watch
from modules.assistant.schemas import ProactivePolicy


def effective_policy(row):
    payload = (row.policy_json or {}) if row else {}
    shared = ProactivePolicy.model_validate(payload.get("settings") or {})
    return ForecastPolicy.model_validate(
        {
            **(payload.get("forecast_v1") or {}),
            "shared_daily_limit": shared.daily_limit,
            "timezone": shared.timezone,
        }
    )


async def read_policy(db, novel_id):
    row = await _watch(db, novel_id)
    available = (
        get_settings().assistant_enabled and get_settings().assistant_forecast_enabled
    )
    return PolicyView(
        generation=row.generation if row else 0,
        policy=effective_policy(row),
        available=available,
        reason=None if available else "前瞻辅助尚未开启",
    )


async def save_policy(db, novel_id, owner_id, data):
    row = await _watch(db, novel_id, create=True, lock=True)
    if row.generation != data.expected_generation:
        raise ConflictError("前瞻设置已在其他位置更新", code="POLICY_CHANGED")
    require_capabilities(data.policy.enabled_capabilities)
    settings = get_settings()
    if data.policy.enabled and not (
        settings.assistant_enabled and settings.assistant_forecast_enabled
    ):
        raise ValidationError(
            "前瞻尚未开启", code="CAPABILITY_UNAVAILABLE", status_code=503
        )
    if data.policy.automatic and not (
        settings.assistant_forecast_automatic_enabled
        and settings.assistant_forecast_semantic_enabled
    ):
        raise ValidationError(
            "主动语义前瞻尚未通过当前启用门槛，仍可手动查看",
            code="AUTOMATIC_UNAVAILABLE",
            status_code=503,
        )
    shared = ProactivePolicy.model_validate((row.policy_json or {}).get("settings") or {})
    shared = shared.model_copy(
        update={
            "daily_limit": data.policy.shared_daily_limit,
            "timezone": data.policy.timezone,
        }
    )
    row.generation += 1
    row.policy_json = {
        **(row.policy_json or {}),
        "settings": shared.model_dump(mode="json"),
        "forecast_v1": data.policy.model_dump(mode="json"),
        "owner_id": str(owner_id),
        "version": row.generation,
        "authorized_at": datetime.now(UTC).isoformat(),
    }
    if not data.policy.automatic:
        row.dirty_json = {
            key: value
            for key, value in (row.dirty_json or {}).items()
            if key != "_forecast_v1"
        }
    from modules.assistant.forecast.queue import refresh_due

    refresh_due(row)
    await db.flush()
    return await read_policy(db, novel_id)
