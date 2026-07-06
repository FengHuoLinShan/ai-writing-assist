from __future__ import annotations

import json
import sys
from pathlib import Path


TOOL_ROOT = Path(__file__).resolve().parents[1]
if str(TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOL_ROOT))

from phase1b import (  # noqa: E402
    Phase1aScene,
    Phase1bJob,
    Chapter,
    deterministic_scene_chunks,
    execute_phase1b_jobs,
    merge_scene,
    normalize_phase1a_scenes,
    parse_enrichment,
    select_scenes,
)


def scene(**overrides):
    base = {
        "scene_id": "S0001",
        "source_index": 1,
        "title": "锁定标题",
        "goal": "锁定目标",
        "core_conflict": "锁定冲突",
        "start_chapter": 5,
        "end_chapter": 5,
        "boundary_status": "complete",
        "source_payload": {},
    }
    base.update(overrides)
    return Phase1aScene(**base)


def test_parse_enrichment_ignores_locked_fields() -> None:
    source = scene()
    parsed = {
        "title": "篡改标题",
        "goal": "篡改目标",
        "scene_chunks": [{"chapter_index": 99}],
        "emotional_beat": "紧张到释然",
        "must_happen": "主角完成调查",
        "must_not_happen": "不能提前揭露真相",
        "narrative_tag": "investigation",
        "confidence": 91,
        "needs_review": False,
        "review_reason": "",
    }

    enrichment, error = parse_enrichment(parsed, source_scene=source)

    assert error is None
    assert "title" not in enrichment
    assert "goal" not in enrichment
    assert "scene_chunks" not in enrichment
    assert enrichment["confidence"] == 0.91


def test_merge_scene_keeps_locked_fields_and_generates_chunks() -> None:
    source = scene(start_chapter=18, end_chapter=20)
    enrichment = {
        "title": "ignored",
        "emotional_beat": "震惊",
        "must_happen": "发现线索",
        "must_not_happen": "不能跳过调查",
        "narrative_tag": "reveal",
        "confidence": 0.8,
        "needs_review": False,
        "review_reason": "",
    }

    final = merge_scene(source, enrichment)

    assert final["title"] == "锁定标题"
    assert final["goal"] == "锁定目标"
    assert final["core_conflict"] == "锁定冲突"
    assert final["scene_chunks"] == [
        {"chapter_index": 18},
        {"chapter_index": 19},
        {"chapter_index": 20},
    ]
    assert final["emotional_beat"] == "震惊"


def test_missing_fields_fallback_marks_review() -> None:
    source = scene(goal="必须发生", core_conflict="不能违背")

    enrichment, error = parse_enrichment(
        {"emotional_beat": "紧张"},
        source_scene=source,
    )

    assert error == "missing_fields"
    assert enrichment["needs_review"] is True
    assert enrichment["emotional_beat"] == "紧张"
    assert enrichment["must_happen"] == "必须发生"
    assert enrichment["must_not_happen"] == "不能违背"


def test_deterministic_scene_chunks() -> None:
    assert deterministic_scene_chunks(5, 5) == [{"chapter_index": 5}]
    assert deterministic_scene_chunks(18, 20) == [
        {"chapter_index": 18},
        {"chapter_index": 19},
        {"chapter_index": 20},
    ]


def test_normalize_scenes_derives_range_from_chunks() -> None:
    scenes = normalize_phase1a_scenes(
        [
            {
                "title": "跨章",
                "goal": "目标",
                "core_conflict": "冲突",
                "scene_chunks": [{"chapter_index": 2}, {"chapter_index": "3"}],
            },
        ],
    )

    assert len(scenes) == 1
    assert scenes[0].start_chapter == 2
    assert scenes[0].end_chapter == 3


def test_sample_selection_keeps_scene_order_and_variety() -> None:
    scenes = [
        scene(scene_id="S1", source_index=1, start_chapter=1, end_chapter=1),
        scene(scene_id="S2", source_index=2, start_chapter=2, end_chapter=3),
        scene(scene_id="S3", source_index=3, start_chapter=4, end_chapter=4),
        scene(scene_id="S4", source_index=4, start_chapter=4, end_chapter=4),
        scene(scene_id="S5", source_index=5, start_chapter=5, end_chapter=5),
    ]

    selected = select_scenes(scenes, scene_ids="", sample_size=4)

    assert len(selected) == 4
    assert [item.source_index for item in selected] == sorted(
        item.source_index for item in selected
    )
    assert any(item.start_chapter != item.end_chapter for item in selected)
    assert selected[-1].scene_id == "S5"


def test_concurrent_dry_run_keeps_all_scenes_and_writes_fallbacks(
    tmp_path: Path,
) -> None:
    scenes = [
        scene(scene_id="S1", source_index=1, start_chapter=1, end_chapter=1),
        scene(scene_id="S2", source_index=2, start_chapter=2, end_chapter=2),
        scene(scene_id="S3", source_index=3, start_chapter=3, end_chapter=3),
    ]
    jobs = [
        Phase1bJob(
            job_index=index,
            scene=item,
            prompt_template="{TEXT}\n{SCENE_JSON}",
        )
        for index, item in enumerate(scenes, start=1)
    ]
    chapters = [
        Chapter(index=1, title="一", body="正文一"),
        Chapter(index=2, title="二", body="正文二"),
        Chapter(index=3, title="三", body="正文三"),
    ]
    summary_path = tmp_path / "summary.jsonl"
    summary_path.write_text("", encoding="utf-8")

    metrics = execute_phase1b_jobs(
        jobs,
        config={"model": "test"},
        api_key="",
        chapters=chapters,
        output_dir=tmp_path,
        max_tokens_override=128,
        dry_run=True,
        print_stream=False,
        concurrency=2,
        summary_path=summary_path,
    )

    assert {item["scene_id"] for item in metrics} == {"S1", "S2", "S3"}
    assert all(item["fallback"] for item in metrics)
    assert all(item["scene_chunks_mismatch_count"] == 0 for item in metrics)
    assert len(list(tmp_path.glob("*.final.json"))) == 3


def test_phase1a_artifact_payload_shape(tmp_path: Path) -> None:
    artifact = tmp_path / "phase1a.artifact.json"
    artifact.write_text(
        json.dumps(
            {
                "phase1a_result": {
                    "candidates": [
                        {
                            "source_chapter_indices": [1, 2],
                            "payload": {
                                "scenes": [
                                    {
                                        "title": "候选",
                                        "goal": "目标",
                                        "core_conflict": "冲突",
                                    },
                                ],
                            },
                        },
                    ],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    from phase1b import load_phase1a_artifact_scenes

    loaded = load_phase1a_artifact_scenes(artifact)

    assert len(loaded) == 1
    assert loaded[0].start_chapter == 1
    assert loaded[0].end_chapter == 2
