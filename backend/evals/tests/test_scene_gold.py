from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from evals.cache import EvalCache
from evals.corpus import build_corpus_snapshot
from evals.scene_gold import repair_scene_gold_cases
from evals.schemas import (
    DatasetCase,
    DatasetSplit,
    EvalSuite,
    LogicalSourceRef,
)


class _FakeExecutor:
    model = "gpt-5.3-codex-spark"
    reasoning_effort = None

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls = 0

    async def generate_structured(self, _prompt, response_model, *, step_name):
        assert step_name == "scene_gold_canonical_range"
        self.calls += 1
        return response_model.model_validate(self.payload)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@pytest.mark.asyncio
async def test_scene_gold_repair_materializes_canonical_ranges_and_cache(
    tmp_path: Path,
) -> None:
    source = tmp_path / "novel.txt"
    source.write_text(
        "第一章 起点\n章首铺垫。唯一场景开始锚点发生在这里。"
        "中间冲突持续推进。最后以唯一场景结束锚点收束。\n"
        "第二章 后续\n另一个章节。\n",
        encoding="utf-8",
    )
    snapshot = build_corpus_snapshot(source, source_alias="fixture")
    chapter = snapshot.chapters[0]
    scene = DatasetCase(
        case_id="scene-000001",
        suite=EvalSuite.scene,
        scenario="location_shift",
        source_group_id=chapter.source_group_id,
        source_refs=[
            LogicalSourceRef(
                corpus_id=snapshot.corpus_id,
                source_alias="fixture",
                source_group_id=chapter.source_group_id,
                chapter_index=1,
                content_hash=chapter.content_hash,
            )
        ],
        input={"text": "概括后的场景文本"},
        reference={"chapter_indices": [1], "boundary_offsets": [0, 8]},
        split=DatasetSplit.test,
    )
    rag = scene.model_copy(update={"case_id": "rag-000001", "suite": EvalSuite.rag})
    executor = _FakeExecutor(
        {
            "locations": [
                {
                    "case_id": scene.case_id,
                    "segments": [
                        {
                            "chapter_index": 1,
                            "start_anchor": "唯一场景开始锚点发生在这里",
                            "end_anchor": "“最后唯一场景结束锚点收束”",
                        }
                    ],
                    "reason": "完整叙事冲突从开始锚点延续到结束锚点。",
                }
            ]
        }
    )
    cache = EvalCache(tmp_path / "cache")

    repaired, meta = await repair_scene_gold_cases(
        [scene, rag],
        source_path=source,
        source_alias="fixture",
        cache=cache,
        primary_executor=executor,  # type: ignore[arg-type]
    )

    repaired_scene = repaired[0]
    ref = repaired_scene.source_refs[0]
    chapter_text = source.read_text(encoding="utf-8").split("第二章", 1)[0]
    assert ref.start_offset == chapter_text.index("唯一场景开始锚点发生在这里")
    assert ref.end_offset == chapter_text.index("最后以唯一场景结束锚点收束") + len(
        "最后以唯一场景结束锚点收束"
    )
    assert ref.range_hash == _hash(chapter_text[ref.start_offset : ref.end_offset])
    assert repaired_scene.reference["boundary_coordinate_system"] == (
        "canonical_chapter_offset_v1"
    )
    assert repaired[1] == rag
    assert meta["scene_case_count"] == 1
    assert executor.calls == 1

    cached_executor = _FakeExecutor({"locations": []})
    cached_repaired, cached_meta = await repair_scene_gold_cases(
        [scene, rag],
        source_path=source,
        source_alias="fixture",
        cache=cache,
        primary_executor=cached_executor,  # type: ignore[arg-type]
        cache_only=True,
    )
    assert cached_executor.calls == 0
    assert cached_repaired[0].source_refs == repaired_scene.source_refs
    assert cached_meta["runs"][0]["cached"] is True


@pytest.mark.asyncio
async def test_scene_gold_repair_rejects_non_unique_anchor(tmp_path: Path) -> None:
    source = tmp_path / "novel.txt"
    source.write_text(
        "第一章 重复\n重复锚点文本一二三四。重复锚点文本一二三四。结束锚点文本五六七八。",
        encoding="utf-8",
    )
    snapshot = build_corpus_snapshot(source, source_alias="fixture")
    chapter = snapshot.chapters[0]
    case = DatasetCase(
        case_id="scene-000002",
        suite=EvalSuite.scene,
        scenario="weak_boundary",
        source_group_id=chapter.source_group_id,
        source_refs=[
            LogicalSourceRef(
                corpus_id=snapshot.corpus_id,
                source_alias="fixture",
                source_group_id=chapter.source_group_id,
                chapter_index=1,
                content_hash=chapter.content_hash,
            )
        ],
        input={"text": "重复"},
        reference={"chapter_indices": [1]},
        split=DatasetSplit.test,
    )
    executor = _FakeExecutor(
        {
            "locations": [
                {
                    "case_id": case.case_id,
                    "segments": [
                        {
                            "chapter_index": 1,
                            "start_anchor": "重复锚点文本一二三四",
                            "end_anchor": "结束锚点文本五六七八",
                        }
                    ],
                    "reason": "测试重复锚点。",
                }
            ]
        }
    )

    with pytest.raises(ValueError, match="anchors must be unique"):
        await repair_scene_gold_cases(
            [case],
            source_path=source,
            source_alias="fixture",
            cache=EvalCache(tmp_path / "cache"),
            primary_executor=executor,  # type: ignore[arg-type]
        )
