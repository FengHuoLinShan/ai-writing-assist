"""
Unit tests for modules.world.character_facade.

All facade functions are thin delegators to CharacterService.
We mock _character_service to isolate the facade layer.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.facade import (
    create_character,
    filter_context_by_character_knowledge,
    get_character_knowledge_context,
    get_characters_context,
    list_characters,
)
from modules.world.schemas import (
    CharacterContextBundle,
    CharacterContextItem,
    CharacterKnowledgeContext,
    CharacterResponse,
)

pytestmark = [pytest.mark.asyncio]


# ============================================================
# create_character
# ============================================================


async def test_create_character_with_valid_data_returns_character_response(
    db_session: AsyncSession,
):
    """Happy path: 创建人物并返回 CharacterResponse"""
    # Arrange
    novel_id = str(uuid.uuid4())
    name = "测试人物"
    world_entity_id = str(uuid.uuid4())
    expected = CharacterResponse(
        entity_id=world_entity_id,
        novel_id=novel_id,
        name=name,
    )
    mock_service = AsyncMock()
    mock_service.create.return_value = expected

    # Act
    with patch("modules.world.character_facade._character_service", mock_service):
        result = await create_character(
            db_session,
            novel_id,
            name,
            world_entity_id,
        )

    # Assert
    mock_service.create.assert_awaited_once()
    call_args = mock_service.create.await_args
    assert call_args.args[0] is db_session
    assert call_args.args[1] == novel_id
    assert call_args.args[2].name == name
    assert call_args.args[2].entity_id == world_entity_id
    assert result == expected


async def test_create_character_with_none_world_entity_id_uses_empty_string(
    db_session: AsyncSession,
):
    """边界: world_entity_id 为 None 时应转为空字符串"""
    # Arrange
    novel_id = str(uuid.uuid4())
    name = "测试人物"
    expected = CharacterResponse(
        entity_id="",
        novel_id=novel_id,
        name=name,
    )
    mock_service = AsyncMock()
    mock_service.create.return_value = expected

    # Act
    with patch("modules.world.character_facade._character_service", mock_service):
        result = await create_character(
            db_session,
            novel_id,
            name,
            world_entity_id=None,
        )

    # Assert
    call_args = mock_service.create.await_args
    assert call_args.args[2].entity_id == ""
    assert result.name == name


async def test_create_character_with_empty_name_raises_validation_error(
    db_session: AsyncSession,
):
    """边界: 空名称应触发 schema validation 异常"""
    # Arrange
    name = ""

    # Act / Assert
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        from modules.world.schemas import CharacterCreate

        CharacterCreate(name=name, entity_id="")


async def test_create_character_propagates_service_exception(
    db_session: AsyncSession,
):
    """异常: service 层抛出的异常应原样向上传播"""
    # Arrange
    novel_id = str(uuid.uuid4())
    name = "测试人物"
    mock_service = AsyncMock()
    mock_service.create.side_effect = RuntimeError("db error")

    # Act / Assert
    with patch("modules.world.character_facade._character_service", mock_service):
        with pytest.raises(RuntimeError, match="db error"):
            await create_character(db_session, novel_id, name)


# ============================================================
# list_characters
# ============================================================


async def test_list_characters_with_defaults_returns_tuple(
    db_session: AsyncSession,
):
    """Happy path: 默认 skip/limit 返回 (items, total)"""
    # Arrange
    novel_id = str(uuid.uuid4())
    char = CharacterResponse(
        entity_id=str(uuid.uuid4()),
        novel_id=novel_id,
        name="主角",
    )
    expected_items = [char]
    expected_total = 1
    mock_service = AsyncMock()
    mock_service.list.return_value = (expected_items, expected_total)

    # Act
    with patch("modules.world.character_facade._character_service", mock_service):
        items, total = await list_characters(db_session, novel_id)

    # Assert
    mock_service.list.assert_awaited_once_with(
        db_session,
        novel_id,
        skip=0,
        limit=100,
    )
    assert items == expected_items
    assert total == expected_total


async def test_list_characters_with_custom_pagination_returns_tuple(
    db_session: AsyncSession,
):
    """边界: 自定义 skip/limit 应正确透传"""
    # Arrange
    novel_id = str(uuid.uuid4())
    mock_service = AsyncMock()
    mock_service.list.return_value = ([], 0)

    # Act
    with patch("modules.world.character_facade._character_service", mock_service):
        await list_characters(db_session, novel_id, skip=10, limit=50)

    # Assert
    mock_service.list.assert_awaited_once_with(
        db_session,
        novel_id,
        skip=10,
        limit=50,
    )


async def test_list_characters_with_zero_limit_returns_empty(
    db_session: AsyncSession,
):
    """边界: limit=0 时仍应正确调用并返回空列表"""
    # Arrange
    novel_id = str(uuid.uuid4())
    mock_service = AsyncMock()
    mock_service.list.return_value = ([], 0)

    # Act
    with patch("modules.world.character_facade._character_service", mock_service):
        items, total = await list_characters(db_session, novel_id, limit=0)

    # Assert
    assert items == []
    assert total == 0


async def test_list_characters_propagates_service_exception(
    db_session: AsyncSession,
):
    """异常: service 层异常应向上传播"""
    # Arrange
    novel_id = str(uuid.uuid4())
    mock_service = AsyncMock()
    mock_service.list.side_effect = ValueError("bad query")

    # Act / Assert
    with patch("modules.world.character_facade._character_service", mock_service):
        with pytest.raises(ValueError, match="bad query"):
            await list_characters(db_session, novel_id)


# ============================================================
# get_characters_context
# ============================================================


async def test_get_characters_context_with_defaults_returns_bundle(
    db_session: AsyncSession,
):
    """Happy path: 默认 reveal_mode 返回 CharacterContextBundle"""
    # Arrange
    novel_id = str(uuid.uuid4())
    char_id = str(uuid.uuid4())
    expected = CharacterContextBundle(
        characters=[
            CharacterContextItem(character_id=char_id, name="主角"),
        ],
        total=1,
        reveal_mode="author_safe",
    )
    mock_service = AsyncMock()
    mock_service.get_characters_context.return_value = expected

    # Act
    with patch("modules.world.character_facade._character_service", mock_service):
        result = await get_characters_context(
            db_session,
            novel_id,
            [char_id],
        )

    # Assert
    mock_service.get_characters_context.assert_awaited_once_with(
        db_session,
        novel_id,
        [char_id],
        "author_safe",
    )
    assert result == expected


async def test_get_characters_context_with_custom_reveal_mode_returns_bundle(
    db_session: AsyncSession,
):
    """边界: 自定义 reveal_mode 应正确透传"""
    # Arrange
    novel_id = str(uuid.uuid4())
    char_id = str(uuid.uuid4())
    expected = CharacterContextBundle(
        characters=[],
        total=0,
        reveal_mode="author_only",
    )
    mock_service = AsyncMock()
    mock_service.get_characters_context.return_value = expected

    # Act
    with patch("modules.world.character_facade._character_service", mock_service):
        result = await get_characters_context(
            db_session,
            novel_id,
            [char_id],
            reveal_mode="author_only",
        )

    # Assert
    mock_service.get_characters_context.assert_awaited_once_with(
        db_session,
        novel_id,
        [char_id],
        "author_only",
    )
    assert result.reveal_mode == "author_only"


async def test_get_characters_context_with_empty_ids_returns_empty_bundle(
    db_session: AsyncSession,
):
    """边界: 空 character_ids 列表应返回空 bundle"""
    # Arrange
    novel_id = str(uuid.uuid4())
    expected = CharacterContextBundle(
        characters=[],
        total=0,
        reveal_mode="author_safe",
    )
    mock_service = AsyncMock()
    mock_service.get_characters_context.return_value = expected

    # Act
    with patch("modules.world.character_facade._character_service", mock_service):
        result = await get_characters_context(db_session, novel_id, [])

    # Assert
    assert result.characters == []
    assert result.total == 0


async def test_get_characters_context_propagates_service_exception(
    db_session: AsyncSession,
):
    """异常: service 层异常应向上传播"""
    # Arrange
    novel_id = str(uuid.uuid4())
    mock_service = AsyncMock()
    mock_service.get_characters_context.side_effect = PermissionError("denied")

    # Act / Assert
    with patch("modules.world.character_facade._character_service", mock_service):
        with pytest.raises(PermissionError, match="denied"):
            await get_characters_context(
                db_session,
                novel_id,
                [str(uuid.uuid4())],
            )


# ============================================================
# get_character_knowledge_context
# ============================================================


async def test_get_character_knowledge_context_with_target_ids_returns_list(
    db_session: AsyncSession,
):
    """Happy path: 带 target_ids 返回知识上下文列表"""
    # Arrange
    novel_id = str(uuid.uuid4())
    char_id = str(uuid.uuid4())
    target_id = str(uuid.uuid4())
    expected = [
        CharacterKnowledgeContext(
            target_type="character",
            target_id=target_id,
            knowledge_level="partial",
            known_content="知道名字",
        ),
    ]
    mock_service = AsyncMock()
    mock_service.get_character_knowledge_context.return_value = expected

    # Act
    with patch("modules.world.character_facade._character_service", mock_service):
        result = await get_character_knowledge_context(
            db_session,
            novel_id,
            char_id,
            target_ids=[target_id],
        )

    # Assert
    mock_service.get_character_knowledge_context.assert_awaited_once_with(
        db_session,
        novel_id,
        char_id,
        [target_id],
    )
    assert result == expected


async def test_get_character_knowledge_context_with_none_target_ids_returns_list(
    db_session: AsyncSession,
):
    """边界: target_ids 为 None 时应正确透传"""
    # Arrange
    novel_id = str(uuid.uuid4())
    char_id = str(uuid.uuid4())
    expected = []
    mock_service = AsyncMock()
    mock_service.get_character_knowledge_context.return_value = expected

    # Act
    with patch("modules.world.character_facade._character_service", mock_service):
        result = await get_character_knowledge_context(
            db_session,
            novel_id,
            char_id,
            target_ids=None,
        )

    # Assert
    mock_service.get_character_knowledge_context.assert_awaited_once_with(
        db_session,
        novel_id,
        char_id,
        None,
    )
    assert result == []


async def test_get_character_knowledge_context_with_empty_target_ids_returns_list(
    db_session: AsyncSession,
):
    """边界: target_ids 为空列表时应正确透传"""
    # Arrange
    novel_id = str(uuid.uuid4())
    char_id = str(uuid.uuid4())
    expected = []
    mock_service = AsyncMock()
    mock_service.get_character_knowledge_context.return_value = expected

    # Act
    with patch("modules.world.character_facade._character_service", mock_service):
        result = await get_character_knowledge_context(
            db_session,
            novel_id,
            char_id,
            target_ids=[],
        )

    # Assert
    mock_service.get_character_knowledge_context.assert_awaited_once_with(
        db_session,
        novel_id,
        char_id,
        [],
    )
    assert result == []


async def test_get_character_knowledge_context_propagates_service_exception(
    db_session: AsyncSession,
):
    """异常: service 层异常应向上传播"""
    # Arrange
    novel_id = str(uuid.uuid4())
    char_id = str(uuid.uuid4())
    mock_service = AsyncMock()
    mock_service.get_character_knowledge_context.side_effect = ConnectionError(
        "db down",
    )

    # Act / Assert
    with patch("modules.world.character_facade._character_service", mock_service):
        with pytest.raises(ConnectionError, match="db down"):
            await get_character_knowledge_context(
                db_session,
                novel_id,
                char_id,
            )


# ============================================================
# filter_context_by_character_knowledge
# ============================================================


async def test_filter_context_by_character_knowledge_with_items_returns_filtered(
    db_session: AsyncSession,
):
    """Happy path: 过滤上下文并返回 filtered 列表"""
    # Arrange
    novel_id = str(uuid.uuid4())
    char_id = str(uuid.uuid4())
    context_items = [
        {
            "target_type": "character",
            "target_id": str(uuid.uuid4()),
            "content": "原始内容",
        },
    ]
    expected_filtered = [
        {
            "target_type": "character",
            "target_id": context_items[0]["target_id"],
            "content": "原始内容",
            "knowledge_level": "full",
        },
    ]
    mock_service = AsyncMock()
    mock_service.filter_context_by_character_knowledge.return_value = (
        expected_filtered,
        0,
        0,
    )

    # Act
    with patch("modules.world.character_facade._character_service", mock_service):
        result = await filter_context_by_character_knowledge(
            db_session,
            novel_id,
            char_id,
            context_items,
        )

    # Assert
    mock_service.filter_context_by_character_knowledge.assert_awaited_once_with(
        db_session,
        novel_id,
        char_id,
        context_items,
    )
    assert result == expected_filtered


async def test_filter_context_by_character_knowledge_with_empty_items_returns_empty(
    db_session: AsyncSession,
):
    """边界: 空 context_items 应返回空列表"""
    # Arrange
    novel_id = str(uuid.uuid4())
    char_id = str(uuid.uuid4())
    mock_service = AsyncMock()
    mock_service.filter_context_by_character_knowledge.return_value = ([], 0, 0)

    # Act
    with patch("modules.world.character_facade._character_service", mock_service):
        result = await filter_context_by_character_knowledge(
            db_session,
            novel_id,
            char_id,
            [],
        )

    # Assert
    assert result == []


async def test_filter_context_by_character_knowledge_discards_counts(
    db_session: AsyncSession,
):
    """边界: facade 只返回 filtered 列表，丢弃 removed_count / replaced_count"""
    # Arrange
    novel_id = str(uuid.uuid4())
    char_id = str(uuid.uuid4())
    context_items = [{"target_type": "event", "target_id": str(uuid.uuid4())}]
    mock_service = AsyncMock()
    mock_service.filter_context_by_character_knowledge.return_value = (
        [],
        5,
        3,
    )

    # Act
    with patch("modules.world.character_facade._character_service", mock_service):
        result = await filter_context_by_character_knowledge(
            db_session,
            novel_id,
            char_id,
            context_items,
        )

    # Assert
    assert result == []
    mock_service.filter_context_by_character_knowledge.assert_awaited_once()


async def test_filter_context_by_character_knowledge_propagates_service_exception(
    db_session: AsyncSession,
):
    """异常: service 层异常应向上传播"""
    # Arrange
    novel_id = str(uuid.uuid4())
    char_id = str(uuid.uuid4())
    mock_service = AsyncMock()
    mock_service.filter_context_by_character_knowledge.side_effect = OSError(
        "disk full",
    )

    # Act / Assert
    with patch("modules.world.character_facade._character_service", mock_service):
        with pytest.raises(OSError, match="disk full"):
            await filter_context_by_character_knowledge(
                db_session,
                novel_id,
                char_id,
                [{}],
            )


# ============================================================
# Additional edge-case tests for input shapes
# ============================================================


async def test_create_character_with_special_characters_in_name(
    db_session: AsyncSession,
):
    """边界: 名称包含特殊字符应正常透传"""
    # Arrange
    novel_id = str(uuid.uuid4())
    name = "主角👑·艾米莉亚『测试』"
    expected = CharacterResponse(
        entity_id=str(uuid.uuid4()),
        novel_id=novel_id,
        name=name,
    )
    mock_service = AsyncMock()
    mock_service.create.return_value = expected

    # Act
    with patch("modules.world.character_facade._character_service", mock_service):
        result = await create_character(db_session, novel_id, name)

    # Assert
    assert result.name == name


async def test_list_characters_with_negative_skip_passes_through(
    db_session: AsyncSession,
):
    """边界: 负数 skip 应透传给 service（由 service 决定如何处置）"""
    # Arrange
    novel_id = str(uuid.uuid4())
    mock_service = AsyncMock()
    mock_service.list.return_value = ([], 0)

    # Act
    with patch("modules.world.character_facade._character_service", mock_service):
        await list_characters(db_session, novel_id, skip=-1)

    # Assert
    mock_service.list.assert_awaited_once_with(
        db_session,
        novel_id,
        skip=-1,
        limit=100,
    )


async def test_get_characters_context_with_multiple_ids_passes_all(
    db_session: AsyncSession,
):
    """边界: 多个 character_ids 应全部透传"""
    # Arrange
    novel_id = str(uuid.uuid4())
    ids = [str(uuid.uuid4()) for _ in range(3)]
    expected = CharacterContextBundle(
        characters=[],
        total=0,
        reveal_mode="author_safe",
    )
    mock_service = AsyncMock()
    mock_service.get_characters_context.return_value = expected

    # Act
    with patch("modules.world.character_facade._character_service", mock_service):
        await get_characters_context(db_session, novel_id, ids)

    # Assert
    mock_service.get_characters_context.assert_awaited_once_with(
        db_session,
        novel_id,
        ids,
        "author_safe",
    )
