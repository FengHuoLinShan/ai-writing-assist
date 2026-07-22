"""Write secret-free PostgreSQL CI diagnostics for merge-gate failures."""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

OUTPUT_DIRECTORY = Path(".test-artifacts")
DEFAULT_TIMEOUT_SECONDS = 15.0


def _output_path() -> Path:
    phase = re.sub(
        r"[^a-z0-9_-]+",
        "-",
        os.environ.get("POSTGRESQL_DIAGNOSTICS_PHASE", "").strip().casefold(),
    ).strip("-")
    suffix = f"-{phase}" if phase else ""
    return OUTPUT_DIRECTORY / f"postgresql-diagnostics{suffix}.json"


def _timeout_seconds() -> float:
    raw = os.environ.get("POSTGRESQL_DIAGNOSTICS_TIMEOUT_SECONDS", "")
    try:
        value = float(raw) if raw else DEFAULT_TIMEOUT_SECONDS
    except ValueError:
        value = DEFAULT_TIMEOUT_SECONDS
    return max(1.0, min(value, 60.0))


async def _collect() -> dict[str, Any]:
    database_url = os.environ.get("E2E_DATABASE_URL", "")
    if not database_url:
        raise RuntimeError("E2E_DATABASE_URL is required")

    engine = create_async_engine(database_url, pool_size=1, max_overflow=0)
    try:
        async with engine.connect() as connection:
            server_version = await connection.scalar(
                text("SELECT current_setting('server_version')")
            )
            extensions = {
                row.extname: row.extversion
                for row in (
                    await connection.execute(
                        text(
                            "SELECT extname, extversion FROM pg_extension "
                            "WHERE extname IN ('vector', 'pg_trgm') "
                            "ORDER BY extname"
                        )
                    )
                )
            }
            has_alembic_table = bool(
                await connection.scalar(
                    text("SELECT to_regclass('public.alembic_version') IS NOT NULL")
                )
            )
            alembic_heads = (
                list(
                    (
                        await connection.execute(
                            text(
                                "SELECT version_num FROM alembic_version "
                                "ORDER BY version_num"
                            )
                        )
                    ).scalars()
                )
                if has_alembic_table
                else []
            )
            lock_wait_rows = (
                await connection.execute(
                    text(
                        "SELECT COALESCE(wait_event, 'unknown') AS wait_event, "
                        "COALESCE(state, 'unknown') AS state, count(*) AS count "
                        "FROM pg_stat_activity "
                        "WHERE datname = current_database() "
                        "AND wait_event_type = 'Lock' "
                        "GROUP BY wait_event, state "
                        "ORDER BY wait_event, state"
                    )
                )
            ).mappings()
            lock_waits = [
                {
                    "wait_event": str(row["wait_event"]),
                    "state": str(row["state"]),
                    "count": int(row["count"]),
                }
                for row in lock_wait_rows
            ]
    finally:
        await engine.dispose()

    return {
        "postgresql_version": server_version,
        "extensions": extensions,
        "alembic_heads": alembic_heads,
        "lock_wait_count": sum(item["count"] for item in lock_waits),
        "lock_waits": lock_waits,
    }


def main() -> None:
    output_path = _output_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    diagnostics = asyncio.run(
        asyncio.wait_for(_collect(), timeout=_timeout_seconds())
    )
    output_path.write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
