from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pydantic import ValidationError as SchemaError
from sqlalchemy import func, select

from core.errors import ConflictError, ValidationError
from modules.evidence.compilation.services.compiled_context import (
    CompiledContext,
    ContextItem,
    ContextSection,
    Tier,
)
from modules.world.map_atlas_models import MapAtlasRevision
from modules.world.map_structure_geometry import (
    geometry_hash,
    layout,
    route_key,
    structure_reference_manifest,
)
from modules.world.map_structure_review import apply_revision_changes, changed_items
from modules.world.map_structure_schemas import (
    MapDocument,
    MapFeature,
    MapGenerateRequest,
    MapNodeCreate,
    MapRevisionReview,
    MapSaveRequest,
    MapSource,
    SpatialConstraint,
)
from modules.world.map_structure_service import MapStructureService
from modules.world.map_structure_workflow import (
    relation_key,
    structure_inputs,
    update_extracted_relations,
)
from modules.world.models import CoreEntity


def points():
    return MapDocument(
        features=[
            MapFeature(
                id=key,
                kind="location",
                label=label,
                points=[{"x": x, "y": 10}],
                locked=True,
            )
            for key, label, x in [
                ("a", "甲城", 10),
                ("b", "乙城", 100),
                ("c", "丙城", 200),
            ]
        ]
    )


def source_range():
    draft_id = uuid.uuid4()
    return MapSource(
        kind="source_range",
        id=draft_id,
        source_hash="a" * 64,
        source_ref=dict(
            draft_id=str(draft_id),
            chapter_index=1,
            version_number=1,
            content_mode="canonical",
            start_offset=0,
            end_offset=8,
            source_hash="a" * 64,
            range_hash="b" * 64,
        ),
    )


def prepared_source(ref, excluded=False):
    item = ContextItem(
        key="source",
        content="甲城在乙城以北",
        status="canonical",
        token_count=8,
        source={"source_ref": ref.source_ref},
        selection_state="excluded" if excluded else "author_pinned",
    )
    return SimpleNamespace(
        confirmation=SimpleNamespace(context_fingerprint="f" * 64),
        compiled=CompiledContext(
            sections=[
                ContextSection(
                    key="author_pinned_material",
                    tier=Tier.P1,
                    content=item.content,
                    status="mixed",
                    items=[item],
                )
            ]
        ),
    )


async def saved_map(db, project_id, document=None):
    service = MapStructureService()
    node = await service.create_node(
        db, project_id, MapNodeCreate(title="演示城市", level="city")
    )
    saved = await service.save(
        db,
        project_id,
        node["id"],
        MapSaveRequest(
            base_revision_id=node["current_revision_id"], document=document or points()
        ),
    )
    return service, node, saved


def test_manual_selection_limits_and_original_ids():
    payload = dict(
        operation_id=uuid.uuid4(),
        base_revision_id=uuid.uuid4(),
        context_confirmation_id=uuid.uuid4(),
        feature_ids=["a"],
    )
    assert MapGenerateRequest(**payload).location_ids == []
    for changes in (
        {"feature_ids": []},
        {"feature_ids": ["a", "a"]},
        {"feature_ids": [f"p{i}" for i in range(21)]},
        {"base_revision_id": None},
    ):
        with pytest.raises(SchemaError):
            MapGenerateRequest(**(payload | changes))
    with pytest.raises(SchemaError):
        MapRevisionReview(base_revision_id=None, action="adopt", change_keys=[])


async def test_manual_source_range_selection_never_creates_canon(
    db_session, test_project_id
):
    ref = source_range()
    document = points()
    document.features[0].sources = [ref]
    with patch.object(
        MapStructureService, "source", autospec=True, return_value="甲城在乙城以北"
    ):
        _, node, saved = await saved_map(db_session, test_project_id, document)
        original = await db_session.scalar(select(func.count(CoreEntity.id)))
        _, selected_doc, _, symbols, source_keys = await structure_inputs(
            db_session,
            test_project_id,
            node["id"],
            {"base_revision_id": saved.id, "feature_ids": ["a"]},
            prepared_source(ref),
        )
        assert symbols == [{"key": "a", "name": "甲城", "kind": "location"}]
        assert selected_doc.features[0].points == document.features[0].points
        assert source_keys["a"]
        assert await db_session.scalar(select(func.count(CoreEntity.id))) == original
        with pytest.raises(ValidationError, match="未进入本次确认"):
            await structure_inputs(
                db_session,
                test_project_id,
                node["id"],
                {"base_revision_id": saved.id, "feature_ids": ["a"]},
                prepared_source(ref, True),
            )
        with pytest.raises(ValidationError, match="还没有"):
            await structure_inputs(
                db_session,
                test_project_id,
                node["id"],
                {"base_revision_id": saved.id, "feature_ids": ["b"]},
                prepared_source(ref),
            )
        with pytest.raises(ValidationError, match="不属于"):
            await structure_inputs(
                db_session,
                test_project_id,
                node["id"],
                {"base_revision_id": saved.id, "feature_ids": ["foreign"]},
                prepared_source(ref),
            )


def test_relation_identity_ignores_quote_and_evidence_order():
    relation = dict(
        subject="a",
        target="b",
        relation="north",
        via=[],
        source_keys=["one"],
        quote="甲城在北",
    )
    assert relation_key(relation) == relation_key(
        relation | {"quote": "甲城在乙城以北", "source_keys": ["two", "one"]}
    )
    assert relation_key(relation) != relation_key(relation | {"relation": "south"})


async def test_local_update_preserves_manual_failed_and_out_of_scope_relations():
    document = points()
    old_task, new_task = uuid.uuid4(), uuid.uuid4()
    document.constraints = [
        SpatialConstraint(
            id="automatic",
            subject="a",
            target="b",
            relation="north",
            generated_by_task_id=old_task,
        ),
        SpatialConstraint(id="manual", subject="a", target="b", relation="east"),
        SpatialConstraint(
            id="failed-scope",
            subject="c",
            target="b",
            relation="north",
            generated_by_task_id=old_task,
        ),
    ]
    await update_extracted_relations(
        None,
        str(uuid.uuid4()),
        str(uuid.uuid4()),
        document,
        [
            SpatialConstraint(
                id="new",
                subject="a",
                target="b",
                relation="south",
                generated_by_task_id=new_task,
            )
        ],
        {"a", "b"},
    )
    assert {item.id for item in document.constraints} == {"manual", "failed-scope", "new"}
    assert [item.points for item in document.features] == [
        item.points for item in points().features
    ]


async def test_provenance_forgery_rejected_and_manual_edits_demoted(
    db_session, test_project_id
):
    service, node, saved = await saved_map(db_session, test_project_id)
    doc = saved.document.model_copy(deep=True)
    generated = SpatialConstraint(
        id="generated",
        subject="a",
        target="b",
        relation="north",
        generated_by_task_id=uuid.uuid4(),
    )
    doc.constraints = [generated]
    with pytest.raises(ValidationError, match="不能指定"):
        await service.save(
            db_session,
            test_project_id,
            node["id"],
            MapSaveRequest(base_revision_id=saved.id, document=doc),
        )
    # Only a domain-owned generation/review path may introduce the marker.
    adopted = await service.save(
        db_session,
        test_project_id,
        node["id"],
        MapSaveRequest(base_revision_id=saved.id, document=doc),
        _trusted_generation=True,
    )
    doc.constraints[0].relation = "south"
    edited = await service.save(
        db_session,
        test_project_id,
        node["id"],
        MapSaveRequest(base_revision_id=adopted.id, document=doc),
    )
    assert edited.document.constraints[0].generated_by_task_id is None


async def test_generated_route_removal_preserves_author_control_points(
    db_session, test_project_id
):
    service, node, saved = await saved_map(db_session, test_project_id)
    task_id = uuid.uuid4()
    document = saved.document.model_copy(deep=True)
    document.constraints = [
        SpatialConstraint(
            id="route-relation",
            subject="a",
            target="b",
            relation="connects",
            generated_by_task_id=task_id,
        )
    ]
    document = layout(document).document
    original = MapAtlasRevision(
        novel_id=uuid.UUID(test_project_id),
        node_id=uuid.UUID(node["id"]),
        base_revision_id=uuid.UUID(saved.id),
        task_id=task_id,
        status="candidate",
        document=document.model_dump(mode="json"),
        geometry_hash=geometry_hash(document),
        problems=[],
    )
    db_session.add(original)
    await db_session.flush()
    plain = document.model_copy(deep=True)
    assert not await update_extracted_relations(
        db_session, test_project_id, node["id"], plain, [], {"a", "b"}
    )
    assert len(plain.features) == 3 and not plain.constraints
    altered = document.model_copy(deep=True)
    altered.features[-1].points[0].x += 25
    refreshed = altered.constraints[0].model_copy(deep=True)
    refreshed.generated_by_task_id = uuid.uuid4()
    refreshed.sources = [source_range()]
    await update_extracted_relations(
        db_session, test_project_id, node["id"], altered, [refreshed], {"a", "b"}
    )
    assert altered.constraints[0].generated_by_task_id == task_id
    problems = await update_extracted_relations(
        db_session, test_project_id, node["id"], altered, [], {"a", "b"}
    )
    assert problems[0].code == "manual_route_preserved"
    assert len(altered.constraints) == 1
    assert altered.features[-1].points[0].x == document.features[-1].points[0].x + 25


def test_partial_selection_expands_relation_route_and_changed_endpoints():
    baseline = points()
    candidate = baseline.model_copy(deep=True)
    candidate.features[1].points[0].x = 250
    candidate.features[2].note = "不相关的说明"
    candidate.constraints.append(
        SpatialConstraint(id="route", subject="a", target="b", relation="connects")
    )
    candidate = layout(candidate).document
    merged, applied, expanded = apply_revision_changes(
        baseline, candidate, ["constraint:route"]
    )
    assert set(applied) == {
        "constraint:route",
        "feature:b",
        f"feature:{route_key('route')}",
    }
    assert set(expanded) == set(applied) - {"constraint:route"}
    assert merged.features[2].note == ""
    assert changed_items(merged, candidate) == {"feature:c"}
    with pytest.raises(ValidationError, match="不属于"):
        apply_revision_changes(baseline, candidate, ["feature:unknown"])


def test_partial_delete_closes_images_bindings_and_dependent_geometry():
    baseline = points()
    baseline.features.append(
        MapFeature(
            id="drawing",
            kind="road",
            label="手工路线",
            points=[{"x": 10, "y": 10}, {"x": 100, "y": 10}],
            depends_on=["a", "b"],
        )
    )
    image_id, annotation_id = uuid.uuid4(), uuid.uuid4()
    baseline = MapDocument.model_validate(
        baseline.model_dump()
        | {
            "images": [{"page_id": image_id, "role": "illustration", "feature_id": "a"}],
            "annotation_bindings": [{"annotation_id": annotation_id, "feature_id": "a"}],
        }
    )
    candidate = MapDocument(features=baseline.features[1:3])
    with pytest.raises(ConflictError) as blocked:
        apply_revision_changes(baseline, candidate, ["feature:a"])
    assert blocked.value.context == {"required_change_keys": ["feature:drawing"]}
    merged, applied, _ = apply_revision_changes(
        baseline, candidate, ["feature:a", "feature:drawing"]
    )
    assert {item.id for item in merged.features} == {"b", "c"}
    assert set(applied) == {
        "feature:a",
        "feature:drawing",
        f"image:{image_id}",
        f"binding:{annotation_id}",
    }
    assert not merged.images and not merged.annotation_bindings


async def test_partial_adoption_keeps_remaining_candidate_and_rejects_stale(
    db_session, test_project_id
):
    service, node, saved = await saved_map(db_session, test_project_id)
    doc = saved.document.model_copy(deep=True)
    for feature in doc.features:
        feature.note = feature.id
    confirmation_id = uuid.uuid4()
    candidate = MapAtlasRevision(
        novel_id=uuid.UUID(test_project_id),
        node_id=uuid.UUID(node["id"]),
        base_revision_id=uuid.UUID(saved.id),
        status="candidate",
        document=doc.model_dump(mode="json"),
        geometry_hash=geometry_hash(doc),
        problems=[],
        confirmation_id=confirmation_id,
        context_fingerprint="f" * 64,
    )
    db_session.add(candidate)
    await db_session.flush()
    original_document = candidate.document
    with patch(
        "modules.world.map_structure_service.prepare_confirmed_ai_action",
        autospec=True,
        return_value=SimpleNamespace(
            confirmation=SimpleNamespace(context_fingerprint="f" * 64)
        ),
    ):
        first = await service.review(
            db_session,
            test_project_id,
            node["id"],
            str(candidate.id),
            MapRevisionReview(
                base_revision_id=saved.id, action="adopt", change_keys=["feature:a"]
            ),
        )
        assert first.applied_change_keys == ["feature:a"]
        assert first.remaining_candidate_id
        assert candidate.status == "rejected" and candidate.document == original_document
        remaining = await db_session.get(
            MapAtlasRevision, uuid.UUID(first.remaining_candidate_id)
        )
        assert remaining.task_id is None and remaining.confirmation_id == confirmation_id
        with pytest.raises(ConflictError):
            await service.review(
                db_session,
                test_project_id,
                node["id"],
                str(candidate.id),
                MapRevisionReview(base_revision_id=first.id, action="restore"),
            )
        second = await service.review(
            db_session,
            test_project_id,
            node["id"],
            str(remaining.id),
            MapRevisionReview(
                base_revision_id=first.id, action="adopt", change_keys=["feature:b"]
            ),
        )
        assert second.remaining_candidate_id
        with pytest.raises(ConflictError, match="已更新"):
            await service.review(
                db_session,
                test_project_id,
                node["id"],
                second.remaining_candidate_id,
                MapRevisionReview(base_revision_id=first.id, action="adopt"),
            )
    with patch(
        "modules.world.map_structure_service.prepare_confirmed_ai_action",
        autospec=True,
        return_value=SimpleNamespace(
            confirmation=SimpleNamespace(context_fingerprint="stale")
        ),
    ):
        with pytest.raises(ConflictError, match="来源已变化"):
            await service.review(
                db_session,
                test_project_id,
                node["id"],
                second.remaining_candidate_id,
                MapRevisionReview(base_revision_id=second.id, action="adopt"),
            )
    with patch(
        "modules.world.map_structure_service.prepare_confirmed_ai_action",
        autospec=True,
        return_value=SimpleNamespace(
            confirmation=SimpleNamespace(context_fingerprint="f" * 64)
        ),
    ):
        final = await service.review(
            db_session,
            test_project_id,
            node["id"],
            second.remaining_candidate_id,
            MapRevisionReview(base_revision_id=second.id, action="adopt"),
        )
    assert final.remaining_candidate_id is None
    assert [feature.note for feature in final.document.features] == ["a", "b", "c"]


def test_structure_manifest_matches_identity_and_preserves_geometry_hash():
    document = points()
    manifest = structure_reference_manifest(document)
    assert [item["name"] for item in manifest] == ["甲城", "乙城", "丙城"]
    assert len({item["reference"] for item in manifest}) == 3
    assert all(
        0 <= point[axis] <= 1
        for item in manifest
        for point in item["points"]
        for axis in ["x", "y"]
    )
    document.features.reverse()
    assert structure_reference_manifest(document) == manifest
    document.constraints = [
        SpatialConstraint(id="c", subject="a", target="b", relation="north")
    ]
    before = geometry_hash(document)
    document.constraints[0].generated_by_task_id = uuid.uuid4()
    assert geometry_hash(document) == before


async def test_historical_preview_uses_requested_version_without_saving(
    db_session, test_project_id, project_factory
):
    from core.errors import NotFoundError
    from modules.world.map_atlas_models import MapAtlasNode

    service, node, first = await saved_map(db_session, test_project_id)
    new_doc = first.document.model_copy(deep=True)
    new_doc.features[0].points[0].x += 500
    second = await service.save(
        db_session,
        test_project_id,
        node["id"],
        MapSaveRequest(base_revision_id=first.id, document=new_doc),
    )
    count = await db_session.scalar(select(func.count(MapAtlasRevision.id)))
    preview = await service.preview_revision(
        db_session, test_project_id, node["id"], first.id
    )
    assert preview.document.features[0].points[0].x == 10
    assert preview.geometry_hash == first.geometry_hash
    assert await db_session.scalar(select(func.count(MapAtlasRevision.id))) == count
    current = await db_session.get(MapAtlasNode, uuid.UUID(node["id"]))
    assert str(current.current_revision_id) == second.id
    foreign = str(await project_factory.create_project())
    with pytest.raises(NotFoundError):
        await service.preview_revision(db_session, foreign, node["id"], first.id)


async def test_manual_workflow_keeps_source_range_and_original_geometry(
    db_session, test_project_id
):
    from unittest.mock import AsyncMock

    from infrastructure.tasks.models import AsyncTask
    from modules.world.map_atlas_models import MapAtlasNode
    from modules.world.map_structure_schemas import MapRelationBatch
    from modules.world.map_structure_service import MAP_TASK
    from modules.world.map_structure_workflow import run_structure

    ref = source_range()
    document = points()
    for feature in document.features[:2]:
        feature.sources = [ref]
    with patch.object(
        MapStructureService, "source", autospec=True, return_value="甲城在乙城以北"
    ):
        _, node, saved = await saved_map(db_session, test_project_id, document)
        task = AsyncTask(
            novel_id=uuid.UUID(test_project_id),
            task_type=MAP_TASK,
            status="running",
            attempt=1,
            lease_id=str(uuid.uuid4()),
            recovery_policy="manual_resume",
            meta={
                "node_id": node["id"],
                "base_revision_id": saved.id,
                "feature_ids": ["a", "b"],
                "location_ids": [],
                "context_confirmation_id": str(uuid.uuid4()),
                "llm_execution_snapshot": {},
            },
        )
        db_session.add(task)
        await db_session.flush()
        model = await db_session.get(MapAtlasNode, uuid.UUID(node["id"]))
        model.structure_task_id = task.id
        await db_session.flush()
        db_session.task_checkpoint_enabled = True
        client = SimpleNamespace(
            generate_structured=AsyncMock(
                return_value=MapRelationBatch(
                    relations=[
                        dict(
                            subject="a",
                            target="b",
                            relation="north",
                            source_keys=[f"range:{ref.id}:0:8"],
                            quote="甲城在乙城以北",
                        )
                    ]
                )
            ),
            close=AsyncMock(),
        )
        with (
            patch(
                "modules.world.map_structure_workflow.prepare_confirmed_ai_action",
                autospec=True,
                return_value=prepared_source(ref),
            ),
            patch(
                "modules.world.map_structure_workflow.require_fresh_confirmation",
                autospec=True,
            ),
            patch(
                "modules.world.map_structure_workflow.restore_project_llm_execution_settings",
                autospec=True,
                return_value={"llm": {"model": "test"}},
            ),
            patch(
                "modules.world.map_structure_workflow.create_project_snapshot_llm_client",
                autospec=True,
                return_value=client,
            ),
        ):
            result = await run_structure(db_session, task)
        candidate = await db_session.get(
            MapAtlasRevision, uuid.UUID(result["revision_id"])
        )
        assert str(model.current_revision_id) == saved.id
        assert candidate.document["constraints"][0]["generated_by_task_id"] == str(
            task.id
        )
        assert (
            candidate.document["constraints"][0]["sources"][0]["kind"] == "source_range"
        )
        assert (
            candidate.document["features"] == document.model_dump(mode="json")["features"]
        )
        request = client.generate_structured.call_args.args[0]
        assert "甲城在乙城以北" in request.messages[0].content
        assert await db_session.scalar(select(func.count(CoreEntity.id))) == 0
        client.close.assert_awaited_once()


def test_local_layout_does_not_place_unselected_or_failed_features():
    from modules.world.map_structure_workflow import layout_selected

    document = points()
    document.features[0].locked = False
    document.features[0].points = []
    document.features[2].locked = False
    document.features[2].points = []
    document.constraints = [
        SpatialConstraint(
            id="untouched-route", subject="b", target="c", relation="connects"
        )
    ]
    generated = layout_selected(document, {"a", "b"}).document
    assert generated.features[0].points
    assert generated.features[2] == document.features[2]
    assert len(generated.features) == 3
    assert generated.constraints == document.constraints


async def test_relation_refresh_is_idempotent_and_preserves_failed_scope():
    from modules.world.map_structure_workflow import update_extracted_relations

    document = points()
    old = SpatialConstraint(
        id="stable",
        subject="a",
        target="b",
        relation="north",
        generated_by_task_id=uuid.uuid4(),
    )
    document.constraints = [old]
    new = old.model_copy(update={"generated_by_task_id": uuid.uuid4()})
    await update_extracted_relations(None, "", "", document, [new], {"a", "b"})
    assert document.constraints == [old]
    await update_extracted_relations(
        None, "", "", document, [new.model_copy(update={"relation": "south"})], {"a"}
    )
    assert document.constraints == [old]


async def test_selected_change_cannot_import_stale_source(db_session, test_project_id):
    service, node, saved = await saved_map(db_session, test_project_id)
    candidate_doc = saved.document.model_copy(deep=True)
    candidate_doc.features[1].sources = [source_range()]
    candidate_doc.features[1].note = "另一区域的修改"
    candidate = MapAtlasRevision(
        novel_id=uuid.UUID(test_project_id),
        node_id=uuid.UUID(node["id"]),
        base_revision_id=uuid.UUID(saved.id),
        status="candidate",
        document=candidate_doc.model_dump(mode="json"),
        geometry_hash=geometry_hash(candidate_doc),
        problems=[],
        confirmation_id=uuid.uuid4(),
        context_fingerprint="f" * 64,
    )
    db_session.add(candidate)
    await db_session.flush()
    with (
        patch(
            "modules.world.map_structure_service.prepare_confirmed_ai_action",
            autospec=True,
            return_value=SimpleNamespace(
                confirmation=SimpleNamespace(context_fingerprint="f" * 64)
            ),
        ),
        patch.object(
            MapStructureService,
            "source",
            autospec=True,
            side_effect=ConflictError("来源已经变化"),
        ),
    ):
        with pytest.raises(ConflictError, match="来源已经变化"):
            await service.review(
                db_session,
                test_project_id,
                node["id"],
                str(candidate.id),
                MapRevisionReview(
                    base_revision_id=saved.id, action="adopt", change_keys=["feature:b"]
                ),
            )
    assert candidate.status == "candidate"


async def test_source_truncation_and_unread_old_evidence_do_not_authorize_removal(
    db_session, test_project_id
):
    from modules.world.map_structure_workflow import confirmed_spatial_sources

    ref = source_range()
    prepared = prepared_source(ref)
    prepared.compiled.sections[0].items[0].content = (
        "甲城" + "文" * 8000 + "乙城在甲城以北"
    )
    sources = await confirmed_spatial_sources(db_session, test_project_id, prepared)
    assert sources[f"range:{ref.id}:0:8"]["truncated"]
    assert len(sources[f"range:{ref.id}:0:8"]["text"]) == 8000
    document = points()
    relation = SpatialConstraint(
        id="old",
        subject="a",
        target="b",
        relation="north",
        sources=[ref],
        generated_by_task_id=uuid.uuid4(),
    )
    document.constraints = [relation]
    await update_extracted_relations(
        None, "", "", document, [], {"a", "b"}, {"entity:unrelated"}
    )
    assert document.constraints == [relation]


async def test_equivalent_manual_relation_is_not_duplicated():
    document = points()
    manual = SpatialConstraint(
        id="author-relation", subject="a", target="b", relation="north"
    )
    document.constraints = [manual]
    automatic = manual.model_copy(
        update={
            "id": relation_key(manual.model_dump()),
            "generated_by_task_id": uuid.uuid4(),
        }
    )
    await update_extracted_relations(None, "", "", document, [automatic], {"a", "b"})
    assert document.constraints == [manual]


async def test_partial_update_preserves_unrelated_stale_baseline_with_warning(
    db_session, test_project_id
):
    stale, fresh = source_range(), source_range()
    baseline = points()
    baseline.features[0].sources = [stale]
    with patch.object(MapStructureService, "source", autospec=True, return_value="原文"):
        service, node, saved = await saved_map(db_session, test_project_id, baseline)
    candidate_doc = saved.document.model_copy(deep=True)
    candidate_doc.features[0].note = "此项仍需重新核对"
    candidate_doc.features[1].sources = [fresh]
    candidate_doc.features[1].note = "新资料"
    candidate = MapAtlasRevision(
        novel_id=uuid.UUID(test_project_id),
        node_id=uuid.UUID(node["id"]),
        base_revision_id=uuid.UUID(saved.id),
        status="candidate",
        document=candidate_doc.model_dump(mode="json"),
        geometry_hash=geometry_hash(candidate_doc),
        problems=[],
        confirmation_id=uuid.uuid4(),
        context_fingerprint="f" * 64,
    )
    db_session.add(candidate)
    await db_session.flush()

    async def source(_service, _db, _novel, ref):
        if ref.id == stale.id:
            raise ConflictError("A区来源已变化")
        return "新原文"

    with (
        patch(
            "modules.world.map_structure_service.prepare_confirmed_ai_action",
            autospec=True,
            return_value=SimpleNamespace(
                confirmation=SimpleNamespace(context_fingerprint="f" * 64)
            ),
        ),
        patch.object(MapStructureService, "source", autospec=True, side_effect=source),
    ):
        adopted = await service.review(
            db_session,
            test_project_id,
            node["id"],
            str(candidate.id),
            MapRevisionReview(
                base_revision_id=saved.id, action="adopt", change_keys=["feature:b"]
            ),
        )
        assert adopted.document.features[0] == baseline.features[0]
        assert adopted.document.features[1].note == "新资料"
        assert any(
            problem.code == "source_stale" and problem.feature_ids == ["a"]
            for problem in adopted.problems
        )
        assert adopted.remaining_candidate_id
        with pytest.raises(ConflictError, match="A区来源"):
            await service.review(
                db_session,
                test_project_id,
                node["id"],
                adopted.remaining_candidate_id,
                MapRevisionReview(
                    base_revision_id=adopted.id, action="adopt", change_keys=["feature:a"]
                ),
            )


async def test_derived_image_new_revision_rebuilds_guide_and_drops_old_prompt(
    db_session, test_project_id
):
    from modules.world.map_atlas_models import MapAtlasPage, MapAtlasRun
    from modules.world.map_atlas_schemas import MapAtlasDerivedRequest
    from modules.world.map_atlas_service import MapAtlasService
    from modules.world.map_atlas_storage import page_object_key

    service, node, old = await saved_map(db_session, test_project_id)
    document = old.document.model_copy(deep=True)
    document.features[0].label = "新的码头"
    new = await service.save(
        db_session,
        test_project_id,
        node["id"],
        MapSaveRequest(base_revision_id=old.id, document=document),
    )
    original_run = MapAtlasRun(
        novel_id=uuid.UUID(test_project_id),
        run_kind="initial",
        status="completed",
        context_snapshot={"context_confirmation_id": str(uuid.uuid4())},
    )
    db_session.add(original_run)
    await db_session.flush()
    page_id = uuid.uuid4()
    page = MapAtlasPage(
        id=page_id,
        novel_id=uuid.UUID(test_project_id),
        node_id=uuid.UUID(node["id"]),
        run_id=original_run.id,
        title="城市",
        visual_brief="旧版地形说明",
        prompt="不应再引用的旧资料",
        evidence={"supported": ["旧秘密"]},
        source_manifest=[{"summary": "旧秘密"}],
        generation_status="review_ready",
        review_status="adopted",
        object_key=page_object_key(test_project_id, str(page_id)),
        source_map_revision_id=uuid.UUID(old.id),
        source_geometry_hash=old.geometry_hash,
        width=1024,
        height=1024,
    )
    db_session.add(page)
    await db_session.flush()
    with (
        patch(
            "modules.world.map_atlas_service.build_project_image_execution_snapshot",
            autospec=True,
            return_value={"image": "test"},
        ),
        patch(
            "modules.world.map_structure_images.prepare_confirmed_ai_action",
            autospec=True,
            return_value=SimpleNamespace(
                confirmation=SimpleNamespace(context_fingerprint="f" * 64),
                compiled=CompiledContext(sections=[]),
            ),
        ),
    ):
        result = await MapAtlasService(storage=SimpleNamespace()).create_derived_page(
            db_session,
            test_project_id,
            str(page.id),
            MapAtlasDerivedRequest(
                source_map_revision_id=new.id, context_confirmation_id=uuid.uuid4()
            ),
            mode="regenerate",
        )
    derived = await db_session.get(MapAtlasPage, uuid.UUID(result["id"]))
    assert "新的码头" in derived.prompt and "S001" in derived.prompt
    assert "不应再引用" not in derived.prompt and "旧秘密" not in derived.prompt
    assert derived.source_manifest == []
    assert derived.source_map_revision_id == uuid.UUID(new.id)
    assert page.prompt == "不应再引用的旧资料"
