"""Request-local account context."""

from __future__ import annotations

from contextvars import ContextVar, Token

from modules.account.contracts import AccountPrincipal

_principal: ContextVar[AccountPrincipal | None] = ContextVar(
    "account_principal",
    default=None,
)


def current_principal() -> AccountPrincipal | None:
    return _principal.get()


def bind_principal(principal: AccountPrincipal) -> Token[AccountPrincipal | None]:
    return _principal.set(principal)


def reset_principal(token: Token[AccountPrincipal | None]) -> None:
    _principal.reset(token)
