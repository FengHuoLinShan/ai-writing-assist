"""Writing 测试共享的治理执行器合成 client mixin。

提供导演分片与独立审查的 `generate_structured` 合成应答，供注入
`open_project_snapshot_llm_client(injected_client=...)` 的假 client 混入。
"""

from __future__ import annotations


class GovernedStructuredMixin:
    """导演全票 required、审查全票 pass 的最小合成实现。"""

    async def generate_structured(self, request, schema, **kwargs):  # noqa: ANN001
        from modules.evidence.compilation.knowledge.llm_schemas import (
            AuditDimensionCheck,
            AuditVerdictOutput,
            DirectorShardDisposition,
            DirectorShardPlan,
        )

        if schema is DirectorShardPlan:
            keys = []
            for message in request.messages:
                for line in message.content.splitlines():
                    line = line.strip()
                    if line.startswith("- ") and "|" in line:
                        keys.append(line[2:].split("|")[0].strip())
            return DirectorShardPlan(
                dispositions=[
                    DirectorShardDisposition(
                        source_key=key,
                        disposition="required_for_generation",
                    )
                    for key in keys
                ]
            )
        if schema is AuditVerdictOutput:
            return AuditVerdictOutput(
                findings=[],
                dimensions=[AuditDimensionCheck(dimension="prior_prose", checked=True)],
                verdict="pass",
            )
        raise AssertionError(f"unexpected schema: {schema}")
