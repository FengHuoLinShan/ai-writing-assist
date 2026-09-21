import uuid
from dataclasses import asdict

import pytest

from modules.evidence.compilation.contracts import VisibilityContextContract
from modules.evidence.compilation.facade import read_novel_evidence
from modules.evidence.compilation.services.parent_evidence import bounded_ranges
from modules.story.outline_state.facade import bind_scene_spans_to_source
from modules.story.outline_state.repositories import SceneRepository
from modules.story.outline_state.schemas import SceneCreate
from modules.writing.facade import build_manuscript_range_ref, create_published_draft_only


async def story(db, novel_id, *, scene=True, paragraph_break="\n\n"):
    texts = ["前言。\n\n林晚看见铜铃，却不知道暗号。\n\n尾声。", "次日才得知铜铃是暗号。"]
    texts[0] = texts[0].replace("\n\n", paragraph_break)
    drafts = [
        await create_published_draft_only(db, novel_id, i, f"第{i}章", text)
        for i, text in enumerate(texts, 1)
    ]
    if scene:
        await SceneRepository().create(
            db,
            uuid.UUID(novel_id),
            SceneCreate(
                scene_index=1,
                title="铜铃",
                status="canonical",
                chapter_ids=["1", "2"],
                scene_chunks=[
                    {"chapter_index": i, "start_offset": 0, "end_offset": len(text)}
                    for i, text in enumerate(texts, 1)
                ],
            ),
        )
        for draft, text in zip(drafts, texts):
            await bind_scene_spans_to_source(
                db,
                novel_id=novel_id,
                chapter_index=draft.chapter_index,
                content_mode="canonical",
                source_draft_id=draft.id,
                source_content_hash=draft.content_hash,
                content=text,
            )
    start = texts[0].index("铜铃")
    ref = await build_manuscript_range_ref(
        db,
        novel_id,
        draft_id=drafts[0].id,
        start_offset=start,
        end_offset=start + 2,
        content_mode="canonical",
    )
    return texts, drafts, ref


def test_intersection_unions_overlap_but_preserves_excluded_gaps():
    assert bounded_ranges(0, 20, allowed=[(0, 8), (4, 15)], excluded=[(6, 10)]) == [
        (0, 6),
        (10, 15),
    ]
    assert bounded_ranges(0, 20, allowed=[]) == []


@pytest.mark.asyncio
async def test_parent_scene_reads_each_source_and_never_future(
    db_session, test_project_id
):
    texts, _, ref = await story(db_session, test_project_id)
    result = await read_novel_evidence(
        db_session,
        novel_id=test_project_id,
        source_ref=ref,
        visibility=VisibilityContextContract(mode="reader", cutoff_chapter=1),
        before=0,
        after=0,
        expand_parent=True,
    )
    parent = result["parent_context"]
    assert [segment["text"] for segment in parent["segments"]] == [texts[0]]
    assert "visibility_cutoff" in parent["omissions"]
    assert not parent["complete"]
    result = await read_novel_evidence(
        db_session,
        novel_id=test_project_id,
        source_ref=ref,
        visibility=VisibilityContextContract(mode="author"),
        expand_parent=True,
    )
    assert len(result["parent_context"]["segments"]) == 2
    assert result["parent_context"]["complete"]


@pytest.mark.asyncio
async def test_parent_obeys_frozen_ranges_exclusions_and_budget(
    db_session, test_project_id
):
    texts, drafts, ref = await story(db_session, test_project_id)
    allowed = {**asdict(ref), "start_offset": 0, "end_offset": len(texts[0])}
    excluded = {**allowed, "start_offset": 0, "end_offset": 3}
    scope = dict(
        source_manifest={drafts[0].id: drafts[0].content_hash},
        allowed_ranges=[allowed],
        excluded_ranges=[excluded],
        max_parent_characters=12,
    )
    result = await read_novel_evidence(
        db_session,
        novel_id=test_project_id,
        source_ref=ref,
        visibility=VisibilityContextContract(mode="author"),
        expand_parent=True,
        **scope,
    )
    parent = result["parent_context"]
    assert sum(len(segment["text"]) for segment in parent["segments"]) == 12
    assert all(
        segment["source_ref"]["start_offset"] >= 3 for segment in parent["segments"]
    )
    assert set(parent["omissions"]) >= {
        "scope_clipped",
        "character_budget",
        "source_outside_manifest_or_stale",
    }
    with pytest.raises(ValueError, match="允许的区间"):
        await read_novel_evidence(
            db_session,
            novel_id=test_project_id,
            source_ref=ref,
            visibility=VisibilityContextContract(mode="author"),
            expand_parent=True,
            allowed_ranges=[],
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("paragraph_break", ["\n", "\n\n"])
async def test_unmapped_parent_is_paragraph_and_character_expansion_is_withheld(
    db_session, test_project_id, paragraph_break
):
    texts, _, ref = await story(
        db_session, test_project_id, scene=False, paragraph_break=paragraph_break
    )
    result = await read_novel_evidence(
        db_session,
        novel_id=test_project_id,
        source_ref=ref,
        visibility=VisibilityContextContract(mode="author"),
        expand_parent=True,
    )
    assert (
        result["parent_context"]["segments"][0]["text"]
        == texts[0].split(paragraph_break)[1]
    )
    result = await read_novel_evidence(
        db_session,
        novel_id=test_project_id,
        source_ref=ref,
        visibility=VisibilityContextContract(
            mode="character", character_id=str(uuid.uuid4()), cutoff_chapter=1
        ),
        before=0,
        after=0,
        expand_parent=True,
    )
    assert result["parent_context"]["segments"] == []
    assert result["parent_context"]["omissions"] == ["character_knowledge_unproven"]


@pytest.mark.asyncio
async def test_parent_http_contract_cutoff_and_foreign_project(
    db_session, test_project_id, async_client
):
    texts, _, ref = await story(db_session, test_project_id)
    cutoff = ref.end_offset + 1
    await db_session.commit()
    payload = {
        "novel_id": test_project_id,
        "content_mode": "canonical",
        "source_ref": asdict(ref),
        "before": 0,
        "after": 0,
        "expand_parent": True,
        "visibility": {"mode": "reader", "cutoff_chapter": 1, "cutoff_offset": cutoff},
    }
    response = await async_client.post(
        "/api/evidence/compilation/evidence/read", json=payload
    )
    assert response.status_code == 200, response.text
    parent = response.json()["parent_context"]
    assert parent["segments"][0]["text"] == texts[0][:cutoff]
    assert parent["segments"][0]["source_ref"]["end_offset"] == cutoff
    assert not parent["complete"]
    other = await async_client.post(
        "/api/evidence/compilation/evidence/read",
        json={**payload, "novel_id": str(uuid.uuid4())},
    )
    assert other.status_code == 404
