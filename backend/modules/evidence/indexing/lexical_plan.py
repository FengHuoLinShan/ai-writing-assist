"""S1 词法查询规划：完整语义输入与全查询有界词项分离（M1 契约 S1）。

语义输入保持调用方原样（喂 embedding）；词法词项按整条请求总上限生成：
冻结名称/别名优先，其余按句子轮转取词，保证较晚输入仍有召回机会，
不做简单前 N 截断。纯确定性函数，无 LLM、无数据库访问。

规划结果进入切片 3 的材料 key（`planner_version` 参与）；词法召回行为
变化时必须 bump 版本。契约见
``docs/plans/2026-10-07-rp-retrieval-refactor-m1-contract.md`` §2。
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

LEXICAL_PLANNER_VERSION = "lexical-plan-v1"

DEFAULT_LEXICAL_TERM_CAP = 64
"""全查询词项总上限（设计 §3 建议从 64 起对照校准）。"""

_MAX_CN_RUN_GRAMS = 12
"""单个连续中文段贡献的 n-gram 上限；更长的段按等距确定采样。"""

_SENTENCE_SPLIT_RE = re.compile(r"[。！？!?；;\n]+")
_WORD_RE = re.compile(r"[a-z0-9][a-z0-9'-]{1,}")
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")


@dataclass(frozen=True)
class LexicalQueryPlan:
    """S1 输出：语义输入与有界词法词项。"""

    semantic_input: str
    """完整语义输入，原样保留供 embedding 与材料 key 使用"""
    lexical_terms: tuple[str, ...]
    """有界、去重、按确定次序的词项（冻结名称优先，其后跨句轮转）"""
    cap: int
    planner_version: str
    sentence_count: int
    frozen_terms_used: tuple[str, ...]
    """实际纳入词项的冻结名称/别名（诊断与 D7 对照用）"""


def normalize_lexical_term(value: str) -> str:
    """NFKC 归一、去空白、小写；词法词项的统一规范形式。"""

    compact = "".join(str(value or "").split())
    return unicodedata.normalize("NFKC", compact).lower()


def _cn_run_grams(run: str, *, cap: int | None = _MAX_CN_RUN_GRAMS) -> list[str]:
    """连续中文段的 2–4 字 n-gram；超限段按等距确定采样到上限。

    ``cap=None`` 供索引侧使用：文档词项不套查询侧上限，否则会永久丢失
    后部命中（设计 §4）；代价（索引体积/写入耗时）由 2d 实测校准。
    """

    grams: list[str] = []
    for size in range(2, min(4, len(run)) + 1):
        for idx in range(len(run) - size + 1):
            grams.append(run[idx : idx + size])
    if cap is not None and len(grams) > cap:
        last = len(grams) - 1
        grams = [grams[round(index * last / (cap - 1))] for index in range(cap)]
    return grams


def extract_index_terms(text: str) -> list[str]:
    """索引侧词项：整段正文的完整中文 2–4 字 n-gram 与英文词。

    写入 ``rag_chunks.lexical_terms``（PG TEXT[] + GIN / SQLite JSON）；
    与查询侧共用规范化形式，保证两侧词项可交集命中。去重保序、确定。
    """

    compact = normalize_lexical_term(text)
    if not compact:
        return []
    spaced = unicodedata.normalize("NFKC", str(text or "")).lower()
    terms: list[str] = list(_WORD_RE.findall(spaced))
    for run in _CJK_RUN_RE.findall(compact):
        terms.extend(_cn_run_grams(run, cap=None))
    return list(dict.fromkeys(term for term in terms if len(term) >= 2))


def _sentence_terms(sentence: str, frozen_normalized: dict[str, str]) -> list[str]:
    """单句词项：冻结命中 → 英文词 → 中文 n-gram，句内有序、去重。"""

    compact = normalize_lexical_term(sentence)
    terms: list[str] = []

    for term in frozen_normalized:
        if term and term in compact:
            terms.append(term)

    # 英文词从保留空格的原句提取；紧缩形式会破坏词边界。
    spaced = unicodedata.normalize("NFKC", sentence).lower()
    terms.extend(_WORD_RE.findall(spaced))

    for run in _CJK_RUN_RE.findall(compact):
        terms.extend(_cn_run_grams(run))

    return list(dict.fromkeys(term for term in terms if len(term) >= 2))


def build_lexical_query_plan(
    query: str,
    *,
    frozen_terms: Iterable[str] = (),
    cap: int = DEFAULT_LEXICAL_TERM_CAP,
) -> LexicalQueryPlan:
    """按整条请求规划有界词项；同输入必得同输出。"""

    cap = max(0, int(cap))
    frozen_ordered: list[str] = []
    frozen_normalized: dict[str, str] = {}
    for raw in frozen_terms:
        normalized = normalize_lexical_term(raw)
        if len(normalized) < 2 or normalized in frozen_normalized:
            continue
        frozen_normalized[normalized] = normalized
        frozen_ordered.append(normalized)
    if not str(query or "").strip() and not frozen_ordered:
        return LexicalQueryPlan(
            semantic_input=str(query or ""),
            lexical_terms=(),
            cap=cap,
            planner_version=LEXICAL_PLANNER_VERSION,
            sentence_count=0,
            frozen_terms_used=(),
        )

    selected: list[str] = []
    selected_set: set[str] = set()

    def take(term: str) -> None:
        if len(selected) >= cap or term in selected_set:
            return
        selected.append(term)
        selected_set.add(term)

    for term in frozen_ordered:
        take(term)
    frozen_used = tuple(selected)

    sentences = [
        part.strip()
        for part in _SENTENCE_SPLIT_RE.split(str(query or ""))
        if part.strip()
    ]
    sentence_lists = [
        _sentence_terms(sentence, frozen_normalized) for sentence in sentences
    ]

    # 跨句轮转：每轮各句取一个新词，直到总上限，晚到输入不会永远排不上。
    cursors = [0] * len(sentence_lists)
    progressed = True
    while len(selected) < cap and progressed:
        progressed = False
        for index, terms in enumerate(sentence_lists):
            while cursors[index] < len(terms) and terms[cursors[index]] in selected_set:
                cursors[index] += 1
            if cursors[index] < len(terms):
                take(terms[cursors[index]])
                cursors[index] += 1
                progressed = True
            if len(selected) >= cap:
                break

    return LexicalQueryPlan(
        semantic_input=str(query or ""),
        lexical_terms=tuple(selected),
        cap=cap,
        planner_version=LEXICAL_PLANNER_VERSION,
        sentence_count=len(sentences),
        frozen_terms_used=frozen_used,
    )
