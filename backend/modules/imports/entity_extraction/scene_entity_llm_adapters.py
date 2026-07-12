"""LLM adapters for Phase 2 scene entity extraction."""

from __future__ import annotations

from typing import Any

from modules.imports.llm_schemas import (
    AliasRelationExtractionOutput,
    SceneEntityExtractionOutput,
)


async def call_llm_extraction(
    chapters_text: str,
    existing_context: str,
    memory_context: str,
    *,
    max_tokens: int = 32_768,
    client_timeout: int = 180,
    max_fix_attempts: int = 1,
    transport_retries: bool = True,
    diagnostics: list[dict[str, Any]] | None = None,
) -> SceneEntityExtractionOutput:
    from infrastructure.llm.agent_step_harness import run_managed_structured
    from infrastructure.llm.prompt_loader import load_prompt
    from infrastructure.llm.schemas import LLMCallRequest, LLMMessage

    system_prompt = load_prompt(
        "scene_entity_extraction",
        existing_entities_context=existing_context,
    )
    system_prompt += f"\n\n## 前序上下文\n\n{memory_context}"

    from modules.imports.entity_extraction.scene_entity_config import (
        current_phase2_high_quality,
        current_phase2_novel_id,
        current_phase2_project_settings,
        current_phase2_request_model,
    )

    project_settings = current_phase2_project_settings()
    if project_settings is None:
        raise RuntimeError("Phase 2 project LLM settings context is required")
    from modules.project.facade import create_project_snapshot_llm_client

    llm_client = create_project_snapshot_llm_client(
        project_settings,
        timeout_override=client_timeout,
        novel_id=current_phase2_novel_id(),
    )
    request_model = current_phase2_request_model() or llm_client.model_name
    request_extra = _reasoning_extra(
        llm_client,
        high_quality=current_phase2_high_quality(),
        request_model=request_model,
    )
    request = LLMCallRequest(
        model=request_model,
        messages=[
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(
                role="user",
                content=(
                    "请从以下正文中提取世界对象。优先保证长期资产召回完整："
                    "人物、地点、组织/势力、关键物品/文本、概念/规则/力量、"
                    "事件/秘密都要分别检查；同一对象用 aliases 或 "
                    "link_to_existing 表达，不要拆成重复对象。"
                    "每个对象和关系必须提供可在当前 Scene 逐字定位的 quote。\n\n"
                    f"{chapters_text}"
                ),
            ),
        ],
        temperature=0.3,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
        extra=request_extra,
    )

    try:
        return await run_managed_structured(
            llm_client,
            request,
            SceneEntityExtractionOutput,
            step_name="imports.scene_entity.extraction.structured",
            max_fix_attempts=max_fix_attempts,
            transport_retries=transport_retries,
            partial_list_fields={"entities", "relations", "delta_events"},
            diagnostics=diagnostics,
            format_repair_attempts=1,
            fix_prompt=(
                "上一轮实体抽取输出不是合法 JSON 或不符合 schema。"
                "请重新输出一个完整 JSON 对象，只包含 entities、relations、"
                "delta_events、memory_update，不要 Markdown 或解释。"
            ),
        )
    finally:
        await llm_client.close()


async def call_alias_relation_extraction(
    chapters_text: str,
    entity_index: str,
    *,
    max_tokens: int = 32_768,
    client_timeout: int = 120,
    max_fix_attempts: int = 0,
    diagnostics: list[dict[str, Any]] | None = None,
) -> AliasRelationExtractionOutput:
    from infrastructure.llm.agent_step_harness import run_managed_structured
    from infrastructure.llm.prompt_loader import load_prompt
    from infrastructure.llm.schemas import LLMCallRequest, LLMMessage

    system_prompt = load_prompt(
        "alias_relation_extraction",
        entity_index=entity_index,
    )
    from modules.imports.entity_extraction.scene_entity_config import (
        current_phase2_high_quality,
        current_phase2_novel_id,
        current_phase2_project_settings,
        current_phase2_request_model,
    )

    project_settings = current_phase2_project_settings()
    if project_settings is None:
        raise RuntimeError("Phase 2 project LLM settings context is required")
    from modules.project.facade import create_project_snapshot_llm_client

    llm_client = create_project_snapshot_llm_client(
        project_settings,
        timeout_override=client_timeout,
        novel_id=current_phase2_novel_id(),
    )
    request_model = current_phase2_request_model() or llm_client.model_name
    request_extra = _reasoning_extra(
        llm_client,
        high_quality=current_phase2_high_quality(),
        request_model=request_model,
    )
    request = LLMCallRequest(
        model=request_model,
        messages=[
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(
                role="user",
                content=(
                    "请只基于下列 Scene 正文和对象索引提取别名与对象关系。"
                    "不要创建新对象；无法在索引中定位两端对象时跳过。"
                    "最多输出 8 个 aliases、12 个 relations；quote 和 "
                    "description 必须短。只输出 JSON。\n\n"
                    f"{chapters_text}"
                ),
            ),
        ],
        temperature=0.2,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
        extra=request_extra,
    )
    try:
        return await run_managed_structured(
            llm_client,
            request,
            AliasRelationExtractionOutput,
            step_name="imports.scene_entity.alias_relation.structured",
            max_fix_attempts=max_fix_attempts,
            transport_retries=True,
            partial_list_fields={"aliases", "relations"},
            diagnostics=diagnostics,
            format_repair_attempts=1,
            fix_prompt=(
                "上一轮别名/关系抽取输出不是合法 JSON 或不符合 schema。"
                "请重新输出一个完整 JSON 对象，只包含 aliases 和 relations，"
                "不要 Markdown 或解释。"
            ),
        )
    finally:
        await llm_client.close()


def _reasoning_extra(
    llm_client: Any,
    *,
    high_quality: bool,
    request_model: str | None = None,
) -> dict[str, Any]:
    summary = getattr(llm_client, "profile_summary", {})
    if callable(summary):
        summary = summary()
    if not isinstance(summary, dict):
        summary = {}
    provider_id = str(summary.get("provider_id") or "")
    model = str(request_model or getattr(llm_client, "model_name", "") or "")
    if provider_id != "deepseek" and not model.startswith("deepseek"):
        return {}
    return {
        "thinking": {"type": "enabled"},
        "reasoning_effort": "max" if high_quality else "high",
    }
