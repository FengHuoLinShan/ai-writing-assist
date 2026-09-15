"""Interaction 测试共享的治理审查合成应答。"""

from __future__ import annotations


class GovernedAuditMixin:
    """审查恒 pass 的最小合成实现（导演不参与 RP M8 切片）。"""

    async def generate_structured(self, request, schema, **kwargs):  # noqa: ANN001
        from modules.evidence.compilation.knowledge.llm_schemas import (
            AuditDimensionCheck,
            AuditVerdictOutput,
            DirectorShardPlan,
        )

        if schema is DirectorShardPlan:
            return DirectorShardPlan(dispositions=[])
        if schema is AuditVerdictOutput:
            return AuditVerdictOutput(
                findings=[],
                dimensions=[
                    AuditDimensionCheck(dimension="source_canon", checked=True)
                ],
                verdict="pass",
            )
        raise AssertionError(f"unexpected schema: {schema}")
