"""治理执行器测试：导演归并、审查收口、一次返修、阻断与投影脱敏（合成 provider）。"""

from __future__ import annotations

from typing import Any

import pytest

from modules.evidence.compilation.knowledge.contracts import (
    KnowledgeContractError,
    KnowledgeDirectorDisposition,
    KnowledgeDirectorPlan,
    KnowledgeSubject,
)
from modules.evidence.compilation.knowledge.llm_schemas import (
    AuditDimensionCheck,
    AuditFindingOutput,
    AuditVerdictOutput,
    DirectorShardDisposition,
    DirectorShardPlan,
)
from modules.evidence.compilation.knowledge.policies import (
    require_capability_policy,
)
from modules.evidence.compilation.knowledge.projection import (
    knowledge_review_payload,
    redact_hidden_phrases,
)
from modules.evidence.compilation.knowledge.scope import (
    build_scope_receipt,
    require_scope_complete,
)
from modules.evidence.compilation.knowledge.workflow import (
    GovernedWorkflowHooks,
    apply_director_plan,
    run_governed_generation,
)
from modules.evidence.compilation.services.compiled_context import (
    CompiledContext,
    ContextItem,
    ContextSection,
    Tier,
)


def _section(key: str, sources: list[dict]) -> ContextSection:
    return ContextSection(
        key=key,
        tier=Tier.P1,
        content="\n".join(str(s.get("label") or s.get("id")) for s in sources),
        sources=list(sources),
        items=[
            ContextItem(key=f"{key}:{i}", content=str(s.get("label")), source=dict(s))
            for i, s in enumerate(sources)
        ],
    )


def _scope_build():
    policy = require_capability_policy("world.generation.suggestion")
    compiled = CompiledContext(
        sections=[
            _section(
                "world_entities",
                [
                    {"type": "world_entity", "id": "a", "label": "主角组织"},
                    {"type": "world_entity", "id": "b", "label": "隐藏反派"},
                ],
            ),
            _section(
                "world_bible_working_pages",
                [{"type": "world_bible_page", "id": "p1", "label": "世界书页"}],
            ),
        ]
    )
    build = build_scope_receipt(
        compiled, policy, KnowledgeSubject(subject_type="author"), novel_id="novel-1"
    )
    require_scope_complete(build)
    return policy, build


class FakeGovernedClient:
    """按 schema 类型分发的合成 provider：导演处置与审查裁决均可脚本化。"""

    def __init__(
        self,
        *,
        director_dispositions: dict[str, str] | None = None,
        director_extra_keys: list[str] | None = None,
        director_missing_keys: list[str] | None = None,
        audit_outputs: list[AuditVerdictOutput] | None = None,
    ) -> None:
        self.director_dispositions = director_dispositions or {}
        self.director_extra_keys = director_extra_keys or []
        self.director_missing_keys = director_missing_keys or []
        self.audit_outputs = list(audit_outputs or [])
        self.audit_calls: list[str] = []
        self.requests: list[Any] = []

    async def generate_structured(self, request, schema, **kwargs):  # noqa: ANN001
        self.requests.append(request)
        if schema is DirectorShardPlan:
            keys = []
            for message in request.messages:
                for line in message.content.splitlines():
                    line = line.strip()
                    if line.startswith("- ") and "|" in line:
                        keys.append(line[2:].split("|")[0].strip())
            dispositions = [
                DirectorShardDisposition(
                    source_key=key,
                    disposition=self.director_dispositions.get(
                        key, "allowed_for_generation"
                    ),
                    reason="测试处置",
                )
                for key in keys
                if key not in self.director_missing_keys
            ]
            dispositions.extend(
                DirectorShardDisposition(
                    source_key=key, disposition="forbidden", reason="幽灵 key"
                )
                for key in self.director_extra_keys
            )
            return DirectorShardPlan(dispositions=dispositions)
        if schema is AuditVerdictOutput:
            self.audit_calls.append(request.messages[-1].content)
            return self.audit_outputs.pop(0)
        raise AssertionError(f"unexpected schema {schema}")


def _audit(
    findings: list[AuditFindingOutput],
    verdict: str = "blocked",
    dimensions: list[str] | None = None,
) -> AuditVerdictOutput:
    dims = dimensions or ["world_entities", "world_bible"]
    return AuditVerdictOutput(
        findings=findings,
        dimensions=[
            AuditDimensionCheck(dimension=d, checked=True) for d in dims
        ],
        verdict=verdict,
    )


def _hooks(generate_output: str, repair_output: str | None = None,
    stages: list[str] | None = None):
    async def generate(plan, generator_keys):  # noqa: ANN001
        return generate_output

    async def repair(original, findings):  # noqa: ANN001
        return repair_output if repair_output is not None else original

    return GovernedWorkflowHooks(
        generate=generate,
        repair=repair if repair_output is not None else None,
        task_instruction="写一段设定建议",
        generator_context="生成者可见：主角组织资料",
        authority_context="权威资料：主角组织；隐藏反派真实身份是某某",
        hidden_phrases=("隐藏反派真实身份是某某",),
        on_stage=stages.append if stages is not None else None,
    )


@pytest.mark.asyncio
async def test_pass_without_repair() -> None:
    policy, build = _scope_build()
    client = FakeGovernedClient(
        director_dispositions={
            "world_entity:a": "required_for_generation",
            "world_entity:b": "director_audit_only",
            "world_bible_page:p1": "allowed_for_generation",
        },
        audit_outputs=[_audit([], verdict="pass")],
    )
    stages: list[str] = []
    outcome = await run_governed_generation(
        client,
        policy=policy,
        scope_build=build,
        hooks=_hooks("生成正文", stages=stages),
    )
    assert outcome.passed
    assert outcome.output == "生成正文"
    assert outcome.repaired is False
    assert "world_entity:b" not in outcome.generator_keys
    assert "world_entity:a" in outcome.generator_keys
    assert stages == ["directing", "generating", "reviewing"]
    payload = outcome.to_result_payload()
    assert payload["status"] == "passed"
    assert "output_hash" not in payload  # include_output 默认 False


@pytest.mark.asyncio
async def test_blocker_blocks_and_one_repair_passes() -> None:
    policy, build = _scope_build()
    audit_blocked = _audit(
        [
            AuditFindingOutput(
                kind="premature_reveal",
                severity="blocker",
                message="输出复述了隐藏反派真实身份是某某",
                excerpt="他就是隐藏反派",
            )
        ]
    )
    audit_pass = _audit([], verdict="pass")
    client = FakeGovernedClient(audit_outputs=[audit_blocked, audit_pass])
    stages: list[str] = []
    outcome = await run_governed_generation(
        client,
        policy=policy,
        scope_build=build,
        hooks=_hooks("泄漏正文", repair_output="修复正文", stages=stages),
    )
    assert outcome.passed
    assert outcome.repaired is True
    assert outcome.output == "修复正文"
    assert outcome.repair_audit is not None
    assert stages == ["directing", "generating", "reviewing", "repairing", "reviewing"]


@pytest.mark.asyncio
async def test_repair_fails_again_blocks_output() -> None:
    policy, build = _scope_build()
    audit_blocked = _audit(
        [
            AuditFindingOutput(
                kind="unsupported_fact",
                severity="major",
                message="出现了资料中没有的地名",
            )
        ]
    )
    client = FakeGovernedClient(audit_outputs=[audit_blocked, audit_blocked])
    outcome = await run_governed_generation(
        client,
        policy=policy,
        scope_build=build,
        hooks=_hooks("错误正文", repair_output="仍错正文"),
    )
    assert not outcome.passed
    assert outcome.status == "blocked"
    assert outcome.output == "", "阻断时不得携带正文"
    assert outcome.repaired is True


@pytest.mark.asyncio
async def test_no_repair_hook_blocks_directly() -> None:
    policy, build = _scope_build()
    audit_blocked = _audit(
        [AuditFindingOutput(kind="conflict", severity="major", message="与正史矛盾")]
    )
    client = FakeGovernedClient(audit_outputs=[audit_blocked])
    outcome = await run_governed_generation(
        client,
        policy=policy,
        scope_build=build,
        hooks=_hooks("矛盾正文"),
    )
    assert outcome.status == "blocked"
    assert outcome.repaired is False


@pytest.mark.asyncio
async def test_unverifiable_verdict_blocks_without_repair() -> None:
    policy, build = _scope_build()
    audit_unverifiable = _audit([], verdict="unverifiable")
    client = FakeGovernedClient(audit_outputs=[audit_unverifiable])
    outcome = await run_governed_generation(
        client,
        policy=policy,
        scope_build=build,
        hooks=_hooks("无法核验正文", repair_output="返修也没用"),
    )
    assert outcome.status == "blocked"
    assert outcome.repaired is False, "unverifiable 不得触发返修"
    assert len(client.audit_calls) == 1


@pytest.mark.asyncio
async def test_server_overrides_lenient_llm_verdict() -> None:
    policy, build = _scope_build()
    audit_lie = _audit(
        [
            AuditFindingOutput(
                kind="premature_reveal",
                severity="blocker",
                message="剧透",
            )
        ],
        verdict="pass",  # LLM 谎报 pass；服务端必须收口为 blocked
    )
    client = FakeGovernedClient(audit_outputs=[audit_lie, audit_lie])
    outcome = await run_governed_generation(
        client,
        policy=policy,
        scope_build=build,
        hooks=_hooks("剧透正文", repair_output="还是剧透"),
    )
    assert outcome.status == "blocked"


@pytest.mark.asyncio
async def test_director_unknown_key_fails_closed() -> None:
    policy, build = _scope_build()
    client = FakeGovernedClient(director_extra_keys=["world_entity:ghost"])
    with pytest.raises(KnowledgeContractError, match="unknown"):
        await run_governed_generation(
            client,
            policy=policy,
            scope_build=build,
            hooks=_hooks("正文"),
        )


@pytest.mark.asyncio
async def test_director_missing_key_fails_closed() -> None:
    policy, build = _scope_build()
    client = FakeGovernedClient(director_missing_keys=["world_entity:a"])
    with pytest.raises(KnowledgeContractError, match="missing"):
        await run_governed_generation(
            client,
            policy=policy,
            scope_build=build,
            hooks=_hooks("正文"),
        )


@pytest.mark.asyncio
async def test_director_cannot_expand_visibility() -> None:
    policy, build = _scope_build()
    from modules.evidence.compilation.knowledge.contracts import (
        KnowledgeDirectorPlan,
    )

    # 服务端生成者集合只含 a；导演把 b 也标 required 也不能扩大
    restricted_build = build_scope_receipt(
        CompiledContext(
            sections=[
                _section(
                    "world_entities",
                    [
                        {"type": "world_entity", "id": "a", "label": "主角组织"},
                        {"type": "world_entity", "id": "b", "label": "隐藏反派"},
                    ],
                )
            ]
        ),
        policy,
        KnowledgeSubject(subject_type="author"),
        novel_id="novel-1",
        generator_visible=["world_entity:a"],
    )
    manual_plan = KnowledgeDirectorPlan(
        policy_version=build.receipt.policy_version,
        capability=policy.capability_id,
        receipt_fingerprint=restricted_build.receipt.receipt_fingerprint(),
        dispositions=(
            KnowledgeDirectorDisposition(
                source_key="world_entity:a", disposition="required_for_generation"
            ),
            KnowledgeDirectorDisposition(
                source_key="world_entity:b", disposition="required_for_generation"
            ),
        ),
    )
    keys = apply_director_plan(restricted_build, manual_plan)
    assert keys == ("world_entity:a",), "导演只能缩小，不能扩大"


@pytest.mark.asyncio
async def test_repair_receives_sanitized_findings() -> None:
    policy, build = _scope_build()
    audit_blocked = _audit(
        [
            AuditFindingOutput(
                kind="premature_reveal",
                severity="blocker",
                message="输出复述了隐藏反派真实身份是某某",
            )
        ]
    )
    client = FakeGovernedClient(audit_outputs=[audit_blocked, _audit([], verdict="pass")])
    received: list[tuple[str, tuple]] = []

    async def generate(plan, generator_keys):  # noqa: ANN001
        return "泄漏正文"

    async def repair(original, findings):  # noqa: ANN001
        received.append((original, findings))
        return "修复正文"

    await run_governed_generation(
        client,
        policy=policy,
        scope_build=build,
        hooks=GovernedWorkflowHooks(
            generate=generate,
            repair=repair,
            task_instruction="t",
            generator_context="g",
            authority_context="a",
            hidden_phrases=("隐藏反派真实身份是某某",),
        ),
    )
    assert received, "repair hook 必须被调用"
    message = received[0][1][0].message
    assert "隐藏反派真实身份是某某" not in message, "返修 finding 必须脱敏"


def test_projection_redacts_hidden_and_drops_invisible_targets() -> None:
    policy, build = _scope_build()
    audit_blocked = _audit(
        [
            AuditFindingOutput(
                kind="premature_reveal",
                severity="blocker",
                message="复述了隐藏反派真实身份是某某",
                source_key="world_entity:b",
            ),
            AuditFindingOutput(
                kind="unsupported_fact",
                severity="major",
                message="无据地名",
                source_key="world_entity:a",
            ),
        ]
    )
    from modules.evidence.compilation.knowledge.contracts import (
        KnowledgeAuditFinding,
        KnowledgeAuditReceipt,
        knowledge_canonical_hash,
    )

    receipt = KnowledgeAuditReceipt(
        policy_version=1,
        capability=policy.capability_id,
        receipt_fingerprint="fp",
        plan_fingerprint="pfp",
        output_hash=knowledge_canonical_hash("正文"),
        verdict="blocked",
        findings=tuple(
            KnowledgeAuditFinding(
                kind=f.kind,
                severity=f.severity,
                message=f.message,
                excerpt=f.excerpt,
                source_key=f.source_key,
            )
            for f in audit_blocked.findings
        ),
        coverage=(),
    )
    payload = knowledge_review_payload(
        audit=receipt,
        visible_keys=["world_entity:a"],
        hidden_phrases=("隐藏反派真实身份是某某",),
    )
    assert payload["status"] == "blocked"
    assert payload["repaired"] is False
    for issue in payload["issues"]:
        assert "隐藏反派真实身份是某某" not in issue["message"]
        assert issue["open_target"] in ("", "world_entity:a")


def test_redact_hidden_phrases() -> None:
    text = "他揭露了隐藏反派真实身份是某某，然后离场。"
    redacted = redact_hidden_phrases(text, ["隐藏反派真实身份是某某"])
    assert "隐藏反派真实身份是某某" not in redacted
    assert "离场" in redacted


@pytest.mark.asyncio
async def test_audit_prompt_carries_output_permissions_and_author_requirements() -> None:
    """RB-2：审查者必须看到输出权限语义与生成器同源的作者要求投影。"""
    policy, build = _scope_build()
    client = FakeGovernedClient(audit_outputs=[_audit([], verdict="pass")])
    hooks = _hooks("生成正文")
    hooks.author_requirements = (
        '<AUTHOR_DECISION_STATE>{"confirmed_requirements": '
        '["不得复活死者"]}</AUTHOR_DECISION_STATE>'
    )
    outcome = await run_governed_generation(
        client, policy=policy, scope_build=build, hooks=hooks
    )
    assert outcome.passed
    prompt = client.audit_calls[0]
    assert "【输出权限】" in prompt
    assert "不因资料中没有依据而单独构成 unsupported_fact" in prompt
    assert "【作者要求（冻结投影）】" in prompt
    assert "不得复活死者" in prompt
    assert prompt.index("【输出权限】") < prompt.index("【任务指令】")
    assert prompt.index("【作者要求（冻结投影）】") < prompt.index("【生成者可见资料】")


def test_audit_prompt_omits_empty_requirements_and_renders_factual_policy() -> None:
    """answer 类能力没有提案豁免子句；未提供作者要求时不渲染空段落。"""
    from modules.evidence.compilation.knowledge.workflow import _audit_messages

    answer_policy = require_capability_policy("world.ask")
    plan = KnowledgeDirectorPlan(
        policy_version=1,
        capability=answer_policy.capability_id,
        receipt_fingerprint="0" * 64,
        dispositions=(),
    )

    async def _generate(plan, generator_keys):  # noqa: ANN001
        return "正文"

    hooks = GovernedWorkflowHooks(generate=_generate, task_instruction="回答问题")
    messages = _audit_messages(answer_policy, hooks, plan, "回答正文")
    prompt = messages[-1].content
    assert "【输出权限】" in prompt
    assert "不因资料中没有依据而单独构成 unsupported_fact" not in prompt
    assert "事实性断言必须有资料依据" in prompt
    assert "【作者要求（冻结投影）】" not in prompt
