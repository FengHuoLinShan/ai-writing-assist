from dataclasses import replace
from uuid import uuid4

import pytest

from core.config import Settings, get_settings
from core.service_keys import WORLD_READ_MAP_SPATIAL_BRIEF
from modules.evidence.compilation.contracts import CompileOptions
from modules.evidence.compilation.markdown_renderer import render_compiled_context
from modules.evidence.compilation.services.compiled_context import CompiledContext
from modules.evidence.compilation.services.context_compiler import ContextCompiler
from modules.evidence.compilation.services.loaders import map_spatial_loader
from modules.evidence.compilation.services.loaders.map_spatial_loader import (
    MapSpatialLoader,
    map_spatial_capability,
)
from modules.evidence.compilation.services.planned_retrieval_service import (
    PlannedContextRetrievalService,
)
from modules.evidence.compilation.services.protocol import Loader
from modules.world.map_spatial_brief_schemas import (
    MapSpatialBriefItem,
    MapSpatialBriefResponse,
)


def _brief() -> MapSpatialBriefResponse:
    return MapSpatialBriefResponse(
        scene_id=str(uuid4()),
        scene_index=4,
        chapter_index=3,
        items=[
            MapSpatialBriefItem(
                node_id=str(uuid4()),
                revision_id=str(uuid4()),
                title="海港区",
                content='{"当前地点":[{"label":"白潮港"}]}',
                content_hash="a" * 64,
                revision_hash="b" * 64,
                geometry_hash="c" * 64,
                source_hashes=["d" * 64],
            )
        ],
        omitted_count=2,
    )


def _install_brief_reader(monkeypatch, result, calls):
    async def read(_db, request):
        calls.append(request)
        return result

    monkeypatch.setattr(
        map_spatial_loader,
        "get",
        lambda key: read if key == WORLD_READ_MAP_SPATIAL_BRIEF else None,
    )


@pytest.mark.parametrize(
    ("action", "capability"),
    [
        ("writing.generate", "writing.generate"),
        ("writing.targeted_revision", "writing.targeted_revision"),
        ("writing.semantic_review", "writing.semantic_review"),
        ("writing.conflict_check.ai_review", "writing.conflict_check.ai_review"),
        ("story.script.generate", "story.script"),
        ("story.one_click.simulate", "story.one_click"),
        ("world.ask", "world.ask"),
    ],
)
def test_map_capabilities_are_independent(action, capability):
    assert map_spatial_capability(action) == capability
    assert map_spatial_capability("assistant.turn") is None


def test_map_spatial_capability_setting_is_empty_by_default_and_splits_values(
    monkeypatch,
):
    monkeypatch.delenv("MAP_SPATIAL_ENABLED_CAPABILITIES", raising=False)
    assert Settings().map_spatial_enabled_capabilities == ()
    monkeypatch.setenv(
        "MAP_SPATIAL_ENABLED_CAPABILITIES", " writing.generate, world.ask "
    )
    assert Settings().map_spatial_enabled_capabilities == (
        "writing.generate",
        "world.ask",
    )


@pytest.mark.asyncio
async def test_context_compiler_injects_on_flag_and_is_silent_off(
    monkeypatch,
):
    calls = []
    brief = _brief()
    _install_brief_reader(monkeypatch, brief, calls)
    enabled = replace(
        get_settings(), map_spatial_enabled_capabilities=("writing.generate",)
    )
    monkeypatch.setattr(map_spatial_loader, "get_settings", lambda: enabled)
    monkeypatch.setattr(
        "modules.evidence.compilation.services.context_compiler.get_settings",
        lambda: enabled,
    )
    options = CompileOptions(
        novel_id=str(uuid4()),
        task="继续当前场景",
        scope="project",
        consumer_action="writing.generate",
        scene_id=str(uuid4()),
        chapter_index=3,
        excluded_asset_ids={
            "map_spatial_nodes": ["excluded-node"],
            "world_entities": ["excluded-entity"],
        },
    )

    compiler = ContextCompiler([MapSpatialLoader()])
    bundle = await compiler.compile(object(), options)
    sections = compiler._build_sections(bundle, options)
    rendered = render_compiled_context(
        CompiledContext(
            sections=sections,
            total_tokens=sum(section.token_count for section in sections),
        )
    )

    assert len(calls) == 1
    assert calls[0]["scene_id"] == str(options.scene_id)
    assert calls[0]["chapter_index"] == 3
    assert set(calls[0]["excluded_ids"]) == {
        "map_spatial_node:excluded-node",
        "world_entity:excluded-entity",
    }
    assert (
        bundle.map_spatial_brief["items"][0]["revision_id"]
        == brief.items[0].revision_id
    )
    assert "空间简报" in rendered and "参考：已保存地图" in rendered
    map_section = next(section for section in sections if section.key == "map_spatial")
    assert map_section.retrieval_metadata["map_baseline"][0]["revision_hash"] == (
        brief.items[0].revision_hash
    )
    assert map_section.retrieval_metadata["omitted_count"] == 2

    calls.clear()
    disabled = replace(get_settings(), map_spatial_enabled_capabilities=())
    monkeypatch.setattr(map_spatial_loader, "get_settings", lambda: disabled)
    monkeypatch.setattr(
        "modules.evidence.compilation.services.context_compiler.get_settings",
        lambda: disabled,
    )
    off_compiler = ContextCompiler([MapSpatialLoader()])
    off = await off_compiler.compile(object(), options)
    off_sections = off_compiler._build_sections(off, options)
    assert calls == []
    assert off.map_spatial_brief is None
    assert all(section.key != "map_spatial" for section in off_sections)


@pytest.mark.asyncio
async def test_planned_world_ask_retrieval_loads_map_only_when_enabled(monkeypatch):
    calls = []
    _install_brief_reader(monkeypatch, _brief(), calls)
    settings = replace(get_settings(), map_spatial_enabled_capabilities=("world.ask",))
    monkeypatch.setattr(map_spatial_loader, "get_settings", lambda: settings)

    class EmptyRagLoader(Loader):
        @property
        def name(self):
            return "rag_chunks"

        async def load(self, _db, _options, _bundle):
            return None

    options = CompileOptions(
        novel_id=str(uuid4()),
        task="白潮港在哪里",
        scope="world",
        consumer_action="world.ask",
        chapter_index=3,
    )
    bundle = await PlannedContextRetrievalService(EmptyRagLoader()).retrieve(
        object(), options
    )

    assert len(calls) == 1
    assert calls[0]["scene_id"] is None
    assert calls[0]["query_text"] == options.task
    assert bundle.map_spatial_brief["items"]
