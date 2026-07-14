"""Shared configuration values for PostgreSQL E2E tests."""

from __future__ import annotations

import os

DATABASE_URL = os.getenv(
    "E2E_DATABASE_URL",
    "postgresql+asyncpg://novelist:novel_dev_pass@localhost:5207/ai_novel_engine",
)
