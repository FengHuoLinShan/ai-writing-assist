"""Copy-protocol structural invariants: table order, topology, digests."""

from __future__ import annotations

import uuid

import pytest

from core.base import Base
from modules.project.demo_copy import (
    _POINTER_FORWARD_REFERENCES,
    DemoProjectCopyService,
)
from modules.world.canon_import import revision_import_digest

OUTLINE = "story_outline_revisions"


def test_copy_table_order_inserts_every_reference_in_final_state() -> None:
    """Cross-table FK targets must precede the referring table, except the
    whitelisted head/pointer FK cycles, whose nullable pointer columns are
    moved onto the copied revisions by a final mutable-pointer pass.
    Immutable revision tables must never depend on a later table.
    """
    tables = DemoProjectCopyService._copy_tables()
    position = {table.name: index for index, table in enumerate(tables)}
    unexpected: list[str] = []
    for table in tables:
        for constraint in table.foreign_key_constraints:
            target = constraint.referred_table
            if target.name == table.name or target.name not in position:
                continue
            if position[target.name] > position[table.name]:
                whitelisted = target.name in _POINTER_FORWARD_REFERENCES.get(
                    table.name, frozenset()
                )
                if not whitelisted:
                    unexpected.append(
                        f"{table.name} -> {target.name} "
                        f"({[c.name for c in constraint.columns]})"
                    )
    assert unexpected == []


def test_pointer_forward_references_are_valid_cycles() -> None:
    tables = DemoProjectCopyService._copy_tables()
    position = {table.name: index for index, table in enumerate(tables)}
    for parent_table, targets in _POINTER_FORWARD_REFERENCES.items():
        assert parent_table in position
        for target_table in targets:
            assert target_table in position
            assert position[target_table] > position[parent_table]
            parent = Base.metadata.tables[parent_table]
            constrained = [
                column
                for constraint in parent.foreign_key_constraints
                if constraint.referred_table.name == target_table
                for column in constraint.columns
            ]
            assert constrained, f"{parent_table} lacks an FK to {target_table}"
            for column in constrained:
                assert column.nullable or column.name in {"novel_id", "id"}, (
                    f"{parent_table}.{column.name} must be nullable to defer"
                )


def test_order_rows_for_insert_resolves_chain_and_branch_dependencies() -> None:
    rows = [
        {"id": "c1", "base_revision_id": "b1", "restored_from_revision_id": None},
        {"id": "b1", "base_revision_id": None, "restored_from_revision_id": None},
        {"id": "a2", "base_revision_id": "a1", "restored_from_revision_id": "b1"},
        {"id": "a1", "base_revision_id": None, "restored_from_revision_id": None},
    ]

    ordered = DemoProjectCopyService._order_rows_for_insert(
        Base.metadata.tables[OUTLINE], rows
    )
    positions = {row["id"]: index for index, row in enumerate(ordered)}
    assert positions["b1"] < positions["c1"]
    assert positions["a1"] < positions["a2"]
    assert positions["b1"] < positions["a2"]


def test_order_rows_for_insert_rejects_cycles() -> None:
    rows = [
        {"id": "x", "base_revision_id": "y", "restored_from_revision_id": None},
        {"id": "y", "base_revision_id": "x", "restored_from_revision_id": None},
    ]
    with pytest.raises(RuntimeError, match="cycle"):
        DemoProjectCopyService._order_rows_for_insert(Base.metadata.tables[OUTLINE], rows)


def test_order_rows_for_insert_allows_multiple_roots_and_optional_parents() -> None:
    root_a = "11111111-1111-1111-1111-111111111111"
    root_b = "22222222-2222-2222-2222-222222222222"
    child = "33333333-3333-3333-3333-333333333333"
    rows = [
        {"id": child, "base_revision_id": root_b, "restored_from_revision_id": None},
        {"id": root_b, "base_revision_id": None, "restored_from_revision_id": None},
        {"id": root_a, "base_revision_id": None, "restored_from_revision_id": None},
    ]
    ordered = DemoProjectCopyService._order_rows_for_insert(
        Base.metadata.tables[OUTLINE], rows
    )
    positions = {row["id"]: index for index, row in enumerate(ordered)}
    assert positions[root_b] < positions[child]
    assert set(positions) == {root_a, root_b, child}


def test_revision_digest_rewrites_bind_destination_identity() -> None:
    source_entity_id = uuid.uuid4()
    destination_entity_id = uuid.uuid4()
    destination_id = uuid.uuid4()
    new_page_id = uuid.uuid4()
    new_revision_id = uuid.uuid4()
    snapshot = {
        "title": "示例",
        "sections_json": [],
        "linked_asset_refs_json": [{"type": "profile", "id": str(source_entity_id)}],
    }
    rows_by_table = {
        "world_bible_page_revisions": [
            {"id": "src-rev", "page_id": "src-page", "snapshot_json": snapshot}
        ]
    }
    rewrites = {
        "world_bible_pages": {"src-page": new_page_id},
        "world_bible_page_revisions": {"src-rev": new_revision_id},
    }

    digests = DemoProjectCopyService._revision_digest_rewrites(
        destination_id,
        rows_by_table,
        rewrites,
        {str(source_entity_id): destination_entity_id},
    )

    new_id, digest = digests["world_bible_page_revisions"]["src-rev"]
    assert new_id == new_revision_id
    assert digest == revision_import_digest(
        "world_bible_page",
        novel_id=destination_id,
        resource_id=new_page_id,
        revision_id=new_revision_id,
        snapshot={
            **snapshot,
            "linked_asset_refs_json": [
                {"type": "profile", "id": str(destination_entity_id)}
            ],
        },
    )


@pytest.mark.asyncio
async def test_immutable_write_guard_flags_revision_rewrites(db_session) -> None:
    from sqlalchemy import delete, update

    from tests.fixtures.immutable_writes import forbid_immutable_writes

    table = Base.metadata.tables["world_canon_revisions"]
    with pytest.raises(AssertionError, match="Update world_canon_revisions"):
        with forbid_immutable_writes(db_session) as guard:
            await db_session.execute(
                update(table)
                .where(table.c.novel_id == uuid.uuid4())
                .values(decision_digest="0" * 64)
            )
            guard.assert_clean()
    with pytest.raises(AssertionError, match="Delete story_outline_revisions"):
        with forbid_immutable_writes(db_session) as guard:
            outline = Base.metadata.tables["story_outline_revisions"]
            await db_session.execute(
                delete(outline).where(outline.c.novel_id == uuid.uuid4())
            )
            guard.assert_clean()


@pytest.mark.asyncio
async def test_immutable_write_guard_allows_pointer_updates(db_session) -> None:
    """Mutable head/pointer tables stay updatable under the guard."""
    from sqlalchemy import update

    from tests.fixtures.immutable_writes import forbid_immutable_writes

    heads = Base.metadata.tables["story_outline_heads"]
    with forbid_immutable_writes(db_session) as guard:
        await db_session.execute(
            update(heads)
            .where(heads.c.novel_id == uuid.uuid4())
            .values(current_revision_id=None)
        )
        guard.assert_clean()


@pytest.mark.parametrize(
    "table_name", ["story_simulation_steps", "interaction_actor_state_revisions"]
)
async def test_team_history_immutable_write_guard(db_session, table_name):
    from sqlalchemy import delete, update

    from tests.fixtures.immutable_writes import forbid_immutable_writes

    table = Base.metadata.tables[table_name]
    for statement in (update(table).values(state_json={}), delete(table)):
        with forbid_immutable_writes(db_session) as guard:
            await db_session.execute(statement.where(table.c.novel_id == uuid.uuid4()))
        with pytest.raises(AssertionError, match=table_name):
            guard.assert_clean()
