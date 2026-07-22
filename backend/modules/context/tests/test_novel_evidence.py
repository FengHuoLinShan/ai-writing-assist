from __future__ import annotations

import uuid
from types import SimpleNamespace

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
from modules.context.novel_evidence import (
    NovelEvidenceService,
    _query_focused_snippet,
)
from modules.context.schemas import EvidenceSearchResponse
from modules.rag.contracts import RagChunkContract
from modules.writing.contracts import SourceRangeRefContract
from modules.writing.facade import create_published_draft_only, grep_manuscript


def test_query_focused_snippet_shows_evidence_instead_of_chunk_prefix() -> None:
    text = (
        "观众魔药配方与材料说明。" * 45
        + "克莱恩由灵视实践想到：不是掌握，是消化；不是挖掘，是扮演。"
        + "他仍需继续理解占卜家的力量边界。"
    )

    snippet = _query_focused_snippet(
        text,
        "克莱恩服食占卜家魔药后，如何通过灵视、占卜实践和扮演逐步理解自己的力量边界？",
    )

    assert len(snippet) <= 500
    assert snippet.startswith("…")
    assert "不是挖掘，是扮演" in snippet
    assert "力量边界" in snippet
    assert not snippet.startswith("观众魔药配方")


def test_query_focused_snippet_keeps_short_text_and_falls_back_to_prefix() -> None:
    assert _query_focused_snippet("短证据", "无关查询") == "短证据"
    assert _query_focused_snippet("甲" * 600, "无关查询") == "甲" * 500


@pytest.mark.asyncio
async def test_author_search_returns_parent_scene_context_and_writing_relation(
    db_session,
    test_project_id,
) -> None:
    from modules.outline.facade import bind_scene_spans_to_source
    from modules.outline.repositories import SceneRepository
    from modules.outline.schemas import SceneCreate

    content = "林晚在旧塔找到铜铃，确认密道曾被人打开。"
    draft = await create_published_draft_only(
        db_session,
        test_project_id,
        11,
        "第十一章",
        content,
    )
    repo = SceneRepository()
    parent = await repo.create(
        db_session,
        uuid.UUID(test_project_id),
        SceneCreate(
            scene_index=11,
            title="旧塔铜铃",
            goal="确认密道入口",
            core_conflict="铜铃声会惊动守卫",
            emotional_beat="从怀疑转为紧迫",
            chapter_ids=["11"],
            scene_chunks=[
                {"chapter_index": 11, "start_offset": 0, "end_offset": len(content)}
            ],
            status="canonical",
        ),
    )
    current = await repo.create(
        db_session,
        uuid.UUID(test_project_id),
        SceneCreate(
            scene_index=12,
            title="追踪守卫",
            chapter_ids=["12"],
            status="canonical",
        ),
    )
    await bind_scene_spans_to_source(
        db_session,
        novel_id=test_project_id,
        chapter_index=11,
        content_mode="canonical",
        source_draft_id=draft.id or "",
        source_content_hash=draft.content_hash,
        content=content,
    )

    result = await grep_novel_evidence(
        db_session,
        novel_id=test_project_id,
        pattern="铜铃",
        content_mode="canonical",
        visibility=VisibilityContextContract(mode="author"),
        context_scene_id=str(current.id),
    )
    wire = EvidenceSearchResponse(**result).model_dump()

    ref = wire["hits"][0]["scene_refs"][0]
    assert ref["target_id"] == str(parent.id)
    assert ref["scene_index"] == 11
    assert ref["scene_title"] == "旧塔铜铃"
    assert ref["context_summary"] == (
        "目标：确认密道入口；冲突：铜铃声会惊动守卫；情绪：从怀疑转为紧迫"
    )
    assert wire["hits"][0]["parent_scene_contexts"] == [ref]
    assert wire["hits"][0]["writing_relevance"]["kind"] == "previous_scene"
    assert "剧情承接" in wire["hits"][0]["writing_relevance"]["label"]

    reader_result = await grep_novel_evidence(
        db_session,
        novel_id=test_project_id,
        pattern="铜铃",
        content_mode="canonical",
        visibility=VisibilityContextContract(mode="reader", cutoff_chapter=11),
        context_scene_id=str(current.id),
    )
    reader_ref = reader_result["hits"][0]["scene_refs"][0]
    assert "scene_title" not in reader_ref
    assert "context_summary" not in reader_ref
    assert reader_result["hits"][0]["writing_relevance"] == {}


@pytest.mark.asyncio
async def test_smart_search_keeps_primary_range_aligned_and_aggregates_parent_scenes(
    db_session,
    test_project_id,
    monkeypatch,
) -> None:
    import modules.outline.facade as outline_facade
    from modules.outline.facade import bind_scene_spans_to_source
    from modules.outline.repositories import SceneRepository
    from modules.outline.schemas import SceneCreate

    first_text = "旧塔入口留下脚印。"
    second_text = "铜铃在密道深处响起。"
    content = first_text + second_text
    draft = await create_published_draft_only(
        db_session,
        test_project_id,
        23,
        "第二十三章",
        content,
    )
    repo = SceneRepository()
    first_scene = await repo.create(
        db_session,
        uuid.UUID(test_project_id),
        SceneCreate(
            scene_index=23,
            title="旧塔入口",
            goal="追踪脚印",
            chapter_ids=["23"],
            scene_chunks=[
                {"chapter_index": 23, "start_offset": 0, "end_offset": len(first_text)}
            ],
            status="canonical",
        ),
    )
    second_scene = await repo.create(
        db_session,
        uuid.UUID(test_project_id),
        SceneCreate(
            scene_index=24,
            title="密道铜铃",
            goal="确认追兵位置",
            chapter_ids=["23"],
            scene_chunks=[
                {
                    "chapter_index": 23,
                    "start_offset": len(first_text),
                    "end_offset": len(content),
                }
            ],
            status="canonical",
        ),
    )
    await bind_scene_spans_to_source(
        db_session,
        novel_id=test_project_id,
        chapter_index=23,
        content_mode="canonical",
        source_draft_id=draft.id or "",
        source_content_hash=draft.content_hash,
        content=content,
    )

    chunks = [
        RagChunkContract(
            id=str(uuid.uuid4()),
            novel_id=test_project_id,
            source_type="chapter_text",
            source_id=draft.id,
            source_content_hash=draft.content_hash,
            content_mode="canonical",
            chapter_index=23,
            start_offset=start,
            end_offset=end,
            text=content[start:end],
            score=score,
        )
        for start, end, score in (
            (0, len(first_text), 0.9),
            (len(first_text), len(content), 0.8),
        )
    ]

    async def fake_retrieve(*_args, **_kwargs):
        return SimpleNamespace(chunks=chunks, warnings=[], degraded=False)

    async def fresh_index(*_args, **_kwargs):
        return {"stale": False}

    original_spans = outline_facade.get_scene_spans_by_chapter
    original_scene = outline_facade.get_scene_contract
    calls = {"spans": 0, "scenes": []}

    async def counted_spans(*args, **kwargs):
        calls["spans"] += 1
        return await original_spans(*args, **kwargs)

    async def counted_scene(*args, **kwargs):
        calls["scenes"].append(args[2])
        return await original_scene(*args, **kwargs)

    monkeypatch.setattr("modules.rag.facade.retrieve", fake_retrieve)
    monkeypatch.setattr("modules.rag.facade.get_index_freshness", fresh_index)
    monkeypatch.setattr(outline_facade, "get_scene_spans_by_chapter", counted_spans)
    monkeypatch.setattr(outline_facade, "get_scene_contract", counted_scene)

    result = await search_novel_evidence(
        db_session,
        novel_id=test_project_id,
        query="铜铃",
        content_mode="canonical",
        visibility=VisibilityContextContract(mode="author"),
        scopes=["manuscript"],
        context_scene_id=str(second_scene.id),
        top_k=20,
    )

    hit = result["hits"][0]
    assert hit["source_ref"]["start_offset"] == len(first_text)
    assert [ref["target_id"] for ref in hit["scene_refs"]] == [str(second_scene.id)]
    assert [ref["target_id"] for ref in hit["parent_scene_contexts"]] == [
        str(first_scene.id),
        str(second_scene.id),
    ]
    assert hit["writing_relevance"]["kind"] == "current_scene"
    assert calls["spans"] == 1
    assert calls["scenes"].count(str(first_scene.id)) == 1
    assert calls["scenes"].count(str(second_scene.id)) == 2


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
async def test_rag_candidate_rehydration_uses_current_source_and_visibility(
    db_session,
    test_project_id,
    monkeypatch,
) -> None:
    visible_text = "当前章节的铜铃线索。"
    hidden_text = "未来章节的黑日密钥。"
    visible = await create_published_draft_only(
        db_session,
        test_project_id,
        30,
        "第三十章",
        visible_text,
    )
    hidden = await create_published_draft_only(
        db_session,
        test_project_id,
        31,
        "第三十一章",
        hidden_text,
    )
    good_id = str(uuid.uuid4())
    stale_id = str(uuid.uuid4())
    hidden_id = str(uuid.uuid4())
    foreign_id = str(uuid.uuid4())
    wrong_mode_id = str(uuid.uuid4())
    chunks = [
        RagChunkContract(
            id=good_id,
            novel_id=test_project_id,
            source_type="chapter_text",
            source_id=visible.id,
            source_content_hash=visible.content_hash,
            content_mode="canonical",
            chapter_index=30,
            start_offset=0,
            end_offset=len(visible_text),
            text="过期缓存",
        ),
        RagChunkContract(
            id=stale_id,
            novel_id=test_project_id,
            source_type="chapter_text",
            source_id=visible.id,
            source_content_hash="f" * 64,
            content_mode="canonical",
            chapter_index=30,
            start_offset=0,
            end_offset=len(visible_text),
            text="过期缓存",
        ),
        RagChunkContract(
            id=hidden_id,
            novel_id=test_project_id,
            source_type="chapter_text",
            source_id=hidden.id,
            source_content_hash=hidden.content_hash,
            content_mode="canonical",
            chapter_index=31,
            start_offset=0,
            end_offset=len(hidden_text),
            text="越界缓存",
        ),
        RagChunkContract(
            id=foreign_id,
            novel_id=str(uuid.uuid4()),
            source_type="chapter_text",
            source_id=visible.id,
            source_content_hash=visible.content_hash,
            content_mode="canonical",
            chapter_index=30,
            start_offset=0,
            end_offset=len(visible_text),
            text="跨项目伪造候选",
        ),
        RagChunkContract(
            id=wrong_mode_id,
            novel_id=test_project_id,
            source_type="chapter_text",
            source_id=visible.id,
            source_content_hash=visible.content_hash,
            content_mode="working",
            chapter_index=30,
            start_offset=0,
            end_offset=len(visible_text),
            text="错误正文模式候选",
        ),
    ]

    batch = await NovelEvidenceService().rehydrate_manuscript_candidates(
        db_session,
        novel_id=test_project_id,
        content_mode="canonical",
        visibility=VisibilityContextContract(mode="reader", cutoff_chapter=30),
        chunks=chunks,
    )

    assert batch.reads_by_chunk_id[good_id]["text"] == visible_text
    assert batch.drop_reason_by_chunk_id == {
        stale_id: "source_hash_mismatch",
        hidden_id: "visibility_denied",
        foreign_id: "novel_id_mismatch",
        wrong_mode_id: "content_mode_mismatch",
    }

    service = NovelEvidenceService()

    async def fail_original_read(*_args, **_kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(service, "_read_visible_source_ref", fail_original_read)
    with pytest.raises(RuntimeError, match="database unavailable"):
        await service.rehydrate_manuscript_candidates(
            db_session,
            novel_id=test_project_id,
            content_mode="canonical",
            visibility=VisibilityContextContract(mode="author"),
            chunks=[chunks[0]],
        )


@pytest.mark.asyncio
async def test_scene_cursor_rebinds_to_candidate_batch_source_version(
    db_session,
    test_project_id,
) -> None:
    from modules.outline.facade import bind_scene_spans_to_source
    from modules.outline.repositories import SceneRepository
    from modules.outline.schemas import SceneCreate
    from modules.writing.facade import create_draft_only

    old_text = "截止 Scene 只包含铜铃。"
    old_draft = await create_draft_only(
        db_session,
        test_project_id,
        40,
        content=old_text,
    )
    scene = await SceneRepository().create(
        db_session,
        uuid.UUID(test_project_id),
        SceneCreate(
            scene_index=40,
            title="铜铃截止点",
            chapter_ids=["40"],
            scene_chunks=[
                {
                    "chapter_index": 40,
                    "start_offset": 0,
                    "end_offset": len(old_text),
                }
            ],
            status="canonical",
        ),
    )
    await bind_scene_spans_to_source(
        db_session,
        novel_id=test_project_id,
        chapter_index=40,
        content_mode="working",
        source_draft_id=old_draft.id or "",
        source_content_hash=old_draft.content_hash,
        content=old_text,
    )
    new_text = "铜铃之后新增了尚未重锚的黑日密钥。"
    new_draft = await create_draft_only(
        db_session,
        test_project_id,
        40,
        content=new_text,
    )
    chunk_id = str(uuid.uuid4())

    batch = await NovelEvidenceService().rehydrate_manuscript_candidates(
        db_session,
        novel_id=test_project_id,
        content_mode="working",
        visibility=VisibilityContextContract(
            mode="reader",
            cutoff_chapter=40,
            cutoff_scene_id=str(scene.id),
        ),
        chunks=[
            RagChunkContract(
                id=chunk_id,
                novel_id=test_project_id,
                source_type="chapter_text",
                source_id=new_draft.id,
                source_content_hash=new_draft.content_hash,
                content_mode="working",
                chapter_index=40,
                start_offset=0,
                end_offset=len(new_text),
                text="不应直接信任的索引文本",
            )
        ],
    )

    assert batch.reads_by_chunk_id == {}
    assert batch.drop_reason_by_chunk_id == {chunk_id: "visibility_denied"}
    assert batch.visibility.cutoff_offset == 0
    assert any("保守排除" in warning for warning in batch.warnings)


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
async def test_author_can_inspect_pending_world_entity_with_warning(
    db_session,
    test_project_id,
) -> None:
    from modules.world.facade import create_entity

    entity = await create_entity(
        db_session,
        test_project_id,
        {
            "name": "待处理暗号",
            "entity_type": "secret",
            "summary": "作者待裁决的世界对象",
            "status": "candidate",
        },
    )

    result = await inspect_novel_target(
        db_session,
        novel_id=test_project_id,
        target_ref={
            "target_type": "world_entity",
            "target_id": str(entity["id"]),
            "target_path": "summary",
        },
        content_mode="working",
        visibility=VisibilityContextContract(mode="author"),
    )

    assert result["visible"] is True
    assert result["item"]["entity_id"] == str(entity["id"])
    assert "包含未采用对象" in result["warnings"]


@pytest.mark.asyncio
async def test_world_evidence_search_excludes_pending_by_default_and_requires_opt_in(
    db_session,
    test_project_id,
) -> None:
    from modules.world.facade import create_entity

    entity = await create_entity(
        db_session,
        test_project_id,
        {
            "name": "未采用的星门密语",
            "entity_type": "secret",
            "summary": "只应在显式开关开启后命中",
            "status": "candidate",
        },
    )

    default_result = await search_novel_evidence(
        db_session,
        novel_id=test_project_id,
        query="星门密语",
        content_mode="working",
        visibility=VisibilityContextContract(mode="author"),
        scopes=["world"],
    )
    opted_in = await search_novel_evidence(
        db_session,
        novel_id=test_project_id,
        query="星门密语",
        content_mode="working",
        visibility=VisibilityContextContract(mode="author"),
        scopes=["world"],
        include_pending_objects=True,
    )

    assert default_result["hits"] == []
    assert opted_in["hits"][0]["target_ref"]["target_id"] == str(entity["id"])
    assert "包含未采用对象" in opted_in["warnings"]


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
async def test_smart_search_aggregates_exact_matches_by_chapter(
    db_session,
    test_project_id,
) -> None:
    await create_published_draft_only(
        db_session,
        test_project_id,
        21,
        "第二十一章",
        "克莱恩观察门窗，随后克莱恩记下线索。",
    )
    await create_published_draft_only(
        db_session,
        test_project_id,
        22,
        "第二十二章",
        "克莱恩抵达车站。",
    )

    result = await search_novel_evidence(
        db_session,
        novel_id=test_project_id,
        query="克莱恩",
        content_mode="canonical",
        visibility=VisibilityContextContract(mode="author"),
        scopes=["manuscript"],
        top_k=100,
    )

    assert [item["chapter_index"] for item in result["hits"]] == [21, 22]
    assert [item["match_count"] for item in result["hits"]] == [2, 1]
    assert all(item["match_basis"] == "occurrence" for item in result["hits"])


@pytest.mark.asyncio
async def test_smart_search_preserves_reranker_order_across_chapter_grouping(
    db_session,
    test_project_id,
    monkeypatch,
) -> None:
    drafts = []
    for chapter, text in (
        (57, "直接证据：克莱恩总结扮演和消化。"),
        (21, "辅助背景：罗塞尔日记提到扮演。"),
        (33, "直接证据：克莱恩练习灵视。"),
    ):
        drafts.append(
            await create_published_draft_only(
                db_session,
                test_project_id,
                chapter,
                f"第{chapter}章",
                text,
            )
        )

    chunks = [
        RagChunkContract(
            id=str(uuid.uuid4()),
            novel_id=test_project_id,
            source_type="chapter_text",
            source_id=draft.id,
            source_content_hash=draft.content_hash,
            content_mode="canonical",
            chapter_index=draft.chapter_index,
            start_offset=0,
            end_offset=len(draft.content or ""),
            text=draft.content or "",
            score=score,
        )
        for draft, score in zip(drafts, (0.8, 0.95, 0.7), strict=True)
    ]

    async def fake_retrieve(*_args, **_kwargs):
        return SimpleNamespace(chunks=chunks, warnings=[], degraded=False)

    async def fresh_index(*_args, **_kwargs):
        return {"stale": False}

    monkeypatch.setattr("modules.rag.facade.retrieve", fake_retrieve)
    monkeypatch.setattr("modules.rag.facade.get_index_freshness", fresh_index)

    result = await search_novel_evidence(
        db_session,
        novel_id=test_project_id,
        query="如何理解能力边界",
        content_mode="canonical",
        visibility=VisibilityContextContract(mode="author"),
        scopes=["manuscript"],
        top_k=20,
    )

    assert [item["chapter_index"] for item in result["hits"]] == [57, 21, 33]
    assert [item["score"] for item in result["hits"]] == [0.8, 0.95, 0.7]


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
