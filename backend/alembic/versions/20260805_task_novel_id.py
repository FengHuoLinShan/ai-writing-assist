"""Promote task project identity to an authoritative column.

Revision ID: 20260805_task_novel_id
Revises: 20260728_interaction
"""

from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260805_task_novel_id"
down_revision = "20260728_interaction"
branch_labels = None
depends_on = None

_FK_NAME = "fk_async_tasks_novel_id_projects"
_INDEX_NAME = "ix_async_tasks_novel_id"
_TRIGGER_NAME = "trg_async_tasks_novel_id_identity"
_TRIGGER_FUNCTION = "enforce_async_task_novel_id_identity"


def _uuid_type() -> sa.TypeEngine:
    return sa.CHAR(36).with_variant(postgresql.UUID(as_uuid=True), "postgresql")


def _canonical_uuid(value: Any) -> uuid.UUID | None:
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    except (AttributeError, TypeError, ValueError):
        return None


def _task_table() -> sa.TableClause:
    guid = _uuid_type()
    return sa.table(
        "async_tasks",
        sa.column("id", guid),
        sa.column("novel_id", guid),
        sa.column("meta", sa.JSON()),
    )


def _project_table() -> sa.TableClause:
    return sa.table("projects", sa.column("id", _uuid_type()))


def _backfill_and_validate(bind: sa.Connection) -> None:
    """Validate legacy JSON ownership before writing the one authoritative key."""
    tasks = _task_table()
    projects = _project_table()
    project_ids = {
        project_id
        for value in bind.execute(sa.select(projects.c.id)).scalars()
        if (project_id := _canonical_uuid(value)) is not None
    }
    updates: list[tuple[Any, uuid.UUID, dict[str, Any]]] = []
    invalid: list[str] = []
    orphan: list[str] = []
    conflict: list[str] = []

    for row in bind.execute(
        sa.select(tasks.c.id, tasks.c.novel_id, tasks.c.meta)
    ).mappings():
        task_id = str(row["id"])
        if row["meta"] is not None and not isinstance(row["meta"], dict):
            invalid.append(task_id)
            continue
        meta = dict(row["meta"] or {})
        raw_meta_novel_id = meta.get("novel_id")
        meta_novel_id = _canonical_uuid(raw_meta_novel_id)
        stored_novel_id = _canonical_uuid(row["novel_id"])
        if raw_meta_novel_id is not None and meta_novel_id is None:
            invalid.append(task_id)
            continue
        if row["novel_id"] is not None and stored_novel_id is None:
            invalid.append(task_id)
            continue
        if stored_novel_id is not None and stored_novel_id != meta_novel_id:
            conflict.append(task_id)
            continue
        if meta_novel_id is None:
            continue
        if meta_novel_id not in project_ids:
            orphan.append(task_id)
            continue
        meta["novel_id"] = str(meta_novel_id)
        if stored_novel_id != meta_novel_id or row["meta"] != meta:
            updates.append((row["id"], meta_novel_id, meta))

    if invalid:
        raise RuntimeError(
            "invalid async_tasks project identity found during migration: "
            f"{len(invalid)} task(s)"
        )
    if conflict:
        raise RuntimeError(
            f"async_tasks.novel_id disagrees with meta.novel_id: {len(conflict)} task(s)"
        )
    if orphan:
        raise RuntimeError(
            "orphan async_tasks project identity found during migration: "
            f"{len(orphan)} task(s)"
        )

    for task_id, novel_id, meta in updates:
        bound_novel_id: uuid.UUID | str = novel_id
        if bind.dialect.name == "sqlite":
            bound_novel_id = str(novel_id)
        bind.execute(
            tasks.update()
            .where(tasks.c.id == task_id)
            .values(novel_id=bound_novel_id, meta=meta)
        )


def _matching_foreign_keys(inspector: sa.Inspector) -> list[dict[str, Any]]:
    return [
        foreign_key
        for foreign_key in inspector.get_foreign_keys("async_tasks")
        if foreign_key.get("constrained_columns") == ["novel_id"]
    ]


def _ensure_foreign_key(bind: sa.Connection) -> None:
    foreign_keys = _matching_foreign_keys(sa.inspect(bind))
    if foreign_keys:
        valid = [
            foreign_key
            for foreign_key in foreign_keys
            if foreign_key.get("referred_table") == "projects"
            and foreign_key.get("referred_columns") == ["id"]
            and str((foreign_key.get("options") or {}).get("ondelete") or "").upper()
            == "CASCADE"
        ]
        if len(valid) != 1 or len(foreign_keys) != 1:
            raise RuntimeError("async_tasks.novel_id has an unexpected foreign key")
        return
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("async_tasks") as batch:
            batch.create_foreign_key(
                _FK_NAME,
                "projects",
                ["novel_id"],
                ["id"],
                ondelete="CASCADE",
            )
        return
    op.create_foreign_key(
        _FK_NAME,
        "async_tasks",
        "projects",
        ["novel_id"],
        ["id"],
        ondelete="CASCADE",
    )


def _ensure_identity_trigger(bind: sa.Connection) -> None:
    if bind.dialect.name == "postgresql":
        op.execute(
            f"""
            CREATE OR REPLACE FUNCTION {_TRIGGER_FUNCTION}()
            RETURNS trigger AS $$
            DECLARE metadata_identity jsonb;
            DECLARE metadata_identity_text text;
            BEGIN
                IF NEW.meta IS NOT NULL
                   AND jsonb_typeof(NEW.meta::jsonb) <> 'object' THEN
                    RAISE EXCEPTION 'async_tasks.meta must be an object';
                END IF;
                metadata_identity := NEW.meta::jsonb -> 'novel_id';
                metadata_identity_text := NEW.meta::jsonb ->> 'novel_id';
                IF TG_OP = 'UPDATE'
                   AND NEW.novel_id IS DISTINCT FROM OLD.novel_id THEN
                    RAISE EXCEPTION 'async_tasks.novel_id is immutable';
                END IF;
                IF NEW.novel_id IS NULL THEN
                    IF metadata_identity IS NOT NULL
                       AND jsonb_typeof(metadata_identity) <> 'null' THEN
                        RAISE EXCEPTION 'global async task cannot have meta.novel_id';
                    END IF;
                ELSIF jsonb_typeof(metadata_identity) IS DISTINCT FROM 'string'
                   OR metadata_identity_text IS DISTINCT FROM NEW.novel_id::text THEN
                    RAISE EXCEPTION 'async_tasks.novel_id disagrees with meta.novel_id';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(f"DROP TRIGGER IF EXISTS {_TRIGGER_NAME} ON async_tasks")
        op.execute(
            f"""
            CREATE TRIGGER {_TRIGGER_NAME}
            BEFORE INSERT OR UPDATE ON async_tasks
            FOR EACH ROW EXECUTE FUNCTION {_TRIGGER_FUNCTION}()
            """
        )
        return
    if bind.dialect.name == "sqlite":
        canonical_column = (
            "CASE WHEN length(NEW.novel_id) = 32 THEN "
            "substr(lower(NEW.novel_id), 1, 8) || '-' || "
            "substr(lower(NEW.novel_id), 9, 4) || '-' || "
            "substr(lower(NEW.novel_id), 13, 4) || '-' || "
            "substr(lower(NEW.novel_id), 17, 4) || '-' || "
            "substr(lower(NEW.novel_id), 21, 12) "
            "ELSE lower(NEW.novel_id) END"
        )
        op.execute(
            f"""
            CREATE TRIGGER IF NOT EXISTS {_TRIGGER_NAME}
            BEFORE INSERT ON async_tasks
            FOR EACH ROW
            WHEN (
                (NEW.meta IS NOT NULL AND json_type(NEW.meta) <> 'object')
                OR (NEW.novel_id IS NULL
                    AND json_type(NEW.meta, '$.novel_id') IS NOT NULL
                    AND json_type(NEW.meta, '$.novel_id') <> 'null')
                OR (NEW.novel_id IS NOT NULL AND (
                    json_type(NEW.meta, '$.novel_id') <> 'text'
                    OR json_extract(NEW.meta, '$.novel_id') <> {canonical_column}
                ))
            )
            BEGIN SELECT RAISE(ABORT, 'async_tasks novel_id identity mismatch'); END
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER IF NOT EXISTS {_TRIGGER_NAME}_update
            BEFORE UPDATE ON async_tasks
            FOR EACH ROW
            WHEN (
                NEW.novel_id IS NOT OLD.novel_id
                OR (NEW.meta IS NOT NULL AND json_type(NEW.meta) <> 'object')
                OR (NEW.novel_id IS NULL
                    AND json_type(NEW.meta, '$.novel_id') IS NOT NULL
                    AND json_type(NEW.meta, '$.novel_id') <> 'null')
                OR (NEW.novel_id IS NOT NULL AND (
                    json_type(NEW.meta, '$.novel_id') <> 'text'
                    OR json_extract(NEW.meta, '$.novel_id') <> {canonical_column}
                ))
            )
            BEGIN SELECT RAISE(ABORT, 'async_tasks novel_id identity mismatch'); END
            """
        )


def upgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError("20260805_task_novel_id requires an online migration")
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("async_tasks")}
    if "novel_id" not in columns:
        op.add_column(
            "async_tasks",
            sa.Column(
                "novel_id",
                _uuid_type(),
                nullable=True,
                comment="一等项目隔离键；meta.novel_id 仅为兼容投影",
            ),
        )
    _backfill_and_validate(bind)
    _ensure_foreign_key(bind)
    if _INDEX_NAME not in {
        index["name"] for index in sa.inspect(bind).get_indexes("async_tasks")
    }:
        op.create_index(_INDEX_NAME, "async_tasks", ["novel_id"])
    _ensure_identity_trigger(bind)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(f"DROP TRIGGER IF EXISTS {_TRIGGER_NAME} ON async_tasks")
        op.execute(f"DROP FUNCTION IF EXISTS {_TRIGGER_FUNCTION}()")
    elif bind.dialect.name == "sqlite":
        op.execute(f"DROP TRIGGER IF EXISTS {_TRIGGER_NAME}")
        op.execute(f"DROP TRIGGER IF EXISTS {_TRIGGER_NAME}_update")
    if _INDEX_NAME in {
        index["name"] for index in sa.inspect(bind).get_indexes("async_tasks")
    }:
        op.drop_index(_INDEX_NAME, table_name="async_tasks")
    foreign_keys = _matching_foreign_keys(sa.inspect(bind))
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("async_tasks") as batch:
            for foreign_key in foreign_keys:
                if foreign_key.get("name"):
                    batch.drop_constraint(foreign_key["name"], type_="foreignkey")
            batch.drop_column("novel_id")
        return
    for foreign_key in foreign_keys:
        if foreign_key.get("name"):
            op.drop_constraint(foreign_key["name"], "async_tasks", type_="foreignkey")
    op.drop_column("async_tasks", "novel_id")
