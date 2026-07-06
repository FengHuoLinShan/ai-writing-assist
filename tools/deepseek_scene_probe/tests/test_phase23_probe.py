from __future__ import annotations

import json
import sys
from pathlib import Path


TOOL_ROOT = Path(__file__).resolve().parents[1]
if str(TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOL_ROOT))

from phase23_common import (  # noqa: E402
    ProbeScene,
    build_phase0_charbudget_windows,
    load_phase1b_final_scenes,
)
from phase2_world_probe import (  # noqa: E402
    Phase2Job,
    build_phase2_payload,
    parse_phase2_output,
)
from phase3_structure_probe import (  # noqa: E402
    auto_select_phase2_rows,
    parse_phase3_output,
)
from probe import Batch, Chapter  # noqa: E402


def scene(**overrides):
    base = {
        "scene_id": "S0001",
        "source_index": 1,
        "title": "标题",
        "goal": "目标",
        "core_conflict": "冲突",
        "start_chapter": 1,
        "end_chapter": 1,
        "boundary_status": "complete",
        "emotional_beat": "情绪",
        "must_happen": "必须发生",
        "must_not_happen": "不能发生",
        "narrative_tag": "intro",
        "confidence": 0.9,
        "needs_review": False,
        "review_reason": "",
        "source_payload": {},
    }
    base.update(overrides)
    return ProbeScene(**base)


def test_charbudget_windows_keep_right_overlap() -> None:
    chapters = [
        Chapter(index=1, title="一", body="a" * 10),
        Chapter(index=2, title="二", body="b" * 10),
        Chapter(index=3, title="三", body="c" * 10),
        Chapter(index=4, title="四", body="d" * 10),
        Chapter(index=5, title="五", body="e" * 10),
    ]

    windows = build_phase0_charbudget_windows(
        chapters,
        chapter_start=1,
        chapter_end=5,
        target_input_chars=40,
        max_window_chapters=3,
        overlap_chapters=1,
    )

    assert [(item.input_start, item.input_end, item.owned_start, item.owned_end) for item in windows] == [
        (1, 2, 1, 1),
        (2, 3, 2, 2),
        (3, 4, 3, 3),
        (4, 5, 4, 5),
    ]


def test_load_phase1b_scenes_applies_repair_overlay(tmp_path: Path) -> None:
    base_run = write_phase1b_run(
        tmp_path / "base",
        [
            {
                "scene_id": "S0001",
                "title": "旧",
                "start_chapter": 1,
                "end_chapter": 1,
                "needs_review": True,
            },
        ],
    )
    repair_run = write_phase1b_run(
        tmp_path / "repair",
        [
            {
                "scene_id": "S0001",
                "title": "新",
                "start_chapter": 1,
                "end_chapter": 1,
                "needs_review": False,
            },
        ],
    )

    scenes = load_phase1b_final_scenes(base_run, repair_run_dirs=[repair_run])

    assert len(scenes) == 1
    assert scenes[0].title == "新"
    assert scenes[0].needs_review is False


def test_phase2_prompt_is_input_first() -> None:
    job = Phase2Job(
        job_index=1,
        window_mode="single_range",
        input_mode="scenes_plus_text",
        prompt_level="minimal",
        max_tokens=128,
        combo_label="test",
        batch=Batch(
            batch_id="B0001-1-1",
            input_start=1,
            input_end=1,
            owned_start=1,
            owned_end=1,
            overlap_start=None,
            overlap_end=None,
        ),
        prompt_template="{INPUT_BLOCK}\n\n任务说明 {OWNED_SCENE_IDS}",
    )
    payload = build_phase2_payload(
        config={"model": "test"},
        job=job,
        chapters=[Chapter(index=1, title="一", body="正文内容")],
        selected_scenes=[scene()],
        owned_scenes=[scene()],
    )

    prompt = payload["messages"][1]["content"]

    assert prompt.startswith("【章节正文】")
    assert "正文内容" in prompt
    assert "任务说明 S0001" in prompt


def test_phase2_parser_marks_invalid_scene_refs() -> None:
    source_scene = scene(scene_id="S0001")
    parsed = {
        "objects": [
            {
                "name": "克莱恩",
                "entity_type": "character",
                "summary": "主角",
                "supporting_scene_ids": ["S0001", "S9999"],
            },
        ],
    }

    final, error, invalid_refs = parse_phase2_output(
        parsed,
        scenes_by_id={"S0001": source_scene},
        allowed_scene_ids={"S0001"},
        owned_scene_ids={"S0001"},
    )

    assert error is None
    assert invalid_refs == 1
    assert final["objects"][0]["supporting_scene_ids"] == ["S0001"]
    assert final["objects"][0]["chapter_range"] == [1, 1]


def test_phase3_parser_normalizes_supported_refs() -> None:
    source_scene = scene(scene_id="S0001")
    parsed = {
        "plot_threads": [
            {
                "title": "主线",
                "summary": "主角进入超凡世界",
                "supporting_scene_ids": ["S0001", "BAD"],
            },
        ],
    }

    final, error, invalid_refs = parse_phase3_output(
        parsed,
        scenes_by_id={"S0001": source_scene},
        allowed_scene_ids={"S0001"},
    )

    assert error is None
    assert invalid_refs == 1
    assert final["plot_threads"][0]["supporting_scene_ids"] == ["S0001"]


def test_phase3_auto_selects_preferred_phase2_combo() -> None:
    rows = [
        {
            "job_index": 1,
            "combo_label": "single_range_scenes_only_strict_mt8192",
            "window_mode": "single_range",
            "input_mode": "scenes_only",
            "prompt_level": "strict",
            "max_tokens": 8192,
            "parse_ok": True,
        },
        {
            "job_index": 2,
            "combo_label": "phase0_charbudget_scenes_plus_text_minimal_mt12288",
            "window_mode": "phase0_charbudget",
            "input_mode": "scenes_plus_text",
            "prompt_level": "minimal",
            "max_tokens": 12288,
            "parse_ok": True,
        },
    ]

    selected = auto_select_phase2_rows(rows)

    assert selected[0]["combo_label"] == "phase0_charbudget_scenes_plus_text_minimal_mt12288"


def write_phase1b_run(run_dir: Path, payloads: list[dict]) -> Path:
    run_dir.mkdir()
    rows = []
    for index, payload in enumerate(payloads, start=1):
        final_path = run_dir / f"scene_{index}.final.json"
        final_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        rows.append(
            {
                "scene_id": payload["scene_id"],
                "source_index": index,
                "final_path": str(final_path),
                "chapter_range": [
                    payload.get("start_chapter"),
                    payload.get("end_chapter"),
                ],
            },
        )
    with (run_dir / "summary.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return run_dir
