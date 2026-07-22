"""
RAG 文本分块

提供面向中文长篇小说的分块策略与通用分块工具。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChineseNovelChunk:
    """中文小说正文分块结果。"""

    chunk_index: int
    text: str
    start_offset: int
    end_offset: int
    char_count: int


class ChunkingService:
    """文本分块服务

    将长文本分割为适合检索的片段。
    MVP 简单实现：按段落分割，每段为一个 chunk。
    后续可扩展为滑动窗口、语义分割等策略。
    """

    DEFAULT_MAX_CHUNK_LENGTH: int = 2000
    """默认最大 chunk 长度（字符数）"""

    DEFAULT_CN_TARGET_LENGTH: int = 900
    DEFAULT_CN_MAX_LENGTH: int = 1400
    DEFAULT_CN_OVERLAP: int = 160

    SCENE_TRANSITION_PATTERNS: list[str] = [
        # 时间跳跃
        "第二天",
        "次日",
        "翌日",
        "几日",
        "数日",
        "一个月后",
        "不久之后",
        "转眼",
        "转眼间",
        "黄昏",
        "清晨",
        "夜晚",
        "入夜",
        "黎明",
        "次日清晨",
        "翌日清晨",
        "半夜",
        "过了几日",
        "又过了几日",
        "几个月后",
        "半年后",
        "一年后",
        "三日后",
        "七日后",
        "十日后",
        "那一年",
        "从此",
        "多年后",
        "曾经",
        "从前",
        "后来",
        "此刻",
        "就在这时",
        "突然",
        "不一会儿",
        # 空间/视角切换
        "与此同时",
        "另一边",
        "另一方面",
        "画面一转",
        "镜头一转",
        "视角切",
        # 分隔符
        "***",
        "---",
        "===",
        "——",
        "……",
    ]

    # 地点转换动词 — 在这些词之后紧跟地点时，优先作为切分点
    LOCATION_TRANSITION_VERBS: list[str] = [
        "回到",
        "来到",
        "走进",
        "离开",
        "返回",
        "前往",
        "抵达",
        "步入",
        "踏入",
        "跨入",
    ]

    def split_by_paragraphs(
        self,
        text: str,
        max_length: int | None = None,
    ) -> list[str]:
        """按段落分割文本

        每个段落为一个 chunk。
        如果段落超过 max_length，则进一步按句号分割。

        Args:
            text: 要分割的文本
            max_length: 最大 chunk 长度

        Returns:
            str 列表，每个元素为一个 chunk
        """
        max_len = max_length or self.DEFAULT_MAX_CHUNK_LENGTH
        if not text.strip():
            return []

        # 先按段落（两个换行符）分割
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

        chunks: list[str] = []
        for para in paragraphs:
            if len(para) <= max_len:
                chunks.append(para)
            else:
                # 超长段落按句号分割
                sentences = (
                    para.replace("。", "。\n")
                    .replace("！", "！\n")
                    .replace("？", "？\n")
                    .split("\n")
                )
                current = ""
                for sentence in sentences:
                    s = sentence.strip()
                    if not s:
                        continue
                    if len(current) + len(s) < max_len:
                        current += s
                    else:
                        if current:
                            chunks.append(current)
                        current = s
                if current:
                    chunks.append(current)

        return chunks

    def split_by_length(
        self,
        text: str,
        chunk_size: int = 1000,
        overlap: int = 100,
    ) -> list[str]:
        """按固定长度分割文本（带重叠）

        Args:
            text: 要分割的文本
            chunk_size: 每个 chunk 的目标字符数
            overlap: 相邻 chunk 的重叠字符数

        Returns:
            str 列表
        """
        if isinstance(chunk_size, bool) or chunk_size <= 0:
            raise ValueError("chunk_size must be a positive integer")
        if isinstance(overlap, bool) or overlap < 0 or overlap >= chunk_size:
            raise ValueError("overlap must be between 0 and chunk_size - 1")
        if not text.strip():
            return []

        chunks: list[str] = []
        start = 0
        text_len = len(text)

        while start < text_len:
            end = min(start + chunk_size, text_len)
            # 尽量在段落或句子边界结束
            if end < text_len:
                # 尝试在最后一个句号处断开
                last_period = text.rfind("。", start, end)
                if last_period > start + chunk_size // 2:
                    end = last_period + 1
                else:
                    # 尝试在最后一个换行处断开
                    last_newline = text.rfind("\n", start, end)
                    if last_newline > start + chunk_size // 2:
                        end = last_newline + 1

            chunks.append(text[start:end].strip())
            start = end - overlap if end < text_len else text_len

        return chunks

    def split_chinese_novel(
        self,
        text: str,
        *,
        target_length: int | None = None,
        max_length: int | None = None,
        overlap: int | None = None,
    ) -> list[ChineseNovelChunk]:
        """面向中文长篇小说的正文分块。

        优先在段落、对话和中文句末标点处切分，并记录原文 offset。
        相邻 chunk 保留少量重叠，便于人物出场和状态变化的前后文召回。
        """
        if not text or not text.strip():
            return []

        target = target_length or self.DEFAULT_CN_TARGET_LENGTH
        max_len = max_length or self.DEFAULT_CN_MAX_LENGTH
        overlap_len = overlap if overlap is not None else self.DEFAULT_CN_OVERLAP
        overlap_len = max(0, min(overlap_len, max_len // 2))

        chunks: list[ChineseNovelChunk] = []
        text_len = len(text)
        start = self._skip_whitespace(text, 0)

        while start < text_len:
            hard_end = min(start + max_len, text_len)
            if hard_end >= text_len:
                end = text_len
            else:
                end = self._choose_cn_boundary_with_scenes(text, start, target, hard_end)

            raw = text[start:end]
            stripped = raw.strip()
            if stripped:
                leading_ws = len(raw) - len(raw.lstrip())
                trailing_ws = len(raw) - len(raw.rstrip())
                adjusted_start = start + leading_ws
                adjusted_end = end - trailing_ws
                chunks.append(
                    ChineseNovelChunk(
                        chunk_index=len(chunks),
                        text=stripped,
                        start_offset=adjusted_start,
                        end_offset=adjusted_end,
                        char_count=len(stripped),
                    ),
                )

            if end >= text_len:
                break

            next_start = max(start + 1, end - overlap_len)
            start = self._skip_whitespace(text, next_start)

        return chunks

    @staticmethod
    def _skip_whitespace(text: str, start: int) -> int:
        while start < len(text) and text[start].isspace():
            start += 1
        return start

    @classmethod
    def _choose_cn_boundary_with_scenes(
        cls,
        text: str,
        start: int,
        target_length: int,
        hard_end: int,
    ) -> int:
        """优先在语义边界（场景转换/地点转换/段落）处切分，回退到标点。

        优先级：场景转换关键词 > 地点转换 > 段落边界 > 句子边界 > 硬截断
        """
        min_end = min(start + max(80, target_length // 2), hard_end)
        target_end = min(start + target_length, hard_end)

        # 搜索窗口内的候选切分点，记录 (位置, 优先级, 距离目标偏差)
        candidates: list[tuple[int, int, float]] = []
        # 优先级: 1=场景转换关键词, 2=地点转换, 3=段落边界, 4=句子边界

        # 1) 场景转换关键词（最高优先级）
        candidates.extend(
            cls._scene_transition_boundary_candidates(
                text,
                min_end=min_end,
                hard_end=hard_end,
                target_end=target_end,
            )
        )

        paragraph_boundary = cls._last_paragraph_boundary(text, min_end, hard_end)

        # 2) 地点转换（段落开头出现地点动词）
        if paragraph_boundary is not None:
            para_start = paragraph_boundary[0]
            para_text = text[para_start:hard_end]
            for verb in cls.LOCATION_TRANSITION_VERBS:
                if verb in para_text[:20]:
                    dist = abs(para_start - target_end)
                    candidates.append((para_start, 2, dist))

        # 3) 段落边界
        if paragraph_boundary is not None:
            para_pos, separator_len = paragraph_boundary
            dist = abs(para_pos - target_end)
            candidates.append((para_pos + separator_len, 3, dist))

        # 4) 句子边界
        candidates.extend(
            cls._sentence_boundary_candidates(
                text,
                min_end=min_end,
                hard_end=hard_end,
                target_end=target_end,
            )
        )

        # 按优先级排序，同优先级按距离
        if candidates:
            candidates.sort(key=lambda x: (x[1], x[2]))
            return candidates[0][0]

        # 无可用边界，硬截断到 target_end
        return min(target_end, hard_end)

    @staticmethod
    def _last_pattern_positions(
        text: str,
        patterns: list[str] | tuple[str, ...],
        min_end: int,
        hard_end: int,
    ) -> list[tuple[str, int]]:
        """Return one candidate per pattern: its last occurrence in the window."""
        positions: list[tuple[str, int]] = []
        for pattern in patterns:
            pos = text.rfind(pattern, min_end, hard_end)
            if pos >= min_end:
                positions.append((pattern, pos))
        return positions

    @classmethod
    def _scene_transition_boundary_candidates(
        cls,
        text: str,
        *,
        min_end: int,
        hard_end: int,
        target_end: int,
    ) -> list[tuple[int, int, float]]:
        return [
            (pos, 1, abs(pos - target_end))
            for _pattern, pos in cls._last_pattern_positions(
                text,
                cls.SCENE_TRANSITION_PATTERNS,
                min_end,
                hard_end,
            )
        ]

    @staticmethod
    def _last_paragraph_boundary(
        text: str,
        min_end: int,
        hard_end: int,
    ) -> tuple[int, int] | None:
        para_pos = text.rfind("\n\n", min_end, hard_end)
        if para_pos >= min_end:
            return para_pos, 2
        para_pos = text.rfind("\n", min_end, hard_end)
        if para_pos >= min_end:
            return para_pos, 1
        return None

    @classmethod
    def _sentence_boundary_candidates(
        cls,
        text: str,
        *,
        min_end: int,
        hard_end: int,
        target_end: int,
    ) -> list[tuple[int, int, float]]:
        return [
            (pos + 1, 4, abs(pos - target_end))
            for _punct, pos in cls._last_pattern_positions(
                text,
                ("。", "！", "？", "”", "」"),
                min_end,
                hard_end,
            )
        ]

    @staticmethod
    def _choose_cn_boundary(
        text: str,
        start: int,
        target_length: int,
        hard_end: int,
    ) -> int:
        min_end = min(start + max(80, target_length // 2), hard_end)
        target_end = min(start + target_length, hard_end)

        boundary_patterns = ("\n\n", "\r\n\r\n", "。", "！", "？", "”", "」", "\n")
        best = -1
        for pattern in boundary_patterns:
            pos = text.rfind(pattern, min_end, hard_end)
            if pos >= min_end:
                candidate = pos + len(pattern)
                if abs(candidate - target_end) < abs(best - target_end) or best < 0:
                    best = candidate
        if best > start:
            return best
        return hard_end

    def extract_summary(self, chunk_text: str, max_length: int = 200) -> str:
        """提取片段摘要

        取片段前若干字符作为摘要。

        Args:
            chunk_text: 片段文本
            max_length: 摘要最大长度

        Returns:
            摘要字符串
        """
        if len(chunk_text) <= max_length:
            return chunk_text
        return chunk_text[:max_length].rstrip() + "…"
