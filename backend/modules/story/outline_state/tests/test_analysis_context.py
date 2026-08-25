"""Manual outline-analysis context projection tests."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.story.outline_state.analysis_context import OutlineAnalysisContextService
from modules.story.outline_state.models import (
    ForeshadowingPlan,
    OutlineArc,
    PlotThread,
    RevealPlan,
    Scene,
    SceneChapterLink,
)

pytestmark = [pytest.mark.asyncio]


async def test_analysis_context_is_range_ordered_and_novel_isolated(
    db_session: AsyncSession,
    sample_novel_id: str,
    other_novel_id: str,
) -> None:
    novel_id = uuid.UUID(sample_novel_id)
    other_id = uuid.UUID(other_novel_id)
    character_id = str(uuid.uuid4())
    entity_id = str(uuid.uuid4())
    reveal_entity_id = uuid.uuid4()
    directly_related_thread_id = uuid.uuid4()
    scene_late = Scene(
        novel_id=novel_id,
        scene_index=8,
        title="迟到的选择",
        pov_character_id=character_id,
        structure_meta={"related_entity_ids": [entity_id]},
        status="draft",
    )
    scene_early = Scene(
        novel_id=novel_id,
        scene_index=3,
        title="先发生的冲突",
        structure_meta={
            "related_thread_ids": [str(directly_related_thread_id)],
        },
        status="canonical",
    )
    outside_scene = Scene(
        novel_id=novel_id,
        scene_index=1,
        title="范围外",
        status="draft",
    )
    other_scene = Scene(
        novel_id=other_id,
        scene_index=0,
        title="另一本书",
        status="draft",
    )
    db_session.add_all([scene_late, scene_early, outside_scene, other_scene])
    await db_session.flush()
    db_session.add_all(
        [
            SceneChapterLink(
                novel_id=novel_id,
                scene_id=scene_late.id,
                chapter_index=6,
            ),
            SceneChapterLink(
                novel_id=novel_id,
                scene_id=scene_early.id,
                chapter_index=3,
            ),
            SceneChapterLink(
                novel_id=novel_id,
                scene_id=outside_scene.id,
                chapter_index=12,
            ),
            SceneChapterLink(
                novel_id=other_id,
                scene_id=other_scene.id,
                chapter_index=4,
            ),
        ]
    )
    db_session.add_all(
        [
            PlotThread(
                novel_id=novel_id,
                name="主线",
                thread_type="main",
                start_chapter=1,
                planned_payoff_chapter=9,
                related_character_ids=[character_id],
                related_entity_ids=[entity_id],
                status="draft",
            ),
            PlotThread(
                novel_id=novel_id,
                name="后期开启",
                thread_type="subplot",
                start_chapter=20,
                status="draft",
            ),
            PlotThread(
                novel_id=novel_id,
                name="无章节锚点的无关剧情线",
                thread_type="subplot",
                status="draft",
            ),
            PlotThread(
                id=directly_related_thread_id,
                novel_id=novel_id,
                name="区间字段不一致但 Scene 明确关联",
                thread_type="subplot",
                start_chapter=18,
                planned_payoff_chapter=22,
                status="draft",
            ),
            OutlineArc(
                novel_id=novel_id,
                title="第一卷",
                arc_index=1,
                start_chapter=1,
                end_chapter=8,
                status="canonical",
            ),
            OutlineArc(
                novel_id=novel_id,
                title="无章节锚点的无关篇章",
                arc_index=99,
                status="draft",
            ),
            ForeshadowingPlan(
                novel_id=novel_id,
                name="钥匙",
                planned_seed_chapter=2,
                planned_reinforce_chapters=[4],
                planned_payoff_chapter=10,
                related_entity_ids=[entity_id],
                status="planted",
            ),
            RevealPlan(
                novel_id=novel_id,
                target_type="entity",
                target_id=reveal_entity_id,
                secret_summary="钥匙属于王室",
                reveal_stages=[{"chapter_index": 5, "reveal_content": "徽记"}],
                status="planned",
            ),
            RevealPlan(
                novel_id=novel_id,
                target_type="entity",
                target_id=uuid.UUID(entity_id),
                secret_summary="当前物品的后续揭示",
                reveal_stages=[{"chapter_index": 12, "reveal_content": "真正来历"}],
                status="planned",
            ),
            RevealPlan(
                novel_id=other_id,
                target_type="entity",
                target_id=uuid.uuid4(),
                secret_summary="他书秘密",
                reveal_stages=[{"chapter_index": 5}],
                status="planned",
            ),
        ]
    )
    await db_session.flush()

    result = await OutlineAnalysisContextService().get_range(
        db_session,
        sample_novel_id,
        start_chapter=3,
        end_chapter=6,
    )

    assert [item["title"] for item in result.scenes] == [
        "先发生的冲突",
        "迟到的选择",
    ]
    assert [item["chapter_indices"] for item in result.scenes] == [[3], [6]]
    assert [item["name"] for item in result.plot_threads] == [
        "主线",
        "区间字段不一致但 Scene 明确关联",
    ]
    assert [item["title"] for item in result.arcs] == ["第一卷"]
    assert [item["name"] for item in result.foreshadowing_plans] == ["钥匙"]
    assert {item["secret_summary"] for item in result.reveal_plans} == {
        "钥匙属于王室",
        "当前物品的后续揭示",
    }
    assert result.related_character_ids == [character_id]
    assert result.related_entity_ids == [entity_id, str(reveal_entity_id)]
    assert "另一本书" not in str(result)
