from __future__ import annotations

from dataclasses import asdict
from types import SimpleNamespace

import pytest

from modules.story.character_arcs import service
from modules.writing.facade import build_manuscript_range_ref, create_published_draft_only


@pytest.mark.asyncio
async def test_arc_actual_requires_exact_current_canonical_evidence(
    db_session, test_project_id, monkeypatch
) -> None:
    text = "她终于叫住了正要离开的同伴。"
    draft = await create_published_draft_only(
        db_session,
        test_project_id,
        2,
        "第二章",
        text,
    )
    ref = await build_manuscript_range_ref(
        db_session,
        test_project_id,
        draft_id=str(draft.id),
        start_offset=0,
        end_offset=len(text),
        content_mode="canonical",
    )
    ref_value = ref.model_dump(mode="json") if hasattr(ref, "model_dump") else asdict(ref)
    evidence_state = {"degraded": False, "range_matches": True}

    async def read_evidence(*_args, **_kwargs):
        source_ref = dict(ref_value)
        if not evidence_state["range_matches"]:
            source_ref["range_hash"] = "0" * 64
        return {
            "source_ref": source_ref,
            "visibility_decision": {"mode": "author", "visible": True},
            "degraded": evidence_state["degraded"],
            "index_fresh": True,
            "text": text,
        }

    monkeypatch.setattr(service, "read_novel_evidence", read_evidence)
    item = {
        "field": "求助行为",
        "value": "向同伴求援",
        "layer": "fact",
        "possibly_false": False,
        "occurred_at": {"scene_index": 2},
        "provenance": {"status": "exact"},
        "source_refs": [ref_value],
    }
    scene = SimpleNamespace(scene_index=3)

    verified = await service._verified_event(db_session, test_project_id, scene, 2, item)
    assert verified is not None
    assert verified.quote == text
    assert verified.chapter_index == 2

    evidence_state["range_matches"] = False
    assert (
        await service._verified_event(db_session, test_project_id, scene, 2, item) is None
    )
    evidence_state["range_matches"] = True
    evidence_state["degraded"] = True
    assert (
        await service._verified_event(db_session, test_project_id, scene, 2, item) is None
    )
    evidence_state["degraded"] = False
    assert (
        await service._verified_event(db_session, test_project_id, scene, 1, item) is None
    )


@pytest.mark.asyncio
async def test_arc_actual_rejects_belief_or_future_scene_even_when_source_is_current(
    db_session, test_project_id, monkeypatch
) -> None:
    text = "她终于叫住了正要离开的同伴。"
    draft = await create_published_draft_only(
        db_session,
        test_project_id,
        2,
        "第二章",
        text,
    )
    ref = await build_manuscript_range_ref(
        db_session,
        test_project_id,
        draft_id=str(draft.id),
        start_offset=0,
        end_offset=len(text),
        content_mode="canonical",
    )
    ref_value = ref.model_dump(mode="json") if hasattr(ref, "model_dump") else asdict(ref)

    async def read_evidence(*_args, **_kwargs):
        return {
            "source_ref": ref_value,
            "visibility_decision": {"mode": "author", "visible": True},
            "degraded": False,
            "index_fresh": True,
            "text": text,
        }

    monkeypatch.setattr(service, "read_novel_evidence", read_evidence)
    scene = SimpleNamespace(scene_index=3)
    item = {
        "field": "求助行为",
        "value": "向同伴求援",
        "layer": "belief",
        "possibly_false": False,
        "occurred_at": {"scene_index": 2},
        "provenance": {"status": "exact"},
        "source_refs": [ref_value],
    }
    assert (
        await service._verified_event(db_session, test_project_id, scene, 2, item) is None
    )

    item["layer"] = "fact"
    item["occurred_at"] = {"scene_index": 4}
    assert (
        await service._verified_event(db_session, test_project_id, scene, 2, item) is None
    )
