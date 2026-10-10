"""Deterministic, exhaustive input partitioning; no relevance-based false negatives."""

import json

from infrastructure.llm.collaboration import content_hash

REQUEST_CHARACTERS = 50000
PART_CHARACTERS = 8000
SCENE_CHARACTERS = 12000
SCENE_OVERLAP = 2000


def serialized_size(value):
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True))


def scene_windows(text, observations):
    """Keep short Scenes whole; long Scenes retain every character and observation.

    An observation is assigned once to a window containing all its verbatim
    quotes. If quotes span windows, retain their enclosing original text as an
    indivisible unit, with an explicit capacity deferral if it cannot fit.
    """
    if len(text) <= SCENE_CHARACTERS:
        return [(0, len(text), observations)]
    windows = []
    for start in range(0, len(text), SCENE_CHARACTERS - SCENE_OVERLAP):
        windows.append([start, min(len(text), start + SCENE_CHARACTERS), []])
        if windows[-1][1] == len(text):
            break
    for item in observations:
        quotes = item["quotes"]
        ranges = item.get("scene_text_ranges")
        matching = next(
            (
                window
                for window in windows
                if (
                    all(window[0] <= start < end <= window[1] for start, end in ranges)
                    if ranges
                    else all(quote in text[window[0] : window[1]] for quote in quotes)
                )
            ),
            None,
        )
        if matching is None:
            locations = (
                [(start, end - start) for start, end in ranges]
                if ranges
                else [(text.find(quote), len(quote)) for quote in quotes]
            )
            if not locations or any(start < 0 for start, _ in locations):
                start, end = 0, len(text)
            else:
                start = max(0, min(start for start, _ in locations) - SCENE_OVERLAP)
                end = min(
                    len(text),
                    max(start + length for start, length in locations) + SCENE_OVERLAP,
                )
            matching = [start, end, []]
            windows.append(matching)
        matching[2].append(item)
    return windows


def current_text_ranges(payload, records):
    """Map authoritative draft offsets to this Scene's concatenated source text."""
    binding = payload["source_binding"]
    parts = [binding, *binding.get("additional_sources", [])]
    result = {}
    for record in records:
        ranges, cursor = [], 0
        for part in parts:
            end = part.get("end_offset")
            length = (
                end - part.get("start_offset", 0)
                if end is not None
                else len(payload["scene_text"])
            )
            for evidence in record["evidence_quotes"]:
                ref = evidence["source_ref"]
                if (
                    ref["draft_id"] == part["draft_id"]
                    and part.get("start_offset", 0)
                    <= ref["start_offset"]
                    < ref["end_offset"]
                    <= part.get("start_offset", 0) + length
                ):
                    start = cursor + ref["start_offset"] - part.get("start_offset", 0)
                    stop = cursor + ref["end_offset"] - part.get("start_offset", 0)
                    if payload["scene_text"][start:stop] != evidence["quote"]:
                        raise ValueError("discovery_quote_scene_offset_mismatch")
                    ranges.append([start, stop])
            cursor += length
        if len(ranges) != len(record["evidence_quotes"]):
            raise ValueError("discovery_quote_scene_offset_missing")
        result[record["observation_id"]] = ranges
    return result


def build_batches(
    text,
    current,
    context_units,
    descriptors,
    *,
    scene_index,
    semantics,
    recall_scope,
    chunks,
):
    index_fields = (
        "entry_id",
        "revision",
        "category",
        "label",
        "subject_labels",
        "prior_review",
        "statement",
        "conditions",
        "conditions_semantics",
    )
    # Stable IDs, rather than query-order UUID ties, define the frozen partition.
    index = [
        {key: descriptor[key] for key in index_fields}
        for descriptor in sorted(descriptors, key=lambda item: item["entry_id"])
    ]
    index_shards = chunks(index, budget=PART_CHARACTERS) or [[]]
    primary = next(
        (
            i
            for i, shard in enumerate(index_shards)
            if serialized_size(shard) <= PART_CHARACTERS
        ),
        None,
    )
    # One indivisible giant descriptor must not poison every context batch.
    # Keep it as an explicit extra identity shard; a missing proof blocks new
    # adoption, while other existing themes remain discoverable.
    index_shards = (
        [index_shards[primary], *index_shards[:primary], *index_shards[primary + 1 :]]
        if primary is not None
        else [[], *index_shards]
    )
    contexts = chunks(context_units, budget=PART_CHARACTERS) or [[]]
    batches, unsupported, scopes = [], [], []
    for start, end, observations in scene_windows(text, current):
        for group in chunks(observations, budget=PART_CHARACTERS) or [[]]:
            new_assigned = False
            # Theme updates see each context once. Routing shards are checked
            # exhaustively in separate new-theme identity reviews, not multiplied
            # into competing updates of the same existing theme.
            for context in contexts:
                batch = {
                    "conditions_semantics": semantics,
                    "scene_text": text[start:end],
                    "scene_text_range": {"start_offset": start, "end_offset": end},
                    "allow_new_themes": False,
                    "theme_index": index_shards[0],
                    "scene_index": scene_index,
                    "current_observation_ids": [item["observation_id"] for item in group],
                    "current_observations": group,
                    "historical_context": context,
                    "recall_scope": recall_scope,
                }
                if (
                    not new_assigned
                    and serialized_size(
                        {**batch, "allow_new_themes": True, "partition_id": "0" * 64}
                    )
                    <= REQUEST_CHARACTERS
                ):
                    batch["allow_new_themes"] = True
                    new_assigned = True
                scope = {
                    "scene_text_range": batch["scene_text_range"],
                    "current_observation_ids": batch["current_observation_ids"],
                    "theme_ids": [
                        unit["theme"]["entry_id"] for unit in context if "theme" in unit
                    ],
                    "historical_observation_ids": [
                        unit["observation"]["observation_id"]
                        for unit in context
                        if "observation" in unit
                    ],
                    "theme_index_ids": [item["entry_id"] for item in index_shards[0]],
                }
                batch["partition_id"] = content_hash(["discovery.partition.v1", scope])
                scopes.append(
                    {
                        "batch": len(batches),
                        "partition_id": batch["partition_id"],
                        **scope,
                    }
                )
                if serialized_size(batch) > REQUEST_CHARACTERS:
                    unsupported.append(len(batches))
                batches.append(batch)
    return batches, unsupported, scopes, index_shards


def identity_review_inputs(batch, changes, shard, shard_index):
    return {
        **batch,
        "theme_index": shard,
        "theme_identity_check": {
            "shard_index": shard_index,
            "instruction": "新增主题身份分片审查：核对每项new是否与本片已有"
            "同主体同细节主题"
            "重复；重复则rejected，不能确定则uncertain。supported必须既有原文"
            "支持且与本片无重复。本片只认证本片范围，不声称检查完整主题索引。",
        },
        "changes": [
            {
                "change_index": ordinal,
                **change.model_dump(mode="json"),
                "target_theme": None,
            }
            for ordinal, change in enumerate(changes)
            if change.action == "new"
        ],
    }
