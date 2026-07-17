"""Deep-import relation provenance persistence tests."""

from unittest.mock import Mock, patch

import pytest

from modules.imports.entity_extraction.scene_entity_persistence import (
    SceneEntityPersistenceGateway,
)
from modules.imports.llm_schemas import (
    AliasRelationExtractionOutput,
    ExtractedRelation,
    Phase2bRelationObservation,
)


class _FakeSavepoint:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeNestedDb:
    def begin_nested(self):
        return _FakeSavepoint()


@pytest.mark.asyncio
async def test_phase2a_relation_payload_keeps_scene_provenance_when_merged() -> None:
    gateway = SceneEntityPersistenceGateway(Mock())
    relation = ExtractedRelation(
        source_name="克莱恩",
        target_name="伦纳德",
        relation_type="colleague",
        quote="他们是同事。",
    )

    with (
        patch(
            "modules.world.facade.find_working_entity_ids_by_names",
            autospec=True,
            return_value={"克莱恩": "entity-1", "伦纳德": "entity-2"},
        ),
        patch(
            "modules.world.facade.create_or_merge_relation",
            autospec=True,
            return_value={"action": "merged", "relation": Mock(id="relation-1")},
        ) as create_or_merge,
        patch.object(gateway, "_record_quote_evidence", autospec=True),
    ):
        created = await gateway.persist_relations(
            _FakeNestedDb(),
            "novel-1",
            [relation],
            scene_index=4,
            source_chapter_index=8,
            workflow_id="workflow-1",
            scene_id="scene-4",
            context_snapshot_id="snapshot-4",
        )

    assert created == 0
    payload = create_or_merge.await_args.args[2]
    assert payload["review_meta"] == {
        "source": "deep_import",
        "workflow_id": "workflow-1",
        "scene_id": "scene-4",
        "scene_index": 4,
        "source_chapter_index": 8,
        "context_snapshot_id": "snapshot-4",
        "quote": "他们是同事。",
        "evidence_refs": [
            {
                "source_type": "scene",
                "scene_id": "scene-4",
                "scene_index": 4,
                "source_chapter_index": 8,
                "quote": "他们是同事。",
            }
        ],
    }


@pytest.mark.asyncio
async def test_phase2b_relation_payload_keeps_workflow_and_scene_evidence() -> None:
    gateway = SceneEntityPersistenceGateway(Mock())
    output = AliasRelationExtractionOutput(
        relations=[
            Phase2bRelationObservation(
                source_ref="entity-001",
                target_ref="entity-002",
                relation_type="sibling",
                persistence_scope="enduring",
                directionality="directed",
                claim_status="established",
                description="克莱恩是梅丽莎的哥哥",
                basis="正文明确亲属关系",
                evidence_quotes=["克莱恩是梅丽莎的哥哥。"],
                confidence=0.92,
            )
        ]
    )

    with (
        patch(
            "modules.world.facade.list_entities",
            autospec=True,
            return_value=[{"id": "entity-1"}, {"id": "entity-2"}],
        ),
        patch(
            "modules.world.facade.create_or_merge_relation",
            autospec=True,
            return_value={"action": "created", "relation": Mock(id="relation-2")},
        ) as create_or_merge,
        patch.object(gateway, "_record_quote_evidence", autospec=True),
    ):
        result = await gateway.persist_alias_relation_output(
            _FakeNestedDb(),
            "novel-1",
            output,
            scene_index=9,
            workflow_id="workflow-2",
            scene_id="scene-9",
            current_scene_text="克莱恩是梅丽莎的哥哥。",
            context_bundle={
                "context_fingerprint": "context-fingerprint",
                "identity_candidates": [
                    {"prompt_ref": "entity-001", "name": "克莱恩", "aliases": []},
                    {"prompt_ref": "entity-002", "name": "梅丽莎", "aliases": []},
                ],
                "_entity_ref_map": {
                    "entity-001": "entity-1",
                    "entity-002": "entity-2",
                },
                "_relation_ref_map": {},
            },
        )

    assert result["aliases"] == 0
    assert result["relations"] == 1
    assert result["uncertain_count"] == 0
    payload = create_or_merge.await_args.args[2]
    review_meta = payload["review_meta"]
    assert review_meta["source"] == "deep_import"
    assert review_meta["workflow_id"] == "workflow-2"
    assert review_meta["scene_id"] == "scene-9"
    assert review_meta["claim_status"] == "established"
    assert review_meta["basis"] == "正文明确亲属关系"
    assert review_meta["confidence"] == 0.92
    assert review_meta["evidence_quotes"] == ["克莱恩是梅丽莎的哥哥。"]
