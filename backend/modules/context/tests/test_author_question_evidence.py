from modules.context.facade import compile_author_question_evidence


def test_author_question_evidence_budgets_and_hides_excluded_content() -> None:
    sources = [
        {
            "key": "page:a",
            "title": "甲",
            "content": "甲" * 1500,
            "source_hash": "a" * 64,
            "score": 1.0,
        },
        {
            "key": "page:b",
            "title": "乙",
            "content": "乙" * 1000,
            "source_hash": "b" * 64,
            "score": 0.9,
        },
    ]

    packet = compile_author_question_evidence(
        sources,
        max_sources=2,
        max_chars=2000,
    )

    assert [item["key"] for item in packet["included"]] == ["page:a", "page:b"]
    assert packet["trace"]["truncated_source_keys"] == ["page:b"]
    assert packet["trace"]["characters_used"] == 2000
    assert "content" not in str(packet["trace"]["excluded"])
