"""演化场景步采样器解析（V4 E07.e）。

生产 LLM 采样器属 E09 真实质量验证的接线范围；未注册时 fail-closed，
绝不伪造观察（计划 §8：缺失来源不造假通过）。

工厂返回 **async context manager**（返修 R1）：项目 LLM 客户端的
``__aexit__`` 由任务生命周期显式持有——进入即取得，退出即释放，
绝不只调 ``__aenter__`` 而丢失退出责任。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

_SAMPLER_REGISTRY: dict[str, Callable[..., Any]] = {
    "project_llm": None,  # 占位：project_llm_sampler_factory 定义后回填
}


class SamplerNotWiredError(Exception):
    """项目未接演化采样器：fail-closed，不伪造观察。"""


def register_scene_sampler(provider: str, factory: Callable[..., Any]) -> None:
    """注册采样器工厂（测试与 E09 生产接线共用入口）。

    工厂签名 ``(db, novel_id) -> async context manager yielding sampler``；
    普通可等待对象也接受（测试替身），由 :func:`resolve_scene_sampler`
    包装成 context manager。
    """
    _SAMPLER_REGISTRY[provider] = factory


@asynccontextmanager
async def _wrap_plain(value: Any) -> AsyncIterator[Any]:
    yield value


@asynccontextmanager
async def project_llm_sampler_factory(db, novel_id: str) -> AsyncIterator[Any]:
    """生产 provider：经项目 LLM 入口构造采样器（E09 接线点）。

    真实模型调用需项目 owner 的账户连接；连接缺失时抛出
    ``ProjectLLMConfigurationError``（fail-closed，不回退环境变量）。
    客户端的进入/退出由本 context manager 成对持有。
    """
    from modules.evolution.llm_sampler import ProjectLLMSampler
    from modules.project.facade import open_project_llm_client

    async with open_project_llm_client(db, novel_id) as client:
        yield ProjectLLMSampler(client)


@asynccontextmanager
async def resolve_scene_sampler(
    *, provider: str, novel_id: str, db: Any | None = None
) -> AsyncIterator[Any]:
    """解析采样器为 async context manager；未接线时 fail-closed。"""
    factory = _SAMPLER_REGISTRY.get(provider)
    if factory is None:
        raise SamplerNotWiredError(
            f"evolution sampler provider {provider!r} is not wired; "
            "refusing to fabricate observations (E09 wiring pending)"
        )
    built = factory(db, novel_id)
    if hasattr(built, "__aenter__"):
        async with built as sampler:
            yield sampler
        return
    if hasattr(built, "__await__"):
        built = await built
    async with _wrap_plain(built) as sampler:
        yield sampler


_SAMPLER_REGISTRY["project_llm"] = project_llm_sampler_factory
