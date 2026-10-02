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
        client, request, capability_id="imports.entity_extraction"
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

    routed = _apply_cost_routing(client, request, capability_id="writing.generate")

    assert routed is request  # 原对象原样返回（回落主模型）


def test_apply_cost_routing_noop_without_injection() -> None:
    from infrastructure.llm.agent_step_harness import _apply_cost_routing

    client = SimpleNamespace()  # 无 cost_routing 属性
    request = _request()

    assert (
        _apply_cost_routing(client, request, capability_id="imports.scene_slicing")
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
    # 默认 unverified：未校准模型不得接收 json_object（fail-closed）
    assert unknown.structured_output == "unverified"


def test_registry_cost_tiers_are_registered() -> None:
    from modules.evidence.contracts import CAPABILITY_REGISTRY

    cheap = {
        key
        for key, policy in CAPABILITY_REGISTRY.items()
        if policy.cost_tier == "cheap"
    }
    assert "imports.entity_extraction" in cheap
    assert "imports.scene_slicing" in cheap
    assert CAPABILITY_REGISTRY["writing.generate"].cost_tier == "standard"
