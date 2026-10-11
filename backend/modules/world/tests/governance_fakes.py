"""World 测试共享的治理审查合成 client mixin。

默认全票 pass；测试可通过 ``audit_verdicts`` 队列注入 blocked/unverifiable
等应答来驱动返修与阻断路径。合成审查者对请求 prompt 声明的全部必查维度
按已查应答（BR-0c 起服务端对缺失/重复/未查维度降为 unverifiable）。
"""

from __future__ import annotations

from modules.evidence.compilation.knowledge.llm_schemas import (
    AuditDimensionCheck,
    AuditVerdictOutput,
)


def _required_dimensions(messages) -> list[str]:
    """从审查 prompt 读取必查维度；合成审查者按全部维度已查应答。"""
    for message in messages:
        for line in message.content.splitlines():
            if line.startswith("必查维度："):
                return [
                    item.strip()
                    for item in line.split("：", 1)[1].split(",")
                    if item.strip()
                ]
    return []


class GovernedWorldAuditMixin:
    """知识审查（AuditVerdictOutput）的合成应答。"""

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
                    AuditDimensionCheck(dimension=dimension, checked=True)
                    for dimension in _required_dimensions(request.messages)
                ],
                verdict=self._next_audit_verdict(),
            )
        raise AssertionError(f"unexpected schema: {schema}")
