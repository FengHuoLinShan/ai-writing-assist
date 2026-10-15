import uuid

import pytest

from modules.evidence.compilation.assistant_dossier_tools import (
    OPERATIONS_SPEC,
    _read_object_dossier_brief,
)
from modules.evidence.compilation.object_dossier_schemas import ObjectDossierBriefRequest


def test_object_brief_r0_operation_is_read_only_and_traces_full_request_schema():
    spec = OPERATIONS_SPEC["evidence.object_dossier_brief.read"]
    assert spec["permission"] == "read"
    assert spec["risk_level"] == "R0"
    assert spec["fee_category"] == "free"
    assert spec["reversibility"] == "read_only"
    assert "apply" not in spec
    assert spec["trace_rule"]["parameter_fields"] == tuple(
        ObjectDossierBriefRequest.model_fields
    )


@pytest.mark.asyncio
async def test_object_brief_assistant_operation_rejects_cross_project_novel_id():
    request = ObjectDossierBriefRequest(
        novel_id=str(uuid.uuid4()),
        scene_id=str(uuid.uuid4()),
        entity_ids=[str(uuid.uuid4())],
    )
    with pytest.raises(ValueError, match="match the active Assistant project"):
        await _read_object_dossier_brief(
            object(), str(uuid.uuid4()), request, context=None
        )
