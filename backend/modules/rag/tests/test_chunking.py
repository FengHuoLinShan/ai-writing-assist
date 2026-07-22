"""
RAG 分块单元测试
"""

from __future__ import annotations

import pytest

from modules.rag.chunking import ChunkingService


class TestChunkingService:
    def test_split_by_paragraphs(self) -> None:
        text = "第一段内容。\n\n第二段内容。\n\n第三段内容。"
        chunks = ChunkingService().split_by_paragraphs(text)
        assert len(chunks) == 3

    def test_split_by_paragraphs_empty(self) -> None:
        assert ChunkingService().split_by_paragraphs("") == []
        assert ChunkingService().split_by_paragraphs("   ") == []

    def test_split_by_length(self) -> None:
        text = "这是一个测试文本。" * 50
        chunks = ChunkingService().split_by_length(text, chunk_size=100, overlap=0)
        assert len(chunks) > 1
        assert all(c for c in chunks)

    @pytest.mark.parametrize(
        ("chunk_size", "overlap"),
        [(0, 0), (-1, 0), (100, -1), (100, 100), (100, 101)],
    )
    def test_split_by_length_rejects_non_progressing_windows(
        self,
        chunk_size: int,
        overlap: int,
    ) -> None:
        with pytest.raises(ValueError):
            ChunkingService().split_by_length(
                "测试文本" * 100,
                chunk_size=chunk_size,
                overlap=overlap,
            )

    def test_split_chinese_novel_keeps_offsets_and_overlap(self) -> None:
        text = "\n\n".join(
            [
                "周明瑞睁开眼睛，发现自己躺在陌生的房间里。" * 12,
                "他按住额头，试图理清脑海里混乱的记忆。" * 12,
                "窗外的煤气灯仍然亮着，克莱恩这个名字浮了出来。" * 12,
            ]
        )
        chunks = ChunkingService().split_chinese_novel(
            text,
            target_length=180,
            max_length=260,
            overlap=40,
        )
        assert len(chunks) >= 3
        assert all(c.text == text[c.start_offset : c.end_offset].strip() for c in chunks)
        assert all(c.char_count == len(c.text) for c in chunks)

    def test_extract_summary(self) -> None:
        svc = ChunkingService()
        assert svc.extract_summary("短文本") == "短文本"
        long_text = "这是一个很长的文本。" * 50
        assert len(svc.extract_summary(long_text, max_length=20)) <= 23
