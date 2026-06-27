"""
集成测试：人物知识边界

流程：
创建人物 → 创建知识记录（unknown）→ 编译女主视角上下文 → 输出中不应包含该知识
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.character.services import CharacterService
from modules.context.services import CompileOptions, ContextCompiler

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


class TestKnowledgeBoundaryFlow:
    """AI长篇小说结构化创作引擎_REVIEW_RULES_v1.0 §19.2 流程2"""

    async def test_unknown_knowledge_filtered_from_context(
        self,
        db_session: AsyncSession,
        test_project_id: str,
    ):
        novel_id = uuid.UUID(hex=test_project_id)
        nid_str = test_project_id

        # Step 1: 创建人物
        from modules.character.schemas import CharacterCreate

        char_service = CharacterService()
        character = await char_service.create_character(
            db_session,
            CharacterCreate(
                novel_id=nid_str,
                name="女主",
                role="女主",
                desire="查清真相",
            ),
        )
        char_id = character.id

        # Step 2: 创建世界对象（包含 hidden_truth）
        from modules.world.repositories import WorldEntityRepository
        from modules.world.schemas import WorldEntityCreate

        we_repo = WorldEntityRepository()
        entity = await we_repo.create(
            db_session,
            novel_id,
            WorldEntityCreate(
                name="残缺王印",
                entity_type="item",
                summary="旧王朝遗物",
                public_info="一个古老的印章",
                hidden_truth="残缺王印可以打开旧王都地下封印区，释放被封印的力量",
            ),
        )
        entity_id_str = str(entity.id)

        # Step 3: 创建知识记录 — 女主对残缺王印的知识等级为 "unknown"
        from modules.character.repositories import CharacterKnowledgeRepository
        from modules.character.schemas import CharacterKnowledgeCreate

        ck_repo = CharacterKnowledgeRepository()
        await ck_repo.create(
            db_session,
            CharacterKnowledgeCreate(
                novel_id=nid_str,
                character_id=char_id,
                target_type="world_entity",
                target_id=entity_id_str,
                knowledge_level="unknown",
                known_content=None,
                status="canonical",
            ),
        )

        # Step 4: 编译女主视角上下文
        compiler = ContextCompiler()
        options = CompileOptions(
            novel_id=nid_str,
            task="生成章节",
            scope="world_character",
            character_ids=[char_id],
            entity_ids=[entity_id_str],
            reveal_mode="author_safe",
        )
        bundle = await compiler.compile(db_session, options)

        # Step 5: 验证上下文输出中不包含 hidden_truth
        # entity 的 hidden_truth 在 author_safe 模式下会被标记/隐藏
        for ent in bundle.world_entities:
            ht = ent.get("hidden_truth", "")
            if ht:
                # 应被标记为 "作者视角信息" 警告
                assert "作者视角" in ht or "author_only" in ent.get("reveal_level", ""), (
                    f"hidden_truth 不应以原始形式暴露: {ht[:50]}"
                )
