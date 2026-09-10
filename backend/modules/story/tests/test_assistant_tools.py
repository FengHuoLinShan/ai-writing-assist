import uuid

import pytest

from core.errors import ConflictError
from modules.account.facade import current_account_id
from modules.assistant.contracts import AssistantOperationContext, WorkContext
from modules.story.assistant_tools import (
    SaveCard,
    SaveScript,
    _card_apply,
    _card_preview,
    _script_apply,
    _script_preview,
)
from modules.story.schemas import CharacterCardContent
from modules.story.service import StoryService
from modules.story.tests.test_story_service import _character, _scene


@pytest.mark.asyncio
async def test_assistant_card_and_script_keep_versions_adoption_and_provenance(
    db_session, test_project_id
):
    scene = await _scene(db_session, test_project_id)
    character_id = await _character(db_session, test_project_id)
    context = AssistantOperationContext(
        str(uuid.uuid4()), str(current_account_id()), WorkContext(scene_id=scene.id)
    )
    card = SaveCard(
        scene_id=scene.id,
        character_id=character_id,
        content=CharacterCardContent(personality="遇到冲突先核对证据"),
    )
    preview = await _card_preview(db_session, test_project_id, card, context=context)
    assert "测试人物" in preview["title"]
    result = await _card_apply(
        db_session, test_project_id, card, preview, context=context
    )
    stored = await StoryService().get_card(db_session, test_project_id, result["id"])
    assert stored.revision.source == "assistant_confirmed"
    assert stored.revision.authorization_ref == f"assistant:{context.run_id}"
    with pytest.raises(ConflictError):
        await _card_apply(db_session, test_project_id, card, preview, context=context)

    await StoryService().create_script_file(
        db_session,
        novel_id=test_project_id,
        scene_id=str(scene.id),
        file_key="opening",
        title="开场",
    )
    script = SaveScript(
        scene_id=scene.id,
        file_key="opening",
        title="开场",
        content="人物走到窗前，先观察院子。",
        adopt=False,
    )
    first = await _script_preview(db_session, test_project_id, script, context=context)
    assert first["file_exists"] and first["before"] is None
    result = await _script_apply(
        db_session, test_project_id, script, first, context=context
    )
    stored = await StoryService().get_script_file(
        db_session, test_project_id, result["id"]
    )
    assert stored.adopted_revision_id is None
    assert stored.revision.provenance["assistant_run_id"] == context.run_id
    adopted = script.model_copy(update={"adopt": True, "content": "他走到窗前。"})
    preview = await _script_preview(db_session, test_project_id, adopted, context=context)
    await _script_apply(db_session, test_project_id, adopted, preview, context=context)
    stored = await StoryService().get_script_file(
        db_session, test_project_id, result["id"]
    )
    assert stored.adopted_revision_id == stored.current_revision_id


@pytest.mark.asyncio
async def test_assistant_can_start_outline_and_scene_plan_in_an_empty_project(
    db_session, test_project_id
):
    from modules.story.assistant_tools import (
        CreateScenes,
        _outline_apply,
        _outline_preview,
        _scenes_apply,
        _scenes_preview,
    )
    from modules.story.outline_state.story_outline_schemas import StoryOutlineContent
    from modules.story.outline_state.story_outline_service import StoryOutlineService

    context = AssistantOperationContext(
        str(uuid.uuid4()), str(current_account_id()), WorkContext(scope="project")
    )
    content = StoryOutlineContent(
        title="调查者的故事",
        creative_core={
            "premise": "调查者寻找失踪者",
            "tone_and_reader_promise": "悬疑中保留希望",
            "story_engine": "每条线索改变对失踪事件的判断",
        },
        outline_markdown="先调查，再选择是否公开真相。",
        major_storylines=[],
        macro_movements=[],
        open_decisions=[],
    )
    preview = await _outline_preview(
        db_session, test_project_id, content, context=context
    )
    assert preview["base_revision_id"] is None
    result = await _outline_apply(
        db_session, test_project_id, content, preview, context=context
    )
    assert (
        str(
            (
                await StoryOutlineService().get_current(db_session, test_project_id)
            ).revision.id
        )
        == result["id"]
    )
    scenes = CreateScenes(
        scenes=[
            {"title": "寻找线索", "goal": "确定失踪的时间"},
            {"title": "追访见证人", "goal": "比较两份证词"},
        ]
    )
    preview = await _scenes_preview(db_session, test_project_id, scenes, context=context)
    result = await _scenes_apply(
        db_session, test_project_id, scenes, preview, context=context
    )
    assert len(result["scene_ids"]) == 2
    with pytest.raises(ConflictError):
        await _scenes_apply(db_session, test_project_id, scenes, preview, context=context)
