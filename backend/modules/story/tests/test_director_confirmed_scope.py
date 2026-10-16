"""A confirmation is an upper bound, including excluded and budget-evicted items."""

import json
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest

from modules.evidence.compilation.contracts import StructureContextBundle
from modules.evidence.compilation.services.compiled_context import CompiledContext
from modules.evidence.compilation.services.object_dossier_sections import (
    ObjectDossierSectionBuilder,
)
from modules.evidence.facade import restrict_object_dossier_brief
from modules.story.director_context import (
    director_confirmation_scope,
    director_only_packet,
    require_director_confirmation_scope,
    scope_director_source,
)
from modules.story.director_tasks import _fit_packet


def confirmed_fixture():
    actor, scene = str(uuid4()), str(uuid4())
    brief = {
        "scene_id": scene,
        "world_items": [
            {
                "entity_id": actor,
                "kind": "world_dossier",
                "entry_id": key,
                "revision_id": f"revision-{key}",
                "facing_label": "表达方式",
                "content": value,
                "value": "UNAPPROVED_METADATA",
                "private_note": "UNAPPROVED_METADATA",
            }
            for key, value in (
                ("kept", "说话简短"),
                ("excluded", "EXCLUDED_SECRET"),
                ("evicted", "EVICTED_SECRET"),
                ("truncated", "TRUNCATED_SECRET"),
                ("author", "AUTHOR_ONLY_SECRET"),
            )
        ],
        "continuity_items": [
            {
                "entity_id": actor,
                "dimension": "entities",
                "field": "state",
                "layer": "fact",
                "value": "衣服湿透",
                "checkpoint_id": "checkpoint",
                "provenance": {
                    "status": "exact",
                    "field": "state",
                    "quote": "UNAPPROVED_METADATA",
                },
            }
        ],
        "pattern_items": [
            {"entry_id": "pattern", "revision_id": "v1", "statement": "先观察再行动"}
        ],
        "validity_notices": [{"world_evidence": "EXCLUDED_SECRET"}],
        "omissions": ["UNAPPROVED_METADATA"],
    }
    sections = ObjectDossierSectionBuilder.build(
        StructureContextBundle(
            novel_id="test",
            task="test",
            scope="scene",
            object_dossier_brief=brief,
            object_reference_dimensions=["object_dossier", "character_pattern"],
        ),
        None,
    )
    dossier = sections[0]
    # retrieval_metadata deliberately still contains the excluded/evicted bases.
    dossier.items = [
        item
        for item in dossier.items
        if item.key not in {"world:excluded", "world:evicted"}
    ]
    next(
        item for item in dossier.items if item.key == "world:truncated"
    ).content = "- [表达方式] TRUNCATED…"
    dossier.content = "\n".join(item.content for item in dossier.items)
    confirmed = SimpleNamespace(
        compiled=CompiledContext(sections=sections),
        rendered_markdown="作者已确认的场景资料",
    )
    return actor, scene, brief, confirmed


def test_brief_requires_complete_selected_item_and_current_revision():
    _, _, brief, confirmed = confirmed_fixture()
    scoped = restrict_object_dossier_brief(brief, confirmed.compiled)
    assert [item["entry_id"] for item in scoped["world_items"]] == ["kept", "author"]
    assert scoped["continuity_items"][0]["value"] == "衣服湿透"
    assert scoped["pattern_items"][0]["statement"] == "先观察再行动"
    assert "SECRET" not in json.dumps(
        {**scoped, "world_items": scoped["world_items"][:1]}
    )
    assert "UNAPPROVED_METADATA" not in json.dumps(scoped)
    changed = deepcopy(brief)
    changed["world_items"][0]["revision_id"] = "replaced-revision"
    assert all(
        item["entry_id"] != "kept"
        for item in restrict_object_dossier_brief(changed, confirmed.compiled)[
            "world_items"
        ]
    )
    assert (
        restrict_object_dossier_brief(brief, CompiledContext(sections=[]))["world_items"]
        == []
    )


async def test_director_packets_intersect_confirmation_and_role_pov(monkeypatch):
    from modules.story.simulation_v3 import SimulationV3Context

    actor, scene, brief, confirmed = confirmed_fixture()
    role_brief = deepcopy(brief)
    role_brief["world_items"] = [
        row for row in role_brief["world_items"] if row["entry_id"] != "author"
    ]
    role_brief["pattern_items"] = []
    observed = []

    async def build(_db, **kwargs):
        observed.append(kwargs["brief"])
        return SimulationV3Context()

    monkeypatch.setattr(
        "modules.story.director_context.build_scene_simulation_context", build
    )
    source = {
        "novel_id": str(uuid4()),
        "scene_id": scene,
        "source_hash": "a" * 64,
        "scene_context": {"secret_card": "EXCLUDED_SECRET"},
        "author_brief": brief,
        "role_briefs": {actor: {"brief": role_brief}},
        "author_examples": {"text": "EXCLUDED_SECRET"},
        "object_validity_notices": [{"story_observation": "EXCLUDED_SECRET"}],
    }
    scoped = await scope_director_source(None, source, confirmed)
    author_packet = director_only_packet(scoped, "", "")
    actor_packet, _ = _fit_packet(
        scoped, actor, "门外起风", 10000, include_author_examples=True
    )
    assert "说话简短" in actor_packet and "衣服湿透" in actor_packet
    assert "AUTHOR_ONLY_SECRET" in author_packet
    assert "AUTHOR_ONLY_SECRET" not in actor_packet
    for secret in (
        "EXCLUDED_SECRET",
        "EVICTED_SECRET",
        "TRUNCATED_SECRET",
        "UNAPPROVED_METADATA",
    ):
        assert secret not in author_packet + actor_packet + json.dumps(observed)
    assert scoped["source_hash"] == source["source_hash"]  # budget preview identity
    scope = director_confirmation_scope(confirmed)
    require_director_confirmation_scope(scoped, scope)
    for parent in ({}, {"confirmation_scope_hash": "old-scope"}):
        with pytest.raises(ValueError, match="新建导演运行"):
            require_director_confirmation_scope(parent, scope)
