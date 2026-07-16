from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def _load_migration():
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "20260716_story_outline.py"
    )
    spec = importlib.util.spec_from_file_location("story_outline_migration", path)
    assert spec is not None
    assert spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_story_outline_migration_is_idempotent_and_has_scoped_constraints() -> None:
    migration = _load_migration()
    engine = sa.create_engine("sqlite://")

    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.exec_driver_sql("CREATE TABLE projects (id CHAR(32) PRIMARY KEY)")
        connection.exec_driver_sql(
            "INSERT INTO projects (id) VALUES "
            "('aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'), "
            "('dddddddddddddddddddddddddddddddd')"
        )
        migration.op = Operations(MigrationContext.configure(connection))

        migration.upgrade()
        migration.upgrade()

        inspector = sa.inspect(connection)
        assert {
            "story_outline_heads",
            "story_outline_revisions",
        } <= set(inspector.get_table_names())
        revision_uniques = {
            tuple(item["column_names"])
            for item in inspector.get_unique_constraints("story_outline_revisions")
        }
        assert ("novel_id", "version_number") in revision_uniques
        assert ("novel_id", "idempotency_key") in revision_uniques
        assert ("id", "novel_id") in revision_uniques
        revision_fks = {
            (
                tuple(item["constrained_columns"]),
                tuple(item["referred_columns"]),
            )
            for item in inspector.get_foreign_keys("story_outline_revisions")
        }
        assert (
            ("base_revision_id", "novel_id"),
            ("id", "novel_id"),
        ) in revision_fks
        assert (
            ("restored_from_revision_id", "novel_id"),
            ("id", "novel_id"),
        ) in revision_fks
        head_uniques = {
            tuple(item["column_names"])
            for item in inspector.get_unique_constraints("story_outline_heads")
        }
        assert ("novel_id",) in head_uniques
        head_fks = {
            (
                tuple(item["constrained_columns"]),
                tuple(item["referred_columns"]),
            )
            for item in inspector.get_foreign_keys("story_outline_heads")
        }
        assert (
            ("current_revision_id", "novel_id"),
            ("id", "novel_id"),
        ) in head_fks

        connection.exec_driver_sql(
            """
            INSERT INTO story_outline_revisions (
                id, novel_id, version_number, title, creative_core_json,
                outline_markdown, major_storylines_json, macro_movements_json,
                open_decisions_json, source, provenance_json, idempotency_key,
                request_hash, content_hash
            ) VALUES (
                '11111111111111111111111111111111',
                'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                1, 'immutable', '{}', 'body', '[]', '[]', '[]', 'manual', '{}',
                'story-outline-migration-test',
                'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
                'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc'
            )
            """
        )
        with pytest.raises(sa.exc.DatabaseError, match="immutable"):
            connection.exec_driver_sql(
                "UPDATE story_outline_revisions SET title='mutated' "
                "WHERE id='11111111111111111111111111111111'"
            )
        assert (
            connection.exec_driver_sql(
                "SELECT title FROM story_outline_revisions "
                "WHERE id='11111111111111111111111111111111'"
            ).scalar_one()
            == "immutable"
        )

        with pytest.raises(sa.exc.IntegrityError, match="FOREIGN KEY"):
            connection.exec_driver_sql(
                """
                INSERT INTO story_outline_heads (id, novel_id, current_revision_id)
                VALUES (
                    '22222222222222222222222222222222',
                    'dddddddddddddddddddddddddddddddd',
                    '11111111111111111111111111111111'
                )
                """
            )
        with pytest.raises(sa.exc.IntegrityError, match="FOREIGN KEY"):
            connection.exec_driver_sql(
                """
                INSERT INTO story_outline_revisions (
                    id, novel_id, version_number, title, creative_core_json,
                    outline_markdown, major_storylines_json, macro_movements_json,
                    open_decisions_json, source, provenance_json, base_revision_id,
                    idempotency_key, request_hash, content_hash
                ) VALUES (
                    '33333333333333333333333333333333',
                    'dddddddddddddddddddddddddddddddd',
                    1, 'cross-project', '{}', 'body', '[]', '[]', '[]',
                    'manual', '{}', '11111111111111111111111111111111',
                    'story-outline-cross-project',
                    'eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
                    'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
                )
                """
            )
        connection.exec_driver_sql(
            """
            INSERT INTO story_outline_heads (id, novel_id, current_revision_id)
            VALUES (
                '44444444444444444444444444444444',
                'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                '11111111111111111111111111111111'
            )
            """
        )
        connection.exec_driver_sql(
            "DELETE FROM projects WHERE id='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'"
        )
        assert (
            connection.exec_driver_sql(
                "SELECT COUNT(*) FROM story_outline_revisions"
            ).scalar_one()
            == 0
        )
        assert (
            connection.exec_driver_sql(
                "SELECT COUNT(*) FROM story_outline_heads"
            ).scalar_one()
            == 0
        )

        migration.downgrade()
        assert not {
            "story_outline_heads",
            "story_outline_revisions",
        } & set(sa.inspect(connection).get_table_names())
