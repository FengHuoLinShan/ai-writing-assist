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
from pydantic import ValidationError

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


def test_scene_event_can_reference_all_observations_without_dropping_evidence() -> None:
    payload = {
        "observations": [
            {"predicate": f"观察 {index}", "quote": f"原句 {index}"}
            for index in range(17)
        ],
        "scene_events": [
            {
                "dimension": "knowledge",
                "event_type": "knowledge_changed",
                "source_observation_indices": list(range(17)),
            }
        ],
    }
    sample = SceneSample.model_validate(payload)
    references = sample.scene_events[0].source_observation_indices
    assert len(references) == 17
    payload["scene_events"][0]["source_observation_indices"] = list(range(65))
    with pytest.raises(ValidationError, match="too_long"):
        SceneSample.model_validate(payload)

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
        **options,
    ):
        assert options == {"max_fix_attempts": 0, "transport_retries": False}
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


class _PartialClient(_FrozenClient):
    async def generate_structured(self, request, schema, *, diagnostics=None, **options):
        assert options == {
            "max_fix_attempts": 0,
            "transport_retries": False,
            "partial_list_fields": {"uncertain_items"},
        }
        self.requests.append(request)
        diagnostics.extend(
            [
                {
                    "kind": "partial_list_validation",
                    "field": "uncertain_items",
                    "kept": 2,
                    "skipped": 1,
                    "errors": [{"index": 1, "errors": []}],
                },
                {
                    "kind": "structured_usage",
                    "status": "succeeded",
                    "attempt": 1,
                    "prompt_tokens": 10,
                    "completion_tokens": 20,
                    "total_tokens": 30,
                },
            ]
        )
        return schema.model_validate(self.payload)


class _RepairingClient:
    """结构化修复路径的冻结形状：失败尝试同样产生 structured_usage
    诊断（响应已发生、可能已计费），最终一次成功。"""

    def __init__(self, attempts: list[dict[str, Any]]) -> None:
        self._attempts = attempts
        self.provider_id = "deepseek"
        self.model = "deepseek-chat"

    async def generate_structured(
        self,
        request: LLMCallRequest,
        schema: type,
        *,
        diagnostics: list[dict[str, Any]] | None = None,
        **options,
    ):
        assert options == {"max_fix_attempts": 0, "transport_retries": False}
        if diagnostics is not None:
            diagnostics.extend(self._attempts)
        return schema.model_validate(FROZEN_VALID)


@pytest.mark.parametrize(
    "text,quote,declared,expected,aligned",
    [
        ("😀也没有提起封锁。", "也没有提起封锁", [2, 8], [1, 8], True),
        ("aaa", "aa", [0, 1], [0, 1], False),
        ("两次两次", "两次", [2, 4], [2, 4], False),
        ("正文", "不存在", [0, 3], [0, 3], False),
    ],
)
async def test_host_only_aligns_a_unique_exact_scene_quote(
    text, quote, declared, expected, aligned
):
    sampler = ProjectLLMSampler(
        _FrozenClient(
            {
                "observations": [
                    {
                        "predicate": "窄观察",
                        "quote": quote,
                        "start_offset": declared[0],
                        "end_offset": declared[1],
                    }
                ]
            }
        )
    )
    payload = await sampler.sample(scene_text=text, input_manifest={})
    observation = payload["observations"][0]
    assert [observation["start_offset"], observation["end_offset"]] == expected
    assert bool(payload["paid_call_receipt"].get("quote_alignment")) == aligned
    if aligned:
        assert (
            payload["paid_call_receipt"]["quote_alignment"]["changes"][0]["declared"]
            == declared
        )


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
    assert "最多40条观察" in rendered
    assert "回忆、传闻" in rendered


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


async def test_flash_observation_sampling_uses_nonthinking_json_budget() -> None:
    client = _FrozenClient(FROZEN_VALID)
    client.model_name = "deepseek-flash"
    await ProjectLLMSampler(client).sample(
        scene_text="林舟与青竹在白石城重逢。", input_manifest=_manifest()
    )
    assert client.requests[0].extra == {"thinking": {"type": "disabled"}}
    assert client.requests[0].temperature == 0.1
    assert client.requests[0].max_tokens == 16384
    assert (
        "仍不唯一就把该观察放进 unresolved_parts"
        in client.requests[0].messages[0].content
    )


async def test_flash_complex_calls_use_high_thinking_and_larger_json_budget() -> None:
    client = _FrozenClient(FROZEN_VALID)
    client.model_name = "deepseek-flash"
    sampler = ProjectLLMSampler(client)
    await sampler._scene_call(LLMCallRequest(), SceneSample, "evolution.state_review.v1")
    await sampler._scene_call(
        LLMCallRequest(), SceneSample, "imports.AuditVerdictOutput.v1"
    )
    await sampler._scene_call(
        LLMCallRequest(), SceneSample, "imports.Phase2aSceneExtractionOutput.v1"
    )
    assert [request.extra for request in client.requests] == [
        {"thinking": {"type": "enabled"}, "reasoning_effort": "high"},
    ] * 3
    assert [request.max_tokens for request in client.requests] == [
        32768,
        65536,
        65536,
    ]


async def test_relation_uncertainty_quarantine_is_in_call_receipt() -> None:
    client = _PartialClient(FROZEN_VALID)
    client.model_name = "deepseek-flash"
    payload = await ProjectLLMSampler(client)._scene_call(
        LLMCallRequest(), SceneSample, "imports.AliasRelationExtractionOutput.v1"
    )
    assert client.requests[0].max_tokens == 65536
    assert payload["paid_call_receipt"]["validation_quarantine"] == [
        {
            "field": "uncertain_items",
            "kept": 2,
            "skipped": 1,
            "errors": [{"index": 1, "errors": []}],
        }
    ]


async def test_repeated_quote_without_exact_offset_is_quarantined() -> None:
    client = _FrozenClient(
        {
            "observations": [
                {
                    "predicate": "甲看见晨光",
                    "quote": "晨光。",
                    "modality": "event_observed",
                },
                {
                    "predicate": "乙看见夜色",
                    "quote": "夜色。",
                    "modality": "event_observed",
                },
            ],
            "scene_events": [
                {
                    "dimension": "knowledge",
                    "event_type": "knowledge_changed",
                    "source_observation_indices": [0],
                },
                {
                    "dimension": "knowledge",
                    "event_type": "knowledge_changed",
                    "source_observation_indices": [1],
                },
            ],
            "unresolved_parts": [],
        }
    )
    payload = await ProjectLLMSampler(client).sample(
        scene_text="晨光。晨光。夜色。", input_manifest=_manifest()
    )
    assert [item["predicate"] for item in payload["observations"]] == ["乙看见夜色"]
    assert [item["source_observation_indices"] for item in payload["scene_events"]] == [
        [0]
    ]
    assert "人工核对" in payload["unresolved_parts"][-1]
    quarantine = payload["paid_call_receipt"]["quote_quarantine"]
    assert quarantine["observations"][0]["index"] == 0
    assert quarantine["observations"][0]["reason"] == "ambiguous_duplicate_quote"
    assert quarantine["scene_events"][0]["index"] == 0


async def test_small_number_of_nonverbatim_quotes_stays_out_of_source_chain() -> None:
    client = _FrozenClient(
        {
            "observations": [
                {"predicate": "误引", "quote": "正文里没有这一句"},
                {"predicate": "夜色", "quote": "夜色。"},
            ],
            "scene_events": [
                {
                    "dimension": "knowledge",
                    "event_type": "knowledge_changed",
                    "source_observation_indices": [0],
                }
            ],
            "unresolved_parts": [],
        }
    )
    payload = await ProjectLLMSampler(client).sample(
        scene_text="夜色。", input_manifest=_manifest()
    )
    assert [item["predicate"] for item in payload["observations"]] == ["夜色"]
    assert payload["scene_events"] == []
    assert (
        payload["paid_call_receipt"]["quote_quarantine"]["observations"][0]["reason"]
        == "quote_not_in_scene"
    )


async def test_unique_whitespace_variant_uses_exact_source_span() -> None:
    client = _FrozenClient(
        {
            "observations": [
                {"predicate": "甲回答", "quote": "甲说：\n“好。”"},
            ],
            "scene_events": [],
            "unresolved_parts": [],
        }
    )
    payload = await ProjectLLMSampler(client).sample(
        scene_text="甲说：\n　　“好。”", input_manifest=_manifest()
    )
    assert payload["observations"][0]["quote"] == "甲说：\n　　“好。”"
    assert payload["observations"][0]["start_offset"] == 0
    assert (
        payload["paid_call_receipt"]["whitespace_alignment"]["changes"][0][
            "declared_quote"
        ]
        == "甲说：\n“好。”"
    )


async def test_invalid_fixture_fails_closed() -> None:
    with pytest.raises(Exception):
        SceneSample.model_validate(FROZEN_INVALID_MODALITY)
    with pytest.raises(Exception):
        SceneSample.model_validate(FROZEN_FABRICATED_FIELD)


async def test_receipt_counts_every_paid_attempt_including_failed_repairs() -> None:
    # PR160-162 审查 F3：两次解析/schema 失败 + 一次成功——三次请求都已
    # 实际发生，回执必须体现 3 次与全部用量（300 tokens），不能只留最后
    # 一次成功的用量、把 attempts 记成 1。
    attempts = [
        {
            "kind": "structured_usage",
            "status": "failed",
            "error_kind": "invalid_json",
            "attempt": 1,
            "completion_tokens": 100,
        },
        {
            "kind": "structured_usage",
            "status": "failed",
            "error_kind": "schema_validation",
            "attempt": 2,
            "completion_tokens": 120,
        },
        {
            "kind": "structured_usage",
            "status": "succeeded",
            "attempt": 3,
            "completion_tokens": 80,
        },
    ]
    sampler = ProjectLLMSampler(_RepairingClient(attempts))

    payload = await sampler.sample(
        scene_text="林舟与青竹在白石城重逢。", input_manifest=_manifest()
    )

    usage = payload["paid_call_receipt"]["usage"]
    assert usage["completion_tokens"] == 300
    assert usage["attempts"] == 3
    assert usage["succeeded_attempts"] == 1
    detail = payload["paid_call_receipt"]["attempts_detail"]
    assert [item["status"] for item in detail] == ["failed", "failed", "succeeded"]
    assert [item.get("error_kind") for item in detail] == [
        "invalid_json",
        "schema_validation",
        None,
    ]


async def test_receipt_keeps_unknown_usage_as_none_not_zero() -> None:
    # 计量通道没给出用量时保持未知（None），不得当作 0 记账。
    attempts = [{"kind": "structured_usage", "status": "succeeded", "attempt": 1}]
    sampler = ProjectLLMSampler(_RepairingClient(attempts))

    payload = await sampler.sample(scene_text="正文。", input_manifest=_manifest())

    usage = payload["paid_call_receipt"]["usage"]
    assert usage["completion_tokens"] is None
    assert usage["attempts"] == 1


async def test_mixed_unknown_usage_totals_stay_unknown() -> None:
    # A06（2026-09-22 审查）：已知 100 + 未知 ≠ 100——部分未知不得汇总成
    # 貌似完整的数值；usage_complete=False 且 unknown_attempts 显式留痕。
    attempts = [
        {
            "kind": "structured_usage",
            "status": "failed",
            "error_kind": "invalid_json",
            "attempt": 1,
            "completion_tokens": 100,
        },
        {"kind": "structured_usage", "status": "succeeded", "attempt": 2},
    ]
    sampler = ProjectLLMSampler(_RepairingClient(attempts))

    payload = await sampler.sample(scene_text="正文。", input_manifest=_manifest())

    usage = payload["paid_call_receipt"]["usage"]
    assert usage["completion_tokens"] is None  # 第二次未知 → 总量未知
    assert usage["attempts"] == 2
    # 口径：任一字段缺失即部分未知——第一次缺 prompt/total 也计入。
    assert usage["unknown_attempts"] == 2
    assert usage["usage_complete"] is False


async def test_partial_field_totals_track_completeness_per_field() -> None:
    # A06：字段级独立计量——prompt 全已知可汇总，completion 存在未知即未知。
    attempts = [
        {
            "kind": "structured_usage",
            "status": "succeeded",
            "attempt": 1,
            "prompt_tokens": 10,
            "completion_tokens": 50,
        },
        {
            "kind": "structured_usage",
            "status": "succeeded",
            "attempt": 2,
            "prompt_tokens": 20,
        },
    ]
    sampler = ProjectLLMSampler(_RepairingClient(attempts))

    payload = await sampler.sample(scene_text="正文。", input_manifest=_manifest())

    usage = payload["paid_call_receipt"]["usage"]
    assert usage["prompt_tokens"] == 30
    assert usage["completion_tokens"] is None
    assert usage["usage_complete"] is False


async def test_final_failure_still_records_paid_receipt() -> None:
    # A07（2026-09-22 审查）：最终抛错时回执不得凭空消失——采样器固化
    # 失败回执（含已发生请求的真实用量）后再重抛，供调用方留档对账。
    class _FailingStructuredClient:
        provider_id = "deepseek"
        model = "deepseek-chat"

        async def generate_structured(
            self,
            request: LLMCallRequest,
            schema: type,
            *,
            diagnostics: list[dict[str, Any]] | None = None,
            **options,
        ):
            assert options == {"max_fix_attempts": 0, "transport_retries": False}
            if diagnostics is not None:
                diagnostics.append(
                    {
                        "kind": "structured_usage",
                        "status": "failed",
                        "error_kind": "invalid_json",
                        "attempt": 1,
                        "completion_tokens": 123,
                    }
                )
            raise ValueError("structured generation failed after repair attempts")

    sampler = ProjectLLMSampler(_FailingStructuredClient())
    with pytest.raises(ValueError, match="failed after repair"):
        await sampler.sample(scene_text="正文。", input_manifest=_manifest())

    receipt = sampler.last_call_receipt
    assert receipt is not None
    assert receipt["outcome"] == "failed_final"
    assert receipt["usage"]["completion_tokens"] == 123
    assert receipt["usage"]["attempts"] == 1
    assert receipt["attempts_detail"][0]["error_kind"] == "invalid_json"


async def test_project_llm_provider_resolve_paths() -> None:
    # 未注册 provider：fail-closed 拒伪造（进入 context manager 即抛）。
    with pytest.raises(SamplerNotWiredError):
        async with resolve_scene_sampler(provider="nope", novel_id="n1", db=None):
            pass
    with pytest.raises(SamplerNotWiredError, match="frozen model"):
        async with resolve_scene_sampler(provider="project_llm", novel_id="n1"):
            pytest.fail("must not resolve the current default for an old run")

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
