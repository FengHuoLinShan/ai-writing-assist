"""Deep-import relation provenance persistence tests."""

from unittest.mock import Mock, patch

import pytest

from modules.imports.entity_extraction.scene_entity_persistence import (
    SceneEntityPersistenceGateway,
)
from modules.imports.llm_schemas import (
    AliasRelationExtractionOutput,
    ExtractedRelation,
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
            ExtractedRelation(
                source_name="克莱恩",
                target_name="梅丽莎",
                relation_type="sibling",
                quote="克莱恩是梅丽莎的哥哥。",
            )
        ]
    )

    with (
        patch(
            "modules.world.facade.find_working_entity_ids_by_names",
            autospec=True,
            return_value={"克莱恩": "entity-1", "梅丽莎": "entity-2"},
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
        )

    assert result == {"aliases": 0, "relations": 1}
    payload = create_or_merge.await_args.args[2]
    assert payload["review_meta"] == {
        "source": "deep_import",
        "workflow_id": "workflow-2",
        "scene_id": "scene-9",
        "scene_index": 9,
        "quote": "克莱恩是梅丽莎的哥哥。",
        "evidence_refs": [
            {
                "source_type": "scene",
                "scene_id": "scene-9",
                "scene_index": 9,
                "quote": "克莱恩是梅丽莎的哥哥。",
            }
        ],
    }
