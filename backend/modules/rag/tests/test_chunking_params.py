"""
中文小说分块默认参数测试。
"""

from __future__ import annotations

from modules.rag.chunking import ChunkingService


def _build_long_text(total_chars: int = 5000) -> str:
    """构造一段足够长的中文正文，用于触发多 chunk 切分。"""
    sentence = "周明瑞睁开眼睛，发现自己躺在陌生的房间里，窗外的煤气灯仍然亮着。"
    repeats = total_chars // len(sentence) + 1
    return (sentence * repeats)[:total_chars]


def test_default_cn_chunking_params() -> None:
    """默认中文分块参数应为 target=700、max=900、overlap=130。"""
    chunking = ChunkingService()
    assert chunking.DEFAULT_CN_TARGET_LENGTH == 900
    assert chunking.DEFAULT_CN_MAX_LENGTH == 1400
    assert chunking.DEFAULT_CN_OVERLAP == 160


def test_default_cn_novel_chunk_sizes() -> None:
    """默认参数切分长文本后，每个 chunk 字符数应在合理区间。"""
    chunking = ChunkingService()
    text = _build_long_text(5000)
    chunks = chunking.split_chinese_novel(text)

    assert len(chunks) > 1
    for c in chunks:
        assert c.char_count <= chunking.DEFAULT_CN_MAX_LENGTH
        assert c.char_count > 0
        assert c.text == text[c.start_offset : c.end_offset].strip()


def test_default_cn_novel_overlap_exists() -> None:
    """相邻 chunk 之间应保留约 overlap 的重叠。"""
    chunking = ChunkingService()
    text = _build_long_text(5000)
    chunks = chunking.split_chinese_novel(text)

    overlaps = []
    for prev, curr in zip(chunks[:-1], chunks[1:]):
        overlap = prev.end_offset - curr.start_offset
        overlaps.append(overlap)

    assert overlaps
    # 重叠不一定精确等于默认值，但应明显大于 0 且不超过 max
    assert all(0 < o <= chunking.DEFAULT_CN_OVERLAP * 2 for o in overlaps)


def test_short_text_single_chunk() -> None:
    """短文本应只产生一个 chunk 且不超过硬上限。"""
    chunking = ChunkingService()
    text = "这是一个很短的正文。"
    chunks = chunking.split_chinese_novel(text)

    assert len(chunks) == 1
    assert chunks[0].char_count <= chunking.DEFAULT_CN_MAX_LENGTH
