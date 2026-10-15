from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from core.errors import ConflictError
from modules.evidence.compilation.services.compiled_context import (
    CompiledContext,
    ContextItem,
    ContextSection,
    Tier,
)
from modules.evidence.compilation.services.confirmation_service import (
    ContextConfirmationService,
    _core_context_fingerprint,
    _map_spatial_baseline,
    execution_compile_options,
)
from modules.evidence.compilation.services.snapshot_service import ContextSnapshotService


def _baseline(revision_id: str) -> dict:
    return {
        "node_id": "map-node",
        "title": "海港区",
        "revision_id": revision_id,
        "revision_hash": f"{revision_id:0<64}"[:64],
        "geometry_hash": "b" * 64,
        "content_hash": "c" * 64,
        "source_hashes": ["d" * 64],
    }


def _compiled(revision_id: str, *, core_content: str = "原有参考资料") -> CompiledContext:
    baseline = _baseline(revision_id)
    source = {
        "type": "map_spatial",
        "id": baseline["node_id"],
        "label": baseline["title"],
        "revision_id": revision_id,
        "revision_hash": baseline["revision_hash"],
        "geometry_hash": baseline["geometry_hash"],
        "content_hash": baseline["content_hash"],
        "source_hashes": baseline["source_hashes"],
    }
    return CompiledContext(
        sections=[
            ContextSection(
                key="world_entities",
                tier=Tier.P1,
                content=core_content,
                sources=[{"type": "world_entity", "id": "entity-1"}],
            ),
            ContextSection(
                key="map_spatial",
                tier=Tier.P3,
                content="白潮港在海港区。",
                sources=[source],
                retrieval_metadata={
                    "map_baseline": [baseline],
                    "scene_id": "scene-1",
                    "chapter_index": 3,
                },
                items=[
                    ContextItem(
                        key=f"map_spatial:{baseline['node_id']}:{revision_id}",
                        content="白潮港在海港区。",
                        source=source,
                    )
                ],
            ),
        ]
    )


@pytest.mark.asyncio
async def test_confirmation_omits_only_changed_map_and_keeps_core_context(monkeypatch):
    import modules.evidence.compilation.services.confirmation_service as confirmation

    novel_id = str(uuid4())
    original = _compiled("revision-a")
    current = _compiled("revision-b")

    class Compiler:
        async def compile_with_tiers(self, *_args, **_kwargs):
            return current

    record = SimpleNamespace(
        compile_options={
            "novel_id": novel_id,
            "task": "写当前场景",
            "scope": "project",
            "consumer_action": "writing.generate",
            "map_spatial_baseline": _map_spatial_baseline(original),
            "compiled_context_core_fingerprint": _core_context_fingerprint(original),
        }
    )
    service = ContextConfirmationService(compiler=Compiler())

    async def require_confirmation(*_args, **_kwargs):
        return record

    monkeypatch.setattr(service, "require_confirmation", require_confirmation)
    monkeypatch.setattr(
        confirmation,
        "_scene_memory_port",
        lambda: SimpleNamespace(scene_memory_v1_version=lambda: 1),
    )

    result = await service.compile_from_confirmation(
        object(),
        novel_id=novel_id,
        action="writing.generate",
        confirmation_id=str(uuid4()),
    )

    assert [section.key for section in result.sections] == ["world_entities"]
    assert result.selection_trace["map_spatial_staleness"]["status"] == "changed"
    assert any("地图版本发生变化" in warning for warning in result.warnings)
    assert any(item.key.startswith("map_spatial:") for item in result.omitted_items)


@pytest.mark.asyncio
async def test_confirmation_still_blocks_when_required_core_context_changes(monkeypatch):
    import modules.evidence.compilation.services.confirmation_service as confirmation

    novel_id = str(uuid4())
    original = _compiled("revision-a")
    current = _compiled("revision-b", core_content="改变后的必查资料")

    class Compiler:
        async def compile_with_tiers(self, *_args, **_kwargs):
            return current

    record = SimpleNamespace(
        compile_options={
            "novel_id": novel_id,
            "task": "写当前场景",
            "scope": "project",
            "consumer_action": "writing.generate",
            "map_spatial_baseline": _map_spatial_baseline(original),
            "compiled_context_core_fingerprint": _core_context_fingerprint(original),
        }
    )
    service = ContextConfirmationService(compiler=Compiler())

    async def require_confirmation(*_args, **_kwargs):
        return record

    monkeypatch.setattr(service, "require_confirmation", require_confirmation)
    monkeypatch.setattr(
        confirmation,
        "_scene_memory_port",
        lambda: SimpleNamespace(scene_memory_v1_version=lambda: 1),
    )

    with pytest.raises(ConflictError, match="参考资料已变化"):
        await service.compile_from_confirmation(
            object(),
            novel_id=novel_id,
            action="writing.generate",
            confirmation_id=str(uuid4()),
        )

    assert execution_compile_options(record.compile_options) == {
        "novel_id": novel_id,
        "task": "写当前场景",
        "scope": "project",
        "consumer_action": "writing.generate",
    }


@pytest.mark.asyncio
async def test_snapshot_compares_map_head_at_read_time_without_mutating_snapshot(
    monkeypatch,
):
    from core import container
    from core.service_keys import WORLD_READ_MAP_NODE_HEADS

    novel_id = uuid4()
    snapshot_id = uuid4()
    expected = _baseline("revision-a")
    metadata = {"map_spatial": {"retrieval_metadata": {"map_baseline": [expected]}}}
    record = SimpleNamespace(
        id=snapshot_id,
        novel_id=novel_id,
        consumer_novel_id=None,
        task_id=None,
        workflow_id=None,
        phase="draft",
        operation="writing.generate",
        scene_id="scene-1",
        scene_index=4,
        chapter_index=3,
        context_mode="canonical",
        include_pending_objects=False,
        status="succeeded",
        attempt=1,
        prompt_hash="e" * 64,
        prompt_name="writing.generate.v1",
        model="offline-test",
        compile_options={},
        included_asset_ids={},
        excluded_asset_ids={},
        context_summary={},
        section_metadata=metadata,
        token_metadata={},
        rendered_context=None,
        result_refs=[],
        error_kind=None,
        error_message=None,
        rendered_context_expires_at=None,
        created_at=datetime.now(),
        updated_at=None,
    )

    class Repository:
        async def get(self, _db, _snapshot_id):
            return record

    head = {
        "node_id": expected["node_id"],
        "title": expected["title"],
        "status": "adopted",
        "revision_id": expected["revision_id"],
        "geometry_hash": expected["geometry_hash"],
        "source_hashes": expected["source_hashes"],
    }
    current_heads = {expected["node_id"]: head}

    async def read_heads(_db, requested_novel_id, node_ids):
        assert str(requested_novel_id) == str(novel_id)
        assert node_ids == [expected["node_id"]]
        return current_heads

    original_get = container.get
    monkeypatch.setattr(
        container,
        "get",
        lambda key: read_heads if key == WORLD_READ_MAP_NODE_HEADS else original_get(key),
    )
    service = ContextSnapshotService(repository=Repository())

    current = await service.get_context_snapshot(
        object(), novel_id=str(novel_id), snapshot_id=snapshot_id
    )
    assert current.map_staleness[0]["status"] == "current"

    current_heads = {
        expected["node_id"]: {**head, "revision_id": "revision-b"}
    }
    changed = await service.get_context_snapshot(
        object(), novel_id=str(novel_id), snapshot_id=snapshot_id
    )
    assert changed.map_staleness[0]["status"] == "changed"

    async def unavailable(*_args, **_kwargs):
        raise RuntimeError("offline")

    monkeypatch.setattr(container, "get", lambda key: unavailable)
    offline = await service.get_context_snapshot(
        object(), novel_id=str(novel_id), snapshot_id=snapshot_id
    )
    assert offline.map_staleness[0]["status"] == "unavailable"
    assert record.section_metadata == metadata
