#!/usr/bin/env python3
"""Apply the Worldbuilding Workspace v1 dev schema delta.

This is intentionally a development helper, not a production migration. It uses
the current ORM metadata to create missing tables in a local/demo database and
then applies the PostgreSQL partial index that SQLAlchemy cannot portably create
for SQLite tests.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))


def _load_backend_models() -> None:
    import infrastructure.tasks.models  # noqa: F401
    import modules.context.models  # noqa: F401
    import modules.imports.models  # noqa: F401
    import modules.memory.models  # noqa: F401
    import modules.outline.models  # noqa: F401
    import modules.project.models  # noqa: F401
    import modules.rag.models  # noqa: F401
    import modules.world.map_models  # noqa: F401
    import modules.world.models  # noqa: F401
    import modules.writing.models  # noqa: F401


def _database_url() -> str:
    env_path = BACKEND / ".env"
    if "DATABASE_URL" not in os.environ and env_path.exists():
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() == "DATABASE_URL":
                return value.strip().strip("\"'")
    return os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://novelist:novel_dev_pass@localhost:5207/ai_novel_engine",
    )


def _sync_url(database_url: str) -> str:
    return database_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")


def main() -> int:
    _load_backend_models()
    from core.base import Base

    engine = create_engine(_sync_url(_database_url()), poolclass=NullPool)
    try:
        Base.metadata.create_all(bind=engine)
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_reader_reveal_null_chapter
                    ON reader_reveal_policies (novel_id, target_hash)
                    WHERE reveal_chapter_index IS NULL
                    """
                )
            )
    finally:
        engine.dispose()
    print("Worldbuilding Workspace v1 dev schema is up to date.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
