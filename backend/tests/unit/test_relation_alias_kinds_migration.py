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
