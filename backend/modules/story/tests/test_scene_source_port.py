"""Story 场景只读 SPI 适配器（AO-5 / ADR-0031）。

evidence 编译与 world 地图经组合根注册的 ``story.scene_source`` port 消费
story 场景事实，不再顶层 import story facade。本文件锁定 adapter 的委托
行为与空态语义。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from modules.story.scene_source_port import SceneSourcePort


@pytest.mark.asyncio
async def test_scene_port_delegates_read_only_calls(monkeypatch) -> None:
    db = SimpleNamespace()
    scene = SimpleNamespace(id="scene-1", scene_index=3)
    get_scene = AsyncMock(return_value=scene)
    presence = AsyncMock(return_value=SimpleNamespace(nodes=(), segments=()))
    reveal = AsyncMock(return_value=SimpleNamespace(has_policy=True, revealed=False))
    monkeypatch.setattr(
        "modules.story.outline_state.facade.get_scene_contract", get_scene
    )
    monkeypatch.setattr("modules.story.facade.project_scene_presence", presence)
    monkeypatch.setattr("modules.story.facade.get_reader_reveal_decision", reveal)
    port = SceneSourcePort()

    contract = await port.get_scene_contract(db, "novel-1", "scene-1")
    report = await port.project_scene_presence(db, "novel-1", through_scene_index=3)
    decision = await port.get_reader_reveal_decision(
        db,
        novel_id="novel-1",
        target_type="entity",
        target_id="entity-1",
        cutoff_chapter=4,
    )

    assert contract is scene
    assert report is not None
    assert decision.has_policy is True and decision.revealed is False
    get_scene.assert_awaited_once_with(db, "novel-1", "scene-1")
    presence.assert_awaited_once_with(db, "novel-1", through_scene_index=3)
    reveal.assert_awaited_once_with(
        db,
        novel_id="novel-1",
        target_type="entity",
        target_id="entity-1",
        cutoff_chapter=4,
    )


@pytest.mark.asyncio
async def test_scene_port_empty_and_missing_states(monkeypatch) -> None:
    monkeypatch.setattr(
        "modules.story.outline_state.facade.get_scene_contract",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "modules.story.facade.project_scene_presence",
        AsyncMock(return_value=None),
    )
    port = SceneSourcePort()

    assert await port.get_scene_contract(SimpleNamespace(), "novel-1", "no") is None
    assert (
        await port.project_scene_presence(
            SimpleNamespace(), "novel-1", through_scene_index=0
        )
        is None
    )


def test_scene_memory_contract_metadata() -> None:
    port = SceneSourcePort()

    assert port.scene_memory_current_version() == 2
    assert port.scene_memory_v1_version() == 1
    assert port.scene_memory_dimensions(1) == (
        "entities",
        "relations",
        "locations",
        "knowledge",
    )
    assert port.scene_memory_dimensions(2) == (
        "entities",
        "relations",
        "locations",
        "knowledge",
        "timeline",
        "causality",
    )
    with pytest.raises(ValueError, match="unsupported Scene memory contract"):
        port.scene_memory_dimensions(99)
