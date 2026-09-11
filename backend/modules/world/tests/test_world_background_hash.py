import uuid

import pytest

from modules.imports.models import ImportedChapter, ImportRecord
from modules.world.models import CoreEntity, EntityRelation, Event
from modules.world.world_background import WorldBackgroundAggregation


class _EmptyResult:
    def scalars(self):
        return self

    def all(self):
        return []


def test_source_hash_tracks_content_beyond_rendered_summary() -> None:
    shared_prefix = "a" * 1000
    first = WorldBackgroundAggregation._entry(
        "00000000-0000-0000-0000-000000000001",
        "world_bible_page",
        "00000000-0000-0000-0000-000000000002",
        "北境",
        shared_prefix + "first",
        "page:北境",
        0.7,
        "canonical",
        "author_only",
        ["北境"],
    )
    second = WorldBackgroundAggregation._entry(
        "00000000-0000-0000-0000-000000000001",
        "world_bible_page",
        "00000000-0000-0000-0000-000000000002",
        "北境",
        shared_prefix + "second",
        "page:北境",
        0.7,
        "canonical",
        "author_only",
        ["北境"],
    )

    assert first.summary == second.summary == shared_prefix
    assert first.source_hash != second.source_hash


@pytest.mark.asyncio
async def test_background_limited_queries_have_stable_tie_breaks() -> None:
    class CapturingSession:
        statements: list[str] = []

        async def execute(self, statement):
            self.statements.append(str(statement))
            return _EmptyResult()

    db = CapturingSession()

    await WorldBackgroundAggregation().build(
        db,  # type: ignore[arg-type]
        "00000000-0000-0000-0000-000000000001",
        limit=1,
    )

    relation_sql = next(
        item for item in db.statements if "FROM entity_relations" in item
    )
    knowledge_sql = next(
        item for item in db.statements if "FROM character_knowledge" in item
    )
    assert "entity_relations.strength DESC, entity_relations.id" in relation_sql
    assert "ORDER BY character_knowledge.id" in knowledge_sql


@pytest.mark.asyncio
async def test_background_keeps_events_with_missing_locations_and_relation_fallback(
    db_session, project_novel_id
) -> None:
    novel_id = uuid.UUID(project_novel_id)
    event_entity = CoreEntity(
        novel_id=novel_id, entity_type="event", name="事件", status="canonical"
    )
    source = CoreEntity(
        novel_id=novel_id, entity_type="faction", name="甲", status="canonical"
    )
    db_session.add_all([event_entity, source])
    await db_session.flush()
    record = ImportRecord(
        novel_id=novel_id, file_name="a.txt", file_type="txt", status="done"
    )
    db_session.add(record)
    await db_session.flush()
    chapter = ImportedChapter(
        novel_id=novel_id,
        import_record_id=record.id,
        chapter_index=1,
        title="一",
        content="x",
    )
    db_session.add(chapter)
    await db_session.flush()
    missing_location = uuid.uuid4()
    db_session.add_all(
        [
            Event(
                entity_id=event_entity.id,
                novel_id=novel_id,
                source_chapter_id=chapter.id,
                location_entity_id=missing_location,
                timeline_order=1,
            ),
            EntityRelation(
                novel_id=novel_id,
                source_id=source.id,
                target_id=missing_location,
                relation_type="near",
                relation_kind="spatial",
                status="canonical",
            ),
        ]
    )
    await db_session.flush()
    bundle = await WorldBackgroundAggregation().build(db_session, project_novel_id)
    summaries = "\n".join(item.summary for item in bundle.entries)
    assert f"location_entity_id={missing_location}" in summaries
    assert str(missing_location) in summaries
