"""E09 第一步：生产采样器的冻结 fixture 验证（不联网、不真实模型）。

- Prompt 注入面（T07）：正文与前序已提交回执身份确定性进入消息。
- Schema 校验：合法 fixture 解析；非法 fixture（未知 modality/编造字段）
  失败关闭，不猜测修复。
- 计量：每次调用的回执进入冻结负载（paid_call_receipt），可审计。
- 生产 provider 解析：未接线 fail-closed；project_llm 工厂指向项目 LLM
  入口（真实调用需 owner 连接，单独授权验收）。
"""

from __future__ import annotations

from typing import Any

import pytest

from infrastructure.llm.schemas import LLMCallRequest
from modules.evolution.llm_sampler import (
    ProjectLLMSampler,
    SceneSample,
    build_scene_messages,
)
from modules.evolution.sampler import (
    SamplerNotWiredError,
    resolve_scene_sampler,
)

FROZEN_VALID = {
    "observations": [
        {
            "predicate": "青竹在白石城取出铜钥匙并声明保管责任",
            "modality": "event_observed",
            "quote": "青竹从袖中取出铜钥匙",
            "mentions": [
                {"surface": "青竹", "entity_type": "character"},
                {"surface": "林舟", "entity_type": "character"},
            ],
        }
    ],
    "scene_events": [
        {
            "dimension": "locations",
            "event_type": "entity_moved",
            "entity_id": None,
            "snapshot_after": {"text_state": "白石城"},
        }
    ],
    "unresolved_parts": [],
}

FROZEN_INVALID_MODALITY = {
    "observations": [{"predicate": "x", "modality": "definitely_true", "quote": "x"}]
}

FROZEN_FABRICATED_FIELD = {
    "observations": [],
    "scene_events": [],
    "entity_uuids_i_invented": ["11111111-1111-4111-8111-111111111111"],
}


class _FrozenClient:
    """冻结 fixture 客户端：记录请求，返回逐字节固定响应与用量诊断。"""

    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.requests: list[LLMCallRequest] = []

    async def generate_structured(
        self,
        request: LLMCallRequest,
        schema: type,
        *,
        diagnostics: list[dict[str, Any]] | None = None,
    ):
        self.requests.append(request)
        if diagnostics is not None:
            diagnostics.append(
                {
                    "kind": "structured_usage",
                    "status": "succeeded",
                    "attempt": 1,
                    "finish_reason": "stop",
                    "completion_tokens": 137,
                    "max_tokens": 4096,
                }
            )
        return schema.model_validate(self.payload)


def _manifest(previous: str | None = None) -> dict[str, Any]:
    return {
        "scene_index": 1,
        "previous_scene_attempt_id": previous,
        "previous_committed_prefix": (
            {"through_scene_index": 0, "through_source_revision": 1} if previous else None
        ),
    }


def test_prompt_carries_text_and_previous_receipt_identity() -> None:
    messages = build_scene_messages(
        scene_text="林舟与青竹在白石城重逢。",
        input_manifest=_manifest(previous="abc123"),
    )
    rendered = "\n".join(message.content for message in messages)
    assert "林舟与青竹在白石城重逢。" in rendered
    assert "abc123" in rendered  # T07：前序回执身份实际进入 Prompt
    assert "committed_prefix" in rendered


def test_head_scene_prompt_declares_no_previous() -> None:
    messages = build_scene_messages(scene_text="正文。", input_manifest=_manifest())
    rendered = "\n".join(message.content for message in messages)
    assert "无（本 Scene 为链头）" in rendered


async def test_frozen_fixture_sampling_records_paid_call() -> None:
    client = _FrozenClient(FROZEN_VALID)
    sampler = ProjectLLMSampler(client)

    payload = await sampler.sample(
        scene_text="林舟与青竹在白石城重逢。",
        input_manifest=_manifest(previous="abc123"),
    )

    parsed = SceneSample.model_validate(
        {k: v for k, v in payload.items() if k != "paid_call_receipt"}
    )
    assert parsed.observations[0].modality == "event_observed"
    assert parsed.observations[0].mentions[0].surface == "青竹"
    assert payload["paid_call_receipt"]["schema"] == "evolution.scene_sample.v1"
    # 计量来自结构化调用诊断通道（completion_tokens 真实进入回执）。
    assert payload["paid_call_receipt"]["usage"]["completion_tokens"] == 137
    assert payload["paid_call_receipt"]["usage"]["attempts"] == 1
    # Prompt 实际携带前序回执身份（采样器没有丢掉注入面）。
    rendered = "\n".join(message.content for message in client.requests[0].messages)
    assert "abc123" in rendered


async def test_invalid_fixture_fails_closed() -> None:
    with pytest.raises(Exception):
        SceneSample.model_validate(FROZEN_INVALID_MODALITY)
    with pytest.raises(Exception):
        SceneSample.model_validate(FROZEN_FABRICATED_FIELD)


async def test_project_llm_provider_resolve_paths() -> None:
    # 未注册 provider：fail-closed 拒伪造（进入 context manager 即抛）。
    with pytest.raises(SamplerNotWiredError):
        async with resolve_scene_sampler(provider="nope", novel_id="n1", db=None):
            pass

    # project_llm 工厂存在且指向项目 LLM 入口；无 owner 连接的项目在
    # 真实调用时 fail-closed（此处只验证装配指向，不发真实请求）。
    from modules.evolution.sampler import project_llm_sampler_factory

    assert callable(project_llm_sampler_factory)

    # 测试替身经 registry 解析为 context manager（普通可等待对象被包装）。
    from modules.evolution.sampler import register_scene_sampler

    class _Echo:
        async def sample(self, *, scene_text: str, input_manifest: dict) -> dict:
            return {"observations": [], "scene_events": []}

    register_scene_sampler("test-wrap", lambda db, novel_id: _Echo())
    async with resolve_scene_sampler(
        provider="test-wrap", novel_id="n1", db=None
    ) as sampler:
        payload = await sampler.sample(scene_text="x", input_manifest={})
        assert payload == {"observations": [], "scene_events": []}
