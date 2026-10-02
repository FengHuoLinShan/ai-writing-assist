"""任务级模型路由（B5）测试：路由决定、verified 过滤、step 覆盖与回落。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from infrastructure.llm.schemas import LLMCallRequest


def _client(routing: dict | None) -> SimpleNamespace:
    return SimpleNamespace(cost_routing=routing)


def _request(model: str = "deepseek-flash") -> LLMCallRequest:
    return LLMCallRequest(model=model, messages=[])


# ============================================================
# 路由决定
# ============================================================


@pytest.mark.asyncio
async def test_cost_routing_disabled_by_default(db_session, test_project_id) -> None:
    from modules.project.model_routing import build_cost_routing

    routing = await build_cost_routing(db_session, test_project_id)

    assert routing == {"enabled": False, "cheap_model": None, "capability_ids": []}


@pytest.mark.asyncio
async def test_hidden_interaction_routing_preserves_owner_gate(db_session):
    from uuid import uuid4

    from core.errors import NotFoundError
    from modules.account.facade import current_account_id
    from modules.account.models import Account
    from modules.project.model_routing import build_cost_routing
    from modules.project.models import Project

    owned = Project(
        id=uuid4(),
        owner_id=current_account_id(),
        title="RP合成测试",
        project_kind="interaction",
    )
    other_owner = uuid4()
    db_session.add(Account(id=other_owner, support_code=f"routing-{other_owner.hex[:8]}"))
    await db_session.flush()
    foreign = Project(
        id=uuid4(), owner_id=other_owner, title="其他账户RP", project_kind="interaction"
    )
    db_session.add_all([owned, foreign])
    await db_session.flush()
    assert (await build_cost_routing(db_session, str(owned.id)))["enabled"] is False
    with pytest.raises(NotFoundError):
        await build_cost_routing(db_session, str(foreign.id))


@pytest.mark.asyncio
async def test_cost_routing_requires_verified_secondary(
    db_session, test_project_id, account_llm_connection
) -> None:
    from modules.account.settings_repositories import GlobalLLMDefaultsRepository
    from modules.project.model_routing import (
        build_cost_routing,
        set_cost_saving_toggle,
    )

    # 附加模型：一个 verified（deepseek-flash）、一个未登记（fallback 档）
    await GlobalLLMDefaultsRepository().upsert(
        db_session,
        {
            "owner_id": account_llm_connection["owner_id"],
            "secondary_models": ["deepseek-flash", "totally-unknown-model"],
        },
    )
    toggle = await set_cost_saving_toggle(db_session, test_project_id, enabled=True)

    # 非 verified 模型不参与路由：effective 生效且选中 verified 的那个
    assert toggle["effective"] is True
    assert toggle["cheap_model"] == "deepseek-flash"

    routing = await build_cost_routing(db_session, test_project_id)
    assert routing["enabled"] is True
    assert "imports.entity_extraction" in routing["capability_ids"]
    assert "writing.generate" not in routing["capability_ids"]


@pytest.mark.asyncio
async def test_cost_routing_without_secondary_falls_back(
    db_session, test_project_id, account_llm_connection
) -> None:
    from modules.project.model_routing import set_cost_saving_toggle

    # 开关打开但没有任何附加模型：回落主模型（effective False）
    toggle = await set_cost_saving_toggle(db_session, test_project_id, enabled=True)
    assert toggle["enabled"] is True
    assert toggle["effective"] is False
    assert toggle["cheap_model"] is None


# ============================================================
# step 覆盖（harness 执行）
# ============================================================


def test_apply_cost_routing_switches_cheap_capability() -> None:
    from infrastructure.llm.agent_step_harness import _apply_cost_routing

    client = _client(
        {
            "enabled": True,
            "cheap_model": "deepseek-flash",
            "capability_ids": ["imports.entity_extraction"],
        }
    )
    request = _request(model="deepseek-v4-flash")

    routed = _apply_cost_routing(
        client, request, routing_capability_id="imports.entity_extraction"
    )

    assert routed is not request
    assert routed.model == "deepseek-flash"


def test_apply_cost_routing_falls_back_for_standard_capability() -> None:
    from infrastructure.llm.agent_step_harness import _apply_cost_routing

    client = _client(
        {
            "enabled": True,
            "cheap_model": "deepseek-flash",
            "capability_ids": ["imports.entity_extraction"],
        }
    )
    request = _request(model="deepseek-v4-flash")

    routed = _apply_cost_routing(
        client, request, routing_capability_id="writing.generate"
    )

    assert routed is request  # 原对象原样返回（回落主模型）


def test_apply_cost_routing_noop_without_injection() -> None:
    from infrastructure.llm.agent_step_harness import _apply_cost_routing

    client = SimpleNamespace()  # 无 cost_routing 属性
    request = _request()

    assert (
        _apply_cost_routing(
            client, request, routing_capability_id="imports.scene_slicing"
        )
        is request
    )


def test_routed_provenance_records_target_model() -> None:
    from infrastructure.llm.agent_step_harness import _routed_provenance

    provenance = {
        "step_name": "imports.entity_extraction",
        "profile_summary": {
            "model": "deepseek-v4-flash",
            "sources": {"model": "account"},
        },
    }

    updated = _routed_provenance(provenance, routed_model="deepseek-flash")

    assert updated["profile_summary"]["model"] == "deepseek-flash"
    assert updated["profile_summary"]["sources"]["model"] == "cost_routing"
    # 原 provenance 不被原地修改
    assert provenance["profile_summary"]["model"] == "deepseek-v4-flash"


# ============================================================
# 前置 3：结构化输出 fail-closed
# ============================================================


def test_structured_output_capability_declaration() -> None:
    from infrastructure.llm.capabilities import resolve_llm_capability_profile

    verified = resolve_llm_capability_profile("deepseek", "deepseek-v4-flash")
    unknown = resolve_llm_capability_profile("deepseek", "never-calibrated-model")

    assert verified.structured_output == "supported"
    assert unknown.structured_output == "unverified"


@pytest.mark.parametrize("response_format", [None, {"type": "json_object"}])
async def test_structured_output_fail_closed_for_declared_unsupported(
    response_format,
) -> None:
    """显式 unsupported 不能通过调用方预填 json_object 绕过。"""
    from unittest.mock import patch

    from infrastructure.llm.capabilities import LLMCapabilityProfile
    from infrastructure.llm.client import LLMClient
    from infrastructure.llm.errors import LLMError
    from infrastructure.llm.schemas import LLMCallRequest, LLMMessage

    unsupported = LLMCapabilityProfile(
        profile_id="test-unsupported-v1",
        provider_id="deepseek",
        model="deepseek-v4-flash",
        context_limit_tokens=128_000,
        verified_input_ceiling_tokens=64_000,
        normal_input_tokens=32_000,
        compact_trigger_tokens=48_000,
        summary_input_ceiling_tokens=64_000,
        story_output_tokens=8_192,
        see_sea_output_tokens=8_192,
        summary_output_tokens=8_192,
        safety_margin_tokens=2_048,
        calibration_status="verified_dev",
        structured_output="unsupported",
    ).validate()

    client = LLMClient(
        api_key="k",
        base_url="https://example.invalid",
        default_model="deepseek-v4-flash",
    )
    client._profile_summary = {"provider_id": "deepseek"}
    from pydantic import BaseModel

    class _Probe(BaseModel):
        ok: bool

    request = LLMCallRequest(
        model="deepseek-v4-flash",
        messages=[LLMMessage(role="user", content="x")],
        response_format=response_format,
    )

    with patch(
        "infrastructure.llm.capabilities.resolve_llm_capability_profile",
        return_value=unsupported,
        autospec=True,
    ):
        with pytest.raises(LLMError) as exc_info:
            await client.generate_structured(request, _Probe)
    assert exc_info.value.error_kind == "unsupported_structured_output"


@pytest.mark.parametrize("declaration", ["unverified", None])
@pytest.mark.parametrize("response_format", [None, {"type": "json_object"}])
async def test_structured_output_unverified_runs_without_provider_json_mode(
    declaration,
    response_format,
) -> None:
    """未校准模型（如 Kimi 模板默认）不失败关闭：剥离 provider json_object，
    走提示词内嵌 schema 与解析修复链，保证 RP 摘要/导入抽取可用。"""
    from unittest.mock import patch

    from infrastructure.llm.capabilities import LLMCapabilityProfile
    from infrastructure.llm.client import LLMClient
    from infrastructure.llm.schemas import LLMCallRequest, LLMCallResponse, LLMMessage

    unverified = LLMCapabilityProfile(
        profile_id="test-unverified-v1",
        provider_id="kimi",
        model="kimi-k3",
        context_limit_tokens=128_000,
        verified_input_ceiling_tokens=64_000,
        normal_input_tokens=32_000,
        compact_trigger_tokens=48_000,
        summary_input_ceiling_tokens=64_000,
        story_output_tokens=8_192,
        see_sea_output_tokens=8_192,
        summary_output_tokens=8_192,
        safety_margin_tokens=2_048,
        calibration_status="verified_dev",
        structured_output=declaration,
    ).validate()

    client = LLMClient(
        api_key="k",
        base_url="https://example.invalid",
        default_model="kimi-k3",
    )
    client._profile_summary = {"provider_id": "kimi"}
    from pydantic import BaseModel

    class _Probe(BaseModel):
        ok: bool

    request = LLMCallRequest(
        model="kimi-k3",
        messages=[LLMMessage(role="user", content="x")],
        response_format=response_format,
    )

    with patch(
        "infrastructure.llm.capabilities.resolve_llm_capability_profile",
        return_value=unverified,
        autospec=True,
    ):
        with patch.object(
            LLMClient, "generate", autospec=True
        ) as mock_generate:
            mock_generate.return_value = LLMCallResponse(
                content='{"ok": true}', model="kimi-k3"
            )
            result = await client.generate_structured(request, _Probe)

    assert result.ok is True
    req_used = mock_generate.call_args[0][1]
    assert req_used.response_format is None
    assert any(
        "output schema" in str(message.content)
        for message in req_used.messages
    )


def test_registry_cost_tiers_are_registered() -> None:
    from modules.evidence.contracts import CAPABILITY_REGISTRY

    cheap = {
        key for key, policy in CAPABILITY_REGISTRY.items() if policy.cost_tier == "cheap"
    }
    assert "imports.entity_extraction" in cheap
    assert "imports.scene_slicing" in cheap
    assert CAPABILITY_REGISTRY["writing.generate"].cost_tier == "standard"


# ============================================================
# 端到端：managed step 的 provenance 记录实际路由模型（B5 验收）
# ============================================================


async def test_managed_step_routes_and_records_provenance() -> None:
    """打开省钱模式后，cheap 能力的 managed 调用换模型且 provenance 记录之。"""
    from pydantic import BaseModel

    from infrastructure.llm.agent_step_harness import run_managed_structured

    class _Out(BaseModel):
        ok: bool = True

    seen: dict = {}

    class _RoutingClient:
        model_name = "deepseek-v4-flash"
        profile_summary = {
            "provider_id": "deepseek",
            "model": "deepseek-v4-flash",
            "sources": {"model": "account"},
        }
        cost_routing = {
            "enabled": True,
            "cheap_model": "deepseek-flash",
            "capability_ids": ["imports.entity_extraction"],
        }

        async def generate_structured(self, request, schema, **kwargs):
            seen["model"] = request.model
            return _Out()

    from infrastructure.llm.schemas import LLMCallRequest

    request = LLMCallRequest(model="deepseek-v4-flash", messages=[])
    result = await run_managed_structured(
        _RoutingClient(),
        request,
        _Out,
        step_name="phase2_world_extraction",
        capability_id="imports.entity_extraction",
    )

    assert isinstance(result, _Out)
    # 实际发送的请求与 provenance 都指向低成本模型
    assert seen["model"] == "deepseek-flash"

    # provenance（receipt 落库形态）记录路由后的模型与来源标记，
    # 组合断言 allowlist 不把 cost_routing 降级为 unknown
    import infrastructure.llm.agent_step_harness as harness
    from infrastructure.llm.schemas import sanitize_profile_summary

    routed = harness._routed_provenance(
        harness.build_managed_llm_provenance(
            _RoutingClient(), step_name="phase2", request=request
        ),
        routed_model="deepseek-flash",
    )
    # 真实链路里 sanitize 收到的是 routed_request（harness 已覆盖 model）
    routed_request = request.model_copy(update={"model": "deepseek-flash"})
    sanitized = sanitize_profile_summary(
        routed["profile_summary"], request=routed_request
    )
    assert sanitized["model"] == "deepseek-flash"
    assert sanitized["sources"]["model"] == "cost_routing"


def test_snapshot_client_uses_frozen_cost_routing() -> None:
    """恢复任务的路由按快照固化；旧快照（无键）空路由回落主模型。"""
    from modules.project.llm_runtime import create_project_snapshot_llm_client

    settings = {
        "llm": {
            "provider_id": "deepseek",
            "label": "DeepSeek",
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-v4-flash",
            "api_key": "test-key",
        },
        "cost_routing": {
            "enabled": True,
            "cheap_model": "deepseek-flash",
            "capability_ids": ["imports.entity_extraction"],
        },
    }
    client = create_project_snapshot_llm_client(settings)
    try:
        assert client.cost_routing["cheap_model"] == "deepseek-flash"
    finally:
        import asyncio

        asyncio.run(client.close())

    legacy = create_project_snapshot_llm_client(
        {k: v for k, v in settings.items() if k != "cost_routing"}
    )
    try:
        assert legacy.cost_routing == {}
    finally:
        import asyncio

        asyncio.run(legacy.close())

@pytest.mark.asyncio
@pytest.mark.parametrize("response_format", [None, {"type": "json_object"}])
async def test_structured_format_repair_respects_unverified_json_mode(
    response_format,
) -> None:
    """未校准模型走到格式修复链也不盲发 json_object（与主路径同一三态口径）。"""
    from unittest.mock import patch

    from infrastructure.llm.capabilities import LLMCapabilityProfile
    from infrastructure.llm.client import LLMClient
    from infrastructure.llm.schemas import LLMCallRequest, LLMCallResponse, LLMMessage

    unverified = LLMCapabilityProfile(
        profile_id="test-unverified-v1",
        provider_id="kimi",
        model="kimi-k3",
        context_limit_tokens=128_000,
        verified_input_ceiling_tokens=64_000,
        normal_input_tokens=32_000,
        compact_trigger_tokens=48_000,
        summary_input_ceiling_tokens=64_000,
        story_output_tokens=8_192,
        see_sea_output_tokens=8_192,
        summary_output_tokens=8_192,
        safety_margin_tokens=2_048,
        calibration_status="verified_dev",
        structured_output="unverified",
    ).validate()

    client = LLMClient(
        api_key="k",
        base_url="https://example.invalid",
        default_model="kimi-k3",
    )
    client._profile_summary = {"provider_id": "kimi"}
    from pydantic import BaseModel

    class _Probe(BaseModel):
        ok: bool

    request = LLMCallRequest(
        model="kimi-k3",
        messages=[LLMMessage(role="user", content="x")],
        response_format=response_format,
    )

    with patch(
        "infrastructure.llm.capabilities.resolve_llm_capability_profile",
        return_value=unverified,
        autospec=True,
    ):
        with patch.object(LLMClient, "generate", autospec=True) as mock_generate:
            mock_generate.side_effect = [
                LLMCallResponse(content="不是 JSON", model="kimi-k3"),
                LLMCallResponse(content='{"ok": true}', model="kimi-k3"),
            ]
            result = await client.generate_structured(
                request,
                _Probe,
                max_fix_attempts=0,
                format_repair_attempts=1,
            )

    assert result.ok is True
    assert mock_generate.call_count == 2  # 主尝试 + 格式修复各一次
    for call in mock_generate.call_args_list:
        assert call[0][1].response_format is None
