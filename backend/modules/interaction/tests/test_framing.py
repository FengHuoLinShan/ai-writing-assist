from __future__ import annotations

from modules.interaction.framing import (
    META_END,
    META_START,
    InteractionStreamFramer,
    frame_complete_story,
    visible_story_content,
)


def test_framer_split_delimiters_keeps_metadata_out_of_visible_story() -> None:
    framer = InteractionStreamFramer()
    payload = (
        "雾中的钟声再次响起。"
        + META_START
        + '{"version":1,"suggested_title":"雾中旅程",'
        + '"action_suggestions":[{"label":"追上去","text":"我追向钟声。"}]}'
        + META_END
    )

    visible = "".join(
        framer.feed(payload[index : index + 3]) for index in range(0, len(payload), 3)
    )
    trailing, metadata, raw = framer.finish()

    assert visible + trailing == "雾中的钟声再次响起。"
    assert META_START not in visible
    assert META_END not in visible
    assert metadata is not None
    assert metadata.suggested_title == "雾中旅程"
    assert metadata.action_suggestions[0].text == "我追向钟声。"
    assert '"version":1' in raw


def test_framer_invalid_metadata_preserves_completed_story_without_suggestions() -> None:
    framer = InteractionStreamFramer()

    visible = framer.feed("故事正文" + META_START + "{bad json}" + META_END)
    trailing, metadata, _raw = framer.finish()

    assert visible + trailing == "故事正文"
    assert metadata is None


def test_framer_ordinary_marker_prefix_is_not_silently_lost() -> None:
    framer = InteractionStreamFramer()

    visible = framer.feed("故事里出现了 <INTERACTION_META")
    trailing, metadata, _raw = framer.finish()

    assert visible + trailing == "故事里出现了 <INTERACTION_META"
    assert metadata is None


def test_one_shot_repair_uses_same_hidden_metadata_boundary() -> None:
    text, metadata = frame_complete_story(
        "你在灯下重新核对笔记。"
        + META_START
        + '{"version":1,"response_kind":"story","suggested_title":"灯下重查"}'
        + META_END
    )
    assert text == "你在灯下重新核对笔记。"
    assert metadata is not None and metadata.suggested_title == "灯下重查"
    assert (
        visible_story_content(
            "你在灯下重新核对笔记。"
            + META_START
            + '{"version":1,"response_kind":"story","suggested_title":"灯下重查"}'
            + META_END
        )
        == "你在灯下重新核对笔记。"
    )
    assert visible_story_content("正文" + META_START + "{bad}" + META_END) == (
        "正文" + META_START + "{bad}" + META_END
    )
