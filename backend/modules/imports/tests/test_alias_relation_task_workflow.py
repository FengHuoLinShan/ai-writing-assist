from __future__ import annotations

import copy
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest import mock

import pytest

from modules.imports.entity_extraction import (
    scene_entity_alias_relation_task as task_module,
)
from modules.imports.entity_extraction.scene_entity_alias_relation_task import (
    AliasRelationTaskWorkflow,
)
from modules.imports.entity_extraction.scene_entity_extraction import (
    SceneEntityExtractionService,
)
from modules.imports.llm_schemas import (
    AliasRelationExtractionOutput,
    ExtractedAlias,
    ExtractedRelation,
)

pytestmark = pytest.mark.asyncio

NOVEL_ID = "11111111-1111-1111-1111-111111111111"
CONFIRMATION_ID = "22222222-2222-2222-2222-222222222222"


def _confirmation() -> dict:
    return {
        "id": CONFIRMATION_ID,
        "novel_id": NOVEL_ID,
        "action": "world.alias_relations.extract",
        "task": "只补抽确认 Scene 的别名和关系",
        "scope": "chapter",
        "context_mode": "working",
        "include_pending_objects": True,
        "selected_asset_ids": {"world_entities": ["entity-1"]},
        "excluded_asset_ids": {"world_entities": ["entity-2"]},
        "user_note": "不要引入未选中设定",
        "compile_options": {"novel_id": NOVEL_ID, "task": "alias"},
        "warnings": [],
        "compiled_at": "2026-07-14T00:00:00+00:00",
    }


def _snapshot(profile_hash: str = "profile-1") -> dict:
    return {
        "version": "1",
        "novel_id": NOVEL_ID,
        "profile_hash": profile_hash,
    }


class _Service:
    def __init__(self) -> None:
        self.text = "林舟又被称为舟哥，他在铁塔前拜见朱延。"
        self.scene = {
            "id": "scene-1",
            "novel_id": NOVEL_ID,
            "scene_index": 1,
            "title": "铁塔会面",
            "goal": "见到朱延",
            "chapter_ids": ["1"],
            "status": "canonical",
        }
        self.snapshot_calls = 0
        self.persist_calls: list[dict] = []

    async def _get_scenes(self, _db, _nid):
        return [copy.deepcopy(self.scene)]

    @staticmethod
    def _scene_id(scene):
        return scene["id"]

    @staticmethod
    def _scene_source_chapter_index(_scene):
        return 1

    async def _load_scene_chapters(self, _db, _scene):
        return self.text

    async def _create_phase2b_snapshot(self, *_args, **_kwargs):
        self.snapshot_calls += 1
        return SimpleNamespace(id="snapshot-1")

    @staticmethod
    def _error_kind(_exc):
        return "provider_error"

    async def _call_alias_relation_extraction(self, *_args, **_kwargs):
        return AliasRelationExtractionOutput(
            aliases=[
                ExtractedAlias(
                    entity_name="林舟",
                    alias="舟哥",
                    quote="林舟又被称为舟哥",
                )
            ],
            relations=[
                ExtractedRelation(
                    source_name="林舟",
                    target_name="朱延",
                    relation_type="师徒",
                    quote="拜见朱延",
                )
            ],
        )

    async def _persist_alias_relation_output(self, _db, _novel_id, _output, **kwargs):
        self.persist_calls.append(kwargs)
        return {"aliases": 1, "relations": 1}


async def _prepare(
    workflow: AliasRelationTaskWorkflow,
    *,
    existing_manifest: dict | None = None,
    confirmation: dict | None = None,
    snapshot: dict | None = None,
    scene_ids: list[str] | None = None,
):
    return await workflow.prepare(
        SimpleNamespace(),
        novel_id=NOVEL_ID,
        task_id="task-1",
        confirmation_id=CONFIRMATION_ID,
        confirmation=confirmation or _confirmation(),
        start_chapter=1,
        end_chapter=1,
        scene_ids=scene_ids if scene_ids is not None else ["scene-1"],
        llm_execution_snapshot=snapshot or _snapshot(),
        project_settings={"llm": {"model": "frozen-model"}},
        existing_manifest=existing_manifest,
    )


async def test_prepare_snapshots_exact_sources_and_consumes_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.world import facade as world_facade

    service = _Service()
    entities = [
        {"id": "entity-1", "name": "林舟", "entity_type": "character"},
        {"id": "entity-2", "name": "禁止出现", "entity_type": "secret"},
        {"id": "entity-3", "name": "朱延", "entity_type": "character"},
    ]
    monkeypatch.setattr(
        world_facade, "list_entities", mock.AsyncMock(return_value=entities)
    )
    workflow = AliasRelationTaskWorkflow(service)

    prepared = await _prepare(workflow)

    manifest = prepared["manifest"]
    runtime_scene = prepared["runtime_plan"]["scenes"][0]
    scene_manifest = manifest["scenes"][0]
    assert service.snapshot_calls == 1
    assert scene_manifest["context_snapshot_id"] == "snapshot-1"
    assert scene_manifest["semantic_fingerprint"]
    assert scene_manifest["source_text_hash"]
    assert scene_manifest["entity_index_hash"] == manifest["entity_index_hash"]
    assert manifest["confirmation_fingerprint"]
    assert manifest["llm_profile_hash"] == "profile-1"
    assert service.text not in repr(manifest)
    assert "不要引入未选中设定" in runtime_scene["entity_index"]
    assert "禁止出现" not in runtime_scene["entity_index"]

    replay = await _prepare(workflow, existing_manifest=manifest)
    assert replay["manifest"] == manifest
    assert service.snapshot_calls == 1


@pytest.mark.parametrize("drift", ["text", "entity", "confirmation", "profile"])
async def test_prepare_rejects_every_external_source_drift(
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    from modules.world import facade as world_facade

    service = _Service()
    entities = [
        {"id": "entity-1", "name": "林舟", "entity_type": "character"},
        {"id": "entity-3", "name": "朱延", "entity_type": "character"},
    ]
    listed = mock.AsyncMock(return_value=entities)
    monkeypatch.setattr(world_facade, "list_entities", listed)
    workflow = AliasRelationTaskWorkflow(service)
    prepared = await _prepare(workflow)
    confirmation = _confirmation()
    snapshot = _snapshot()
    if drift == "text":
        service.text += "后来又增加了一句。"
    elif drift == "entity":
        listed.return_value = [
            *entities,
            {"id": "entity-4", "name": "黑塔", "entity_type": "location"},
        ]
    elif drift == "confirmation":
        confirmation["user_note"] = "已更改的用户边界"
    else:
        snapshot = _snapshot("profile-2")

    with pytest.raises(ValueError, match="changed|fingerprint"):
        await _prepare(
            workflow,
            existing_manifest=prepared["manifest"],
            confirmation=confirmation,
            snapshot=snapshot,
        )


async def test_execute_produces_schema_valid_bounded_receipt_without_db_argument(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.world import facade as world_facade

    service = _Service()
    monkeypatch.setattr(
        world_facade,
        "list_entities",
        mock.AsyncMock(
            return_value=[
                {"id": "entity-1", "name": "林舟", "entity_type": "character"},
                {"id": "entity-3", "name": "朱延", "entity_type": "character"},
            ]
        ),
    )
    workflow = AliasRelationTaskWorkflow(service)
    prepared = await _prepare(workflow)

    receipt = await workflow.execute(
        runtime_plan=prepared["runtime_plan"],
        project_settings={"llm": {"model": "frozen-model"}},
        novel_id=NOVEL_ID,
    )

    assert receipt["receipt_hash"]
    assert receipt["scenes"][0]["status"] == "succeeded"
    assert receipt["total_timeout_s"] > 0
    assert receipt["concurrency"] > 0
    assert receipt["llm_timeout_s"] > 0
    output = AliasRelationExtractionOutput.model_validate(receipt["scenes"][0]["output"])
    assert output.aliases[0].alias == "舟哥"


async def test_execute_uses_phase2b_effective_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.world import facade as world_facade

    service = _Service()
    monkeypatch.setattr(
        world_facade,
        "list_entities",
        mock.AsyncMock(
            return_value=[
                {"id": "entity-1", "name": "林舟", "entity_type": "character"},
                {"id": "entity-3", "name": "朱延", "entity_type": "character"},
            ]
        ),
    )
    effective = mock.Mock(return_value=777.0)
    monkeypatch.setattr(
        task_module,
        "_effective_alias_relation_total_timeout_seconds",
        effective,
    )
    workflow = AliasRelationTaskWorkflow(service)
    prepared = await _prepare(workflow)

    receipt = await workflow.execute(
        runtime_plan=prepared["runtime_plan"],
        project_settings={"llm": {"model": "frozen-model"}},
        novel_id=NOVEL_ID,
    )

    assert receipt["total_timeout_s"] == 777.0
    effective.assert_called_once()


async def test_finalize_revalidates_then_uses_strict_atomic_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.context import facade as context_facade
    from modules.world import facade as world_facade

    service = _Service()
    monkeypatch.setattr(
        world_facade,
        "list_entities",
        mock.AsyncMock(
            return_value=[
                {"id": "entity-1", "name": "林舟", "entity_type": "character"},
                {"id": "entity-3", "name": "朱延", "entity_type": "character"},
            ]
        ),
    )
    succeeded = mock.AsyncMock()
    monkeypatch.setattr(context_facade, "succeed_context_snapshot", succeeded)
    monkeypatch.setattr(context_facade, "fail_context_snapshot", mock.AsyncMock())
    workflow = AliasRelationTaskWorkflow(service)
    prepared = await _prepare(workflow)
    receipt = await workflow.execute(
        runtime_plan=prepared["runtime_plan"],
        project_settings={"llm": {"model": "frozen-model"}},
        novel_id=NOVEL_ID,
    )

    finalized = await workflow.finalize(
        SimpleNamespace(),
        novel_id=NOVEL_ID,
        task_id="task-1",
        confirmation_id=CONFIRMATION_ID,
        confirmation=_confirmation(),
        start_chapter=1,
        end_chapter=1,
        scene_ids=["scene-1"],
        llm_execution_snapshot=_snapshot(),
        project_settings={"llm": {"model": "frozen-model"}},
        manifest=prepared["manifest"],
        receipt=receipt,
    )

    assert finalized["summary"]["total_aliases"] == 1
    assert finalized["summary"]["total_relations"] == 1
    assert service.persist_calls[0]["strict"] is True
    succeeded.assert_awaited_once()


async def test_finalize_rejects_duplicate_receipt_scenes_before_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.context import facade as context_facade
    from modules.world import facade as world_facade

    service = _Service()
    monkeypatch.setattr(
        world_facade,
        "list_entities",
        mock.AsyncMock(
            return_value=[
                {"id": "entity-1", "name": "林舟", "entity_type": "character"},
                {"id": "entity-3", "name": "朱延", "entity_type": "character"},
            ]
        ),
    )
    succeeded = mock.AsyncMock()
    monkeypatch.setattr(context_facade, "succeed_context_snapshot", succeeded)
    monkeypatch.setattr(context_facade, "fail_context_snapshot", mock.AsyncMock())
    workflow = AliasRelationTaskWorkflow(service)
    prepared = await _prepare(workflow)
    receipt = await workflow.execute(
        runtime_plan=prepared["runtime_plan"],
        project_settings={"llm": {"model": "frozen-model"}},
        novel_id=NOVEL_ID,
    )
    tampered = copy.deepcopy(receipt)
    tampered["scenes"].append(copy.deepcopy(tampered["scenes"][0]))
    unsigned = {key: value for key, value in tampered.items() if key != "receipt_hash"}
    tampered["receipt_hash"] = task_module._stable_hash(unsigned)

    with pytest.raises(ValueError, match="duplicate scene ids"):
        await workflow.finalize(
            SimpleNamespace(),
            novel_id=NOVEL_ID,
            task_id="task-1",
            confirmation_id=CONFIRMATION_ID,
            confirmation=_confirmation(),
            start_chapter=1,
            end_chapter=1,
            scene_ids=["scene-1"],
            llm_execution_snapshot=_snapshot(),
            project_settings={"llm": {"model": "frozen-model"}},
            manifest=prepared["manifest"],
            receipt=tampered,
        )

    assert service.persist_calls == []
    succeeded.assert_not_awaited()


async def test_finalize_keeps_context_snapshot_result_refs_scene_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.context import facade as context_facade
    from modules.world import facade as world_facade

    class _TwoSceneService(_Service):
        def __init__(self) -> None:
            super().__init__()
            self.scenes = [
                self.scene,
                {**self.scene, "id": "scene-2", "scene_index": 2, "title": "再会"},
            ]

        async def _get_scenes(self, _db, _nid):
            return copy.deepcopy(self.scenes)

        async def _create_phase2b_snapshot(
            self,
            _db,
            _nid,
            scene,
            _chapters_text,
            _entity_index,
            **_kwargs,
        ):
            return SimpleNamespace(id=f"snapshot-{scene['id']}")

        async def _persist_alias_relation_output(
            self,
            _db,
            _novel_id,
            _output,
            **kwargs,
        ):
            refs = kwargs["result_refs"]
            refs.append(
                {
                    "type": "entity_relation",
                    "id": f"relation-{kwargs['scene_id']}",
                }
            )
            return {"aliases": 0, "relations": 1}

    service = _TwoSceneService()
    monkeypatch.setattr(
        world_facade,
        "list_entities",
        mock.AsyncMock(
            return_value=[
                {"id": "entity-1", "name": "林舟", "entity_type": "character"},
                {"id": "entity-3", "name": "朱延", "entity_type": "character"},
            ]
        ),
    )
    succeeded = mock.AsyncMock()
    monkeypatch.setattr(context_facade, "succeed_context_snapshot", succeeded)
    monkeypatch.setattr(context_facade, "fail_context_snapshot", mock.AsyncMock())
    workflow = AliasRelationTaskWorkflow(service)
    prepared = await _prepare(workflow, scene_ids=["scene-1", "scene-2"])
    receipt = await workflow.execute(
        runtime_plan=prepared["runtime_plan"],
        project_settings={"llm": {"model": "frozen-model"}},
        novel_id=NOVEL_ID,
    )

    finalized = await workflow.finalize(
        SimpleNamespace(),
        novel_id=NOVEL_ID,
        task_id="task-1",
        confirmation_id=CONFIRMATION_ID,
        confirmation=_confirmation(),
        start_chapter=1,
        end_chapter=1,
        scene_ids=["scene-1", "scene-2"],
        llm_execution_snapshot=_snapshot(),
        project_settings={"llm": {"model": "frozen-model"}},
        manifest=prepared["manifest"],
        receipt=receipt,
    )

    assert finalized["result_refs"] == [
        {"type": "entity_relation", "id": "relation-scene-1"},
        {"type": "entity_relation", "id": "relation-scene-2"},
    ]
    assert [call.kwargs["result_refs"] for call in succeeded.await_args_list] == [
        [{"type": "entity_relation", "id": "relation-scene-1"}],
        [{"type": "entity_relation", "id": "relation-scene-2"}],
    ]


async def test_task_strict_persistence_does_not_swallow_relation_failure() -> None:
    from modules.world import facade as world_facade

    @asynccontextmanager
    async def _savepoint():
        yield

    db = SimpleNamespace(begin_nested=_savepoint)
    output = AliasRelationExtractionOutput(
        aliases=[ExtractedAlias(entity_name="林舟", alias="舟哥")],
        relations=[
            ExtractedRelation(
                source_name="林舟",
                target_name="朱延",
                relation_type="师徒",
            )
        ],
    )
    with (
        mock.patch.object(
            world_facade,
            "find_working_entity_ids_by_names",
            autospec=True,
            return_value={"林舟": "entity-1", "朱延": "entity-2"},
        ),
        mock.patch.object(
            world_facade,
            "append_candidate_alias",
            autospec=True,
            return_value=True,
        ),
        mock.patch.object(
            world_facade,
            "create_or_merge_relation",
            autospec=True,
            side_effect=RuntimeError("relation write failed"),
        ),
        mock.patch(
            "modules.imports.entity_extraction.scene_entity_persistence."
            "SceneEntityPersistenceGateway._record_quote_evidence",
            autospec=True,
        ),
    ):
        with pytest.raises(RuntimeError, match="relation write failed"):
            await SceneEntityExtractionService()._persist_alias_relation_output(
                db,  # type: ignore[arg-type]
                NOVEL_ID,
                output,
                scene_index=1,
                workflow_id="task-1",
                scene_id="scene-1",
                strict=True,
            )
