"""Consultation freezes one original candidate group and its actual manuscript."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from core.config import get_settings
from core.errors import ConflictError
from infrastructure.tasks.models import AsyncTask
from modules.collaboration import cases
from modules.collaboration.contracts import CaseCreate, Grant
from modules.evidence.facade import collect_creative_manifest
from modules.imports.contracts import ImportConsultScope
from modules.imports.facade import get_review_summary, inspect_consultation_scope
from modules.writing.facade import create_draft_only
from tests.utils import _create_entity


async def test_exact_import_dossier_never_adopts_or_expands_candidate_group(
    db_session, test_project_id, monkeypatch
):
    db, nid = db_session, test_project_id
    settings = replace(
        get_settings(), assistant_enabled=True, collaboration_v2_enabled=True
    )
    monkeypatch.setattr(cases, "get_settings", lambda: settings)
    await create_draft_only(db, nid, 1, "港口", "青港又名北港。城外仍是一片荒野。")
    entity = await _create_entity(db, nid, "location", "青港")
    entity.created_by = "ai_import"
    entity.content_json = {
        "aliases": [
            {
                "alias": "北港",
                "kind": "name",
                "status": "candidate",
                "source_chapter_index": 1,
            },
            {
                "alias": "南港",
                "kind": "identity",
                "status": "candidate",
                "source_chapter_index": 1,
            },
        ]
    }
    await db.flush()
    summary = await get_review_summary(db, nid)
    key = next(
        value["key"]
        for value in summary["candidates"]
        if value["fields"].get("alias") == "北港"
    )
    before = await db.scalar(select(func.count()).select_from(AsyncTask))
    scope = ImportConsultScope(chapter_from=1, chapter_to=1, asset_keys=[key])
    dossier = await inspect_consultation_scope(db, nid, scope)
    assert len(dossier["items"]) == 1 and dossier["items"][0]["key"] == key
    assert "青港又名北港" in dossier["sources"][0]["text"]
    bound = scope.model_copy(update={"expected_hash": dossier["fingerprint"]})
    grant = Grant(
        resources=[],
        read_kinds=[],
        import_scope=bound,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    case = await cases.create_case(
        db,
        nid,
        CaseCreate(
            operation_id=uuid4(),
            goal="查清这个称呼是否为同一地点",
            recipe_id="import_consult",
            grant=grant,
        ),
    )
    material = await collect_creative_manifest(db, nid, grant, 1)
    assert (
        case["requests_used"] == 0 and material.resources[0].kind == "import_review_group"
    )
    assert await db.scalar(select(func.count()).select_from(AsyncTask)) == before
    assert entity.content_json["aliases"][0]["status"] == "candidate"
    entity.content_json = {
        **entity.content_json,
        "aliases": [
            {
                "alias": "北港",
                "kind": "identity",
                "status": "candidate",
                "source_chapter_index": 1,
            }
        ],
    }
    await db.flush()
    with pytest.raises(ConflictError, match="原待决组"):
        await collect_creative_manifest(db, nid, grant, 1)
