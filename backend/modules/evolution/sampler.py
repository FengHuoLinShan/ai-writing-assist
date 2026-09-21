"""演化场景步采样器解析（V4 E07.e）。

生产 LLM 采样器属 E09 真实质量验证的接线范围；未注册时 fail-closed，
绝不伪造观察（计划 §8：缺失来源不造假通过）。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_SAMPLER_REGISTRY: dict[str, Callable[..., Any]] = {
    "project_llm": None,  # 占位：project_llm_sampler_factory 定义后回填
}


class SamplerNotWiredError(Exception):
    """项目未接演化采样器：fail-closed，不伪造观察。"""


def register_scene_sampler(provider: str, factory: Callable[..., Any]) -> None:
    """注册采样器工厂（测试与 E09 生产接线共用入口）。"""
    _SAMPLER_REGISTRY[provider] = factory


async def project_llm_sampler_factory(db, novel_id: str):  # noqa: RUF029
    """生产 provider：经项目 LLM 入口构造采样器（E09 接线点）。

    真实模型调用需项目 owner 的账户连接；连接缺失时抛出
    ``ProjectLLMConfigurationError``（fail-closed，不回退环境变量）。
    """
    from modules.evolution.llm_sampler import ProjectLLMSampler
    from modules.project.facade import open_project_llm_client

    client = await open_project_llm_client(db, novel_id).__aenter__()
    return ProjectLLMSampler(client)


async def resolve_scene_sampler(
    *, provider: str, novel_id: str, db: Any | None = None
) -> Any:
    factory = _SAMPLER_REGISTRY.get(provider)
    if factory is None:
        raise SamplerNotWiredError(
            f"evolution sampler provider {provider!r} is not wired; "
            "refusing to fabricate observations (E09 wiring pending)"
        )
    built = factory(db, novel_id) if db is not None else factory(novel_id)
    if hasattr(built, "__await__"):
        built = await built
    return built


_SAMPLER_REGISTRY["project_llm"] = project_llm_sampler_factory
