"""Frozen synthetic long-book coverage for distant recall and bounded discovery input."""

import json
from types import SimpleNamespace
from uuid import UUID

import pytest

from modules.evolution.discovery import (
    DISCOVERY_RECALL_CANDIDATE_LIMIT,
    DISCOVERY_REQUEST_CHARACTERS,
    prepare_discovery,
)


def _observation(
    observation_id, predicate, *, scene_index, chapter_index, start, end, quote
):
    source_ref = {
        "draft_id": f"draft-{chapter_index}",
        "content_hash": f"{chapter_index:064x}",
        "chapter_identity": f"chapter:{chapter_index}",
        "start_offset": start,
        "end_offset": end,
    }
    return {
        "observation_id": observation_id,
        "predicate": predicate,
        "quote": quote,
        "modality": "event_observed",
        "source_ref": source_ref,
        "evidence_quotes": [{"quote": quote, "source_ref": source_ref}],
        "mentions": [
            {
                "surface": "青竹" if scene_index == 72 else "竹叶",
                "resolution": {
                    "outcome": "reuse",
                    "resolved_entity_id": "world-character-1",
                },
            }
        ],
    }


@pytest.mark.asyncio
async def test_synthetic_long_book_keeps_distant_identity_batches_and_discloses_overflow(
    monkeypatch,
):
    prior_frozen = {}
    pairs = []
    for index in range(72):
        quote = f"第{index + 1}章的旧观察。"
        item = _observation(
            f"prior-{index:02d}",
            "旧细节长期保持一致。" * (5200 if index == 0 else 1),
            scene_index=index,
            chapter_index=index + 1,
            start=0,
            end=len(quote),
            quote=quote,
        )
        run_key, attempt_key = f"prior-run-{index}", f"prior-attempt-{index}"
        prior_frozen[(run_key, attempt_key)] = SimpleNamespace(
            run_id=run_key,
            attempt_id=attempt_key,
            source_manifest_hash="b" * 64,
            payload={
                "scene_id": str(UUID(int=index + 1)),
                "scene_index": index,
                "compiled_observations": [item],
            },
        )
        pairs.append(
            (
                SimpleNamespace(
                    committed_scene_index=index,
                    run_key=run_key,
                    attempt_key=attempt_key,
                ),
                None,
            )
        )

    quotes = [f"当前观察{index:03d}：青竹收起旧信。" for index in range(120)]
    scene_text_parts, observations, cursor = [], [], 0
    for index, quote in enumerate(quotes):
        scene_text_parts.append(quote)
        observations.append(
            _observation(
                f"current-{index:03d}",
                quote,
                scene_index=72,
                chapter_index=73,
                start=cursor,
                end=cursor + len(quote),
                quote=quote,
            )
        )
        cursor += len(quote)
        filler = "远处传来脚步声，灯火微微晃动。" * 4
        scene_text_parts.append(filler)
        cursor += len(filler)
    scene_text = "".join(scene_text_parts)
    frozen = SimpleNamespace(
        novel_id=str(UUID(int=999)),
        run_id="synthetic-run",
        attempt_id="current-attempt",
        source_manifest_hash="e" * 64,
        payload={
            "scene_id": str(UUID(int=73)),
            "scene_index": 72,
            "scene_text": scene_text,
            "compiled_observations": observations,
            "source_binding": {
                "draft_id": "draft-73",
                "chapter_index": 73,
                "content_hash": f"{73:064x}",
                "start_offset": 0,
                "end_offset": len(scene_text),
                "additional_sources": [],
            },
        },
    )

    class Store:
        async def load_committed_pairs(self, run_id):
            assert run_id == "synthetic-run"
            return pairs

        async def load_frozen(self, run_key, attempt_key):
            return prior_frozen[(run_key, attempt_key)]

    async def skip_prefix_validation(db, store, parent, *, run_key=None):
        assert parent is prior_frozen[("prior-run-71", "prior-attempt-71")]

    async def empty_ledger(db, novel_id, *, through_scene_index, offset, limit):
        assert through_scene_index == 71 and offset == 0 and limit == 100
        return {"items": [], "total": 0}

    monkeypatch.setattr(
        "modules.evolution.discovery.require_current_prefix", skip_prefix_validation
    )
    monkeypatch.setattr("modules.evolution.discovery.list_ledger", empty_ledger)
    result = await prepare_discovery(None, Store(), frozen)

    scope = result["coverage"]["recall_scope"]
    assert result["coverage"]["total_prior_observations"] == 72
    assert scope["selected_candidates"] == DISCOVERY_RECALL_CANDIDATE_LIMIT
    assert scope["omitted_candidates"] == 8
    assert scope["omission_reason"]
    assert (
        len({tuple(batch["current_observation_ids"]) for batch in result["batches"]}) > 1
    )
    assert all(
        len(json.dumps(batch, ensure_ascii=False)) <= DISCOVERY_REQUEST_CHARACTERS
        for index, batch in enumerate(result["batches"])
        if index not in result["unsupported_batches"]
    )

    history_ids = {
        item["observation"]["observation_id"]
        for index, batch in enumerate(result["batches"])
        if index not in result["unsupported_batches"]
        for item in batch["historical_context"]
        if "observation" in item
    }
    assert "prior-00" not in history_ids
    assert "prior-01" in history_ids
    assert len(history_ids) == DISCOVERY_RECALL_CANDIDATE_LIMIT - 1
    assert {
        item["observation_id"]
        for batch in result["batches"]
        for item in batch["current_observations"]
    } == {item["observation_id"] for item in observations}
    assert all(
        batch["scene_text_range"]["end_offset"]
        > batch["scene_text_range"]["start_offset"]
        for index, batch in enumerate(result["batches"])
        if index not in result["unsupported_batches"]
    )
    assert all(
        quote in batch["scene_text"]
        for i, batch in enumerate(result["batches"])
        if i not in result["unsupported_batches"]
        for item in batch["current_observations"]
        for quote in item["quotes"]
    )
    assert result["unsupported_batches"]
    assert any(
        any(
            unit.get("observation", {}).get("observation_id") == "prior-00"
            for unit in batch["historical_context"]
        )
        for i, batch in enumerate(result["batches"])
        if i in result["unsupported_batches"]
    )


def _ledger_theme(index, observation_id):
    return {
        "entry_id": f"theme-{index:03d}",
        "revision": 1,
        "source_status": "current",
        "method_status": "current",
        "proposal_target": None,
        "independent_review": {"verdict": "supported"},
        "author_decision": None,
        "claim": {
            "realm": "history",
            "category": "conditional_behavior",
            "label": f"主题{index:03d}" + "长" * 190,
            "targets": [],
            "unresolved_subjects": ["甲"],
            "statement": "某主题陈述。",
            "conditions": [],
            "confidence": 0.7,
            "modality": "event_observed",
            "evidence": [
                {
                    "observation_id": observation_id,
                    "role": "primary",
                    "purpose": "occurrence",
                    "occurrence_kind": "event",
                    "occurrence_id": f"occ-{index:03d}",
                }
            ],
            "dependencies": [],
        },
    }


@pytest.mark.asyncio
async def test_theme_index_growth_shards_instead_of_dropping_all_batches(monkeypatch):
    """300 个有效主题的全量索引超容量时：分批不消失、索引分片且完整携带。"""
    scene_text = "甲安静地等候。"
    observation = _observation(
        "current-0",
        scene_text,
        scene_index=1,
        chapter_index=2,
        start=0,
        end=len(scene_text),
        quote=scene_text,
    )
    themes = [_ledger_theme(index, "current-0") for index in range(300)]
    frozen = SimpleNamespace(
        novel_id=str(UUID(int=999)),
        run_id="synthetic-run",
        attempt_id="current-attempt",
        source_manifest_hash="e" * 64,
        payload={
            "scene_id": str(UUID(int=2)),
            "scene_index": 1,
            "scene_text": scene_text,
            "compiled_observations": [observation],
            "source_binding": {
                "draft_id": "draft-2",
                "chapter_index": 2,
                "content_hash": f"{2:064x}",
                "start_offset": 0,
                "end_offset": len(scene_text),
                "additional_sources": [],
            },
        },
    )

    class Store:
        async def load_committed_pairs(self, run_id):
            return []

    async def paged_ledger(db, novel_id, *, through_scene_index, offset, limit):
        return {"items": themes[offset : offset + limit], "total": len(themes)}

    monkeypatch.setattr("modules.evolution.discovery.list_ledger", paged_ledger)
    result = await prepare_discovery(None, Store(), frozen)

    # 旧行为：全量索引撑爆每批 → 0 批且 300 主题被伪装成单主题超限。
    assert result["batches"]
    assert result["unsupported_contexts"] == []
    assert result["unsupported_current_groups"] == []
    assert all(
        len(json.dumps(batch, ensure_ascii=False)) <= DISCOVERY_REQUEST_CHARACTERS
        for index, batch in enumerate(result["batches"])
        if index not in result["unsupported_batches"]
    )
    # 当前观察全部被批次覆盖。
    assert {
        observation_id
        for batch in result["batches"]
        for observation_id in batch["current_observation_ids"]
    } == {"current-0"}
    # 批负载只带 slim 索引；索引分片披露且全量条目完整到达。
    assert len(result["theme_index_shards"]) > 1
    assert all(
        {"entry_id", "category", "label"} <= set(item)
        for batch in result["batches"]
        for item in batch["theme_index"]
    )
    assert {
        item["entry_id"] for shard in result["theme_index_shards"] for item in shard
    } == {theme["entry_id"] for theme in themes}
    # allow_new_themes 恰好授予一个批次。
    assert sum(bool(batch["allow_new_themes"]) for batch in result["batches"]) == 1
    # 宿主侧完整索引（含 subject_labels/target_ids）保持完整，供 new 校验。
    assert all(
        {"subject_labels", "target_ids"} <= set(item) for item in result["theme_index"]
    )


@pytest.mark.asyncio
async def test_theme_keeps_all_bound_proof_without_copying_unrelated_scene_observations(
    monkeypatch,
):
    prior_text = "甲留下线索。"
    old_observations = [
        _observation(
            f"prior-{index:03d}",
            prior_text + "资料" * 500,
            scene_index=0,
            chapter_index=1,
            start=0,
            end=len(prior_text),
            quote=prior_text,
        )
        for index in range(80)
    ]
    parent = SimpleNamespace(
        run_id="old",
        attempt_id="old-attempt",
        source_manifest_hash="a" * 64,
        payload={
            "scene_id": str(UUID(int=1)),
            "scene_index": 0,
            "compiled_observations": old_observations,
        },
    )
    current_text = "甲返回。"
    current = _observation(
        "current",
        current_text,
        scene_index=1,
        chapter_index=2,
        start=0,
        end=len(current_text),
        quote=current_text,
    )
    frozen = SimpleNamespace(
        novel_id=str(UUID(int=999)),
        run_id="new",
        attempt_id="new-attempt",
        source_manifest_hash="b" * 64,
        payload={
            "scene_id": str(UUID(int=2)),
            "scene_index": 1,
            "scene_text": current_text,
            "compiled_observations": [current],
            "source_binding": {
                "draft_id": "draft-2",
                "chapter_index": 2,
                "content_hash": f"{2:064x}",
                "start_offset": 0,
                "end_offset": len(current_text),
                "additional_sources": [],
            },
        },
    )
    themes = [
        _ledger_theme(index, old_observations[index]["observation_id"])
        for index in range(80)
    ]
    for theme in themes:
        theme["claim"]["dependencies"] = [{"scene_id": str(UUID(int=1))}]

    class Store:
        async def load_committed_pairs(self, run_id):
            return [
                (
                    SimpleNamespace(
                        committed_scene_index=0, run_key="old", attempt_key="old-attempt"
                    ),
                    None,
                )
            ]

        async def load_frozen(self, run_key, attempt_key):
            return parent

    async def valid_prefix(*args, **kwargs):
        pass

    async def paged_ledger(db, novel_id, *, through_scene_index, offset, limit):
        return {"items": themes[offset : offset + limit], "total": len(themes)}

    monkeypatch.setattr(
        "modules.evolution.discovery.require_current_prefix", valid_prefix
    )
    monkeypatch.setattr("modules.evolution.discovery.list_ledger", paged_ledger)
    result = await prepare_discovery(None, Store(), frozen)
    descriptors = [
        unit["theme"]
        for batch in result["batches"]
        for unit in batch["historical_context"]
        if "theme" in unit
    ]
    assert len(descriptors) == 80
    assert not result["unsupported_batches"]
    assert {
        item["evidence_observations"][0]["observation_id"] for item in descriptors
    } == {observation["observation_id"] for observation in old_observations}
    assert all(len(item["evidence_observations"]) == 1 for item in descriptors)
    assert result["coverage"]["recall_scope"]["omitted_candidates"] == 16
