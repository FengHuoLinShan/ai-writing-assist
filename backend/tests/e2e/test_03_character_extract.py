"""
人物档案抽取 E2E 测试 — 真实 LLM + 真实 PG

验证完整链路：创建角色 → 写入章节 → RAG 索引 → LLM 抽取
→ DB 写入 → apply-suggestions → 前端 API
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from tests.e2e.seed_data import create_full_scene


@pytest_asyncio.fixture
async def extract_ctx(db_session: AsyncSession):
    meta = await create_full_scene(db_session)
    await db_session.flush()

    from pathlib import Path

    from modules.writing.models import WritingDraft

    chapter_text = Path(__file__).resolve().parent / "samples" / "lotm_chapter_1.txt"
    content = chapter_text.read_text(encoding="utf-8")

    draft = WritingDraft(
        id=uuid.uuid4(),
        novel_id=meta["project_uuid"],
        chapter_index=1,
        title="第一章 穿越者",
        content=content,
        version_number=1,
        status="draft",
    )
    db_session.add(draft)
    await db_session.flush()

    from modules.rag.facade import index_chapter

    count = await index_chapter(db_session, meta["project_id"], 1)
    await db_session.flush()

    return db_session, meta["project_id"], meta["character_ids"], count


class TestCharacterExtractE2E:
    """真实 LLM 抽取人物档案"""

    @pytest.mark.asyncio
    async def test_extract_writes_ai_suggestions_with_real_llm(
        self,
        extract_ctx,
    ) -> None:
        db, pid, cids, chunk_count = extract_ctx

        assert chunk_count > 0, f"No RAG chunks indexed, got {chunk_count}"

        char_id = cids["克莱恩·莫雷蒂"]

        from infrastructure.tasks.models import AsyncTask
        from modules.character.tasks import handle_character_extract

        task = AsyncTask(
            id=uuid.uuid4(),
            task_type="character_extract",
            status="pending",
            meta={"novel_id": pid, "character_id": char_id},
            progress=0.0,
        )

        result = await handle_character_extract(db, task)

        assert result["status"] == "ok", f"Extract failed: {result}"
        assert len(result["fields"]) > 0, "No fields extracted"

        from modules.character.repositories import CharacterRepository

        repo = CharacterRepository()
        char_uuid = uuid.UUID(hex=char_id)
        updated = await repo.get(db, char_uuid)
        assert updated is not None
        assert updated.meta is not None
        assert "ai_suggestions" in updated.meta
        suggestions = updated.meta["ai_suggestions"]
        assert len(suggestions) > 0, f"ai_suggestions is empty: {updated.meta}"
        assert "ai_suggestions_at" in updated.meta

        for field in result["fields"]:
            assert field in suggestions, f"Field {field} missing from ai_suggestions"

    @pytest.mark.asyncio
    async def test_extract_then_apply_suggestions(
        self,
        extract_ctx,
    ) -> None:
        db, pid, cids, chunk_count = extract_ctx
        char_id = cids["克莱恩·莫雷蒂"]

        from infrastructure.tasks.models import AsyncTask
        from modules.character.tasks import handle_character_extract

        task = AsyncTask(
            id=uuid.uuid4(),
            task_type="character_extract",
            status="pending",
            meta={"novel_id": pid, "character_id": char_id},
            progress=0.0,
        )
        result = await handle_character_extract(db, task)
        assert result["status"] == "ok"

        from modules.character.schemas import CharacterUpdate
        from modules.character.services import CharacterService
        from modules.character.tasks import _EXTRACTABLE_FIELDS

        service = CharacterService()
        char = await service.get_character(db, char_id, novel_id=pid)
        meta = dict(getattr(char, "meta", {}) or {})
        suggestions = meta.get("ai_suggestions", {})
        assert len(suggestions) > 0

        fields_to_apply = list(suggestions.keys())
        updates: dict[str, object] = {}
        for field in fields_to_apply:
            if field in suggestions and suggestions[field]:
                if field in _EXTRACTABLE_FIELDS:
                    updates[field] = suggestions[field]

        remaining_suggestions = {
            k: v for k, v in suggestions.items() if k not in fields_to_apply
        }
        meta["ai_suggestions"] = remaining_suggestions
        if not remaining_suggestions:
            meta.pop("ai_suggestions", None)
            meta.pop("ai_suggestions_at", None)
        updates["meta"] = meta

        update_data = CharacterUpdate(**updates)
        updated = await service.update_character(db, char_id, update_data, novel_id=pid)

        for field in fields_to_apply:
            if field in _EXTRACTABLE_FIELDS and suggestions.get(field):
                assert getattr(updated, field) == suggestions[field], (
                    f"Field {field}: expected {suggestions[field]!r}, "
                    f"got {getattr(updated, field)!r}"
                )

        assert (
            updated.meta.get("ai_suggestions") is None
            or updated.meta.get("ai_suggestions") == {}
        )

    @pytest.mark.asyncio
    async def test_extract_apply_then_get_character_shows_updated_fields(
        self,
        extract_ctx,
    ) -> None:
        db, pid, cids, chunk_count = extract_ctx
        char_id = cids["克莱恩·莫雷蒂"]

        from infrastructure.tasks.models import AsyncTask
        from modules.character.tasks import handle_character_extract

        task = AsyncTask(
            id=uuid.uuid4(),
            task_type="character_extract",
            status="pending",
            meta={"novel_id": pid, "character_id": char_id},
            progress=0.0,
        )
        result = await handle_character_extract(db, task)
        assert result["status"] == "ok"

        from modules.character.schemas import CharacterUpdate
        from modules.character.services import CharacterService
        from modules.character.tasks import _EXTRACTABLE_FIELDS

        service = CharacterService()
        char = await service.get_character(db, char_id, novel_id=pid)
        suggestions = char.meta.get("ai_suggestions", {})
        assert len(suggestions) > 0

        fields_to_apply = list(suggestions.keys())
        updates: dict[str, object] = {}
        for field in fields_to_apply:
            if field in suggestions and suggestions[field]:
                if field in _EXTRACTABLE_FIELDS:
                    updates[field] = suggestions[field]

        remaining_suggestions = {
            k: v for k, v in suggestions.items() if k not in fields_to_apply
        }
        meta = dict(char.meta or {})
        meta["ai_suggestions"] = remaining_suggestions
        if not remaining_suggestions:
            meta.pop("ai_suggestions", None)
            meta.pop("ai_suggestions_at", None)
        updates["meta"] = meta

        update_data = CharacterUpdate(**updates)
        await service.update_character(db, char_id, update_data, novel_id=pid)

        refreshed = await service.get_character(db, char_id, novel_id=pid)
        for field in fields_to_apply:
            if field in _EXTRACTABLE_FIELDS and suggestions.get(field):
                assert getattr(refreshed, field) == suggestions[field], (
                    f"Field {field}: expected {suggestions[field]!r}, "
                    f"got {getattr(refreshed, field)!r}"
                )
