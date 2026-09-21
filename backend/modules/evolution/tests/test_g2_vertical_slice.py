"""G2 确定性夹具纵切（V4 计划 §9 最小纵切 / T03 / T07 / T17）。

定位（按 PR #158 评审收窄）：**确定性夹具下的存储/投影集成切片**——
provider、人物候选与场景事件来自固定夹具；完整 G2（持续认知闭环、
真实模型质量、独立 case 经 Evidence 消费）在后续里程碑验收。

虚构测试小说：林舟、青竹、白石城、铜钥匙。

    原文（Scene 0/1/2，各自绑定真实章节草稿） → 前序状态内容注入
    → 后序理解 → 新 case 消费 → 地图在场（未知路线不造真）
    → 修订失效（提交边界重验拒绝过期来源，T17 建议失效）

每一步都经过真实内核：管线组合器（屏障/预算/采样/观察/身份/一致性门/
窄提交）、E04 关系存储、E03c 回执纪律、E05 失效传播、在场投影与建议
有效性缝。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.collaboration import content_hash
from modules.evolution.commit import CommitConflictError
from modules.evolution.consumers import check_suggestion_validity
from modules.evolution.contracts import CommittedPrefix
from modules.evolution.invalidation import (
    apply_source_invalidation,
    compute_source_change,
)
from modules.evolution.pipeline import (
    BarrierBlockedError,
    SceneSourceBinding,
    run_scene_step,
)
from modules.evolution.store import PostgresAttemptStore
from modules.story.continuity.models import MemoryEvent
from modules.story.continuity.presence import project_scene_presence
from modules.story.continuity.services import MemoryService
from modules.story.outline_state.models import Scene
from modules.writing.facade import create_draft_only, get_latest_draft_for_chapter

RUN = "run-g2"
LINZHOU = "11111111-1111-4111-8111-111111111111"
QINGZHU = "22222222-2222-4222-8222-222222222222"

SCENE_0_TEXT = "林舟与青竹在白石城重逢。青竹从袖中取出铜钥匙，说此物需妥善保管。"
SCENE_1_TEXT = "青竹把铜钥匙收进包袱。林舟问她去哪儿，她说要先回白石城东市的当铺。"
SCENE_2_TEXT = "三日后，林舟独自出现在渡口。他望着江面，没有说明自己如何离开白石城。"


@dataclass
class _DeterministicSampler:
    """扮演 provider（async）：按 Scene 返回固定观察与场景事件（不调用真实模型）。

    观察提及只给表面名（与生产 sampler 契约一致）——提及身份由宿主派生。
    scene_events 里故意混入一个未获解析支持的 entity_id（LINZHOU 的旧
    UUID 已知但该 Scene 观察未提及相关实体）以驱动一致性门。
    """

    calls: int = 0
    texts: dict[int, str] = field(default_factory=dict)

    async def sample(self, *, scene_text: str, input_manifest: dict[str, Any]) -> dict:
        self.calls += 1
        self.texts[input_manifest["scene_index"]] = scene_text
        scene_index = input_manifest["scene_index"]
        if scene_index == 0:
            return {
                "scene_events": [
                    {
                        "dimension": "locations",
                        "event_type": "entity_moved",
                        "entity_id": LINZHOU,
                        "snapshot_after": {
                            "location_id": "baishi",
                            "text_state": "白石城",
                        },
                        "source": "evolution",
                    },
                    {
                        "dimension": "locations",
                        "event_type": "entity_moved",
                        "entity_id": QINGZHU,
                        "snapshot_after": {
                            "location_id": "baishi",
                            "text_state": "白石城",
                        },
                        "source": "evolution",
                    },
                    {
                        # 未获本 Scene 观察解析支持的提议（引用观察未提及的
                        # 实体）：一致性门应拦下，不取得状态效果。
                        "dimension": "entities",
                        "event_type": "manual_correction",
                        "entity_id": "99999999-9999-4999-8999-999999999999",
                        "snapshot_after": {"summary": "编造的旧事实修正"},
                    },
                ],
                "observations": [
                    {
                        "predicate": "青竹在白石城取出铜钥匙并声明保管责任",
                        "modality": "event_observed",
                        "quote": "青竹从袖中取出铜钥匙",
                        "mentions": [
                            {"surface": "青竹", "entity_type": "character"},
                            {"surface": "林舟", "entity_type": "character"},
                        ],
                    }
                ],
            }
        if scene_index == 1:
            return {
                "scene_events": [
                    {
                        "dimension": "knowledge",
                        "event_type": "knowledge_changed",
                        "entity_id": LINZHOU,
                        "snapshot_after": {
                            "id": "know-custody",
                            "character_id": LINZHOU,
                            "knowledge": "青竹保管铜钥匙（保管≠所有权）",
                        },
                        "source": "evolution",
                    }
                ],
                "observations": [
                    {
                        "predicate": "青竹收起铜钥匙并计划前往东市当铺",
                        "modality": "character_statement",
                        # 逐字引用：必须是本段正文的连续子串。
                        "quote": "她说要先回白石城东市的当铺",
                        "mentions": [
                            {"surface": "青竹", "entity_type": "character"},
                            {"surface": "林舟", "entity_type": "character"},
                        ],
                    }
                ],
            }
        return {
            "scene_events": [
                {
                    "dimension": "locations",
                    "event_type": "entity_moved",
                    "entity_id": LINZHOU,
                    "snapshot_after": {
                        "location_id": "dukou",
                        "text_state": "渡口",
                    },
                    "source": "evolution",
                }
            ],
            "observations": [
                {
                    "predicate": "林舟出现在渡口，离开白石城的路径未知",
                    "modality": "event_observed",
                    "quote": "没有说明自己如何离开白石城",
                    "mentions": [{"surface": "林舟", "entity_type": "character"}],
                }
            ],
        }


@dataclass
class _WorldCandidates:
    """扮演 world 候选召回：青竹/林舟已在 World 注册（精确名证据）。"""

    known: dict[str, str]

    async def lookup(self, novel_id: str, surface: str) -> list:
        entity_id = self.known.get(surface)
        if entity_id is None:
            return []

        @dataclass
        class _Suggestion:
            existing_entity_id: str
            existing_entity_name: str
            similarity_score: float
            match_method: str

        return [
            _Suggestion(entity_id, surface, 1.0, "exact_name"),
        ]


async def _scene(
    db: AsyncSession, novel_id: str, index: int, chapter: int, title: str
) -> Scene:
    item = Scene(
        novel_id=uuid.UUID(novel_id),
        scene_index=index,
        title=title,
        chapter_ids=[chapter],
        scene_chunks=[{"chapter_index": chapter}],
        status="draft",
    )
    db.add(item)
    await db.flush()
    return item


async def _binding(
    db: AsyncSession, novel_id: str, chapter: int
) -> SceneSourceBinding:
    draft = await get_latest_draft_for_chapter(db, novel_id, chapter)
    assert draft is not None, f"chapter {chapter} must have a working draft"
    return SceneSourceBinding(
        draft_id=str(draft.id),
        chapter_index=chapter,
        content_hash=str(draft.content_hash),
    )


def _applier(novel_id: str, scene_id: str, scene_index: int, chapter: int):
    async def applier(db, frozen) -> Any:
        from modules.evolution.commit import ApplierResult

        events = [
            {**event, "source": "evolution"}
            for event in (frozen.payload or {}).get("scene_events") or []
        ]
        await MemoryService().record_scene_events(
            db,
            novel_id,
            scene_id=scene_id,
            scene_index=scene_index,
            chapter_index=chapter,
            events=events,
            producer_family="evolution",
        )
        return ApplierResult(
            committed_prefix=CommittedPrefix(
                through_scene_index=scene_index, through_source_revision=chapter
            )
        )

    return applier


@pytest.mark.asyncio
async def test_g2_vertical_slice(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    db, nid = db_session, test_project_id
    await db.commit()  # 封存场景等已写入数据，后续失效回滚不波及

    scene0 = await _scene(db, nid, 0, 1, "重逢")
    scene1 = await _scene(db, nid, 1, 2, "钥匙")
    scene2 = await _scene(db, nid, 2, 3, "渡口")
    # 每个 Scene 绑定真实章节草稿：来源指纹来自 Writing 数据库。
    await create_draft_only(db, nid, 1, "重逢", SCENE_0_TEXT)
    await create_draft_only(db, nid, 2, "钥匙", SCENE_1_TEXT)
    await create_draft_only(db, nid, 3, "渡口", SCENE_2_TEXT)
    await db.commit()

    store = PostgresAttemptStore(db, nid)
    await store.register_run(RUN, mode="append", budget_total=10)

    sampler = _DeterministicSampler()
    candidates = _WorldCandidates({"青竹": QINGZHU, "林舟": LINZHOU})

    # ---- 1. 原文 → 前序状态（Scene 0） ----
    step0 = await run_scene_step(
        db,
        store,
        run_key=RUN,
        scene_index=0,
        scene_text=SCENE_0_TEXT,
        source=await _binding(db, nid, 1),
        sampler=sampler,
        applier=_applier(nid, str(scene0.id), 0, 1),
        identity_candidates=candidates.lookup,
    )
    assert step0.committed_prefix.through_scene_index == 0
    assert step0.identity_outcomes == {"reuse": 2}
    # 一致性门：观察未支持的 manual_correction 提议被拦下，不取得状态效果。
    assert len(step0.gated_scene_events) == 1
    assert step0.gated_scene_events[0]["event_type"] == "manual_correction"

    # ---- 2. 后序理解：Scene 1 输入包含 Scene 0 回执身份与实际状态内容（T07）----
    step1 = await run_scene_step(
        db,
        store,
        run_key=RUN,
        scene_index=1,
        scene_text=SCENE_1_TEXT,
        source=await _binding(db, nid, 2),
        sampler=sampler,
        applier=_applier(nid, str(scene1.id), 1, 2),
        identity_candidates=candidates.lookup,
    )
    assert step1.input_manifest["previous_scene_attempt_id"] == (step0.receipt_attempt_id)
    assert step0.receipt_attempt_id in str(step1.input_manifest)
    # 前序实际状态内容（观察摘要）进入输入清单——不靠回执 ID 冒充理解。
    assert any("铜钥匙" in line for line in step1.input_manifest["previous_observations"])

    # ---- 3. 新 case 消费同一合法状态：章节重放含 custody 知识 ----
    replay = await MemoryService().replay_state(db, nid, 2)
    knowledge = replay["character_knowledge"]
    assert any("保管" in item.get("knowledge", "") for item in knowledge)

    # ---- 4. 地图在场：Scene 2 后林舟在渡口，路线未知不造真（T03） ----
    step2 = await run_scene_step(
        db,
        store,
        run_key=RUN,
        scene_index=2,
        scene_text=SCENE_2_TEXT,
        source=await _binding(db, nid, 3),
        sampler=sampler,
        applier=_applier(nid, str(scene2.id), 2, 3),
        identity_candidates=candidates.lookup,
    )
    assert step2.committed_prefix.through_scene_index == 2

    presence = await project_scene_presence(db, nid, through_scene_index=2)
    linzhou_nodes = [node for node in presence.nodes if node.character_id == LINZHOU]
    assert [(node.location, node.presence_kind) for node in linzhou_nodes] == [
        ("白石城", "confirmed_in_scene"),
        ("渡口", "last_observed"),
    ]
    qingzhu_nodes = [node for node in presence.nodes if node.character_id == QINGZHU]
    assert [(node.location, node.presence_kind) for node in qingzhu_nodes] == [
        ("白石城", "last_observed")
    ]
    (segment,) = presence.segments
    assert segment.character_id == LINZHOU
    assert segment.status == "unknown"  # 无移动证据：不造路程/方式/时间
    assert segment.from_location == "白石城" and segment.to_location == "渡口"
    assert presence.unknown_route_characters == [LINZHOU]

    # ---- 5. 修订失效：改 Scene 0 正文 → 传播失效（E05）----
    await create_draft_only(db, nid, 1, "重逢（修订）", SCENE_0_TEXT + "夜雨初歇。")
    await db.commit()
    change = compute_source_change(SCENE_0_TEXT, SCENE_0_TEXT + "夜雨初歇。")
    receipt = await apply_source_invalidation(
        db, nid, chapter_index=1, change=change, content_mode="working"
    )
    assert receipt.earliest_affected_scene_index == 0
    assert receipt.invalidated_consumers["story_scene_projections"]

    # ---- 5b. 提交边界重验：来源变化后，旧绑定的新 Scene 步被拒绝（返修 R2）。
    # 不依赖手调失效 helper——prepare 之前的真实来源校验先失败关闭。
    stale_binding = SceneSourceBinding(
        draft_id="ffffffff-ffff-4fff-8fff-ffffffffffff",
        chapter_index=1,
        content_hash="f" * 64,
    )
    with pytest.raises(CommitConflictError, match="source_changed"):
        await run_scene_step(
            db,
            store,
            run_key=RUN,
            scene_index=3,
            scene_text=SCENE_0_TEXT,
            source=stale_binding,
            sampler=sampler,
            applier=_applier(nid, str(scene0.id), 3, 1),
        )

    # ---- 6. T17：旧建议失去有效资格，历史可查看 ----
    old_hash = content_hash({"text": SCENE_0_TEXT})
    validity = await check_suggestion_validity(
        db, nid, chapter_index=1, claimed_hash=old_hash, content_mode="working"
    )
    assert validity.verdict == "stale"
    assert validity.detail

    # 屏障顺序检查（返修 R3）：Scene 0 已提交后，跳场 Scene 7 与重复
    # Scene 0 都被拒；全新 run 的 Scene 1 在无链头时阻塞。
    with pytest.raises(BarrierBlockedError):
        await run_scene_step(
            db,
            store,
            run_key=RUN,
            scene_index=7,
            scene_text=SCENE_2_TEXT,
            source=await _binding(db, nid, 3),
            sampler=sampler,
            applier=_applier(nid, str(scene2.id), 7, 3),
        )
    # 重复 Scene 0：正文取当前修订稿（来源校验通过），顺序检查拒绝。
    revised = SCENE_0_TEXT + "夜雨初歇。"
    with pytest.raises(BarrierBlockedError):
        await run_scene_step(
            db,
            store,
            run_key=RUN,
            scene_index=0,
            scene_text=revised,
            source=await _binding(db, nid, 1),
            sampler=sampler,
            applier=_applier(nid, str(scene0.id), 0, 1),
        )

    fresh_store = PostgresAttemptStore(db, nid)
    # shadow 注册：不占用同项目的 live 单写者位（E07.c 门禁），屏障语义一致。
    await fresh_store.register_run(
        "run-g2-b", mode="bootstrap", budget_total=2, execution_mode="shadow"
    )
    with pytest.raises(BarrierBlockedError):
        await run_scene_step(
            db,
            fresh_store,
            run_key="run-g2-b",
            scene_index=1,
            scene_text=SCENE_1_TEXT,
            source=await _binding(db, nid, 2),
            sampler=_DeterministicSampler(),
            applier=_applier(nid, str(scene1.id), 1, 2),
        )

    # 事件与回执保留（失效不删历史）。
    kept_events = list(
        (
            await db.execute(
                select(MemoryEvent).where(
                    MemoryEvent.novel_id == uuid.UUID(nid),
                    MemoryEvent.source == "evolution",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(kept_events) >= 4
    receipts_kept = await store.load_head_receipt(RUN)
    assert receipts_kept is not None and receipts_kept.attempt_id == (
        step2.receipt_attempt_id
    )
