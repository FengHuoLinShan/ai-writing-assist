import uuid

import pytest

from modules.world.models import CoreEntity, WorldBiblePage
from modules.world.services.worldbuilding.activation_preview_service import (
    ActivationPreviewService,
)


@pytest.mark.asyncio
async def test_activation_preview_accepts_legacy_page_asset_refs(
    db_session,
    project_novel_id: str,
) -> None:
    entity = CoreEntity(
        novel_id=uuid.UUID(project_novel_id),
        entity_type="location",
        name="北境港口",
        status="canonical",
        importance=0.8,
    )
    page = WorldBiblePage(
        novel_id=uuid.UUID(project_novel_id),
        page_type="location",
        page_key="location:north-port",
        title="北境商路",
        status="canonical",
        linked_asset_refs_json=[],
    )
    db_session.add_all([entity, page])
    await db_session.flush()
    page.linked_asset_refs_json = [{"type": "core_entity", "id": str(entity.id)}]
    await db_session.flush()

    result = await ActivationPreviewService().preview(
        db_session,
        project_novel_id,
        depth=2,
    )

    assert [item["target"]["target_id"] for item in result["items"]] == [
        str(entity.id)
    ]
    assert result["items"][0]["decision"] == "included"
    assert result["items"][0]["source"] == "page_linked"
    assert result["rule_evaluations"][-1]["candidate_count"] == 1


@pytest.mark.asyncio
async def test_activation_preview_traces_missing_and_top_k_exclusions(
    db_session,
    project_novel_id: str,
) -> None:
    entities = [
        CoreEntity(
            novel_id=uuid.UUID(project_novel_id),
            entity_type="location",
            name=f"地点 {index}",
            status="canonical",
            importance=float(index) / 10,
        )
        for index in range(2)
    ]
    db_session.add_all(entities)
    await db_session.flush()

    missing_id = str(uuid.uuid4())
    result = await ActivationPreviewService().preview(
        db_session,
        project_novel_id,
        entity_ids=[str(item.id) for item in entities] + [missing_id],
        depth=0,
        top_k=1,
    )

    assert len(result["items"]) == 1
    reasons = {item["excluded_reason"] for item in result["excluded_items"]}
    assert reasons == {"target_missing", "rule_top_k"}
    assert result["rule_evaluations"][0] == {
        "rule_id": "legacy_explicit",
        "matched": True,
        "matched_clauses": ["explicit_target"],
        "blocked_clauses": [],
        "candidate_count": 2,
    }
