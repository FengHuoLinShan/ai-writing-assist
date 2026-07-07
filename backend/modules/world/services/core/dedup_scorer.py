"""中文实体去重多路信号计算器

解耦"同源信号重复加权"问题，提供 5+ 路独立异质信号：
- 字符形相似（rapidfuzz）
- 音似（pypinyin + Jaro-Winkler）
- 包含/子串
- 语义向量（pgvector cosine）
- 结构化特征（长度差异、行政区划前缀冲突）

Usage:
    scorer = DedupScorer()
    signals = scorer.compute_signals(
        "张三", "张三丰科技有限公司",
        candidate_aliases=["三丰"],
        semantic_cosine=0.72,
    )
    print(signals.substring_match)  # 1.0
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# 行政区划前缀 — 冲突时直接降权
_CN_ADMIN_PREFIXES: frozenset[str] = frozenset(
    {
        "北京",
        "上海",
        "天津",
        "重庆",
        "河北",
        "山西",
        "辽宁",
        "吉林",
        "黑龙江",
        "江苏",
        "浙江",
        "安徽",
        "福建",
        "江西",
        "山东",
        "河南",
        "湖北",
        "湖南",
        "广东",
        "海南",
        "四川",
        "贵州",
        "云南",
        "陕西",
        "甘肃",
        "青海",
        "台湾",
        "内蒙古",
        "广西",
        "西藏",
        "宁夏",
        "新疆",
        "香港",
        "澳门",
    }
)


@dataclass(frozen=True)
class DedupSignals:
    """去重决策用的异质信号向量。

    所有 float 字段范围 [0.0, 1.0]，值越大越相似。
    """

    rapidfuzz_ratio: float = 0.0
    """partial_ratio — 对中文简称/全称更友好"""

    rapidfuzz_token_sort: float = 0.0
    """token_sort_ratio — 对抗字序差异"""

    pinyin_jaro: float = 0.0
    """拼音 Jaro-Winkler — 同音不同字场景"""

    substring_match: float = 0.0
    """0.0=无包含, 0.5=单向包含, 1.0=双向包含/精确"""

    len_diff_ratio: float = 0.0
    """1.0 - min(1.0, abs(len_a - len_b) / max(len_a, len_b)) — 长度越接近越高"""

    semantic_cosine: float | None = None
    """语义向量余弦相似度，无向量时为 None"""

    pg_trgm_raw: float = 0.0
    """Python trigram Jaccard（模拟 pg_trgm similarity()），f9"""

    prefix_conflict: bool = False
    """True 表示行政区划前缀冲突（如北京 vs 上海）"""

    def to_vector(self) -> list[float]:
        """转为数值向量（供 ML 模型使用）。"""
        return [
            self.rapidfuzz_ratio,
            self.rapidfuzz_token_sort,
            self.pinyin_jaro,
            self.substring_match,
            self.len_diff_ratio,
            self.semantic_cosine if self.semantic_cosine is not None else 0.0,
            self.pg_trgm_raw,
        ]


class DedupScorer:
    """计算 query 与 candidate 之间的异质去重信号。"""

    def __init__(self) -> None:
        self._pinyin: Any | None = None
        self._rapidfuzz: Any | None = None
        self._jaro_winkler: Any | None = None
        self._pinyin_available = True
        self._jaro_winkler_available = True

    # ----------------------------------------------------------
    # lazy imports — 避免启动时加载 heavy C 扩展
    # ----------------------------------------------------------

    def _get_rapidfuzz(self) -> Any:
        if self._rapidfuzz is None:
            from rapidfuzz import fuzz

            self._rapidfuzz = fuzz
        return self._rapidfuzz

    def _get_pinyin(self) -> Any:
        if self._pinyin is None and self._pinyin_available:
            try:
                from pypinyin import lazy_pinyin

                self._pinyin = lazy_pinyin
            except Exception:
                logger.warning("pypinyin unavailable, pinyin signals will be 0")
                self._pinyin_available = False
        return self._pinyin

    def _get_jaro_winkler(self) -> Any:
        if self._jaro_winkler is None and self._jaro_winkler_available:
            try:
                from rapidfuzz.distance.JaroWinkler import similarity

                self._jaro_winkler = similarity
            except Exception:
                logger.warning("JaroWinkler unavailable, falling back to python")
                self._jaro_winkler_available = False
        return self._jaro_winkler

    # ----------------------------------------------------------
    # public API
    # ----------------------------------------------------------

    def compute_signals(
        self,
        query_name: str,
        candidate_name: str,
        candidate_aliases: list[str] | None = None,
        *,
        semantic_cosine: float | None = None,
    ) -> DedupSignals:
        """计算 query 与 candidate 的全量信号。

        Args:
            query_name: 查询名称（通常是候选实体名称）
            candidate_name: 候选目标名称（已有实体名称）
            candidate_aliases: 候选目标别名列表
            semantic_cosine: 预计算的语义余弦相似度（可选）

        Returns:
            DedupSignals — 冻结 dataclass，可安全缓存/哈希
        """
        q = query_name.strip().lower()
        c = candidate_name.strip().lower()

        if not q or not c:
            return DedupSignals(semantic_cosine=semantic_cosine)

        # 1. rapidfuzz 形相似
        rf = self._rapidfuzz_score(q, c)

        # 2. 拼音音似
        py = self._pinyin_score(q, c)

        # 3. 子串包含
        sub = self._substring_score(q, c, candidate_aliases)

        # 4. 长度差异
        len_ratio = self._len_diff_ratio(q, c)

        # 5. 行政区划前缀冲突
        prefix_conflict = self._prefix_conflict(q, c)

        # 6. trigram Jaccard（模拟 pg_trgm）
        trgm = self._trigram_score(q, c)

        return DedupSignals(
            rapidfuzz_ratio=rf["partial"],
            rapidfuzz_token_sort=rf["token_sort"],
            pinyin_jaro=py,
            substring_match=sub,
            len_diff_ratio=len_ratio,
            semantic_cosine=semantic_cosine,
            pg_trgm_raw=trgm,
            prefix_conflict=prefix_conflict,
        )

    # ----------------------------------------------------------
    # private signal calculators
    # ----------------------------------------------------------

    def _rapidfuzz_score(self, q: str, c: str) -> dict[str, float]:
        """返回 {partial: float, token_sort: float}，范围 [0, 1]。"""
        fuzz = self._get_rapidfuzz()
        if fuzz is None:
            return {"partial": 0.0, "token_sort": 0.0}

        partial = fuzz.partial_ratio(q, c, score_cutoff=0) / 100.0
        token_sort = fuzz.token_sort_ratio(q, c, score_cutoff=0) / 100.0
        return {"partial": round(partial, 4), "token_sort": round(token_sort, 4)}

    def _pinyin_score(self, q: str, c: str) -> float:
        """拼音 Jaro-Winkler 相似度，范围 [0, 1]。"""
        lazy_pinyin = self._get_pinyin()
        if lazy_pinyin is None:
            return 0.0

        try:
            q_py = "".join(lazy_pinyin(q))
            c_py = "".join(lazy_pinyin(c))
        except Exception:
            return 0.0

        if not q_py or not c_py:
            return 0.0

        jaro = self._get_jaro_winkler()
        if jaro is None:
            # fallback：简单字符重叠率
            return self._fallback_overlap(q_py, c_py)

        try:
            score = jaro(q_py, c_py, score_cutoff=0.0)
            # rapidfuzz.distance.JaroWinkler.similarity 返回 0.0-1.0
            if isinstance(score, (int, float)):
                return round(min(1.0, float(score)), 4)
            return 0.0
        except Exception:
            return self._fallback_overlap(q_py, c_py)

    @staticmethod
    def _substring_score(
        q: str,
        c: str,
        aliases: list[str] | None,
    ) -> float:
        """子串匹配评分。

        - 1.0 : q == c 或双向包含
        - 0.85: 单向包含（简称 ⊂ 全称）或顺序核心字匹配
        - 0.5 : 部分重叠（如共享核心词）
        - 0.0 : 无包含关系
        """
        if q == c:
            return 1.0

        # 双向包含
        if q in c and c in q:
            return 1.0

        # 单向包含（连续子串）
        if q in c or c in q:
            return 0.85

        # 顺序核心字匹配（如 "王五" ⊂ "王老五"，不要求连续）
        if DedupScorer._ordered_subsequence_match(q, c):
            return 0.85
        if DedupScorer._ordered_subsequence_match(c, q):
            return 0.85

        # 检查别名
        if aliases:
            for alias in aliases:
                a = alias.strip().lower()
                if not a:
                    continue
                if q == a or a == c:
                    return 1.0
                if q in a and a in q:
                    return 1.0
                if q in a or a in q:
                    return 0.85
                if c in a or a in c:
                    return 0.85
                if DedupScorer._ordered_subsequence_match(q, a):
                    return 0.85
                if DedupScorer._ordered_subsequence_match(a, q):
                    return 0.85

        # 核心词重叠（至少 2 个中文字共享）
        q_chars = set(q)
        c_chars = set(c)
        overlap = len(q_chars & c_chars)
        min_len = min(len(q_chars), len(c_chars))
        if min_len > 0 and overlap / min_len >= 0.5:
            return 0.5

        return 0.0

    @staticmethod
    def _ordered_subsequence_match(shorter: str, longer: str) -> bool:
        """检查 shorter 的所有字符是否按顺序出现在 longer 中（不要求连续）。

        例: "王五" 是 "王老五" 的顺序子序列（True）
            "王五" 是 "五老王" 的顺序子序列（False，顺序不对）
        """
        if len(shorter) > len(longer):
            return False
        if len(shorter) <= 1:
            return False  # 单字匹配太宽泛，不走此路径

        it = iter(longer)
        return all(ch in it for ch in shorter)

    @staticmethod
    def _trigram_score(q: str, c: str) -> float:
        """模拟 pg_trgm similarity()：名称前后各补 2 空格，3-gram 滑窗，Jaccard。

        返回值范围 [0.0, 1.0]。
        """

        def _normalize(name: str) -> str:
            return f"  {name.strip().lower()}  "

        def _grams(name: str) -> set[str]:
            n = _normalize(name)
            return {n[i : i + 3] for i in range(len(n) - 2)}

        gq = _grams(q)
        gc = _grams(c)
        if not gq and not gc:
            return 1.0
        union = len(gq | gc)
        if union == 0:
            return 0.0
        return round(len(gq & gc) / union, 4)

    @staticmethod
    def _len_diff_ratio(q: str, c: str) -> float:
        """长度差异归一化评分，越接近 1.0 表示长度越接近。"""
        len_q = len(q)
        len_c = len(c)
        max_len = max(len_q, len_c)
        if max_len == 0:
            return 1.0
        diff = abs(len_q - len_c)
        return round(1.0 - min(1.0, diff / max_len), 4)

    @staticmethod
    def _prefix_conflict(q: str, c: str) -> bool:
        """检查行政区划前缀是否冲突（如北京 vs 上海）。"""
        q_prefix = DedupScorer._extract_prefix(q)
        c_prefix = DedupScorer._extract_prefix(c)
        if q_prefix is None or c_prefix is None:
            return False
        if q_prefix == c_prefix:
            return False
        return True

    @staticmethod
    def _extract_prefix(name: str) -> str | None:
        """提取名称开头的行政区划前缀。"""
        for prefix in _CN_ADMIN_PREFIXES:
            if name.startswith(prefix):
                return prefix
        return None

    @staticmethod
    def _fallback_overlap(a: str, b: str) -> float:
        """无 JaroWinkler 时的回退：简单字符重叠率。"""
        if not a or not b:
            return 0.0
        sa, sb = set(a), set(b)
        inter = len(sa & sb)
        union = len(sa | sb)
        if union == 0:
            return 0.0
        return round(inter / union, 4)
