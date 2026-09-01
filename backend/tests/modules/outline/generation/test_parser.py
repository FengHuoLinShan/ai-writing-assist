"""Deep-import-only PlotStructureParser tests."""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel

from infrastructure.llm.schemas import LLMCallRequest
from modules.story.outline_state.generation.context_builder import PlotStructureContext
from modules.story.outline_state.generation.models import (
    SimplePlotThread,
    SimpleStructureOutput,
    StructureEvidenceReviewOutput,
)
from modules.story.outline_state.generation.parser import PlotStructureParser


class _FakeLLMClient:
    def __init__(self, return_value: BaseModel | Exception | None = None) -> None:
        self.return_value = return_value
        self.calls: list[LLMCallRequest] = []

    async def generate_structured(
        self,
        request: LLMCallRequest,
        response_model: type[BaseModel],
        **_kwargs,
    ) -> BaseModel:
        self.calls.append(request)
        if isinstance(self.return_value, Exception):
            raise self.return_value
        if self.return_value is None:
            return response_model()
        return self.return_value


def _context(*, with_scene: bool) -> PlotStructureContext:
    return PlotStructureContext(
        markdown="# 已采用世界资料",
        entity_name_to_id={},
        character_name_to_id={},
        scenes=(
            [
                {
                    "scene_id": "S-1",
                    "title": "门前试探",
                    "start_chapter": 1,
                    "end_chapter": 2,
                }
            ]
            if with_scene
            else []
        ),
    )


@pytest.mark.asyncio
async def test_creative_whole_structure_path_is_retired() -> None:
    parser = PlotStructureParser(_context(with_scene=True), fast_structured=False)

    with pytest.raises(RuntimeError, match="P20 current-layer workflow"):
        await parser.parse(_FakeLLMClient(), "deepseek-v4", 1, 3)


@pytest.mark.asyncio
async def test_phase3_without_scene_evidence_returns_review_without_provider() -> None:
    parser = PlotStructureParser(_context(with_scene=False), fast_structured=True)
    client = _FakeLLMClient()

    result = await parser.parse(client, "deepseek-v4", 1, 3)

    assert result is not None
    assert result.threads == []
    assert result.diagnostics == {
        "parameter_version": "phase3_structure_simple_v2",
        "input_mode": "no_scene_evidence",
        "prompt_level": "none",
        "provider_called": False,
        "needs_review": True,
    }
    assert client.calls == []


@pytest.mark.asyncio
async def test_phase3_structures_only_scene_supported_evidence() -> None:
    parser = PlotStructureParser(_context(with_scene=True), fast_structured=True)
    client = _FakeLLMClient(
        SimpleStructureOutput(
            plot_threads=[
                SimplePlotThread(
                    title="潮门调查",
                    summary="主角循着门上的光追查失踪者。",
                    confidence=0.80,
                    supporting_scene_ids=["S-1"],
                )
            ]
        )
    )

    result = await parser.parse(client, "deepseek-v4", 1, 3)

    assert result is not None
    assert [item.name for item in result.threads] == ["潮门调查"]
    assert result.threads[0].supporting_scene_ids == ["S-1"]
    assert result.threads[0].needs_review is True
    assert "scene_source_not_exact:S-1" in result.threads[0].review_reason
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_phase3_provider_failure_returns_none_without_creative_fallback() -> None:
    parser = PlotStructureParser(_context(with_scene=True), fast_structured=True)
    client = _FakeLLMClient(RuntimeError("provider unavailable"))

    result = await parser.parse(client, "deepseek-v4", 1, 3)

    assert result is None
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_phase3_auto_adopts_only_independently_supported_exact_sources() -> None:
    class EvidenceClient(_FakeLLMClient):
        async def generate_structured(self, request, response_model, **_kwargs):
            self.calls.append(request)
            if response_model is SimpleStructureOutput:
                return SimpleStructureOutput.model_validate(
                    {
                        "plot_threads": [
                            {
                                "title": "门后追查",
                                "summary": "主角先发现门缝光，再决定追查。",
                                "confidence": 0.93,
                                "supporting_scene_ids": ["S-1", "S-2"],
                            }
                        ],
                        "reveals": [
                            {
                                "title": "不存在的身份",
                                "summary": "守门人就是失踪者。",
                                "confidence": 0.99,
                                "supporting_scene_ids": ["S-2"],
                            }
                        ],
                    }
                )
            payload = json.loads(request.messages[-1].content)
            reviews = []
            for item in payload["review_items"]:
                unsupported = item["category"] == "reveals"
                quote = (
                    "他决定继续追查。" if item["scene_id"] == "S-2" else "门缝透出蓝光。"
                )
                reviews.append(
                    {
                        "candidate_id": item["candidate_id"],
                        "verdict": "unsupported" if unsupported else "supported",
                        "confidence": 0.97,
                        "evidence": [{"quote": quote}],
                    }
                )
            return StructureEvidenceReviewOutput(reviews=reviews)

    def scene(scene_id: str, text: str) -> dict:
        return {
            "scene_id": scene_id,
            "title": scene_id,
            "start_chapter": 1,
            "end_chapter": 1,
            "_evidence": {
                "status": "exact",
                "source_hash": scene_id,
                "sources": [{"text": text}],
            },
        }

    parser = PlotStructureParser(
        PlotStructureContext(
            markdown="",
            scenes=[
                scene("S-1", "门缝透出蓝光。"),
                scene("S-2", "他决定继续追查。"),
            ],
        ),
        fast_structured=True,
    )
    client = EvidenceClient()

    result = await parser.parse(client, "deepseek-v4", 1, 1)

    assert result is not None
    assert result.threads[0].needs_review is False
    assert result.threads[0].evidence_gate["status"] == "passed"
    assert result.reveal_plans[0].needs_review is True
    assert result.reveal_plans[0].evidence_gate["status"] == "needs_review"
    assert result.diagnostics["evidence_gate_passed_count"] == 1
    assert result.diagnostics["evidence_review_unsupported_count"] == 1
    assert len(client.calls) == 2


@pytest.mark.asyncio
async def test_phase3_scene_part_conflict_blocks_supported_part() -> None:
    class EvidenceClient(_FakeLLMClient):
        async def generate_structured(self, request, response_model, **_kwargs):
            self.calls.append(request)
            if response_model is SimpleStructureOutput:
                return SimpleStructureOutput.model_validate(
                    {
                        "reveals": [
                            {
                                "title": "门后结论",
                                "summary": "门后只有一个人。",
                                "confidence": 0.96,
                                "supporting_scene_ids": ["S-1"],
                            }
                        ]
                    }
                )
            payload = json.loads(request.messages[-1].content)
            return StructureEvidenceReviewOutput.model_validate(
                {
                    "reviews": [
                        {
                            "candidate_id": item["candidate_id"],
                            "verdict": (
                                "conflict"
                                if item["candidate_id"].endswith(":2")
                                else "supported"
                            ),
                            "confidence": 0.97,
                            "evidence": [
                                {
                                    "quote": (
                                        "冲突证据。"
                                        if item["candidate_id"].endswith(":2")
                                        else "支持证据。"
                                    ),
                                }
                            ],
                        }
                        for item in payload["review_items"]
                    ]
                }
            )

    text = "支持证据。" + ("甲" * 48_000) + "冲突证据。"
    parser = PlotStructureParser(
        PlotStructureContext(
            markdown="",
            scenes=[
                {
                    "scene_id": "S-1",
                    "title": "S-1",
                    "start_chapter": 1,
                    "end_chapter": 1,
                    "_evidence": {
                        "status": "exact",
                        "source_hash": "hash-1",
                        "sources": [{"text": text}],
                    },
                }
            ],
        ),
        fast_structured=True,
    )

    result = await parser.parse(EvidenceClient(), "deepseek-v4", 1, 1)

    assert result is not None
    reveal = result.reveal_plans[0]
    assert reveal.needs_review is True
    assert reveal.evidence_gate["scene_verdicts"] == {"S-1": "conflict"}
    assert "evidence_review_conflict:S-1" in reveal.review_reason


@pytest.mark.asyncio
async def test_phase3_first_pass_review_request_skips_paid_evidence_call() -> None:
    context = PlotStructureContext(
        markdown="",
        scenes=[
            {
                "scene_id": "S-1",
                "title": "S-1",
                "start_chapter": 1,
                "end_chapter": 1,
                "_evidence": {
                    "status": "exact",
                    "sources": [{"text": "门缝透出蓝光。"}],
                },
            }
        ],
    )
    client = _FakeLLMClient(
        SimpleStructureOutput(
            plot_threads=[
                SimplePlotThread(
                    title="门后追查",
                    summary="需要作者判断的追查线。",
                    confidence=0.95,
                    supporting_scene_ids=["S-1"],
                    needs_review=True,
                )
            ]
        )
    )

    result = await PlotStructureParser(context, fast_structured=True).parse(
        client, "deepseek-v4", 1, 1
    )

    assert result is not None
    assert "first_pass_requested_review" in result.threads[0].review_reason
    assert len(client.calls) == 1
