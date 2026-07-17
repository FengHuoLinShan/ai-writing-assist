"""P20 v2 generation and deterministic current-layer materialization."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import DomainError
from infrastructure.llm.agent_step_harness import (
    AgentPermissionLevel,
    run_managed_structured,
)
from infrastructure.llm.client import LLMClient
from infrastructure.llm.prompt_loader import load_prompt
from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
from infrastructure.tasks.contracts import CompletedTaskPayloadContract
from modules.context import facade as context_facade
from modules.context.contracts import ConfirmedAIActionContext
from modules.outline.models import (
    ForeshadowingPlan,
    OutlineArc,
    PlotThread,
    RevealPlan,
    Scene,
)
from modules.outline.p20_context import (
    P20ContextBuilder,
    P20GenerationPlan,
    serialize_untrusted_json,
)
from modules.outline.p20_schemas import (
    P20_OUTPUT_SCHEMAS,
    OutlineLayerGenerateRequest,
    P20ArcDraft,
    P20InformationMovement,
    P20OutlineArcOutput,
    P20PlannedSceneOutput,
    P20PlotThreadOutput,
    P20SceneDraft,
    P20SemanticAudit,
    P20ThreadDraft,
)

P20_TIMEOUT_SECONDS = 1800
P20_PROMPTS = {
    "plot_thread": "p20_plot_thread",
    "outline_arc": "p20_outline_arc",
    "planned_scene": "p20_planned_scene",
}
_P20_SHORT_REFERENCE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(?:SO-CURRENT|IM\d{3}|[MPTASCE]\d{3})(?![A-Za-z0-9_])"
)


def _embedded_reference_violations(output: BaseModel) -> list[str]:
    """Find short citations that cannot be verified outside dedicated fields."""

    violations: list[str] = []

    def visit(value: Any, path: str) -> None:
        if len(violations) >= 20:
            return
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = f"{path}.{key}" if path else str(key)
                if str(key).endswith(("_ref", "_refs")):
                    continue
                visit(child, child_path)
            return
        if isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]")
            return
        if not isinstance(value, str):
            return
        tokens = list(dict.fromkeys(_P20_SHORT_REFERENCE_PATTERN.findall(value)))
        if tokens:
            violations.append(
                f"{path} 在自由文本中嵌入短引用 {', '.join(tokens)}；"
                "请删除这些引用，只在契约的 *_ref/*_refs 字段使用短引用"
            )

    visit(output.model_dump(mode="json"), "output")
    return violations


def _information_movement_chronology_violations(output: BaseModel) -> list[str]:
    """Report chronology as a semantic issue without rewriting model content.

    Node chronology is a narrative constraint rather than a JSON-shape concern.
    Keeping it out of Pydantic validation lets the bounded P20 semantic revision
    see the exact movement instead of receiving an opaque ``value_error`` in the
    generic format-repair loop.
    """

    if not isinstance(output, P20PlotThreadOutput):
        return []
    violations: list[str] = []
    for thread_index, thread in enumerate(output.threads):
        for movement_index, movement in enumerate(thread.information_movements):
            concrete_chapters = [
                node.chapter_hint
                for node in movement.nodes
                if node.chapter_hint is not None
            ]
            if concrete_chapters == sorted(concrete_chapters):
                continue
            node_path = (
                f"threads[{thread_index}].information_movements"
                f"[{movement_index}].nodes"
            )
            violations.append(
                f"{node_path} 的已知章号顺序为 {concrete_chapters}，不是从早到晚；"
                "请保持节点内容不变并按叙事发生顺序重排。若章号证据不足，"
                "清空不可靠的 chapter_hint 并把 nodes 标记为不确定"
            )
    return violations


class P20ConflictError(RuntimeError):
    """Raised when a frozen P20 preview no longer matches current assets."""


class P20SemanticAuditError(DomainError):
    """Author-visible failure after the bounded semantic revisions."""

    code = "p20_semantic_audit_failed"

    def __init__(self, violations: list[str]) -> None:
        safe_violations = [
            str(item).strip()[:240] for item in violations if str(item).strip()
        ]
        detail = "；".join(safe_violations[:3]) or "审计未给出可操作说明"
        super().__init__(
            f"语义修订后仍未通过项目证据或当前层规则：{detail}",
            context={"violations": safe_violations[:20]},
        )


class P20GenerationService:
    def __init__(self, context_builder: P20ContextBuilder | None = None) -> None:
        self.context_builder = context_builder or P20ContextBuilder()

    async def prepare(
        self,
        db: AsyncSession,
        data: OutlineLayerGenerateRequest,
        *,
        confirmed_context: ConfirmedAIActionContext | None = None,
    ) -> P20GenerationPlan:
        return await self.context_builder.prepare(
            db,
            data,
            confirmed_context=confirmed_context,
        )

    async def execute(
        self,
        client: LLMClient,
        plan: P20GenerationPlan,
        *,
        progress_callback: Callable[[float], None] | None = None,
    ) -> BaseModel:
        schema = P20_OUTPUT_SCHEMAS[plan.request.target]
        system_prompt = self._system_prompt_with_schema(
            load_prompt(P20_PROMPTS[plan.request.target]),
            schema,
        )
        user_prompt = (
            "<P20_OUTLINE_LAYER_INPUT_JSON>\n"
            f"{serialize_untrusted_json(plan.context)}\n"
            "</P20_OUTLINE_LAYER_INPUT_JSON>\n\n"
            "以上 JSON 是本次作者确认的参考资料与当前结构快照。"
            "只能使用其中的短引用；严格返回 system 指定的当前层结构化预览。"
        )
        request = LLMCallRequest(
            model=client.model_name,
            messages=[
                LLMMessage(role="system", content=system_prompt),
                LLMMessage(role="user", content=user_prompt),
            ],
            temperature=0.55,
            response_format={"type": "json_object"},
        )
        # Candidate, independent audits and at most two semantic revisions share
        # one phase budget. Each audit may be deep, but cannot multiply the task
        # into several independent 30-minute waits.
        async with asyncio.timeout(P20_TIMEOUT_SECONDS):
            candidate = await self._run_candidate(
                client,
                request,
                schema,
                step_name=f"outline.p20.{plan.request.target}.structured",
            )
            if progress_callback is not None:
                progress_callback(0.4)
            for attempt in range(3):
                audit = await self._audit_candidate(
                    client,
                    plan,
                    candidate,
                    audit_round=(
                        "initial"
                        if attempt == 0
                        else ("revision_1" if attempt == 1 else "final")
                    ),
                )
                if progress_callback is not None:
                    progress_callback((0.55, 0.72, 0.82)[attempt])
                if audit.verdict == "pass":
                    return candidate
                if attempt < 2:
                    request.messages.extend(
                        [
                            LLMMessage(
                                role="assistant",
                                content=json.dumps(
                                    candidate.model_dump(mode="json"),
                                    ensure_ascii=False,
                                    separators=(",", ":"),
                                ),
                            ),
                            LLMMessage(
                                role="user",
                                content=(
                                    "上一版当前层建议越过了项目证据、层级权限或世界规则，"
                                    "不能作为可采用预览。保留其有效的长篇结构作用，但完全"
                                    "删除外部正史污染；已物化章节内只保留输入证据支持的"
                                    "事实和节点，未决定内容降为原创未来提案、不确定项或"
                                    "作者决策。作者已经明确禁止的内容必须从所有字段中完全"
                                    "删除，不能改写成 author_decisions 的问题、选项、"
                                    "例子、可能性或不确定项。请返回修订后的完整当前层 "
                                    "JSON，不要解释。"
                                    "逐条执行越界项给出的字段级修正；如果审计指出了"
                                    "正确的短引用，必须替换到对应 *_ref/*_refs 字段。"
                                    "如果输入证据不足以确定正确引用，就清空该引用与"
                                    "不可靠章号并标记不确定，不能保留已指出的错配。"
                                    "越界项："
                                    + json.dumps(
                                        audit.violations,
                                        ensure_ascii=False,
                                        separators=(",", ":"),
                                    )
                                    + "\n"
                                    + self._schema_contract(schema)
                                ),
                            ),
                        ]
                    )
                    candidate = await self._run_candidate(
                        client,
                        request,
                        schema,
                        step_name=(
                            f"outline.p20.{plan.request.target}.semantic_revision"
                            + ("" if attempt == 0 else f"_{attempt + 1}")
                        ),
                    )
                    if progress_callback is not None:
                        progress_callback((0.65, 0.78)[attempt])
                    continue
                raise P20SemanticAuditError(audit.violations)
        raise AssertionError("unreachable P20 semantic audit state")

    @staticmethod
    def _schema_contract(schema: type[BaseModel]) -> str:
        return (
            "<P20_OUTPUT_CONTRACT_JSON_SCHEMA>\n"
            f"{serialize_untrusted_json(schema.model_json_schema())}\n"
            "</P20_OUTPUT_CONTRACT_JSON_SCHEMA>\n"
            "输出必须直接匹配以上完整契约；不要增加契约之外的字段。"
        )

    @classmethod
    def _system_prompt_with_schema(
        cls,
        prompt: str,
        schema: type[BaseModel],
    ) -> str:
        return f"{prompt}\n\n{cls._schema_contract(schema)}"

    @staticmethod
    async def _run_candidate(
        client: LLMClient,
        request: LLMCallRequest,
        schema: type[BaseModel],
        *,
        step_name: str,
    ) -> BaseModel:
        return await run_managed_structured(
            client,
            request,
            schema,
            step_name=step_name,
            max_fix_attempts=2,
            format_repair_attempts=1,
            permission_level=AgentPermissionLevel.suggest,
            read_only=True,
            timeout=P20_TIMEOUT_SECONDS,
        )

    @classmethod
    async def _audit_candidate(
        cls,
        client: LLMClient,
        plan: P20GenerationPlan,
        candidate: BaseModel,
        *,
        audit_round: str,
    ) -> P20SemanticAudit:
        payload = {
            "target": plan.request.target,
            "mode": plan.request.mode,
            "author_instruction": plan.request.instruction,
            "authoritative_project_context": plan.context,
            "candidate_current_layer_preview": candidate.model_dump(mode="json"),
        }
        audits = await asyncio.gather(
            cls._run_audit(
                client,
                payload,
                prompt_name="p20_evidence_audit",
                step_name=(
                    f"outline.p20.{plan.request.target}.evidence_canon_audit."
                    f"{audit_round}"
                ),
            ),
            cls._run_audit(
                client,
                payload,
                prompt_name="p20_scope_rule_audit",
                step_name=(
                    f"outline.p20.{plan.request.target}.scope_rule_audit."
                    f"{audit_round}"
                ),
            ),
            cls._run_audit(
                client,
                payload,
                prompt_name="p20_author_instruction_audit",
                step_name=(
                    f"outline.p20.{plan.request.target}.author_instruction_audit."
                    f"{audit_round}"
                ),
            ),
        )
        audit_labels = ("evidence_canon", "scope_rule", "author_instruction")
        deterministic_violations = [
            f"[reference_integrity] {item}"
            for item in _embedded_reference_violations(candidate)
        ] + [
            f"[information_chronology] {item}"
            for item in _information_movement_chronology_violations(candidate)
        ]
        violations = list(
            dict.fromkeys(
                [
                    f"[{label}] {violation}"
                    for label, audit in zip(audit_labels, audits, strict=True)
                    for violation in audit.violations
                ]
                + deterministic_violations
            )
        )[:20]
        return P20SemanticAudit(
            verdict="revise" if violations else "pass",
            violations=violations,
        )

    @classmethod
    async def _run_audit(
        cls,
        client: LLMClient,
        payload: dict[str, Any],
        *,
        prompt_name: str,
        step_name: str,
    ) -> P20SemanticAudit:
        system_prompt = cls._system_prompt_with_schema(
            load_prompt(prompt_name),
            P20SemanticAudit,
        )
        return await run_managed_structured(
            client,
            LLMCallRequest(
                model=client.model_name,
                messages=[
                    LLMMessage(role="system", content=system_prompt),
                    LLMMessage(
                        role="user",
                        content=(
                            "<P20_AUDIT_INPUT_JSON>\n"
                            f"{serialize_untrusted_json(payload)}\n"
                            "</P20_AUDIT_INPUT_JSON>"
                        ),
                    ),
                ],
                temperature=0.0,
                response_format={"type": "json_object"},
            ),
            P20SemanticAudit,
            step_name=step_name,
            max_fix_attempts=2,
            format_repair_attempts=1,
            permission_level=AgentPermissionLevel.suggest,
            read_only=True,
            timeout=P20_TIMEOUT_SECONDS,
        )

    @staticmethod
    def task_result(
        plan: P20GenerationPlan,
        output: BaseModel,
        *,
        task_id: str,
    ) -> dict[str, Any]:
        draft = output.model_dump(mode="json")
        target = plan.request.target
        counts = {
            "total_threads": len(draft.get("threads") or []),
            "total_arcs": len(draft.get("arcs") or []),
            "total_scenes": len(draft.get("scenes") or []),
        }
        return {
            "contract_version": "outline_layer_v2",
            "target": target,
            "mode": plan.request.mode,
            "draft_structure": draft,
            "requires_apply": True,
            "source_task_id": task_id,
            "context_confirmation_id": plan.request.context_confirmation_id,
            "context_fingerprint": plan.source_fingerprint,
            "story_outline_revision_id": plan.context_provenance[
                "story_outline_revision_id"
            ],
            "overlap": P20GenerationService._overlap_summary(plan),
            **counts,
            "_reference_map": plan.reference_map,
            "_request": plan.request.model_dump(mode="json"),
            "_context_provenance": plan.context_provenance,
        }

    @staticmethod
    def _overlap_summary(plan: P20GenerationPlan) -> dict[str, Any]:
        context = plan.context
        return {
            "plot_threads": [
                {"ref": item["ref"], "name": item["name"]}
                for item in context.get("plot_threads") or []
            ],
            "outline_arcs": [
                {"ref": item["ref"], "title": item["title"]}
                for item in context.get("outline_arcs") or []
            ],
            "scenes": [
                {"ref": item["ref"], "title": item["title"]}
                for item in context.get("scenes") or []
            ],
        }


class P20ApplyService:
    """Validate an edited preview and atomically apply only its current layer."""

    def __init__(self, generation: P20GenerationService | None = None) -> None:
        self.generation = generation or P20GenerationService()

    async def apply(
        self,
        db: AsyncSession,
        *,
        task: CompletedTaskPayloadContract,
        novel_id: str,
        confirmation_id: str,
        draft_structure: dict[str, Any],
    ) -> dict[str, Any]:
        task_result = task.result
        request_payload = task_result.get("_request")
        reference_map = task_result.get("_reference_map")
        if not isinstance(request_payload, dict) or not isinstance(
            reference_map,
            dict,
        ):
            raise ValueError("P20 source task is missing its frozen v2 contract")
        request = OutlineLayerGenerateRequest.model_validate(request_payload)
        if request.novel_id != novel_id:
            raise ValueError("P20 source task novel mismatch")
        if request.context_confirmation_id != confirmation_id:
            raise ValueError("P20 source task confirmation mismatch")

        preview = task_result.get("draft_structure")
        if not isinstance(preview, dict):
            raise ValueError("P20 source task has no draft_structure")
        schema = P20_OUTPUT_SCHEMAS[request.target]
        edited = schema.model_validate(draft_structure)
        self._validate_preview_scope(request, preview, edited)
        self._validate_references(request, edited, reference_map)

        from modules.project.facade import require_active_project_exclusive

        # Recompile before taking the project-wide finalization lock. RAG trace
        # persistence uses an independent DB session whose project FK would
        # otherwise wait on our own FOR UPDATE lock, leaving the apply request
        # idle in transaction. Once locked, revalidate the confirmation and
        # rebuild only from the already compiled context so no external trace
        # write runs inside the exclusive section.
        fresh = await self.generation.prepare(db, request)
        if fresh.source_fingerprint != task_result.get("context_fingerprint"):
            raise P20ConflictError(
                "小说总纲、所选资产或确认上下文已经变化；请重新生成预览"
            )
        if fresh.confirmed_context is None:
            raise RuntimeError("P20 apply freshness plan is missing confirmed context")

        await require_active_project_exclusive(db, novel_id)
        await context_facade.require_fresh_confirmation(
            db,
            novel_id=novel_id,
            action="outline.generate",
            confirmation_id=confirmation_id,
            for_update=True,
        )
        locked_fresh = await self.generation.prepare(
            db,
            request,
            confirmed_context=fresh.confirmed_context,
        )
        if locked_fresh.source_fingerprint != fresh.source_fingerprint:
            raise P20ConflictError(
                "小说总纲、所选资产或确认上下文在采用时发生变化；请重新生成预览"
            )
        fresh = locked_fresh

        adopted_at = datetime.now(UTC).isoformat()
        applied_result: dict[str, Any]
        async with db.begin_nested():
            if request.target == "plot_thread":
                result_refs = await self._apply_threads(
                    db,
                    request=request,
                    output=edited,
                    reference_map=reference_map,
                    task_id=task.task_id,
                    context_fingerprint=fresh.source_fingerprint,
                    story_outline_revision_id=fresh.context_provenance[
                        "story_outline_revision_id"
                    ],
                    adopted_at=adopted_at,
                )
            elif request.target == "outline_arc":
                result_refs = await self._apply_arcs(
                    db,
                    request=request,
                    output=edited,
                    reference_map=reference_map,
                    task_id=task.task_id,
                    context_fingerprint=fresh.source_fingerprint,
                    story_outline_revision_id=fresh.context_provenance[
                        "story_outline_revision_id"
                    ],
                    adopted_at=adopted_at,
                )
            else:
                result_refs = await self._apply_scenes(
                    db,
                    request=request,
                    output=edited,
                    reference_map=reference_map,
                    task_id=task.task_id,
                    context_fingerprint=fresh.source_fingerprint,
                    story_outline_revision_id=fresh.context_provenance[
                        "story_outline_revision_id"
                    ],
                    adopted_at=adopted_at,
                )
            await context_facade.attach_result_refs(
                db,
                confirmation_id=confirmation_id,
                result_refs=result_refs,
                status="done",
            )
            applied_result = {
                "status": "applied",
                "contract_version": "outline_layer_v2",
                "target": request.target,
                "mode": request.mode,
                "result": edited.result,
                "applied_ids": [item["id"] for item in result_refs],
                "total_threads": sum(
                    item["type"] == "plot_thread" for item in result_refs
                ),
                "total_arcs": sum(
                    item["type"] == "outline_arc" for item in result_refs
                ),
                "total_scenes": sum(
                    item["type"] == "scene" for item in result_refs
                ),
            }
            from infrastructure.tasks.facade import replace_completed_task_result

            replaced = await replace_completed_task_result(
                db,
                task_id=task.task_id,
                task_type="outline_generate",
                novel_id=novel_id,
                expected_revision_token=task.revision_token,
                result={
                    **task_result,
                    "requires_apply": False,
                    "apply_status": "applied",
                    "applied_result": applied_result,
                },
            )
            if not replaced:
                raise P20ConflictError("P20 preview is no longer applicable")

        return applied_result

    @staticmethod
    def _validate_preview_scope(
        request: OutlineLayerGenerateRequest,
        preview: dict[str, Any],
        edited: BaseModel,
    ) -> None:
        field = {
            "plot_thread": "threads",
            "outline_arc": "arcs",
            "planned_scene": "scenes",
        }[request.target]
        preview_refs = [
            str(item.get("proposal_ref") or "")
            for item in preview.get(field) or []
            if isinstance(item, dict)
        ]
        edited_refs = [item.proposal_ref for item in getattr(edited, field)]
        if preview_refs != edited_refs or len(edited_refs) != len(set(edited_refs)):
            raise ValueError("edited preview must preserve proposal order and references")

    @staticmethod
    def _validate_references(
        request: OutlineLayerGenerateRequest,
        output: BaseModel,
        refs: dict[str, dict[str, str]],
    ) -> None:
        embedded = _embedded_reference_violations(output)
        if embedded:
            raise ValueError(embedded[0])
        valid_threads = set(refs.get("threads") or {})
        valid_arcs = set(refs.get("arcs") or {})
        valid_scenes = set(refs.get("scenes") or {})
        valid_characters = set(refs.get("characters") or {})
        valid_entities = set(refs.get("entities") or {})
        selected_refs = {
            "plot_thread": {
                ref
                for ref, value in (refs.get("threads") or {}).items()
                if value in request.selected_thread_ids
            },
            "outline_arc": {
                ref
                for ref, value in (refs.get("arcs") or {}).items()
                if value in request.selected_arc_ids
            },
            "planned_scene": {
                ref
                for ref, value in (refs.get("scenes") or {}).items()
                if value in request.selected_scene_ids
            },
        }[request.target]

        def require_subset(values: list[str], allowed: set[str], label: str) -> None:
            if not set(values).issubset(allowed):
                raise ValueError(f"{label} contains an unknown or cross-novel reference")

        if request.target == "plot_thread":
            assert isinstance(output, P20PlotThreadOutput)
            require_subset(
                [item.existing_thread_ref for item in output.reuse_judgments],
                valid_threads,
                "reuse_judgments",
            )
            for item in output.threads:
                P20ApplyService._require_target_ref(
                    request,
                    item.target_thread_ref,
                    selected_refs,
                )
                require_subset(
                    item.related_character_refs,
                    valid_characters,
                    "characters",
                )
                require_subset(item.related_entity_refs, valid_entities, "entities")
                movement_refs = [
                    movement.movement_ref
                    for movement in item.information_movements
                ]
                if len(movement_refs) != len(set(movement_refs)):
                    raise ValueError("information movement references must be unique")
                for movement in item.information_movements:
                    if movement.target_ref is not None:
                        require_subset(
                            [movement.target_ref],
                            valid_characters | valid_entities,
                            "information movement target",
                        )
                    require_subset(
                        [node.scene_ref for node in movement.nodes if node.scene_ref],
                        valid_scenes,
                        "information movement Scene",
                    )
        elif request.target == "outline_arc":
            assert isinstance(output, P20OutlineArcOutput)
            for item in output.arcs:
                P20ApplyService._require_target_ref(
                    request,
                    item.target_arc_ref,
                    selected_refs,
                )
                require_subset(item.related_thread_refs, valid_threads, "threads")
                require_subset(
                    item.related_character_refs,
                    valid_characters,
                    "characters",
                )
                require_subset(item.related_entity_refs, valid_entities, "entities")
        else:
            assert isinstance(output, P20PlannedSceneOutput)
            for item in output.scenes:
                P20ApplyService._require_target_ref(
                    request,
                    item.target_scene_ref,
                    selected_refs,
                )
                if item.parent_arc_ref:
                    require_subset([item.parent_arc_ref], valid_arcs, "parent arc")
                if item.pov_character_ref:
                    require_subset(
                        [item.pov_character_ref],
                        valid_characters,
                        "POV character",
                    )
                require_subset(item.related_thread_refs, valid_threads, "threads")
                require_subset(
                    item.related_character_refs,
                    valid_characters,
                    "characters",
                )
                require_subset(item.related_entity_refs, valid_entities, "entities")

    @staticmethod
    def _require_target_ref(
        request: OutlineLayerGenerateRequest,
        target_ref: str | None,
        selected_refs: set[str],
    ) -> None:
        if request.mode == "create" and target_ref is not None:
            raise ValueError("create mode cannot update an existing asset")
        if request.mode == "revise" and target_ref not in selected_refs:
            raise ValueError("revise mode can only update explicitly selected assets")

    async def _apply_threads(
        self,
        db: AsyncSession,
        *,
        request: OutlineLayerGenerateRequest,
        output: P20PlotThreadOutput,
        reference_map: dict[str, dict[str, str]],
        task_id: str,
        context_fingerprint: str,
        story_outline_revision_id: str,
        adopted_at: str,
    ) -> list[dict[str, str]]:
        result_refs: list[dict[str, str]] = []
        for draft in output.threads:
            if request.mode == "revise":
                thread_id = uuid.UUID(reference_map["threads"][draft.target_thread_ref])
                thread = await db.scalar(
                    select(PlotThread).where(
                        PlotThread.id == thread_id,
                        PlotThread.novel_id == uuid.UUID(request.novel_id),
                    )
                )
                if thread is None:
                    raise P20ConflictError("selected PlotThread no longer exists")
                before = self._thread_snapshot(thread)
                meta = self._revision_meta(
                    thread.provenance_meta,
                    before=before,
                    task_id=task_id,
                    context_fingerprint=context_fingerprint,
                    story_outline_revision_id=story_outline_revision_id,
                    adopted_at=adopted_at,
                )
            else:
                thread = PlotThread(novel_id=uuid.UUID(request.novel_id), status="draft")
                meta = self._new_asset_meta(
                    task_id=task_id,
                    context_fingerprint=context_fingerprint,
                    story_outline_revision_id=story_outline_revision_id,
                    adopted_at=adopted_at,
                )
                db.add(thread)
            self._assign_thread(thread, draft, reference_map)
            meta["information_movements"] = [
                item.model_dump(mode="json") for item in draft.information_movements
            ]
            meta["p20_basis"] = draft.basis
            meta["p20_uncertain_fields"] = list(draft.uncertain_fields)
            meta["p20_confidence"] = draft.confidence
            meta["needs_review"] = bool(
                draft.uncertain_fields
                or any(item.uncertain_fields for item in draft.information_movements)
            )
            thread.provenance_meta = meta
            await db.flush()
            result_refs.append({"type": "plot_thread", "id": str(thread.id)})
            result_refs.extend(
                await self._project_information_movements(
                    db,
                    request=request,
                    thread=thread,
                    draft=draft,
                    reference_map=reference_map,
                    task_id=task_id,
                    context_fingerprint=context_fingerprint,
                    story_outline_revision_id=story_outline_revision_id,
                    adopted_at=adopted_at,
                )
            )
        return result_refs

    async def _apply_arcs(
        self,
        db: AsyncSession,
        *,
        request: OutlineLayerGenerateRequest,
        output: P20OutlineArcOutput,
        reference_map: dict[str, dict[str, str]],
        task_id: str,
        context_fingerprint: str,
        story_outline_revision_id: str,
        adopted_at: str,
    ) -> list[dict[str, str]]:
        refs: list[dict[str, str]] = []
        for draft in output.arcs:
            if request.mode == "revise":
                arc_id = uuid.UUID(reference_map["arcs"][draft.target_arc_ref])
                arc = await db.scalar(
                    select(OutlineArc).where(
                        OutlineArc.id == arc_id,
                        OutlineArc.novel_id == uuid.UUID(request.novel_id),
                    )
                )
                if arc is None:
                    raise P20ConflictError("selected OutlineArc no longer exists")
                meta = self._revision_meta(
                    arc.provenance_meta,
                    before=self._arc_snapshot(arc),
                    task_id=task_id,
                    context_fingerprint=context_fingerprint,
                    story_outline_revision_id=story_outline_revision_id,
                    adopted_at=adopted_at,
                )
            else:
                arc = OutlineArc(novel_id=uuid.UUID(request.novel_id), status="draft")
                meta = self._new_asset_meta(
                    task_id=task_id,
                    context_fingerprint=context_fingerprint,
                    story_outline_revision_id=story_outline_revision_id,
                    adopted_at=adopted_at,
                )
                db.add(arc)
            self._assign_arc(arc, draft, reference_map)
            meta["p20_basis"] = draft.basis
            meta["p20_uncertain_fields"] = list(draft.uncertain_fields)
            meta["p20_confidence"] = draft.confidence
            arc.provenance_meta = meta
            await db.flush()
            refs.append({"type": "outline_arc", "id": str(arc.id)})
        return refs

    async def _apply_scenes(
        self,
        db: AsyncSession,
        *,
        request: OutlineLayerGenerateRequest,
        output: P20PlannedSceneOutput,
        reference_map: dict[str, dict[str, str]],
        task_id: str,
        context_fingerprint: str,
        story_outline_revision_id: str,
        adopted_at: str,
    ) -> list[dict[str, str]]:
        refs: list[dict[str, str]] = []
        next_index = int(
            await db.scalar(
                select(func.max(Scene.scene_index)).where(
                    Scene.novel_id == uuid.UUID(request.novel_id)
                )
            )
            or -1
        ) + 1
        for draft in output.scenes:
            if request.mode == "revise":
                scene_id = uuid.UUID(reference_map["scenes"][draft.target_scene_ref])
                scene = await db.scalar(
                    select(Scene).where(
                        Scene.id == scene_id,
                        Scene.novel_id == uuid.UUID(request.novel_id),
                    )
                )
                if scene is None:
                    raise P20ConflictError("selected Scene no longer exists")
                original_chunks = list(scene.scene_chunks or [])
                original_chapter_ids = list(scene.chapter_ids or [])
                meta = self._revision_meta(
                    scene.structure_meta,
                    before=self._scene_snapshot(scene),
                    task_id=task_id,
                    context_fingerprint=context_fingerprint,
                    story_outline_revision_id=story_outline_revision_id,
                    adopted_at=adopted_at,
                )
                planning_state = (
                    "materialized"
                    if original_chunks or original_chapter_ids
                    else str(meta.get("planning_state") or "planned")
                )
            else:
                scene = Scene(
                    novel_id=uuid.UUID(request.novel_id),
                    scene_index=next_index,
                    source="ai_generated",
                    scene_chunks=[],
                    chapter_ids=[],
                    status="draft",
                )
                next_index += 1
                original_chunks = []
                original_chapter_ids = []
                planning_state = "planned"
                meta = self._new_asset_meta(
                    task_id=task_id,
                    context_fingerprint=context_fingerprint,
                    story_outline_revision_id=story_outline_revision_id,
                    adopted_at=adopted_at,
                )
                db.add(scene)
            self._assign_scene(scene, draft, reference_map)
            scene.scene_chunks = original_chunks
            scene.chapter_ids = original_chapter_ids
            meta.update(
                {
                    "semantic_origin": "p20_planned_scene",
                    "planning_state": planning_state,
                    "planned_chapter_range": {
                        "start": draft.planned_start_chapter,
                        "end": draft.planned_end_chapter,
                    },
                    "parent_outline_arc_id": self._resolve_optional(
                        draft.parent_arc_ref,
                        reference_map.get("arcs", {}),
                    ),
                    "related_thread_ids": self._resolve_many(
                        draft.related_thread_refs,
                        reference_map.get("threads", {}),
                    ),
                    "related_character_ids": self._resolve_many(
                        draft.related_character_refs,
                        reference_map.get("characters", {}),
                    ),
                    "related_entity_ids": self._resolve_many(
                        draft.related_entity_refs,
                        reference_map.get("entities", {}),
                    ),
                    "semantic_field_statuses": draft.semantic_field_statuses(),
                    "core_conflict_status": draft.core_conflict_status,
                    "narrative_function": draft.narrative_function,
                    "p20_basis": draft.basis,
                    "p20_uncertain_fields": list(draft.uncertain_fields),
                    "p20_confidence": draft.confidence,
                    "needs_review": bool(draft.uncertain_fields),
                }
            )
            scene.structure_meta = meta
            await db.flush()
            refs.append({"type": "scene", "id": str(scene.id)})
        return refs

    async def _project_information_movements(
        self,
        db: AsyncSession,
        *,
        request: OutlineLayerGenerateRequest,
        thread: PlotThread,
        draft: P20ThreadDraft,
        reference_map: dict[str, dict[str, str]],
        task_id: str,
        context_fingerprint: str,
        story_outline_revision_id: str,
        adopted_at: str,
    ) -> list[dict[str, str]]:
        refs: list[dict[str, str]] = []
        desired_foreshadow_ids: set[str] = set()
        desired_reveal_ids: set[str] = set()
        for movement in draft.information_movements:
            movement_id = self._information_movement_id(thread.id, movement.movement_ref)
            if any(
                node.kind in {"seed", "reinforce", "payoff"}
                for node in movement.nodes
            ):
                desired_foreshadow_ids.add(movement_id)
            if (
                movement.target_ref
                and movement.hidden_content
                and any(
                    node.kind in {"partial_reveal", "full_reveal"}
                    for node in movement.nodes
                )
            ):
                desired_reveal_ids.add(movement_id)
        await self._retire_stale_information_projections(
            db,
            novel_id=request.novel_id,
            thread=thread,
            desired_foreshadow_ids=desired_foreshadow_ids,
            desired_reveal_ids=desired_reveal_ids,
            task_id=task_id,
            adopted_at=adopted_at,
        )
        for movement in draft.information_movements:
            movement_id = self._information_movement_id(
                thread.id,
                movement.movement_ref,
            )
            foreshadow_nodes = [
                node
                for node in movement.nodes
                if node.kind in {"seed", "reinforce", "payoff"}
            ]
            reveal_nodes = [
                node
                for node in movement.nodes
                if node.kind in {"partial_reveal", "full_reveal"}
            ]
            common_meta = {
                **self._new_asset_meta(
                    task_id=task_id,
                    context_fingerprint=context_fingerprint,
                    story_outline_revision_id=story_outline_revision_id,
                    adopted_at=adopted_at,
                ),
                "information_movement_id": movement_id,
                "information_movement_ref": movement.movement_ref,
                "projection_owner_thread_id": str(thread.id),
                "p20_basis": movement.basis,
                "p20_uncertain_fields": list(movement.uncertain_fields),
                "p20_confidence": movement.confidence,
            }
            projection_warnings = []
            if reveal_nodes and not movement.target_ref:
                projection_warnings.append("reveal_target_unresolved")
            if reveal_nodes and not movement.hidden_content:
                projection_warnings.append("reveal_hidden_content_unresolved")
            if projection_warnings:
                common_meta.update(
                    {
                        "needs_review": True,
                        "projection_warnings": projection_warnings,
                    }
                )
            if foreshadow_nodes:
                plan = await self._find_projection(
                    db,
                    ForeshadowingPlan,
                    request.novel_id,
                    movement_id,
                )
                if plan is None:
                    plan = ForeshadowingPlan(
                        novel_id=uuid.UUID(request.novel_id),
                        status="draft",
                    )
                    db.add(plan)
                elif plan.status == "deprecated":
                    plan.status = "draft"
                plan.name = movement.information_subject[:255]
                plan.summary = movement.hidden_content
                plan.surface_meaning = movement.surface_understanding
                plan.hidden_meaning = movement.hidden_content
                plan.planned_seed_chapter = self._first_chapter(
                    foreshadow_nodes,
                    "seed",
                )
                plan.planned_reinforce_chapters = [
                    node.chapter_hint
                    for node in foreshadow_nodes
                    if node.kind == "reinforce" and node.chapter_hint is not None
                ]
                plan.planned_payoff_chapter = self._first_chapter(
                    foreshadow_nodes,
                    "payoff",
                )
                plan.related_entity_ids = (
                    [self._target_id(movement, reference_map)]
                    if movement.target_ref
                    else []
                )
                plan.related_thread_ids = [str(thread.id)]
                plan.provenance_meta = common_meta
                await db.flush()
                refs.append({"type": "foreshadowing_plan", "id": str(plan.id)})
            if reveal_nodes:
                if not movement.target_ref or not movement.hidden_content:
                    # Keep the author's information movement on the PlotThread,
                    # but do not manufacture a RevealPlan target or secret. A
                    # later edit can resolve the missing field and project it.
                    continue
                target_id = self._target_id(movement, reference_map)
                target_type = (
                    "character"
                    if movement.target_ref in reference_map.get("characters", {})
                    else "world_entity"
                )
                plan = await self._find_projection(
                    db,
                    RevealPlan,
                    request.novel_id,
                    movement_id,
                )
                if plan is None:
                    plan = RevealPlan(
                        novel_id=uuid.UUID(request.novel_id),
                        status="draft",
                    )
                    db.add(plan)
                elif plan.status == "deprecated":
                    plan.status = "draft"
                plan.target_type = target_type
                plan.target_id = uuid.UUID(target_id)
                plan.secret_summary = movement.hidden_content
                plan.reveal_stages = [
                    {
                        "stage_index": index,
                        "chapter_index": node.chapter_hint,
                        "reveal_content": node.content,
                        "trigger": node.trigger,
                        "effect": node.effect,
                        "reveal_level": (
                            "partial" if node.kind == "partial_reveal" else "full"
                        ),
                    }
                    for index, node in enumerate(reveal_nodes)
                    if node.chapter_hint is not None
                ]
                unresolved_reveal_nodes = sum(
                    node.chapter_hint is None for node in reveal_nodes
                )
                plan_meta = dict(common_meta)
                if unresolved_reveal_nodes:
                    plan_meta.update(
                        {
                            "needs_review": True,
                            "projection_warning": "reveal_node_missing_chapter_hint",
                            "unresolved_reveal_node_count": unresolved_reveal_nodes,
                        }
                    )
                plan.related_thread_ids = [str(thread.id)]
                plan.provenance_meta = plan_meta
                await db.flush()
                refs.append({"type": "reveal_plan", "id": str(plan.id)})
        return refs

    @staticmethod
    def _information_movement_id(thread_id: uuid.UUID, movement_ref: str) -> str:
        return str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"outline-information:{thread_id}:{movement_ref}",
            )
        )

    @staticmethod
    async def _retire_stale_information_projections(
        db: AsyncSession,
        *,
        novel_id: str,
        thread: PlotThread,
        desired_foreshadow_ids: set[str],
        desired_reveal_ids: set[str],
        task_id: str,
        adopted_at: str,
    ) -> None:
        thread_id = str(thread.id)
        desired_by_model = (
            (ForeshadowingPlan, desired_foreshadow_ids),
            (RevealPlan, desired_reveal_ids),
        )
        for model, desired_ids in desired_by_model:
            plans = list(
                (
                    await db.scalars(
                        select(model).where(
                            model.novel_id == uuid.UUID(novel_id),
                        )
                    )
                ).all()
            )
            for plan in plans:
                meta = dict(plan.provenance_meta or {})
                if meta.get("projection_owner_thread_id") != thread_id:
                    continue
                movement_id = str(meta.get("information_movement_id") or "")
                if movement_id in desired_ids:
                    continue
                remaining_thread_ids = [
                    str(value)
                    for value in (plan.related_thread_ids or [])
                    if str(value) != thread_id
                ]
                plan.related_thread_ids = remaining_thread_ids
                meta["projection_retired"] = {
                    "task_id": task_id,
                    "adopted_at": adopted_at,
                    "reason": (
                        "information_movement_removed_or_projection_no_longer_valid"
                    ),
                    "previous_status": plan.status,
                }
                if remaining_thread_ids:
                    meta["projection_owner_thread_id"] = None
                else:
                    plan.status = "deprecated"
                plan.provenance_meta = meta

    @staticmethod
    async def _find_projection(
        db: AsyncSession,
        model: type[ForeshadowingPlan] | type[RevealPlan],
        novel_id: str,
        movement_id: str,
    ) -> ForeshadowingPlan | RevealPlan | None:
        rows = list(
            (
                await db.scalars(
                    select(model).where(model.novel_id == uuid.UUID(novel_id))
                )
            ).all()
        )
        return next(
            (
                item
                for item in rows
                if dict(item.provenance_meta or {}).get("information_movement_id")
                == movement_id
            ),
            None,
        )

    @staticmethod
    def _assign_thread(
        thread: PlotThread,
        draft: P20ThreadDraft,
        refs: dict[str, dict[str, str]],
    ) -> None:
        thread.name = draft.name
        thread.thread_type = draft.thread_type[:32]
        thread.summary = draft.summary
        thread.visible_goal = draft.visible_goal
        thread.hidden_truth = draft.hidden_truth
        thread.start_chapter = draft.start_chapter
        thread.planned_payoff_chapter = draft.planned_payoff_chapter
        thread.current_stage = draft.current_stage[:32] if draft.current_stage else None
        thread.related_character_ids = P20ApplyService._resolve_many(
            draft.related_character_refs,
            refs.get("characters", {}),
        )
        thread.related_entity_ids = P20ApplyService._resolve_many(
            draft.related_entity_refs,
            refs.get("entities", {}),
        )
        thread.reader_known_state = draft.reader_known_state
        thread.author_known_state = draft.author_known_state

    @staticmethod
    def _assign_arc(
        arc: OutlineArc,
        draft: P20ArcDraft,
        refs: dict[str, dict[str, str]],
    ) -> None:
        arc.title = draft.title
        arc.arc_index = draft.arc_index
        arc.start_chapter = draft.start_chapter
        arc.end_chapter = draft.end_chapter
        arc.arc_goal = draft.arc_goal
        arc.core_conflict = draft.core_conflict
        arc.main_opposition = draft.main_opposition
        arc.entry_hook = draft.entry_hook
        arc.midpoint_turn = draft.midpoint_turn
        arc.climax = draft.climax
        arc.result = draft.result_state
        arc.next_hook = draft.next_hook
        arc.related_thread_ids = P20ApplyService._resolve_many(
            draft.related_thread_refs,
            refs.get("threads", {}),
        )
        arc.related_character_ids = P20ApplyService._resolve_many(
            draft.related_character_refs,
            refs.get("characters", {}),
        )
        arc.related_entity_ids = P20ApplyService._resolve_many(
            draft.related_entity_refs,
            refs.get("entities", {}),
        )

    @staticmethod
    def _assign_scene(
        scene: Scene,
        draft: P20SceneDraft,
        refs: dict[str, dict[str, str]],
    ) -> None:
        scene.title = draft.title
        scene.goal = draft.goal
        scene.core_conflict = draft.core_conflict
        scene.emotional_beat = draft.emotional_beat
        scene.must_happen = draft.must_happen
        scene.must_not_happen = draft.must_not_happen
        scene.narrative_tag = draft.narrative_tag
        scene.pov_character_id = P20ApplyService._resolve_optional(
            draft.pov_character_ref,
            refs.get("characters", {}),
        )

    @staticmethod
    def _resolve_many(values: list[str], mapping: dict[str, str]) -> list[str]:
        return [mapping[value] for value in values]

    @staticmethod
    def _resolve_optional(value: str | None, mapping: dict[str, str]) -> str | None:
        return mapping[value] if value is not None else None

    @staticmethod
    def _target_id(
        movement: P20InformationMovement,
        refs: dict[str, dict[str, str]],
    ) -> str:
        assert movement.target_ref is not None
        return (
            refs.get("characters", {}).get(movement.target_ref)
            or refs.get("entities", {})[movement.target_ref]
        )

    @staticmethod
    def _first_chapter(nodes: list[Any], kind: str) -> int | None:
        return next(
            (
                node.chapter_hint
                for node in nodes
                if node.kind == kind and node.chapter_hint is not None
            ),
            None,
        )

    @staticmethod
    def _new_asset_meta(
        *,
        task_id: str,
        context_fingerprint: str,
        story_outline_revision_id: str,
        adopted_at: str,
    ) -> dict[str, Any]:
        return {
            "source": "ai_generated",
            "adopted_at": adopted_at,
            "adopted_from_preview_task_id": task_id,
            "context_fingerprint": context_fingerprint,
            "story_outline_revision_id": story_outline_revision_id,
            "ai_revision_history": [],
        }

    @classmethod
    def _revision_meta(
        cls,
        current: dict[str, Any] | None,
        *,
        before: dict[str, Any],
        task_id: str,
        context_fingerprint: str,
        story_outline_revision_id: str,
        adopted_at: str,
    ) -> dict[str, Any]:
        meta = dict(current or {})
        history = list(meta.get("ai_revision_history") or [])
        history.append(
            {
                "before": before,
                "source_task_id": task_id,
                "context_fingerprint": context_fingerprint,
                "story_outline_revision_id": story_outline_revision_id,
                "adopted_at": adopted_at,
            }
        )
        meta["ai_revision_history"] = history
        meta["last_ai_revision"] = {
            "source_task_id": task_id,
            "context_fingerprint": context_fingerprint,
            "story_outline_revision_id": story_outline_revision_id,
            "adopted_at": adopted_at,
        }
        return meta

    @staticmethod
    def _thread_snapshot(item: PlotThread) -> dict[str, Any]:
        return {
            key: getattr(item, key)
            for key in (
                "name",
                "thread_type",
                "summary",
                "visible_goal",
                "hidden_truth",
                "start_chapter",
                "planned_payoff_chapter",
                "current_stage",
                "related_character_ids",
                "related_entity_ids",
                "related_memory_ids",
                "reader_known_state",
                "author_known_state",
                "status",
            )
        }

    @staticmethod
    def _arc_snapshot(item: OutlineArc) -> dict[str, Any]:
        return {
            key: getattr(item, key)
            for key in (
                "title",
                "arc_index",
                "start_chapter",
                "end_chapter",
                "arc_goal",
                "core_conflict",
                "main_opposition",
                "entry_hook",
                "midpoint_turn",
                "climax",
                "result",
                "next_hook",
                "related_thread_ids",
                "related_character_ids",
                "related_entity_ids",
                "status",
            )
        }

    @staticmethod
    def _scene_snapshot(item: Scene) -> dict[str, Any]:
        return {
            key: getattr(item, key)
            for key in (
                "title",
                "goal",
                "core_conflict",
                "emotional_beat",
                "must_happen",
                "must_not_happen",
                "narrative_tag",
                "pov_character_id",
                "scene_chunks",
                "chapter_ids",
                "status",
            )
        }
