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
    """模型提议的场景事件（仍走 E03b producer 分区与校验）。

    ``source_observation_indices`` 指向同一响应里本批观察的序号——状态
    提议必须自附证据（A03 语义门）；``knowledge_subject`` 是 knowledge
    维度事件的认知主体（谁知道）。两者缺失不会使 schema 失败，但会被
    状态门拦下进入待裁定，而非取得状态效果。
    """

    model_config = ConfigDict(extra="forbid")

    dimension: str = Field(
        pattern="^(entities|relations|locations|knowledge|timeline|causality)$"
    )
    event_type: str = Field(min_length=1, max_length=64)
    entity_id: str | None = None
    snapshot_after: dict[str, Any] = Field(default_factory=dict)
    source_observation_indices: list[int] = Field(default_factory=list, max_length=16)
    knowledge_subject: str | None = Field(default=None, max_length=120)


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
    "unresolved_parts，不要猜测。scene_events 是状态提议，不是复述：每条"
    "必须用 source_observation_indices 引用本批观察的序号作为证据；客观"
    "状态变化只能基于 event_observed 观察，传闻/假设/角色陈述最多支撑"
    " knowledge 维度且必须写明 knowledge_subject；引用不上证据的提议"
    "会被拦下待作者裁定。"
)


def build_scene_messages(
    *,
    scene_text: str,
    input_manifest: dict[str, Any],
) -> list[LLMMessage]:
    """确定性 Prompt：正文 + 前序已提交回执身份与**实际状态内容**（T07）。

    前序理解不只传回执 ID——结构化前序观察（A04）按 modality 原样注入：
    belief/hypothesis/character_statement 在输入里保持传闻/假设语义，
    不再压成裸谓词冒充"已确认的观察"；主体与来源 Scene 一并携带，
    截断条数显式披露（未注入不等于不存在）。
    """
    previous = input_manifest.get("previous_scene_attempt_id")
    previous_prefix = input_manifest.get("previous_committed_prefix")
    prior_observations = input_manifest.get("previous_observations") or []
    coverage = input_manifest.get("previous_observations_coverage") or {}
    context_lines = [
        f"【Scene {input_manifest.get('scene_index', 0)} 正文】",
        scene_text,
    ]
    if previous:
        context_lines.append(
            "【前序已提交理解（回执身份）】"
            f"attempt_id={previous}；committed_prefix={previous_prefix}"
        )
        if prior_observations:
            context_lines.append(
                "【前序观察（按 modality 标注：belief/hypothesis/"
                "character_statement 是传闻、假设或角色陈述，"
                "不是客观事实；author_plan 是规划意图）】"
            )
            for item in prior_observations:
                if isinstance(item, str):  # 兼容裸谓词条目的存量输入
                    context_lines.append(f"- {item}")
                    continue
                subjects = "、".join(str(s) for s in item.get("subjects") or [])
                scene_anchor = item.get("scene_index")
                anchor = (
                    f"；来自 Scene {scene_anchor}" if scene_anchor is not None else ""
                )
                suffix = (
                    f"（主体：{subjects}{anchor}）"
                    if subjects
                    else (
                        f"（来自 Scene {scene_anchor}）"
                        if scene_anchor is not None
                        else ""
                    )
                )
                context_lines.append(
                    f"- [{item.get('modality', 'unclear')}] "
                    f"{item.get('predicate', '')}{suffix}"
                )
            omitted = coverage.get("omitted_observations")
            if isinstance(omitted, int) and omitted > 0:
                context_lines.append(f"（另有 {omitted} 条前序观察因注入上限未列出）")
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
        try:
            result: SceneSample = await self._client.generate_structured(
                request, SceneSample, diagnostics=diagnostics
            )
        except Exception:
            # 最终失败也必须留下回执（A07）：请求可能已发出、可能已计费，
            # 回执先行固化再重抛，调用方据此进入待核对而非盲目重采样。
            self.last_call_receipt = self._build_receipt(
                diagnostics, outcome="failed_final"
            )
            raise
        receipt = self._build_receipt(diagnostics, outcome="succeeded")
        self.last_call_receipt = receipt
        payload: dict[str, Any] = result.model_dump(mode="json")
        payload["paid_call_receipt"] = receipt
        return payload

    def _build_receipt(
        self, diagnostics: list[dict[str, Any]], *, outcome: str
    ) -> dict[str, Any]:
        """结构化修复的每次请求都已实际发生（解析/schema 失败的响应同样
        可能已计费）：回执保留全部请求明细与状态。

        用量口径（A06）：任一尝试对某字段未知，该字段总量即未知（None），
        绝不把未知次数默认为免费。``unknown_attempts`` 计缺失任一字段的
        尝试（部分或完全未知）；``usage_complete`` 为真当且仅当全部尝试
        报齐三个字段。attempts_detail 保留逐次对账明细。
        """
        attempts = [
            item for item in diagnostics if item.get("kind") == "structured_usage"
        ]
        usage_fields = ("prompt_tokens", "completion_tokens", "total_tokens")

        def _field_total(field: str) -> int | None:
            values: list[int] = []
            for item in attempts:
                value = item.get(field)
                if isinstance(value, bool) or not isinstance(value, int):
                    return None
                values.append(value)
            return sum(values) if values else None

        unknown_attempts = sum(
            1
            for item in attempts
            if any(
                isinstance(item.get(field), bool) or not isinstance(item.get(field), int)
                for field in usage_fields
            )
        )
        return {
            "provider": getattr(self._client, "provider_id", None) or "project_llm",
            "model": getattr(self._client, "model", None)
            or getattr(self._client, "model_id", None),
            "schema": "evolution.scene_sample.v1",
            "outcome": outcome,
            "usage": {
                "prompt_tokens": _field_total("prompt_tokens"),
                "completion_tokens": _field_total("completion_tokens"),
                "total_tokens": _field_total("total_tokens"),
                "attempts": len(attempts),
                "succeeded_attempts": sum(
                    1 for item in attempts if item.get("status") == "succeeded"
                ),
                "unknown_attempts": unknown_attempts,
                "usage_complete": bool(attempts) and unknown_attempts == 0,
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
