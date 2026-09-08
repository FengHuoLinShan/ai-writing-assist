"""Focused completion checks use exact local prose and no provider/network I/O."""

from __future__ import annotations

import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from modules.imports.api import DeepImportRequest
from modules.imports.completion_hints import alias_completion_hints, completion_hints
from modules.imports.llm_schemas import ExtractedEntity, SceneEntityExtractionOutput
from modules.imports.schemas import TargetedCompletionRequest
from modules.imports.targeted_completion import (
    CompletionOutput,
    freeze_completion_permission,
    materialize_completion,
    normalize_roots,
    run_targeted_completion,
    select_automatic_roots,
    stable_hash,
)
from modules.imports.workflow import DeepImportWorkflow
from modules.imports.workflow_schemas import DeepImportProgress
from modules.writing.contracts import SourceRangeRefContract, WritingDraftContract

ENTITY_ID = "00000000-0000-0000-0000-000000000001"
DRAFT_ID = "00000000-0000-0000-0000-000000000002"


def _target(key="a", name="小文", *, resolved=True, depth=0, proof=None):
    return SimpleNamespace(
        key=key,
        name=name,
        target_ref={"target_id": ENTITY_ID} if resolved else None,
        resolution="resolved" if resolved else "unresolved",
        depth=depth,
        root_keys=["root"],
        direct_evidence_refs=proof or [],
    )


def _result(targets=None, text="小文是一名守卫。小文守护苍桥。"):
    source = SourceRangeRefContract(
        draft_id=DRAFT_ID,
        chapter_index=1,
        version_number=1,
        content_mode="working",
        start_offset=10,
        end_offset=10 + len(text),
        source_hash="a" * 64,
        range_hash=hashlib.sha256(text.encode()).hexdigest(),
    )
    return SimpleNamespace(
        targets=targets or [_target()],
        evidence=[
            SimpleNamespace(
                key="e1", source_ref=source, text=text, target_keys=["a", "b"]
            )
        ],
    )


def test_wire_requires_explicit_authorization_and_exclusive_identity():
    assert not DeepImportRequest(
        novel_id="n", authorization_confirmed=True
    ).targeted_completion.enabled
    with pytest.raises(ValidationError):
        TargetedCompletionRequest(
            novel_id="n", targets=[{"name": "小文"}], authorization_confirmed=False
        )
    with pytest.raises(ValidationError):
        TargetedCompletionRequest(
            novel_id="n",
            targets=[{"name": "小文", "entity_id": ENTITY_ID}],
            authorization_confirmed=True,
        )
    with pytest.raises(ValidationError):
        TargetedCompletionRequest(
            novel_id="n",
            targets=[{"name": "小文"}],
            start_chapter=3,
            end_chapter=2,
            authorization_confirmed=True,
        )


def test_roots_are_stable_and_not_silently_limited_to_a_batch():
    roots = normalize_roots(
        [{"name": f"对象{i}"} for i in range(37)] + [{"name": "对象0"}]
    )
    assert len(roots) == 37
    assert roots[0] == {"key": "name:对象0", "name": "对象0"}


async def test_disabled_and_old_authorization_do_not_read_or_call_llm():
    assert (
        await freeze_completion_permission(
            None, novel_id="n", start_chapter=1, end_chapter=2, options={"enabled": False}
        )
        is None
    )
    await run_targeted_completion(
        None,
        task=None,
        progress=DeepImportProgress(),
        checkpoint=None,
        project_settings={},
    )


async def test_submission_freezes_exact_source_manifest_without_prose():
    drafts = [
        WritingDraftContract(
            novel_id="n",
            chapter_index=1,
            id=DRAFT_ID,
            content_hash="a" * 64,
            content="secret prose",
        )
    ]
    with patch(
        "modules.writing.facade.list_latest_drafts_for_chapters",
        autospec=True,
        return_value=drafts,
    ):
        permission = await freeze_completion_permission(
            None,
            novel_id="n",
            start_chapter=1,
            end_chapter=1,
            options={"enabled": True},
            targets=[{"name": "小文"}],
        )
    assert permission["source_manifest"] == {DRAFT_ID: "a" * 64}
    assert permission["source_manifest_hash"] == stable_hash(
        permission["source_manifest"]
    )
    assert permission["root_selection"] == "explicit"
    assert "secret prose" not in str(permission)


def test_hints_require_a_specific_gap_and_literal_source_name():
    text = "小文是一名守卫。"
    plain = ExtractedEntity(name="小文", entity_type="character", evidence_quotes=[text])
    gap = plain.model_copy(update={"candidate_reason": "public_info_evidence_not_found"})
    missing = plain.model_copy(
        update={"name": "假名", "candidate_reason": "identity_uncertain"}
    )
    output = SceneEntityExtractionOutput(entities=[plain, gap, missing])
    hints = completion_hints(output, scene_id="scene", source_text=text)
    assert len(hints) == 1
    assert hints[0]["name"] == "小文"
    assert hints[0]["fields"] == ["public_info"]


def test_missing_endpoint_name_survives_only_with_matching_quote():
    diagnostics = [
        {
            "kind": "relation_endpoint",
            "mention_name": "苍桥",
            "related_refs": [],
            "reason": "unknown_relation_endpoint_ref",
            "evidence_quotes": ["小文守护苍桥。"],
        }
    ]
    hints = alias_completion_hints(
        diagnostics, scene_id="s", source_text="小文守护苍桥。", context_bundle={}
    )
    assert [hint["name"] for hint in hints] == ["苍桥"]
    assert not alias_completion_hints(
        diagnostics, scene_id="s", source_text="无此内容", context_bundle={}
    )


def test_materializer_keeps_only_exact_supported_fields_and_offsets():
    output = CompletionOutput.model_validate(
        {
            "entities": [
                {
                    "target_key": "a",
                    "entity_type": "character",
                    "summary": "一名守卫",
                    "hidden_truth": "来自未来",
                    "field_evidence": {
                        "summary": [{"evidence_key": "e1", "quote": "小文是一名守卫。"}],
                        "hidden_truth": [{"evidence_key": "e1", "quote": "不存在的证据"}],
                    },
                }
            ]
        }
    )
    items, diagnostics = materialize_completion(
        output, _result(), batch_keys=["a"], workflow_id="wf"
    )
    assert items[0]["payload"] == {
        "operation": "fill_empty",
        "entity_id": ENTITY_ID,
        "fields": {"summary": "一名守卫"},
    }
    source = items[0]["source_refs"][0]["source_range"]
    assert source["start_offset"] == 10
    assert source["end_offset"] == 10 + len("小文是一名守卫。")
    assert source["range_hash"] == hashlib.sha256("小文是一名守卫。".encode()).hexdigest()
    assert diagnostics


def test_materializer_new_identity_needs_name_and_type_evidence():
    result = _result(targets=[_target(resolved=False)])
    output = CompletionOutput.model_validate(
        {
            "entities": [
                {
                    "target_key": "a",
                    "entity_type": "character",
                    "summary": "守卫",
                    "field_evidence": {
                        "summary": [{"evidence_key": "e1", "quote": "小文是一名守卫。"}]
                    },
                }
            ]
        }
    )
    assert not materialize_completion(output, result, batch_keys=["a"], workflow_id="wf")[
        0
    ]
    quote = {"evidence_key": "e1", "quote": "小文是一名守卫。"}
    output.entities[0].field_evidence = {
        field: [
            type(output.entities[0].field_evidence["summary"][0]).model_validate(quote)
        ]
        for field in ("name", "entity_type", "summary")
    }
    items, _ = materialize_completion(output, result, batch_keys=["a"], workflow_id="wf")
    assert items[0]["payload"]["operation"] == "create"
    assert items[0]["payload"]["entity"]["name"] == "小文"


def test_neighbor_keeps_exact_direct_proof_and_db_relation_proof():
    source = _result().evidence[0].source_ref
    from dataclasses import asdict

    proof = [
        {
            "source_ref": asdict(source),
            "quote": "小文守护苍桥。",
            "basis": "literal_quote",
        },
        {"relation_id": "edge", "source_hash": "b" * 64, "basis": "canonical_relation"},
    ]
    target = _target(depth=1, proof=proof)
    output = CompletionOutput.model_validate(
        {
            "entities": [
                {
                    "target_key": "a",
                    "summary": "守卫",
                    "field_evidence": {
                        "summary": [{"evidence_key": "e1", "quote": "小文是一名守卫。"}]
                    },
                }
            ]
        }
    )
    items, _ = materialize_completion(
        output, _result(targets=[target]), batch_keys=["a"], workflow_id="wf"
    )
    assert items[0]["depth"] == 1
    assert len(items[0]["source_refs"]) == 2
    assert items[0]["direct_relation_ref"]["relation_id"] == "edge"


def test_neighbor_to_neighbor_edge_and_unknown_target_are_not_written():
    result = _result(targets=[_target(depth=1), _target(key="b", name="苍桥", depth=1)])
    output = CompletionOutput.model_validate(
        {
            "entities": [{"target_key": "unknown"}],
            "relations": [
                {
                    "source_key": "a",
                    "target_key": "b",
                    "relation_type": "守护",
                    "description": "小文守护苍桥",
                    "evidence": [{"evidence_key": "e1", "quote": "小文守护苍桥。"}],
                }
            ],
        }
    )
    items, diagnostics = materialize_completion(
        output, result, batch_keys=["a"], workflow_id="wf"
    )
    assert not items and len(diagnostics) == 2


async def test_automatic_roots_filter_filled_fields_and_include_workflow_unresolved():
    progress = DeepImportProgress(
        checkpoints={
            "phase2": {
                "scenes": [
                    {
                        "created_entity_ids": [ENTITY_ID],
                        "completion_hints": [
                            {
                                "name": "小文",
                                "quote": "小文是一名守卫",
                                "kind": "field_gap",
                                "fields": ["summary"],
                            },
                            {
                                "name": "苍桥",
                                "quote": "小文守护苍桥",
                                "kind": "relation_endpoint",
                            },
                        ],
                    }
                ]
            }
        }
    )
    context = SimpleNamespace(
        entities=[
            SimpleNamespace(
                entity_id=ENTITY_ID,
                name="小文",
                aliases=[],
                summary="作者已填",
                public_info=None,
                hidden_truth=None,
            )
        ]
    )

    async def trace(_db, **kwargs):
        return (
            {
                "links": [
                    {
                        "status": "needs_review",
                        "id": "link",
                        "provenance": {"workflow_id": "wf", "quote": "小文是一名守卫"},
                    }
                ]
            }
            if kwargs["claim_path"] == "public_info"
            else {"links": []}
        )

    with (
        patch(
            "modules.world.facade.get_world_context", autospec=True, return_value=context
        ),
        patch(
            "modules.evidence.facade.trace_novel_evidence",
            autospec=True,
            side_effect=trace,
        ),
    ):
        roots = await select_automatic_roots(
            None, novel_id="n", workflow_id="wf", progress=progress
        )
    assert roots == [
        {"key": "name:苍桥", "name": "苍桥"},
        {"key": "entity:" + ENTITY_ID, "entity_id": ENTITY_ID},
    ]
    assert any(
        item["kind"] == "unresolved_evidence"
        for item in progress.checkpoints["completion_hints"]
    )


async def test_full_import_resume_enters_completion_without_replaying_scene_or_phase2():
    scene, entity = AsyncMock(), AsyncMock()
    structure = SimpleNamespace(
        run_full_pipeline=AsyncMock(return_value={"total_threads": 1})
    )
    runners = SimpleNamespace(
        scene_full=scene, entity_full=entity, structure_full=structure
    )
    workflow = DeepImportWorkflow(phase_runners=runners)
    progress = DeepImportProgress(
        quality_stats={"phase2": {"total_scenes": 2}},
        checkpoints={"targeted_completion": {"status": "running"}},
    )
    continuation = AsyncMock()
    with patch.object(
        workflow, "_is_llm_health_required", autospec=True, return_value=False
    ):
        result = await workflow.run_step(
            None,
            "n",
            1,
            2,
            progress,
            project_settings={},
            on_targeted_completion=continuation,
        )
    scene.run_full_pipeline.assert_not_awaited()
    entity.run_full_pipeline.assert_not_awaited()
    continuation.assert_awaited_once_with(progress)
    assert result.phase == "done"


@pytest.mark.parametrize(
    ("confidence", "certainty", "expected"),
    [
        (None, "explicit", "open"),
        (0, "explicit", "open"),
        (0.89, "explicit", "open"),
        (0.99, "inference", "open"),
        (0.99, "uncertain", "open"),
        (0.99, "explicit", "include"),
    ],
)
def test_each_claim_quality_is_independent_of_other_high_confidence_claims(
    confidence, certainty, expected
):
    quote = {"evidence_key": "e1", "quote": "小文是一名守卫。"}
    result = _result(targets=[_target(), _target(key="b", name="苍桥")])
    output = CompletionOutput.model_validate(
        {
            "entities": [
                {
                    "target_key": "a",
                    "summary": "守卫",
                    "confidence": confidence,
                    "certainty": certainty,
                    "field_evidence": {"summary": [quote]},
                },
                {
                    "target_key": "b",
                    "summary": "桥梁",
                    "confidence": 0.99,
                    "certainty": "explicit",
                    "field_evidence": {
                        "summary": [{"evidence_key": "e1", "quote": "小文守护苍桥。"}]
                    },
                },
            ]
        }
    )
    items, _ = materialize_completion(
        output, result, batch_keys=["a", "b"], workflow_id="wf"
    )
    assert [item["disposition"] for item in items] == [expected, "include"]
    assert bool(items[0]["review_reasons"]) is (expected == "open")


def test_missing_quality_defaults_to_review_even_with_exact_quotes():
    output = CompletionOutput.model_validate(
        {
            "entities": [
                {
                    "target_key": "a",
                    "summary": "守卫",
                    "field_evidence": {
                        "summary": [{"evidence_key": "e1", "quote": "小文是一名守卫。"}]
                    },
                }
            ]
        }
    )
    items, _ = materialize_completion(
        output, _result(), batch_keys=["a"], workflow_id="wf"
    )
    assert items[0]["disposition"] == "open"
    assert "missing_or_low_confidence" in items[0]["review_reasons"]


def test_low_confidence_alias_and_inferred_relation_stay_review_only():
    left, right = _target(), _target(key="b", name="苍桥", depth=1)
    right.target_ref = {"target_id": DRAFT_ID}
    result = _result(targets=[left, right])
    output = CompletionOutput.model_validate(
        {
            "aliases": [
                {
                    "target_key": "a",
                    "alias": "守卫",
                    "alias_kind": "title",
                    "confidence": 0,
                    "certainty": "explicit",
                    "evidence": [{"evidence_key": "e1", "quote": "小文是一名守卫。"}],
                }
            ],
            "relations": [
                {
                    "source_key": "a",
                    "target_key": "b",
                    "relation_type": "守护",
                    "relation_kind": "spatial",
                    "description": "小文守护苍桥",
                    "confidence": 0.99,
                    "certainty": "inference",
                    "evidence": [{"evidence_key": "e1", "quote": "小文守护苍桥。"}],
                }
            ],
        }
    )
    items, _ = materialize_completion(
        output, result, batch_keys=["a", "b"], workflow_id="wf"
    )
    assert len(items) == 2
    assert all(item["disposition"] == "open" for item in items)
    assert items[0]["review_reasons"] == ["missing_or_low_confidence"]
    assert items[1]["review_reasons"] == ["inferred_or_uncertain_claim"]
