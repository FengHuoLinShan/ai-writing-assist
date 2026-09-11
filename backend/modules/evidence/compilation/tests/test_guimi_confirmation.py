"""Audit regressions: finite writing defaults and retained manuscript identity."""

from modules.evidence.compilation.schemas import (
    ContextCompileRequest,
    ContextConfirmRequest,
)
from modules.evidence.compilation.services.compiled_context import (
    CompiledContext,
    ContextItem,
    ContextSection,
    Tier,
)
from modules.evidence.compilation.services.review_projection import (
    selected_asset_ids_from_compiled,
)


def test_writing_budget_is_finite_and_shared_by_preview_and_confirmation():
    for schema in (ContextCompileRequest, ContextConfirmRequest):
        assert (
            schema(
                novel_id="n", scope="chapter", task="继续", action="writing.generate"
            ).budget_tokens
            == 12000
        )
        assert (
            schema(
                novel_id="n",
                scope="chapter",
                task="继续",
                action="writing.generate",
                budget_tokens=500,
            ).budget_tokens
            == 500
        )
    assert (
        ContextCompileRequest(novel_id="n", scope="chapter", task="其他").budget_tokens
        == 4000
    )


def test_retained_range_registers_draft_but_excluded_item_does_not():
    source = {"type": "rag", "id": "chunk", "source_ref": {"draft_id": "draft-1"}}
    ctx = CompiledContext(
        sections=[
            ContextSection(
                key="retrieval",
                tier=Tier.P2,
                content="正文",
                items=[ContextItem(key="chunk", content="正文", source=source)],
            )
        ],
        excluded_items=[
            ContextItem(
                key="excluded",
                content="秘密",
                source={"source_ref": {"draft_id": "excluded-draft"}},
            )
        ],
    )
    assert selected_asset_ids_from_compiled(ctx, novel_id="n")["writing_drafts"] == [
        "draft-1"
    ]


def test_world_question_keeps_manuscript_before_generic_profiles():
    from modules.evidence.compilation.contracts import (
        CompileOptions,
        StructureContextBundle,
    )
    from modules.evidence.compilation.services.context_compiler import ContextCompiler

    bundle = StructureContextBundle(
        novel_id="n",
        task="新家在哪",
        scope="full",
        characters=[{"name": "人物", "summary": "背景" * 2000}],
        world_entities=[{"id": "e", "name": "人物", "summary": "背景" * 2000}],
        rag_chunks=[
            {
                "id": "r",
                "text": "他们的新家在水仙花街2号",
                "source_ref": {"draft_id": "d"},
            }
        ],
    )
    sections = ContextCompiler()._build_sections(
        bundle,
        CompileOptions(
            novel_id="n", task=bundle.task, scope="full", consumer_action="world.ask"
        ),
    )
    compiled = CompiledContext(
        sections=sections,
        total_tokens=sum(section.token_count for section in sections),
        budget_tokens=700,
    ).enforce_budget()
    assert any(
        section.key == "retrieval_evidence_packs" and "水仙花街2号" in section.content
        for section in compiled.sections
    )
    assert not any(section.key == "pov_knowledge" for section in compiled.sections)


def test_residence_question_retrieves_event_and_keeps_original_request():
    from modules.evidence.compilation.contracts import CompileOptions
    from modules.evidence.compilation.services.retrieval_query_planner import (
        RetrievalQueryPlanner,
    )

    question = "前60章中，克莱恩搬到哪条街、几号？请给出章节依据。"
    options = CompileOptions(
        novel_id="n",
        task=question,
        scope="full",
        consumer_action="world.ask",
        retrieval_purpose="ask_world",
    )
    plan = RetrievalQueryPlanner().plan(options)
    assert plan.clauses[0].query_text == "搬家"
    assert any("克莱恩" in clause.query_text for clause in plan.clauses)
    assert all("请给出章节依据" not in clause.query_text for clause in plan.clauses)
    assert options.task == question


def test_question_preview_and_execution_share_retrieval_purpose():
    from modules.evidence.compilation.services.confirmation_service import (
        resolve_retrieval_purpose,
    )

    assert (
        resolve_retrieval_purpose(
            "world.ask", "generic_context", reveal_mode="author_safe"
        )
        == "ask_world"
    )
