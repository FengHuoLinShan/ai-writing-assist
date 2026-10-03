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


def verified_secondary_models(provider_id: str, models: list[str] | None) -> list[str]:
    """过滤出已登记且声明支持结构化输出的附加模型；未登记不参与路由。

    档案把已登记模型标注为 verified_dev / historical_evidence_tuning 等
    实测口径，未登记模型一律落 unknown_fallback / legacy_fallback 的
    24K 保守档——fallback 档即 fail-closed 信号。cheap 能力全部是结构化
    抽取任务，路由目标还必须声明 ``structured_output="supported"``：
    未校准模型可以作主模型照常调用，但不被自动选为省钱路由目标。
    """
    from infrastructure.llm.capabilities import resolve_llm_capability_profile

    result: list[str] = []
    for model in models or []:
        name = str(model or "").strip()
        if not name:
            continue
        profile = resolve_llm_capability_profile(provider_id, name)
        if str(profile.calibration_status).endswith("fallback"):
            continue
        if (profile.structured_output or "unverified") != "supported":
            continue
        result.append(name)
    return result


async def build_cost_routing(
    db: AsyncSession,
    novel_id: str,
    *,
    project_context: Any = None,
    provider_id: str | None = None,
) -> dict[str, Any]:
    """解析当前生效的路由配置；未启用或无可用模型时返回空路由（回落主模型）。

    ``project_context``：调用方已加载的同项目 ProjectContext，避免与运行
    profile 解析重复查询同一行（open_project_llm_client 每次开 client 都会
    走到这里）；省略时在此自行加载。
    ``provider_id`` 绑定实际 client/快照连接；当前附加模型属于其他连接时回落。
    """
    from uuid import UUID

    from modules.account.facade import read_account_secondary_models
    from modules.project.services import ProjectService

    project = (
        project_context
        if project_context is not None
        else await ProjectService().get_project_context(db, novel_id, project_kind=None)
    )
    if project is None:
        from core.errors import NotFoundError

        raise NotFoundError("Project not found")
    settings = project.settings or {}
    enabled = (settings.get(COST_SAVING_KEY) or {}).get("enabled") is True
    routing: dict[str, Any] = {
        "enabled": False,
        "cheap_model": None,
        "capability_ids": [],
    }
    if not enabled:
        return routing
    account_provider_id, secondary = await read_account_secondary_models(
        db, owner_id=UUID(project.owner_id)
    )
    if not account_provider_id or (
        provider_id is not None and provider_id != account_provider_id
    ):
        return routing
    candidates = verified_secondary_models(account_provider_id, secondary)
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
    project = await db.scalar(_select(Project).where(Project.id == UUID(str(novel_id))))
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
        _select(Project).where(Project.id == UUID(str(novel_id))).with_for_update()
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
