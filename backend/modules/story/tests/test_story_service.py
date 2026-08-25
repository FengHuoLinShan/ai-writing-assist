from __future__ import annotations

import uuid

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.tasks.registry import get_registry
from modules.story.generation import (
    STORY_CARD_TASK,
    STORY_CHARACTER_CARD_ACTION,
    STORY_ONE_CLICK_ACTION,
    STORY_ONE_CLICK_TASK,
    STORY_REACTION_TASK,
    STORY_SCRIPT_TASK,
)
from modules.story.outline_state.repositories import SceneRepository
from modules.story.outline_state.schemas import SceneCreate
from modules.story.schemas import (
    CardPreview,
    CharacterCardContent,
    OneClickOutput,
    ScriptPreview,
)
from modules.story.service import (
    StoryAuthorizationError,
    StoryConflictError,
    StoryNotFoundError,
    StoryService,
)


async def _scene(
    db: AsyncSession,
    novel_id: str,
    *,
    title: str = "测试场景",
):
    return await SceneRepository().create(
        db,
        uuid.UUID(novel_id),
        SceneCreate(scene_index=0, title=title, goal="完成一次选择"),
    )


async def _character(db: AsyncSession, novel_id: str) -> uuid.UUID:
    from modules.world.models import Character, CoreEntity

    character_id = uuid.uuid4()
    project_id = uuid.UUID(novel_id)
    db.add(
        CoreEntity(
            id=character_id,
            novel_id=project_id,
            entity_type="character",
            name="测试人物",
            summary="人物摘要",
            status="canonical",
        )
    )
    db.add(
        Character(
            entity_id=character_id,
            novel_id=project_id,
            name="测试人物",
            personality="克制",
            status="canonical",
        )
    )
    await db.flush()
    return character_id


def _content(personality: str = "克制") -> CharacterCardContent:
    return CharacterCardContent(personality=personality)


def _one_click_output(scene_id: uuid.UUID, character_id: uuid.UUID) -> OneClickOutput:
    return OneClickOutput(
        scene_id=scene_id,
        cards=[CardPreview(character_id=character_id, content=_content())],
        reactions=[],
        script=ScriptPreview(
            scene_id=scene_id,
            script_text="人物做出选择。",
            narrative_plan="先制造压力，再留下代价。",
        ),
    )


@pytest.mark.asyncio
async def test_character_card_is_novel_isolated(
    db_session: AsyncSession,
    project_factory,
) -> None:
    novel_id = str(await project_factory.create_project("小说一"))
    other_novel_id = str(await project_factory.create_project("小说二"))
    scene = await _scene(db_session, novel_id)
    character_id = await _character(db_session, novel_id)
    service = StoryService()

    saved = await service.create_manual_card(
        db_session,
        novel_id=novel_id,
        scene_id=str(scene.id),
        character_id=str(character_id),
        content=_content(),
    )

    with pytest.raises(StoryNotFoundError):
        await service.get_card(db_session, other_novel_id, str(saved.id))


@pytest.mark.asyncio
async def test_card_and_script_heads_use_cas(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    scene = await _scene(db_session, test_project_id)
    service = StoryService()
    character_id = await _character(db_session, test_project_id)

    first_card = await service.create_manual_card(
        db_session,
        novel_id=test_project_id,
        scene_id=str(scene.id),
        character_id=str(character_id),
        content=_content(),
    )
    with pytest.raises(StoryConflictError) as card_conflict:
        await service.create_manual_card(
            db_session,
            novel_id=test_project_id,
            scene_id=str(scene.id),
            character_id=str(character_id),
            content=_content("变化"),
            expected_revision_id=uuid.uuid4(),
        )
    assert card_conflict.value.latest["current_revision_id"] == str(
        first_card.current_revision_id
    )

    first_script = await service.create_script_revision(
        db_session,
        novel_id=test_project_id,
        scene_id=str(scene.id),
        file_key="main",
        content="第一版",
        content_json={"beats": []},
        expected_revision_id=None,
        adopt=False,
    )
    with pytest.raises(StoryConflictError) as script_conflict:
        await service.create_script_revision(
            db_session,
            novel_id=test_project_id,
            scene_id=str(scene.id),
            file_key="main",
            content="冲突版",
            content_json=None,
            expected_revision_id=uuid.uuid4(),
            adopt=False,
        )
    assert script_conflict.value.latest["current_revision_id"] == str(
        first_script.current_revision_id
    )
    assert first_card.current_revision_id is not None
    assert first_script.current_revision_id is not None


@pytest.mark.asyncio
async def test_card_source_task_must_be_done_same_novel_and_action(
    db_session: AsyncSession,
    project_factory,
) -> None:
    from infrastructure.tasks.models import AsyncTask

    novel_id = str(await project_factory.create_project("小说一"))
    other_novel_id = str(await project_factory.create_project("小说二"))
    scene = await _scene(db_session, novel_id)
    character_id = await _character(db_session, novel_id)
    source_task = AsyncTask(
        id=uuid.uuid4(),
        task_type=STORY_CARD_TASK,
        novel_id=uuid.UUID(other_novel_id),
        status="done",
        meta={"action": STORY_CHARACTER_CARD_ACTION},
        result={"preview": {}},
    )
    db_session.add(source_task)
    await db_session.flush()

    with pytest.raises(StoryAuthorizationError):
        await StoryService().create_manual_card(
            db_session,
            novel_id=novel_id,
            scene_id=str(scene.id),
            character_id=str(character_id),
            content=_content(),
            source_task_id=source_task.id,
        )


@pytest.mark.asyncio
async def test_one_click_only_persists_authorized_freshness_checked_cards(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    scene = await _scene(db_session, test_project_id)
    character_id = await _character(db_session, test_project_id)
    service = StoryService()
    output = _one_click_output(scene.id, character_id)

    persisted, skipped = await service.persist_one_click_cards(
        db_session,
        novel_id=test_project_id,
        output=output,
        requested_character_ids=[str(character_id)],
        submit_authorized=False,
        authorization_ref="task:unauthorized",
        source_hashes={str(character_id): "a" * 64},
    )
    assert persisted == []
    assert skipped == []
    assert (
        await service.list_cards(
            db_session,
            test_project_id,
            scene_id=str(scene.id),
        )
        == []
    )

    persisted, skipped = await service.persist_one_click_cards(
        db_session,
        novel_id=test_project_id,
        output=output,
        requested_character_ids=[str(character_id)],
        submit_authorized=True,
        authorization_ref="task:authorized",
        source_hashes={str(character_id): "a" * 64},
    )
    assert len(persisted) == 1
    assert skipped == []
    current = (
        await service.list_cards(db_session, test_project_id, scene_id=str(scene.id))
    )[0]
    assert current.current_revision_id == persisted[0]
    assert current.revision is not None
    assert current.revision.source_manifest["source_hash"] == "a" * 64

    persisted, skipped = await service.persist_one_click_cards(
        db_session,
        novel_id=test_project_id,
        output=output,
        requested_character_ids=[str(character_id)],
        submit_authorized=True,
        authorization_ref="task:authorized-again",
        source_hashes={str(character_id): "a" * 64},
    )
    assert persisted == []
    assert skipped == [character_id]

    persisted, skipped = await service.persist_one_click_cards(
        db_session,
        novel_id=test_project_id,
        output=output,
        requested_character_ids=[str(character_id)],
        submit_authorized=True,
        authorization_ref="task:stale",
        source_hashes={str(character_id): "b" * 64},
    )
    assert len(persisted) == 1
    assert skipped == []
    assert persisted[0] != current.current_revision_id


@pytest.mark.asyncio
async def test_scene_story_assets_batch_load_revisions(
    db_session: AsyncSession,
    test_project_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scene = await _scene(db_session, test_project_id)
    service = StoryService()
    for index in range(3):
        character_id = await _character(db_session, test_project_id)
        await service.create_manual_card(
            db_session,
            novel_id=test_project_id,
            scene_id=str(scene.id),
            character_id=str(character_id),
            content=_content(f"性格-{index}"),
        )
        await service.create_script_revision(
            db_session,
            novel_id=test_project_id,
            scene_id=str(scene.id),
            file_key=f"script-{index}",
            content=f"剧本-{index}",
            content_json={"beats": [f"beat-{index}"]},
            expected_revision_id=None,
            adopt=True,
        )

    async def fail_single_get(*_args, **_kwargs):
        raise AssertionError("list reads must use the batch revision query")

    monkeypatch.setattr(service.card_revisions, "get", fail_single_get)
    monkeypatch.setattr(service.script_revisions, "get", fail_single_get)
    statements: list[str] = []

    def capture_statement(_conn, _cursor, statement, *_args) -> None:
        statements.append(statement)

    engine = db_session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", capture_statement)
    try:
        assets = await service.get_scene_story_assets(
            db_session,
            novel_id=test_project_id,
            scene_id=str(scene.id),
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture_statement)

    assert len(assets["character_cards"]) == 3
    assert len(assets["adopted_scripts"]) == 3
    assert assets["beats"] == ["beat-0", "beat-1", "beat-2"]
    assert [item["stale"] for item in assets["adopted_scripts"]] == [
        True,
        True,
        False,
    ]
    assert sum("FROM story_character_card_revisions" in sql for sql in statements) == 1
    assert sum("FROM story_scene_script_revisions" in sql for sql in statements) == 1


def test_story_task_manifest_and_public_actions_are_registered() -> None:
    registry = get_registry()
    for task_type in (
        STORY_CARD_TASK,
        STORY_REACTION_TASK,
        STORY_SCRIPT_TASK,
        STORY_ONE_CLICK_TASK,
    ):
        assert registry.get_handler(task_type) is not None
        assert registry.get_definition(task_type) is not None
        assert registry.get_definition(task_type).recovery_policy == "auto_requeue"
    assert STORY_ONE_CLICK_ACTION == "story.one_click.simulate"
