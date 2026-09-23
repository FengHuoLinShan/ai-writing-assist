"""Pure Phase 3 requests and review compilation for the sequential reading owner."""

import json
from uuid import UUID

from modules.story.outline_state.generation.context_builder import PlotStructureContext
from modules.story.outline_state.generation.models import (
    SimpleStructureOutput,
    StructureEvidenceReviewOutput,
)
from modules.story.outline_state.generation.parser import (
    PlotStructureParser,
    _apply_structure_evidence,
    _materialize_structure_evidence,
    _normalize_simple_structure_refs,
    _phase3_evidence_batches,
    _phase3_evidence_request,
    _prepare_structure_evidence,
    _simple_structure_to_parsed,
)


def build_structure_request(scene_cards, world_context):
    context = PlotStructureContext(
        markdown=json.dumps(world_context, ensure_ascii=False), scenes=scene_cards
    )
    request, _ = PlotStructureParser(
        context, fast_structured=True
    )._build_deep_import_simple_request(
        "",
        min(item["start_chapter"] for item in scene_cards),
        max(item["end_chapter"] for item in scene_cards),
        scene_cards,
    )
    return request, SimpleStructureOutput


def prepare_structure_review(raw, scene_cards):
    scenes = {item["scene_id"]: item for item in scene_cards}
    output, _ = _normalize_simple_structure_refs(
        SimpleStructureOutput.model_validate(raw), scenes
    )
    _, units, _ = _prepare_structure_evidence(output, scenes)
    return [
        (
            _phase3_evidence_request(model="", batch=batch, high_quality=False),
            StructureEvidenceReviewOutput,
        )
        for batch in _phase3_evidence_batches(units)
    ]


def materialize_structure_review(raw, scene_cards, results):
    scenes = {item["scene_id"]: item for item in scene_cards}
    output, invalid = _normalize_simple_structure_refs(
        SimpleStructureOutput.model_validate(raw), scenes
    )
    states, units, mapping = _prepare_structure_evidence(output, scenes)
    batches = _phase3_evidence_batches(units)
    if len(results) != len(batches):
        raise ValueError("Structure review calls are incomplete")
    verdicts = []
    for batch, result in zip(batches, results, strict=True):
        verdicts.extend(
            _apply_structure_evidence(
                states,
                mapping,
                StructureEvidenceReviewOutput.model_validate(result),
                batch,
            )
        )
    reviewed, diagnostics = _materialize_structure_evidence(
        output, states, len(batches), 0, verdicts, {}
    )
    return {
        "output": reviewed.model_dump(mode="json"),
        "diagnostics": {**diagnostics, "invalid_scene_ref_count": invalid},
    }


async def persist_structure_drafts(
    db, novel_id, *, raw, scene_cards, reviews, provenance
):
    """Recompile the frozen reviews and persist editable, unadopted Story drafts."""
    from modules.story.outline_state.generator import PlotStructureGenerator

    materialized = materialize_structure_review(raw, scene_cards, reviews)
    output = SimpleStructureOutput.model_validate(materialized["output"])
    start = min(item["start_chapter"] for item in scene_cards)
    end = max(item["end_chapter"] for item in scene_cards)
    parsed = _simple_structure_to_parsed(
        output,
        scene_by_id={item["scene_id"]: item for item in scene_cards},
        start_chapter=start,
        end_chapter=end,
        diagnostics=materialized["diagnostics"],
    )
    result = await PlotStructureGenerator()._persister.persist(
        db,
        UUID(novel_id),
        start,
        end,
        parsed,
        entity_name_to_id={},
        character_name_to_id={},
        strict=True,
        provenance_meta_override={
            **provenance,
            "source": "evolution",
            "auto_ingested": True,
            "user_edited": False,
            "needs_review": True,
        },
    )
    return {
        **materialized,
        "result_refs": PlotStructureGenerator.result_refs(result.to_dict()),
    }
