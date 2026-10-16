"""Assistant 操作注册表装配件（AO-5 第二批 / ADR-0031）。

领域插件文件只导出纯数据 ``OPERATIONS_SPEC``（label/schema/prepare/apply 及
可选 permission/read_result/revision），不再 import ``modules.assistant``；
只有本装配件（仅被组合根 ``app/bootstrap.py`` 导入）依赖
``modules.assistant.contracts.AssistantOperation`` 并按原构造语义物化注册表，
容器注册仍只在组合根完成。操作名、参数 schema、目标函数与权限逐字段等于
装配位置移动前的产物，assistant 消费侧零改动。
"""

from dataclasses import replace
from time import monotonic
from uuid import NAMESPACE_URL, uuid5

from app.assistant_operation_metadata import OPERATION_METADATA, TRACE_PARAMETER_FIELDS
from modules.assistant.contracts import AssistantOperation, AssistantOperationTraceRule
from modules.assistant.evidence_tools import fingerprint
from modules.assistant.map_spatial_advisories import (
    OPERATIONS_SPEC as _SPATIAL_ADVISORIES,
)
from modules.assistant.notice_disposition_operations import (
    OPERATIONS_SPEC as _NOTICE_DISPOSITIONS,
)
from modules.collaboration.assistant_tools import OPERATIONS_SPEC as _COLLABORATION_AUTHOR
from modules.evidence.assistant_read_operations import OPERATIONS_SPEC as _EVIDENCE_READ
from modules.evidence.compilation.assistant_dossier_tools import (
    OPERATIONS_SPEC as _EVIDENCE_OBJECT_DOSSIER,
)
from modules.evidence.forecast import OPERATIONS_SPEC as _EVIDENCE_FORECAST
from modules.evolution.assistant_tools import OPERATIONS_SPEC as _EVOLUTION
from modules.imports.assistant_tools import OPERATIONS_SPEC as _IMPORTS
from modules.interaction.author_operations import OPERATIONS_SPEC as _INTERACTION_AUTHOR
from modules.project.assistant_dedup_tool import OPERATIONS_SPEC as _PROJECT_DEDUP
from modules.project.assistant_tools import OPERATIONS_SPEC as _PROJECT
from modules.project.assistant_validity_tools import OPERATIONS_SPEC as _PROJECT_VALIDITY
from modules.story.assistant_generation_tools import (
    OPERATIONS_SPEC as _STORY_GENERATION,
)
from modules.story.assistant_information_tools import (
    OPERATIONS_SPEC as _STORY_INFORMATION,
)
from modules.story.assistant_planning_tools import OPERATIONS_SPEC as _STORY_PLANNING
from modules.story.assistant_scene_operations import OPERATIONS_SPEC as _STORY_SCENE
from modules.story.assistant_state_operations import OPERATIONS_SPEC as _STORY_STATE
from modules.story.assistant_structure_workflow import (
    OPERATIONS_SPEC as _STORY_STRUCTURE,
)
from modules.story.assistant_tools import OPERATIONS_SPEC as _STORY
from modules.story.continuity.operations import OPERATIONS_SPEC as _STORY_FACT_TIMELINE
from modules.story.character_arcs.operations import (
    OPERATIONS_SPEC as _STORY_CHARACTER_ARCS,
)
from modules.story.director_operations import OPERATIONS_SPEC as _STORY_DIRECTOR
from modules.story.world_progression_operations import (
    OPERATIONS_SPEC as _STORY_WORLD_PROGRESSION,
)
from modules.world.assistant_author_operations import OPERATIONS_SPEC as _WORLD_AUTHOR
from modules.world.assistant_cocreation_tools import OPERATIONS_SPEC as _WORLD_COCREATION
from modules.world.assistant_dossier_tools import OPERATIONS_SPEC as _WORLD_DOSSIER
from modules.world.assistant_map_tools import OPERATIONS_SPEC as _WORLD_MAP
from modules.world.assistant_opening_tools import (
    OPERATIONS_SPEC as _WORLD_OPENING,
)
from modules.world.assistant_outcome_tools import OPERATIONS_SPEC as _WORLD_OUTCOME
from modules.world.assistant_page_tools import OPERATIONS_SPEC as _WORLD_PAGE
from modules.world.assistant_review_tools import OPERATIONS_SPEC as _WORLD_REVIEW
from modules.world.assistant_tools import OPERATIONS_SPEC as _WORLD
from modules.world.assistant_validity_tools import OPERATIONS_SPEC as _WORLD_VALIDITY
from modules.world.assistant_vocabulary_tools import (
    OPERATIONS_SPEC as _WORLD_VOCABULARY,
)
from modules.writing.assistant_a1_operations import OPERATIONS_SPEC as _WRITING_A1
from modules.writing.assistant_candidate_tools import (
    OPERATIONS_SPEC as _WRITING_CANDIDATE,
)
from modules.writing.assistant_generation_tool import (
    OPERATIONS_SPEC as _WRITING_GENERATION,
)
from modules.writing.assistant_tools import OPERATIONS_SPEC as _WRITING
from modules.writing.chapter_order_operations import (
    OPERATIONS_SPEC as _WRITING_CHAPTER_ORDER,
)

_FIELDS = frozenset(AssistantOperation.__dataclass_fields__)
_CATALOG_FIELDS = frozenset(
    {
        "op_version",
        "description",
        "risk_level",
        "fee_category",
        "reversibility",
        "preconditions",
        "produces",
        "target_type",
        "ai_available",
        "transaction_mode",
        "trace_rule",
    }
)


def _materialize(specs: dict[str, dict]) -> dict[str, AssistantOperation]:
    """严格物化目录项；未知字段或缺少 v2 元数据都失败关闭。"""
    built: dict[str, AssistantOperation] = {}
    for name, spec in specs.items():
        unknown = set(spec) - _FIELDS
        if unknown:
            raise ValueError(f"操作 {name} 声明了未知字段: {sorted(unknown)}")
        metadata = dict(OPERATION_METADATA.get(name) or {})
        # Legacy plugins are being migrated incrementally, so their explicit
        # metadata remains in the adjacent legacy catalogue. New domain specs
        # carry their complete v2 declaration with the provider.
        inline_metadata = {key: spec[key] for key in _CATALOG_FIELDS if key in spec}
        if inline_metadata:
            if metadata:
                raise ValueError(f"操作 {name} 的目录元数据只能有一个声明来源")
            metadata.update(inline_metadata)
        trace_fields = TRACE_PARAMETER_FIELDS.get(name)
        if "trace_rule" not in metadata:
            raise ValueError(f"操作 {name} 缺少显式留痕参数规则")
        if trace_fields is not None:
            metadata["trace_rule"] = replace(
                metadata["trace_rule"], parameter_fields=trace_fields
            )
        values = {**metadata, **spec, "op_id": spec.get("op_id", name)}
        missing = _CATALOG_FIELDS - values.keys()
        if missing:
            raise ValueError(f"操作 {name} 缺少目录字段: {sorted(missing)}")
        if isinstance(values["trace_rule"], dict):
            try:
                values["trace_rule"] = AssistantOperationTraceRule(**values["trace_rule"])
            except TypeError as exc:
                raise ValueError(f"操作 {name} 的留痕规则无效") from exc
        operation = AssistantOperation(**values)
        _validate_catalog_entry(name, operation)
        built[name] = _instrument(operation)
    return built


def _instrument(operation: AssistantOperation) -> AssistantOperation:
    """Trace real callback calls while leaving domain specs and return values intact."""
    prepare = operation.prepare
    apply = operation.apply

    def trace_call_enabled(context) -> bool:
        from modules.assistant.operation_trace_service import (
            current_operation_trace_context,
        )

        active = current_operation_trace_context()
        return bool(
            getattr(context, "trace_enabled", False)
            or (active and active.get("operation_id") == operation.op_id)
        )

    async def record(db, novel_id, arguments, context, event_type, **kwargs):
        if context is None or not trace_call_enabled(context):
            return
        from core.container import get
        from core.service_keys import ASSISTANT_OPERATION_TRACE
        from modules.assistant.operation_trace_service import (
            current_operation_trace_context,
        )

        active = current_operation_trace_context()
        call_id = (
            (
                active.get("call_id")
                if active and active.get("operation_id") == operation.op_id
                else None
            )
            or context.trace_call_id
            or str(
                uuid5(
                    NAMESPACE_URL,
                    f"{context.run_id}:{operation.op_id}:{fingerprint(arguments)}",
                )
            )
        )
        saved = await get(ASSISTANT_OPERATION_TRACE)(
            db,
            enabled=True,
            novel_id=str(novel_id),
            owner_id=context.owner_id,
            operation=operation,
            event_type=event_type,
            arguments=arguments,
            actor_type=context.trace_actor_type,
            entrypoint=context.trace_entrypoint,
            run_id=context.run_id,
            session_id=context.trace_session_id,
            call_id=call_id,
            parent_call_id=(
                active.get("parent_call_id")
                if active and active.get("operation_id") == operation.op_id
                else context.trace_parent_call_id
            ),
            usage=context.trace_usage,
            **kwargs,
        )
        if saved is False and context.trace_status is not None:
            context.trace_status["incomplete_count"] = (
                context.trace_status.get("incomplete_count", 0) + 1
            )

    async def traced_prepare(db, novel_id, arguments, *, context=None):
        preflight = bool(
            (getattr(context, "internal_meta", None) or {}).get("confirmation_preflight")
        )
        if not trace_call_enabled(context) or preflight:
            return await prepare(db, novel_id, arguments, context=context)
        started = monotonic()
        args_json = (
            arguments.model_dump(mode="json")
            if hasattr(arguments, "model_dump")
            else arguments
        )
        if operation.permission != "read":
            await record(db, novel_id, args_json, context, "proposed")
        try:
            result = await prepare(db, novel_id, arguments, context=context)
        except Exception as error:
            await record(
                db,
                novel_id,
                args_json,
                context,
                "failed",
                error_code=getattr(error, "code", "operation_prepare_failed"),
                duration_ms=round((monotonic() - started) * 1000),
            )
            raise
        await record(
            db,
            novel_id,
            args_json,
            context,
            "executed" if operation.permission == "read" else "previewed",
            preview=result,
            duration_ms=round((monotonic() - started) * 1000),
        )
        return result

    async def traced_apply(db, novel_id, arguments, preview, *, context=None):
        if apply is None or not trace_call_enabled(context):
            if apply is None:
                return None
            return await apply(db, novel_id, arguments, preview, context=context)
        started = monotonic()
        args_json = (
            arguments.model_dump(mode="json")
            if hasattr(arguments, "model_dump")
            else arguments
        )
        try:
            result = await apply(db, novel_id, arguments, preview, context=context)
        except Exception as error:
            from modules.assistant.operation_trace_service import (
                current_operation_trace_context,
            )

            active = current_operation_trace_context()
            if (
                operation.transaction_mode == "multi_stage"
                and active
                and active.get("operation_id") == operation.op_id
            ):
                active["failure_event"] = "outcome_unknown"
                active["error_code"] = getattr(error, "code", "operation_apply_failed")
                raise
            event_type = (
                "outcome_unknown"
                if operation.transaction_mode == "multi_stage"
                else "failed"
            )
            await record(
                db,
                novel_id,
                args_json,
                context,
                event_type,
                preview=preview,
                error_code=getattr(error, "code", "operation_apply_failed"),
                duration_ms=round((monotonic() - started) * 1000),
            )
            raise
        from modules.assistant.operation_trace_service import (
            current_operation_trace_context,
        )

        active = current_operation_trace_context()
        if (
            operation.transaction_mode == "multi_stage"
            and active
            and active.get("operation_id") == operation.op_id
        ):
            active["result"] = result
            return result
        await record(
            db,
            novel_id,
            args_json,
            context,
            "executed",
            preview=preview,
            result=result,
            duration_ms=round((monotonic() - started) * 1000),
        )
        return result

    return replace(
        operation,
        prepare=traced_prepare,
        apply=traced_apply if apply is not None else None,
    )


def _validate_catalog_entry(name: str, operation: AssistantOperation) -> None:
    if operation.op_id != name:
        raise ValueError(f"操作 {name} 的 op_id 必须与目录键相同")
    if not operation.op_version or not operation.description.strip():
        raise ValueError(f"操作 {name} 缺少版本或用途说明")
    if operation.risk_level not in {"R0", "R1", "R2", "R3", "R4"}:
        raise ValueError(f"操作 {name} 的风险等级无效")
    if operation.fee_category not in {
        "free",
        "possible_model_charge",
        "possible_image_charge",
    }:
        raise ValueError(f"操作 {name} 的费用类别无效")
    if operation.transaction_mode not in {"single_transaction", "multi_stage"}:
        raise ValueError(f"操作 {name} 的事务形态无效")
    if operation.permission == "read" and operation.risk_level != "R0":
        raise ValueError(f"只读操作 {name} 必须是 R0")
    if operation.permission != "read" and operation.apply is None:
        raise ValueError(f"可执行操作 {name} 必须声明 apply")
    if operation.permission == "suggest" and operation.risk_level != "R1":
        raise ValueError(f"建议操作 {name} 必须是 R1")
    if operation.permission not in {"read", "suggest", "confirm"}:
        raise ValueError(f"操作 {name} 的权限类型无效")
    if operation.risk_level in {"R3", "R4"} and operation.permission != "confirm":
        raise ValueError(f"R3/R4 操作 {name} 必须要求作者确认")
    if not operation.ai_available:
        raise ValueError(f"AI 禁用的操作 {name} 不得进入 AI 目录")
    rule = operation.trace_rule
    if rule.parameter_fields != tuple(operation.schema.model_fields):
        raise ValueError(f"操作 {name} 的留痕字段与参数 schema 不一致")
    if rule.parameter_policy != "schema_safe":
        raise ValueError(f"操作 {name} 的参数留痕策略必须使用 schema_safe")
    if rule.mode == "coalesce":
        if not rule.window_seconds or rule.window_seconds < 1 or rule.exemption_reason:
            raise ValueError(f"操作 {name} 的合并留痕窗口无效")
    elif rule.mode == "exempt":
        if not rule.exemption_reason or rule.window_seconds is not None:
            raise ValueError(f"操作 {name} 的留痕豁免必须说明理由")
    elif rule.mode != "per_call" or rule.window_seconds or rule.exemption_reason:
        raise ValueError(f"操作 {name} 的逐次留痕规则无效")


# 逐项物化；bootstrap 按与改造前完全相同的合并顺序取用。
project_dedup_operations = _materialize(_PROJECT_DEDUP)
story_information_operations = _materialize(_STORY_INFORMATION)
writing_operations = _materialize(_WRITING)
writing_generation_operations = _materialize(_WRITING_GENERATION)
writing_candidate_operations = _materialize(_WRITING_CANDIDATE)
project_operations = _materialize(_PROJECT)
project_validity_operations = _materialize(_PROJECT_VALIDITY)
story_operations = _materialize(_STORY)
story_structure_operations = _materialize(_STORY_STRUCTURE)
story_planning_operations = _materialize(_STORY_PLANNING)
story_scene_operations = _materialize(_STORY_SCENE)
story_state_operations = _materialize(_STORY_STATE)
story_director_operations = _materialize(_STORY_DIRECTOR)
story_world_progression_operations = _materialize(_STORY_WORLD_PROGRESSION)
story_fact_timeline_operations = _materialize(_STORY_FACT_TIMELINE)
story_character_arc_operations = _materialize(_STORY_CHARACTER_ARCS)
story_generation_operations = _materialize(_STORY_GENERATION)
world_opening_operations = _materialize(_WORLD_OPENING)
world_map_operations = _materialize(_WORLD_MAP)
world_vocabulary_operations = _materialize(_WORLD_VOCABULARY)
world_validity_operations = _materialize(_WORLD_VALIDITY)
evidence_forecast_operations = _materialize(_EVIDENCE_FORECAST)
evidence_read_operations = _materialize(_EVIDENCE_READ)
evidence_object_dossier_operations = _materialize(_EVIDENCE_OBJECT_DOSSIER)

evolution_operations = _materialize(_EVOLUTION)
imports_operations = _materialize(_IMPORTS)
world_operations = _materialize(_WORLD)
world_author_operations = _materialize(_WORLD_AUTHOR)
world_page_operations = _materialize(_WORLD_PAGE)
world_outcome_operations = _materialize(_WORLD_OUTCOME)
world_cocreation_operations = _materialize(_WORLD_COCREATION)
world_review_operations = _materialize(_WORLD_REVIEW)
world_dossier_operations = _materialize(_WORLD_DOSSIER)

assistant_spatial_advisory_operations = _materialize(_SPATIAL_ADVISORIES)
assistant_notice_operations = _materialize(_NOTICE_DISPOSITIONS)
writing_a1_operations = _materialize(_WRITING_A1)
writing_chapter_order_operations = _materialize(_WRITING_CHAPTER_ORDER)
interaction_author_operations = _materialize(_INTERACTION_AUTHOR)
collaboration_author_operations = _materialize(_COLLABORATION_AUTHOR)
