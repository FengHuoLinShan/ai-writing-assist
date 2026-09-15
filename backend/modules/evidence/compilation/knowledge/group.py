"""组级知识治理（ADR-0025）。

导入相位、实体融合等按「组」摊薄治理成本：一个来源组（窗口 / Scene /
候选组 / 问题组 / 任务批）冻结一份 scope receipt，组内输出统一对照该
receipt 复核；blocked 且提供返修回调时返修一次再复审。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from modules.evidence.compilation.knowledge.contracts import (
    KnowledgeDirectorDisposition,
    KnowledgeDirectorPlan,
    KnowledgeScopeReceipt,
    KnowledgeSourceEntry,
    KnowledgeSubject,
)
from modules.evidence.compilation.knowledge.policies import (
    require_capability_policy,
)
from modules.evidence.compilation.knowledge.projection import knowledge_review_payload
from modules.evidence.compilation.knowledge.scope import KnowledgeScopeBuild
from modules.evidence.compilation.knowledge.workflow import (
    GovernedWorkflowHooks,
    run_knowledge_audit,
)


@dataclass(frozen=True)
class GroupSource:
    """组内一条来源（调用方负责冻结内容哈希）。"""

    source_key: str
    source_type: str
    source_id: str = ""
    content_hash: str = ""
    label: str = ""
    dimensions: tuple[str, ...] = ()


async def _noop_generate(_plan, _generator_keys) -> str:  # noqa: ANN001
    return ""


def build_group_scope(
    *,
    capability: str,
    novel_id: str,
    group_key: str,
    sources: Sequence[GroupSource],
    subject_type: str = "author",
) -> tuple[KnowledgeScopeBuild, KnowledgeDirectorPlan]:
    """冻结组级 receipt + 全票 required 处置计划（服务端已裁剪生成者包）。"""
    policy = require_capability_policy(capability)
    entries = tuple(
        KnowledgeSourceEntry(
            source_key=source.source_key,
            source_type=source.source_type,
            source_id=source.source_id,
            content_hash=source.content_hash
            or hashlib.sha256(source.source_key.encode("utf-8")).hexdigest(),
            label=source.label or source.source_type,
            dimensions=source.dimensions,
        )
        for source in sources
    )
    fingerprint = hashlib.sha256(
        json.dumps(
            [entry.content_hash for entry in entries] + [group_key],
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    receipt = KnowledgeScopeReceipt(
        policy_version=1,
        capability=policy.capability_id,
        novel_id=str(novel_id),
        subject=KnowledgeSubject(subject_type=subject_type),
        included=entries,
        scope_complete=True,
        authority_fingerprint=fingerprint,
        generator_fingerprint=fingerprint,
    )
    plan = KnowledgeDirectorPlan(
        policy_version=1,
        capability=policy.capability_id,
        receipt_fingerprint=receipt.receipt_fingerprint(),
        dispositions=tuple(
            KnowledgeDirectorDisposition(
                source_key=entry.source_key,
                disposition="required_for_generation",
            )
            for entry in entries
        ),
    )
    plan.validate_against_receipt(receipt)
    scope_build = KnowledgeScopeBuild(
        receipt=receipt,
        generator_keys=tuple(entry.source_key for entry in entries),
        audit_only_keys=(),
    )
    return scope_build, plan


async def govern_group_output(
    client,
    *,
    capability: str,
    novel_id: str,
    group_key: str,
    sources: Sequence[GroupSource],
    output: str,
    task_instruction: str,
    generator_context: str = "",
    repair: Callable[[str], Awaitable[str]] | None = None,
    step_prefix: str | None = None,
) -> dict:
    """对照组级 receipt 审查一段输出；blocked 且有返修回调时返修一次再复审。

    返回 ``{"status": passed|blocked, "text", "review"}``；blocked 时 text 为
    空串。unverifiable / not_checked 不返修直接阻断。
    """
    policy = require_capability_policy(capability)
    scope_build, plan = build_group_scope(
        capability=capability,
        novel_id=novel_id,
        group_key=group_key,
        sources=sources,
    )
    context = generator_context[:24000]

    async def _audit(text: str):  # noqa: ANN202
        return await run_knowledge_audit(
            client,
            policy=policy,
            scope_build=scope_build,
            plan=plan,
            hooks=GovernedWorkflowHooks(
                generate=_noop_generate,
                task_instruction=task_instruction,
                generator_context=context,
                authority_context=context,
            ),
            output=text,
            step_prefix=step_prefix or f"{capability}.group",
        )

    audit = await _audit(output)
    if audit.verdict == "pass":
        return {
            "status": "passed",
            "text": output,
            "review": knowledge_review_payload(
                audit=audit, visible_keys=scope_build.generator_keys
            ),
        }
    if audit.verdict != "blocked" or repair is None:
        return {
            "status": "blocked",
            "text": "",
            "review": knowledge_review_payload(
                audit=audit, visible_keys=scope_build.generator_keys
            ),
        }

    findings_block = "\n".join(
        f"- [{item.severity}] {item.kind}: {item.message}" for item in audit.findings
    )
    repaired_text = await repair(findings_block)
    repair_audit = await _audit(repaired_text)
    review = knowledge_review_payload(
        audit=repair_audit,
        repaired=True,
        visible_keys=scope_build.generator_keys,
    )
    if repair_audit.verdict == "pass":
        return {"status": "passed", "text": repaired_text, "review": review}
    return {"status": "blocked", "text": "", "review": review}


def serialize_group_output(output) -> str:  # noqa: ANN001
    """结构化组输出折成待审文本。"""
    if hasattr(output, "model_dump"):
        return json.dumps(
            output.model_dump(mode="json"), ensure_ascii=False, default=str
        )
    return str(output)
