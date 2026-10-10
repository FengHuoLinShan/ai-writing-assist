"""Scale invariants: exhaustive shards, real limits, stable scopes and identity veto."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from infrastructure.llm.collaboration import content_hash
from modules.evolution.discovery import (
    _chunks,
    _discovery_envelope,
    compile_discovery,
)
from modules.evolution.discovery_capacity import (
    REQUEST_CHARACTERS,
    build_batches,
    identity_review_inputs,
    serialized_size,
)
from modules.evolution.ledger_contracts import DiscoveryOutput
from modules.evolution.tests.issue209_data import synthetic_descriptors
from modules.evolution.tests.test_discovery_occurrences import prepared_occurrence


@pytest.mark.parametrize("themes", [0, 1, 100, 1000])
@pytest.mark.parametrize("scene_size", [100, 16000, 70000])
def test_exhaustive_deterministic_partitions(themes, scene_size):
    text = "前文。" * (scene_size // 3) + "人物举起钥匙。"
    current = [{"observation_id": "current", "quotes": ["人物举起钥匙。"]}]
    descriptors = synthetic_descriptors(themes)
    history = [
        {
            "observation": {
                "observation_id": f"candidate-{i}",
                "quotes": [f"历史原句{i}。"],
            }
        }
        for i in range(50)
    ]
    context = [{"theme": item} for item in descriptors] + history
    kwargs = dict(scene_index=3, semantics="有源", recall_scope={}, chunks=_chunks)
    result = build_batches(text, current, context, descriptors, **kwargs)
    assert result == build_batches(
        text, current, context, list(reversed(descriptors)), **kwargs
    )
    batches, unsupported, scopes, indexes = result
    assert not unsupported
    assert all(serialized_size(batch) <= REQUEST_CHARACTERS for batch in batches)
    assert {item["entry_id"] for shard in indexes for item in shard} == {
        item["entry_id"] for item in descriptors
    }
    assert {identity for scope in scopes for identity in scope["theme_ids"]} == {
        item["entry_id"] for item in descriptors
    }
    assert {
        identity for scope in scopes for identity in scope["historical_observation_ids"]
    } == {item["observation"]["observation_id"] for item in history}
    # All original characters are covered; overlap never grants extra authority.
    covered = set()
    for scope in scopes:
        bounds = scope["scene_text_range"]
        covered.update(range(bounds["start_offset"], bounds["end_offset"]))
    assert len(covered) == len(text)
    primary = [
        batch
        for batch in batches
        if batch["allow_new_themes"] and "current" in batch["current_observation_ids"]
    ]
    assert len(primary) == 1


def test_oversized_atomic_theme_is_disclosed_without_losing_other_batches():
    descriptors = synthetic_descriptors(2)
    descriptors[1]["evidence_observations"][0]["quotes"] = ["超" * 60000]
    batches, unsupported, scopes, _ = build_batches(
        "人物举钥匙。",
        [{"observation_id": "current", "quotes": ["人物举钥匙。"]}],
        [{"theme": item} for item in descriptors],
        descriptors,
        scene_index=0,
        semantics="有源",
        recall_scope={},
        chunks=_chunks,
    )
    assert unsupported and len(unsupported) < len(batches)
    assert scopes[unsupported[0]]["theme_ids"] == ["theme-000001"]
    assert all(
        serialized_size(batch) <= REQUEST_CHARACTERS
        for i, batch in enumerate(batches)
        if i not in unsupported
    )


@pytest.mark.parametrize("identity_verdict", [None, "rejected", "uncertain", "supported"])
def test_new_theme_requires_every_identity_shard(identity_verdict):
    prepared, batch, change = prepared_occurrence()
    batch.update(theme_index=[], scene_text="甲紧张地摸了摸戒指。")
    prepared.update(
        batches=[batch],
        unsupported_batches=[],
        coverage={},
        theme_index_shards=[[], [{"entry_id": "old-theme", "label": "摸戒指"}]],
    )
    output = DiscoveryOutput.model_validate(
        {
            "changes": [change],
            "coverage": "inspected",
            "coverage_note": "检查了给定输入。",
        }
    )
    ids = batch["current_observation_ids"]
    payload = {
        "discovery_preparation": prepared,
        "scene_discovery_0": {
            "stage": "sampled",
            "result": output.model_dump(mode="json"),
        },
        "scene_discovery_review_0": {
            "result": {
                "verdicts": [
                    {
                        "change_index": 0,
                        "verdict": "supported",
                        "reason": "来源支持。",
                        "occurrence_observation_ids": ids,
                    }
                ]
            }
        },
    }
    frozen = SimpleNamespace(
        payload=payload,
        attempt_id="attempt",
        source_manifest_hash="a" * 64,
        previous_receipt=None,
    )
    if identity_verdict:
        inputs = identity_review_inputs(
            batch, output.changes, prepared["theme_index_shards"][1], 1
        )
        payload["scene_discovery_identity_0_1"] = {
            "stage": "sampled",
            "input_hash": content_hash(_discovery_envelope(frozen, prepared, inputs)),
            "result": {
                "verdicts": [
                    {
                        "change_index": 0,
                        "verdict": identity_verdict,
                        "reason": "已检查这一片。",
                    }
                ]
            },
        }
    result = compile_discovery(frozen)
    assert bool(result["changes"]) == (identity_verdict == "supported")
    assert bool(result["coverage"]["identity_review_gaps"]) == (identity_verdict is None)
    assert result == compile_discovery(frozen)  # Frozen replay is deterministic.
    if identity_verdict == "supported":
        tampered = deepcopy(payload["scene_discovery_identity_0_1"])
        tampered["input_hash"] = "changed"
        payload["scene_discovery_identity_0_1"] = tampered
        assert not compile_discovery(frozen)["changes"]


def test_repeated_quote_windows_use_authoritative_source_offsets():
    from modules.evolution.discovery_capacity import current_text_ranges, scene_windows

    quote = "甲举起钥匙。"
    text = quote + "前文。" * 10000 + quote
    start = len(text) - len(quote)
    payload = {
        "scene_text": text,
        "source_binding": {
            "draft_id": "draft",
            "chapter_index": 1,
            "start_offset": 30,
            "end_offset": 30 + len(text),
        },
    }
    records = [
        {
            "observation_id": "last-occurrence",
            "evidence_quotes": [
                {
                    "quote": quote,
                    "source_ref": {
                        "draft_id": "draft",
                        "start_offset": 30 + start,
                        "end_offset": 30 + len(text),
                    },
                }
            ],
        }
    ]
    ranges = current_text_ranges(payload, records)
    windows = scene_windows(
        text,
        [
            {
                "observation_id": "last-occurrence",
                "quotes": [quote],
                "scene_text_ranges": ranges["last-occurrence"],
            }
        ],
    )
    assigned = [(left, right) for left, right, items in windows if items]
    assert len(assigned) == 1
    assert assigned[0][0] <= start < len(text) <= assigned[0][1]
    assert assigned[0][0] > 0


def test_cross_chapter_quote_ranges_preserve_scene_positions():
    from modules.evolution.discovery_capacity import current_text_ranges

    payload = {
        "scene_text": "前半后半",
        "source_binding": {
            "draft_id": "first",
            "chapter_index": 1,
            "start_offset": 10,
            "end_offset": 12,
            "additional_sources": [
                {
                    "draft_id": "second",
                    "chapter_index": 2,
                    "start_offset": 20,
                    "end_offset": 22,
                }
            ],
        },
    }
    ranges = current_text_ranges(
        payload,
        [
            {
                "observation_id": "cross",
                "evidence_quotes": [
                    {
                        "quote": "半",
                        "source_ref": {
                            "draft_id": "first",
                            "start_offset": 11,
                            "end_offset": 12,
                        },
                    },
                    {
                        "quote": "后",
                        "source_ref": {
                            "draft_id": "second",
                            "start_offset": 20,
                            "end_offset": 21,
                        },
                    },
                ],
            }
        ],
    )
    assert ranges == {"cross": [[1, 2], [2, 3]]}


def test_giant_first_index_and_context_do_not_poison_all_other_batches():
    descriptors = synthetic_descriptors(2)
    descriptors[0]["label"] = "超" * 60000
    batches, unsupported, scopes, shards = build_batches(
        "人物举钥匙。",
        [{"observation_id": "current", "quotes": ["人物举钥匙。"]}],
        [{"theme": item} for item in descriptors],
        descriptors,
        scene_index=0,
        semantics="有源",
        recall_scope={},
        chunks=_chunks,
    )
    assert unsupported and len(unsupported) < len(batches)
    assert {item["entry_id"] for shard in shards for item in shard} == {
        item["entry_id"] for item in descriptors
    }
    supported = [batch for i, batch in enumerate(batches) if i not in unsupported]
    assert sum(batch["allow_new_themes"] for batch in supported) == 1
    assert all(serialized_size(batch) <= REQUEST_CHARACTERS for batch in supported)
    assert scopes[unsupported[0]]["theme_ids"] == ["theme-000000"]
