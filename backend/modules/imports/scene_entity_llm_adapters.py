"""LLM adapters for Phase 2 scene entity extraction."""

from __future__ import annotations

from modules.imports.llm_schemas import (
    AliasRelationExtractionOutput,
    SceneEntityExtractionOutput,
)


async def call_llm_extraction(
    chapters_text: str,
    existing_context: str,
    memory_context: str,
    *,
    max_tokens: int = 8192,
    client_timeout: int = 180,
    max_fix_attempts: int = 1,
    transport_retries: bool = True,
) -> SceneEntityExtractionOutput:
    from core.config import get_settings
    from infrastructure.llm.client import LLMClient
    from infrastructure.llm.prompt_loader import load_prompt
    from infrastructure.llm.schemas import LLMCallRequest, LLMMessage

    system_prompt = load_prompt(
        "scene_entity_extraction",
        existing_entities_context=existing_context,
    )
    system_prompt += f"\n\n## 前序上下文\n\n{memory_context}"

    settings = get_settings()
    request = LLMCallRequest(
        model=settings.llm_model,
        messages=[
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(
                role="user",
                content=(
                    "请从以下正文中提取世界对象。优先保证长期资产召回完整："
                    "人物、地点、组织/势力、关键物品/文本、概念/规则/力量、"
                    "事件/秘密都要分别检查；同一对象用 aliases 或 "
                    "link_to_existing 表达，不要拆成重复对象。\n\n"
                    f"{chapters_text}"
                ),
            ),
        ],
        temperature=0.3,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )

    llm_client = LLMClient(timeout=client_timeout)
    return await llm_client.generate_structured(
        request,
        SceneEntityExtractionOutput,
        max_fix_attempts=max_fix_attempts,
        transport_retries=transport_retries,
        fix_prompt=(
            "上一轮实体抽取输出不是合法 JSON 或不符合 schema。"
            "请重新输出一个完整 JSON 对象，只包含 entities、relations、"
            "delta_events、memory_update，不要 Markdown 或解释。"
        ),
    )

async def call_alias_relation_extraction(
    chapters_text: str,
    entity_index: str,
    *,
    max_tokens: int = 4096,
    client_timeout: int = 120,
) -> AliasRelationExtractionOutput:
    from core.config import get_settings
    from infrastructure.llm.client import LLMClient
    from infrastructure.llm.prompt_loader import load_prompt
    from infrastructure.llm.schemas import LLMCallRequest, LLMMessage

    system_prompt = load_prompt(
        "alias_relation_extraction",
        entity_index=entity_index,
    )
    settings = get_settings()
    request = LLMCallRequest(
        model=settings.llm_model,
        messages=[
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(
                role="user",
                content=(
                    "请只基于下列 Scene 正文和对象索引提取别名与对象关系。"
                    "不要创建新对象；无法在索引中定位两端对象时跳过。\n\n"
                    f"{chapters_text}"
                ),
            ),
        ],
        temperature=0.2,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )
    llm_client = LLMClient(timeout=client_timeout)
    return await llm_client.generate_structured(
        request,
        AliasRelationExtractionOutput,
        max_fix_attempts=1,
        transport_retries=True,
        fix_prompt=(
            "上一轮别名/关系抽取输出不是合法 JSON 或不符合 schema。"
            "请重新输出一个完整 JSON 对象，只包含 aliases 和 relations，"
            "不要 Markdown 或解释。"
        ),
    )

