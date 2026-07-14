from __future__ import annotations

from typing import Any


class DomainError(Exception):
    """Domain-level error that API adapters translate to HTTP responses."""

    code = "domain_error"
    status_code = 400

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        self.message = message
        self.detail = message
        self.code = code or self.code
        self.status_code = status_code or self.status_code
        self.context = context
        super().__init__(message)


class NotFoundError(DomainError):
    code = "not_found"
    status_code = 404


class ConflictError(DomainError):
    code = "conflict"
    status_code = 409


class ValidationError(DomainError):
    code = "validation_error"
    status_code = 400
