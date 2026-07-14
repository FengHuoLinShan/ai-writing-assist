"""Contract tests for the public aliases in ``shared.types``."""

from shared.types import (
    JSON,
    ChapterIndex,
    CharacterID,
    DraftID,
    EmbeddingVector,
    EntityID,
    JSONList,
    NovelID,
    RelationshipID,
    SnapshotID,
    TaskID,
)


def test_identifier_aliases_remain_api_level_strings() -> None:
    aliases = (
        NovelID,
        EntityID,
        CharacterID,
        RelationshipID,
        SnapshotID,
        DraftID,
        TaskID,
    )

    assert all(alias.__value__ is str for alias in aliases)


def test_json_and_numeric_aliases_keep_their_public_shapes() -> None:
    assert JSON.__value__ == dict[str, object]
    assert JSONList.__value__ == list[object]
    assert ChapterIndex.__value__ is int
    assert EmbeddingVector.__value__ == list[float]
