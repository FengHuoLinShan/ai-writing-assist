import uuid

import pytest

from core.errors import ConflictError, NotFoundError
from modules.evidence.compilation.assistant_dossier_tools import (
    OPERATIONS_SPEC,
    ReadAssistantObjectDossierBrief,
    _read_object_dossier_brief,
)
from modules.assistant.contracts import AssistantOperationContext
from modules.assistant.schemas import WorkContext


def test_object_brief_r0_operation_is_read_only_and_traces_full_request_schema():
    spec = OPERATIONS_SPEC["evidence.object_dossier_brief.read"]
    assert spec["permission"] == "read"
    assert spec["risk_level"] == "R0"
    assert spec["fee_category"] == "free"
    assert spec["reversibility"] == "read_only"
    assert "apply" not in spec
    assert set(spec["trace_rule"]["parameter_fields"]) == set(
        ReadAssistantObjectDossierBrief.model_fields
    )


@pytest.mark.asyncio
async def test_object_brief_assistant_operation_rejects_missing_or_frozen_scope():
    request = ReadAssistantObjectDossierBrief(
        scene_id=str(uuid.uuid4()),
        entity_ids=[str(uuid.uuid4())],
    )
    with pytest.raises(NotFoundError, match="作者范围"):
        await _read_object_dossier_brief(
            object(), str(uuid.uuid4()), request, context=None
        )
    context = AssistantOperationContext(
        run_id=str(uuid.uuid4()),
        owner_id=str(uuid.uuid4()),
        work=WorkContext(
            scope="project",
            page="scene",
            context_confirmation_id=uuid.uuid4(),
            context_confirmation_action="story.character_card.generate",
        ),
    )
    with pytest.raises(ConflictError, match="不能展开"):
        await _read_object_dossier_brief(
            object(), str(uuid.uuid4()), request, context=context
        )
