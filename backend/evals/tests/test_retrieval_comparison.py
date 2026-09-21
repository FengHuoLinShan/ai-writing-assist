import pytest

pytest.importorskip("rank_bm25")

from evals.retrieval_comparison import evaluate_case, load_cases, run, tokenize


def test_tokenizer_normalizes_and_preserves_frequency():
    assert tokenize("ＡＢ１２ 铜铃铜铃") == ["ab12", "铜铃", "铃铜", "铜铃"]


@pytest.mark.asyncio
async def test_all_ranking_arms_filter_before_scoring_and_keep_range_gold():
    report = await run()
    assert not report["evidence"]["quality_claim_allowed"]
    assert report["evidence"]["usage"]["actual_requests"] == 0
    assert len(report["generation_arms"]) == 5
    for case in report["cases"]:
        for arm in case["arms"].values():
            assert not arm["model_executed"]
            for ref in arm["retrieved"]:
                assert ref["chapter_index"] == 1
                assert ref["source_alias"].endswith("-current")
                assert ref["start_offset"] < ref["end_offset"]


@pytest.mark.asyncio
async def test_rechunking_does_not_change_gold_and_parent_completes_required_conditions():
    case = next(case for case in load_cases() if case.scenario == "negation")
    gold = case.reference.copy()
    result = await evaluate_case(case, chunk_target=8)
    assert case.reference == gold
    assert result["arms"]["current"]["parent_group_recall"] == 1
    assert result["arms"]["current"]["range_group_recall"] <= 1


@pytest.mark.asyncio
async def test_no_authorized_sources_do_not_reach_reranker():
    case = load_cases()[0].model_copy(deep=True)
    case.input["source_manifest"] = {}
    result = await evaluate_case(case)
    assert all(not arm["retrieved"] for arm in result["arms"].values())
