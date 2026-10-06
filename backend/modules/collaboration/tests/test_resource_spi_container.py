"""collaboration 资源 SPI 的容器解析（AO-5 / ADR-0031）。

L2 provider adapter（story/writing creative.py）在组合根装配
``collaboration.resources`` 时经容器解析 SPI 类型，不再顶层 import
modules.collaboration.contracts。本文件锁定：注册的类型对象不变、
装配出的端口形状不变。
"""

from __future__ import annotations

from core.container import get
from modules.collaboration.contracts import (
    CreativeResourcePort,
    ResourceSnapshot,
)
from modules.story import creative as story_creative
from modules.story.assistant_information_tools import KINDS
from modules.world import creative as world_creative
from modules.writing import creative as writing_creative


def test_resource_spi_types_resolved_from_container() -> None:
    assert get("collaboration.ResourceSnapshot") is ResourceSnapshot
    assert get("collaboration.CreativeResourcePort") is CreativeResourcePort


def test_story_resource_ports_keep_shape() -> None:
    ports = story_creative.ports()
    assert set(ports) == {"scene", *KINDS}
    for kind, port in ports.items():
        assert isinstance(port, CreativeResourcePort)
        assert callable(port.inventory)
        assert port.read is story_creative.read
        assert port.validate is story_creative.validate
        assert port.apply is story_creative.apply


def test_writing_resource_port_keeps_shape() -> None:
    port = writing_creative.port()
    assert isinstance(port, CreativeResourcePort)
    assert port.inventory is writing_creative.inventory
    assert port.read is writing_creative.read
    assert port.validate is writing_creative.validate
    assert port.apply is writing_creative.apply


def test_world_resource_port_keeps_shape() -> None:
    port = world_creative.port()
    assert isinstance(port, CreativeResourcePort)
    assert port.inventory is world_creative.inventory
    assert port.read is world_creative.read
    assert port.validate is world_creative.validate
    assert port.apply is world_creative.apply
