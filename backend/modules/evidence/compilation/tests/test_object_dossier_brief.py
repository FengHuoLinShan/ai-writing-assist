"""Three-layer object briefs preserve cutoff, source and POV boundaries."""

from __future__ import annotations

from copy import deepcopy
from uuid import UUID, uuid4

import pytest

from infrastructure.stable_hash import stable_hash
from modules.evidence.compilation.contracts import CompileOptions
from modules.evidence.compilation.object_dossier_schemas import (
    ObjectDossierBriefRequest,
    ObjectDossierBriefResponse,
)
from modules.evidence.compilation.services.object_dossier_brief import (
    ObjectDossierBriefService,
)

NOVEL_ID = str(uuid4())
SCENE_ID = str(uuid4())
ENTITY_ID = str(uuid4())
POV_ID = str(uuid4())
CHECKPOINT_ID = str(uuid4())


def _story_view(*, character: bool = False, reader: bool = False) -> dict:
    facts = [
        {
            "subject_id": ENTITY_ID,
            "subject_label": "北门",
            "field": "condition",
            "value": "北门关闭",
            "layer": "fact",
            "occurred_at": {"scene_index": 2},
            "source": {
                "checkpoint_id": CHECKPOINT_ID,
                "dimension": "entities",
                "provenance": {
                    "field": "condition",
                    "event_id": str(uuid4()),
                    "status": "exact",
                    "source_refs": [
                        {
                            "draft_id": str(uuid4()),
                            "chapter_index": 1,
                            "version_number": 2,
                            "content_mode": "canonical",
                            "start_offset": 3,
                            "end_offset": 7,
                            "source_hash": "a" * 64,
                            "range_hash": "b" * 64,
                        }
                    ],
                },
            },
            "confidence": "confirmed",
            "possibly_false": False,
        },
        {
            "subject_id": ENTITY_ID,
            "subject_label": "北门守卫",
            "field": "knows:gate",
            "value": "北门关闭",
            "layer": "belief",
            "occurred_at": None,
            "source": {"checkpoint_id": CHECKPOINT_ID},
            "confidence": "confirmed",
            "possibly_false": True,
        },
        {
            "subject_id": ENTITY_ID,
            "subject_label": "未锚定观察",
            "field": "observation",
            "value": {"modality": "character_statement", "text": "北门关闭"},
            "layer": "observation",
            "occurred_at": None,
            "source": {"checkpoint_id": CHECKPOINT_ID},
            "confidence": "derived",
            "possibly_false": False,
        },
    ]
    return {
        "novel_id": NOVEL_ID,
        "scene_id": SCENE_ID,
        "scene_index": 2,
        "viewpoint": (
            {"kind": "character", "target_id": POV_ID}
            if character
            else {"kind": "reader"}
            if reader
            else {"kind": "author"}
        ),
        "state_fingerprint": "story-fingerprint",
        "omissions": [],
        "dimensions": [
            {
                "dimension": "entities",
                "label": "人物与对象",
                "status": "ok",
                "facts": facts,
            },
            {
                "dimension": "relations",
                "label": "关系",
                "status": "missing",
                "gap_reason": "没有时点关系记录",
                "facts": [],
            },
        ],
    }


def _world_dossier() -> dict:
    return {
        "entity_id": ENTITY_ID,
        "entity_type": "location",
        "entity_status": "canonical",
        "as_of_scene_id": SCENE_ID,
        "entries": [
            {
                "id": str(uuid4()),
                "entry_group_id": str(uuid4()),
                "revision_number": 2,
                "facing": {"kind": "core", "key": "history"},
                "facing_label": "长期历史",
                "legacy_field_key": None,
                "content": "北门关闭",
                "tags": ["access"],
                "evidence": [
                    {
                        "scene_id": SCENE_ID,
                        "chapter_id": None,
                        "source_hash": "c" * 64,
                        "start_offset": 3,
                        "end_offset": 7,
                        "quote": "北门关闭",
                    }
                ],
                "legacy_value": None,
                "source_metadata": {},
                "quote_text": "raw quote must not be projected",
                "source": "manual",
                "visibility": "public",
                "status": "active",
                "validity": {"start": None, "end": None},
                "anchor_problem": None,
                "effective_at_cutoff": True,
            },
            {
                "id": str(uuid4()),
                "entry_group_id": str(uuid4()),
                "revision_number": 1,
                "facing": {"kind": "core", "key": "secret"},
                "facing_label": "秘密",
                "content": "北门地下有密道",
                "evidence": [],
                "visibility": "secret",
                "source": "manual",
                "tags": [],
                "effective_at_cutoff": True,
            },
        ],
        "legacy_profile_fields": [
            {
                "profile_id": str(uuid4()),
                "profile_type": "location",
                "profile_status": "canonical",
                "template_id": str(uuid4()),
                "template_version_number": 3,
                "field_key": "condition",
                "label": "所在区域",
                "facing": {"kind": "core", "key": "geography"},
                "value": "北门关闭",
                "mapped": True,
                "source_metadata": {"profile_source": "author"},
            },
            {
                "profile_id": str(uuid4()),
                "profile_type": "location",
                "profile_status": "canonical",
                "template_id": None,
                "template_version_number": None,
                "field_key": "unknown_legacy_key",
                "label": "未知字段",
                "facing": None,
                "value": "must remain unmapped",
                "mapped": False,
                "source_metadata": {},
            },
        ],
        "total_count": 2,
        "omitted_count": 0,
        "dossier_fingerprint": "world-fingerprint",
        "unknown": False,
    }


def _pattern() -> dict:
    return {
        "entry_id": str(uuid4()),
        "revision_id": str(uuid4()),
        "revision": 4,
        "entity_ids": [ENTITY_ID],
        "category": "conditional_behavior",
        "statement": "守卫听见钟声后会检查北门。",
        "conditions": ["听见钟声"],
        "modality": "hypothesis",
        "confidence": 0.8,
        "competing_explanations": ["当日加强巡查"],
        "review_verdict": "supported",
        "author_decision": "keep",
        "evidence_refs": [
            {
                "observation_id": "obs-1",
                "scene_id": SCENE_ID,
                "scene_index": 2,
                "modality": "character_statement",
                "role": "support",
                "source": {
                    "draft_id": "draft-1",
                    "content_hash": "d" * 64,
                    "start_offset": 5,
                    "end_offset": 14,
                    "source_visibility": "canonical",
                },
            }
        ],
        "interpretation_only": True,
    }


def _options(*, reveal_mode: str = "author_safe") -> CompileOptions:
    return CompileOptions(
        novel_id=NOVEL_ID,
        task="object brief test",
        scope="scene",
        scene_id=SCENE_ID,
        reveal_mode=reveal_mode,
        viewpoint_character_id=POV_ID if reveal_mode == "character" else None,
        content_mode="canonical",
    )


@pytest.fixture
def facade_reads(monkeypatch):
    calls = {"checkpoints": 0, "story": _story_view, "dossier": _world_dossier}

    async def active_project(_db, _novel_id, *, allow_demo_readonly):
        assert allow_demo_readonly is False
        return None

    async def scene_state(_db, *, novel_id, scene_id, viewpoint, include_checkpoints):
        assert novel_id == NOVEL_ID
        assert scene_id == SCENE_ID
        return {
            "state": calls["story"](
                character=viewpoint["kind"] == "character",
                reader=viewpoint["kind"] == "reader",
            ),
            "checkpoints": (
                await checkpoints(_db, novel_id, scene_id)
                if include_checkpoints
                else None
            ),
        }

    async def checkpoints(_db, novel_id, scene_id):
        calls["checkpoints"] += 1
        return {
            "novel_id": novel_id,
            "scene_id": scene_id,
            "scene_index": 2,
            "items": [
                {
                    "id": CHECKPOINT_ID,
                    "dimension": "entities",
                    "source_hash": "e" * 64,
                    "status": "ready",
                    "stage_index": 1,
                    "is_current": True,
                }
            ],
        }

    async def dossier(
        _db,
        novel_id,
        entity_id,
        *,
        as_of_scene_id,
        limit,
        offset,
        visibility_filter,
        visible_contents,
    ):
        assert novel_id == NOVEL_ID
        assert entity_id == ENTITY_ID
        assert as_of_scene_id == SCENE_ID
        assert (limit, offset) == (250, 0)
        value = calls["dossier"]()
        value["visibility_filter"] = visibility_filter
        if visibility_filter == "public":
            entries = [
                item
                for item in value["entries"]
                if item.get("visibility") == "public"
                and (visible_contents is None or item.get("content") in visible_contents)
            ]
            value["entries"] = entries[offset : offset + limit]
            value["total_count"] = len(entries)
            value["omitted_count"] = max(0, len(entries) - len(value["entries"]))
            value["legacy_profile_fields"] = []
            value["dossier_fingerprint"] = stable_hash(
                {"entries": value["entries"], "total_count": value["total_count"]}
            )
        return value

    monkeypatch.setattr(
        "modules.evidence.compilation.services.object_dossier_brief.require_active_project",
        active_project,
    )

    def service(key):
        return {
            "evidence.read_story_object_state": scene_state,
            "evidence.read_world_object_dossier": dossier,
        }[key.name]

    monkeypatch.setattr("core.container.get", service)
    return calls


async def test_author_brief_aggregates_three_layers_and_keeps_only_reference_ids(
    facade_reads,
):
    async def read_patterns(_db, **kwargs):
        assert kwargs == {
            "novel_id": NOVEL_ID,
            "scene_id": SCENE_ID,
            "entity_ids": [ENTITY_ID],
            "only_adopted": False,
        }
        return {
            "novel_id": NOVEL_ID,
            "scene_id": SCENE_ID,
            "scene_index": 2,
            "items": [_pattern()],
            "omitted_count": 0,
            "omissions": [],
            "coverage": "complete",
            "ledger_fingerprint": "ledger-fingerprint",
        }

    result = await ObjectDossierBriefService(read_patterns).load(
        None,
        _options(reveal_mode="author_full"),
        entity_ids=[ENTITY_ID],
        include_patterns=True,
    )

    response = ObjectDossierBriefResponse.model_validate(result)
    assert facade_reads["checkpoints"] == 1
    assert response.layers == ["world", "continuity", "evolution"]
    assert response.world_fingerprint
    assert response.continuity_fingerprint
    assert response.pattern_fingerprint == "ledger-fingerprint"
    assert len(response.world_items) == 3
    assert sum(item.kind == "world_dossier" for item in response.world_items) == 2
    assert sum(item.kind == "legacy_profile_field" for item in response.world_items) == 1
    assert response.continuity_items[0].layer == "fact"
    assert response.continuity_items[1].layer == "belief"
    assert response.continuity_items[1].possibly_false is True
    assert response.continuity_items[2].layer == "observation"
    assert response.pattern_items[0].modality == "hypothesis"
    assert response.pattern_items[0].evidence_refs[0]["modality"] == "character_statement"
    dossier_entry = next(
        item
        for item in response.world_items
        if item.kind == "world_dossier" and item.source_refs
    )
    assert "quote" not in dossier_entry.source_refs[0]
    assert "raw quote must not be projected" not in str(response.model_dump())
    assert "unknown_legacy_key" not in str(response.model_dump())
    assert "1 个旧档案字段未绑定模板面向" in " ".join(response.omissions)


async def test_character_brief_fails_closed_on_secret_and_evolution_patterns(
    facade_reads,
):
    async def forbidden_patterns(*_args, **_kwargs):
        raise AssertionError("POV projection must not call Evolution")

    result = await ObjectDossierBriefService(forbidden_patterns).load(
        None,
        _options(reveal_mode="character"),
        entity_ids=[ENTITY_ID],
        include_patterns=True,
    )

    response = ObjectDossierBriefResponse.model_validate(result)
    assert facade_reads["checkpoints"] == 0
    assert [
        item.content for item in response.world_items if item.kind == "world_dossier"
    ] == ["北门关闭"]
    assert all(
        item.visibility == "public"
        for item in response.world_items
        if item.kind == "world_dossier"
    )
    visible_entry = next(
        item for item in response.world_items if item.kind == "world_dossier"
    )
    assert visible_entry.facing is None
    assert visible_entry.facing_label is None
    assert visible_entry.source_refs == []
    assert visible_entry.dossier_fingerprint is None
    assert response.checkpoint_refs == []
    assert response.checkpoint_fingerprint != "story-fingerprint"
    assert all(item.checkpoint_id == "" for item in response.continuity_items)
    assert all(item.source_refs == [] for item in response.continuity_items)
    assert response.world_dossier_fingerprints[0]["fingerprint"] != "world-fingerprint"
    assert response.pattern_items == []
    assert all(item.layer != "observation" for item in response.continuity_items)
    assert "secret" not in str(response.model_dump())
    assert "人物倾向" in " ".join(response.omissions)


async def test_current_legacy_value_cannot_fill_a_past_scene(facade_reads):
    def changed_dossier():
        value = _world_dossier()
        value["legacy_profile_fields"][0]["value"] = "今日才关闭"
        return value

    facade_reads["dossier"] = changed_dossier
    result = await ObjectDossierBriefService().load(
        None,
        _options(reveal_mode="author_full"),
        entity_ids=[ENTITY_ID],
        include_patterns=False,
    )
    response = ObjectDossierBriefResponse.model_validate(result)
    assert all(item.kind != "legacy_profile_field" for item in response.world_items)
    assert any("目标 Scene 的时点事实" in item for item in response.omissions)


async def test_legacy_field_cannot_borrow_another_fields_equal_value(facade_reads):
    def wrong_field():
        value = _world_dossier()
        value["legacy_profile_fields"][0]["field_key"] = "origin_place"
        return value

    facade_reads["dossier"] = wrong_field
    result = await ObjectDossierBriefService().load(
        None,
        _options(reveal_mode="author_full"),
        entity_ids=[ENTITY_ID],
        include_patterns=False,
    )
    assert all(item["kind"] != "legacy_profile_field" for item in result["world_items"])
    assert any("时点事实证明" in item for item in result["omissions"])


async def test_author_safe_secret_changes_do_not_leak_values_or_fingerprints(
    facade_reads,
):
    secret = {"value": "第一版隐藏真相"}
    base_story = _story_view()
    base_dossier = _world_dossier()

    def story(*, character=False, reader=False):
        value = deepcopy(base_story)
        value["viewpoint"] = {"kind": "reader"} if reader else {"kind": "author"}
        if not reader:
            value["state_fingerprint"] = f"author-{secret['value']}"
            value["dimensions"][0]["facts"].append(
                {
                    "subject_id": ENTITY_ID,
                    "subject_label": "北门",
                    "field": "identity_position",
                    "value": secret["value"],
                    "layer": "fact",
                    "source": {"checkpoint_id": CHECKPOINT_ID},
                    "confidence": "confirmed",
                    "possibly_false": False,
                }
            )
        return value

    def dossier():
        value = deepcopy(base_dossier)
        value["entries"][1]["content"] = secret["value"]
        value["dossier_fingerprint"] = f"world-{secret['value']}"
        value["legacy_profile_fields"].append(
            {
                **value["legacy_profile_fields"][0],
                "field_key": "hidden_truth",
                "value": secret["value"],
            }
        )
        return value

    facade_reads["story"] = story
    facade_reads["dossier"] = dossier

    async def brief(mode):
        return ObjectDossierBriefResponse.model_validate(
            await ObjectDossierBriefService().load(
                None,
                _options(reveal_mode=mode),
                entity_ids=[ENTITY_ID],
                include_patterns=False,
            )
        )

    safe_first = await brief("author_safe")
    full = await brief("author_full")
    assert secret["value"] not in str(safe_first.model_dump())
    assert secret["value"] in str(full.model_dump())
    assert all(item.field != "identity_position" for item in safe_first.continuity_items)
    assert any(item.field == "identity_position" for item in full.continuity_items)
    assert all(item.kind != "legacy_profile_field" for item in safe_first.world_items)
    assert all(item.field_key != "hidden_truth" for item in full.world_items)
    assert safe_first.checkpoint_refs == []
    assert safe_first.omitted_count == 0
    secret["value"] = "第二版隐藏真相"
    safe_second = await brief("author_safe")
    assert safe_first.fingerprint == safe_second.fingerprint
    assert safe_first.world_fingerprint == safe_second.world_fingerprint
    assert safe_first.checkpoint_fingerprint == safe_second.checkpoint_fingerprint
    assert safe_first.omitted_count == safe_second.omitted_count


async def test_author_safe_rejects_story_reader_that_returns_author_view(facade_reads):
    facade_reads["story"] = lambda **_kwargs: _story_view()
    result = await ObjectDossierBriefService().load(
        None,
        _options(),
        entity_ids=[ENTITY_ID],
        include_patterns=False,
    )
    assert result["world_items"] == result["continuity_items"] == []
    assert result["unknown_layers"] == ["world", "continuity"]


async def test_missing_story_port_reports_unknown_without_reading_world(
    facade_reads, monkeypatch
):
    def missing(_key):
        raise KeyError("evidence.read_story_object_state")

    monkeypatch.setattr("core.container.get", missing)
    result = await ObjectDossierBriefService().load(
        None, _options(), entity_ids=[ENTITY_ID], include_patterns=True
    )
    assert result["coverage"] == "unknown"
    assert result["unknown_layers"] == ["world", "continuity"]
    assert result["world_items"] == result["continuity_items"] == []


async def test_draft_entity_and_profile_are_excluded(facade_reads):
    def draft_entity():
        value = _world_dossier()
        value["entity_status"] = "draft"
        return value

    facade_reads["dossier"] = draft_entity
    draft = await ObjectDossierBriefService().load(
        None,
        _options(reveal_mode="author_full"),
        entity_ids=[ENTITY_ID],
        include_patterns=False,
    )
    assert draft["world_items"] == []
    assert "world" in draft["unknown_layers"]

    def draft_profile():
        value = _world_dossier()
        value["legacy_profile_fields"][0]["profile_status"] = "draft"
        return value

    facade_reads["dossier"] = draft_profile
    profile = await ObjectDossierBriefService().load(
        None,
        _options(reveal_mode="author_full"),
        entity_ids=[ENTITY_ID],
        include_patterns=False,
    )
    assert all(item["kind"] != "legacy_profile_field" for item in profile["world_items"])
    assert any("尚未采用" in item for item in profile["omissions"])


async def test_bridged_generic_revision_still_requires_story_cutoff_proof(facade_reads):
    generic_entry_id = str(uuid4())

    def generic_revision(value: str) -> dict:
        dossier = _world_dossier()
        dossier["entries"].append(
            {
                "id": generic_entry_id,
                "entry_group_id": str(uuid4()),
                "revision_number": 1,
                "facing": {"kind": "core", "key": "geography"},
                "facing_label": "地理",
                "legacy_field_key": "generic_profile:" + "a" * 64,
                "content": value,
                "legacy_value": value,
                "evidence": [],
                "source_metadata": {
                    "generic_profile_field_key": "condition",
                    "generic_profile_mapped": True,
                    "generic_profile_metadata": {
                        "profile_status": "canonical",
                        "source": "legacy_import",
                    },
                },
                "source": "legacy_import",
                "visibility": "secret",
                "status": "active",
                "effective_at_cutoff": True,
            }
        )
        dossier["total_count"] = len(dossier["entries"])
        return dossier

    facade_reads["dossier"] = lambda: generic_revision("只有旧档案记载的城门习惯")
    unproved = await ObjectDossierBriefService().load(
        None,
        _options(reveal_mode="author_full"),
        entity_ids=[ENTITY_ID],
        include_patterns=False,
    )
    assert all(
        item.get("content") != "只有旧档案记载的城门习惯"
        for item in unproved["world_items"]
    )
    assert any("时点事实证明" in item for item in unproved["omissions"])
    assert any(
        item.get("content") == "北门地下有密道" for item in unproved["world_items"]
    )  # explicit author Dossier entries keep their own current revision semantics

    modern = generic_revision("作者现时明确修订的档案")
    modern["entries"][-1]["source"] = "author"
    facade_reads["dossier"] = lambda: modern
    explicit_author_revision = await ObjectDossierBriefService().load(
        None,
        _options(reveal_mode="author_full"),
        entity_ids=[ENTITY_ID],
        include_patterns=False,
    )
    assert any(
        item.get("entry_id") == generic_entry_id
        and item.get("content") == "作者现时明确修订的档案"
        for item in explicit_author_revision["world_items"]
    )

    withdrawn_author_revision = generic_revision("已撤回采用的当前档案")
    withdrawn_author_revision["entries"][-1]["source"] = "author"
    withdrawn_author_revision["entries"][-1]["source_metadata"][
        "generic_profile_metadata"
    ]["profile_status"] = "draft"
    facade_reads["dossier"] = lambda: withdrawn_author_revision
    withdrawn = await ObjectDossierBriefService().load(
        None,
        _options(reveal_mode="author_full"),
        entity_ids=[ENTITY_ID],
        include_patterns=False,
    )
    assert all(
        item.get("entry_id") != generic_entry_id for item in withdrawn["world_items"]
    )

    for reveal_mode in ("author_safe", "character"):
        facade_reads["dossier"] = lambda: generic_revision("北门关闭")
        safe_result = await ObjectDossierBriefService().load(
            None,
            _options(reveal_mode=reveal_mode),
            entity_ids=[ENTITY_ID],
            include_patterns=False,
        )
        assert all(
            item.get("entry_id") != generic_entry_id
            for item in safe_result["world_items"]
        )

    facade_reads["dossier"] = lambda: generic_revision("北门关闭")
    proved = await ObjectDossierBriefService().load(
        None,
        _options(reveal_mode="author_full"),
        entity_ids=[ENTITY_ID],
        include_patterns=False,
    )
    assert any(
        item.get("content") == "北门关闭"
        and item.get("entry_id") == generic_entry_id
        and item.get("kind") == "world_dossier"
        for item in proved["world_items"]
    )

    def wrong_generic_field():
        value = generic_revision("北门关闭")
        value["entries"][-1]["source_metadata"]["generic_profile_field_key"] = (
            "origin_place"
        )
        return value

    facade_reads["dossier"] = wrong_generic_field
    wrong_key = await ObjectDossierBriefService().load(
        None,
        _options(reveal_mode="author_full"),
        entity_ids=[ENTITY_ID],
        include_patterns=False,
    )
    assert all(item.get("entry_id") != generic_entry_id for item in wrong_key["world_items"])
    facade_reads["dossier"] = lambda: generic_revision("北门关闭")

    def earlier_fact_story(*, character=False, reader=False):
        view = _story_view(character=character, reader=reader)
        view["dimensions"][0]["facts"][0]["occurred_at"] = {"scene_index": 1}
        return view

    facade_reads["story"] = earlier_fact_story
    earlier = await ObjectDossierBriefService().load(
        None,
        _options(reveal_mode="author_full"),
        entity_ids=[ENTITY_ID],
        include_patterns=False,
    )
    assert any(
        item.get("entry_id") == generic_entry_id for item in earlier["world_items"]
    )

    for change in (
        lambda view: view["dimensions"][0]["facts"][0].update(
            occurred_at={"scene_index": 3}
        ),
        lambda view: view["dimensions"][0]["facts"][0].update(confidence="unverified"),
        lambda view: view["dimensions"][0]["facts"][0].update(value="城门已打开"),
        lambda view: view["dimensions"][0]["facts"][0]["source"]["provenance"].update(
            status="unverified", source_refs=[]
        ),
        lambda view: view["dimensions"][0]["facts"][0]["source"].update(
            dimension="locations"
        ),
        lambda view: view["dimensions"][0]["facts"][0]["source"].update(
            checkpoint_id=str(uuid4())
        ),
    ):
        facade_reads["dossier"] = lambda: generic_revision("北门关闭")

        def modified_story(*, character=False, reader=False):
            view = _story_view(character=character, reader=reader)
            change(view)
            return view

        facade_reads["story"] = modified_story
        invalid = await ObjectDossierBriefService().load(
            None,
            _options(reveal_mode="author_full"),
            entity_ids=[ENTITY_ID],
            include_patterns=False,
        )
        assert all(
            item.get("entry_id") != generic_entry_id for item in invalid["world_items"]
        )


async def test_evolution_provider_failure_is_not_hidden_as_missing_di(facade_reads):
    async def broken_provider(*_args, **_kwargs):
        raise RuntimeError("source store unavailable")

    with pytest.raises(RuntimeError, match="source store unavailable"):
        await ObjectDossierBriefService(broken_provider).load(
            None,
            _options(reveal_mode="author_full"),
            entity_ids=[ENTITY_ID],
            include_patterns=True,
        )


def test_brief_request_contract_requires_a_cutoff_and_explicit_pattern_opt_in():
    request = ObjectDossierBriefRequest(
        novel_id=NOVEL_ID,
        scene_id=SCENE_ID,
        entity_ids=[ENTITY_ID],
    )
    assert request.include_patterns is False
    assert request.only_adopted_patterns is False
    with pytest.raises(ValueError, match="viewpoint_character_id"):
        ObjectDossierBriefRequest(
            novel_id=NOVEL_ID,
            scene_id=SCENE_ID,
            entity_ids=[ENTITY_ID],
            reveal_mode="character",
        )
    with pytest.raises(ValueError, match="requires include_patterns"):
        ObjectDossierBriefRequest(
            novel_id=NOVEL_ID,
            scene_id=SCENE_ID,
            entity_ids=[ENTITY_ID],
            only_adopted_patterns=True,
        )


def test_object_brief_api_is_registered_without_importing_evolution_service_key():
    from modules.evidence.compilation.api import router

    route = next(
        item for item in router.routes if item.path.endswith("/object-dossier-brief")
    )
    assert route.methods == {"POST"}
    assert route.response_model is ObjectDossierBriefResponse


async def test_object_brief_http_uses_registered_ports(
    async_client, db_session, test_project_id
):
    from core.container import get
    from core.service_keys import (
        EVIDENCE_READ_EVOLUTION_OBJECT_PATTERNS,
        EVIDENCE_READ_STORY_OBJECT_STATE,
        EVIDENCE_READ_WORLD_OBJECT_DOSSIER,
    )
    from modules.story.outline_state.models import Scene
    from modules.world.models import CoreEntity

    scene_id, entity_id = uuid4(), uuid4()
    db_session.add(Scene(id=scene_id, novel_id=UUID(test_project_id), scene_index=0))
    db_session.add(
        CoreEntity(
            id=entity_id,
            novel_id=UUID(test_project_id),
            entity_type="location",
            name="北门",
            status="canonical",
        )
    )
    await db_session.flush()
    assert callable(get(EVIDENCE_READ_STORY_OBJECT_STATE))
    assert callable(get(EVIDENCE_READ_WORLD_OBJECT_DOSSIER))
    assert callable(get(EVIDENCE_READ_EVOLUTION_OBJECT_PATTERNS))

    response = await async_client.post(
        "/api/evidence/compilation/object-dossier-brief",
        json={
            "novel_id": test_project_id,
            "scene_id": str(scene_id),
            "entity_ids": [str(entity_id)],
        },
    )
    assert response.status_code == 200, response.text
    payload = ObjectDossierBriefResponse.model_validate(response.json())
    assert payload.novel_id == test_project_id
    assert payload.scene_id == str(scene_id)
    assert payload.pattern_items == []
