"""World 域知识治理接线（ADR-0025）。

世界生成中心等服务端已按作者确认编译资料并裁剪生成者包（Evidence compile、
source refs 与 rendered_context），导演的可见性职责由服务端权威裁剪承担；
治理落地为「全知审查 → ≤1 次语义返修 → 复审 → 通过或阻断」。

- 建议类（对象/页面提案）：审查回执写入 suggestion payload 的 ``knowledge_review``，
  阻断建议仍保存为 candidate，但采用门禁统一拒绝未 PASS 项。
- 展示类（chat/Ask World 临时回答）：blocked 时不返回不安全正文。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Sequence

from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
from modules.evidence.contracts import (
    REPAIR_INSTRUCTION_TEMPLATE,
    GovernedWorkflowHooks,
    KnowledgeDirectorDisposition,
    KnowledgeDirectorPlan,
    KnowledgeScopeBuild,
    KnowledgeScopeReceipt,
    KnowledgeSourceEntry,
    KnowledgeSubject,
    knowledge_review_payload,
    require_capability_policy,
    run_knowledge_audit,
)
from modules.world.schemas import WorldBibleSourceRef

_REVIEW_BLOCKED_MESSAGE = (
    "知识审查未通过：该内容可能越过角色/读者知识边界或缺乏来源支持，"
    "暂不返回正文。请补充资料或调整范围后重试。"
)


def _ref_dimensions(source_type: str) -> tuple[str, ...]:
    if source_type in {"world_bible_page", "world_bible_page_draft"}:
        return ("world_bible",)
    if source_type == "world_bible_synopsis":
        return ("world_bible",)
    if source_type == "writing_chapter":
        return ("prior_prose",)
    return ("world_entities",)


def world_scope_entries(
    source_refs: Sequence[WorldBibleSourceRef],
    rendered_context: str,
) -> tuple[KnowledgeSourceEntry, ...]:
    """把世界侧冻结来源（证据 refs + 服务端编译上下文）折成 scope entries。

    author_messages 是作者指令而非资料，不进入知识来源清单。
    """
    entries: list[KnowledgeSourceEntry] = []
    for ref in source_refs:
        if ref.source_type == "author_messages":
            continue
        digest = ref.source_hash or hashlib.sha256(
            str(ref.source_id or ref.page_id or "").encode("utf-8")
        ).hexdigest()
        entries.append(
            KnowledgeSourceEntry(
                source_key=(
                    f"{ref.source_type}:{ref.source_id or ref.chapter_index or 'page'}"
                    f":{digest[:12]}"
                ),
                source_type=ref.source_type,
                source_id=str(ref.source_id or ref.page_id or ref.chapter_index or ""),
                content_hash=digest,
                label=ref.title or ref.source_type,
                dimensions=_ref_dimensions(ref.source_type),
            )
        )
    context_hash = hashlib.sha256(rendered_context.encode("utf-8")).hexdigest()
    entries.append(
        KnowledgeSourceEntry(
            source_key=f"compiled_context:{context_hash[:12]}",
            source_type="compiled_context",
            source_id="server",
            content_hash=context_hash,
            label="服务端编译的权威上下文",
            dimensions=("world_rules", "world_bible"),
        )
    )
    return tuple(entries)


async def _noop_generate(_plan, _generator_keys) -> str:  # noqa: ANN001
    return ""


def _blocked_result(scope_build: KnowledgeScopeBuild, audit) -> dict:  # noqa: ANN001
    return {
        "status": "blocked",
        "text": "",
        "review": knowledge_review_payload(
            audit=audit, visible_keys=scope_build.generator_keys
        ),
    }


async def govern_world_output(
    client,
    *,
    capability: str,
    novel_id: str,
    source_refs: Sequence[WorldBibleSourceRef],
    rendered_context: str,
    output: str,
    task_instruction: str,
    author_requirements: str = "",
    repair: Callable[[str], Awaitable[str]] | None = None,
    step_prefix: str | None = None,
) -> dict:
    """审查一段已生成的世界侧输出；blocked 且提供返修回调时返修一次再复审。

    返回 ``{"status": passed|blocked, "text": 最终输出, "review": 脱敏回执}``；
    blocked 时 text 为空串（调用方不得展示/采用原文，建议类仍可保存为不可采用
    candidate）。生成者可见资料 = 本次编译上下文（服务端已裁剪）；权威对照同源。
    author_requirements 是与生成器同源的作者决定冻结投影，不截断进入审查。
    """
    policy = require_capability_policy(capability)
    entries = world_scope_entries(source_refs, rendered_context)
    fingerprint = "|".join(entry.content_hash for entry in entries)
    receipt = KnowledgeScopeReceipt(
        policy_version=1,
        capability=policy.capability_id,
        novel_id=novel_id,
        subject=KnowledgeSubject(subject_type="author"),
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
    # 资料投影按预算截断；作者决定投影（author_requirements）不截断——
    # 审查者必须看到与生成器等价的作者边界才能核验提案是否遵守。
    context_for_audit = rendered_context[:24000]

    async def _audit(text: str):  # noqa: ANN202
        return await run_knowledge_audit(
            client,
            policy=policy,
            scope_build=scope_build,
            plan=plan,
            hooks=GovernedWorkflowHooks(
                generate=_noop_generate,
                task_instruction=task_instruction,
                author_requirements=author_requirements,
                generator_context=context_for_audit,
                authority_context=context_for_audit,
            ),
            output=text,
            step_prefix=step_prefix or capability,
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
        return _blocked_result(scope_build, audit)

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


def serialize_governed_output(output) -> str:  # noqa: ANN001
    """结构化输出折成待审文本（pydantic → 紧凑 JSON）。"""
    if hasattr(output, "model_dump"):
        return json.dumps(
            output.model_dump(mode="json"), ensure_ascii=False, default=str
        )
    return str(output)


def structured_repair_factory(
    run_structured: Callable[..., Awaitable],
    client,  # noqa: ANN001
    request: LLMCallRequest,
    schema: type,
    *,
    step_name: str,
    **run_kwargs,
) -> Callable[[str], Awaitable[str]]:
    """为结构化生成构造返修回调：追加审查问题后用同一 schema 重生成。"""

    async def _repair(findings_block: str) -> str:
        repair_request = request.model_copy(deep=True)
        repair_request.messages.append(
            LLMMessage(
                role="user",
                content=REPAIR_INSTRUCTION_TEMPLATE.format(
                    findings_block=findings_block
                ),
            )
        )
        repaired = await run_structured(
            client,
            repair_request,
            schema,
            step_name=f"{step_name}.knowledge.repair",
            **run_kwargs,
        )
        return serialize_governed_output(repaired)

    return _repair


def require_knowledge_review_passed(
    payload_json: dict,
    *,
    label: str,
) -> None:
    """采用门禁：携带 knowledge_review 的 AI 建议必须 PASS 才可被采用。

    无 knowledge_review 键的旧 AI 建议按 legacy 处理同样拒绝（fail closed），
    提示作者重新生成；由非 AI 路径创建的建议不调用本门禁。
    """
    from modules.evidence.contracts import require_knowledge_review_for_adoption

    require_knowledge_review_for_adoption(
        payload_json,
        label=label,
    )


def knowledge_blocked_reply() -> str:
    """展示类能力 blocked 时返回给作者的替代正文（不含任何生成内容）。"""
    return _REVIEW_BLOCKED_MESSAGE
