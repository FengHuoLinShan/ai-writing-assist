"""演化场景步采样器解析（V4 E07.e）。

生产 LLM 采样器属 E09 真实质量验证的接线范围；未注册时 fail-closed，
绝不伪造观察（计划 §8：缺失来源不造假通过）。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_SAMPLER_REGISTRY: dict[str, Callable[[str], Any]] = {}


class SamplerNotWiredError(Exception):
    """项目未接演化采样器：fail-closed，不伪造观察。"""


def register_scene_sampler(provider: str, factory: Callable[[str], Any]) -> None:
    """注册采样器工厂（测试与 E09 生产接线共用入口）。"""
    _SAMPLER_REGISTRY[provider] = factory


def resolve_scene_sampler(*, provider: str, novel_id: str) -> Any:
    factory = _SAMPLER_REGISTRY.get(provider)
    if factory is None:
        raise SamplerNotWiredError(
            f"evolution sampler provider {provider!r} is not wired; "
            "refusing to fabricate observations (E09 wiring pending)"
        )
    return factory(novel_id)
