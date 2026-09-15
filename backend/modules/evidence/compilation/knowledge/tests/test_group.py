"""组级知识治理 helper 单测（ADR-0025 组级 receipt 摊薄）。"""

from __future__ import annotations

import pytest

from modules.evidence.compilation.knowledge.group import (
    GroupSource,
    build_group_scope,
    govern_group_output,
)
from modules.evidence.compilation.knowledge.llm_schemas import (
    AuditDimensionCheck,
    AuditVerdictOutput,
)

_SOURCES = [
    GroupSource(
        source_key="scene_text:1",
        source_type="prior_prose",
        source_id="1",
        content_hash="a" * 64,
        label="Scene 正文",
        dimensions=("prior_prose",),
    ),
    GroupSource(
        source_key="workflow_context",
        source_type="imported_assets",
        content_hash="b" * 64,
        label="导入工作流上下文",
        dimensions=("imported_assets",),
    ),
]


def test_build_group_scope_freezes_stable_receipt() -> None:
    first = build_group_scope(
        capability="imports.entity_extraction",
        novel_id="n1",
        group_key="scene:1",
        sources=_SOURCES,
    )
    second = build_group_scope(
        capability="imports.entity_extraction",
        novel_id="n1",
        group_key="scene:1",
        sources=_SOURCES,
    )
    other_group = build_group_scope(
        capability="imports.entity_extraction",
        novel_id="n1",
        group_key="scene:2",
        sources=_SOURCES,
    )
    assert (
        first[0].receipt.receipt_fingerprint() == second[0].receipt.receipt_fingerprint()
    )
    assert (
        first[0].receipt.receipt_fingerprint()
        != other_group[0].receipt.receipt_fingerprint()
    )
    assert set(first[0].generator_keys) == {item.source_key for item in _SOURCES}


class _GroupFakeClient:
    provider = "fake"
    model_name = "fake-model"

    def __init__(self, verdicts: list[str]) -> None:
        self.verdicts = list(verdicts)
        self.calls = 0

    async def generate_structured(self, _request, schema, **_kwargs):
        self.calls += 1
        assert schema is AuditVerdictOutput
        return AuditVerdictOutput(
            findings=[],
            dimensions=[
                AuditDimensionCheck(dimension="prior_prose", checked=True)
            ],
            verdict=self.verdicts.pop(0) if self.verdicts else "pass",
        )


@pytest.mark.asyncio
async def test_govern_group_output_pass_without_repair() -> None:
    client = _GroupFakeClient(["pass"])
    result = await govern_group_output(
        client,
        capability="imports.entity_extraction",
        novel_id="n1",
        group_key="scene:1",
        sources=_SOURCES,
        output='{"entities": []}',
        task_instruction="从 Scene 正文抽取实体",
    )
    assert result["status"] == "passed"
    assert result["review"]["status"] == "passed"
    assert client.calls == 1


@pytest.mark.asyncio
async def test_govern_group_output_blocked_without_repair_callback() -> None:
    client = _GroupFakeClient(["blocked"])
    result = await govern_group_output(
        client,
        capability="imports.entity_extraction",
        novel_id="n1",
        group_key="scene:1",
        sources=_SOURCES,
        output="无来源事实",
        task_instruction="从 Scene 正文抽取实体",
    )
    assert result["status"] == "blocked"
    assert result["text"] == ""
    assert client.calls == 1


@pytest.mark.asyncio
async def test_govern_group_output_repairs_once_then_rechecks() -> None:
    client = _GroupFakeClient(["blocked", "pass"])
    repairs: list[str] = []

    async def _repair(findings_block: str) -> str:
        repairs.append(findings_block)
        return '{"entities": [], "repaired": true}'

    result = await govern_group_output(
        client,
        capability="imports.entity_extraction",
        novel_id="n1",
        group_key="scene:1",
        sources=_SOURCES,
        output="无来源事实",
        task_instruction="从 Scene 正文抽取实体",
        repair=_repair,
    )
    assert result["status"] == "passed"
    assert result["text"] == '{"entities": [], "repaired": true}'
    assert result["review"]["repaired"] is True
    assert client.calls == 2
    assert len(repairs) == 1


@pytest.mark.asyncio
async def test_govern_group_output_unverifiable_never_repairs() -> None:
    client = _GroupFakeClient(["unverifiable"])
    repairs: list[str] = []

    async def _repair(findings_block: str) -> str:
        repairs.append(findings_block)
        return "{}"

    result = await govern_group_output(
        client,
        capability="imports.entity_extraction",
        novel_id="n1",
        group_key="scene:1",
        sources=_SOURCES,
        output="无法核验",
        task_instruction="从 Scene 正文抽取实体",
        repair=_repair,
    )
    assert result["status"] == "blocked"
    assert result["text"] == ""
    assert client.calls == 1
    assert repairs == []
