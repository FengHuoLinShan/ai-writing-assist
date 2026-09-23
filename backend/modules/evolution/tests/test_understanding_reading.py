"""Committed observations cannot survive a changed prefix or Scene authority."""

from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import select

from core.errors import ConflictError
from modules.evolution.facade import read_committed_understanding
from modules.evolution.models import EvolutionRun
from modules.evolution.sampler import register_scene_sampler
from modules.evolution.tasks import handle_evolution_scene_step
from modules.story.outline_state.models import Scene
from modules.writing.facade import create_draft_only


async def test_append_preserves_refs_but_shadow_exclusion_and_recompute_do_not_widen_them(
    db_session, evolution_project_id
):
    db, nid = db_session, evolution_project_id
    drafts = [
        await create_draft_only(db, nid, index + 1, content=f"第{index}次钟声。")
        for index in range(2)
    ]
    scenes = [
        Scene(
            novel_id=UUID(nid),
            scene_index=index,
            chapter_ids=[index + 1],
            scene_chunks=[],
            status="draft",
        )
        for index in range(2)
    ]
    db.add_all(scenes)
    await db.commit()

    class Sampler:
        async def sample(self, *, scene_text, input_manifest):
            return {
                "observations": [
                    {
                        "predicate": "钟声响起",
                        "quote": scene_text,
                        "modality": "event_observed",
                        "mentions": [],
                    }
                ]
            }

    provider = "read-boundaries-" + nid
    register_scene_sampler(provider, lambda db, novel_id: Sampler())

    async def step(run, index, mode="live"):
        await handle_evolution_scene_step(
            db,
            SimpleNamespace(
                meta={
                    "novel_id": nid,
                    "run_key": run,
                    "scene_index": index,
                    "scene_id": str(scenes[index].id),
                    "chapter_index": index + 1,
                    "scene_text": drafts[index].content,
                    "sampler_provider": provider,
                    "execution_mode": mode,
                    "budget_total": 4,
                }
            ),
        )
        await db.commit()

    hashes = {draft.id: draft.content_hash for draft in drafts}
    await step("first", 0)
    original, _ = await read_committed_understanding(db, nid, hashes)
    assert len(original) == 1
    await step("first", 1)
    assert await read_committed_understanding(db, nid, hashes, required=original) == (
        original,
        [],
    )
    refs, _ = await read_committed_understanding(
        db, nid, {drafts[1].id: drafts[1].content_hash}
    )
    assert refs == []
    await step("shadow", 0, "shadow")
    assert await read_committed_understanding(db, nid, hashes, required=original) == (
        original,
        [],
    )
    run = await db.scalar(
        select(EvolutionRun).where(
            EvolutionRun.novel_id == UUID(nid), EvolutionRun.run_key == "first"
        )
    )
    run.status = "drained"
    await db.commit()
    await step("replacement", 0)
    with pytest.raises(ConflictError, match="场景理解"):
        await read_committed_understanding(db, nid, hashes, required=original)
    replacements, _ = await read_committed_understanding(db, nid, hashes)
    assert len(replacements) == 1 and replacements[0].run_key == "replacement"
    scenes[0].structure_meta = {"phase1a_fallback": True, "needs_review": True}
    await db.commit()
    with pytest.raises(ConflictError, match="场景理解"):
        await read_committed_understanding(db, nid, hashes, required=replacements)
    scenes[0].structure_meta = {
        "review_issues_version": 1,
        "review_issues": [{"kind": "optional_interpretation", "required": False}],
    }
    await db.commit()
    assert (await read_committed_understanding(db, nid, hashes, required=replacements))[
        0
    ] == replacements
    scenes[0].chapter_ids = [99]
    await db.commit()
    with pytest.raises(ConflictError, match="场景理解"):
        await read_committed_understanding(db, nid, hashes, required=replacements)
