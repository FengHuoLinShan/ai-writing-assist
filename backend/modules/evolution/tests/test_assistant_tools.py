from uuid import uuid4

import pytest
from pydantic import ValidationError

from modules.evolution import assistant_tools


def test_reading_preview_requires_spatial_discovery_and_rescan_range_is_valid():
    base = {
        "operation_id": str(uuid4()),
        "mode": "bootstrap",
        "end_chapter": 3,
    }
    with pytest.raises(ValidationError, match="空间发现"):
        assistant_tools.PrepareSpatialReading(**base)
    request = assistant_tools.PrepareSpatialReading(**base, discover_spatial=True)
    assert request.discover_spatial is True
    with pytest.raises(ValidationError, match="补扫范围"):
        assistant_tools.PrepareSpatialRescan(
            run_key="run-1",
            operation_id=uuid4(),
            from_scene_index=4,
            through_scene_index=3,
        )


@pytest.mark.asyncio
async def test_reading_operation_only_prepares_and_rechecks_free_authorization_preview(
    monkeypatch,
):
    from modules.evolution import workflow

    calls = []

    async def preview(_db, novel_id, request):
        calls.append((novel_id, request.operation_id))
        return {"fingerprint": "a" * 64, "call_count": 4, "additional_budget": 4}

    monkeypatch.setattr(workflow, "preview_reading", preview)
    args = assistant_tools.PrepareSpatialReading(
        operation_id=uuid4(), mode="bootstrap", end_chapter=3, discover_spatial=True
    )
    prepared = await assistant_tools._reading_preview(None, "novel-1", args)
    result = await assistant_tools._reading_apply(None, "novel-1", args, prepared)
    assert len(calls) == 2
    assert result["authorization_required"] is True
    assert result["authorization_preview"]["additional_budget"] == 4


@pytest.mark.asyncio
async def test_rescan_operation_never_starts_spatial_rescan(monkeypatch):
    from modules.evolution import spatial_rescan

    calls = []

    async def preview(_db, novel_id, run_key, request):
        calls.append((novel_id, run_key, request.operation_id))
        return {"fingerprint": "b" * 64, "call_count": 2, "additional_budget": 2}

    monkeypatch.setattr(spatial_rescan, "preview_spatial_rescan", preview)
    args = assistant_tools.PrepareSpatialRescan(
        run_key="run-1",
        operation_id=uuid4(),
        from_scene_index=0,
        through_scene_index=2,
    )
    prepared = await assistant_tools._rescan_preview(None, "novel-1", args)
    result = await assistant_tools._rescan_apply(None, "novel-1", args, prepared)
    assert len(calls) == 2
    assert result["authorization_required"] is True
    assert result["authorization_preview"]["call_count"] == 2
