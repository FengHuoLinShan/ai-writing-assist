from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from modules.project.models import Project


pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_core_entities_migration_copies_legacy_data_before_drop() -> None:
    migration_path = (
        Path(__file__).parents[2]
        / "alembic"
        / "versions"
        / "d967c0547254_refactor_core_entities_shared_table.py"
    )
    source = migration_path.read_text()

    first_copy = source.index("INSERT INTO core_entities")
    first_drop = source.index('op.drop_table("character_knowledge")')

    assert first_copy < first_drop
    assert "characters_new" in source
    assert "character_knowledge_new" in source
    assert "geo_locations_new" in source
    assert "geo_edges_new" in source
    assert "COALESCE(c.world_entity_id, c.id)" in source
    assert "parent.world_entity_id" in source
    # Verify target_id mapping resolves legacy extension table IDs
    assert "target_char.world_entity_id" in source
    assert "target_geo.world_entity_id" in source


async def _create_project(db_session: AsyncSession, title: str) -> str:
    project_id = uuid.uuid4()
    db_session.add(
        Project(
            id=project_id,
            title=title,
            genre="奇幻",
            tone="克制",
            language="zh",
        )
    )
    await db_session.flush()
    return str(project_id)


async def test_alias_api_rejects_cross_novel_writes(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    other_project_id = await _create_project(db_session, "另一本小说")

    created = await async_client.post(
        f"/api/world/entities?novel_id={test_project_id}",
        json={
            "entity_type": "item",
            "name": "青铜钥匙",
            "status": "canonical",
        },
    )
    assert created.status_code == 201
    entity_id = created.json()["id"]

    forbidden = await async_client.post(
        f"/api/world/entities/{entity_id}/aliases"
        f"?novel_id={other_project_id}&alias=别人的钥匙",
    )
    assert forbidden.status_code == 404

    fetched = await async_client.get(
        f"/api/world/entities/{entity_id}?novel_id={test_project_id}",
    )
    assert fetched.status_code == 200
    assert fetched.json()["aliases"] == []


async def test_remove_alias_idempotent(
    async_client: AsyncClient,
    test_project_id: str,
) -> None:
    """删除不存在的别名应返回 204（幂等），而非 404。"""
    created = await async_client.post(
        f"/api/world/entities?novel_id={test_project_id}",
        json={
            "entity_type": "item",
            "name": "测试物品",
            "status": "canonical",
        },
    )
    assert created.status_code == 201
    entity_id = created.json()["id"]

    # 先添加一个别名
    add_r = await async_client.post(
        f"/api/world/entities/{entity_id}/aliases"
        f"?novel_id={test_project_id}&alias=测试别名",
    )
    assert add_r.status_code == 201

    # 第一次删除 — 别名存在
    r1 = await async_client.delete(
        f"/api/world/entities/{entity_id}/aliases"
        f"?novel_id={test_project_id}&alias=测试别名",
    )
    assert r1.status_code == 204

    # 第二次删除 — 别名已不存在（幂等）
    r2 = await async_client.delete(
        f"/api/world/entities/{entity_id}/aliases"
        f"?novel_id={test_project_id}&alias=测试别名",
    )
    assert r2.status_code == 204

    # 删除一个从未存在的别名
    r3 = await async_client.delete(
        f"/api/world/entities/{entity_id}/aliases"
        f"?novel_id={test_project_id}&alias=不存在的别名",
    )
    assert r3.status_code == 204


async def test_entity_type_mapping() -> None:
    """entity_types 映射应覆盖所有有效类型，且修正错误的映射。"""
    from modules.world.services.entity_types import ENTITY_TYPE_MAP, is_entity_type_valid, map_entity_type

    # 错误映射修复："概念" 应映射为 "concept" 而非 "secret"
    assert map_entity_type("概念") == "concept", "概念→concept"
    assert map_entity_type("设定") == "secret", "设定→secret（保留）"

    # 新增类型的中文映射
    assert map_entity_type("生物") == "creature", "生物→creature"
    assert map_entity_type("怪物") == "creature", "怪物→creature"
    assert map_entity_type("技能") == "skill", "技能→skill"
    assert map_entity_type("能力") == "skill", "能力→skill"
    assert map_entity_type("其他") == "other", "其他→other"

    # character_ref 向后兼容映射
    assert map_entity_type("character_ref") == "character", "character_ref→character"

    # 正则验证应接受所有 mapped 类型值
    for raw, expected in ENTITY_TYPE_MAP.items():
        assert is_entity_type_valid(expected), f"{raw}→{expected} 应通过 is_entity_type_valid"

    # 新类型值应通过验证
    for t in ("concept", "creature", "skill", "other"):
        assert is_entity_type_valid(t), f"{t} 应通过 is_entity_type_valid"


async def test_get_characters_context_accepts_character_ids_keyword(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    from modules.character.facade import create_character_extension, get_characters_context
    from modules.world.facade import create_entity

    entity = await create_entity(
        db_session,
        test_project_id,
        name="林动",
        entity_type="character",
        status="canonical",
    )
    await create_character_extension(
        db_session,
        entity_id=entity.id,
        novel_id=test_project_id,
        role="protagonist",
    )

    bundle = await get_characters_context(
        db_session,
        test_project_id,
        character_ids=[entity.id],
    )

    assert bundle.total == 1
    assert bundle.characters[0].entity_id == entity.id
    assert bundle.characters[0].character_id == entity.id
    assert bundle.characters[0].role == "protagonist"


async def test_memory_geo_mutation_updates_character_location_by_core_entity_name(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    from modules.character.facade import (
        create_character_extension,
        get_character_location_id,
    )
    from modules.memory.facade import (
        confirm_memory_proposal,
        create_memory_update_proposals,
    )
    from modules.world.facade import create_entity

    character = await create_entity(
        db_session,
        test_project_id,
        name="林动",
        entity_type="character",
        status="canonical",
    )
    await create_character_extension(
        db_session,
        entity_id=character.id,
        novel_id=test_project_id,
    )
    location = await create_entity(
        db_session,
        test_project_id,
        name="炎城",
        entity_type="location",
        status="canonical",
    )

    proposals = await create_memory_update_proposals(
        db_session,
        test_project_id,
        source_type="chapter_text",
        source_id=str(uuid.uuid4()),
        extraction_result={
            "proposals": [
                {
                    "proposal_type": "create_memory",
                    "chapter_index": 3,
                    "payload": {
                        "memory_type": "chapter_state",
                        "summary": "林动前往炎城",
                        "chapter_index": 3,
                        "geo_mutations": {
                            "character_shifts": [
                                {
                                    "character_name": "林动",
                                    "destination_location_name": "炎城",
                                    "movement_type": "御剑飞行",
                                }
                            ],
                            "faction_shifts": [],
                        },
                    },
                }
            ]
        },
    )

    await confirm_memory_proposal(db_session, proposals[0].id, test_project_id)

    assert await get_character_location_id(
        db_session,
        test_project_id,
        character.id,
    ) == location.id


async def test_find_entity_by_name_alias_exact_match(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    """别名精确匹配应通过 Python 遍历找到正确实体。"""
    from modules.world.facade import add_alias, create_entity, find_entity_id_by_name

    entity = await create_entity(
        db_session,
        test_project_id,
        name="Fire City",
        entity_type="location",
        status="canonical",
    )
    await add_alias(db_session, entity.id, "炎城", alias_type="translation", novel_id=test_project_id)

    # Exact name match
    result = await find_entity_id_by_name(db_session, test_project_id, "Fire City")
    assert result == entity.id

    # Alias match
    result = await find_entity_id_by_name(db_session, test_project_id, "炎城")
    assert result == entity.id


async def test_find_entity_by_name_alias_respects_entity_type(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    """同名别名在不同 entity_type 下应区分。"""
    from modules.world.facade import add_alias, create_entity, find_entity_id_by_name

    loc = await create_entity(
        db_session,
        test_project_id,
        name="Location Alpha",
        entity_type="location",
        status="canonical",
    )
    await add_alias(db_session, loc.id, "阿尔法", novel_id=test_project_id)

    char = await create_entity(
        db_session,
        test_project_id,
        name="Character Beta",
        entity_type="character",
        status="canonical",
    )
    await add_alias(db_session, char.id, "贝塔", novel_id=test_project_id)

    # Type-filtered alias search
    assert await find_entity_id_by_name(db_session, test_project_id, "阿尔法", entity_type="location") == loc.id
    assert await find_entity_id_by_name(db_session, test_project_id, "阿尔法", entity_type="character") is None
    assert await find_entity_id_by_name(db_session, test_project_id, "贝塔", entity_type="character") == char.id


async def test_find_entity_by_name_empty_aliases(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    """无别名的实体按别名查找应返回 None。"""
    from modules.world.facade import create_entity, find_entity_id_by_name

    await create_entity(
        db_session,
        test_project_id,
        name="唯一名称",
        entity_type="item",
        status="canonical",
    )

    assert await find_entity_id_by_name(db_session, test_project_id, "不存在的别名") is None


async def test_find_entity_by_name_special_characters(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    """含特殊字符的别名不应导致查询异常。"""
    from modules.world.facade import add_alias, create_entity, find_entity_id_by_name

    entity = await create_entity(
        db_session,
        test_project_id,
        name='Item "Special"',
        entity_type="item",
        status="canonical",
    )
    # Alias with quotes and special chars — previously this would have broken
    # JSONPath string interpolation.
    await add_alias(db_session, entity.id, '带有"引号"的别名', novel_id=test_project_id)

    result = await find_entity_id_by_name(db_session, test_project_id, '带有"引号"的别名')
    assert result == entity.id


async def test_dedup_service_alias_search(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    """去重服务的别名搜索应通过 Python 遍历正确匹配。"""
    from modules.world.facade import add_alias, create_entity
    from modules.world.services.dedup_service import EntityDedupService
    from shared.utils import parse_uuid

    entity = await create_entity(
        db_session,
        test_project_id,
        name="青铜古剑",
        entity_type="item",
        status="canonical",
    )
    await add_alias(db_session, entity.id, "古剑", novel_id=test_project_id)

    service = EntityDedupService()
    nid = parse_uuid(test_project_id, "novel_id")

    # Exact alias match
    matches = await service._find_alias_matches_in_jsonb(db_session, nid, "古剑")
    assert len(matches) == 1
    assert matches[0]["entity_id"] == entity.id
    assert matches[0]["entity_name"] == "青铜古剑"

    # Non-match
    matches = await service._find_alias_matches_in_jsonb(db_session, nid, "不存在的别名")
    assert matches == []


async def test_find_alias_helpers() -> None:
    """共享别名工具函数应正确处理 CoreEntity 和原始列表。"""
    from modules.world.services.helpers import find_alias_in_entity, find_alias_in_list

    class MockEntity:
        aliases = [
            {"alias": "正名", "type": "name"},
            {"alias": "别名A", "type": "nickname"},
        ]

    assert find_alias_in_entity(MockEntity(), "正名") is True
    assert find_alias_in_entity(MockEntity(), "别名A") is True
    assert find_alias_in_entity(MockEntity(), "不存在") is False

    class EmptyEntity:
        aliases = []
    assert find_alias_in_entity(EmptyEntity(), "正名") is False

    class NoneEntity:
        aliases = None
    assert find_alias_in_entity(NoneEntity(), "正名") is False

    raw_list = [{"alias": "原始1", "type": "name"}, {"alias": "原始2", "type": "title"}]
    assert find_alias_in_list(raw_list, "原始1") is True
    assert find_alias_in_list(raw_list, "原始2") is True
    assert find_alias_in_list(raw_list, "不存在的") is False
    assert find_alias_in_list(None, "任何") is False
    assert find_alias_in_list([], "任何") is False
    assert find_alias_in_entity(MockEntity(), "") is False
    assert find_alias_in_list(raw_list, "") is False


async def test_find_entity_by_name_no_limit_truncation(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    """find_entity_by_name 不应截断别名搜索（>500 实体场景）。"""
    from modules.world.facade import add_alias, create_entity, find_entity_id_by_name

    # 创建一个带别名的实体（模拟第 500+ 个位置但没有真正创建 500 个）
    entity = await create_entity(
        db_session,
        test_project_id,
        name="FarEntity",
        entity_type="item",
        status="canonical",
    )
    await add_alias(db_session, entity.id, "远方的别名", alias_type="name", novel_id=test_project_id)

    # 别名搜索应找到匹配
    result = await find_entity_id_by_name(db_session, test_project_id, "远方的别名")
    assert result == entity.id, "别名搜索不应因 limit 截断而返回 None"

    # 验证 repositories.py 的 alias 分支不再硬编码 limit(500)
    import ast, pathlib
    repo_path = pathlib.Path(__file__).parents[2] / "modules/world/repositories.py"
    tree = ast.parse(repo_path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "limit":
            for arg in node.args:
                if isinstance(arg, ast.Constant) and arg.value == 500:
                    raise AssertionError(
                        "repositories.py 中仍有 `.limit(500)` 在 alias 分支中，"
                        "这会导致第 501+ 个实体的别名无法匹配"
                    )


async def test_dedup_service_alias_search_performance(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    """去重别名搜索应使用列投影，避免加载核心实体的大字段。"""
    from modules.world.services.dedup_service import EntityDedupService
    from modules.world.models import CoreEntity
    from shared.utils import parse_uuid

    # 验证 `_find_alias_matches_in_jsonb` 使用列投影
    service = EntityDedupService()
    nid = parse_uuid(test_project_id, "novel_id")

    # 空结果也是正确的
    matches = await service._find_alias_matches_in_jsonb(db_session, nid, "不存在的别名")
    assert matches == []

    # 验证方法签名使用了 select(CoreEntity.id, CoreEntity.name, CoreEntity.aliases)
    # 而非 select(CoreEntity)
    import ast, pathlib
    dedup_path = pathlib.Path(__file__).parents[2] / "modules/world/services/dedup_service.py"
    tree = ast.parse(dedup_path.read_text())

    # 只在 _find_alias_matches_in_jsonb 函数体内搜索
    for func_node in ast.walk(tree):
        if isinstance(func_node, ast.AsyncFunctionDef) and func_node.name == "_find_alias_matches_in_jsonb":
            for node in ast.walk(func_node):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id == "select" and len(node.args) == 1
                        and isinstance(node.args[0], ast.Name)
                        and node.args[0].id == "CoreEntity"):
                    raise AssertionError(
                        "_find_alias_matches_in_jsonb 应使用列投影"
                        " select(CoreEntity.id, CoreEntity.name, CoreEntity.aliases)"
                    )
