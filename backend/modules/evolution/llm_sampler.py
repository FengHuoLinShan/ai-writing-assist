"""生产 LLM 采样器：经项目 LLM 入口的 schema 化观察（V4 E09 第一步）。

边界（与仓库 LLM 规则一致）：

- 客户端只经 ``modules.project.facade.open_project_llm_client`` 获取——
  provider/model/Key 来自项目 owner 的账户连接；本模块不碰环境变量、
  不缓存凭据、不在数据库事务内做 provider I/O（pipeline 在采样前已
  commit 边界由调用方事务控制）。
- 输出是 Pydantic schema 化的窄观察（modality 七态、提及显式、引用
  必须来自原文）；schema 校验失败即失败，不猜测修复。
- 计量：每次实际调用记录 provider/model/usage 进入冻结负载与回执的
  ``paid_call_receipts``——预算预留（T21）在采样前完成，费用事后可审计。
- Prompt 必须携带前序已提交回执身份（T07：后一 Scene 的输入实际包含
  前一 Scene 的已提交理解），以确定性文本注入，不靠模型记忆。

真实模型验收单独请授权执行；本模块的单元验证用冻结 fixture 客户端
（不联网、逐字节固定响应）。
"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from infrastructure.llm.schemas import LLMCallRequest, LLMMessage


class SamplerMention(BaseModel):
    """模型输出的提及：禁止编造实体 UUID，未解析即留表面名。"""

    model_config = ConfigDict(extra="forbid")

    surface: str = Field(min_length=1, max_length=200)
    entity_type: str | None = Field(default=None, max_length=32)


class SamplerObservation(BaseModel):
    """一条窄观察：谓词 + modality + 原文引用（不得虚构引用）。"""

    model_config = ConfigDict(extra="forbid")

    predicate: str = Field(min_length=1, max_length=2000)
    modality: str = Field(
        default="event_observed",
        pattern=(
            "^(event_observed|character_statement|belief|hypothesis|"
            "author_plan|figurative|unclear)$"
        ),
    )
    quote: str = Field(min_length=1, max_length=2000)
    mentions: list[SamplerMention] = Field(default_factory=list, max_length=32)


class SamplerSceneEvent(BaseModel):
    """模型提议的场景事件（仍走 E03b producer 分区与校验）。"""

    model_config = ConfigDict(extra="forbid")

    dimension: str = Field(
        pattern="^(entities|relations|locations|knowledge|timeline|causality)$"
    )
    event_type: str = Field(min_length=1, max_length=64)
    entity_id: str | None = None
    snapshot_after: dict[str, Any] = Field(default_factory=dict)


class SceneSample(BaseModel):
    """一次场景步的 schema 化采样结果。"""

    model_config = ConfigDict(extra="forbid")

    observations: list[SamplerObservation] = Field(default_factory=list, max_length=64)
    scene_events: list[SamplerSceneEvent] = Field(default_factory=list, max_length=200)
    unresolved_parts: list[str] = Field(default_factory=list, max_length=32)


SYSTEM_PROMPT = (
    "你是小说理解引擎的窄任务观察者。只依据给定正文与给定前序理解，"
    "输出结构化观察：逐字引用必须来自本段正文；无法确定 modality 时用 "
    "unclear；提及只给表面名与类型，绝不编造实体 ID；不确定的内容放进 "
    "unresolved_parts，不要猜测。"
)


def build_scene_messages(
    *,
    scene_text: str,
    input_manifest: dict[str, Any],
) -> list[LLMMessage]:
    """确定性 Prompt：正文 + 前序已提交回执身份与**实际状态内容**（T07）。

    前序理解不只传回执 ID——前序观察的有界摘要（谓词列表）一并注入，
    让模型拿到真实理解内容，而不是靠身份引用冒充上下文（返修 R3）。
    """
    previous = input_manifest.get("previous_scene_attempt_id")
    previous_prefix = input_manifest.get("previous_committed_prefix")
    prior_observations = input_manifest.get("previous_observations") or []
    context_lines = [f"【Scene {input_manifest.get('scene_index', 0)} 正文】", scene_text]
    if previous:
        context_lines.append(
            "【前序已提交理解（回执身份）】"
            f"attempt_id={previous}；committed_prefix={previous_prefix}"
        )
        if prior_observations:
            context_lines.append("【前序已确认的观察（有界摘要）】")
            context_lines.extend(f"- {line}" for line in prior_observations)
    else:
        context_lines.append("【前序已提交理解】无（本 Scene 为链头）")
    return [
        LLMMessage(role="system", content=SYSTEM_PROMPT),
        LLMMessage(role="user", content="\n".join(context_lines)),
    ]


class _StructuredClient(Protocol):
    async def generate_structured(self, request: LLMCallRequest, schema: type): ...


class ProjectLLMSampler:
    """经项目 LLM 入口的场景采样器（E09 生产路径）。

    客户端由调用方经 async context manager 持有（见 sampler.py 工厂）；
    采样器本身不负责客户端生命周期。
    """

    def __init__(self, client: _StructuredClient) -> None:
        self._client = client
        self.last_call_receipt: dict[str, Any] | None = None

    async def sample(
        self, *, scene_text: str, input_manifest: dict[str, Any]
    ) -> dict[str, Any]:
        request = LLMCallRequest(
            messages=build_scene_messages(
                scene_text=scene_text, input_manifest=input_manifest
            ),
            temperature=0.2,
        )
        diagnostics: list[dict[str, Any]] = []
        result: SceneSample = await self._client.generate_structured(
            request, SceneSample, diagnostics=diagnostics
        )
        # 结构化修复的每次请求都已实际发生（解析/schema 失败的响应同样
        # 可能已计费）：回执保留全部请求明细与状态，用量跨全部尝试累计，
        # 未知用量保持 None 而不当零（PR160-162 审查 F3）。
        attempts = [
            item for item in diagnostics if item.get("kind") == "structured_usage"
        ]

        def _known_total(field: str) -> int | None:
            known = [
                item[field]
                for item in attempts
                if isinstance(item.get(field), int)
            ]
            return sum(known) if known else None

        receipt = {
            "provider": getattr(self._client, "provider_id", None) or "project_llm",
            "model": getattr(self._client, "model", None)
            or getattr(self._client, "model_id", None),
            "schema": "evolution.scene_sample.v1",
            "usage": {
                "prompt_tokens": _known_total("prompt_tokens"),
                "completion_tokens": _known_total("completion_tokens"),
                "total_tokens": _known_total("total_tokens"),
                "attempts": len(attempts),
                "succeeded_attempts": sum(
                    1 for item in attempts if item.get("status") == "succeeded"
                ),
            }
            if attempts
            else None,
            "attempts_detail": [
                {
                    "attempt": item.get("attempt"),
                    "status": item.get("status"),
                    "completion_tokens": item.get("completion_tokens"),
                    **(
                        {"error_kind": item["error_kind"]}
                        if item.get("error_kind")
                        else {}
                    ),
                }
                for item in attempts
            ],
        }
        self.last_call_receipt = receipt
        payload: dict[str, Any] = result.model_dump(mode="json")
        payload["paid_call_receipt"] = receipt
        return payload
