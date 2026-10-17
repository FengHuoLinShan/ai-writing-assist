"""Offline tests for Story-owned structural notice semantics."""

from types import SimpleNamespace

import pytest

from modules.story import notice_sources as source


def scene(**overrides):
    values = {
        "id": "scene-1",
        "source": "manual",
        "structure_meta": {},
        "goal": "带走账本",
        "core_conflict": "守卫封锁出口",
        "emotional_beat": "紧张升级",
        "pov_character_id": "character-1",
        "title": "旧港追逐",
        "updated_at": None,
        "chapter_ids": ["12"],
        "scene_chunks": [],
        # These are author instructions, not inputs to deterministic literal checks.
        "must_happen": "带走账本",
        "must_not_happen": "主角死亡",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def workbench_item(value, *, health=None):
    return SimpleNamespace(scene=value, health=health or [])


def issue_codes(issues):
    return {code for code, _severity, _summary in issues}


def test_trusted_semantic_statuses_preserve_not_applicable_and_uncertain():
    item = workbench_item(
        scene(
            source="deep_import",
            structure_meta={
                "semantic_field_statuses": {
                    "goal": "not_applicable",
                    "core_conflict": "uncertain",
                    "emotional_beat": "present",
                }
            },
            goal="",
            core_conflict="",
            emotional_beat="",
        )
    )

    issues = source._scene_issues(item, 12)

    assert "structure-goal" not in issue_codes(issues)
    assert "structure-core_conflict" in issue_codes(issues)
    assert any("核心冲突仍待确认" in summary for _code, _severity, summary in issues)
    assert "structure-emotional_beat" in issue_codes(issues)


def test_review_organize_health_and_chapter_mapping_remain_status_only():
    item = workbench_item(
        scene(
            structure_meta={"needs_organize": True},
            chapter_ids=[],
            scene_chunks=[{"chapter_index": "12", "start_pos": 0, "end_pos": 1}],
        ),
        health=["needs_review"],
    )

    issues = source._scene_issues(item, 12)

    assert issue_codes(issues) == {"structure-review", "structure-organize"}
    assert all(
        "张力" not in summary and "更好" not in summary for _, _, summary in issues
    )


def test_unmapped_chapter_is_reported_but_instruction_literals_are_not_checked():
    item = workbench_item(
        scene(
            chapter_ids=[],
            scene_chunks=[
                {"chapter_index": "not-a-chapter", "start_pos": 0, "end_pos": 1}
            ],
        )
    )

    issues = source._scene_issues(item, 12)

    assert "structure-chapter-map" in issue_codes(issues)
    assert all(
        "账本" not in summary and "主角死亡" not in summary for _, _, summary in issues
    )


@pytest.mark.asyncio
async def test_chapter_scope_is_unbounded_and_notice_links_to_story_workbench(
    monkeypatch,
):
    value = scene(
        source="deep_import",
        structure_meta={"semantic_field_statuses": {"goal": "uncertain"}},
        goal="",
    )

    class FakeWorkbench:
        async def get_workbench(
            self,
            db,
            novel_id,
            *,
            selected_scene_id,
            chapter_from,
            chapter_to,
            limit,
        ):
            assert db == "session"
            assert novel_id == "novel-1"
            assert selected_scene_id is None
            assert chapter_from == chapter_to == 12
            assert limit is None
            return SimpleNamespace(
                items=[SimpleNamespace(kind="scene", **vars(workbench_item(value)))]
            )

    monkeypatch.setattr(source, "SceneWorkbenchService", FakeWorkbench)

    notices = await source.list_scene_structure_notices(
        "session", "novel-1", {"chapter_index": 12}
    )

    goal_notice = next(
        item for item in notices if item["notice_key"].endswith("structure-goal")
    )
    assert goal_notice["source_id"] == "story.structure"
    assert goal_notice["actions"][0] == {
        "kind": "navigate",
        "page": "outline",
        "scene_id": "scene-1",
        "scene_field": "goal",
        "label": "打开场景",
    }
