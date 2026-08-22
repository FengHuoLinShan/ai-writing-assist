from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import sqlalchemy as sa


def _load_migration():
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "20260822_relation_alias_kinds.py"
    )
    spec = importlib.util.spec_from_file_location("relation_alias_kinds_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_relation_alias_kind_migration_preserves_alias_order_and_metadata() -> None:
    migration = _load_migration()
    assert migration._RELATION_KIND_BY_TYPE["member_of"] == "social"
    assert migration._RELATION_KIND_BY_TYPE["located_at"] == "spatial"
    assert migration._RELATION_KIND_BY_TYPE["causes"] == "causal"
    assert migration._RELATION_KIND_BY_TYPE["sequence_progression"] == "temporal"
    assert migration._RELATION_KIND_BY_TYPE["knows_about"] == "epistemic"
    assert migration._RELATION_KIND_BY_TYPE["seeks"] == "intentional"
    assert migration._RELATION_KIND_BY_TYPE["related_to"] == "state"

    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    entities = sa.Table(
        "core_entities",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("content_json", sa.JSON),
    )
    metadata.create_all(engine)
    original = {
        "other": {"kept": True},
        "aliases": [
            "旧名",
            {"alias": "先生", "type": "尊称", "source": "manual"},
            {"alias": "周明瑞", "type": "穿越前身份", "status": "candidate"},
            {"alias": "K", "type": "未收录类型", "evidence_refs": [{"id": 1}]},
        ],
    }
    with engine.begin() as connection:
        connection.execute(entities.insert().values(id=1, content_json=original))
        migration.op = SimpleNamespace(get_bind=lambda: connection)
        migration._migrate_aliases(remove_kind=False)
        migrated = connection.execute(
            sa.select(entities.c.content_json).where(entities.c.id == 1)
        ).scalar_one()

    assert migrated["other"] == original["other"]
    assert [item["alias"] for item in migrated["aliases"]] == [
        "旧名",
        "先生",
        "周明瑞",
        "K",
    ]
    assert [item["kind"] for item in migrated["aliases"]] == [
        "name",
        "title",
        "identity",
        "name",
    ]
    assert migrated["aliases"][1]["source"] == "manual"
    assert migrated["aliases"][2]["status"] == "candidate"
    assert migrated["aliases"][3]["evidence_refs"] == [{"id": 1}]


def test_relation_kind_migration_queues_unknown_canonical_types() -> None:
    migration = _load_migration()
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    sa.Table(
        "core_entities",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("content_json", sa.JSON),
    )
    relations = sa.Table(
        "entity_relations",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("relation_type", sa.String(64)),
        sa.Column("relation_kind", sa.String(16)),
        sa.Column("status", sa.String(16)),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            relations.insert(),
            [
                {"id": 1, "relation_type": " FRIEND_OF ", "status": "canonical"},
                {"id": 2, "relation_type": "自定义关系", "status": "canonical"},
                {"id": 3, "relation_type": "另一个自定义", "status": "candidate"},
                {"id": 4, "relation_type": "causes", "status": "candidate"},
            ],
        )
        migration.op = SimpleNamespace(
            add_column=lambda *_args, **_kwargs: None,
            create_check_constraint=lambda *_args, **_kwargs: None,
            get_bind=lambda: connection,
        )
        migration.upgrade()
        rows = list(
            connection.execute(
                sa.select(
                    relations.c.id,
                    relations.c.relation_kind,
                    relations.c.status,
                ).order_by(relations.c.id)
            ).mappings()
        )

    assert [(row["relation_kind"], row["status"]) for row in rows] == [
        ("social", "canonical"),
        (None, "candidate"),
        (None, "candidate"),
        ("causal", "candidate"),
    ]


def test_relation_alias_kind_downgrade_removes_null_kind_keys() -> None:
    migration = _load_migration()
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    entities = sa.Table(
        "core_entities",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("content_json", sa.JSON),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            entities.insert().values(
                id=1,
                content_json={
                    "aliases": [
                        {"alias": "待分类", "type": "自定义", "kind": None},
                        {"alias": "已分类", "type": "name", "kind": "name"},
                    ]
                },
            )
        )
        migration.op = SimpleNamespace(get_bind=lambda: connection)
        migration._migrate_aliases(remove_kind=True)
        downgraded = connection.execute(
            sa.select(entities.c.content_json).where(entities.c.id == 1)
        ).scalar_one()

    assert all("kind" not in item for item in downgraded["aliases"])
