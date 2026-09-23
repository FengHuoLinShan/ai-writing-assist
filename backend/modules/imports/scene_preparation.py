"""Reuse source planning/slicing/commit without starting a legacy workflow owner."""

from infrastructure.llm.collaboration import content_hash
from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
from modules.imports.llm_schemas import SceneSlicingOutput
from modules.imports.phase1a_context import _left_boundary_context
from modules.imports.scene_commit import SceneCommitter, _build_structure_meta
from modules.imports.scene_enrichment import (
    _final_candidate,
    _validate_enrichment_evidence,
)
from modules.imports.scene_fusion import FinalSceneCandidate
from modules.imports.scene_planning import ScenePlanResult, build_scene_import_plan
from modules.imports.scene_slicing import (
    Phase1aSceneSlicer,
    SceneSliceCandidate,
    SceneSlicingResult,
)
from modules.imports.workflow_llm_adapters import (
    _phase1a_scene_system_prompt,
    _phase1a_scene_user_prompt,
    build_scene_enrichment_request,
)


def scene_enrichment_input(scene, source_parts, scene_text, input_manifest):
    """Only exact current prose and the committed parent enter the Scene prompt."""
    meta = scene.get("structure_meta") or {}
    source, cursor = [], 0
    for index, part in enumerate(source_parts):
        length = part["end_offset"] - part["start_offset"]
        if length <= 0:
            raise ValueError("scene enrichment requires exact nonempty ranges")
        source.append(
            {
                "chunk_index": index,
                "chapter_index": part["chapter_index"],
                "start_offset": part["start_offset"],
                "end_offset": part["end_offset"],
                "source_draft_id": part["draft_id"],
                "source_content_hash": part["content_hash"],
                "text": scene_text[cursor : cursor + length],
            }
        )
        cursor += length
    if not source or cursor != len(scene_text):
        raise ValueError("scene enrichment requires complete source coverage")
    locked = SceneSliceCandidate(
        candidate_id=scene["id"],
        source_window_id="evolution-scene",
        source_window_index=1,
        title=scene.get("title") or "",
        goal=scene.get("goal") or "",
        core_conflict=scene.get("core_conflict") or "",
        core_conflict_status=meta.get("core_conflict_status", "uncertain"),
        phase1a_confidence=meta.get("phase1a_confidence", 0),
        boundary_basis=meta.get("boundary_basis", ""),
        start_chapter=source[0]["chapter_index"],
        end_chapter=source[-1]["chapter_index"],
        source_chapter_indices=sorted({part["chapter_index"] for part in source}),
        scene_chunks=[
            {
                key: value
                for key, value in part.items()
                if key not in {"chunk_index", "text"}
            }
            for part in source
        ],
        boundary_status=meta.get("boundary_status", "complete"),
        needs_review=bool(meta.get("needs_review")),
        review_reason=meta.get("review_reason", ""),
    )
    return {
        "locked_scene": locked.model_dump(mode="json"),
        "scene_source": source,
        "scene_guard": content_hash(scene),
        "boundary_review": meta.get("boundary_review"),
        "related_context": {"committed_parent": input_manifest},
        "context_fingerprint": content_hash(input_manifest),
        "source_integrity": {
            "complete": True,
            "source_fingerprint": content_hash(source),
        },
        "sequence_index": scene["scene_index"] + 1,
    }


def enrichment_request(payload):
    from modules.imports.llm_schemas import SceneEnrichmentOutput

    request, _ = build_scene_enrichment_request(payload)
    return request, SceneEnrichmentOutput


def materialize_enrichment(payload, result):
    from modules.imports.llm_schemas import SceneEnrichmentOutput

    output = _validate_enrichment_evidence(
        SceneEnrichmentOutput.model_validate(result), payload["scene_source"]
    )
    candidate = _final_candidate(
        SceneSliceCandidate.model_validate(payload["locked_scene"]),
        output,
        sequence_index=payload["sequence_index"],
        fallback_required=False,
        source_integrity=payload["source_integrity"],
        context_fingerprint=payload["context_fingerprint"],
    )
    return candidate.model_dump(mode="json")


def enrichment_update(scene, result, workflow_id):
    candidate = FinalSceneCandidate.model_validate(result["candidate"])
    meta = scene.get("structure_meta") or {}
    if (
        result["review"]["status"] != "passed"
        or candidate.confidence < 0.9
        or candidate.needs_review
    ):
        reason = "新整理的叙事信息尚待核对，请检查建议和正文后编辑。"
        if result["review"]["status"] == "passed":
            reason = "独立核对已完成，但整理建议置信不足或仍有未决约束，请检查后编辑。"
        return {
            "structure_meta": {
                **meta,
                "needs_review": True,
                "review_reason": reason,
                "evolution_semantic_proposal": result,
                "knowledge_review": result["review"],
                "review_issues": [
                    *meta.get("review_issues", []),
                    {"kind": "semantic_review", "required": True, "message": reason},
                ],
            }
        }
    compiled = _build_structure_meta(
        candidate, workflow_id=workflow_id, provenance_key=meta.get("provenance_key", "")
    )
    semantic_meta = {
        key: value
        for key, value in compiled.items()
        if key.startswith(("phase1b_", "semantic_", "review_"))
        or key in {"narrative_function", "needs_review"}
    }
    return {
        **{
            key: getattr(candidate, key)
            for key in (
                "emotional_beat",
                "must_happen",
                "must_not_happen",
                "narrative_tag",
            )
        },
        "structure_meta": {
            **meta,
            **semantic_meta,
            "phase": "phase1b_enrichment",
            "knowledge_review": result["review"],
            "evolution_run": workflow_id,
        },
    }


def plan_boundaries(chapters, boundary_chapters=()):
    plan = build_scene_import_plan(
        chapters,
        start_chapter=chapters[0]["chapter_index"],
        end_chapter=chapters[-1]["chapter_index"],
    )
    sources = {
        chapter["chapter_index"]: chapter for chapter in [*chapters, *boundary_chapters]
    }
    for window in plan.windows:
        window.left_boundary_context = _left_boundary_context(window, sources)
    return plan.model_dump(mode="json", exclude={"chapters"})


def boundary_request(payload):
    return LLMCallRequest(
        messages=[
            LLMMessage(role="system", content=_phase1a_scene_system_prompt()),
            LLMMessage(
                role="user",
                content=_phase1a_scene_user_prompt(
                    chapters=payload["chapters"],
                    window=payload["window"],
                    left_boundary_context=payload.get("left_boundary_context") or "",
                    reference_context=payload.get("reference_context") or {},
                    validation_feedback=payload.get("validation_feedback"),
                ),
            ),
        ],
        temperature=0.2,
        max_tokens=payload["max_tokens"],
        response_format={"type": "json_object"},
    ), SceneSlicingOutput


async def slice_boundaries(plan, chapters, call):
    # The caller owns every request, retry, frozen response and budget reservation.
    result = await Phase1aSceneSlicer(call, concurrency=1).run(
        ScenePlanResult.model_validate({**plan, "chapters": chapters})
    )
    return result.model_dump(mode="json")


async def commit_boundaries(db, novel_id, result, *, workflow_id, start, end):
    sliced = SceneSlicingResult.model_validate(result)
    # Array order is a model claim. Only exact source order may become Scene order.
    ordered = sorted(
        sliced.candidates,
        key=lambda candidate: min(
            (chunk.chapter_index, chunk.start_offset or 0)
            for chunk in candidate.scene_chunks
        ),
    )
    if ordered:
        last = ordered[-1]
        edges = last.diagnostics.get("window_edges") or {}
        if (
            last.boundary_status == "continues_right"
            or edges.get("trailing_relation") == "continues_right"
        ):
            last.needs_review = True
            last.review_reason = "所选正文在场景中途结束，请确认完整场景边界后再理解。"
    unresolved = {
        window
        for diagnostic in sliced.diagnostics
        if diagnostic.get("kind") == "window_edge_coordination"
        for window in diagnostic.get("unresolved_continuation_window_ids", [])
    }
    for candidate in ordered:
        if candidate.source_window_id in unresolved:
            candidate.needs_review = True
            candidate.review_reason = (
                "该范围承接了尚未确认归属的前序场景，请核对衔接边界。"
            )
    candidates = [
        FinalSceneCandidate(
            **{
                key: value
                for key, value in candidate.model_dump().items()
                if key in FinalSceneCandidate.model_fields
                and key not in {"needs_review", "review_reason"}
            },
            phase="phase1a_slicing",
            source_candidate_ids=[candidate.candidate_id],
            confidence=candidate.phase1a_confidence,
            fallback_required=candidate.boundary_status == "fallback",
            needs_review=candidate.needs_review or candidate.phase1a_confidence < 0.90,
            review_reason=candidate.review_reason
            or (
                "场景边界置信不足，请确认来源与结构。"
                if candidate.phase1a_confidence < 0.90
                else ""
            ),
            phase1b_field_statuses={
                field: "uncertain"
                for field in ("emotional_beat", "must_happen", "must_not_happen")
            },
            phase1b_uncertain_fields=[
                "emotional_beat",
                "narrative_tag",
                "narrative_function",
            ],
        )
        for candidate in ordered
    ]
    result = await SceneCommitter().commit(
        db, novel_id, candidates, workflow_id, start_chapter=start, end_chapter=end
    )
    return result.model_dump(mode="json")
