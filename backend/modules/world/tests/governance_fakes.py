"""World 测试共享的治理审查合成 client mixin。

默认全票 pass；测试可通过 ``audit_verdicts`` 队列注入 blocked/unverifiable
等应答来驱动返修与阻断路径。
"""

from __future__ import annotations

from modules.evidence.compilation.knowledge.llm_schemas import (
    AuditDimensionCheck,
    AuditVerdictOutput,
)


class GovernedWorldAuditMixin:
    """知识审查（AuditVerdictOutput）的合成应答。"""

    def _audit_dimension(self) -> str:
        return "world_bible"

    def _next_audit_verdict(self) -> str:
        verdicts = getattr(self, "audit_verdicts", None)
        if verdicts:
            return verdicts.pop(0)
        return "pass"

    def _audit_findings(self) -> list:
        return []

    async def _governed_generate_structured(self, request, schema, **kwargs):  # noqa: ANN001
        if schema is AuditVerdictOutput:
            return AuditVerdictOutput(
                findings=self._audit_findings(),
                dimensions=[
                    AuditDimensionCheck(
                        dimension=self._audit_dimension(), checked=True
                    )
                ],
                verdict=self._next_audit_verdict(),
            )
        raise AssertionError(f"unexpected schema: {schema}")
