from modules.world.world_background import WorldBackgroundAggregation


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
