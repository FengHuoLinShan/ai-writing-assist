"""Scene memory 契约的 port 解析（AO-5 / ADR-0031）。

evidence 编译不再顶层 import story 契约：CompileOptions 的契约版本缺省
为 None（编译时解析 story 当前版本），维度解析经 ``story.scene_source``
port。本文件锁定缺省解析与显式版本两条路径。
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.container import container_scope, get
from modules.evidence.compilation.contracts import (
    CompileOptions,
    SceneMemoryContractPort,
)
from modules.evidence.compilation.services.loaders.memory_records_loader import (
    _scene_memory_dimensions,
)
from modules.story.scene_source_port import SceneSourcePort


def test_compile_options_default_defers_to_current_version() -> None:
    options = CompileOptions(novel_id="n-1", task="t", scope="s")

    assert options.scene_memory_contract_version is None
    replaced = replace(options, scene_memory_contract_version=1)
    assert replaced.scene_memory_contract_version == 1


def test_scene_memory_port_satisfies_consumer_protocol() -> None:
    port = get("story.scene_source")

    assert isinstance(port, SceneSourcePort)
    protocol_methods = [
        name
        for name in SceneMemoryContractPort.__protocol_attrs__  # type: ignore[attr-defined]
    ]
    for name in protocol_methods:
        assert callable(getattr(port, name, None)), name


def test_scene_memory_dimensions_resolve_default_version() -> None:
    with container_scope({"story.scene_source": SceneSourcePort()}):
        assert _scene_memory_dimensions(None) == (
            "entities",
            "relations",
            "locations",
            "knowledge",
            "timeline",
            "causality",
        )
        # 显式冻结版本按冻结口径解析（旧 confirmation 按 V1 回放）。
        assert _scene_memory_dimensions(1) == (
            "entities",
            "relations",
            "locations",
            "knowledge",
        )


@pytest.mark.asyncio
async def test_scene_port_review_resolution_reader(monkeypatch) -> None:
    """review_resolution_sources 经 port 读 Scene contract，缺失返回 None。"""
    from modules.evidence.compilation.services import review_resolution_sources

    get_scene = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "modules.story.outline_state.facade.get_scene_contract", get_scene
    )
    with container_scope({"story.scene_source": SceneSourcePort()}):
        with pytest.raises(ValueError, match="来源场景不存在"):
            await review_resolution_sources.read_sources(
                SimpleNamespace(),
                novel_id="n-1",
                scene_id="s-1",
                source_manifest={},
                chapter_from=1,
                chapter_to=2,
            )
    get_scene.assert_awaited_once()
