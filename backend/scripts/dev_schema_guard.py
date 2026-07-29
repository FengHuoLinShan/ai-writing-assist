"""Fail closed when the local database is behind the Alembic head."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, pool

from core.config import get_settings

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WAIT_INTERVAL_SECONDS = 2.0


def _sync_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql+asyncpg://"):
        return database_url.replace(
            "postgresql+asyncpg://",
            "postgresql+psycopg2://",
            1,
        )
    if database_url.startswith("sqlite+aiosqlite://"):
        return database_url.replace("sqlite+aiosqlite://", "sqlite://", 1)
    return database_url


def _read_schema_revisions() -> tuple[frozenset[str], frozenset[str]]:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    expected_heads = frozenset(ScriptDirectory.from_config(config).get_heads())
    engine = create_engine(
        _sync_database_url(get_settings().database_url),
        poolclass=pool.NullPool,
    )
    try:
        with engine.connect() as connection:
            current_heads = frozenset(
                MigrationContext.configure(connection).get_current_heads()
            )
    finally:
        engine.dispose()
    return current_heads, expected_heads


def _schema_is_current() -> bool:
    try:
        current_heads, expected_heads = _read_schema_revisions()
    except Exception:  # noqa: BLE001 - the local guard must fail closed.
        return False
    return bool(expected_heads) and current_heads == expected_heads


def _print_blocked_message(*, waiting: bool) -> None:
    action = (
        "Backend/worker startup is paused."
        if waiting
        else "Local app services were not started."
    )
    print(
        f"Local database schema is not at the current Alembic head. {action}",
        file=sys.stderr,
        flush=True,
    )
    print(
        "Run `make migrate` from the repository root, then retry.",
        file=sys.stderr,
        flush=True,
    )


def require_schema_current() -> bool:
    """Return whether the database is current, with actionable CLI output."""
    if _schema_is_current():
        print("Local database schema is at the current Alembic head.", flush=True)
        return True
    _print_blocked_message(waiting=False)
    return False


def wait_for_schema_current(
    *,
    interval_seconds: float = DEFAULT_WAIT_INTERVAL_SECONDS,
) -> None:
    """Pause a reload child until an external migration reaches the head."""
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive")

    waiting = False
    while not _schema_is_current():
        if not waiting:
            _print_blocked_message(waiting=True)
            waiting = True
        time.sleep(interval_seconds)

    if waiting:
        print(
            "Local database schema reached the Alembic head; resuming startup.",
            flush=True,
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check that the local database is at the Alembic head.",
    )
    parser.add_argument(
        "--wait",
        action="store_true",
        help="Wait for an external `make migrate` instead of exiting non-zero.",
    )
    args = parser.parse_args()

    if args.wait:
        wait_for_schema_current()
        return 0
    return 0 if require_schema_current() else 2


if __name__ == "__main__":
    raise SystemExit(main())
