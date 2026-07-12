from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import sqlalchemy as sa

BACKEND_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    BACKEND_ROOT / "alembic" / "versions" / "20260712_llm_max_tokens_12000.py"
)

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _load_migration_module():
    spec = importlib.util.spec_from_file_location(
        "test_llm_max_tokens_migration_module",
        MIGRATION_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MIGRATION = _load_migration_module()


def test_upgrade_normalizes_general_values_without_touching_deep_import(
    monkeypatch,
) -> None:
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    global_defaults = sa.Table(
        "global_llm_defaults",
        metadata,
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("max_tokens", sa.Integer(), nullable=True),
    )
    projects = sa.Table(
        "projects",
        metadata,
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("settings", sa.JSON(), nullable=False),
    )
    metadata.create_all(engine)
    deep_import = {
        "phase0": {
            "max_tokens_per_input_char": 1.0,
            "min_max_tokens": 13_000,
            "max_max_tokens": 32_768,
        }
    }

    with engine.begin() as connection:
        connection.execute(
            global_defaults.insert(),
            [
                {"id": "global-old", "max_tokens": 4096},
                {"id": "global-custom", "max_tokens": 20_000},
            ],
        )
        connection.execute(
            projects.insert(),
            [
                {
                    "id": "11111111-1111-1111-1111-111111111111",
                    "settings": {
                        "llm": {"model": "custom", "max_tokens": 4096},
                        "deep_import": deep_import,
                    },
                },
                {
                    "id": "22222222-2222-2222-2222-222222222222",
                    "settings": {"deep_import": deep_import},
                },
            ],
        )
        monkeypatch.setattr(MIGRATION.op, "get_bind", lambda: connection)

        MIGRATION.upgrade()

        assert connection.execute(
            sa.select(global_defaults.c.max_tokens).order_by(global_defaults.c.id)
        ).scalars().all() == [12_000, 12_000]
        rows = {
            row.id: row.settings
            for row in connection.execute(sa.select(projects.c.id, projects.c.settings))
        }
        old = rows[next(key for key in rows if str(key).startswith("11111111"))]
        inherited = rows[next(key for key in rows if str(key).startswith("22222222"))]
        assert old["llm"]["max_tokens"] == 12_000
        assert old["deep_import"] == deep_import
        assert inherited == {"deep_import": deep_import}
