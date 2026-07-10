from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = BACKEND_ROOT / "alembic" / "versions" / "20260710_novel_evidence.py"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _load_migration_module():
    spec = importlib.util.spec_from_file_location(
        "test_novel_evidence_migration",
        MIGRATION_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MIGRATION = _load_migration_module()


class _FakeOp:
    def __init__(self) -> None:
        self.sql: list[str] = []
        self.columns: list[str] = []
        self.indexes: list[str] = []

    def add_column(self, table, column):  # type: ignore[no-untyped-def]
        self.columns.append(f"{table}.{column.name}")

    def create_index(self, name, table, columns):  # type: ignore[no-untyped-def]
        self.indexes.append(f"{table}.{name}:{','.join(columns)}")

    def execute(self, statement):  # type: ignore[no-untyped-def]
        self.sql.append(str(statement))


class _FakeInspector:
    def get_columns(self, _table):  # type: ignore[no-untyped-def]
        return []

    def get_indexes(self, _table):  # type: ignore[no-untyped-def]
        return []


class _FakeBind:
    def __init__(self) -> None:
        self.sql: list[str] = []

    def execute(self, statement, _params=None):  # type: ignore[no-untyped-def]
        self.sql.append(str(statement))


def test_rag_unique_keys_partition_canonical_and_working(monkeypatch) -> None:
    fake_op = _FakeOp()
    bind = _FakeBind()
    monkeypatch.setattr(MIGRATION, "op", fake_op)

    MIGRATION._upgrade_rag_chunks(bind, _FakeInspector())

    create_sql = "\n".join(
        statement for statement in fake_op.sql if "CREATE UNIQUE INDEX" in statement
    )
    assert "source_type, content_mode" in create_sql
    assert "source_type, content_mode, source_id" in create_sql
    assert any("DELETE FROM rag_chunks" in statement for statement in bind.sql)
