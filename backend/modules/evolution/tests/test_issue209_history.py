"""Synthetic histories exercise the real prefix validator without provider output."""

from uuid import UUID

import pytest
from sqlalchemy import select

from modules.evolution.ledger import claim_freshness
from modules.evolution.models import EvolutionFrozenAttempt
from modules.evolution.tests.issue209_data import seed_history
from modules.writing.models import WritingDraft


@pytest.mark.parametrize("scenes", [1, 10, 100])
async def test_history_dependencies_and_same_length_source_edit(
    db_session, evolution_project_id, scenes
):
    db, nid = db_session, evolution_project_id
    claims = await seed_history(db, nid, scenes)
    await db.commit()
    claim = claims[-1].model_copy(
        update={"dependencies": [item.dependencies[0] for item in claims]}
    )
    assert await claim_freshness(db, nid, claim) == "current"
    draft = await db.get(WritingDraft, UUID(claims[0].evidence[0].source_ref.draft_id))
    draft.content = "否" + draft.content[1:]
    await db.commit()
    assert await claim_freshness(db, nid, claim) == "source_changed"
    assert await claim_freshness(db, nid, claims[0]) == "source_changed"
    # Hash or selected dependence changes cannot bypass frozen-source checks.
    assert (
        await claim_freshness(
            db,
            nid,
            claims[-1].model_copy(
                update={
                    "dependencies": [
                        claims[-1]
                        .dependencies[0]
                        .model_copy(update={"source_manifest_hash": "b" * 64})
                    ]
                }
            ),
        )
        == "source_changed"
    )
    row = await db.scalar(
        select(EvolutionFrozenAttempt).where(
            EvolutionFrozenAttempt.novel_id == UUID(nid),
            EvolutionFrozenAttempt.attempt_key == claims[-1].dependencies[0].attempt_id,
        )
    )
    assert row.status == "applied"  # Qualification never rewrites history.
