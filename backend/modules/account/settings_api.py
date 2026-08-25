"""Settings API router."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from core.csrf import require_xhr_request
from core.dependencies import DbSession
from modules.account.settings_schemas import (
    AccountImageConnectionResponse,
    AccountImageConnectionUpdate,
    AccountLLMBalancesResponse,
    AccountLLMConnectionsResponse,
    AccountLLMConnectionUpdate,
    GlobalAuthorPrefsResponse,
    GlobalAuthorPrefsUpdate,
    GlobalLLMDefaultsResponse,
    GlobalLLMDefaultsUpdate,
)
from modules.account.settings_service import SettingsService

handler_router = APIRouter(tags=["settings"])
router = handler_router
_service = SettingsService()


def _bad_request(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.get(
    "/llm-connections",
    response_model=AccountLLMConnectionsResponse,
)
async def api_get_account_llm_connections(
    db: DbSession,
) -> AccountLLMConnectionsResponse:
    return await _service.get_account_llm_connections(db)


@router.get(
    "/image-connection",
    response_model=AccountImageConnectionResponse,
)
async def api_get_account_image_connection(
    db: DbSession,
) -> AccountImageConnectionResponse:
    return await _service.get_account_image_connection(db)


@router.put(
    "/image-connection",
    response_model=AccountImageConnectionResponse,
    dependencies=[Depends(require_xhr_request)],
)
async def api_connect_account_image_provider(
    db: DbSession,
    data: AccountImageConnectionUpdate,
) -> AccountImageConnectionResponse:
    try:
        return await _service.connect_account_image_provider(db, data.api_key)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.delete(
    "/image-connection",
    response_model=AccountImageConnectionResponse,
    dependencies=[Depends(require_xhr_request)],
)
async def api_clear_account_image_provider(
    db: DbSession,
) -> AccountImageConnectionResponse:
    return await _service.clear_account_image_provider(db)


@router.put(
    "/llm-connections/{provider_id}",
    response_model=AccountLLMConnectionsResponse,
    dependencies=[Depends(require_xhr_request)],
)
async def api_connect_account_llm_provider(
    db: DbSession,
    provider_id: str,
    data: AccountLLMConnectionUpdate,
) -> AccountLLMConnectionsResponse:
    try:
        return await _service.connect_account_llm_provider(
            db,
            provider_id,
            data.api_key,
        )
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post(
    "/llm-connections/{provider_id}/activate",
    response_model=AccountLLMConnectionsResponse,
    dependencies=[Depends(require_xhr_request)],
)
async def api_activate_account_llm_provider(
    db: DbSession,
    provider_id: str,
) -> AccountLLMConnectionsResponse:
    try:
        return await _service.activate_account_llm_provider(db, provider_id)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.delete(
    "/llm-connections/{provider_id}",
    response_model=AccountLLMConnectionsResponse,
    dependencies=[Depends(require_xhr_request)],
)
async def api_clear_account_llm_provider(
    db: DbSession,
    provider_id: str,
) -> AccountLLMConnectionsResponse:
    try:
        return await _service.clear_account_llm_provider(db, provider_id)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.get(
    "/llm-balances",
    response_model=AccountLLMBalancesResponse,
)
async def api_get_account_llm_balances(
    db: DbSession,
) -> AccountLLMBalancesResponse:
    return await _service.get_account_llm_balances(db)


@router.get("/llm-defaults", response_model=GlobalLLMDefaultsResponse | None)
async def api_get_global_llm_defaults(db: DbSession) -> GlobalLLMDefaultsResponse | None:
    return await _service.get_global_llm_defaults(db)


@router.put(
    "/llm-defaults",
    response_model=GlobalLLMDefaultsResponse,
    dependencies=[Depends(require_xhr_request)],
)
async def api_put_global_llm_defaults(
    db: DbSession,
    data: GlobalLLMDefaultsUpdate,
) -> GlobalLLMDefaultsResponse:
    try:
        return await _service.upsert_global_llm_defaults(
            db, data.model_dump(exclude_unset=True)
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/author-preferences", response_model=GlobalAuthorPrefsResponse | None)
async def api_get_global_author_prefs(db: DbSession) -> GlobalAuthorPrefsResponse | None:
    return await _service.get_global_author_prefs(db)


@router.put(
    "/author-preferences",
    response_model=GlobalAuthorPrefsResponse,
    dependencies=[Depends(require_xhr_request)],
)
async def api_put_global_author_prefs(
    db: DbSession,
    data: GlobalAuthorPrefsUpdate,
) -> GlobalAuthorPrefsResponse:
    return await _service.upsert_global_author_prefs(
        db, data.model_dump(exclude_unset=True)
    )


@router.post("/refresh", dependencies=[Depends(require_xhr_request)])
async def api_refresh_settings() -> dict:
    """调试端点：触发客户端刷新（D16）。"""
    return {"ok": True}
