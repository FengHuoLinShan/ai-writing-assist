from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select

from modules.world.map_atlas_models import MapAtlasNode, MapAtlasPage, MapAtlasRun
from modules.world.map_atlas_schemas import AtlasPlan
from modules.world.map_atlas_workflow import _persist_plan
from modules.world.models import CoreEntity


def _node(
    *,
    plan_key: str,
    level: str,
    parent_plan_key: str | None = None,
    existing_parent_node_id: str | None = None,
) -> dict[str, object]:
    return {
        "plan_key": plan_key,
        "parent_plan_key": parent_plan_key,
        "existing_parent_node_id": existing_parent_node_id,
        "title": plan_key,
        "level": level,
        "summary": plan_key,
        "visual_brief": f"{plan_key} map",
    }


def test_plan_rejects_non_monotonic_parent_levels() -> None:
    with pytest.raises(PydanticValidationError, match="strictly above"):
        AtlasPlan(
            style_brief="atlas",
            nodes=[
                _node(plan_key="district", level="district"),
                _node(
                    plan_key="city",
                    level="city",
                    parent_plan_key="district",
                ),
            ],
        )


@pytest.mark.parametrize("root_level", ["cover", "world"])
def test_cover_and_world_cannot_have_a_parent(root_level: str) -> None:
    with pytest.raises(PydanticValidationError, match="must be roots"):
        AtlasPlan(
            style_brief="atlas",
            nodes=[
                _node(plan_key="root", level="region"),
                _node(
                    plan_key=root_level,
                    level=root_level,
                    parent_plan_key="root",
                ),
            ],
        )


def test_interior_cannot_have_a_child() -> None:
    with pytest.raises(PydanticValidationError, match="strictly above"):
        AtlasPlan(
            style_brief="atlas",
            nodes=[
                _node(plan_key="interior", level="interior"),
                _node(
                    plan_key="street",
                    level="street",
                    parent_plan_key="interior",
                ),
            ],
        )


@pytest.mark.asyncio
async def test_existing_parent_uses_its_persisted_level(
    db_session,
    test_project_id,
) -> None:
    run = MapAtlasRun(
        novel_id=uuid.UUID(test_project_id),
        run_kind="update",
        status="planning",
    )
    db_session.add(run)
    await db_session.flush()
    parent = MapAtlasNode(
        novel_id=run.novel_id,
        created_by_run_id=run.id,
        semantic_key="district",
        title="district",
        level="district",
        status="adopted",
    )
    db_session.add(parent)
    await db_session.flush()
    plan = AtlasPlan(
        style_brief="atlas",
        nodes=[
            _node(
                plan_key="city",
                level="city",
                existing_parent_node_id=str(parent.id),
            )
        ],
    )

    with pytest.raises(ValueError, match="strictly above"):
        await _persist_plan(db_session, object(), run, plan)


@pytest.mark.asyncio
async def test_interior_still_requires_run_authorization(
    db_session,
    test_project_id,
) -> None:
    run = MapAtlasRun(
        novel_id=uuid.UUID(test_project_id),
        run_kind="initial",
        status="planning",
        include_interiors=False,
    )
    db_session.add(run)
    await db_session.flush()
    plan = AtlasPlan(
        style_brief="atlas",
        nodes=[_node(plan_key="interior", level="interior")],
    )

    with pytest.raises(ValueError, match="unapproved interior"):
        await _persist_plan(db_session, object(), run, plan)


@pytest.mark.asyncio
async def test_reused_node_keeps_canonical_metadata_until_candidate_adoption(
    db_session,
    test_project_id,
) -> None:
    novel_id = uuid.UUID(test_project_id)
    original_run = MapAtlasRun(
        novel_id=novel_id,
        run_kind="initial",
        status="completed",
    )
    update_run = MapAtlasRun(
        novel_id=novel_id,
        run_kind="update",
        status="planning",
    )
    location = CoreEntity(
        novel_id=novel_id,
        entity_type="location",
        name="旧城",
        status="canonical",
    )
    db_session.add_all([original_run, update_run, location])
    await db_session.flush()
    parent = MapAtlasNode(
        novel_id=novel_id,
        created_by_run_id=original_run.id,
        semantic_key="east",
        title="东境",
        level="region",
        status="adopted",
    )
    old_parent = MapAtlasNode(
        novel_id=novel_id,
        created_by_run_id=original_run.id,
        semantic_key="west",
        title="西境",
        level="region",
        status="adopted",
    )
    db_session.add_all([parent, old_parent])
    await db_session.flush()
    reused = MapAtlasNode(
        novel_id=novel_id,
        created_by_run_id=original_run.id,
        parent_id=old_parent.id,
        location_entity_id=location.id,
        semantic_key=f"entity:{location.id}",
        title="旧城",
        level="city",
        status="adopted",
        summary="旧摘要",
        sort_order=1,
    )
    db_session.add(reused)
    update_run.source_manifest = [
        {"source_type": "entity", "source_id": str(location.id)}
    ]
    await db_session.flush()
    plan = AtlasPlan(
        style_brief="atlas",
        nodes=[
            {
                **_node(
                    plan_key="city",
                    level="city",
                    existing_parent_node_id=str(parent.id),
                ),
                "location_entity_id": str(location.id),
                "title": "新城",
                "summary": "新摘要",
            }
        ],
    )

    with patch(
        "modules.world.map_atlas_workflow._require_attempt",
        autospec=True,
    ):
        await _persist_plan(db_session, object(), update_run, plan)

    page = (
        await db_session.execute(
            select(MapAtlasPage).where(MapAtlasPage.run_id == update_run.id)
        )
    ).scalar_one()
    assert (reused.parent_id, reused.title, reused.summary, reused.sort_order) == (
        old_parent.id,
        "旧城",
        "旧摘要",
        1,
    )
    assert page.node_id == reused.id
    assert page.node_proposal == {
        "node_id": str(reused.id),
        "parent_id": str(parent.id),
        "title": "新城",
        "level": "city",
        "summary": "新摘要",
        "sort_order": 0,
    }
