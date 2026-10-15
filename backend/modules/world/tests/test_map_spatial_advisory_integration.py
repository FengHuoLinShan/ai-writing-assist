"""Exercise the registered reader against isolated SQLite domain records."""

import uuid
from dataclasses import replace

import pytest

from core.container import get
from core.service_keys import WORLD_READ_MAP_SPATIAL_ADVISORIES
from modules.story.outline_state.models import Scene
from modules.world.map_atlas_models import MapAtlasNode, MapAtlasRevision
from modules.world.map_structure_schemas import MapDocument
from modules.world.map_structure_service import source_digest, source_payload
from modules.world.models import CoreEntity
from modules.writing.schemas import WritingConflictCheckCreate
from modules.writing.services import WritingConflictCheckService
from modules.writing.source_hashing import hash_text


async def seed(db, novel_id):
    nid = uuid.UUID(novel_id)
    places = [
        CoreEntity(
            novel_id=nid,
            entity_type="location",
            name=name,
            summary=name,
            public_info=name,
            reveal_level="revealed",
            status="canonical",
        )
        for name in ("东城", "西城")
    ]
    db.add_all(places)
    await db.flush()
    content = "东城与西城遥遥相对。"
    scene = Scene(
        novel_id=nid,
        scene_index=1,
        title="两城",
        status="canonical",
        chapter_ids=["1"],
        structure_meta={"location_entity_id": str(places[0].id)},
        scene_chunks=[
            {
                "chapter_index": 1,
                "start_pos": 0,
                "end_pos": len(content),
                "source_content_hash": hash_text(content),
            }
        ],
    )
    node = MapAtlasNode(
        novel_id=nid,
        semantic_key="region/test",
        title="两城地图",
        level="region",
        status="adopted",
    )
    db.add_all([scene, node])
    await db.flush()
    sources = [
        {
            "kind": "entity",
            "id": str(place.id),
            "quote": place.name,
            "source_hash": source_digest(source_payload(place)),
        }
        for place in places
    ]
    document = MapDocument.model_validate(
        {
            "schema_version": 2,
            "features": [
                {
                    "id": key,
                    "kind": "location",
                    "label": place.name,
                    "entity_id": str(place.id),
                    "sources": [sources[index]],
                }
                for index, (key, place) in enumerate(
                    zip(("east", "west"), places, strict=True)
                )
            ],
            "constraints": [
                {
                    "id": key,
                    "subject": "east",
                    "target": "west",
                    "relation": direction,
                    "sources": sources,
                }
                for key, direction in (("north", "north"), ("south", "south"))
            ],
        }
    )
    revision = MapAtlasRevision(
        novel_id=nid,
        node_id=node.id,
        status="saved",
        document=document.model_dump(mode="json"),
        geometry_hash="a" * 64,
    )
    db.add(revision)
    await db.flush()
    node.current_revision_id = revision.id
    await db.flush()
    return scene, node, revision, places, content


@pytest.mark.asyncio
async def test_registered_reader_uses_real_scene_contract_and_records_checked_maps(
    db_session, test_project_id
):
    scene, node, revision, places, _ = await seed(db_session, test_project_id)
    read = get(WORLD_READ_MAP_SPATIAL_ADVISORIES)
    request = {"novel_id": test_project_id, "scene_id": str(scene.id)}
    result = await read(db_session, request)
    assert [item.rule_code for item in result.items] == ["direction_conflict"]
    assert result.scene_index == 1
    assert result.map_revisions[0].revision_id == str(revision.id)

    # Current canonical data, exclusions and explicit Scene identity are hard boundaries.
    excluded = await read(
        db_session, {**request, "excluded_ids": [f"world_entity:{places[1].id}"]}
    )
    assert excluded.items == []
    excluded_node = await read(
        db_session, {**request, "excluded_ids": [f"map_spatial:{node.id}:{revision.id}"]}
    )
    assert excluded_node.items == [] and excluded_node.map_revisions == []
    places[1].status = "candidate"
    await db_session.flush()
    assert (await read(db_session, request)).items == []
    places[1].status = "canonical"
    places[1].name = "重命名后的西城"
    await db_session.flush()
    assert (await read(db_session, request)).items == []
    scene.structure_meta = {}
    await db_session.flush()
    unknown = await read(db_session, request)
    assert unknown.items == [] and unknown.map_revisions == [] and unknown.unknowns


@pytest.mark.asyncio
async def test_writing_default_loader_reaches_registered_world_reader_and_g8b(
    db_session, test_project_id, monkeypatch
):
    from core.config import get_settings

    scene, node, revision, _, content = await seed(db_session, test_project_id)
    settings = replace(
        get_settings(),
        map_spatial_enabled_capabilities=("writing.conflict_check.spatial_advisory",),
    )
    monkeypatch.setattr("core.config.get_settings", lambda: settings)
    service = WritingConflictCheckService()
    check = await service.create_check(
        db_session,
        WritingConflictCheckCreate(
            novel_id=test_project_id,
            scene_id=str(scene.id),
            chapter_index=1,
            content=content,
        ),
    )
    assert check.summary_json["map_spatial_advisory"]["status"] == "checked"
    item = next(
        item
        for item in check.items
        if item.source_type == "map_spatial_advisory.direction_conflict"
    )
    assert item.severity == "low" and item.needs_review
    assert item.location_json["fix_paths"] == ["writing", "map"]
    assert check.summary_json["map_baseline"]["nodes"][str(node.id)][
        "revision_id"
    ] == str(revision.id)
    node.status = "provisional"
    await db_session.flush()
    fetched = await service.get_check(
        db_session, novel_id=test_project_id, check_id=str(check.id)
    )
    assert fetched.map_staleness["changed"] is True
    from modules.writing.schemas import WritingConflictItemUpdate

    ignored = await service.update_item(
        db_session,
        novel_id=test_project_id,
        item_id=str(item.id),
        data=WritingConflictItemUpdate(status="ignored"),
    )
    assert ignored.status == "ignored"


@pytest.mark.asyncio
async def test_checked_map_without_warning_still_has_version_baseline(
    db_session, test_project_id
):
    scene, _, revision, _, _ = await seed(db_session, test_project_id)
    # Create a consistent head rather than mutating an immutable revision.
    document = dict(revision.document)
    document["constraints"] = document["constraints"][:1]
    new_revision = MapAtlasRevision(
        novel_id=revision.novel_id,
        node_id=revision.node_id,
        status="saved",
        document=document,
        geometry_hash="a" * 64,
    )
    db_session.add(new_revision)
    await db_session.flush()
    node = await db_session.get(MapAtlasNode, revision.node_id)
    node.current_revision_id = new_revision.id
    await db_session.flush()
    result = await get(WORLD_READ_MAP_SPATIAL_ADVISORIES)(
        db_session, {"novel_id": test_project_id, "scene_id": str(scene.id)}
    )
    assert result.items == []
    assert result.map_revisions[0].revision_id == str(new_revision.id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        "planned",
        "stale",
        "hidden",
        "source_hidden",
        "source_working",
        "invalid_anchor",
        "custom_without_traits",
    ],
)
async def test_uncertain_or_unavailable_claims_do_not_become_conflicts(
    db_session, test_project_id, change
):
    from copy import deepcopy

    from modules.world.project_vocabulary_schemas import VocabularyTermCreate
    from modules.world.project_vocabulary_service import create_project_vocabulary_term

    scene, node, revision, places, _ = await seed(db_session, test_project_id)
    document = deepcopy(revision.document)
    if change == "planned":
        document["constraints"][1]["modality"] = "author_plan"
    elif change == "stale":
        document["constraints"][1]["sources"][0]["source_hash"] = "f" * 64
    elif change == "hidden":
        places[1].reveal_level = "hidden"
    elif change == "source_hidden":
        secret_source = CoreEntity(
            novel_id=uuid.UUID(test_project_id),
            entity_type="item",
            name="公开城志",
            public_info="公开城志",
            hidden_truth="隐藏的城门暗道",
            status="canonical",
            reveal_level="revealed",
        )
        db_session.add(secret_source)
        await db_session.flush()
        src = {
            "kind": "entity",
            "id": str(secret_source.id),
            "quote": secret_source.hidden_truth,
            "source_hash": source_digest(source_payload(secret_source)),
        }
        document["constraints"][1]["sources"] = [src]
    elif change == "source_working":
        document["constraints"][1]["sources"] = [
            {
                "kind": "source_range",
                "id": str(uuid.uuid4()),
                "source_hash": "b" * 64,
                "quote": "候选正文",
                "source_ref": {"content_mode": "working"},
            }
        ]
    elif change == "invalid_anchor":
        document["constraints"][1]["effective"] = {
            "start": {"kind": "scene", "id": str(uuid.uuid4())}
        }
    else:
        term = await create_project_vocabulary_term(
            db_session,
            test_project_id,
            VocabularyTermCreate(kind="relation", name="只作文字的方位"),
        )
        for edge in document["constraints"]:
            edge.update(type_ref=str(term.id), type_revision_id=str(term.revision_id))
    new_revision = MapAtlasRevision(
        novel_id=revision.novel_id,
        node_id=node.id,
        status="saved",
        document=document,
        geometry_hash="a" * 64,
    )
    db_session.add(new_revision)
    await db_session.flush()
    node.current_revision_id = new_revision.id
    await db_session.flush()
    result = await get(WORLD_READ_MAP_SPATIAL_ADVISORIES)(
        db_session, {"novel_id": test_project_id, "scene_id": str(scene.id)}
    )
    assert result.items == []


@pytest.mark.asyncio
async def test_forecast_uses_real_brief_only_when_enabled_and_scene_has_location(
    db_session, test_project_id, monkeypatch
):
    from types import SimpleNamespace

    from core.config import get_settings
    from modules.assistant.forecast.registry import rollout_available
    from modules.story.forecast import inspect

    scene, _, revision, _, _ = await seed(db_session, test_project_id)
    focus = SimpleNamespace(scene_id=scene.id, page="outline")
    assert not rollout_available(test_project_id, "story.spatial_planning.v1")
    assert not any(
        item["capability_id"] == "story.spatial_planning.v1"
        for item in await inspect(db_session, test_project_id, focus, set())
    )

    settings = replace(
        get_settings(), map_spatial_enabled_capabilities=("story.spatial_planning",)
    )
    monkeypatch.setattr("core.config.get_settings", lambda: settings)
    assert rollout_available(test_project_id, "story.spatial_planning.v1")
    facts = await inspect(db_session, test_project_id, focus, set())
    spatial = next(
        item for item in facts if item["capability_id"] == "story.spatial_planning.v1"
    )
    assert spatial["source"]["map_revisions"][0]["revision_id"] == str(revision.id)
    assert await inspect(db_session, test_project_id, focus, {str(scene.id)}) == []
    scene.structure_meta = {}
    await db_session.flush()
    assert not any(
        item["capability_id"] == "story.spatial_planning.v1"
        for item in await inspect(db_session, test_project_id, focus, set())
    )


@pytest.mark.asyncio
async def test_reader_preserves_character_boundary_and_project_isolation(
    db_session, test_project_id, project_factory
):
    from core.errors import ValidationError
    from modules.world.models.character import Character, CharacterKnowledge

    scene, _, _, places, _ = await seed(db_session, test_project_id)
    actor = CoreEntity(
        novel_id=uuid.UUID(test_project_id),
        entity_type="character",
        name="未知地理的旅人",
        status="canonical",
        reveal_level="revealed",
    )
    db_session.add(actor)
    await db_session.flush()
    db_session.add(
        Character(entity_id=actor.id, novel_id=actor.novel_id, name=actor.name)
    )
    await db_session.flush()
    db_session.add(
        CharacterKnowledge(
            novel_id=actor.novel_id,
            character_id=actor.id,
            target_type="entity",
            target_id=places[1].id,
            knowledge_level="unknown",
            is_public_baseline=True,
            status="canonical",
        )
    )
    await db_session.flush()
    read = get(WORLD_READ_MAP_SPATIAL_ADVISORIES)
    request = {
        "novel_id": test_project_id,
        "scene_id": str(scene.id),
        "reveal_mode": "character",
    }
    with pytest.raises(ValidationError):
        await read(db_session, request)
    assert (
        await read(db_session, {**request, "viewpoint_character_id": str(actor.id)})
    ).items == []
    other = await project_factory.create_project()
    result = await read(db_session, {"novel_id": str(other), "scene_id": str(scene.id)})
    assert result.items == [] and result.map_revisions == []


@pytest.mark.asyncio
async def test_only_active_pinned_calculation_traits_enable_custom_direction(
    db_session, test_project_id
):
    from copy import deepcopy

    from modules.world.project_vocabulary_schemas import (
        VocabularyTermCreate,
        VocabularyTraits,
    )
    from modules.world.project_vocabulary_service import (
        archive_project_vocabulary_term,
        create_project_vocabulary_term,
    )

    scene, node, revision, _, _ = await seed(db_session, test_project_id)
    term = await create_project_vocabulary_term(
        db_session,
        test_project_id,
        VocabularyTermCreate(
            kind="relation",
            name="罗盘方向",
            traits=VocabularyTraits(orientation=["compass"]),
        ),
    )
    document = deepcopy(revision.document)
    for edge in document["constraints"]:
        edge.update(type_ref=str(term.id), type_revision_id=str(term.revision_id))
    new_revision = MapAtlasRevision(
        novel_id=revision.novel_id,
        node_id=node.id,
        status="saved",
        document=document,
        geometry_hash="a" * 64,
    )
    db_session.add(new_revision)
    await db_session.flush()
    node.current_revision_id = new_revision.id
    await db_session.flush()
    read = get(WORLD_READ_MAP_SPATIAL_ADVISORIES)
    request = {"novel_id": test_project_id, "scene_id": str(scene.id)}
    assert len((await read(db_session, request)).items) == 1
    await archive_project_vocabulary_term(
        db_session, test_project_id, str(term.id), expected_revision_id=term.revision_id
    )
    assert (await read(db_session, request)).items == []


@pytest.mark.asyncio
async def test_optional_advisory_database_error_does_not_prevent_saving_check(
    db_session, test_project_id, monkeypatch
):
    from sqlalchemy import text

    from core.config import get_settings

    scene, _, _, _, content = await seed(db_session, test_project_id)
    settings = replace(
        get_settings(),
        map_spatial_enabled_capabilities=("writing.conflict_check.spatial_advisory",),
    )
    monkeypatch.setattr("core.config.get_settings", lambda: settings)

    async def database_failure(db, *_args):
        await db.execute(text("SELECT * FROM nonexistent_spatial_advisory_test_table"))

    check = await WritingConflictCheckService(
        map_spatial_advisory_loader=database_failure
    ).create_check(
        db_session,
        WritingConflictCheckCreate(
            novel_id=test_project_id,
            scene_id=str(scene.id),
            chapter_index=1,
            content=content,
        ),
    )
    assert check.summary_json["map_spatial_advisory"] == {"status": "not_checked"}
    assert (await db_session.execute(text("SELECT 1"))).scalar_one() == 1
    assert check.id


@pytest.mark.asyncio
async def test_compiler_and_ask_reach_real_registered_scene_map_reader(
    db_session, test_project_id, monkeypatch
):
    from core.config import get_settings
    from modules.evidence.compilation.contracts import CompileOptions
    from modules.evidence.compilation.services.context_compiler import ContextCompiler
    from modules.evidence.compilation.services.loaders import map_spatial_loader
    from modules.evidence.compilation.services.loaders.map_spatial_loader import (
        MapSpatialLoader,
    )
    from modules.evidence.compilation.services.loaders.rag_chunks_loader import (
        RagChunksLoader,
    )
    from modules.world.schemas import AskWorldQuestionRequest
    from modules.world.services.worldbuilding.ask_world_service import AskWorldService

    scene, _, revision, _, _ = await seed(db_session, test_project_id)
    settings = replace(
        get_settings(), map_spatial_enabled_capabilities=("writing.generate", "world.ask")
    )
    monkeypatch.setattr(map_spatial_loader, "get_settings", lambda: settings)
    monkeypatch.setattr(
        "modules.evidence.compilation.services.context_compiler.get_settings",
        lambda: settings,
    )
    options = CompileOptions(
        novel_id=test_project_id,
        task="两城转场",
        scope="scene",
        scene_id=str(scene.id),
        chapter_index=1,
        consumer_action="writing.generate",
    )
    compiled = await ContextCompiler([MapSpatialLoader()]).compile(db_session, options)
    assert compiled.map_spatial_brief["items"][0]["revision_id"] == str(revision.id)

    # World port, sources and SQL remain real; only unrelated RAG is isolated.
    async def empty_rag(self, _db, _options, _bundle):
        return None

    monkeypatch.setattr(RagChunksLoader, "load", empty_rag)
    question = AskWorldQuestionRequest(novel_id=test_project_id, question="东城在哪里")
    service = AskWorldService()
    candidates, trace = await service._retrieve_candidates(
        db_session,
        question,
    )
    maps = [item for item in candidates if item["kind"] == "map_spatial"]
    assert maps == [] and any("截止章节" in warning for warning in trace["warnings"])

    # A real Scene-bound compiled reference enters Ask only in the confirmed selection.
    from modules.evidence.compilation.services.compiled_context import CompiledContext

    sections = ContextCompiler._build_map_spatial_sections(compiled)
    maps = service._map_candidates_from_compiled(
        CompiledContext(sections=sections), question
    )
    assert maps and maps[0]["citation"].map_scene_id == str(scene.id)
    citation = maps[0]["citation"]
    node_id = citation.map_baseline[0]["node_id"]
    assert citation.map_baseline[0]["revision_id"] == str(revision.id)
    assert service._confirmed_candidates(maps, {}) == []
    assert service._confirmed_candidates(maps, {"map_spatial": [node_id]}) == maps
    assert (
        await service.open_citation(db_session, test_project_id, citation)
    ).status == "current"

    # Ask's existing confirmation dialog allows an explicit chapter without a Scene.
    chapter_options = CompileOptions(
        novel_id=test_project_id,
        task=question.question,
        scope="full",
        chapter_index=1,
        consumer_action="world.ask",
    )
    chapter_bundle = await ContextCompiler([MapSpatialLoader()]).compile(
        db_session, chapter_options
    )
    chapter_maps = service._map_candidates_from_compiled(
        CompiledContext(
            sections=ContextCompiler._build_map_spatial_sections(chapter_bundle)
        ),
        question,
    )
    assert chapter_maps and chapter_maps[0]["citation"].map_scene_id is None
    assert chapter_maps[0]["citation"].map_chapter_index == 1
    assert (
        await service.open_citation(
            db_session, test_project_id, chapter_maps[0]["citation"]
        )
    ).status == "current"


@pytest.mark.asyncio
@pytest.mark.parametrize("second_mode, conflict", [("步行", True), ("马车", False)])
async def test_journey_comparison_and_route_evidence_ignore_drawn_connection_gap(
    db_session, test_project_id, second_mode, conflict
):
    from copy import deepcopy

    scene, node, revision, places, _ = await seed(db_session, test_project_id)
    earlier = Scene(
        novel_id=revision.novel_id,
        scene_index=0,
        title="旧路",
        status="canonical",
        chapter_ids=["1"],
    )
    db_session.add(earlier)
    await db_session.flush()
    document = deepcopy(revision.document)
    source = document["features"][0]["sources"]
    document["constraints"] = [
        {
            "id": "closed-road",
            "subject": "east",
            "target": "west",
            "relation": "connects",
            "sources": source,
            "effective": {"end": {"kind": "scene", "id": str(earlier.id)}},
        }
    ]
    document["journeys"] = [
        {
            "id": key,
            "origin": "east",
            "destination": "west",
            "transport_label": mode,
            "sources": source,
            "duration": {"minimum": minimum, "maximum": maximum, "unit": "日"},
        }
        for key, mode, minimum, maximum in (
            ("short", "步行", 2, 3),
            ("long", second_mode, 5, 6),
        )
    ]
    new_revision = MapAtlasRevision(
        novel_id=revision.novel_id,
        node_id=node.id,
        status="saved",
        document=document,
        geometry_hash="a" * 64,
    )
    db_session.add(new_revision)
    await db_session.flush()
    node.current_revision_id = new_revision.id
    await db_session.flush()
    result = await get(WORLD_READ_MAP_SPATIAL_ADVISORIES)(
        db_session,
        {
            "novel_id": test_project_id,
            "scene_id": str(scene.id),
            "transitions": [
                {
                    "from_location_id": str(places[0].id),
                    "to_location_id": str(places[1].id),
                }
            ],
        },
    )
    codes = [item.rule_code for item in result.items]
    assert ("journey_duration_conflict" in codes) is conflict
    assert "route_no_active_connection" not in codes
    assert result.unknowns  # A declared route still cannot prove arrival timing.


@pytest.mark.asyncio
async def test_manual_author_journeys_are_checked_but_plans_are_not(
    db_session, test_project_id
):
    from copy import deepcopy

    scene, node, revision, _places, _ = await seed(db_session, test_project_id)
    document = deepcopy(revision.document)
    document["constraints"] = []
    document["journeys"] = [
        {
            "id": key,
            "origin": "east",
            "destination": "west",
            "transport_label": "步行",
            "duration": {"minimum": low, "maximum": high, "unit": "日"},
            "sources": [],
            "author_decision": {"origin": "manual"},
        }
        for key, low, high in (("short", 2, 3), ("long", 5, 6))
    ]
    revision.document = document
    await db_session.flush()
    reader = get(WORLD_READ_MAP_SPATIAL_ADVISORIES)
    request = {"novel_id": test_project_id, "scene_id": str(scene.id)}
    result = await reader(db_session, request)
    assert "journey_duration_conflict" in {item.rule_code for item in result.items}
    document = deepcopy(document)
    for journey in document["journeys"]:
        journey["modality"] = "author_plan"
    revision.document = document
    await db_session.flush()
    result = await reader(db_session, request)
    assert "journey_duration_conflict" not in {item.rule_code for item in result.items}
