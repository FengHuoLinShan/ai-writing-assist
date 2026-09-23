"""V4 审查（2026-09-22 修复包 2）回归。

覆盖 A02 Scene 来源区间、A04 结构化前序认知、A08 任意 Scene 幂等回放。

A02 反例（审查复现）：一章前半段与后半段属不同 Scene，后半段逐字来自
草稿却因哈希不等于整章哈希无法推进。修复后绑定携带码点区间，服务端按
权威草稿切片逐字比对——同章多 Scene 各自推进；区间漂移、越界、整稿换版
（含同长度替换）都拒绝。

A04 反例：前序认知被压成裸谓词放在"已确认的观察"标题下——belief 的
"城主或许已死"进入下一 Scene 时变成既定事实。修复后前序观察结构化保留
modality/主体/来源 Scene，窗口与截断显式披露。

A08 反例：任务层幂等回放只查链尾——head 到 Scene 2 后重复 Scene 0 的
任务触发屏障拒绝而非返回原回执。修复后按稳定请求身份（来源指纹）查任意
已提交 Scene 的原回执；修订请求指纹不同不套用旧回执。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from modules.evolution.commit import ApplierResult, CommitConflictError
from modules.evolution.contracts import CommittedPrefix
from modules.evolution.llm_sampler import build_scene_messages
from modules.evolution.pipeline import (
    BarrierBlockedError,
    SceneSourceBinding,
    compute_scene_manifest_hash,
    run_scene_step,
)
from modules.evolution.store import PostgresAttemptStore
from modules.story.outline_state.models import Scene
from modules.writing.facade import create_draft_only, get_latest_draft_for_chapter

# 一章四段：每段是独立的 Scene（A02 审查反例的"一章多 Scene"）。
SEGMENTS = [
    "林舟走进白石城。",
    "星盘在袖中发亮。",
    "青竹递出铜钥匙。",
    "三日后渡口起了大雾。",
]
CHAPTER_TEXT = "".join(SEGMENTS)


def _offsets(index: int) -> tuple[int, int]:
    start = sum(len(segment) for segment in SEGMENTS[:index])
    return start, start + len(SEGMENTS[index])


@dataclass
class _SegmentSampler:
    """按 Scene 返回固定观察；Scene 0 的观察是 belief（传闻）。"""

    calls: int = 0

    async def sample(self, *, scene_text: str, input_manifest: dict[str, Any]) -> dict:
        self.calls += 1
        scene_index = input_manifest["scene_index"]
        if scene_index == 0:
            predicate, modality = "林舟猜想城主或许已死", "belief"
        else:
            predicate, modality = f"第{scene_index}段场景推进", "event_observed"
        return {
            "observations": [
                {
                    "predicate": predicate,
                    "modality": modality,
                    "quote": scene_text[: min(6, len(scene_text))],
                    "mentions": [{"surface": "林舟", "entity_type": "character"}],
                }
            ],
            "scene_events": [],
        }


def _noop_applier(scene_index: int, chapter: int):
    async def applier(db, frozen) -> ApplierResult:
        return ApplierResult(
            committed_prefix=CommittedPrefix(
                through_scene_index=scene_index, through_source_revision=chapter
            )
        )

    return applier


async def _seed_scenes(
    db: AsyncSession, novel_id: str, count: int, chapter: int = 1
) -> None:
    for index in range(count):
        db.add(
            Scene(
                novel_id=uuid.UUID(novel_id),
                scene_index=index,
                title=f"Scene {index}",
                chapter_ids=[chapter],
                scene_chunks=[{"chapter_index": chapter}],
                status="draft",
            )
        )
    await db.flush()


async def _binding_for_segment(
    db: AsyncSession, novel_id: str, index: int, chapter: int = 1
) -> SceneSourceBinding:
    draft = await get_latest_draft_for_chapter(db, novel_id, chapter)
    assert draft is not None
    start, end = _offsets(index)
    return SceneSourceBinding(
        draft_id=str(draft.id),
        chapter_index=chapter,
        content_hash=str(draft.content_hash),
        start_offset=start,
        end_offset=end,
    )


# ---------------------------------------------------------------------------
# A02：同章多 Scene 的区间来源绑定
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_same_chapter_multiple_scenes_advance_via_sub_ranges(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    """审查反例：后半段逐字来自草稿却非整章哈希。修复后两段各成 Scene，
    各自推进；观察身份锚定草稿绝对区间（分段不同 → 身份不同）。"""
    db, nid = db_session, test_project_id
    await _seed_scenes(db, nid, 3)
    await create_draft_only(db, nid, 1, "一章两景", CHAPTER_TEXT)
    await db.commit()

    store = PostgresAttemptStore(db, nid)
    await store.register_run("run-a02", mode="append", budget_total=5)
    sampler = _SegmentSampler()

    step0 = await run_scene_step(
        db,
        store,
        run_key="run-a02",
        scene_index=0,
        scene_text=SEGMENTS[0],
        source=await _binding_for_segment(db, nid, 0),
        sampler=sampler,
        applier=_noop_applier(0, 1),
    )
    assert step0.committed_prefix.through_scene_index == 0

    # 后半段：逐字来自同一草稿的另一区间，正常推进（旧实现在此判 source_changed）。
    step1 = await run_scene_step(
        db,
        store,
        run_key="run-a02",
        scene_index=1,
        scene_text=SEGMENTS[1],
        source=await _binding_for_segment(db, nid, 1),
        sampler=sampler,
        applier=_noop_applier(1, 1),
    )
    assert step1.committed_prefix.through_scene_index == 1
    # 区间不同 → 观察身份不同（锚定草稿绝对空间，不因分段复用旧身份）。
    assert set(step0.observation_ids).isdisjoint(step1.observation_ids)

    # A04 顺带断言：Scene 1 的输入里，Scene 0 的传闻仍是 belief。
    prior = step1.input_manifest["previous_observations"]
    belief_entries = [item for item in prior if item.get("modality") == "belief"]
    assert belief_entries and "城主" in str(belief_entries[0].get("predicate"))
    assert "林舟" in (belief_entries[0].get("subjects") or [])
    coverage = step1.input_manifest["previous_observations_coverage"]
    assert coverage["scenes_included"] == [0]


@pytest.mark.asyncio
async def test_sub_range_mismatch_out_of_range_and_reversion_rejected(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    """区间与正文不一致、区间越界、整稿换版（含同长度替换）都拒绝。"""
    db, nid = db_session, test_project_id
    await _seed_scenes(db, nid, 2)
    await create_draft_only(db, nid, 1, "一章两景", CHAPTER_TEXT)
    await db.commit()
    store = PostgresAttemptStore(db, nid)
    await store.register_run("run-a02b", mode="append", budget_total=5)
    sampler = _SegmentSampler()

    # 正文与区间错位：SEGMENTS[1] 的文字配 [0,8) 区间。
    binding0 = await _binding_for_segment(db, nid, 0)
    with pytest.raises(CommitConflictError, match="source_changed"):
        await run_scene_step(
            db,
            store,
            run_key="run-a02b",
            scene_index=0,
            scene_text=SEGMENTS[1],
            source=binding0,
            sampler=sampler,
            applier=_noop_applier(0, 1),
        )

    # 区间越界：end 超出草稿长度。
    start, _ = _offsets(0)
    draft = await get_latest_draft_for_chapter(db, nid, 1)
    out_of_range = SceneSourceBinding(
        draft_id=str(draft.id),
        chapter_index=1,
        content_hash=str(draft.content_hash),
        start_offset=start,
        end_offset=len(CHAPTER_TEXT) + 5,
    )
    with pytest.raises(CommitConflictError, match="source_changed"):
        await run_scene_step(
            db,
            store,
            run_key="run-a02b",
            scene_index=0,
            scene_text=SEGMENTS[0],
            source=out_of_range,
            sampler=sampler,
            applier=_noop_applier(0, 1),
        )

    # 正常推进 Scene 0 后整稿换版（首段同长度替换）：修订前的旧绑定在
    # 新步被拒（旧稿已非本章最新）。注意：首段同长度替换不移动后段偏移，
    # 后段逐字未变、重绑新稿后仍可推进——被拒的是旧绑定，不是后段本身。
    step0 = await run_scene_step(
        db,
        store,
        run_key="run-a02b",
        scene_index=0,
        scene_text=SEGMENTS[0],
        source=await _binding_for_segment(db, nid, 0),
        sampler=sampler,
        applier=_noop_applier(0, 1),
    )
    assert step0.committed_prefix.through_scene_index == 0
    stale_binding = await _binding_for_segment(db, nid, 1)  # 修订前草稿的绑定
    revised = CHAPTER_TEXT.replace(SEGMENTS[0], "林舟走出白石城。", 1)
    await create_draft_only(db, nid, 1, "一章两景（修订）", revised)
    await db.commit()
    with pytest.raises(CommitConflictError, match="source_changed"):
        await run_scene_step(
            db,
            store,
            run_key="run-a02b",
            scene_index=1,
            scene_text=SEGMENTS[1],
            source=stale_binding,
            sampler=sampler,
            applier=_noop_applier(1, 1),
        )
    # 同长度替换不移动后段偏移：重绑修订稿后，逐字未变的后段照常推进。
    step1 = await run_scene_step(
        db,
        store,
        run_key="run-a02b",
        scene_index=1,
        scene_text=SEGMENTS[1],
        source=await _binding_for_segment(db, nid, 1),
        sampler=sampler,
        applier=_noop_applier(1, 1),
    )
    assert step1.committed_prefix.through_scene_index == 1


def test_binding_range_hash_consistency_enforced() -> None:
    """range_hash 与整稿指纹+区间不一致即构造失败（协议内自洽）。"""
    digest = "a" * 64
    start, end = _offsets(1)
    with pytest.raises(ValidationError, match="range_hash"):
        SceneSourceBinding(
            draft_id=uuid.uuid4().hex,
            chapter_index=1,
            content_hash=digest,
            start_offset=start,
            end_offset=end,
            range_hash="0" * 64,
        )
    from modules.evolution.contracts import SourceRevisionRef

    consistent = SceneSourceBinding(
        draft_id=uuid.uuid4().hex,
        chapter_index=1,
        content_hash=digest,
        start_offset=start,
        end_offset=end,
        range_hash=SourceRevisionRef.compute_range_hash(digest, start, end),
    )
    assert consistent.range_hash


# ---------------------------------------------------------------------------
# A04：前序认知结构化 + 窗口覆盖度
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prior_observation_window_discloses_coverage(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    """前序观察窗口覆盖最近 3 个已提交 Scene；更早的 Scene（含其传闻）
    不在注入面时由覆盖度显式披露——未注入不等于不存在。"""
    db, nid = db_session, test_project_id
    await _seed_scenes(db, nid, 4)
    await create_draft_only(db, nid, 1, "一章四景", CHAPTER_TEXT)
    await db.commit()

    store = PostgresAttemptStore(db, nid)
    await store.register_run("run-a04", mode="append", budget_total=6)
    sampler = _SegmentSampler()
    for index in range(4):
        await run_scene_step(
            db,
            store,
            run_key="run-a04",
            scene_index=index,
            scene_text=SEGMENTS[index],
            source=await _binding_for_segment(db, nid, index),
            sampler=sampler,
            applier=_noop_applier(index, 1),
        )

    entries, coverage = await store.load_prior_observations("run-a04")
    assert coverage["total_committed_scenes"] == 4
    assert coverage["scenes_included"] == [1, 2, 3]  # 窗口=3：Scene 0 在窗外
    assert all(entry["scene_index"] in {1, 2, 3} for entry in entries)
    # 窗口外不注入，但覆盖度没有谎称它不存在。
    assert all(entry["scene_index"] != 0 for entry in entries)


def test_prompt_renders_modality_labels_and_truncation() -> None:
    """Prompt 不再把传闻放进"已确认"标题：modality 原样标注、主体与来源
    Scene 携带，截断条数显式披露。"""
    messages = build_scene_messages(
        scene_text="正文。",
        input_manifest={
            "scene_index": 3,
            "previous_scene_attempt_id": "abc123",
            "previous_committed_prefix": {
                "through_scene_index": 2,
                "through_source_revision": 1,
            },
            "previous_observations": [
                {
                    "predicate": "城主或许已死",
                    "modality": "belief",
                    "subjects": ["林舟"],
                    "scene_index": 2,
                },
                {
                    "predicate": "青竹递出铜钥匙",
                    "modality": "event_observed",
                    "subjects": ["青竹"],
                    "scene_index": 1,
                },
            ],
            "previous_observations_coverage": {
                "omitted_observations": 3,
                "scenes_included": [1, 2],
            },
        },
    )
    rendered = "\n".join(message.content for message in messages)
    assert "已确认的观察" not in rendered
    assert "[belief] 城主或许已死（主体：林舟；来自 Scene 2）" in rendered
    assert "[event_observed] 青竹递出铜钥匙（主体：青竹；来自 Scene 1）" in rendered
    assert "另有 3 条前序观察因注入上限未列出" in rendered
    assert "不是客观事实" in rendered


# ---------------------------------------------------------------------------
# A08：任意已提交 Scene 的幂等回放（按稳定请求身份）
# ---------------------------------------------------------------------------


@dataclass
class _ChapterSampler:
    texts: dict[int, str]
    calls: int = 0

    async def sample(self, *, scene_text: str, input_manifest: dict[str, Any]) -> dict:
        self.calls += 1
        return {
            "observations": [
                {
                    "predicate": f"推进 Scene {input_manifest['scene_index']}",
                    "modality": "event_observed",
                    "quote": scene_text[:6],
                    "mentions": [],
                }
            ],
            "scene_events": [],
        }


@pytest.mark.asyncio
async def test_handler_replays_any_committed_scene_by_request_identity(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    """0→1→2 提交后重复 0/1/2 都拿回原回执（不重采样不扣费）；修订请求
    指纹不同不套用旧回执，走屏障语义拒绝。"""
    from modules.evolution.sampler import register_scene_sampler
    from modules.evolution.tasks import handle_evolution_scene_step

    db, nid = db_session, test_project_id
    texts = {
        1: "林舟走进白石城，灯市如昼。",
        2: "青竹递出铜钥匙，说是故人所托。",
        3: "三日后，渡口起了大雾。",
    }
    scene_ids: dict[int, str] = {}
    for index, text in texts.items():
        scene = Scene(
            novel_id=uuid.UUID(nid),
            scene_index=index - 1,
            title=f"Scene {index - 1}",
            chapter_ids=[index],
            scene_chunks=[{"chapter_index": index}],
            status="draft",
        )
        db.add(scene)
        await db.flush()
        scene_ids[index - 1] = str(scene.id)
        await create_draft_only(db, nid, index, f"第{index}章", text)
    await db.commit()
    # 链推进前的第 1 章原稿快照（修订后计算原请求指纹用）。
    original_draft = await get_latest_draft_for_chapter(db, nid, 1)
    assert original_draft is not None

    sampler = _ChapterSampler(texts=texts)
    register_scene_sampler("a08-echo", lambda db, novel_id: sampler)

    @dataclass
    class _Task:
        meta: dict

    def _request(chapter: int, scene_text: str):
        return _Task(
            meta={
                "novel_id": nid,
                "run_key": "run-a08",
                "scene_index": chapter - 1,
                "scene_text": scene_text,
                "scene_id": scene_ids[chapter - 1],
                "chapter_index": chapter,
                "budget_total": 5,
                "sampler_provider": "a08-echo",
            }
        )

    attempts = {}
    for chapter in (1, 2, 3):
        result = await handle_evolution_scene_step(db, _request(chapter, texts[chapter]))
        attempts[chapter - 1] = result["attempt_id"]
        assert result["committed_prefix"]["through_scene_index"] == chapter - 1
    assert sampler.calls == 3

    # head 已到 Scene 2：重复 Scene 0/1/2 都幂等返回原回执（A08 反例）。
    for chapter in (1, 2, 3):
        replay = await handle_evolution_scene_step(db, _request(chapter, texts[chapter]))
        assert replay["recovered"] is True
        assert replay["attempt_id"] == attempts[chapter - 1]
    assert sampler.calls == 3  # 无一重采样

    store = PostgresAttemptStore(db, nid)
    run = await store.load_run("run-a08")
    assert int(run.budget_remaining) == 2  # 幂等重放零扣减

    # 修订请求（同 Scene、正文变化）：指纹不同不套用旧回执；head 已推进，
    # 屏障拒绝——不是拿旧回执冒充成功。
    revised = "林舟走进白石城，灯市如昼，风起。"
    await create_draft_only(db, nid, 1, "第1章（修订）", revised)
    await db.commit()
    with pytest.raises(BarrierBlockedError):
        await handle_evolution_scene_step(db, _request(1, revised))
    assert sampler.calls == 3

    # 存储级：稳定请求身份判定——原指纹命中，修订指纹不命中。
    original_binding = SceneSourceBinding(
        draft_id=str(original_draft.id),
        chapter_index=1,
        content_hash=str(original_draft.content_hash),
    )
    matched = await store.load_committed_scene_receipt(
        "run-a08",
        0,
        source_manifest_hash=compute_scene_manifest_hash(
            "run-a08", 0, texts[1], original_binding
        ),
    )
    assert matched is not None and matched.attempt_id == attempts[0]
    revised_draft = await get_latest_draft_for_chapter(db, nid, 1)
    revised_binding = SceneSourceBinding(
        draft_id=str(revised_draft.id),
        chapter_index=1,
        content_hash=str(revised_draft.content_hash),
    )
    assert (
        await store.load_committed_scene_receipt(
            "run-a08",
            0,
            source_manifest_hash=compute_scene_manifest_hash(
                "run-a08", 0, revised, revised_binding
            ),
        )
        is None
    )


@pytest.mark.asyncio
async def test_handler_rejects_scene_chapter_mismatch(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    """A02：scene_id 与章号的组合经 outline_state 权威校验——场景不属于
    声称的章即拒绝，不信任请求独立声称的映射。"""
    from modules.evolution.tasks import handle_evolution_scene_step

    db, nid = db_session, test_project_id
    scene = Scene(
        novel_id=uuid.UUID(nid),
        scene_index=0,
        title="Scene 0",
        chapter_ids=[1],
        scene_chunks=[{"chapter_index": 1}],
        status="draft",
    )
    db.add(scene)
    await db.flush()
    await create_draft_only(db, nid, 1, "第一章", "正文。")
    await create_draft_only(db, nid, 2, "第二章", "另一章正文。")
    await db.commit()

    @dataclass
    class _Task:
        meta: dict

    with pytest.raises(ValueError, match="not part of scene"):
        await handle_evolution_scene_step(
            db,
            _Task(
                meta={
                    "novel_id": nid,
                    "run_key": "run-a02c",
                    "scene_index": 0,
                    "scene_text": "另一章正文。",
                    "scene_id": str(scene.id),
                    "chapter_index": 2,  # 场景属于第 1 章
                    "budget_total": 3,
                }
            ),
        )
