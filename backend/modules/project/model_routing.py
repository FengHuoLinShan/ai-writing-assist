"""任务级模型路由（B5）：按能力成本档在同 provider 连接内选低成本模型。

约束（方案 B5）：
- 路由不变成用户负担：默认关闭，项目级「省钱模式」一个开关；
- 只在同一账户连接（同 provider）内切换模型，未配置/未校准时回落主模型；
- 非 verified 档的模型不参与路由（fail-closed）；
- 只有注册表标记 ``cost_tier="cheap"`` 的抽取/整理类能力会被路由。

路由决定在 modules/project 层做（读注册表与账户配置），执行在
infrastructure/llm/agent_step_harness（按注入的集合覆盖 request.model）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

COST_SAVING_KEY = "llm_cost_saving_v1"


def cheap_capability_ids() -> frozenset[str]:
    """注册表中标记 cheap 成本档的能力集（B5 路由消费）。"""
    from modules.evidence.contracts import CAPABILITY_REGISTRY

    return frozenset(
        capability_id
        for capability_id, policy in CAPABILITY_REGISTRY.items()
        if policy.cost_tier == "cheap"
    )


def verified_secondary_models(
    provider_id: str, models: list[str] | None
) -> list[str]:
    """过滤出已在能力档案登记（非 fallback 档）的附加模型；未登记不参与路由。

    档案把已登记模型标注为 verified_dev / historical_evidence_tuning 等
    实测口径，未登记模型一律落 unknown_fallback / legacy_fallback 的
    24K 保守档——fallback 档即 fail-closed 信号。
    """
    from infrastructure.llm.capabilities import resolve_llm_capability_profile

    result: list[str] = []
    for model in models or []:
        name = str(model or "").strip()
        if not name:
            continue
        profile = resolve_llm_capability_profile(provider_id, name)
        if not str(profile.calibration_status).endswith("fallback"):
            result.append(name)
    return result


async def build_cost_routing(db: AsyncSession, novel_id: str) -> dict[str, Any]:
    """解析当前生效的路由配置；未启用或无可用模型时返回空路由（回落主模型）。"""
    from sqlalchemy import select as _select

    from modules.account.settings_repositories import GlobalLLMDefaultsRepository
    from modules.project.models import Project
    from modules.project.services import ProjectService

    await ProjectService().get_project(db, novel_id)  # owner/active 边界
    from uuid import UUID

    project = await db.scalar(
        _select(Project).where(Project.id == UUID(str(novel_id)))
    )
    if project is None:
        return {"enabled": False, "cheap_model": None, "capability_ids": []}
    settings = project.settings or {}
    enabled = (settings.get(COST_SAVING_KEY) or {}).get("enabled") is True
    routing: dict[str, Any] = {
        "enabled": False,
        "cheap_model": None,
        "capability_ids": [],
    }
    if not enabled:
        return routing
    defaults = await GlobalLLMDefaultsRepository().get(
        db, project.owner_id
    )
    if defaults is None or not defaults.provider_id:
        return routing
    candidates = verified_secondary_models(
        str(defaults.provider_id), list(defaults.secondary_models or [])
    )
    if not candidates:
        return routing
    routing.update(
        {
            "enabled": True,
            "cheap_model": candidates[0],
            "capability_ids": sorted(cheap_capability_ids()),
        }
    )
    return routing


async def read_cost_saving_toggle(db: AsyncSession, novel_id: str) -> dict:
    from uuid import UUID

    from sqlalchemy import select as _select

    from modules.project.models import Project
    from modules.project.services import ProjectService

    await ProjectService().get_project(db, novel_id)
    project = await db.scalar(
        _select(Project).where(Project.id == UUID(str(novel_id)))
    )
    settings = (project.settings or {}) if project is not None else {}
    enabled = (settings.get(COST_SAVING_KEY) or {}).get("enabled") is True
    routing = await build_cost_routing(db, novel_id)
    return {
        "enabled": enabled,
        "effective": bool(routing["enabled"]),
        "cheap_model": routing["cheap_model"],
    }


async def set_cost_saving_toggle(
    db: AsyncSession, novel_id: str, *, enabled: bool
) -> dict:
    from uuid import UUID

    from sqlalchemy import select as _select

    from modules.project.models import Project
    from modules.project.services import ProjectService

    service = ProjectService()
    service._reject_demo_write()
    await service.get_project(db, novel_id)
    project = await db.scalar(
        _select(Project)
        .where(Project.id == UUID(str(novel_id)))
        .with_for_update()
    )
    if project is None:
        from core.errors import NotFoundError

        raise NotFoundError("Project not found")
    project.settings = {
        **(project.settings or {}),
        COST_SAVING_KEY: {"enabled": bool(enabled)},
    }
    await db.flush()
    routing = await build_cost_routing(db, novel_id)
    return {
        "enabled": bool(enabled),
        "effective": bool(routing["enabled"]),
        "cheap_model": routing["cheap_model"],
    }
