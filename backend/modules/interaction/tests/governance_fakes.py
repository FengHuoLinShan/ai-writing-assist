"""Interaction 测试共享的治理审查合成应答。

合成审查者对请求 prompt 声明的全部必查维度按已查应答（BR-0c 起服务端
对缺失/重复/未查维度降为 unverifiable）。
"""

from __future__ import annotations


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
                    AuditDimensionCheck(dimension=dimension, checked=True)
                    for dimension in _required_dimensions(request.messages)
                ],
                verdict="pass",
            )
        raise AssertionError(f"unexpected schema: {schema}")
