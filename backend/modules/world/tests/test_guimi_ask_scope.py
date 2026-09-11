"""Confirmed manuscript ranges remain the question-answering boundary."""

from types import SimpleNamespace

from modules.world.services.worldbuilding.ask_world_service import AskWorldService


def test_confirmation_does_not_admit_other_ranges_of_same_chapter():
    ref = dict(
        draft_id="d",
        version_number=1,
        source_hash="hash",
        content_mode="canonical",
        start_offset=10,
        end_offset=30,
    )

    def candidate(**changes):
        return dict(
            kind="manuscript", citation=SimpleNamespace(source_ref={**ref, **changes})
        )

    permitted = candidate()
    values = [
        permitted,
        candidate(start_offset=0),
        candidate(end_offset=31),
        candidate(version_number=2),
        candidate(draft_id="other"),
    ]
    assert AskWorldService._confirmed_candidates(
        values, {"writing_drafts": ["d"]}, source_refs=[ref]
    ) == [permitted]
    assert (
        AskWorldService._confirmed_candidates(
            values, {"writing_drafts": ["d"]}, source_refs=[]
        )
        == []
    )


def test_citation_instructions_do_not_dilute_fact_relevance():
    from modules.world.services.worldbuilding.ask_world_retrieval import (
        MIN_RELEVANCE,
        ask_world_relevance,
    )

    assert (
        ask_world_relevance(
            "前60章中，克莱恩搬到哪条街、几号？请给出章节依据。",
            "第三十章",
            "克莱恩和家人搬进水仙花街2号。",
        )
        >= MIN_RELEVANCE
    )
    assert (
        ask_world_relevance(
            "前60章中，克莱恩搬到哪条街、几号？请给出章节依据。",
            "其他章节",
            "守卫在海边巡逻。",
        )
        < MIN_RELEVANCE
    )


async def test_all_eight_confirmed_ranges_reach_answer_budget(monkeypatch):
    import pytest

    from modules.evidence.compilation.services.author_question_evidence import (
        compile_author_question_evidence,
    )
    from modules.evidence.compilation.services.compiled_context import (
        CompiledContext,
        ContextItem,
        ContextSection,
        Tier,
    )
    from modules.world.llm_schemas import GeneratedAskWorldOutput
    from modules.world.schemas import (
        AskWorldCitation,
        AskWorldQuestionRequest,
        AskWorldSaveRequest,
    )

    refs = [
        dict(
            draft_id=f"d{i}",
            version_number=1,
            source_hash="0" * 64,
            range_hash=f"{i:064x}",
            content_mode="canonical",
            chapter_index=i + 1,
            start_offset=0,
            end_offset=10,
        )
        for i in range(8)
    ]
    prepared = SimpleNamespace(
        confirmation=SimpleNamespace(
            selected_asset_ids={"writing_drafts": [ref["draft_id"] for ref in refs]}
        ),
        compile_options={"top_k": 8},
        compiled=CompiledContext(
            sections=[
                ContextSection(
                    key="evidence",
                    content="",
                    tier=Tier.P1,
                    items=[
                        ContextItem(
                            key=str(i), content="正文", source={"source_ref": ref}
                        )
                        for i, ref in enumerate(refs)
                    ],
                )
            ]
        ),
    )

    async def prepare(*args, **kwargs):
        return prepared

    async def retrieve(*args, **kwargs):
        return [
            dict(
                key=str(i),
                kind="manuscript",
                title=f"第{i + 1}章",
                content="已确认正文",
                source_hash="0" * 64,
                score=1,
                citation=AskWorldCitation(
                    citation_key=str(i),
                    kind="manuscript",
                    title=f"第{i + 1}章",
                    source_hash="0" * 64,
                    source_ref=ref,
                ),
            )
            for i, ref in enumerate(refs)
        ], {}

    def budget(sources, **kwargs):
        packet = compile_author_question_evidence(sources, **kwargs)
        assert len(packet["included"]) == 8
        trace = service._evidence_trace(packet["trace"], sources, {})
        assert len(trace.included_titles) == 8
        generated = GeneratedAskWorldOutput(
            answer="已回读资料",
            no_answer=False,
            uncertainty="",
            claims=[
                {"text": f"来源{i}支持的结论", "citation_keys": [str(i)]}
                for i in range(8)
            ],
        )
        response = service._response_from_generated(
            "住址在哪里",
            generated,
            sources,
            trace,
            model="test",
            provider="test",
            snapshot_id="test",
        )
        assert len(response.citations) == 8
        saved = AskWorldSaveRequest(
            novel_id="n",
            question=response.question,
            answer=response.answer,
            claims=response.claims,
            uncertainty=response.uncertainty,
            citations=response.citations,
            response_hash=response.response_hash,
        )
        assert len(saved.citations) == 8
        raise RuntimeError("verified before model call")

    service = AskWorldService()
    monkeypatch.setattr(service, "_retrieve_candidates", retrieve)
    monkeypatch.setattr("modules.evidence.facade.prepare_confirmed_ai_action", prepare)
    monkeypatch.setattr(
        "modules.evidence.facade.compile_author_question_evidence", budget
    )
    with pytest.raises(RuntimeError, match="verified before model call"):
        await service.ask(
            None,
            AskWorldQuestionRequest(
                novel_id="n", question="住址在哪里", context_confirmation_id="c"
            ),
        )
