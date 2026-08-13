from __future__ import annotations

import uuid
from dataclasses import asdict

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.facade import get_scene_execution_bundle
from modules.outline.repositories import SceneRepository
from modules.outline.schemas import SceneCreate
from modules.outline.story_outline_schemas import StoryOutlineRevisionCreate
from modules.outline.story_outline_service import StoryOutlineService


def _outline() -> StoryOutlineRevisionCreate:
    return StoryOutlineRevisionCreate(
        base_revision_id=None,
        idempotency_key="execution-bundle-outline-0001",
        title="潮汐尽头的王座",
        creative_core={
            "premise": "群岛必须在旧王权复苏前重建联盟。",
            "tone_and_reader_promise": "克制的海洋奇幻与政治抉择。",
            "story_engine": "每次退潮都暴露遗迹与代价。",
        },
        outline_markdown="# 总纲\n联盟必须重建。",
        major_storylines=[
            {
                "name": "群岛联盟",
                "narrative_function": "主冲突。",
                "trajectory": "从互助到分裂。",
                "intersections": [],
                "resolution_direction": "联盟接受分权与共同代价。",
            }
        ],
        macro_movements=[
            {
                "name": "第一次退潮",
                "story_state_change": "孤立岛屿形成脆弱共同体。",
                "advanced_storylines": ["群岛联盟"],
            }
        ],
        open_decisions=[],
    )


@pytest.mark.asyncio
async def test_scene_execution_bundle_is_version_bound_and_reports_missing_fields(
    db_session: AsyncSession,
    sample_novel_id: str,
) -> None:
    scene = await SceneRepository().create(
        db_session,
        uuid.UUID(sample_novel_id),
        SceneCreate(
            scene_index=2,
            title="进入遗迹",
            goal="取得潮汐钥匙。",
            pov_character_id="pov-1",
            must_happen="钥匙必须被发现。",
            must_not_happen="不能提前揭示旧王身份。",
            structure_meta={
                "knowledge_boundary": "POV 只知道遗迹传闻。",
                "entry_state": "队伍分散在入口。",
                "exit_state": "主角带着钥匙离开。",
                "outcome": "得到钥匙。",
                "cost": "失去与盟友的信任。",
                "continuity": "上一 Scene 的船损仍未修复。",
                "new_fact_candidates": ["钥匙会响应退潮"],
            },
        ),
    )
    await StoryOutlineService().create_revision(db_session, sample_novel_id, _outline())

    bundle = await get_scene_execution_bundle(
        db_session,
        sample_novel_id,
        str(scene.id),
    )

    assert bundle is not None
    assert bundle.missing_fields == []
    assert bundle.story_outline_version == 1
    assert bundle.story_execution_profile is not None
    assert bundle.story_execution_profile["version"] == "story_execution_profile.v1"
    assert len(bundle.story_execution_profile_hash or "") == 64
    assert {item["type"] for item in bundle.upstream_manifest} == {
        "story_outline_revision",
        "story_execution_profile.v1",
    }
    assert len(bundle.contract_hash) == 64
    assert asdict(bundle)["scene"]["outcome"] == "得到钥匙。"


@pytest.mark.asyncio
async def test_scene_execution_bundle_never_invents_a_missing_story_outline(
    db_session: AsyncSession,
    sample_novel_id: str,
) -> None:
    scene = await SceneRepository().create(
        db_session,
        uuid.UUID(sample_novel_id),
        SceneCreate(scene_index=0),
    )

    bundle = await get_scene_execution_bundle(
        db_session,
        sample_novel_id,
        str(scene.id),
    )

    assert bundle is not None
    assert bundle.story_outline_revision_id is None
    assert bundle.story_execution_profile is None
    assert bundle.omissions == ["current_story_outline"]
    assert bundle.upstream_manifest == []
