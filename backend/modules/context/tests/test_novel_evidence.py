from __future__ import annotations

import uuid

import pytest

from modules.context.contracts import VisibilityContextContract
from modules.context.facade import (
    grep_novel_evidence,
    inspect_novel_target,
    locate_scene_quote,
    read_novel_evidence,
    record_evidence_link,
    record_unresolved_evidence_link,
    search_novel_evidence,
    trace_novel_evidence,
)
from modules.writing.contracts import SourceRangeRefContract
from modules.writing.facade import create_published_draft_only, grep_manuscript


@pytest.mark.asyncio
async def test_reader_cutoff_filters_grep_and_read(
    db_session,
    test_project_id,
) -> None:
    await create_published_draft_only(
        db_session,
        test_project_id,
        80,
        "第八十章",
        "当前可见秘密",
    )
    await create_published_draft_only(
        db_session,
        test_project_id,
        81,
        "第八十一章",
        "未来不可见秘密",
    )
    visibility = VisibilityContextContract(mode="reader", cutoff_chapter=80)

    result = await grep_novel_evidence(
        db_session,
        novel_id=test_project_id,
        pattern="秘密",
        content_mode="canonical",
        visibility=visibility,
    )

    assert [item["chapter_index"] for item in result["hits"]] == [80]

    future, _, _ = await grep_manuscript(
        db_session,
        test_project_id,
        "未来不可见",
        content_mode="canonical",
    )
    with pytest.raises(ValueError, match="超出当前可见截止位置"):
        await read_novel_evidence(
            db_session,
            novel_id=test_project_id,
            source_ref=future[0].source_ref,
            visibility=visibility,
        )


@pytest.mark.asyncio
async def test_same_chapter_offset_filters_grep_read_and_paragraph_expansion(
    db_session,
    test_project_id,
) -> None:
    content = "可见段落。\n截止点后的未来秘密。"
    cutoff = content.index("截止点后")
    await create_published_draft_only(
        db_session,
        test_project_id,
        80,
        "第八十章",
        content,
    )
    visibility = VisibilityContextContract(
        mode="reader",
        cutoff_chapter=80,
        cutoff_offset=cutoff,
    )

    hidden = await grep_novel_evidence(
        db_session,
        novel_id=test_project_id,
        pattern="未来秘密",
        content_mode="canonical",
        visibility=visibility,
    )
    visible = await grep_novel_evidence(
        db_session,
        novel_id=test_project_id,
        pattern="可见段落",
        content_mode="canonical",
        visibility=visibility,
    )
    raw_hidden, _, _ = await grep_manuscript(
        db_session,
        test_project_id,
        "未来秘密",
        content_mode="canonical",
    )

    assert hidden["hits"] == []
    read = await read_novel_evidence(
        db_session,
        novel_id=test_project_id,
        source_ref=SourceRangeRefContract(**visible["hits"][0]["source_ref"]),
        visibility=visibility,
        before=0,
        after=3,
    )
    assert "可见段落" in read["text"]
    assert "未来秘密" not in read["text"]
    with pytest.raises(ValueError, match="超出当前可见截止位置"):
        await read_novel_evidence(
            db_session,
            novel_id=test_project_id,
            source_ref=raw_hidden[0].source_ref,
            visibility=visibility,
        )


@pytest.mark.asyncio
async def test_trace_rehydrates_valid_original_text(
    db_session,
    test_project_id,
) -> None:
    await create_published_draft_only(
        db_session,
        test_project_id,
        50,
        "第五十章",
        "阿澜在旧塔得知密钥藏在钟后。",
    )
    hits, _, _ = await grep_manuscript(
        db_session,
        test_project_id,
        "密钥藏在钟后",
        content_mode="canonical",
    )
    from modules.world.facade import create_entity

    entity = await create_entity(
        db_session,
        test_project_id,
        {
            "name": "旧塔密钥",
            "entity_type": "item",
            "summary": "密钥藏在钟后",
            "status": "canonical",
        },
    )
    target = {
        "target_type": "world_entity",
        "target_id": str(entity["id"]),
        "target_path": "summary",
    }
    await record_evidence_link(
        db_session,
        novel_id=test_project_id,
        target_ref=target,
        source_ref=hits[0].source_ref,
        claim_path="summary",
        provenance={"workflow": "test"},
    )

    trace = await trace_novel_evidence(
        db_session,
        novel_id=test_project_id,
        target_ref=target,
        claim_path="summary",
        content_mode="canonical",
        visibility=VisibilityContextContract(mode="reader", cutoff_chapter=51),
    )

    assert len(trace["links"]) == 1
    assert "密钥藏在钟后" in trace["links"][0]["read"]["text"]
    assert trace["links"][0]["source_ref"]["range_hash"]


@pytest.mark.asyncio
async def test_reader_trace_excludes_unresolved_source_and_invisible_target(
    db_session,
    test_project_id,
) -> None:
    from modules.world.facade import create_entity

    entity = await create_entity(
        db_session,
        test_project_id,
        {
            "name": "未公开的暗号",
            "entity_type": "secret",
            "summary": "未来暗号",
            "status": "candidate",
        },
    )
    target = {
        "target_type": "world_entity",
        "target_id": str(entity["id"]),
        "target_path": "summary",
    }
    await record_unresolved_evidence_link(
        db_session,
        novel_id=test_project_id,
        target_ref=target,
        claim_path="summary",
        provenance={"quote": "未来暗号"},
    )

    trace = await trace_novel_evidence(
        db_session,
        novel_id=test_project_id,
        target_ref=target,
        claim_path="summary",
        content_mode="canonical",
        visibility=VisibilityContextContract(mode="reader", cutoff_chapter=5),
    )

    assert trace["links"] == []
    assert trace["visibility_decision"]["visible"] is False
    assert all("未来暗号" not in warning for warning in trace["warnings"])


@pytest.mark.asyncio
async def test_reader_reveal_policy_redacts_until_prior_stage(
    db_session,
    test_project_id,
) -> None:
    from modules.outline.reveal_repository import RevealPlanRepository
    from modules.world.facade import create_entity

    entity = await create_entity(
        db_session,
        test_project_id,
        {
            "name": "旧塔密钥",
            "entity_type": "item",
            "summary": "密钥其实是唤醒古神的媒介",
            "public_info": "一把普通的铜钥匙",
            "status": "canonical",
        },
    )
    entity_id = str(entity["id"])
    await RevealPlanRepository().create(
        db_session,
        uuid.UUID(test_project_id),
        {
            "target_type": "entity",
            "target_id": uuid.UUID(entity_id),
            "secret_summary": "古神媒介",
            "reveal_stages": [
                {
                    "stage_index": 0,
                    "chapter_index": 60,
                    "reveal_content": "读者已知密钥与仪式有关",
                }
            ],
            "status": "canonical",
            "provenance_meta": {},
        },
    )
    target = {
        "target_type": "world_entity",
        "target_id": entity_id,
        "target_path": "",
    }

    before = await inspect_novel_target(
        db_session,
        novel_id=test_project_id,
        target_ref=target,
        content_mode="canonical",
        visibility=VisibilityContextContract(mode="reader", cutoff_chapter=60),
    )
    after = await inspect_novel_target(
        db_session,
        novel_id=test_project_id,
        target_ref=target,
        content_mode="canonical",
        visibility=VisibilityContextContract(mode="reader", cutoff_chapter=61),
    )

    assert before["item"]["summary"] is None
    assert before["item"]["public_info"] == "一把普通的铜钥匙"
    assert before["degraded"] is True
    assert after["item"]["reader_reveal_content"] == "读者已知密钥与仪式有关"
    assert after["visibility_decision"]["visible"] is True


@pytest.mark.asyncio
async def test_inspect_does_not_count_forged_source_ref(
    db_session,
    test_project_id,
) -> None:
    from modules.context.evidence_repository import EvidenceLinkRepository
    from modules.world.facade import create_entity
    from shared.target_ref import normalize_target_ref

    entity = await create_entity(
        db_session,
        test_project_id,
        {
            "name": "伪造引用对象",
            "entity_type": "item",
            "public_info": "读者可见",
            "status": "canonical",
        },
    )
    target_dict = {
        "target_type": "world_entity",
        "target_id": str(entity["id"]),
        "target_path": "summary",
    }
    target = normalize_target_ref(target_dict)
    await EvidenceLinkRepository().create(
        db_session,
        novel_id=uuid.UUID(test_project_id),
        target_ref=target.canonical_dict(),
        target_hash=target.target_hash(),
        claim_path="summary",
        evidence_type="supports",
        source_ref={
            "draft_id": str(uuid.uuid4()),
            "chapter_index": 1,
            "version_number": 1,
            "content_mode": "canonical",
            "start_offset": 0,
            "end_offset": 1,
            "source_hash": "0" * 64,
            "range_hash": "0" * 64,
        },
        precision="range",
        status="active",
        provenance={"workflow": "forged-test"},
    )

    result = await inspect_novel_target(
        db_session,
        novel_id=test_project_id,
        target_ref=target_dict,
        content_mode="canonical",
        visibility=VisibilityContextContract(mode="reader", cutoff_chapter=2),
    )

    assert result["visible"] is True
    assert result["evidence_count"] == 0
    assert result["index_fresh"] is False
    assert any("已失效" in warning for warning in result["warnings"])


@pytest.mark.asyncio
async def test_reader_inspect_without_reveal_policy_uses_public_baseline(
    db_session,
    test_project_id,
) -> None:
    from modules.world.facade import create_entity

    entity = await create_entity(
        db_session,
        test_project_id,
        {
            "name": "铜钥匙",
            "entity_type": "item",
            "summary": "它是唤醒古神的媒介",
            "public_info": "一把普通铜钥匙",
            "hidden_truth": "仪式真相",
            "status": "canonical",
        },
    )

    result = await inspect_novel_target(
        db_session,
        novel_id=test_project_id,
        target_ref={
            "target_type": "world_entity",
            "target_id": str(entity["id"]),
            "target_path": "",
        },
        content_mode="canonical",
        visibility=VisibilityContextContract(mode="reader", cutoff_chapter=80),
    )

    assert result["item"]["summary"] == "一把普通铜钥匙"
    assert result["item"]["hidden_truth"] is None
    assert "古神" not in str(result["item"])
    assert "仪式真相" not in str(result["item"])


@pytest.mark.asyncio
async def test_scene_quote_requires_unique_exact_span_before_active_link(
    db_session,
    test_project_id,
) -> None:
    from modules.outline.facade import bind_scene_spans_to_source
    from modules.outline.repositories import SceneRepository
    from modules.outline.schemas import SceneCreate

    content = "雨夜里，周明瑞醒来时发现自己成了克莱恩。"
    draft = await create_published_draft_only(
        db_session,
        test_project_id,
        3,
        "第三章",
        content,
    )
    quote = "周明瑞醒来时发现自己成了克莱恩。"
    start = content.index(quote)
    scene = await SceneRepository().create(
        db_session,
        uuid.UUID(test_project_id),
        SceneCreate(
            scene_index=3,
            title="雨夜苏醒",
            chapter_ids=["3"],
            scene_chunks=[
                {
                    "chapter_index": 3,
                    "start_offset": start,
                    "end_offset": start + len(quote),
                }
            ],
            status="canonical",
        ),
    )
    await bind_scene_spans_to_source(
        db_session,
        novel_id=test_project_id,
        chapter_index=3,
        content_mode="canonical",
        source_draft_id=draft.id or "",
        source_content_hash=draft.content_hash,
        content=content,
    )

    source_ref, reason = await locate_scene_quote(
        db_session,
        novel_id=test_project_id,
        scene_id=str(scene.id),
        quote=quote,
        content_mode="canonical",
    )

    assert reason is None
    assert source_ref is not None
    assert source_ref.draft_id == draft.id
    assert source_ref.start_offset == start


@pytest.mark.asyncio
async def test_scene_quote_cannot_resolve_beyond_phase2_visible_chapter(
    db_session,
    test_project_id,
) -> None:
    from modules.outline.facade import bind_scene_spans_to_source
    from modules.outline.repositories import SceneRepository
    from modules.outline.schemas import SceneCreate
    from modules.writing.facade import create_draft_only

    visible = "可见章节只有铜铃。"
    future = "未来章节才出现黑日密钥。"
    visible_draft = await create_draft_only(
        db_session,
        test_project_id,
        80,
        content=visible,
    )
    future_draft = await create_draft_only(
        db_session,
        test_project_id,
        81,
        content=future,
    )
    scene = await SceneRepository().create(
        db_session,
        uuid.UUID(test_project_id),
        SceneCreate(
            scene_index=80,
            title="跨章密钥",
            chapter_ids=["80", "81"],
            scene_chunks=[
                {"chapter_index": 80, "start_offset": 0, "end_offset": len(visible)},
                {"chapter_index": 81, "start_offset": 0, "end_offset": len(future)},
            ],
            status="canonical",
        ),
    )
    for chapter, draft, content in (
        (80, visible_draft, visible),
        (81, future_draft, future),
    ):
        await bind_scene_spans_to_source(
            db_session,
            novel_id=test_project_id,
            chapter_index=chapter,
            content_mode="working",
            source_draft_id=draft.id or "",
            source_content_hash=draft.content_hash,
            content=content,
        )

    blocked, reason = await locate_scene_quote(
        db_session,
        novel_id=test_project_id,
        scene_id=str(scene.id),
        quote="黑日密钥",
        content_mode="working",
        visible_until_chapter=80,
    )
    global_ref, global_reason = await locate_scene_quote(
        db_session,
        novel_id=test_project_id,
        scene_id=str(scene.id),
        quote="黑日密钥",
        content_mode="working",
    )

    assert blocked is None
    assert reason == "quote_not_found_in_visible_scene"
    assert global_ref is not None
    assert global_reason is None
    assert global_ref.chapter_index == 81


@pytest.mark.asyncio
async def test_working_smart_search_reports_pending_index_without_old_chunks(
    db_session,
    test_project_id,
) -> None:
    from modules.rag.facade import request_chapter_index
    from modules.writing.facade import create_draft_only

    await create_draft_only(
        db_session,
        test_project_id,
        9,
        content="工作稿新增的铜铃线索",
    )
    await request_chapter_index(
        db_session,
        test_project_id,
        9,
        content_mode="working",
    )

    result = await search_novel_evidence(
        db_session,
        novel_id=test_project_id,
        query="铜铃",
        content_mode="working",
        visibility=VisibilityContextContract(mode="author"),
        scopes=["manuscript"],
        chapter_from=9,
        chapter_to=9,
    )

    assert result["hits"] == []
    assert result["degraded"] is True
    assert any("工作稿索引更新中" in item for item in result["warnings"])


@pytest.mark.asyncio
async def test_reader_outline_search_marks_extract_only_checkpoint_degraded(
    db_session,
    test_project_id,
) -> None:
    from modules.outline.facade import bind_scene_spans_to_source
    from modules.outline.repositories import SceneRepository
    from modules.outline.schemas import SceneCreate

    content = "铜铃在雨夜响起。"
    draft = await create_published_draft_only(
        db_session,
        test_project_id,
        12,
        "第十二章",
        content,
    )
    scene = await SceneRepository().create(
        db_session,
        uuid.UUID(test_project_id),
        SceneCreate(
            scene_index=12,
            title="雨夜铜铃",
            chapter_ids=["12"],
            scene_chunks=[
                {"chapter_index": 12, "start_offset": 0, "end_offset": len(content)}
            ],
            status="canonical",
        ),
    )
    await bind_scene_spans_to_source(
        db_session,
        novel_id=test_project_id,
        chapter_index=12,
        content_mode="canonical",
        source_draft_id=draft.id or "",
        source_content_hash=draft.content_hash,
        content=content,
    )

    result = await search_novel_evidence(
        db_session,
        novel_id=test_project_id,
        query="铜铃",
        content_mode="canonical",
        visibility=VisibilityContextContract(mode="reader", cutoff_chapter=12),
        scopes=["outline"],
    )

    assert result["hits"][0]["target_ref"]["target_id"] == str(scene.id)
    assert result["degraded"] is True
    assert any("可见原文摘录" in warning for warning in result["warnings"])
