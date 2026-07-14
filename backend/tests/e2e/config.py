"""Shared configuration values for PostgreSQL E2E tests."""

from __future__ import annotations

import os
import re

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

DATABASE_URL = os.getenv("E2E_DATABASE_URL", "")

_DEDICATED_DATABASE_MARKER = re.compile(r"(?:^|[_-])(?:audit|e2e|test)(?:$|[_-])")


def require_e2e_database_url(database_url: str | None = None) -> str:
    """Return one explicit, dedicated PostgreSQL E2E target or fail closed."""

    value = DATABASE_URL if database_url is None else database_url
    if not value:
        raise RuntimeError(
            "E2E_DATABASE_URL must be set explicitly to a dedicated test database"
        )
    try:
        url = make_url(value)
        backend = url.get_backend_name()
        database = url.database or ""
    except (ArgumentError, AttributeError, TypeError, ValueError):
        raise RuntimeError("E2E_DATABASE_URL is not a valid database URL") from None
    if backend != "postgresql":
        raise RuntimeError("E2E_DATABASE_URL must use PostgreSQL")
    if not _DEDICATED_DATABASE_MARKER.search(database.casefold()):
        raise RuntimeError(
            "E2E_DATABASE_URL must target a dedicated database whose name "
            "contains a standalone 'audit', 'e2e', or 'test' marker"
        )
    return value
