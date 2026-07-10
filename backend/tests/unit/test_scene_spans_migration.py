from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    BACKEND_ROOT / "alembic" / "versions" / "20260709_scene_spans_rag_visibility.py"
)

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _load_migration_module():
    spec = importlib.util.spec_from_file_location(
        "test_scene_spans_rag_visibility",
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
        self.calls: list[tuple[str, str]] = []

    def get_bind(self):
        return object()

    def create_table(self, name, *args, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(("create_table", name))

    def add_column(self, table, column):  # type: ignore[no-untyped-def]
        self.calls.append(("add_column", f"{table}.{column.name}"))

    def create_index(self, name, table, columns):  # type: ignore[no-untyped-def]
        self.calls.append(("create_index", f"{table}.{name}"))


class _FakeInspector:
    def __init__(
        self,
        *,
        tables: set[str],
        rag_columns: set[str],
        scene_span_indexes: set[str],
        rag_indexes: set[str],
    ) -> None:
        self._tables = tables
        self._rag_columns = rag_columns
        self._scene_span_indexes = scene_span_indexes
        self._rag_indexes = rag_indexes

    def get_table_names(self):  # type: ignore[no-untyped-def]
        return list(self._tables)

    def get_columns(self, table):  # type: ignore[no-untyped-def]
        if table == "rag_chunks":
            return [{"name": name} for name in self._rag_columns]
        return []

    def get_indexes(self, table):  # type: ignore[no-untyped-def]
        if table == "scene_spans":
            return [{"name": name} for name in self._scene_span_indexes]
        if table == "rag_chunks":
            return [{"name": name} for name in self._rag_indexes]
        return []


def test_upgrade_noops_when_squashed_schema_already_has_objects(monkeypatch):
    fake_op = _FakeOp()
    inspector = _FakeInspector(
        tables={"scene_spans", "rag_chunks"},
        rag_columns={"scene_span_id"},
        scene_span_indexes={
            "ix_scene_spans_novel_id",
            "ix_scene_spans_scene_id",
            "ix_scene_spans_scene",
            "ix_scene_spans_novel_chapter",
        },
        rag_indexes={"ix_rag_chunks_scene_span_id"},
    )
    monkeypatch.setattr(MIGRATION, "op", fake_op)
    monkeypatch.setattr(MIGRATION.sa, "inspect", lambda _bind: inspector)

    MIGRATION.upgrade()

    assert fake_op.calls == []


def test_upgrade_adds_missing_scene_span_objects(monkeypatch):
    fake_op = _FakeOp()
    inspector = _FakeInspector(
        tables={"rag_chunks"},
        rag_columns=set(),
        scene_span_indexes=set(),
        rag_indexes=set(),
    )
    monkeypatch.setattr(MIGRATION, "op", fake_op)
    monkeypatch.setattr(MIGRATION.sa, "inspect", lambda _bind: inspector)

    MIGRATION.upgrade()

    assert ("create_table", "scene_spans") in fake_op.calls
    assert ("add_column", "rag_chunks.scene_span_id") in fake_op.calls
    assert ("create_index", "rag_chunks.ix_rag_chunks_scene_span_id") in fake_op.calls


def test_backfill_scene_spans_from_existing_scene_chunks(monkeypatch):
    class _ScalarResult:
        def scalar(self):
            return 0

    class _MappingsResult:
        def __init__(self, rows) -> None:  # type: ignore[no-untyped-def]
            self._rows = rows

        def mappings(self):  # type: ignore[no-untyped-def]
            return self._rows

    class _BackfillBind:
        def __init__(self) -> None:
            self.inserted: list[dict] = []

        def execute(self, statement, params=None):  # type: ignore[no-untyped-def]
            sql = str(statement)
            if "COUNT(*) FROM scene_spans" in sql:
                return _ScalarResult()
            if "FROM scenes WHERE scene_chunks IS NOT NULL" in sql:
                return _MappingsResult(
                    [
                        {
                            "id": "11111111-1111-1111-1111-111111111111",
                            "novel_id": "22222222-2222-2222-2222-222222222222",
                            "source": "deep_import",
                            "status": "draft",
                            "scene_chunks": [
                                {
                                    "chapter_index": 2,
                                    "start_pos": 80,
                                    "end_pos": 120,
                                },
                                {
                                    "chapter_index": 2,
                                    "start_paragraph": 1,
                                    "end_paragraph": 3,
                                },
                                {
                                    "chapter_index": 2,
                                    "start_offset": 10,
                                    "end_offset": 20,
                                },
                            ],
                        }
                    ]
                )
            if "INSERT INTO scene_spans" in sql:
                self.inserted.extend(params)
                return None
            raise AssertionError(sql)

    bind = _BackfillBind()
    inspector = _FakeInspector(
        tables={"scenes", "scene_spans"},
        rag_columns=set(),
        scene_span_indexes=set(),
        rag_indexes=set(),
    )
    monkeypatch.setattr(MIGRATION.sa, "inspect", lambda _bind: inspector)

    MIGRATION._backfill_scene_spans_if_empty(bind)

    assert [row["part_no"] for row in bind.inserted] == [0, 1, 2]
    assert [row["start_offset"] for row in bind.inserted] == [10, 80, None]
    assert [row["start_paragraph"] for row in bind.inserted] == [None, None, 1]
    assert {row["source"] for row in bind.inserted} == {"deep_import"}
