"""Real PostgreSQL owner, cutoff, DI and read-only HTTP boundary for briefs."""

import hashlib
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from core.errors import NotFoundError
from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import BOOTSTRAP_ACCOUNT_ID, AccountPrincipal
from modules.account.models import Account
from modules.evidence.compilation.facade import read_object_dossier_brief
from modules.evolution.contracts import SourceRevisionRef
from modules.evolution.evidence_read import read_evolution_object_patterns
from modules.evolution.ledger import _claim_ranges_current
from modules.evolution.ledger_contracts import LedgerClaim
from modules.evolution.models import EvolutionLedgerEntry, EvolutionLedgerRevision
from modules.project.models import Project
from modules.story.continuity.models import MemorySceneCheckpoint
from modules.story.outline_state.models import Scene
from modules.world.dossier_service import WorldObjectDossierService
from modules.world.models import CoreEntity, WorldObjectDossierEntry
from modules.world.schemas.dossier import DossierEntryCreate, DossierFacingRef
from modules.writing.models import WritingDraft

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


async def test_object_brief_http_is_owner_scoped_and_read_only(db_session, async_client):
    owner_two, novel_id, other_novel_id = uuid4(), uuid4(), uuid4()
    scene_id, entity_id, other_entity_id = uuid4(), uuid4(), uuid4()
    if await db_session.get(Account, BOOTSTRAP_ACCOUNT_ID) is None:
        db_session.add(Account(id=BOOTSTRAP_ACCOUNT_ID, support_code="brief-owner"))
    db_session.add(Account(id=owner_two, support_code="brief-other"))
    await db_session.flush()
    db_session.add_all(
        [
            Project(id=novel_id, owner_id=BOOTSTRAP_ACCOUNT_ID, title="简报测试"),
            Project(id=other_novel_id, owner_id=owner_two, title="他人作品"),
        ]
    )
    await db_session.flush()
    db_session.add(Scene(id=scene_id, novel_id=novel_id, scene_index=0))
    db_session.add_all(
        [
            CoreEntity(
                id=entity_id,
                novel_id=novel_id,
                entity_type="location",
                name="北门",
                status="canonical",
            ),
            CoreEntity(
                id=other_entity_id,
                novel_id=other_novel_id,
                entity_type="location",
                name="他人地点",
                status="canonical",
            ),
        ]
    )
    await db_session.flush()
    await WorldObjectDossierService().create_entry(
        db_session,
        str(novel_id),
        str(entity_id),
        DossierEntryCreate(
            facing=DossierFacingRef(kind="core", key="history"),
            content="作者秘密：北门下有密道",
            visibility="secret",
        ),
    )
    await WorldObjectDossierService().create_entry(
        db_session,
        str(novel_id),
        str(entity_id),
        DossierEntryCreate(
            facing=DossierFacingRef(kind="core", key="history"),
            content="北门已封",
            visibility="public",
        ),
    )
    await db_session.flush()

    models = (
        MemorySceneCheckpoint,
        WorldObjectDossierEntry,
        EvolutionLedgerRevision,
    )

    async def row_counts():
        return [
            await db_session.scalar(select(func.count()).select_from(model))
            for model in models
        ]

    before = await row_counts()
    url = "/api/evidence/compilation/object-dossier-brief"
    request = {
        "novel_id": str(novel_id),
        "scene_id": str(scene_id),
        "entity_ids": [str(entity_id)],
        "reveal_mode": "author_full",
        "include_patterns": True,
    }
    response = await async_client.post(url, json=request)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["novel_id"] == str(novel_id)
    assert body["scene_index"] == 0
    assert body["pattern_items"] == []
    assert body["pattern_fingerprint"]
    assert any("北门下有密道" in item.get("content", "") for item in body["world_items"])
    safe = await async_client.post(
        url,
        json={**request, "reveal_mode": "author_safe", "include_patterns": False},
    )
    assert safe.status_code == 200, safe.text
    assert "北门下有密道" not in safe.text
    assert safe.json()["checkpoint_refs"] == []
    assert safe.json()["pattern_items"] == []
    assert await row_counts() == before

    demo_token = bind_principal(
        AccountPrincipal(
            account_id=BOOTSTRAP_ACCOUNT_ID,
            status="active",
            identity_type="demo_readonly",
            support_code="brief-demo",
            access_scope="demo_readonly",
            demo_project_id=novel_id,
        )
    )
    try:
        for mode in ("author_full", "author_safe"):
            denied = await async_client.post(url, json={**request, "reveal_mode": mode})
            assert denied.status_code in {403, 404}
            assert "北门下有密道" not in denied.text
            assert body["fingerprint"] not in denied.text
        with pytest.raises(NotFoundError):
            await read_object_dossier_brief(
                db_session,
                novel_id=str(novel_id),
                scene_id=str(scene_id),
                entity_ids=[str(entity_id)],
                reveal_mode="author_full",
                include_patterns=True,
            )
    finally:
        reset_principal(demo_token)
    assert await row_counts() == before

    db_session.add_all(
        [
            WorldObjectDossierEntry(
                novel_id=novel_id,
                entity_id=entity_id,
                entry_group_id=uuid4(),
                revision_number=1,
                facing_kind="core",
                facing_key="history",
                content=f"隐藏资料{i:03d}",
                source="author",
                visibility="secret",
                status="active",
            )
            for i in range(251)
        ]
    )
    await db_session.flush()
    after_seed = await row_counts()
    safe_after = await async_client.post(
        url,
        json={**request, "reveal_mode": "author_safe", "include_patterns": False},
    )
    assert safe_after.status_code == 200, safe_after.text
    for key in (
        "world_items",
        "world_fingerprint",
        "fingerprint",
        "coverage",
        "omissions",
        "omitted_count",
    ):
        assert safe_after.json()[key] == safe.json()[key], key
    world_reader = WorldObjectDossierService()
    proven = await world_reader.read(
        db_session,
        str(novel_id),
        str(entity_id),
        as_of_scene_id=str(scene_id),
        visibility_filter="public",
        visible_contents=["北门已封"],
    )
    unproven = await world_reader.read(
        db_session,
        str(novel_id),
        str(entity_id),
        as_of_scene_id=str(scene_id),
        visibility_filter="public",
        visible_contents=[],
    )
    assert proven.total_count == 1
    assert [item.content for item in proven.entries] == ["北门已封"]
    assert unproven.total_count == 0
    assert await row_counts() == after_seed

    foreign_entity = await async_client.post(
        url, json={**request, "entity_ids": [str(other_entity_id)]}
    )
    assert foreign_entity.status_code == 404
    foreign_owner = await async_client.post(
        url, json={**request, "novel_id": str(other_novel_id)}
    )
    assert foreign_owner.status_code in {403, 404}
    missing_cutoff = await async_client.post(
        url, json={**request, "scene_id": str(uuid4())}
    )
    assert missing_cutoff.status_code == 404
    assert await row_counts() == after_seed


async def test_pattern_reader_rejects_future_and_stale_source_on_postgres(db_session):
    novel_id, scene_id, future_scene_id, entity_id = (uuid4() for _ in range(4))
    if await db_session.get(Account, BOOTSTRAP_ACCOUNT_ID) is None:
        db_session.add(Account(id=BOOTSTRAP_ACCOUNT_ID, support_code="brief-ledger"))
    await db_session.flush()
    db_session.add(Project(id=novel_id, owner_id=BOOTSTRAP_ACCOUNT_ID, title="台账范围"))
    await db_session.flush()
    db_session.add_all(
        [
            Scene(id=scene_id, novel_id=novel_id, scene_index=0),
            Scene(id=future_scene_id, novel_id=novel_id, scene_index=1),
            CoreEntity(
                id=entity_id,
                novel_id=novel_id,
                entity_type="location",
                name="北门",
                status="canonical",
            ),
        ]
    )
    await db_session.flush()

    content = "北门今日确实关闭"
    draft = WritingDraft(
        novel_id=novel_id,
        chapter_index=0,
        content=content,
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
        status="published",
        version_number=1,
    )
    db_session.add(draft)
    await db_session.flush()

    source_ref = SourceRevisionRef(
        novel_id=str(novel_id),
        source_kind="chapter_draft",
        draft_id=str(draft.id),
        content_hash="a" * 64,
        chapter_identity="chapter:0",
        start_offset=0,
        end_offset=5,
        range_hash=SourceRevisionRef.compute_range_hash("a" * 64, 0, 5),
        source_revision=1,
        segmentation_version=1,
        source_visibility="canonical",
    )

    def claim(source_scene_id, source_scene_index):
        return LedgerClaim(
            category="conditional_behavior",
            label="钟声后检查北门",
            statement="守卫听见钟声后会检查北门",
            conditions=["听见钟声"],
            realm="history",
            modality="hypothesis",
            confidence=0.8,
            targets=[
                {
                    "domain": "world",
                    "kind": "entity",
                    "target_id": str(entity_id),
                    "version_fingerprint": "entity-version",
                    "binding": "resolved",
                    "label": "北门",
                }
            ],
            evidence=[
                {
                    "observation_id": "observation-1",
                    "position": {
                        "scene_id": str(source_scene_id),
                        "scene_index": source_scene_index,
                        "chapter_index": 0,
                    },
                    "modality": "character_statement",
                    "quote": "我听见钟声就去检查北门",
                    "source_ref": source_ref,
                    "role": "support",
                }
            ],
            dependencies=[
                {
                    "run_key": "missing-run",
                    "attempt_id": "missing-attempt",
                    "scene_id": str(scene_id),
                    "scene_index": 0,
                    "source_manifest_hash": "b" * 64,
                }
            ],
            method_fingerprint="c" * 64,
        )

    for suffix, source_scene_id, source_index in (
        ("future", future_scene_id, 1),
        ("stale", scene_id, 0),
    ):
        entry = EvolutionLedgerEntry(
            novel_id=novel_id,
            origin_key=(suffix[0] * 64),
            category="conditional_behavior",
            head_revision=1,
            author_decision_json={},
        )
        db_session.add(entry)
        await db_session.flush()
        db_session.add(
            EvolutionLedgerRevision(
                novel_id=novel_id,
                entry_id=entry.id,
                revision=1,
                operation_key=(suffix[0] * 64),
                request_hash="d" * 64,
                scene_index=0,
                kind="extract",
                body_json={
                    "claim": claim(source_scene_id, source_index).model_dump(mode="json"),
                    "review": {"verdict": "supported"},
                    "author_decision": {},
                },
            )
        )
    await db_session.flush()
    assert await _claim_ranges_current(db_session, str(novel_id), claim(scene_id, 0)) == (
        "source_changed"
    )
    result = await read_evolution_object_patterns(
        db_session,
        novel_id=str(novel_id),
        scene_id=str(scene_id),
        entity_ids=[str(entity_id)],
    )
    assert result["items"] == []
    assert result["omitted_count"] == 2
    assert any("超出截止 Scene" in item for item in result["omissions"])
    assert any("证据已失效" in item for item in result["omissions"])
