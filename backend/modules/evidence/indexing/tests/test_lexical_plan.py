"""S1 词法查询规划器契约（M1 契约 S1，M3 切片 2）。

钉住：语义输入原样保留、冻结名称优先、全查询总上限、跨句轮转公平性
（晚到输入不被前 N 截断挤掉）、确定性与规范化。
"""

from modules.evidence.indexing.lexical_plan import (
    DEFAULT_LEXICAL_TERM_CAP,
    LEXICAL_PLANNER_VERSION,
    build_lexical_query_plan,
    extract_index_terms,
    normalize_lexical_term,
)


def test_semantic_input_is_preserved_verbatim() -> None:
    query = "沈砚为什么把铜钥匙交给顾青梧？灯塔下面有什么？"
    plan = build_lexical_query_plan(query, frozen_terms=["沈砚"])

    assert plan.semantic_input == query
    assert plan.planner_version == LEXICAL_PLANNER_VERSION


def test_frozen_terms_take_priority_in_order() -> None:
    plan = build_lexical_query_plan(
        "继续剧情",
        frozen_terms=["雾渡港", "灯塔", "雾渡港", "x"],
    )

    assert plan.lexical_terms[:2] == ("雾渡港", "灯塔")
    assert plan.frozen_terms_used == ("雾渡港", "灯塔")


def test_total_cap_is_enforced_for_long_multi_sentence_queries() -> None:
    query = (
        "。".join(
            f"第{word}句话里埋着一条通往旧仓库的线索" for word in "甲乙丙丁戊己庚辛"
        )
        + "。"
    )
    plan = build_lexical_query_plan(query)

    assert len(plan.lexical_terms) <= DEFAULT_LEXICAL_TERM_CAP
    assert len(plan.lexical_terms) == len(set(plan.lexical_terms))
    assert plan.sentence_count == 8


def test_round_robin_keeps_late_sentences_recalled() -> None:
    # 首句单独即可填满 cap=6；轮转保证五句每句至少贡献一个词项。
    query = (
        "沈砚在雾渡港灯塔下的旧仓库里找到了铜钥匙打开了尘封多年的铁盒子。"
        "继续。甲说走。乙说等。藏宝图在哪里。"
    )
    plan = build_lexical_query_plan(query, cap=6)

    assert len(plan.lexical_terms) == 6
    assert "藏宝" in plan.lexical_terms  # 最后一句仍有词项入选
    # 前面各短句也各有一席，而不是首句独占。
    for fragment in ("沈砚", "继续", "甲说", "乙说"):
        assert any(term.startswith(fragment) for term in plan.lexical_terms), fragment


def test_deterministic_and_normalized() -> None:
    query = "Where is the Lighthouse？沈砚 的铜钥匙"
    plan_a = build_lexical_query_plan(query, frozen_terms=["沈砚"])
    plan_b = build_lexical_query_plan(query, frozen_terms=["沈砚"])

    assert plan_a == plan_b
    assert "lighthouse" in plan_a.lexical_terms
    assert normalize_lexical_term("Ｌｉｇｈｔｈｏｕｓｅ ") == "lighthouse"


def test_duplicate_sentences_do_not_duplicate_terms() -> None:
    query = "灯塔下有旧仓库。灯塔下有旧仓库。"
    plan = build_lexical_query_plan(query)

    assert len(plan.lexical_terms) == len(set(plan.lexical_terms))


def test_empty_query_falls_back_to_frozen_terms_only() -> None:
    plan = build_lexical_query_plan("   ", frozen_terms=["灯塔"])

    assert plan.lexical_terms == ("灯塔",)
    assert plan.sentence_count == 0
    assert plan.frozen_terms_used == ("灯塔",)


def test_zero_cap_yields_no_terms() -> None:
    plan = build_lexical_query_plan("灯塔在哪里", frozen_terms=["灯塔"], cap=0)

    assert plan.lexical_terms == ()
    assert plan.cap == 0


def test_extract_index_terms_keeps_full_grams_without_query_cap() -> None:
    text = "沈砚在雾渡港灯塔下的旧仓库里找到了铜钥匙。"

    terms = extract_index_terms(text)

    assert "沈砚" in terms and "铜钥匙" in terms
    # 索引侧不套查询侧上限：长段的 2–4 字 n-gram 完整保留
    run_grams = [t for t in terms if len(t) >= 2 and all("一" <= c <= "鿿" for c in t)]
    assert len(run_grams) > 30
    assert len(terms) == len(set(terms))


def test_extract_index_terms_includes_english_and_normalizes() -> None:
    terms = extract_index_terms("Lighthouse 的秘密 Where is it")

    assert "lighthouse" in terms
    assert "where" in terms
    assert "秘密" in terms


def test_extract_index_terms_empty_text() -> None:
    assert extract_index_terms("") == []
    assert extract_index_terms("   ") == []
